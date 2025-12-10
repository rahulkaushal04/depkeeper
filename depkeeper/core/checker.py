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


# ============================================================================
# Version Checker
# ============================================================================


class VersionChecker:
    """
    Check package versions from PyPI.

    This class queries PyPI for package information, checks for updates,
    and filters versions based on update strategies.

    Attributes
    ----------
    http_client : HTTPClient, optional
        HTTP client for PyPI requests. If None, creates a new client.
    concurrent_limit : int
        Maximum number of concurrent requests to PyPI.
    """

    def __init__(
        self,
        http_client: Optional[HTTPClient] = None,
        concurrent_limit: int = 10,
        extract_from_ranges: bool = True,
    ) -> None:
        """
        Initialize version checker.

        Parameters
        ----------
        http_client : HTTPClient, optional
            HTTP client for PyPI requests. If not provided, a new client
            will be created and managed internally.
        concurrent_limit : int, optional
            Maximum concurrent requests. Default is 10.
        extract_from_ranges : bool, optional
            Whether to extract baseline versions from range constraints (>=, >, ~=).
            If True (default), extracts baseline from constraints like >=1.0.0.
            If False, only extracts from pinned versions (==1.0.0).
        """
        self.http_client = http_client
        self.concurrent_limit = concurrent_limit
        self.extract_from_ranges = extract_from_ranges
        self._semaphore = asyncio.Semaphore(concurrent_limit)

        # Track if we own the HTTP client (for cleanup)
        self._owns_http_client = http_client is None

    # ----------------------------------------------------------------------
    # Context Manager
    # ----------------------------------------------------------------------

    async def __aenter__(self) -> "VersionChecker":
        """Enter async context manager."""
        if self.http_client is None:
            self.http_client = HTTPClient()
            await self.http_client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore
        """Exit async context manager."""
        if self._owns_http_client and self.http_client is not None:
            await self.http_client.__aexit__(exc_type, exc_val, exc_tb)

    # ----------------------------------------------------------------------
    # Single Package Check
    # ----------------------------------------------------------------------

    async def check_package(
        self,
        name: str,
        current_version: Optional[str] = None,
    ) -> Package:
        """
        Check package information from PyPI.

        Parameters
        ----------
        name : str
            Package name to check.
        current_version : str, optional
            Current installed or pinned version.

        Returns
        -------
        Package
            Package object with version information and metadata.

        Raises
        ------
        PyPIError
            If package is not found or PyPI API returns an error.
        RuntimeError
            If HTTP client is not initialized.
        """
        async with self._semaphore:
            metadata = await self._fetch_pypi_metadata(name)
            return self._parse_package_data(name, metadata, current_version)

    # ----------------------------------------------------------------------
    # Multiple Package Check
    # ----------------------------------------------------------------------

    async def check_multiple(
        self,
        requirements: List[Requirement],
    ) -> List[Package]:
        """
        Check multiple packages concurrently.

        Parameters
        ----------
        requirements : List[Requirement]
            List of requirements to check.

        Returns
        -------
        List[Package]
            List of packages with version information. If a package check
            fails, an empty Package object is returned for that package.
        """
        return await self._check_multiple_concurrent(requirements)

    async def _check_multiple_concurrent(
        self, requirements: List[Requirement]
    ) -> List[Package]:
        """Check multiple packages concurrently without progress bar."""
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

    # ----------------------------------------------------------------------
    # PyPI Metadata Fetching
    # ----------------------------------------------------------------------

    async def _fetch_pypi_metadata(self, name: str) -> Dict[str, Any]:
        """
        Fetch package metadata from PyPI JSON API.

        Parameters
        ----------
        name : str
            Package name.

        Returns
        -------
        Dict[str, Any]
            Package metadata dictionary from PyPI.

        Raises
        ------
        RuntimeError
            If HTTP client is not initialized.
        PyPIError
            If package is not found or API error occurs.
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

    # ----------------------------------------------------------------------
    # Package Data Parsing
    # ----------------------------------------------------------------------

    def _parse_package_data(
        self,
        name: str,
        data: Dict[str, Any],
        current_version: Optional[str] = None,
    ) -> Package:
        """
        Parse PyPI JSON response into Package object.

        Parameters
        ----------
        name : str
            Package name.
        data : Dict[str, Any]
            PyPI JSON response data.
        current_version : str, optional
            Current installed or pinned version.

        Returns
        -------
        Package
            Parsed package object with metadata.
        """
        info = data.get("info", {})

        # Get latest version from info (most reliable source)
        latest_version = info.get("version")

        # Get metadata (minimal for Phase 1)
        metadata = {
            "requires_python": info.get("requires_python"),
            "dependencies": self._get_dependencies(info),
        }

        return Package(
            name=name,
            current_version=current_version,
            latest_version=latest_version,
            available_versions=[],  # Not needed for Phase 1
            metadata=metadata,
            last_updated=None,  # Not needed for Phase 1
        )

    # ----------------------------------------------------------------------
    # Metadata Helpers
    # ----------------------------------------------------------------------

    def _get_dependencies(self, info: Dict[str, Any]) -> List[str]:
        """
        Extract dependencies from package info.

        Parameters
        ----------
        info : Dict[str, Any]
            Package info dictionary from PyPI.

        Returns
        -------
        List[str]
            List of dependency strings (without environment markers).
        """
        requires_dist = info.get("requires_dist", [])
        if not requires_dist:
            return []

        # Filter out environment markers for simplicity
        deps: List[str] = []
        for dep in requires_dist:
            # Remove everything after semicolon (markers)
            base_dep = dep.split(";")[0].strip()
            if base_dep:
                deps.append(base_dep)

        return deps

    # ----------------------------------------------------------------------
    # Utility Helpers
    # ----------------------------------------------------------------------

    def _extract_current_version(self, req: Requirement) -> Optional[str]:
        """
        Extract current version from a requirement.

        For pinned versions (==), always returns the exact version.
        For range constraints (>=, >, ~=), returns baseline version only if
        extract_from_ranges is True.

        Parameters
        ----------
        req : Requirement
            Requirement object to extract version from.

        Returns
        -------
        str | None
            Current/baseline version if determinable, otherwise None.
        """
        if not req.specs:
            return None

        # Exact pin: ==1.0.0 (always extract)
        if len(req.specs) == 1 and req.specs[0][0] == "==":
            return req.specs[0][1]

        # Only extract from range constraints if enabled
        if not self.extract_from_ranges:
            return None

        # For >= or > operators, use as baseline/minimum
        # This helps users understand what version constraint exists
        if len(req.specs) == 1:
            operator, version = req.specs[0]
            if operator in (">=", ">", "~="):
                return version

        # For complex specs like ">=1.0,<2.0", try to extract lower bound
        for operator, version in req.specs:
            if operator in (">=", ">", "~="):
                # Return the first lower bound found
                return version

        return None

    def _create_error_package(
        self, name: str, current_version: Optional[str]
    ) -> Package:
        """
        Create an error Package object with empty data.

        Parameters
        ----------
        name : str
            Package name.
        current_version : str, optional
            Current version if known.

        Returns
        -------
        Package
            Package object with no available versions or metadata.
        """
        return Package(
            name=name,
            current_version=current_version,
            latest_version=None,
            available_versions=[],
            metadata={},
            last_updated=None,
        )
