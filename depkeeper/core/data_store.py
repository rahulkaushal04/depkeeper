"""Centralized PyPI data store for depkeeper.

Provides a unified, async-safe cache for PyPI package metadata so that
``VersionChecker`` and ``DependencyAnalyzer`` share a single HTTP fetch
per package.  All public helpers on `PyPIDataStore` are either
``async`` (may trigger a network round-trip) or synchronous accessors
that return only what has already been cached.

Typical usage::

    from depkeeper.utils.http import HTTPClient
    from depkeeper.core.data_store import PyPIDataStore

    async with HTTPClient() as client:
        store = PyPIDataStore(client)
        data  = await store.get_package_data("requests")
        print(data.latest_version)          # e.g. "2.31.0"
        print(data.all_versions[:3])        # newest-first, no pre-releases
"""

from __future__ import annotations

import sys
import re
import asyncio
from datetime import datetime, timezone
from urllib.parse import quote
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple, TypeVar

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version, parse
from packaging.specifiers import InvalidSpecifier, SpecifierSet

from depkeeper.exceptions import PyPIError
from depkeeper.utils.http import HTTPClient
from depkeeper.utils.logger import get_logger
from depkeeper.utils.naming import normalize_package_name
from depkeeper.constants import PYPI_JSON_API

logger = get_logger("data_store")

__all__ = ["PyPIDataStore", "PyPIPackageData"]

_T = TypeVar("_T")


@dataclass
class PyPIPackageData:
    """Snapshot of one PyPI package, shared by every caller (treat as read-only).

    Attributes:
        name: Normalized package name (lower-case, hyphens).
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

    #: Earliest file upload time per version (UTC); ``None`` when PyPI omits or
    #: garbles it. Missing entries mean "unknown" and are treated as old.
    upload_times: Dict[str, Optional[datetime]] = field(default_factory=dict)

    #: PyPI ``info.project_urls`` (label -> URL) plus ``home_page`` under the
    #: key ``"Homepage"`` when no such label exists. Only http(s) URLs kept.
    project_urls: Dict[str, str] = field(default_factory=dict)

    def release_links(self) -> Dict[str, str]:
        """Return changelog, release-notes and homepage links from ``project_urls``.

        Keys are ``"changelog"``, ``"release_notes"`` and ``"homepage"``; kinds
        with no matching label are omitted.
        """
        wanted = {
            "changelog": (
                "changelog",
                "change log",
                "changes",
                "history",
                "news",
                "what's new",
            ),
            "release_notes": (
                "release notes",
                "releases",
                "release",
                "release history",
            ),
            "homepage": (
                "homepage",
                "home",
                "home page",
                "website",
                "source",
                "repository",
            ),
        }
        lowered = {k.strip().lower(): v for k, v in self.project_urls.items()}
        links: Dict[str, str] = {}
        for kind, labels in wanted.items():
            for label in labels:
                if label in lowered:
                    links[kind] = lowered[label]
                    break
        return links

    def get_versions_in_major(self, major: int) -> List[str]:
        """Return stable versions that share a given major number.

        Pre-releases and versions whose ``release`` tuple is empty are
        skipped.

        Args:
            major: The major version number to filter on (e.g. ``2``).

        Returns:
            Version strings in descending order (inherits the sort order
            of `parsed_versions`).
        """
        result: List[str] = []

        for version_str, parsed in self.parsed_versions:
            if parsed.is_prerelease:
                continue
            # `release` can be empty (e.g. epoch-only tags).
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
        behavior.

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

        if not requires_python or not isinstance(requires_python, str):
            return True

        try:
            return SpecifierSet(requires_python).contains(
                python_version, prereleases=True
            )
        except InvalidSpecifier:
            # Malformed upstream metadata must not exclude a release.
            return True

    def get_python_compatible_versions(
        self,
        python_version: str,
        major: Optional[int] = None,
        include_prereleases: bool = False,
    ) -> List[str]:
        """Return stable versions compatible with *python_version*.

        Optionally restrict results to a single major version.  Versions
        are returned in descending order.

        Args:
            python_version: Dot-separated Python version to check against,
                e.g. ``"3.10.0"``.
            major: If provided, only versions with this major number are
                included.
            include_prereleases: Also return pre-releases (per-package
                ``allow_prerelease`` policy).

        Returns:
            Filtered, descending list of version strings.
        """
        result: List[str] = []

        for version_str, parsed in self.parsed_versions:
            if parsed.is_prerelease and not include_prereleases:
                continue

            if major is not None:
                if not parsed.release or parsed.release[0] != major:
                    continue

            if self.is_python_compatible(version_str, python_version):
                result.append(version_str)

        return result


class PyPIDataStore:
    """Async-safe, per-process cache for PyPI package metadata.

    Each unique (normalized) package name triggers **at most one**
    concurrent HTTP request to ``/pypi/{pkg}/json``.  Two independent
    mechanisms cooperate:

    * a **per-key in-flight map** coalesces callers that ask for the same
      package (or the same ``name==version`` dependency list) while a
      fetch is already running — the first caller performs the request and
      every later caller awaits its result;
    * a `asyncio.Semaphore` caps how many *distinct* fetches may be
      outbound at once.

    A counting semaphore alone cannot deduplicate: it admits
    ``concurrent_limit`` coroutines simultaneously, so a re-check inside it
    is not mutually exclusive.  Waiters coalesced by the in-flight map do
    **not** consume a semaphore slot.

    Failures are never cached.  Once a fetch fails, its in-flight entry is
    dropped so that a later call re-attempts the request (transient network
    errors must stay recoverable).

    Args:
        http_client: A pre-configured `HTTPClient` instance (owns
            connection pool / session).
        concurrent_limit: Maximum number of PyPI fetches that may be
            in-flight at once.  Defaults to ``10``.
        target_python: ``"X.Y"`` Python the dependency environment markers
            (``python_version`` / ``python_full_version``) are evaluated
            for.  ``None`` (or an unusable value) means the running
            interpreter.  It is fixed for the store's lifetime, so the
            per-store dependency caches never mix targets.

    Raises:
        ValueError: *concurrent_limit* is less than ``1`` (a limit of zero
            would deadlock every fetch).

    Example::

        async with HTTPClient() as client:
            store = PyPIDataStore(client, concurrent_limit=5)

            await store.prefetch_packages(["flask", "click", "jinja2"])

            flask = await store.get_package_data("flask")
            print(flask.latest_version)
    """

    def __init__(
        self,
        http_client: HTTPClient,
        concurrent_limit: int = 10,
        target_python: Optional[str] = None,
    ) -> None:
        if concurrent_limit < 1:
            raise ValueError(f"concurrent_limit must be >= 1, got {concurrent_limit}")

        # Only Python-version markers change; platform markers stay the host's.
        self._marker_env: Dict[str, str] = {"extra": ""}
        match = re.match(r"\s*([0-9]+)\.([0-9]+)", target_python or "")
        if match:
            xy = f"{match.group(1)}.{match.group(2)}"
            self._marker_env["python_version"] = xy
            self._marker_env["python_full_version"] = f"{xy}.0"

        self.http_client = http_client
        self._semaphore = asyncio.Semaphore(concurrent_limit)

        self._package_data: Dict[str, PyPIPackageData] = {}

        # "name==version" -> dependency list
        self._version_deps_cache: Dict[str, List[str]] = {}

        # "name==version" -> sorted sha256 hex digests (successes only)
        self._digests_cache: Dict[str, List[str]] = {}

        # Entries live only while a fetch is running (see _coalesce).
        self._inflight_packages: Dict[str, "asyncio.Task[PyPIPackageData]"] = {}
        self._inflight_version_deps: Dict[str, "asyncio.Task[List[str]]"] = {}

    async def get_package_data(self, name: str) -> PyPIPackageData:
        """Fetch (or return cached) metadata for *name*.

        Cached entries are returned without awaiting anything.  Otherwise
        the call is *coalesced*: the first caller starts the fetch and any
        concurrent caller for the same normalized name awaits that same
        fetch, so PyPI sees exactly one request.

        Args:
            name: PyPI package name (any casing / underscore style).

        Returns:
            A `PyPIPackageData` populated from the latest PyPI
            JSON response.  Every caller for the same normalized name
            receives the *same* object.

        Raises:
            PyPIError: The package does not exist on PyPI or the API
                returned an unexpected status code.
            NetworkError: The request failed (timeout, rate limit, 5xx).

        Example::

            >>> data = await store.get_package_data("Requests")
            >>> data.name
            'requests'
            >>> data.latest_version
            '2.31.0'
        """
        normalized = _normalize(name)

        cached = self._package_data.get(normalized)
        if cached is not None:
            return cached

        return await self._coalesce(
            self._inflight_packages,
            normalized,
            lambda: self._load_package_data(name, normalized),
        )

    async def prefetch_packages(self, names: List[str]) -> None:
        """Concurrently warm the cache for a batch of packages.

        Duplicate names (including different spellings that normalize to
        the same key, e.g. ``Flask`` and ``flask``) are collapsed to a
        single fetch.  Errors for individual packages are silenced so that
        one bad package name does not prevent the rest from being cached.

        Args:
            names: Package names to prefetch.

        Example::

            >>> await store.prefetch_packages(["numpy", "pandas", "numpy"])
            # two fetches, not three; subsequent get_package_data calls
            # for these return instantly
        """
        # Insertion order keeps requests deterministic; first spelling wins.
        unique: Dict[str, str] = {}
        for name in names:
            unique.setdefault(_normalize(name), name)

        await asyncio.gather(
            *(self.get_package_data(name) for name in unique.values()),
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
           `PyPIPackageData` (``latest_dependencies`` or
           ``dependencies_cache``).
        3. A targeted ``/pypi/{name}/{version}/json`` fetch, coalesced per
           ``name==version`` key and throttled by the semaphore.

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

        cached_deps = self._version_deps_cache.get(cache_key)
        if cached_deps is not None:
            return cached_deps

        pkg_data = self._package_data.get(normalized)
        if pkg_data:
            if version == pkg_data.latest_version:
                self._version_deps_cache[cache_key] = pkg_data.latest_dependencies
                return pkg_data.latest_dependencies

            if version in pkg_data.dependencies_cache:
                deps = pkg_data.dependencies_cache[version]
                self._version_deps_cache[cache_key] = deps
                return deps

        return await self._coalesce(
            self._inflight_version_deps,
            cache_key,
            lambda: self._load_version_dependencies(
                name, version, normalized, cache_key
            ),
        )

    async def get_version_digests(self, name: str, version: str) -> Optional[List[str]]:
        """Return the sorted, unique sha256 hex digests of a release's files.

        Reads the cached package JSON when it carries digests, else fetches
        ``/pypi/{name}/{version}/json``. Returns ``None`` when the digests
        cannot be determined (network error, unknown release, no files);
        failures are never cached.
        """
        key = f"{_normalize(name)}=={version}"
        cached = self._digests_cache.get(key)
        if cached is not None:
            return cached

        pkg_data = self._package_data.get(_normalize(name))
        files = (pkg_data.releases.get(version) if pkg_data else None) or []
        digests = _sha256_digests(files)
        if not digests:
            url = (
                f"https://pypi.org/pypi/{quote(name, safe='')}"
                f"/{quote(version, safe='')}/json"
            )
            try:
                async with self._semaphore:
                    response = await self.http_client.get(url)
                if response.status_code != 200:
                    return None
                body = response.json()
                digests = _sha256_digests(body.get("urls") or [])
            except Exception as exc:  # noqa: BLE001 -- never cache, never raise
                logger.debug(
                    "Error fetching digests for %s==%s: %s", name, version, exc
                )
                return None
        if not digests:
            return None
        self._digests_cache[key] = digests
        return digests

    async def _coalesce(
        self,
        inflight: Dict[str, "asyncio.Task[_T]"],
        key: str,
        loader: Callable[[], Coroutine[Any, Any, _T]],
    ) -> _T:
        """Run *loader* once per *key*, sharing the result with all waiters.

        The first caller for *key* wraps *loader* in a task and registers
        it in *inflight*; concurrent callers await that same task instead
        of starting a second fetch.

        The task is awaited through `asyncio.shield` so that one
        caller being cancelled neither cancels the shared fetch nor
        strands the other waiters.  ``asyncio.run`` cancels any leftover
        task during loop shutdown, so no work is orphaned.

        Args:
            inflight: The in-flight registry for this kind of fetch.
            key: Normalized cache key.
            loader: Zero-argument factory returning the fetch coroutine.
                It is only called when no fetch is already in flight, so
                no coroutine is created (and left un-awaited) needlessly.

        Returns:
            Whatever *loader* resolves to.

        Raises:
            Exception: Whatever *loader* raises, re-raised in every waiter.
        """
        task = inflight.get(key)

        if task is None:
            task = asyncio.ensure_future(loader())
            inflight[key] = task
            # Runs even if every waiter was cancelled, so the entry is dropped
            # and the exception is retrieved.
            task.add_done_callback(lambda t: self._on_inflight_done(inflight, key, t))

        return await asyncio.shield(task)

    def _on_inflight_done(
        self,
        inflight: Dict[str, "asyncio.Task[_T]"],
        key: str,
        task: "asyncio.Task[_T]",
    ) -> None:
        """Clean up an in-flight entry once its task settles."""
        if inflight.get(key) is task:
            del inflight[key]

        if not task.cancelled():
            task.exception()  # retrieve to silence asyncio's warning

    def _discard_inflight(
        self, inflight: Dict[str, "asyncio.Task[_T]"], key: str
    ) -> None:
        """Drop this coroutine's own in-flight entry before it settles.

        Removing the entry inside the loader (rather than only in the done
        callback, which the loop schedules a tick later) guarantees that a
        caller arriving after a *failed* fetch starts a fresh attempt
        instead of inheriting the failure.
        """
        if inflight.get(key) is asyncio.current_task():
            del inflight[key]

    async def _load_package_data(
        self,
        name: str,
        normalized: str,
    ) -> PyPIPackageData:
        """Fetch, parse and cache one package (semaphore-throttled)."""
        try:
            async with self._semaphore:
                # Re-check: another coroutine may have cached it while we queued.
                cached = self._package_data.get(normalized)
                if cached is not None:
                    return cached

                data = await self._fetch_from_pypi(name)
                pkg_data = self._parse_package_data(name, data)
                self._package_data[normalized] = pkg_data
                return pkg_data
        finally:
            self._discard_inflight(self._inflight_packages, normalized)

    async def _load_version_dependencies(
        self,
        name: str,
        version: str,
        normalized: str,
        cache_key: str,
    ) -> List[str]:
        """Fetch and cache deps for one ``name==version`` (semaphore-throttled)."""
        try:
            async with self._semaphore:
                cached = self._version_deps_cache.get(cache_key)
                if cached is not None:
                    return cached

                fetched = await self._fetch_version_dependencies(name, version)
                if fetched is None:
                    # Transient failure: answer "none known" but do not cache.
                    return []
                deps = fetched
                self._version_deps_cache[cache_key] = deps

                # Re-read the entry: it may have been fetched while we queued.
                pkg_data = self._package_data.get(normalized)
                if pkg_data:
                    pkg_data.dependencies_cache[version] = deps

                return deps
        finally:
            self._discard_inflight(self._inflight_version_deps, cache_key)

    def get_cached_package(self, name: str) -> Optional[PyPIPackageData]:
        """Return cached data for *name* without triggering a fetch.

        Args:
            name: Package name (any casing / underscore style).

        Returns:
            The cached `PyPIPackageData`, or ``None`` if the
            package has not been fetched yet.
        """
        return self._package_data.get(_normalize(name))

    def get_versions(self, name: str) -> List[str]:
        """Return cached stable versions for *name* (newest first).

        Returns an empty list when *name* has not been fetched yet.

        Args:
            name: Package name.

        Returns:
            List of version strings, or ``[]``.
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
        caller should call `get_package_data` first if a definitive
        answer is needed.

        Args:
            name: Package name.
            version: Package version string.
            python_version: Dot-separated Python version.

        Returns:
            Compatibility flag (see `PyPIPackageData.is_python_compatible`).
        """
        pkg = self.get_cached_package(name)
        return pkg.is_python_compatible(version, python_version) if pkg else True

    async def _fetch_from_pypi(self, name: str) -> Dict[str, Any]:
        """Fetch ``/pypi/{name}/json`` and return the raw JSON body.

        Raises:
            PyPIError: On 404 (package not found) or any non-200 status.
        """
        url = PYPI_JSON_API.format(package=quote(name, safe=""))
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

        try:
            payload = response.json()
        except ValueError as exc:
            raise PyPIError(
                f"PyPI returned invalid JSON for '{name}'",
                package_name=name,
            ) from exc
        if not isinstance(payload, dict):
            raise PyPIError(
                f"PyPI returned an unexpected payload for '{name}'",
                package_name=name,
            )
        return payload

    async def _fetch_version_dependencies(
        self,
        name: str,
        version: str,
    ) -> Optional[List[str]]:
        """Fetch ``/pypi/{name}/{version}/json`` and extract base deps.

        Returns ``None`` (unknown, must not be cached) on any network,
        status or parsing failure; ``[]`` only when PyPI answers 404 or the
        release genuinely has no dependencies.
        """
        url = (
            f"https://pypi.org/pypi/{quote(name, safe='')}"
            f"/{quote(version, safe='')}/json"
        )

        try:
            response = await self.http_client.get(url)
            if response.status_code == 404:
                return []
            if response.status_code != 200:
                return None

            info = response.json().get("info") or {}
            return self._extract_dependencies(info)

        except Exception as exc:  # noqa: BLE001 -- never raise
            logger.debug(
                "Error fetching deps for %s==%s: %s",
                name,
                version,
                exc,
            )
            return None

    def _parse_package_data(
        self,
        name: str,
        data: Dict[str, Any],
    ) -> PyPIPackageData:
        """Transform a raw PyPI JSON response into `PyPIPackageData`.

        Skips versions with no files, only yanked files, or an unparseable
        version. ``parsed_versions`` is sorted newest first.

        Raises:
            PyPIError: The payload is malformed.
        """
        info = data.get("info") or {}
        releases = data.get("releases") or {}
        if not isinstance(info, dict) or not isinstance(releases, dict):
            raise PyPIError(
                f"PyPI returned a malformed payload for '{name}'",
                package_name=name,
            )

        latest_version = _text(info.get("version"))
        latest_requires_python = _text(info.get("requires_python"))
        latest_deps: List[str] = self._extract_dependencies(info)
        project_urls = _http_urls(info.get("project_urls"), info.get("home_page"))

        parsed_versions: List[Tuple[str, Version]] = []
        python_requirements: Dict[str, Optional[str]] = {}
        upload_times: Dict[str, Optional[datetime]] = {}

        for version_str, files in releases.items():
            if not files or not isinstance(files, list):
                continue

            # pip ignores yanked releases; skip one only if every file is yanked
            if all(isinstance(f, dict) and f.get("yanked") for f in files):
                continue

            try:
                parsed = parse(version_str)
            except InvalidVersion:
                # Non-PEP-440 tags (e.g. "1.0-alpha").
                continue

            parsed_versions.append((version_str, parsed))
            upload_times[version_str] = _earliest_upload(version_str, files)

            # Files of a release agree on requires_python; take the first.
            for file_info in files:
                if isinstance(file_info, dict) and _text(
                    file_info.get("requires_python")
                ):
                    python_requirements[version_str] = file_info["requires_python"]
                    break
            else:
                python_requirements[version_str] = None

        parsed_versions.sort(key=lambda x: x[1], reverse=True)

        all_versions: List[str] = [v for v, p in parsed_versions if not p.is_prerelease]

        return PyPIPackageData(
            name=_normalize(name),
            latest_version=latest_version,
            latest_requires_python=latest_requires_python,
            latest_dependencies=latest_deps,
            all_versions=all_versions,
            parsed_versions=parsed_versions,
            python_requirements=python_requirements,
            upload_times=upload_times,
            project_urls=project_urls,
            releases=releases,
            dependencies_cache=(
                {latest_version: latest_deps} if latest_version else {}
            ),
        )

    def _extract_dependencies(self, info: Dict[str, Any]) -> List[str]:
        """Return base (non-extra) dependency specifiers from ``info``.

        Environment markers are evaluated for the store's target Python
        (the running interpreter when none was given) with ``extra`` empty,
        so extra-only deps drop out; deps whose marker is false are skipped.  The marker is then removed so callers
        get clean PEP-508 name+version specs.

        Args:
            info: The ``info`` sub-dict from a PyPI JSON response.

        Returns:
            List of strings like ``["requests>=2.25", "click"]``.
        """
        requires_dist = info.get("requires_dist")
        deps: List[str] = []

        for dep in requires_dist if isinstance(requires_dist, list) else ():
            if not isinstance(dep, str):
                continue
            try:
                marker = Requirement(dep).marker
                if marker is not None and not marker.evaluate(self._marker_env):
                    continue
            except InvalidRequirement:
                pass  # keep unparseable lines as-is; the analyzer skips them

            base = dep.split(";")[0].strip()
            if base:
                deps.append(base)

        return deps

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


def _earliest_upload(version: str, files: List[Any]) -> Optional[datetime]:
    """Earliest ``upload_time_iso_8601`` among *files*, or ``None`` if unknown."""
    times: List[datetime] = []
    for f in files:
        raw = f.get("upload_time_iso_8601") if isinstance(f, dict) else None
        if not isinstance(raw, str):
            continue
        try:
            # fromisoformat rejects "Z" before Python 3.11.
            t = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        times.append(t if t.tzinfo else t.replace(tzinfo=timezone.utc))
    if not times:
        logger.debug("%s: no usable upload time; treating as old", version)
        return None
    return min(times)


def _sha256_digests(files: Any) -> List[str]:
    """Sorted unique sha256 hex digests found in PyPI file entries."""
    found = set()
    for f in files if isinstance(files, list) else []:
        d = (f.get("digests") or {}).get("sha256") if isinstance(f, dict) else None
        if isinstance(d, str) and re.fullmatch(r"[0-9a-fA-F]{64}", d):
            found.add(d.lower())
    return sorted(found)


def _text(value: Any) -> Optional[str]:
    """Return *value* when it is a non-empty string, else ``None``."""
    return value if isinstance(value, str) and value else None


def _normalize(name: str) -> str:
    """Normalize *name* (PEP 503); alias keeping cache keys consistent app-wide."""
    return normalize_package_name(name)


def _http_urls(project_urls: Any, home_page: Any) -> Dict[str, str]:
    """Keep only http(s) links (they end up in Markdown/JSON output)."""
    out: Dict[str, str] = {}
    if isinstance(project_urls, dict):
        for label, url in project_urls.items():
            if (
                isinstance(label, str)
                and isinstance(url, str)
                and url.startswith(("http://", "https://"))
            ):
                out[label] = url.strip()
    if (
        isinstance(home_page, str)
        and home_page.startswith(("http://", "https://"))
        and not any(k.strip().lower() in ("homepage", "home") for k in out)
    ):
        out["Homepage"] = home_page.strip()
    return out
