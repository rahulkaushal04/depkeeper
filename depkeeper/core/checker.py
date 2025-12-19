"""Version checking utilities for depkeeper.

This module provides the VersionChecker class for querying PyPI to check
package versions and metadata. It supports concurrent requests, version
extraction from requirements, and error handling for PyPI API interactions.

The VersionChecker can operate as an async context manager and handles
its own HTTP client lifecycle or accept an external client for shared
connection pooling.

Examples
--------
Basic usage with context manager:

    >>> from depkeeper.core.checker import VersionChecker
    >>> async with VersionChecker() as checker:
    ...     pkg = await checker.check_package("requests", "2.28.0")
    ...     print(f"{pkg.name}: {pkg.current_version} -> {pkg.latest_version}")

Check multiple packages concurrently:

    >>> from depkeeper.models.requirement import Requirement
    >>> requirements = [
    ...     Requirement(name="requests", specs=[("==", "2.28.0")]),
    ...     Requirement(name="click", specs=[(">=", "8.0.0")]),
    ... ]
    >>> async with VersionChecker() as checker:
    ...     packages = await checker.check_multiple(requirements)
    ...     for pkg in packages:
    ...         print(f"{pkg.name}: {pkg.latest_version}")

Custom configuration:

    >>> async with VersionChecker(concurrent_limit=20) as checker:
    ...     pkg = await checker.check_package("flask")

Notes
-----
The module uses asyncio for concurrent PyPI requests and implements rate
limiting through a semaphore to avoid overwhelming the PyPI API. All network
errors are wrapped in PyPIError for consistent error handling.

See Also
--------
depkeeper.utils.http.HTTPClient : HTTP client for PyPI requests
depkeeper.models.package.Package : Package data model
depkeeper.models.requirement.Requirement : Requirement specification
"""

from __future__ import annotations

import sys
import asyncio
from typing import Any, Dict, List, Optional
from packaging.specifiers import SpecifierSet
from packaging.version import parse, InvalidVersion

from depkeeper.exceptions import PyPIError
from depkeeper.utils.http import HTTPClient
from depkeeper.models.package import Package
from depkeeper.utils.logger import get_logger
from depkeeper.constants import PYPI_JSON_API
from depkeeper.models.requirement import Requirement

logger = get_logger("checker")


class VersionChecker:
    """Check package versions from PyPI.

    This class queries PyPI for package information, checks for updates,
    and filters versions based on update strategies. It supports concurrent
    requests with configurable limits and can extract version information
    from both pinned and range-based version specifications.

    The VersionChecker operates as an async context manager, automatically
    managing HTTP client lifecycle. When no external HTTP client is provided,
    it creates and manages its own client.

    Attributes
    ----------
    http_client : HTTPClient or None
        HTTP client for PyPI requests. If None initially, a client will be
        created when entering the context manager.
    concurrent_limit : int
        Maximum number of concurrent requests to PyPI. Default is 10.
    extract_from_ranges : bool
        Whether to extract baseline versions from range constraints like
        >=1.0.0. If True (default), extracts the baseline version. If False,
        only extracts from exact pins (==1.0.0).

    Examples
    --------
    Check a single package:

    >>> from depkeeper.core.checker import VersionChecker
    >>> async with VersionChecker() as checker:
    ...     pkg = await checker.check_package("requests", "2.28.0")
    ...     if pkg.latest_version:
    ...         print(f"Latest version: {pkg.latest_version}")

    Check multiple packages with custom concurrency:

    >>> from depkeeper.models.requirement import Requirement
    >>> reqs = [
    ...     Requirement(name="requests", specs=[("==", "2.28.0")]),
    ...     Requirement(name="flask", specs=[(">=", "2.0.0")]),
    ... ]
    >>> async with VersionChecker(concurrent_limit=5) as checker:
    ...     packages = await checker.check_multiple(reqs)

    Share an HTTP client across multiple checkers:

    >>> from depkeeper.utils.http import HTTPClient
    >>> async with HTTPClient() as client:
    ...     checker1 = VersionChecker(http_client=client)
    ...     checker2 = VersionChecker(http_client=client)
    ...     # Both checkers share the same connection pool

    Notes
    -----
    - Uses asyncio.Semaphore for rate limiting concurrent requests
    - Automatically handles HTTP client cleanup when self-managed
    - Extracts dependency information from PyPI metadata
    - Returns error Package objects instead of raising for individual failures
      in batch operations

    See Also
    --------
    check_package : Check a single package
    check_multiple : Check multiple packages concurrently
    """

    def __init__(
        self,
        http_client: Optional[HTTPClient] = None,
        concurrent_limit: int = 10,
        extract_from_ranges: bool = True,
    ) -> None:
        """Initialize version checker.

        Parameters
        ----------
        http_client : HTTPClient, optional
            HTTP client for PyPI requests. If not provided, a new client
            will be created and managed internally when entering the async
            context manager.
        concurrent_limit : int, optional
            Maximum concurrent requests to PyPI. Default is 10. Prevents
            overwhelming the PyPI API and respects rate limits.
        extract_from_ranges : bool, optional
            Whether to extract baseline versions from range constraints
            (>=, >, ~=). If True (default), extracts the baseline version
            from constraints like >=1.0.0. If False, only extracts from
            pinned versions (==1.0.0). Useful for understanding minimum
            version requirements.

        Examples
        --------
        Default initialization:

        >>> checker = VersionChecker()

        Custom concurrency limit:

        >>> checker = VersionChecker(concurrent_limit=20)

        Disable range extraction:

        >>> checker = VersionChecker(extract_from_ranges=False)

        Notes
        -----
        The semaphore for rate limiting is created immediately, but the
        HTTP client is only initialized when entering the context manager
        if not provided externally.
        """
        self.http_client = http_client
        self.concurrent_limit = concurrent_limit
        self.extract_from_ranges = extract_from_ranges
        self._semaphore = asyncio.Semaphore(concurrent_limit)
        self._owns_http_client = http_client is None

    async def __aenter__(self) -> "VersionChecker":
        """Enter async context manager.

        Creates and initializes the HTTP client if not provided externally.
        This ensures proper resource management and connection pooling.

        Returns
        -------
        VersionChecker
            The initialized version checker instance.

        Examples
        --------
        >>> async with VersionChecker() as checker:
        ...     # HTTP client is now initialized and ready
        ...     pkg = await checker.check_package("requests")
        """
        if self.http_client is None:
            self.http_client = HTTPClient()
            await self.http_client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore
        """Exit async context manager.

        Cleans up the HTTP client if it was created internally. External
        clients are not closed to allow for reuse.

        Parameters
        ----------
        exc_type : type or None
            Exception type if an exception was raised.
        exc_val : Exception or None
            Exception instance if an exception was raised.
        exc_tb : traceback or None
            Traceback object if an exception was raised.

        Notes
        -----
        Only closes the HTTP client if it was created internally
        (_owns_http_client is True).
        """
        if self._owns_http_client and self.http_client is not None:
            await self.http_client.__aexit__(exc_type, exc_val, exc_tb)

    async def get_package_info(
        self,
        name: str,
        current_version: Optional[str] = None,
    ) -> Package:
        """Fetch package information from PyPI.

        Retrieves the latest version and metadata for a package from the PyPI
        JSON API. The request is rate-limited using the configured semaphore
        to prevent overwhelming the API.

        Parameters
        ----------
        name : str
            Package name to check (case-insensitive, normalized to PyPI
            standard).
        current_version : str, optional
            Current installed or pinned version. Used for comparison and
            included in the returned Package object.

        Returns
        -------
        Package
            Package object containing version information and metadata,
            including the latest version, dependencies, and Python version
            requirements.

        Raises
        ------
        PyPIError
            If the package is not found on PyPI or the API returns an error.
            The exception includes the package name for debugging.
        RuntimeError
            If the HTTP client is not initialized (context manager not
            entered).

        Examples
        --------
        Check if a package has updates:

        >>> async with VersionChecker() as checker:
        ...     pkg = await checker.get_package_info("requests", "2.28.0")
        ...     if pkg.current_version != pkg.latest_version:
        ...         print(f"Update available: {pkg.latest_version}")

        Check latest version without current version:

        >>> async with VersionChecker() as checker:
        ...     pkg = await checker.get_package_info("flask")
        ...     print(f"Latest: {pkg.latest_version}")

        Handle missing packages:

        >>> from depkeeper.exceptions import PyPIError
        >>> async with VersionChecker() as checker:
        ...     try:
        ...         pkg = await checker.get_package_info("nonexistent-pkg")
        ...     except PyPIError as e:
        ...         print(f"Package not found: {e.package_name}")

        Notes
        -----
        This method is rate-limited by the semaphore configured in __init__.
        Multiple concurrent calls will be queued appropriately.

        See Also
        --------
        check_packages : Fetch information for multiple packages concurrently
        """
        async with self._semaphore:
            metadata = await self._fetch_pypi_metadata(name=name)
            return self._parse_package_data(
                name=name, data=metadata, current_version=current_version
            )

    async def check_packages(
        self,
        requirements: List[Requirement],
    ) -> List[Package]:
        """Fetch information for multiple packages concurrently.

        Retrieves version information for all packages in parallel, up to the
        configured concurrency limit. If any package check fails, an error
        Package object is returned for that package instead of raising an
        exception, allowing the operation to continue for other packages.

        Parameters
        ----------
        requirements : list of Requirement
            List of requirement objects to check. Current versions are
            automatically extracted from version specifications when possible.

        Returns
        -------
        list of Package
            List of Package objects with version information, in the same
            order as the input requirements. Failed checks return Package
            objects with None for latest_version and empty metadata.

        Examples
        --------
        Check multiple packages:

        >>> from depkeeper.models.requirement import Requirement
        >>> async with VersionChecker() as checker:
        ...     reqs = [
        ...         Requirement(name="requests", specs=[("==", "2.28.0")]),
        ...         Requirement(name="flask", specs=[(">=", "2.0.0")]),
        ...         Requirement(name="click", specs=[]),
        ...     ]
        ...     packages = await checker.check_packages(reqs)
        ...     for pkg in packages:
        ...         print(f"{pkg.name}: {pkg.latest_version}")

        Handle failures gracefully:

        >>> async with VersionChecker() as checker:
        ...     packages = await checker.check_packages(reqs)
        ...     for pkg in packages:
        ...         if pkg.latest_version is None:
        ...             print(f"Failed to check {pkg.name}")
        ...         else:
        ...             print(f"{pkg.name} is up to date")

        Notes
        -----
        - Failures are logged but do not stop the entire operation
        - Results maintain the same order as input requirements
        - Respects the concurrent_limit setting
        - Current versions are extracted automatically from requirements

        See Also
        --------
        get_package_info : Fetch information for a single package
        """
        # Create concurrent tasks for all package checks
        check_tasks = [self._create_package_check_task(req) for req in requirements]

        # Gather all results, capturing exceptions for individual failures
        results = await asyncio.gather(*check_tasks, return_exceptions=True)

        # Process results and handle failures gracefully
        return self._process_check_results(requirements, results)

    def _create_package_check_task(
        self, requirement: Requirement
    ) -> asyncio.Task[Package]:
        """Create an async task to check a single package.

        Parameters
        ----------
        requirement : Requirement
            Requirement object containing package name and version specs.

        Returns
        -------
        asyncio.Task[Package]
            Async task that will fetch package information.

        Notes
        -----
        This is an internal helper method to improve code organization.
        """
        current_version = self.extract_current_version(requirement)
        return asyncio.create_task(
            self.get_package_info(requirement.name, current_version)
        )

    def _process_check_results(
        self, requirements: List[Requirement], results: List[Any]
    ) -> List[Package]:
        """Process results from concurrent package checks.

        Handles both successful Package objects and exceptions, converting
        failures into error Package objects to maintain consistency.

        Parameters
        ----------
        requirements : list of Requirement
            Original requirements that were checked.
        results : list of Any
            Results from asyncio.gather, may contain Package objects or
            Exception instances.

        Returns
        -------
        list of Package
            List of Package objects, with error packages for any failures.

        Notes
        -----
        This is an internal helper method to improve code organization.
        """
        packages: List[Package] = []

        for requirement, result in zip(requirements, results):
            if isinstance(result, Exception):
                logger.error(
                    f"Failed to fetch package info for {requirement.name}: {result}"
                )
                current_version = self.extract_current_version(requirement)
                packages.append(
                    self.create_error_package(requirement.name, current_version)
                )
            else:
                packages.append(result)

        return packages

    async def _fetch_pypi_metadata(self, name: str) -> Dict[str, Any]:
        """Fetch package metadata from PyPI JSON API.

        Makes an HTTP request to PyPI's JSON API to retrieve comprehensive
        package information including versions, dependencies, and metadata.

        Parameters
        ----------
        name : str
            Package name to fetch metadata for.

        Returns
        -------
        dict[str, Any]
            Complete package metadata dictionary from PyPI, containing 'info',
            'releases', and other package information.

        Raises
        ------
        RuntimeError
            If HTTP client is not initialized. Occurs when this method is
            called outside of the async context manager.
        PyPIError
            If the package is not found (404), API error occurs, or network
            request fails. The exception wraps the underlying error with
            package context.

        Notes
        -----
        This is an internal method. Use check_package() or check_multiple()
        instead of calling this directly.

        The PyPI JSON API endpoint format is: https://pypi.org/pypi/{package}/json
        """
        if self.http_client is None:
            raise RuntimeError("HTTP client not initialized")

        url = PYPI_JSON_API.format(package=name)

        try:
            data = await self.http_client.get_json(url)
            return data
        except PyPIError:
            raise
        except Exception as exc:
            raise PyPIError(
                f"Failed to fetch PyPI metadata for {name}: {exc}",
                package_name=name,
            ) from exc

    def _parse_package_data(
        self,
        name: str,
        data: Dict[str, Any],
        current_version: Optional[str] = None,
    ) -> Package:
        """Parse PyPI JSON response into Package object.

        Extracts relevant information from the PyPI JSON response and creates
        a structured Package object. For Phase 1, focuses on essential data:
        latest version, dependencies, and Python version requirements.

        Parameters
        ----------
        name : str
            Package name.
        data : dict[str, Any]
            Complete PyPI JSON response data.
        current_version : str, optional
            Current installed or pinned version to include in the Package.

        Returns
        -------
        Package
            Parsed package object with metadata.

        Notes
        -----
        This is an internal method. The Package object is returned by
        get_package_info() and check_packages().

        Phase 1 includes minimal metadata. Future phases may extract:
        - Complete version history
        - Upload timestamps
        - Author information
        - Project URLs
        """
        info = data.get("info", {})
        latest_version = info.get("version")
        latest_requires_python = info.get("requires_python")

        # Base metadata
        metadata = {
            "requires_python": latest_requires_python,
            "dependencies": self._get_dependencies(info),
            "latest_metadata": {
                "requires_python": latest_requires_python,
            },
        }

        # Find max safe upgrade version that is Python compatible
        # - If current version exists: stay within same major version to avoid breaking changes
        # - If no current version: find latest Python-compatible version
        safe_upgrade_version = None
        current_py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        if current_version and latest_version:
            # Current version exists: find max version within same major (minor/patch updates only)
            safe_upgrade_version = self._find_max_minor_version(
                data, current_version, latest_version, current_py
            )
        elif latest_version:
            # No current version: find latest Python-safe upgrade version (any major)
            safe_upgrade_version = self._find_safe_upgrade_version(data, current_py)

        if safe_upgrade_version:
            # Get metadata for safe upgrade version
            safe_upgrade_metadata = self._get_version_metadata(
                data, safe_upgrade_version
            )
            metadata["safe_upgrade_metadata"] = safe_upgrade_metadata

        # Get metadata for current version if available
        if current_version:
            current_metadata = self._get_version_metadata(data, current_version)
            if current_metadata:
                metadata["current_metadata"] = current_metadata

        return Package(
            name=name,
            current_version=current_version,
            latest_version=latest_version,
            safe_upgrade_version=safe_upgrade_version,
            metadata=metadata,
        )

    def _find_max_minor_version(
        self,
        data: Dict[str, Any],
        current_version: str,
        latest_version: str,
        python_version: str,
    ) -> Optional[str]:
        """Find the maximum version within the same major version as current.

        This helps identify safe upgrade paths that avoid breaking changes
        from major version bumps AND ensures Python version compatibility.

        Parameters
        ----------
        data : dict
            Complete PyPI package data
        current_version : str
            Current installed version
        latest_version : str
            Latest available version
        python_version : str
            Current Python version to check compatibility (e.g., '3.8.0')

        Returns
        -------
        str or None
            Latest version with same major version as current that is compatible
            with the Python version, or None if not found
        """
        try:
            current_parsed = parse(current_version)
            latest_parsed = parse(latest_version)
        except InvalidVersion:
            logger.debug(
                f"Invalid version format: {current_version} or {latest_version}"
            )
            return None

        # If latest is same major version, check if it's safe to upgrade to
        if hasattr(current_parsed, "release") and hasattr(latest_parsed, "release"):
            if len(current_parsed.release) > 0 and len(latest_parsed.release) > 0:
                if current_parsed.release[0] == latest_parsed.release[0]:
                    # Same major version, check if it's safe to upgrade to
                    releases = data.get("releases", {})
                    if latest_version in releases:
                        if self._is_version_safe_to_upgrade(
                            releases[latest_version], python_version
                        ):
                            return latest_version

        # Otherwise, search for max version with same major AND Python safe to upgrade to
        releases = data.get("releases", {})
        if not releases:
            return None

        try:
            valid_versions = []
            for v in releases.keys():
                if not releases[v]:  # Skip empty releases
                    continue
                try:
                    parsed = parse(v)
                    # Only include non-prerelease versions with same major
                    if (
                        not parsed.is_prerelease
                        and hasattr(parsed, "release")
                        and len(parsed.release) > 0
                        and hasattr(current_parsed, "release")
                        and len(current_parsed.release) > 0
                        and parsed.release[0] == current_parsed.release[0]
                    ):
                        # Check if it's safe to upgrade to
                        if self._is_version_safe_to_upgrade(
                            releases[v], python_version
                        ):
                            valid_versions.append((v, parsed))
                except InvalidVersion:
                    continue

            if not valid_versions:
                return None

            # Sort by version, newest first
            valid_versions.sort(key=lambda x: x[1], reverse=True)
            return valid_versions[0][0]

        except Exception as e:
            logger.debug(f"Error finding max minor version: {e}")
            return None

    def _find_safe_upgrade_version(
        self, data: Dict[str, Any], python_version: str
    ) -> Optional[str]:
        """Find the latest stable safe upgrade version for the given Python version.

        Searches through all available versions from newest to oldest to find
        the most recent version that is safe to upgrade to with the specified
        Python version. Prioritizes stable releases over pre-releases.

        Parameters
        ----------
        data : dict
            Complete PyPI package data
        python_version : str
            Python version to check compatibility (e.g., '3.8.0')

        Returns
        -------
        str or None
            Latest safe upgrade version, or None if not found
        """
        releases = data.get("releases", {})
        if not releases:
            return None

        # Get all versions sorted from newest to oldest
        try:
            # Filter out empty releases and parse versions
            valid_versions = []
            for v in releases.keys():
                if not v or not releases[v]:
                    continue
                try:
                    parsed = parse(v)
                    valid_versions.append((v, parsed))
                except InvalidVersion:
                    continue

            # Sort by version, newest first
            valid_versions.sort(key=lambda x: x[1], reverse=True)
        except Exception:
            return None

        # First pass: Try to find latest stable (non-prerelease) safe upgrade version
        for version_str, parsed_version in valid_versions:
            if (
                hasattr(parsed_version, "is_prerelease")
                and parsed_version.is_prerelease
            ):
                continue

            if self._is_version_safe_to_upgrade(releases[version_str], python_version):
                logger.debug(f"Found latest safe upgrade stable version: {version_str}")
                return version_str

        # Second pass: If no stable version found, try pre-releases
        for version_str, parsed_version in valid_versions:
            if self._is_version_safe_to_upgrade(releases[version_str], python_version):
                logger.debug(
                    f"Found latest safe upgrade pre-release version: {version_str}"
                )
                return version_str

        logger.debug(f"No safe upgrade version found for Python {python_version}")
        return None

    def _is_version_safe_to_upgrade(
        self, release_data: List[Dict[str, Any]], python_version: str
    ) -> bool:
        """Check if a version is safe to upgrade to with the given Python version.

        Parameters
        ----------
        release_data : list
            List of release files for a specific version
        python_version : str
            Python version to check compatibility

        Returns
        -------
        bool
            True if safe to upgrade to, False otherwise
        """
        if not release_data:
            return False

        # Check the first release file (usually the source distribution)
        for release_file in release_data:
            requires_python = release_file.get("requires_python")

            if not requires_python:
                # No requirement means compatible with all versions
                return True

            try:
                spec = SpecifierSet(requires_python)
                return python_version in spec
            except Exception:
                # If we can't parse the specifier, assume incompatible for safety
                logger.debug(f"Failed to parse requires_python: {requires_python}")
                return False

        return False

    def _get_version_metadata(
        self, data: Dict[str, Any], version: str
    ) -> Dict[str, Any]:
        """Get metadata for a specific version.

        Parameters
        ----------
        data : dict
            Complete PyPI package data
        version : str
            Version to get metadata for

        Returns
        -------
        dict
            Metadata dictionary with requires_python
        """
        releases = data.get("releases", {})
        release_data = releases.get(version, [])

        if release_data:
            for release_file in release_data:
                requires_python = release_file.get("requires_python")
                return {"requires_python": requires_python}

        return {"requires_python": None}

    def _get_dependencies(self, info: Dict[str, Any]) -> List[str]:
        """Extract dependencies from package info.

        Parses the requires_dist field from PyPI metadata to extract a list
        of package dependencies. Environment markers (platform-specific or
        Python version conditions) are removed for simplicity in Phase 1.

        Parameters
        ----------
        info : dict[str, Any]
            Package info dictionary from PyPI JSON response.

        Returns
        -------
        list of str
            List of dependency specification strings without environment
            markers. Empty list if no dependencies.

        Examples
        --------
        >>> info = {
        ...     "requires_dist": [
        ...         "certifi>=2017.4.17",
        ...         "charset-normalizer>=2; python_version>='3.7'",
        ...         "idna>=2.5,<4",
        ...     ]
        ... }
        >>> checker = VersionChecker()
        >>> deps = checker._get_dependencies(info)
        >>> print(deps)
        ['certifi>=2017.4.17', 'charset-normalizer>=2', 'idna>=2.5,<4']

        Notes
        -----
        This is an internal helper method. Environment markers (after
        semicolons) are stripped to simplify dependency handling in Phase 1.
        Future phases may preserve and evaluate markers.
        """
        requires_dist = info.get("requires_dist", [])
        if not requires_dist:
            return []

        deps: List[str] = []
        for dep in requires_dist:
            base_dep = dep.split(";")[0].strip()
            if base_dep:
                deps.append(base_dep)

        return deps

    def extract_current_version(self, req: Requirement) -> Optional[str]:
        """Extract current version from a requirement.

        Determines the current or baseline version from a requirement's
        version specifications. For exact pins (==), always returns the
        pinned version. For range constraints (>=, >, ~=), returns the
        baseline version only if extract_from_ranges is enabled.

        Parameters
        ----------
        req : Requirement
            Requirement object to extract version from.

        Returns
        -------
        str or None
            Current or baseline version if determinable from the requirement
            specifications. None if no version can be extracted or the
            requirement has no version specs.

        Examples
        --------
        Exact version pin:

        >>> from depkeeper.models.requirement import Requirement
        >>> checker = VersionChecker()
        >>> req = Requirement(name="requests", specs=[("==", "2.28.0")])
        >>> checker._extract_current_version(req)
        '2.28.0'

        Range constraint with extraction enabled:

        >>> req = Requirement(name="flask", specs=[(">=", "2.0.0")])
        >>> checker = VersionChecker(extract_from_ranges=True)
        >>> checker.extract_current_version(req)
        '2.0.0'

        Range constraint with extraction disabled:

        >>> checker = VersionChecker(extract_from_ranges=False)
        >>> checker.extract_current_version(req)
        None

        Complex constraint:

        >>> req = Requirement(name="click", specs=[(">=", "8.0"), ("<", "9.0")])
        >>> checker.extract_current_version(req)
        '8.0'

        Notes
        -----
        This is an internal helper method. The extraction behavior for range
        constraints is controlled by the extract_from_ranges setting to support
        different use cases:

        - True: Extract baseline for user visibility of minimum versions
        - False: Only extract exact pins for strict current version tracking
        """
        if not req.specs:
            return None

        if len(req.specs) == 1 and req.specs[0][0] == "==":
            return req.specs[0][1]

        if not self.extract_from_ranges:
            return None

        if len(req.specs) == 1:
            operator, version = req.specs[0]
            if operator in (">=", ">", "~="):
                return version

        for operator, version in req.specs:
            if operator in (">=", ">", "~="):
                return version

        return None

    def create_error_package(
        self, name: str, current_version: Optional[str]
    ) -> Package:
        """Create an error Package object with empty data.

        Constructs a Package object with minimal information when a package
        check fails. Used to maintain consistency in batch operations where
        some packages may fail but others succeed.

        Parameters
        ----------
        name : str
            Package name.
        current_version : str, optional
            Current version if known from the requirement.

        Returns
        -------
        Package
            Package object with no latest version, no available versions,
            and empty metadata. Indicates a failed check.

        Examples
        --------
        >>> checker = VersionChecker()
        >>> error_pkg = checker.create_error_package("nonexistent", "1.0.0")
        >>> error_pkg.latest_version is None
        True
        >>> error_pkg.metadata
        {}

        Notes
        -----
        This is an internal helper method used by check_packages() to handle
        individual package check failures without stopping the entire batch
        operation.
        """
        return Package(
            name=name,
            current_version=current_version,
            latest_version=None,
            safe_upgrade_version=None,
            metadata={},
        )
