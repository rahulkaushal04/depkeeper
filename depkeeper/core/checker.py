from __future__ import annotations

import asyncio
from datetime import datetime
from packaging.version import parse
from typing import Any, Dict, List, Optional

from depkeeper.exceptions import PyPIError
from depkeeper.utils.http import HTTPClient
from depkeeper.models.package import Package
from depkeeper.utils.logger import get_logger
from depkeeper.models.version import VersionInfo
from depkeeper.models.requirement import Requirement
from depkeeper.constants import PYPI_JSON_API, UpdateStrategy

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
        """
        self.http_client = http_client
        self.concurrent_limit = concurrent_limit
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
        show_progress: bool = False,
    ) -> List[Package]:
        """
        Check multiple packages concurrently.

        Parameters
        ----------
        requirements : List[Requirement]
            List of requirements to check.
        show_progress : bool, optional
            Whether to display a progress bar. Default is False.

        Returns
        -------
        List[Package]
            List of packages with version information. If a package check
            fails, an empty Package object is returned for that package.
        """
        if show_progress:
            return await self._check_multiple_with_progress(requirements)
        else:
            return await self._check_multiple_concurrent(requirements)

    async def _check_multiple_with_progress(
        self, requirements: List[Requirement]
    ) -> List[Package]:
        """Check multiple packages with progress bar display."""
        try:
            from rich.console import Console
            from rich.progress import Progress
        except ImportError:
            logger.warning("rich not installed; falling back to no progress bar")
            return await self._check_multiple_concurrent(requirements)

        console = Console()
        packages: List[Package] = []

        with Progress(console=console) as progress:
            task = progress.add_task(
                "[cyan]Checking packages...",
                total=len(requirements),
            )

            for req in requirements:
                current = self._extract_current_version(req)
                try:
                    package = await self.check_package(req.name, current)
                    packages.append(package)

                except Exception as exc:
                    logger.error(f"Failed to check {req.name}: {exc}")
                    packages.append(self._create_error_package(req.name, current))

                finally:
                    progress.advance(task)

        return packages

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
    # Version Queries
    # ----------------------------------------------------------------------

    async def get_latest_version(
        self,
        name: str,
        include_pre_release: bool = False,
    ) -> Optional[VersionInfo]:
        """
        Get latest stable version of a package.

        Parameters
        ----------
        name : str
            Package name.
        include_pre_release : bool, optional
            Whether to include pre-release versions. Default is False.

        Returns
        -------
        VersionInfo | None
            Latest version or None if not found.
        """
        try:
            package = await self.check_package(name)

            if not package.available_versions:
                return None

            # Parse and filter versions
            versions = [VersionInfo(v) for v in package.available_versions]

            if not include_pre_release:
                versions = [v for v in versions if v.is_stable]

            if not versions:
                return None

            return max(versions)

        except Exception as exc:
            logger.error(f"Failed to get latest version for {name}: {exc}")
            return None

    async def get_all_versions(self, name: str) -> List[VersionInfo]:
        """
        Get all available versions of a package.

        Parameters
        ----------
        name : str
            Package name.

        Returns
        -------
        List[VersionInfo]
            List of all published versions, sorted oldest to newest.
        """
        try:
            package = await self.check_package(name)
            return [VersionInfo(v) for v in package.available_versions]

        except Exception as exc:
            logger.error(f"Failed to get versions for {name}: {exc}")
            return []

    # ----------------------------------------------------------------------
    # Version Filtering
    # ----------------------------------------------------------------------

    def filter_versions(
        self,
        versions: List[VersionInfo],
        current: VersionInfo,
        strategy: UpdateStrategy = UpdateStrategy.MODERATE,
    ) -> List[VersionInfo]:
        """
        Filter versions based on update strategy.

        Parameters
        ----------
        versions : List[VersionInfo]
            List of available versions to filter.
        current : VersionInfo
            Current version as baseline for comparison.
        strategy : UpdateStrategy, optional
            Update strategy to apply. Default is MODERATE.

        Returns
        -------
        List[VersionInfo]
            Filtered list of versions matching the strategy.
        """
        if strategy == UpdateStrategy.CONSERVATIVE:
            # Only patch updates (same major.minor)
            return [
                v
                for v in versions
                if v > current and v.major == current.major and v.minor == current.minor
            ]

        elif strategy == UpdateStrategy.MODERATE:
            # Minor and patch updates (same major)
            return [v for v in versions if v > current and v.major == current.major]

        elif strategy == UpdateStrategy.AGGRESSIVE:
            # All newer versions including major updates
            return [v for v in versions if v > current]

        else:  # CUSTOM or unknown
            # Return all newer versions (same as AGGRESSIVE)
            return [v for v in versions if v > current]

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
                package=name,
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
        releases = data.get("releases", {})

        # Parse versions
        available_versions = self._parse_versions(releases)

        # Get latest version
        latest_version = info.get("version")

        # Get metadata
        metadata = {
            "upload_date": self._get_upload_date(releases, latest_version),
            "maintainer": info.get("author") or info.get("maintainer"),
            "requires_python": info.get("requires_python"),
            "dependencies": self._get_dependencies(info),
            "homepage_url": (
                info.get("home_page")
                or info.get("project_url")
                or info.get("package_url")
            ),
            "summary": info.get("summary"),
            "license": info.get("license"),
        }

        # Get last updated date
        last_updated = None
        if latest_version and latest_version in releases:
            release_files = releases[latest_version]
            if release_files:
                upload_time = release_files[0].get("upload_time_iso_8601")
                if upload_time:
                    try:
                        last_updated = datetime.fromisoformat(
                            upload_time.replace("Z", "+00:00")
                        )
                    except Exception:
                        pass

        return Package(
            name=name,
            current_version=current_version,
            latest_version=latest_version,
            available_versions=available_versions,
            metadata=metadata,
            last_updated=last_updated,
        )

    def _parse_versions(self, releases: Dict[str, List]) -> List[str]:
        """
        Extract and sort version list from releases.

        Parameters
        ----------
        releases : Dict[str, List]
            Releases dictionary from PyPI.

        Returns
        -------
        List[str]
            Sorted list of valid version strings (oldest to newest).
        """
        versions: List[str] = []

        for version_str, files in releases.items():
            # Skip versions with no files
            if not files:
                continue

            try:
                # Validate version string
                parse(version_str)
                versions.append(version_str)
            except Exception:
                logger.warning(f"Invalid version string: {version_str}")
                continue

        # Sort versions
        try:
            versions.sort(key=lambda v: parse(v))
        except Exception as exc:
            logger.warning(f"Failed to sort versions: {exc}")

        return versions

    # ----------------------------------------------------------------------
    # Metadata Helpers
    # ----------------------------------------------------------------------

    def _get_upload_date(
        self, releases: Dict[str, List], version: Optional[str]
    ) -> Optional[str]:
        """
        Get upload date for a specific version.

        Parameters
        ----------
        releases : Dict[str, List]
            Releases dictionary from PyPI.
        version : str, optional
            Version string to get upload date for.

        Returns
        -------
        str | None
            Upload date string (ISO 8601) or None if not found.
        """
        if not version or version not in releases:
            return None

        files = releases[version]
        if not files:
            return None

        return files[0].get("upload_time_iso_8601")

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

        Parameters
        ----------
        req : Requirement
            Requirement object to extract version from.

        Returns
        -------
        str | None
            Current version if pinned, otherwise None.
        """
        if req.specs and len(req.specs) == 1 and req.specs[0][0] == "==":
            return req.specs[0][1]
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
