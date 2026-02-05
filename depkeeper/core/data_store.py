"""Centralized PyPI data store for depkeeper.

Provides a unified, async-safe cache for PyPI package metadata so that
``VersionChecker`` and ``DependencyAnalyzer`` share a single HTTP fetch
per package.  All public helpers on :class:`PyPIDataStore` are either
``async`` (may trigger a network round-trip) or synchronous accessors
that return only what has already been cached.

Typical usage::

    from depkeeper.utils.http import HTTPClient
    from depkeeper.data_store import PyPIDataStore

    async with HTTPClient() as client:
        store = PyPIDataStore(client)
        data  = await store.get_package_data("requests")
        print(data.latest_version)          # e.g. "2.31.0"
        print(data.all_versions[:3])        # newest-first, no pre-releases
"""

from __future__ import annotations

import sys
import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from packaging.version import InvalidVersion, Version, parse
from packaging.specifiers import InvalidSpecifier, SpecifierSet

from depkeeper.exceptions import PyPIError
from depkeeper.utils.http import HTTPClient
from depkeeper.utils.logger import get_logger
from depkeeper.constants import PYPI_JSON_API

logger = get_logger("data_store")

# Public API
__all__ = ["PyPIDataStore", "PyPIPackageData"]


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------


@dataclass
class PyPIPackageData:
    """Immutable-by-convention snapshot of one PyPI package.

    Populated once by :pymeth:`PyPIDataStore._parse_package_data` and then
    shared across every caller that requests the same package.  All
    mutable collections use ``field(default_factory=…)`` so that each
    instance owns its own lists / dicts.

    Attributes:
        name: Normalised package name (lower-case, hyphens).
        latest_version: Version string reported by PyPI ``info.version``.
        latest_requires_python: ``requires_python`` marker for *latest*.
        latest_dependencies: Base (non-extra) deps of *latest*.
        all_versions: Stable (non-pre-release) versions, newest first.
        parsed_versions: Every version that could be parsed, as
            ``(raw_str, Version)`` pairs sorted descending.
        python_requirements: Maps version string → its ``requires_python``
            specifier (or ``None`` when the upload omits it).
        releases: Raw ``releases`` dict from the PyPI JSON response.
        dependencies_cache: Lazily populated per-version dependency lists;
            seeded with *latest* on construction.
    """

    name: str
    latest_version: Optional[str] = None
    latest_requires_python: Optional[str] = None
    latest_dependencies: List[str] = field(default_factory=list)

    all_versions: List[str] = field(default_factory=list)
    parsed_versions: List[Tuple[str, Version]] = field(default_factory=list)

    python_requirements: Dict[str, Optional[str]] = field(default_factory=dict)
    releases: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)

    dependencies_cache: Dict[str, List[str]] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_versions_in_major(self, major: int) -> List[str]:
        """Return stable versions that share a given major number.

        Pre-releases and versions whose ``release`` tuple is empty are
        skipped.

        Args:
            major: The major version number to filter on (e.g. ``2``).

        Returns:
            Version strings in descending order (inherits the sort order
            of :pyattr:`parsed_versions`).

        Example::

            >>> data.parsed_versions  # imagine already populated
            [("3.1.0", Version("3.1.0")), ("2.7.18", Version("2.7.18")), ...]
            >>> data.get_versions_in_major(2)
            ['2.7.18', ...]
        """
        result: List[str] = []

        for version_str, parsed in self.parsed_versions:
            if parsed.is_prerelease:
                continue
            # release is a tuple like (major, minor, micro); guard against empty
            if parsed.release and parsed.release[0] == major:
                result.append(version_str)

        return result

    def is_python_compatible(
        self,
        version: str,
        python_version: str,
    ) -> bool:
        """Check whether a package version supports a given Python version.

        Returns ``True`` when the package omits ``requires_python`` or when
        parsing the specifier fails — matching pip's own permissive
        behaviour.

        Args:
            version: Package version string, e.g. ``"1.4.2"``.
            python_version: Dot-separated Python version, e.g.
                ``"3.11.2"``.

        Returns:
            ``True`` if *python_version* satisfies the package's
            ``requires_python`` constraint (or if the constraint is absent /
            unparseable).

        Example::

            >>> data.python_requirements["1.4.2"] = ">=3.7"
            >>> data.is_python_compatible("1.4.2", "3.11.2")
            True
            >>> data.is_python_compatible("1.4.2", "2.7.18")
            False
        """
        requires_python = self.python_requirements.get(version)

        # No constraint recorded → treat as compatible (mirrors pip)
        if not requires_python:
            return True

        try:
            return python_version in SpecifierSet(requires_python)
        except InvalidSpecifier:
            # Malformed specifier → be permissive
            return True

    def get_python_compatible_versions(
        self,
        python_version: str,
        major: Optional[int] = None,
    ) -> List[str]:
        """Return stable versions compatible with *python_version*.

        Optionally restrict results to a single major version.  Versions
        are returned in descending order.

        Args:
            python_version: Dot-separated Python version to check against,
                e.g. ``"3.10.0"``.
            major: If provided, only versions with this major number are
                included.

        Returns:
            Filtered, descending list of version strings.

        Example::

            >>> data.get_python_compatible_versions("3.9.7", major=2)
            ['2.7.18', '2.7.16']
        """
        result: List[str] = []

        for version_str, parsed in self.parsed_versions:
            if parsed.is_prerelease:
                continue

            # Major-version gate (skipped when major is None)
            if major is not None:
                if not parsed.release or parsed.release[0] != major:
                    continue

            if self.is_python_compatible(version_str, python_version):
                result.append(version_str)

        return result


# ---------------------------------------------------------------------------
# Async data-store with double-checked locking
# ---------------------------------------------------------------------------


class PyPIDataStore:
    """Async-safe, per-process cache for PyPI package metadata.

    Each unique (normalised) package name triggers **at most one** HTTP
    request to ``/pypi/{pkg}/json``.  A :class:`asyncio.Semaphore`
    limits concurrent outbound fetches, and a double-checked lock inside
    the semaphore prevents thundering-herd duplicates when several
    coroutines request the same package simultaneously.

    Args:
        http_client: A pre-configured :class:`HTTPClient` instance (owns
            connection pool / session).
        concurrent_limit: Maximum number of PyPI fetches that may be
            in-flight at once.  Defaults to ``10``.

    Example::

        async with HTTPClient() as client:
            store = PyPIDataStore(client, concurrent_limit=5)

            # warm the cache for several packages at once
            await store.prefetch_packages(["flask", "click", "jinja2"])

            # subsequent calls return instantly from cache
            flask = await store.get_package_data("flask")
            print(flask.latest_version)
    """

    def __init__(
        self,
        http_client: HTTPClient,
        concurrent_limit: int = 10,
    ) -> None:
        self.http_client = http_client
        self._semaphore = asyncio.Semaphore(concurrent_limit)

        # Primary cache: normalised name → parsed package snapshot
        self._package_data: Dict[str, PyPIPackageData] = {}

        # Secondary cache: "name==version" → dependency list (avoids
        # repeated per-version fetches even after the main cache is warm)
        self._version_deps_cache: Dict[str, List[str]] = {}

    # ------------------------------------------------------------------
    # Public async accessors
    # ------------------------------------------------------------------

    async def get_package_data(self, name: str) -> PyPIPackageData:
        """Fetch (or return cached) metadata for *name*.

        Uses double-checked locking: the first check is lock-free; if the
        package is missing a second check runs *inside* the semaphore so
        that only one coroutine actually performs the HTTP call.

        Args:
            name: PyPI package name (any casing / underscore style).

        Returns:
            A :class:`PyPIPackageData` populated from the latest PyPI
            JSON response.

        Raises:
            PyPIError: The package does not exist on PyPI or the API
                returned an unexpected status code.

        Example::

            >>> data = await store.get_package_data("Requests")
            >>> data.name
            'requests'
            >>> data.latest_version
            '2.31.0'
        """
        normalized = _normalize(name)

        # Fast path — already cached (no lock needed)
        if normalized in self._package_data:
            return self._package_data[normalized]

        async with self._semaphore:
            # Second check — another coroutine may have populated while we waited
            if normalized in self._package_data:
                return self._package_data[normalized]

            data = await self._fetch_from_pypi(name)
            pkg_data = self._parse_package_data(name, data)
            self._package_data[normalized] = pkg_data
            return pkg_data

    async def prefetch_packages(self, names: List[str]) -> None:
        """Concurrently warm the cache for a batch of packages.

        Errors for individual packages are silenced so that one bad
        package name does not prevent the rest from being cached.

        Args:
            names: Package names to prefetch.

        Example::

            >>> await store.prefetch_packages(["numpy", "pandas", "scipy"])
            # subsequent get_package_data calls for these return instantly
        """
        await asyncio.gather(
            *(self.get_package_data(name) for name in names),
            return_exceptions=True,  # swallow per-package failures
        )

    async def get_version_dependencies(
        self,
        name: str,
        version: str,
    ) -> List[str]:
        """Return the base dependencies for a specific version of *name*.

        Resolution order (fastest first):

        1. Per-version dependency cache (``_version_deps_cache``).
        2. Already-populated fields inside the cached
           :class:`PyPIPackageData` (``latest_dependencies`` or
           ``dependencies_cache``).
        3. A targeted ``/pypi/{name}/{version}/json`` fetch, guarded by
           the semaphore and a second cache check.

        Args:
            name: Package name.
            version: Exact version string, e.g. ``"1.2.3"``.

        Returns:
            List of PEP-508 dependency specifiers with extras and
            environment markers stripped.

        Example::

            >>> deps = await store.get_version_dependencies("flask", "2.3.0")
            >>> deps
            ['Werkzeug>=2.0', 'Jinja2>=3.0', ...]
        """
        normalized = _normalize(name)
        cache_key = f"{normalized}=={version}"

        # ── layer 1: flat version-deps cache ──────────────────────────
        if cache_key in self._version_deps_cache:
            return self._version_deps_cache[cache_key]

        # ── layer 2: already inside PyPIPackageData ────────────────────
        pkg_data = self._package_data.get(normalized)
        if pkg_data:
            if version == pkg_data.latest_version:
                self._version_deps_cache[cache_key] = pkg_data.latest_dependencies
                return pkg_data.latest_dependencies

            if version in pkg_data.dependencies_cache:
                deps = pkg_data.dependencies_cache[version]
                self._version_deps_cache[cache_key] = deps
                return deps

        # ── layer 3: network fetch (double-checked) ────────────────────
        async with self._semaphore:
            if cache_key in self._version_deps_cache:
                return self._version_deps_cache[cache_key]

            deps = await self._fetch_version_dependencies(name, version)
            self._version_deps_cache[cache_key] = deps

            # Back-fill the package-level cache so future reads skip this path
            if pkg_data:
                pkg_data.dependencies_cache[version] = deps

            return deps

    # ------------------------------------------------------------------
    # Public synchronous accessors (cache-only, no I/O)
    # ------------------------------------------------------------------

    def get_cached_package(self, name: str) -> Optional[PyPIPackageData]:
        """Return cached data for *name* without triggering a fetch.

        Args:
            name: Package name (any casing / underscore style).

        Returns:
            The cached :class:`PyPIPackageData`, or ``None`` if the
            package has not been fetched yet.

        Example::

            >>> store.get_cached_package("flask")  # after a prior fetch
            PyPIPackageData(name='flask', latest_version='3.0.0', ...)
            >>> store.get_cached_package("unknown")
            None
        """
        return self._package_data.get(_normalize(name))

    def get_versions(self, name: str) -> List[str]:
        """Return cached stable versions for *name* (newest first).

        Returns an empty list when *name* has not been fetched yet.

        Args:
            name: Package name.

        Returns:
            List of version strings, or ``[]``.

        Example::

            >>> store.get_versions("flask")
            ['3.0.0', '2.3.3', '2.3.2', ...]
        """
        pkg = self.get_cached_package(name)
        return pkg.all_versions if pkg else []

    def is_python_compatible(
        self,
        name: str,
        version: str,
        python_version: str,
    ) -> bool:
        """Check Python compatibility using only cached metadata.

        Returns ``True`` when the package has not been fetched yet — the
        caller should :pymeth:`get_package_data` first if a definitive
        answer is needed.

        Args:
            name: Package name.
            version: Package version string.
            python_version: Dot-separated Python version.

        Returns:
            Compatibility flag (see :pymeth:`PyPIPackageData.is_python_compatible`).

        Example::

            >>> store.is_python_compatible("flask", "3.0.0", "3.11.2")
            True
        """
        pkg = self.get_cached_package(name)
        return pkg.is_python_compatible(version, python_version) if pkg else True

    # ------------------------------------------------------------------
    # Network helpers (private)
    # ------------------------------------------------------------------

    async def _fetch_from_pypi(self, name: str) -> Dict[str, Any]:
        """Hit ``/pypi/{name}/json`` and return the raw JSON body.

        Raises:
            PyPIError: On 404 (package not found) or any non-200 status.
        """
        url = PYPI_JSON_API.format(package=name)
        response = await self.http_client.get(url)

        if response.status_code == 404:
            raise PyPIError(
                f"Package '{name}' not found on PyPI",
                package_name=name,
            )
        if response.status_code != 200:
            raise PyPIError(
                f"PyPI returned status {response.status_code} for '{name}'",
                package_name=name,
            )

        return response.json()

    async def _fetch_version_dependencies(
        self,
        name: str,
        version: str,
    ) -> List[str]:
        """Hit ``/pypi/{name}/{version}/json`` and extract base deps.

        Any network or parsing error is caught and logged at DEBUG level;
        an empty list is returned so that one broken version does not
        break the whole analysis.
        """
        url = f"https://pypi.org/pypi/{name}/{version}/json"

        try:
            response = await self.http_client.get(url)
            if response.status_code != 200:
                return []

            info = response.json().get("info", {})
            return self._extract_dependencies(info)

        except Exception as exc:  # noqa: BLE001 — intentional broad catch
            logger.debug(
                "Error fetching deps for %s==%s: %s",
                name,
                version,
                exc,
            )
            return []

    # ------------------------------------------------------------------
    # Parsing helpers (private, synchronous)
    # ------------------------------------------------------------------

    def _parse_package_data(
        self,
        name: str,
        data: Dict[str, Any],
    ) -> PyPIPackageData:
        """Transform a raw PyPI JSON response into :class:`PyPIPackageData`.

        Filters out versions that cannot be parsed by ``packaging`` and
        those with no associated file uploads.  The resulting
        ``parsed_versions`` list is sorted descending so that callers can
        rely on index-0 being the newest parseable version.
        """
        info = data.get("info", {})
        releases = data.get("releases", {})

        latest_version: Optional[str] = info.get("version")
        latest_requires_python: Optional[str] = info.get("requires_python")
        latest_deps: List[str] = self._extract_dependencies(info)

        parsed_versions: List[Tuple[str, Version]] = []
        python_requirements: Dict[str, Optional[str]] = {}

        for version_str, files in releases.items():
            # Skip phantom versions that have no uploaded files
            if not files:
                continue

            try:
                parsed = parse(version_str)
            except InvalidVersion:
                # Non-PEP-440 tags (e.g. "1.0-alpha") — silently skip
                continue

            parsed_versions.append((version_str, parsed))

            # Pull requires_python from the first file that declares it;
            # most releases are uniform, so iterating once is sufficient.
            for file_info in files:
                if file_info.get("requires_python"):
                    python_requirements[version_str] = file_info["requires_python"]
                    break
            else:
                # for/else: no file had requires_python → record None
                python_requirements[version_str] = None

        # Descending sort so index 0 == newest
        parsed_versions.sort(key=lambda x: x[1], reverse=True)

        # Public version list excludes pre-releases
        all_versions: List[str] = [v for v, p in parsed_versions if not p.is_prerelease]

        return PyPIPackageData(
            name=_normalize(name),
            latest_version=latest_version,
            latest_requires_python=latest_requires_python,
            latest_dependencies=latest_deps,
            all_versions=all_versions,
            parsed_versions=parsed_versions,
            python_requirements=python_requirements,
            releases=releases,
            # Seed the per-version dep cache with what we already know
            dependencies_cache=(
                {latest_version: latest_deps} if latest_version else {}
            ),
        )

    @staticmethod
    def _extract_dependencies(info: Dict[str, Any]) -> List[str]:
        """Pull base (non-extra) dependency specifiers from ``info``.

        ``requires_dist`` entries that belong to an *extra* group contain
        a ``; extra == "…"`` marker and are stripped here.  The
        environment-marker portion after the first ``;`` is also removed
        so callers get clean PEP-508 name+version specs.

        Args:
            info: The ``info`` sub-dict from a PyPI JSON response.

        Returns:
            List of strings like ``["requests>=2.25", "click"]``.
        """
        requires_dist: List[str] = info.get("requires_dist") or []
        deps: List[str] = []

        for dep in requires_dist:
            # Extra-conditional dependencies are out of scope
            if "extra==" in dep or "extra ==" in dep:
                continue

            # Strip environment markers (everything after the first ";")
            base = dep.split(";")[0].strip()
            if base:
                deps.append(base)

        return deps

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def get_current_python_version() -> str:
        """Return the running interpreter's version as ``"major.minor.micro"``.

        Example::

            >>> PyPIDataStore.get_current_python_version()
            '3.11.4'
        """
        return (
            f"{sys.version_info.major}."
            f"{sys.version_info.minor}."
            f"{sys.version_info.micro}"
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _normalize(name: str) -> str:
    """Normalise a package name to lower-case with hyphens.

    Matches the canonicalisation rule used by PyPI so that
    ``"My_Package"`` and ``"my-package"`` map to the same cache key.

    Args:
        name: Raw package name.

    Returns:
        Normalised name string.

    Example::

        >>> _normalize("Flask_Login")
        'flask-login'
    """
    return name.lower().replace("_", "-")
