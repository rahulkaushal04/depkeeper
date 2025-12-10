"""
Comprehensive test suite for depkeeper.core.checker module.

Tests cover:
    - Single package checks
    - Multiple package checks (concurrent and with progress)
    - Version queries (latest, all versions)
    - Version filtering with different strategies
    - PyPI metadata fetching and parsing
    - Error handling and edge cases
    - HTTP client integration
    - Context manager behavior
"""

from __future__ import annotations

import pytest
import asyncio
from datetime import datetime
from typing import Dict, Any, List
from unittest.mock import AsyncMock

from depkeeper.utils.http import HTTPClient
from depkeeper.models.package import Package
from depkeeper.core.checker import VersionChecker
from depkeeper.models.requirement import Requirement
from depkeeper.exceptions import PyPIError, NetworkError


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_http_client():
    """Create a mock HTTP client for testing."""
    client = AsyncMock(spec=HTTPClient)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


@pytest.fixture
def sample_pypi_response() -> Dict[str, Any]:
    """Sample PyPI JSON response for testing."""
    return {
        "info": {
            "name": "requests",
            "version": "2.31.0",
            "author": "Kenneth Reitz",
            "summary": "Python HTTP for Humans.",
            "home_page": "https://requests.readthedocs.io",
            "requires_python": ">=3.7",
            "license": "Apache 2.0",
            "requires_dist": [
                "charset-normalizer (<4,>=2)",
                "idna (<4,>=2.5)",
                "urllib3 (<3,>=1.21.1)",
                "certifi (>=2017.4.17)",
            ],
        },
        "releases": {
            "2.28.0": [
                {
                    "filename": "requests-2.28.0-py3-none-any.whl",
                    "upload_time_iso_8601": "2022-05-01T12:00:00Z",
                }
            ],
            "2.28.1": [
                {
                    "filename": "requests-2.28.1-py3-none-any.whl",
                    "upload_time_iso_8601": "2022-06-15T10:30:00Z",
                }
            ],
            "2.29.0": [
                {
                    "filename": "requests-2.29.0-py3-none-any.whl",
                    "upload_time_iso_8601": "2023-01-10T09:00:00Z",
                }
            ],
            "2.30.0": [
                {
                    "filename": "requests-2.30.0-py3-none-any.whl",
                    "upload_time_iso_8601": "2023-05-22T14:20:00Z",
                }
            ],
            "2.31.0": [
                {
                    "filename": "requests-2.31.0-py3-none-any.whl",
                    "upload_time_iso_8601": "2023-05-22T16:00:00Z",
                }
            ],
        },
    }


@pytest.fixture
def sample_pypi_response_empty_releases() -> Dict[str, Any]:
    """Sample PyPI response with no valid releases."""
    return {
        "info": {
            "name": "emptypackage",
            "version": "1.0.0",
            "author": "Test Author",
            "summary": "Empty package for testing.",
        },
        "releases": {},
    }


@pytest.fixture
def sample_requirements() -> List[Requirement]:
    """Sample list of requirements for testing."""
    return [
        Requirement(
            name="requests",
            specs=[("==", "2.28.0")],
            extras=[],
            markers=None,
            url=None,
            editable=False,
            hashes=[],
            comment=None,
            line_number=1,
            raw_line="requests==2.28.0",
        ),
        Requirement(
            name="django",
            specs=[(">=", "4.0"), ("<", "5.0")],
            extras=[],
            markers=None,
            url=None,
            editable=False,
            hashes=[],
            comment=None,
            line_number=2,
            raw_line="django>=4.0,<5.0",
        ),
        Requirement(
            name="flask",
            specs=[],
            extras=[],
            markers=None,
            url=None,
            editable=False,
            hashes=[],
            comment=None,
            line_number=3,
            raw_line="flask",
        ),
    ]


# ============================================================================
# Test VersionChecker Initialization
# ============================================================================


class TestVersionCheckerInitialization:
    """Tests for VersionChecker initialization and configuration."""

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        checker = VersionChecker()

        assert checker.http_client is None
        assert checker.concurrent_limit == 10
        assert checker._owns_http_client is True

    def test_init_with_custom_http_client(self, mock_http_client):
        """Test initialization with custom HTTP client."""
        checker = VersionChecker(http_client=mock_http_client)

        assert checker.http_client == mock_http_client
        assert checker._owns_http_client is False

    def test_init_with_custom_concurrent_limit(self):
        """Test initialization with custom concurrent limit."""
        checker = VersionChecker(concurrent_limit=20)

        assert checker.concurrent_limit == 20
        assert checker._semaphore._value == 20

    def test_semaphore_created(self):
        """Test that semaphore is created with correct limit."""
        checker = VersionChecker(concurrent_limit=5)

        assert checker._semaphore is not None
        assert checker._semaphore._value == 5


# ============================================================================
# Test Context Manager
# ============================================================================


class TestContextManager:
    """Tests for async context manager behavior."""

    @pytest.mark.asyncio
    async def test_context_manager_creates_http_client(self):
        """Test that context manager creates HTTP client when needed."""
        checker = VersionChecker()

        async with checker as ctx:
            assert ctx.http_client is not None
            assert isinstance(ctx.http_client, HTTPClient)

    @pytest.mark.asyncio
    async def test_context_manager_closes_owned_client(self):
        """Test that context manager closes HTTP client it created."""
        checker = VersionChecker()

        async with checker:
            client = checker.http_client
            assert client is not None

        # After exiting context, client should be closed
        # We can't easily test if it's closed without checking internals

    @pytest.mark.asyncio
    async def test_context_manager_does_not_close_provided_client(
        self, mock_http_client
    ):
        """Test that context manager doesn't close provided HTTP client."""
        checker = VersionChecker(http_client=mock_http_client)

        async with checker:
            pass

        # Should not call close on provided client
        mock_http_client.__aexit__.assert_not_called()

    @pytest.mark.asyncio
    async def test_context_manager_reentry(self):
        """Test that context manager can be entered multiple times."""
        checker = VersionChecker()

        async with checker:
            pass

        async with checker:
            pass


# ============================================================================
# Test Single Package Check
# ============================================================================


class TestCheckPackage:
    """Tests for single package checking."""

    @pytest.mark.asyncio
    async def test_check_package_success(self, mock_http_client, sample_pypi_response):
        """Test successful package check."""
        mock_http_client.get_json = AsyncMock(return_value=sample_pypi_response)
        checker = VersionChecker(http_client=mock_http_client)

        package = await checker.check_package("requests", current_version="2.28.0")

        assert package.name == "requests"
        assert package.current_version == "2.28.0"
        assert package.latest_version == "2.31.0"

    @pytest.mark.asyncio
    async def test_check_package_without_current_version(
        self, mock_http_client, sample_pypi_response
    ):
        """Test package check without current version."""
        mock_http_client.get_json = AsyncMock(return_value=sample_pypi_response)
        checker = VersionChecker(http_client=mock_http_client)

        package = await checker.check_package("requests")

        assert package.name == "requests"
        assert package.current_version is None
        assert package.latest_version == "2.31.0"

    @pytest.mark.asyncio
    async def test_check_package_not_found(self, mock_http_client):
        """Test package check when package doesn't exist."""
        mock_http_client.get_json = AsyncMock(
            side_effect=PyPIError("Package not found", package_name="nonexistent")
        )
        checker = VersionChecker(http_client=mock_http_client)

        with pytest.raises(PyPIError) as exc_info:
            await checker.check_package("nonexistent")

        assert "nonexistent" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_check_package_network_error(self, mock_http_client):
        """Test package check with network error."""
        mock_http_client.get_json = AsyncMock(
            side_effect=NetworkError("Connection timeout")
        )
        checker = VersionChecker(http_client=mock_http_client)

        with pytest.raises(PyPIError):
            await checker.check_package("requests")

    @pytest.mark.asyncio
    async def test_check_package_without_http_client(self):
        """Test that check_package raises error without HTTP client."""
        checker = VersionChecker()

        with pytest.raises(RuntimeError, match="HTTP client not initialized"):
            await checker.check_package("requests")

    @pytest.mark.asyncio
    async def test_check_package_respects_semaphore(
        self, mock_http_client, sample_pypi_response
    ):
        """Test that package checks respect concurrent limit."""
        mock_http_client.get_json = AsyncMock(return_value=sample_pypi_response)
        checker = VersionChecker(http_client=mock_http_client, concurrent_limit=1)

        # This should work without deadlock
        package = await checker.check_package("requests")
        assert package.name == "requests"

    @pytest.mark.asyncio
    async def test_check_package_metadata_parsing(
        self, mock_http_client, sample_pypi_response
    ):
        """Test that package metadata is correctly parsed."""
        mock_http_client.get_json = AsyncMock(return_value=sample_pypi_response)
        checker = VersionChecker(http_client=mock_http_client)

        package = await checker.check_package("requests")

        assert package.metadata["requires_python"] == ">=3.7"
        assert len(package.metadata["dependencies"]) == 4
        assert "charset-normalizer (<4,>=2)" in package.metadata["dependencies"]


# ============================================================================
# Test Multiple Package Checks
# ============================================================================


class TestCheckMultiple:
    """Tests for checking multiple packages concurrently."""

    @pytest.mark.asyncio
    async def test_check_multiple_success(
        self, mock_http_client, sample_pypi_response, sample_requirements
    ):
        """Test checking multiple packages successfully."""
        mock_http_client.get_json = AsyncMock(return_value=sample_pypi_response)
        checker = VersionChecker(http_client=mock_http_client)

        packages = await checker.check_multiple(sample_requirements)

        assert len(packages) == 3
        assert all(isinstance(p, Package) for p in packages)
        assert packages[0].name == "requests"

    @pytest.mark.asyncio
    async def test_check_multiple_with_failures(
        self, mock_http_client, sample_pypi_response, sample_requirements
    ):
        """Test checking multiple packages with some failures."""
        # First call succeeds, second fails, third succeeds
        mock_http_client.get_json = AsyncMock(
            side_effect=[
                sample_pypi_response,
                PyPIError("Package not found"),
                sample_pypi_response,
            ]
        )
        checker = VersionChecker(http_client=mock_http_client)

        packages = await checker.check_multiple(sample_requirements)

        assert len(packages) == 3
        # Second package should be error package
        assert packages[1].name == "django"
        assert packages[1].latest_version is None
        assert packages[1].available_versions == []

    @pytest.mark.asyncio
    async def test_check_multiple_empty_list(self, mock_http_client):
        """Test checking empty list of packages."""
        checker = VersionChecker(http_client=mock_http_client)

        packages = await checker.check_multiple([])

        assert packages == []

    @pytest.mark.asyncio
    async def test_check_multiple_concurrent_execution(
        self, mock_http_client, sample_pypi_response, sample_requirements
    ):
        """Test that multiple checks run concurrently."""
        call_times = []

        async def mock_get_json(url):
            call_times.append(asyncio.get_event_loop().time())
            await asyncio.sleep(0.1)  # Simulate network delay
            return sample_pypi_response

        mock_http_client.get_json = mock_get_json
        checker = VersionChecker(http_client=mock_http_client, concurrent_limit=10)

        start_time = asyncio.get_event_loop().time()
        await checker.check_multiple(sample_requirements)
        end_time = asyncio.get_event_loop().time()

        # If concurrent, should take ~0.1s, not 0.3s
        assert end_time - start_time < 0.3


# ============================================================================
# Test PyPI Metadata Fetching
# ============================================================================


class TestFetchPyPIMetadata:
    """Tests for PyPI metadata fetching."""

    @pytest.mark.asyncio
    async def test_fetch_metadata_success(self, mock_http_client, sample_pypi_response):
        """Test successful metadata fetch."""
        mock_http_client.get_json = AsyncMock(return_value=sample_pypi_response)
        checker = VersionChecker(http_client=mock_http_client)

        metadata = await checker._fetch_pypi_metadata("requests")

        assert metadata == sample_pypi_response
        mock_http_client.get_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_metadata_correct_url(
        self, mock_http_client, sample_pypi_response
    ):
        """Test that correct PyPI URL is used."""
        mock_http_client.get_json = AsyncMock(return_value=sample_pypi_response)
        checker = VersionChecker(http_client=mock_http_client)

        await checker._fetch_pypi_metadata("requests")

        call_args = mock_http_client.get_json.call_args[0][0]
        assert "https://pypi.org/pypi/requests/json" in call_args

    @pytest.mark.asyncio
    async def test_fetch_metadata_pypi_error(self, mock_http_client):
        """Test metadata fetch with PyPI error."""
        mock_http_client.get_json = AsyncMock(
            side_effect=PyPIError("Package not found", package_name="nonexistent")
        )
        checker = VersionChecker(http_client=mock_http_client)

        with pytest.raises(PyPIError) as exc_info:
            await checker._fetch_pypi_metadata("nonexistent")

        assert "nonexistent" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fetch_metadata_generic_error(self, mock_http_client):
        """Test metadata fetch with generic error."""
        mock_http_client.get_json = AsyncMock(side_effect=Exception("Connection error"))
        checker = VersionChecker(http_client=mock_http_client)

        with pytest.raises(PyPIError) as exc_info:
            await checker._fetch_pypi_metadata("requests")

        assert "Failed to fetch PyPI metadata" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fetch_metadata_no_http_client(self):
        """Test metadata fetch without HTTP client."""
        checker = VersionChecker()

        with pytest.raises(RuntimeError, match="HTTP client not initialized"):
            await checker._fetch_pypi_metadata("requests")


# ============================================================================
# Test Package Data Parsing
# ============================================================================


class TestParsePackageData:
    """Tests for parsing PyPI response data into Package objects."""

    def test_parse_package_data_complete(self, sample_pypi_response):
        """Test parsing complete package data."""
        checker = VersionChecker()

        package = checker._parse_package_data(
            "requests", sample_pypi_response, current_version="2.28.0"
        )

        assert package.name == "requests"
        assert package.current_version == "2.28.0"
        assert package.latest_version == "2.31.0"

    def test_parse_package_data_without_current_version(self, sample_pypi_response):
        """Test parsing package data without current version."""
        checker = VersionChecker()

        package = checker._parse_package_data("requests", sample_pypi_response)

        assert package.name == "requests"
        assert package.current_version is None
        assert package.latest_version == "2.31.0"

    def test_parse_package_data_metadata_fields(self, sample_pypi_response):
        """Test that all metadata fields are correctly parsed."""
        checker = VersionChecker()

        package = checker._parse_package_data("requests", sample_pypi_response)

        assert package.metadata["requires_python"] == ">=3.7"
        assert len(package.metadata["dependencies"]) == 4

    def test_parse_package_data_missing_info(self):
        """Test parsing with missing info section."""
        checker = VersionChecker()
        data = {"info": {}, "releases": {}}

        package = checker._parse_package_data("testpkg", data)

        assert package.name == "testpkg"
        assert package.latest_version is None

    def test_parse_package_data_empty_releases(
        self, sample_pypi_response_empty_releases
    ):
        """Test parsing with empty releases."""
        checker = VersionChecker()

        package = checker._parse_package_data(
            "emptypackage", sample_pypi_response_empty_releases
        )

        assert package.name == "emptypackage"
        assert len(package.available_versions) == 0


# ============================================================================
# Test Metadata Helpers
# ============================================================================


class TestGetDependencies:
    """Tests for extracting dependencies from package info."""

    def test_get_dependencies_success(self):
        """Test extracting dependencies successfully."""
        checker = VersionChecker()
        info = {
            "requires_dist": [
                "requests (>=2.20.0)",
                "click (>=7.0)",
                "pytest (>=5.0) ; extra == 'dev'",
            ]
        }

        deps = checker._get_dependencies(info)

        assert len(deps) == 3
        assert "requests (>=2.20.0)" in deps
        assert "click (>=7.0)" in deps
        assert "pytest (>=5.0)" in deps  # Marker removed

    def test_get_dependencies_with_markers(self):
        """Test that environment markers are removed."""
        checker = VersionChecker()
        info = {
            "requires_dist": [
                'typing-extensions ; python_version<"3.8"',
                'importlib-metadata ; python_version<"3.8"',
            ]
        }

        deps = checker._get_dependencies(info)

        assert len(deps) == 2
        assert all(";" not in dep for dep in deps)
        assert "typing-extensions" in deps[0]
        assert "importlib-metadata" in deps[1]

    def test_get_dependencies_empty(self):
        """Test extracting dependencies when none exist."""
        checker = VersionChecker()
        info = {"requires_dist": []}

        deps = checker._get_dependencies(info)

        assert deps == []

    def test_get_dependencies_missing_field(self):
        """Test extracting dependencies when field is missing."""
        checker = VersionChecker()
        info = {}

        deps = checker._get_dependencies(info)

        assert deps == []

    def test_get_dependencies_none_value(self):
        """Test extracting dependencies when value is None."""
        checker = VersionChecker()
        info = {"requires_dist": None}

        deps = checker._get_dependencies(info)

        assert deps == []


# ============================================================================
# Test Utility Helpers
# ============================================================================


class TestExtractCurrentVersion:
    """Tests for extracting current version from requirements."""

    def test_extract_current_version_pinned(self):
        """Test extracting version from pinned requirement."""
        checker = VersionChecker()
        req = Requirement(
            name="requests",
            specs=[("==", "2.28.0")],
            extras=[],
            markers=None,
            url=None,
            editable=False,
            hashes=[],
            comment=None,
            line_number=1,
            raw_line="requests==2.28.0",
        )

        version = checker._extract_current_version(req)

        assert version == "2.28.0"

    def test_extract_current_version_unpinned(self):
        """Test extracting version from unpinned requirement with default behavior."""
        # Default: extract_from_ranges=True, should extract baseline version
        checker = VersionChecker()
        req = Requirement(
            name="requests",
            specs=[(">=", "2.28.0")],
            extras=[],
            markers=None,
            url=None,
            editable=False,
            hashes=[],
            comment=None,
            line_number=1,
            raw_line="requests>=2.28.0",
        )

        version = checker._extract_current_version(req)

        assert version == "2.28.0"

    def test_extract_current_version_unpinned_strict_mode(self):
        """Test extracting version from unpinned requirement with strict mode."""
        # Strict mode: extract_from_ranges=False, should return None for unpinned
        checker = VersionChecker(extract_from_ranges=False)
        req = Requirement(
            name="requests",
            specs=[(">=", "2.28.0")],
            extras=[],
            markers=None,
            url=None,
            editable=False,
            hashes=[],
            comment=None,
            line_number=1,
            raw_line="requests>=2.28.0",
        )

        version = checker._extract_current_version(req)

        assert version is None

    def test_extract_current_version_no_specs(self):
        """Test extracting version from requirement without specs."""
        checker = VersionChecker()
        req = Requirement(
            name="requests",
            specs=[],
            extras=[],
            markers=None,
            url=None,
            editable=False,
            hashes=[],
            comment=None,
            line_number=1,
            raw_line="requests",
        )

        version = checker._extract_current_version(req)

        assert version is None

    def test_extract_current_version_multiple_specs(self):
        """Test extracting version from requirement with multiple specs with default behavior."""
        # Default: extract_from_ranges=True, should extract lower bound
        checker = VersionChecker()
        req = Requirement(
            name="django",
            specs=[(">=", "4.0"), ("<", "5.0")],
            extras=[],
            markers=None,
            url=None,
            editable=False,
            hashes=[],
            comment=None,
            line_number=1,
            raw_line="django>=4.0,<5.0",
        )

        version = checker._extract_current_version(req)

        assert version == "4.0"

    def test_extract_current_version_multiple_specs_strict_mode(self):
        """Test extracting version from requirement with multiple specs in strict mode."""
        # Strict mode: extract_from_ranges=False, should return None for ranges
        checker = VersionChecker(extract_from_ranges=False)
        req = Requirement(
            name="django",
            specs=[(">=", "4.0"), ("<", "5.0")],
            extras=[],
            markers=None,
            url=None,
            editable=False,
            hashes=[],
            comment=None,
            line_number=1,
            raw_line="django>=4.0,<5.0",
        )

        version = checker._extract_current_version(req)

        assert version is None

    def test_extract_current_version_greater_than(self):
        """Test extracting version from > operator."""
        checker = VersionChecker()
        req = Requirement(
            name="flask",
            specs=[(">", "2.0.0")],
            extras=[],
            markers=None,
            url=None,
            editable=False,
            hashes=[],
            comment=None,
            line_number=1,
            raw_line="flask>2.0.0",
        )

        version = checker._extract_current_version(req)

        assert version == "2.0.0"

    def test_extract_current_version_compatible(self):
        """Test extracting version from ~= operator."""
        checker = VersionChecker()
        req = Requirement(
            name="click",
            specs=[("~=", "8.0")],
            extras=[],
            markers=None,
            url=None,
            editable=False,
            hashes=[],
            comment=None,
            line_number=1,
            raw_line="click~=8.0",
        )

        version = checker._extract_current_version(req)

        assert version == "8.0"


class TestCreateErrorPackage:
    """Tests for creating error package objects."""

    def test_create_error_package_with_version(self):
        """Test creating error package with current version."""
        checker = VersionChecker()

        package = checker._create_error_package("testpkg", "1.0.0")

        assert package.name == "testpkg"
        assert package.current_version == "1.0.0"
        assert package.latest_version is None
        assert package.available_versions == []
        assert package.metadata == {}

    def test_create_error_package_without_version(self):
        """Test creating error package without current version."""
        checker = VersionChecker()

        package = checker._create_error_package("testpkg", None)

        assert package.name == "testpkg"
        assert package.current_version is None
        assert package.latest_version is None

    def test_create_error_package_structure(self):
        """Test that error package has correct structure."""
        checker = VersionChecker()

        package = checker._create_error_package("testpkg", "1.0.0")

        assert isinstance(package, Package)
        assert hasattr(package, "name")
        assert hasattr(package, "current_version")
        assert hasattr(package, "latest_version")
        assert hasattr(package, "available_versions")
        assert hasattr(package, "metadata")
        assert hasattr(package, "last_updated")


# ============================================================================
# Test Edge Cases and Error Handling
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and unusual scenarios."""

    @pytest.mark.asyncio
    async def test_malformed_pypi_response(self, mock_http_client):
        """Test handling of malformed PyPI response."""
        mock_http_client.get_json = AsyncMock(return_value={})
        checker = VersionChecker(http_client=mock_http_client)

        package = await checker.check_package("testpkg")

        # Should not crash, return package with empty data
        assert package.name == "testpkg"
        assert package.latest_version is None

    @pytest.mark.asyncio
    async def test_pypi_response_missing_releases(self, mock_http_client):
        """Test handling PyPI response without releases."""
        mock_http_client.get_json = AsyncMock(
            return_value={"info": {"name": "test", "version": "1.0.0"}}
        )
        checker = VersionChecker(http_client=mock_http_client)

        package = await checker.check_package("test")

        assert package.name == "test"
        assert len(package.available_versions) == 0

    @pytest.mark.asyncio
    async def test_unicode_in_package_data(self, mock_http_client):
        """Test handling Unicode characters in package data."""
        response = {
            "info": {
                "name": "testpkg",
                "version": "1.0.0",
                "summary": "Test package with 中文 and émojis ��",
                "author": "Tëst Authör",
            },
            "releases": {
                "1.0.0": [
                    {
                        "filename": "test.whl",
                        "upload_time_iso_8601": "2023-01-01T00:00:00Z",
                    }
                ]
            },
        }
        mock_http_client.get_json = AsyncMock(return_value=response)
        checker = VersionChecker(http_client=mock_http_client)

        package = await checker.check_package("testpkg")

        assert package.name == "testpkg"

    @pytest.mark.asyncio
    async def test_very_large_version_list(self, mock_http_client):
        """Test handling package with many versions."""
        releases = {
            f"1.0.{i}": [
                {
                    "filename": f"test-1.0.{i}.whl",
                    "upload_time_iso_8601": "2023-01-01T00:00:00Z",
                }
            ]
            for i in range(100)
        }
        response = {
            "info": {"name": "testpkg", "version": "1.0.99"},
            "releases": releases,
        }
        mock_http_client.get_json = AsyncMock(return_value=response)
        checker = VersionChecker(http_client=mock_http_client)

        package = await checker.check_package("testpkg")

        assert package.latest_version == "1.0.99"

    @pytest.mark.asyncio
    async def test_package_name_normalization(
        self, mock_http_client, sample_pypi_response
    ):
        """Test that package names are handled consistently."""
        mock_http_client.get_json = AsyncMock(return_value=sample_pypi_response)
        checker = VersionChecker(http_client=mock_http_client)

        # Different name formats should work
        package1 = await checker.check_package("requests")
        package2 = await checker.check_package("Requests")
        package3 = await checker.check_package("REQUESTS")

        assert package1.name == "requests"
        assert package2.name == "requests"
        assert package3.name == "requests"

    @pytest.mark.asyncio
    async def test_concurrent_limit_respected(
        self, mock_http_client, sample_pypi_response
    ):
        """Test that concurrent limit is respected."""
        call_count = 0
        max_concurrent = 0
        current_concurrent = 0

        async def mock_get_json(url):
            nonlocal call_count, max_concurrent, current_concurrent
            current_concurrent += 1
            max_concurrent = max(max_concurrent, current_concurrent)
            call_count += 1
            await asyncio.sleep(0.01)
            current_concurrent -= 1
            return sample_pypi_response

        mock_http_client.get_json = mock_get_json
        checker = VersionChecker(http_client=mock_http_client, concurrent_limit=2)

        requirements = [
            Requirement(
                name=f"package{i}",
                specs=[],
                extras=[],
                markers=None,
                url=None,
                editable=False,
                hashes=[],
                comment=None,
                line_number=i,
                raw_line=f"package{i}",
            )
            for i in range(5)
        ]

        await checker.check_multiple(requirements)

        assert call_count == 5
        assert max_concurrent <= 2


# ============================================================================
# Test Integration Scenarios
# ============================================================================


class TestIntegrationScenarios:
    """Integration tests for complete workflows."""

    @pytest.mark.asyncio
    async def test_full_check_workflow(self, mock_http_client, sample_pypi_response):
        """Test complete workflow from init to package check."""
        mock_http_client.get_json = AsyncMock(return_value=sample_pypi_response)

        async with VersionChecker(http_client=mock_http_client) as checker:
            # Check single package
            package = await checker.check_package("requests", "2.28.0")
            assert package.name == "requests"
            assert package.current_version == "2.28.0"
            assert package.latest_version == "2.31.0"

    @pytest.mark.asyncio
    async def test_multiple_packages_workflow(
        self, mock_http_client, sample_pypi_response, sample_requirements
    ):
        """Test workflow for checking multiple packages."""
        mock_http_client.get_json = AsyncMock(return_value=sample_pypi_response)

        async with VersionChecker(http_client=mock_http_client) as checker:
            packages = await checker.check_multiple(sample_requirements)

            assert len(packages) == len(sample_requirements)
            for pkg in packages:
                assert isinstance(pkg, Package)
                assert pkg.name is not None

    @pytest.mark.asyncio
    async def test_error_recovery_workflow(
        self, mock_http_client, sample_pypi_response
    ):
        """Test workflow with errors and recovery."""
        # Simulate intermittent failures
        call_count = 0

        async def mock_get_json(url):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise PyPIError("Temporary error")
            return sample_pypi_response

        mock_http_client.get_json = mock_get_json

        async with VersionChecker(http_client=mock_http_client) as checker:
            # First call succeeds
            pkg1 = await checker.check_package("requests")
            assert pkg1.name == "requests"

            # Second call fails
            with pytest.raises(PyPIError):
                await checker.check_package("django")

            # Third call succeeds
            pkg3 = await checker.check_package("flask")
            assert pkg3.name == "flask"
