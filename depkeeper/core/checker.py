"""Version checking with strict major version boundary enforcement.

This module provides the primary interface for determining which version of
a package should be recommended for upgrade, with **strict enforcement** of
major version boundaries to prevent breaking changes.

All PyPI metadata is sourced through :class:`~depkeeper.core.data_store.PyPIDataStore`
to ensure that every ``/pypi/{pkg}/json`` call is made at most once per process.

The recommendation algorithm prioritises:

1. **Major-version stability** — recommendations **never** cross major version
   boundaries. If current is 2.x.x, recommended will always be 2.y.z (never 3.0.0).
2. **Python compatibility** — versions that do not support the running
   interpreter are skipped.
3. **Stable releases** — pre-releases are never recommended.

Typical usage::

    from depkeeper.utils.http import HTTPClient
    from depkeeper.core.data_store import PyPIDataStore
    from depkeeper.core.version_checker import VersionChecker
    from depkeeper.parser import RequirementsParser

    async with HTTPClient() as http:
        store   = PyPIDataStore(http)
        checker = VersionChecker(data_store=store)

        # Parse requirements
        parser = RequirementsParser()
        requirements = parser.parse_file("requirements.txt")

        # Check all packages concurrently
        packages = await checker.check_packages(requirements)

        for pkg in packages:
            if pkg.recommended_version:
                print(f"{pkg.name}: {pkg.current_version} → {pkg.recommended_version}")
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from packaging.version import InvalidVersion, Version, parse
from packaging.specifiers import InvalidSpecifier, SpecifierSet

from depkeeper.exceptions import PyPIError
from depkeeper.core.data_store import PyPIDataStore, PyPIPackageData
from depkeeper.models.package import Package
from depkeeper.models.requirement import Requirement
from depkeeper.utils.logger import get_logger

logger = get_logger("version_checker")


class VersionChecker:
    """Async package version checker with strict major version boundaries.

    Fetches metadata from PyPI (via the shared data store) and determines
    the highest Python-compatible version for each package, **strictly
    respecting major-version boundaries** when a current version is known.
    Unlike the base implementation, this checker will never recommend
    crossing a major version boundary, even if a newer major exists.

    All network I/O is delegated to *data_store*, which guarantees that
    each unique package is fetched at most once.

    Args:
        data_store: Shared PyPI metadata cache. **Required**.
        infer_version_from_constraints: When ``True`` and a requirement has
            no pinned version (``==``), attempt to infer a "current" version
            from range constraints like ``>=2.0``. Defaults to ``True``.

    Raises:
        TypeError: If *data_store* is ``None``.

    Example::

        >>> async with HTTPClient() as http:
        ...     store   = PyPIDataStore(http)
        ...     checker = VersionChecker(data_store=store)
        ...     pkg     = await checker.get_package_info("flask", current_version="2.0.0")
        ...     print(pkg.recommended_version)
        '2.3.3'  # Never 3.x.x, even if 3.0.0 is available
    """

    def __init__(
        self,
        data_store: PyPIDataStore,
        infer_version_from_constraints: bool = True,
    ) -> None:
        if data_store is None:
            raise TypeError(
                "data_store must not be None; pass a PyPIDataStore instance"
            )

        self.data_store: PyPIDataStore = data_store
        self.infer_version_from_constraints: bool = infer_version_from_constraints

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_package_info(
        self,
        name: str,
        current_version: Optional[str] = None,
    ) -> Package:
        """Fetch metadata and compute a recommended version for *name*.

        **CRITICAL**: Recommendations **NEVER** cross major version boundaries.
        If *current_version* is ``2.x.x``, the recommended version will be
        ``2.y.z`` (never ``3.0.0``), even if ``3.0.0`` is the latest available
        version on PyPI.

        Calls :meth:`PyPIDataStore.get_package_data` (which may trigger a
        network fetch or return cached data), then applies the strict
        major-boundary recommendation algorithm to choose the best upgrade
        target.

        Args:
            name: Package name (any casing / separator style).
            current_version: The version currently installed (if known).
                When provided, the recommendation stays within the same
                major version. If no compatible version exists in that
                major, stays on current version rather than crossing
                the boundary.

        Returns:
            A :class:`Package` with ``latest_version``,
            ``recommended_version``, and metadata fields populated.

        Raises:
            PyPIError: The package does not exist on PyPI or the API
                returned an unexpected status.

        Example::

            >>> pkg = await checker.get_package_info("requests", current_version="2.25.0")
            >>> pkg.latest_version
            '2.31.0'
            >>> pkg.recommended_version
            '2.31.0'  # Stays in major version 2
        """
        try:
            pkg_data = await self.data_store.get_package_data(name)
        except PyPIError:
            # Package not found or API error — return unavailable stub
            logger.warning("Package '%s' unavailable; creating stub", name)
            return self.create_unavailable_package(name, current_version)

        return self._build_package_from_data(pkg_data, current_version)

    async def check_packages(
        self,
        requirements: List[Requirement],
    ) -> List[Package]:
        """Check multiple packages concurrently.

        For each requirement, extracts the current version (via
        :meth:`extract_current_version`) and calls :meth:`get_package_info`.
        Errors for individual packages are caught and replaced with
        unavailable stubs so that one bad package does not block the rest.

        Args:
            requirements: Parsed requirements from a requirements file.

        Returns:
            List of :class:`Package` objects, one per requirement.

        Example::

            >>> requirements = parser.parse_file("requirements.txt")
            >>> packages = await checker.check_packages(requirements)
            >>> [p.name for p in packages if p.recommended_version]
            ['flask', 'requests', 'click']
        """
        tasks = [self._create_package_check_task(req) for req in requirements]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return self._process_check_results(requirements, results)

    def extract_current_version(
        self,
        req: Requirement,
    ) -> Optional[str]:
        """Infer a "current" version from a requirement's version specifiers.

        Heuristic:

        1. If the requirement has exactly one specifier and it is ``==``,
           return that version (pinned).
        2. If :attr:`infer_version_from_constraints` is ``False``, stop here.
        3. Otherwise, scan for the first ``>=``, ``>``, or ``~=`` specifier
           and return its version. This treats ``>=2.0`` as "currently on
           2.0" for major-version boundary purposes.

        Args:
            req: A parsed :class:`Requirement`.

        Returns:
            The inferred version string, or ``None`` when inference is not
            possible.

        Example::

            >>> req1 = Requirement(name="flask", specs=[("==", "2.0.0")], ...)
            >>> checker.extract_current_version(req1)
            '2.0.0'

            >>> req2 = Requirement(name="flask", specs=[(">=", "2.0"), ("<", "3")], ...)
            >>> checker.extract_current_version(req2)
            '2.0'

            >>> req3 = Requirement(name="flask", specs=[], ...)
            >>> checker.extract_current_version(req3) is None
            True
        """
        if not req.specs:
            return None

        # Exact pin: treat as the current version
        if len(req.specs) == 1 and req.specs[0][0] == "==":
            return req.specs[0][1]

        if not self.infer_version_from_constraints:
            return None

        # Infer from range lower-bound operators
        for operator, version in req.specs:
            if operator in (">=", ">", "~="):
                return version

        return None

    def create_unavailable_package(
        self,
        name: str,
        current_version: Optional[str],
    ) -> Package:
        """Create a stub :class:`Package` when PyPI data is unavailable.

        Used when a package lookup fails (404, network error, etc.) so that
        the caller can still process the rest of the package list.

        Args:
            name: Package name.
            current_version: The version that was installed (if known).

        Returns:
            A :class:`Package` with ``latest_version`` and
            ``recommended_version`` both set to ``None``.

        Example::

            >>> pkg = checker.create_unavailable_package("nonexistent", "1.0.0")
            >>> pkg.latest_version is None
            True
        """
        return Package(
            name=name,
            current_version=current_version,
            latest_version=None,
            recommended_version=None,
            metadata={},
        )

    # ------------------------------------------------------------------
    # Task management (private)
    # ------------------------------------------------------------------

    def _create_package_check_task(
        self,
        requirement: Requirement,
    ) -> asyncio.Task[Package]:
        """Spawn an async task to check a single requirement.

        Extracts the current version from *requirement* and delegates to
        :meth:`get_package_info`.

        Args:
            requirement: A parsed requirement.

        Returns:
            An :class:`asyncio.Task` that will resolve to a :class:`Package`.
        """
        current_version = self.extract_current_version(requirement)
        return asyncio.create_task(
            self.get_package_info(requirement.name, current_version)
        )

    def _process_check_results(
        self,
        requirements: List[Requirement],
        results: List[Any],
    ) -> List[Package]:
        """Convert :func:`asyncio.gather` results into a flat package list.

        Any exceptions raised during individual checks are caught and
        replaced with unavailable package stubs.

        Args:
            requirements: Original requirement list (for error recovery).
            results: Output of ``gather(*tasks, return_exceptions=True)``.

        Returns:
            List of :class:`Package` objects (same length as *requirements*).
        """
        packages: List[Package] = []

        for requirement, result in zip(requirements, results):
            if isinstance(result, Exception):
                logger.error(
                    "Failed to fetch package info for %s: %s",
                    requirement.name,
                    result,
                )
                packages.append(
                    self.create_unavailable_package(
                        requirement.name,
                        self.extract_current_version(requirement),
                    )
                )
            else:
                packages.append(result)

        return packages

    # ------------------------------------------------------------------
    # Recommendation algorithm (private)
    # ------------------------------------------------------------------

    def _build_package_from_data(
        self,
        pkg_data: PyPIPackageData,
        current_version: Optional[str],
    ) -> Package:
        """Construct a :class:`Package` from cached PyPI metadata.

        Applies the **strict major-boundary** recommendation algorithm:

        1. If *current_version* is provided and parseable, determine its
           major version number.
        2. Find **all** Python-compatible versions within that same major
           (using :meth:`PyPIPackageData.get_python_compatible_versions`).
        3. Return the **highest** version from that filtered list as the
           recommendation.
        4. If no compatible version exists in the current major, **stay on
           current version** rather than suggesting a major upgrade.
        5. If no *current_version* is provided, find the highest
           Python-compatible stable version across all majors.

        This ensures that recommendations **never** cross major version
        boundaries, preventing inadvertent breaking changes.

        Args:
            pkg_data: Cached package metadata from the data store.
            current_version: The version currently installed (if known).

        Returns:
            A fully populated :class:`Package`.

        Example (internal)::

            >>> # Current is 2.0.0, latest is 3.1.0
            >>> pkg = self._build_package_from_data(pkg_data, "2.0.0")
            >>> pkg.recommended_version
            '2.3.3'  # Highest in major 2, NOT 3.1.0
        """
        latest_version: Optional[str] = pkg_data.latest_version
        python_version: str = PyPIDataStore.get_current_python_version()

        # ── Determine recommended version ─────────────────────────────
        recommended_version: Optional[str] = None

        if current_version:
            # CRITICAL: Stay within current major version
            try:
                current_parsed = parse(current_version)
                current_major = (
                    current_parsed.release[0] if current_parsed.release else None
                )

                if current_major is not None:
                    # Get all Python-compatible versions in the current major
                    compatible_in_major = pkg_data.get_python_compatible_versions(
                        python_version, major=current_major
                    )

                    if compatible_in_major:
                        # First one is the highest (already sorted descending)
                        recommended_version = compatible_in_major[0]
                        logger.debug(
                            "%s: current=%s (major=%d), recommended=%s within major %d",
                            pkg_data.name,
                            current_version,
                            current_major,
                            recommended_version,
                            current_major,
                        )
                    else:
                        # No compatible version in current major - stay on current
                        logger.warning(
                            "%s: no Python-compatible version found in major %d, staying on %s",
                            pkg_data.name,
                            current_major,
                            current_version,
                        )
                        recommended_version = current_version
                else:
                    logger.warning(
                        "%s: cannot determine major version from %s",
                        pkg_data.name,
                        current_version,
                    )
                    recommended_version = current_version

            except InvalidVersion:
                logger.warning(
                    "%s: invalid current version %s, cannot recommend",
                    pkg_data.name,
                    current_version,
                )
                recommended_version = None
        else:
            # No current version - just find highest compatible stable version
            compatible_versions = pkg_data.get_python_compatible_versions(
                python_version
            )
            if compatible_versions:
                recommended_version = compatible_versions[0]

        # ── Build metadata dict ────────────────────────────────────────
        metadata: Dict[str, Any] = {
            "dependencies": pkg_data.latest_dependencies,
            "latest_metadata": {
                "requires_python": pkg_data.latest_requires_python,
            },
        }

        if recommended_version:
            metadata["recommended_metadata"] = {
                "requires_python": pkg_data.python_requirements.get(
                    recommended_version
                ),
            }

        if current_version:
            metadata["current_metadata"] = {
                "requires_python": pkg_data.python_requirements.get(current_version),
            }

        return Package(
            name=pkg_data.name,
            current_version=current_version,
            latest_version=latest_version,
            recommended_version=recommended_version,
            metadata=metadata,
        )
