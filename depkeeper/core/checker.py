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

import asyncio
from typing import Any, Dict, List, Optional

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

    async def check_package(
        self,
        name: str,
        current_version: Optional[str] = None,
    ) -> Package:
        """Check package information from PyPI.

        Fetches the latest version and metadata for a package from the PyPI
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
        ...     pkg = await checker.check_package("requests", "2.28.0")
        ...     if pkg.current_version != pkg.latest_version:
        ...         print(f"Update available: {pkg.latest_version}")

        Check latest version without current version:

        >>> async with VersionChecker() as checker:
        ...     pkg = await checker.check_package("flask")
        ...     print(f"Latest: {pkg.latest_version}")

        Handle missing packages:

        >>> from depkeeper.exceptions import PyPIError
        >>> async with VersionChecker() as checker:
        ...     try:
        ...         pkg = await checker.check_package("nonexistent-pkg")
        ...     except PyPIError as e:
        ...         print(f"Package not found: {e.package_name}")

        Notes
        -----
        This method is rate-limited by the semaphore configured in __init__.
        Multiple concurrent calls will be queued appropriately.

        See Also
        --------
        check_multiple : Check multiple packages concurrently
        """
        async with self._semaphore:
            metadata = await self._fetch_pypi_metadata(name)
            return self._parse_package_data(name, metadata, current_version)

    async def check_multiple(
        self,
        requirements: List[Requirement],
    ) -> List[Package]:
        """Check multiple packages concurrently.

        Fetches version information for all packages in parallel, up to the
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
        ...     packages = await checker.check_multiple(reqs)
        ...     for pkg in packages:
        ...         print(f"{pkg.name}: {pkg.latest_version}")

        Handle failures gracefully:

        >>> async with VersionChecker() as checker:
        ...     packages = await checker.check_multiple(reqs)
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
        check_package : Check a single package
        """
        return await self._check_multiple_concurrent(requirements)

    async def _check_multiple_concurrent(
        self, requirements: List[Requirement]
    ) -> List[Package]:
        """Check multiple packages concurrently without progress bar.

        Internal method that handles the actual concurrent checking logic.
        Creates tasks for all packages and gathers results with exception
        handling.

        Parameters
        ----------
        requirements : list of Requirement
            List of requirements to check.

        Returns
        -------
        list of Package
            List of Package objects, with error packages for any failures.

        Notes
        -----
        This is an internal method. Use check_multiple() instead.
        """
        tasks = []
        for req in requirements:
            current = self._extract_current_version(req)
            tasks.append(self.check_package(req.name, current))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        packages: List[Package] = []
        for req, result in zip(requirements, results):
            if isinstance(result, Exception):
                logger.error(f"Failed to check {req.name}: {result}")
                current = self._extract_current_version(req)
                packages.append(self._create_error_package(req.name, current))
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
            Parsed package object with metadata. Available_versions and
            last_updated are not populated in Phase 1.

        Notes
        -----
        This is an internal method. The Package object is returned by
        check_package() and check_multiple().

        Phase 1 includes minimal metadata. Future phases may extract:
        - Complete version history
        - Upload timestamps
        - Author information
        - Project URLs
        """
        info = data.get("info", {})
        latest_version = info.get("version")
        metadata = {
            "requires_python": info.get("requires_python"),
            "dependencies": self._get_dependencies(info),
        }

        return Package(
            name=name,
            current_version=current_version,
            latest_version=latest_version,
            available_versions=[],
            metadata=metadata,
            last_updated=None,
        )

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

    def _extract_current_version(self, req: Requirement) -> Optional[str]:
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
        >>> checker._extract_current_version(req)
        '2.0.0'

        Range constraint with extraction disabled:

        >>> checker = VersionChecker(extract_from_ranges=False)
        >>> checker._extract_current_version(req)
        None

        Complex constraint:

        >>> req = Requirement(name="click", specs=[(">=", "8.0"), ("<", "9.0")])
        >>> checker._extract_current_version(req)
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

    def _create_error_package(
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
        >>> error_pkg = checker._create_error_package("nonexistent", "1.0.0")
        >>> error_pkg.latest_version is None
        True
        >>> error_pkg.metadata
        {}

        Notes
        -----
        This is an internal helper method used by check_multiple() to handle
        individual package check failures without stopping the entire batch
        operation.
        """
        return Package(
            name=name,
            current_version=current_version,
            latest_version=None,
            available_versions=[],
            metadata={},
            last_updated=None,
        )
