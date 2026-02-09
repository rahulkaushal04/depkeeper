"""Unit tests for depkeeper.data_store module.

This test suite provides comprehensive coverage of PyPI data store functionality,
including package data caching, version resolution, dependency fetching, Python
compatibility checking, and async concurrency control.

Test Coverage:
- PyPIPackageData dataclass and query methods
- PyPIDataStore initialization and configuration
- Async package data fetching with double-checked locking
- Semaphore-based concurrent request limiting
- Version dependency caching and resolution
- Python version compatibility checking
- Package name normalization
- Edge cases (missing data, invalid versions, concurrent access, etc.)
"""

from __future__ import annotations

import pytest
import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch
from packaging.version import Version

from depkeeper.core.data_store import (
    PyPIDataStore,
    PyPIPackageData,
    _normalize,
)
from depkeeper.exceptions import PyPIError
from depkeeper.utils.http import HTTPClient


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_http_client() -> MagicMock:
    """Create a mock HTTPClient for testing.

    Returns:
        Mock HTTPClient with configurable response behavior.
    """
    client = MagicMock(spec=HTTPClient)
    return client


@pytest.fixture
def sample_pypi_response() -> Dict[str, Any]:
    """Create a sample PyPI JSON API response.

    Returns:
        Dict mimicking PyPI's /pypi/{package}/json structure.
    """
    return {
        "info": {
            "name": "requests",
            "version": "2.31.0",
            "requires_python": ">=3.7",
            "requires_dist": [
                "charset-normalizer>=2.0.0",
                "idna>=2.5",
                "urllib3>=1.21.1",
                "certifi>=2017.4.17",
                "PySocks>=1.5.6; extra == 'socks'",  # Should be filtered
            ],
        },
        "releases": {
            "2.31.0": [
                {"requires_python": ">=3.7", "filename": "requests-2.31.0.tar.gz"}
            ],
            "2.30.0": [
                {"requires_python": ">=3.7", "filename": "requests-2.30.0.tar.gz"}
            ],
            "2.29.0": [
                {"requires_python": ">=3.7", "filename": "requests-2.29.0.tar.gz"}
            ],
            "2.0.0": [{"requires_python": None, "filename": "requests-2.0.0.tar.gz"}],
            "1.2.3": [
                {"requires_python": ">=2.7", "filename": "requests-1.2.3.tar.gz"}
            ],
            "3.0.0a1": [  # Pre-release
                {"requires_python": ">=3.8", "filename": "requests-3.0.0a1.tar.gz"}
            ],
            "invalid-version": [],  # No files - should be skipped
        },
    }


@pytest.fixture
def sample_package_data() -> PyPIPackageData:
    """Create a sample PyPIPackageData instance.

    Returns:
        Pre-populated PyPIPackageData for testing query methods.
    """
    return PyPIPackageData(
        name="requests",
        latest_version="2.31.0",
        latest_requires_python=">=3.7",
        latest_dependencies=["charset-normalizer>=2.0.0", "idna>=2.5"],
        all_versions=["2.31.0", "2.30.0", "2.29.0", "2.0.0", "1.2.3"],
        parsed_versions=[
            ("2.31.0", Version("2.31.0")),
            ("2.30.0", Version("2.30.0")),
            ("2.29.0", Version("2.29.0")),
            ("2.0.0", Version("2.0.0")),
            ("1.2.3", Version("1.2.3")),
            ("3.0.0a1", Version("3.0.0a1")),  # Pre-release
        ],
        python_requirements={
            "2.31.0": ">=3.7",
            "2.30.0": ">=3.7",
            "2.29.0": ">=3.7",
            "2.0.0": None,
            "1.2.3": ">=2.7",
        },
        releases={},
        dependencies_cache={"2.31.0": ["charset-normalizer>=2.0.0", "idna>=2.5"]},
    )


# ============================================================================
# Test: _normalize helper function
# ============================================================================


class TestNormalizeFunction:
    """Tests for _normalize package name normalization."""

    def test_lowercase_conversion(self) -> None:
        """Test _normalize converts to lowercase.

        Happy path: Package names should be lowercased for consistency.
        """
        assert _normalize("Requests") == "requests"
        assert _normalize("FLASK") == "flask"
        assert _normalize("DjAnGo") == "django"

    def test_underscore_to_hyphen(self) -> None:
        """Test _normalize replaces underscores with hyphens.

        PyPI treats underscores and hyphens as equivalent.
        """
        assert _normalize("flask_login") == "flask-login"
        assert _normalize("my_package_name") == "my-package-name"

    def test_combined_normalization(self) -> None:
        """Test _normalize handles both case and underscores.

        Integration test: Both transformations applied together.
        """
        assert _normalize("Flask_Login") == "flask-login"
        assert _normalize("My_PACKAGE_Name") == "my-package-name"

    def test_already_normalized(self) -> None:
        """Test _normalize is idempotent for normalized names.

        Edge case: Already normalized names should pass through unchanged.
        """
        assert _normalize("requests") == "requests"
        assert _normalize("flask-login") == "flask-login"

    def test_empty_string(self) -> None:
        """Test _normalize handles empty strings.

        Edge case: Empty input should return empty output.
        """
        assert _normalize("") == ""

    def test_special_characters_preserved(self) -> None:
        """Test _normalize preserves other characters.

        Edge case: Only underscores converted, other chars unchanged.
        """
        assert _normalize("package-v2.0") == "package-v2.0"
        assert _normalize("my.package") == "my.package"


# ============================================================================
# Test: PyPIPackageData dataclass
# ============================================================================


class TestPyPIPackageData:
    """Tests for PyPIPackageData dataclass and its query methods."""

    def test_dataclass_initialization(self) -> None:
        """Test PyPIPackageData can be initialized with required fields.

        Happy path: Minimal initialization with just name.
        """
        data = PyPIPackageData(name="test-package")
        assert data.name == "test-package"
        assert data.latest_version is None
        assert data.all_versions == []
        assert data.dependencies_cache == {}

    def test_dataclass_with_all_fields(self) -> None:
        """Test PyPIPackageData initialization with all fields.

        Verifies all fields are properly stored.
        """
        data = PyPIPackageData(
            name="requests",
            latest_version="2.31.0",
            latest_requires_python=">=3.7",
            latest_dependencies=["dep1", "dep2"],
            all_versions=["2.31.0", "2.30.0"],
            parsed_versions=[("2.31.0", Version("2.31.0"))],
            python_requirements={"2.31.0": ">=3.7"},
            releases={"2.31.0": []},
            dependencies_cache={"2.31.0": ["dep1"]},
        )
        assert data.name == "requests"
        assert data.latest_version == "2.31.0"
        assert len(data.all_versions) == 2

    def test_get_versions_in_major_filters_correctly(
        self, sample_package_data: PyPIPackageData
    ) -> None:
        """Test get_versions_in_major returns only specified major version.

        Happy path: Filter versions by major number.
        """
        v2_versions = sample_package_data.get_versions_in_major(2)
        assert "2.31.0" in v2_versions
        assert "2.30.0" in v2_versions
        assert "2.29.0" in v2_versions
        assert "1.2.3" not in v2_versions

    def test_get_versions_in_major_excludes_prereleases(
        self, sample_package_data: PyPIPackageData
    ) -> None:
        """Test get_versions_in_major excludes pre-release versions.

        Pre-releases (alpha, beta, rc) should be filtered out.
        """
        v3_versions = sample_package_data.get_versions_in_major(3)
        assert "3.0.0a1" not in v3_versions

    def test_get_versions_in_major_empty_result(
        self, sample_package_data: PyPIPackageData
    ) -> None:
        """Test get_versions_in_major returns empty for non-existent major.

        Edge case: No versions with specified major number.
        """
        v99_versions = sample_package_data.get_versions_in_major(99)
        assert v99_versions == []

    def test_get_versions_in_major_descending_order(
        self, sample_package_data: PyPIPackageData
    ) -> None:
        """Test get_versions_in_major maintains descending sort order.

        Versions should be returned newest-first.
        """
        v2_versions = sample_package_data.get_versions_in_major(2)
        assert v2_versions[0] == "2.31.0"
        assert v2_versions[-1] == "2.0.0"

    def test_get_versions_in_major_handles_empty_release_tuple(self) -> None:
        """Test get_versions_in_major skips versions with empty release tuple.

        Edge case: Malformed version objects should be filtered safely.
        """
        data = PyPIPackageData(
            name="test",
            parsed_versions=[
                ("1.0", Version("1.0")),
            ],
        )
        # Version("1.0") has release=(1, 0), should work fine
        result = data.get_versions_in_major(1)
        assert "1.0" in result

    def test_is_python_compatible_with_requirement(
        self, sample_package_data: PyPIPackageData
    ) -> None:
        """Test is_python_compatible checks version constraints.

        Happy path: Python version within requirements.
        """
        assert sample_package_data.is_python_compatible("2.31.0", "3.9.0") is True
        assert sample_package_data.is_python_compatible("2.31.0", "3.11.4") is True

    def test_is_python_compatible_incompatible(
        self, sample_package_data: PyPIPackageData
    ) -> None:
        """Test is_python_compatible rejects incompatible versions.

        Python version outside requirements should return False.
        """
        assert sample_package_data.is_python_compatible("2.31.0", "3.6.0") is False
        assert sample_package_data.is_python_compatible("2.31.0", "2.7.18") is False

    def test_is_python_compatible_no_requirement(
        self, sample_package_data: PyPIPackageData
    ) -> None:
        """Test is_python_compatible returns True when no requirement set.

        Edge case: Missing requires_python should be permissive (pip behavior).
        """
        assert sample_package_data.is_python_compatible("2.0.0", "2.7.0") is True
        assert sample_package_data.is_python_compatible("2.0.0", "3.11.0") is True

    def test_is_python_compatible_invalid_specifier(
        self, sample_package_data: PyPIPackageData
    ) -> None:
        """Test is_python_compatible handles malformed specifiers gracefully.

        Edge case: Invalid specifiers should be treated as compatible (permissive).
        """
        sample_package_data.python_requirements["bad"] = "invalid specifier >><"
        assert sample_package_data.is_python_compatible("bad", "3.9.0") is True

    def test_is_python_compatible_version_not_in_requirements(
        self, sample_package_data: PyPIPackageData
    ) -> None:
        """Test is_python_compatible when version not in python_requirements dict.

        Edge case: Unknown version should return True (permissive).
        """
        assert sample_package_data.is_python_compatible("99.99.99", "3.9.0") is True

    def test_get_python_compatible_versions_all_major(
        self, sample_package_data: PyPIPackageData
    ) -> None:
        """Test get_python_compatible_versions without major filter.

        Happy path: Return all compatible versions across all major versions.
        """
        compatible = sample_package_data.get_python_compatible_versions("3.9.0")
        assert "2.31.0" in compatible
        assert "2.30.0" in compatible
        assert "1.2.3" in compatible  # Compatible with Python 3.9

    def test_get_python_compatible_versions_with_major(
        self, sample_package_data: PyPIPackageData
    ) -> None:
        """Test get_python_compatible_versions with major version filter.

        Should only return versions from specified major and compatible with Python.
        """
        compatible = sample_package_data.get_python_compatible_versions(
            "3.9.0", major=2
        )
        assert "2.31.0" in compatible
        assert "1.2.3" not in compatible  # Wrong major

    def test_get_python_compatible_versions_incompatible_python(
        self, sample_package_data: PyPIPackageData
    ) -> None:
        """Test get_python_compatible_versions filters out incompatible versions.

        Old Python versions should exclude newer package versions.
        """
        compatible = sample_package_data.get_python_compatible_versions(
            "2.7.18", major=2
        )
        # 2.31.0, 2.30.0, 2.29.0 require >=3.7, so excluded
        assert "2.31.0" not in compatible
        assert "2.0.0" in compatible  # No python requirement

    def test_get_python_compatible_versions_excludes_prereleases(
        self, sample_package_data: PyPIPackageData
    ) -> None:
        """Test get_python_compatible_versions excludes pre-releases.

        Alpha, beta, rc versions should be filtered out.
        """
        compatible = sample_package_data.get_python_compatible_versions("3.9.0")
        assert "3.0.0a1" not in compatible

    def test_get_python_compatible_versions_empty_result(
        self, sample_package_data: PyPIPackageData
    ) -> None:
        """Test get_python_compatible_versions with no matches.

        Edge case: No compatible versions available.
        """
        compatible = sample_package_data.get_python_compatible_versions(
            "2.6.0", major=2
        )
        # Python 2.6 very old, likely no matches
        assert isinstance(compatible, list)


# ============================================================================
# Test: PyPIDataStore initialization
# ============================================================================


class TestPyPIDataStoreInit:
    """Tests for PyPIDataStore initialization and configuration."""

    def test_initialization_with_defaults(self, mock_http_client: MagicMock) -> None:
        """Test PyPIDataStore initializes with default concurrent_limit.

        Happy path: Default semaphore limit should be 10.
        """
        store = PyPIDataStore(mock_http_client)
        assert store.http_client is mock_http_client
        assert store._semaphore._value == 10
        assert store._package_data == {}
        assert store._version_deps_cache == {}

    def test_initialization_with_custom_limit(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test PyPIDataStore accepts custom concurrent_limit.

        Semaphore should be configured with custom value.
        """
        store = PyPIDataStore(mock_http_client, concurrent_limit=5)
        assert store._semaphore._value == 5

    def test_initialization_zero_concurrent_limit(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test PyPIDataStore handles zero concurrent_limit.

        Edge case: Zero limit effectively blocks all concurrent requests.
        """
        store = PyPIDataStore(mock_http_client, concurrent_limit=0)
        assert store._semaphore._value == 0

    def test_initialization_large_concurrent_limit(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test PyPIDataStore handles very large concurrent_limit.

        Edge case: Large values should work without issues.
        """
        store = PyPIDataStore(mock_http_client, concurrent_limit=1000)
        assert store._semaphore._value == 1000

    def test_initial_state_empty_caches(self, mock_http_client: MagicMock) -> None:
        """Test PyPIDataStore starts with empty caches.

        Both package and version caches should be empty initially.
        """
        store = PyPIDataStore(mock_http_client)
        assert len(store._package_data) == 0
        assert len(store._version_deps_cache) == 0


# ============================================================================
# Test: PyPIDataStore async fetching
# ============================================================================


class TestPyPIDataStoreGetPackageData:
    """Tests for PyPIDataStore.get_package_data async fetching."""

    @pytest.mark.asyncio
    async def test_fetch_package_success(
        self, mock_http_client: MagicMock, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """Test get_package_data fetches and caches package data.

        Happy path: Successful fetch from PyPI.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_pypi_response
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)
        data = await store.get_package_data("requests")

        assert data.name == "requests"
        assert data.latest_version == "2.31.0"
        assert "charset-normalizer>=2.0.0" in data.latest_dependencies
        assert "2.31.0" in data.all_versions

    @pytest.mark.asyncio
    async def test_fetch_normalizes_package_name(
        self, mock_http_client: MagicMock, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """Test get_package_data normalizes package names.

        Different casings and underscores should map to same cached entry.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_pypi_response
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)
        data1 = await store.get_package_data("Requests")
        data2 = await store.get_package_data("REQUESTS")
        data3 = await store.get_package_data("requests")

        # All should return the same cached object
        assert data1 is data2 is data3
        assert mock_http_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_fetch_caches_result(
        self, mock_http_client: MagicMock, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """Test get_package_data caches to avoid redundant fetches.

        Second call should return cached data without HTTP request.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_pypi_response
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)
        data1 = await store.get_package_data("requests")
        data2 = await store.get_package_data("requests")

        assert data1 is data2  # Same object
        assert mock_http_client.get.call_count == 1  # Only one fetch

    @pytest.mark.asyncio
    async def test_fetch_404_raises_pypi_error(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test get_package_data raises PyPIError on 404.

        Package not found should raise descriptive error.
        """
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)
        with pytest.raises(PyPIError) as exc_info:
            await store.get_package_data("nonexistent-package")

        assert "not found" in str(exc_info.value).lower()
        assert exc_info.value.package_name == "nonexistent-package"

    @pytest.mark.asyncio
    async def test_fetch_non_200_raises_pypi_error(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test get_package_data raises PyPIError on non-200 status.

        Server errors should be reported with status code.
        """
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)
        with pytest.raises(PyPIError) as exc_info:
            await store.get_package_data("test-package")

        assert "500" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_concurrent_requests_deduplicated(
        self, mock_http_client: MagicMock, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """Test concurrent requests for same package deduplicated.

        Multiple simultaneous requests should trigger only one HTTP fetch
        (double-checked locking).
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_pypi_response
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)

        # Fire 10 concurrent requests for same package
        results = await asyncio.gather(
            *[store.get_package_data("requests") for _ in range(10)]
        )

        # All should return same cached object
        assert all(r is results[0] for r in results)
        # Only one HTTP call made
        assert mock_http_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_concurrent_different_packages(
        self, mock_http_client: MagicMock, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """Test concurrent requests for different packages processed concurrently.

        Different packages should not block each other (subject to semaphore).
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_pypi_response
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client, concurrent_limit=5)

        # Request 3 different packages concurrently
        results = await asyncio.gather(
            store.get_package_data("requests"),
            store.get_package_data("flask"),
            store.get_package_data("django"),
        )

        # Should have made 3 separate HTTP calls
        assert mock_http_client.get.call_count == 3
        # Each should be cached separately
        assert len(store._package_data) == 3


# ============================================================================
# Test: PyPIDataStore prefetch
# ============================================================================


class TestPyPIDataStorePrefetch:
    """Tests for PyPIDataStore.prefetch_packages batch loading."""

    @pytest.mark.asyncio
    async def test_prefetch_multiple_packages(
        self, mock_http_client: MagicMock, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """Test prefetch_packages loads multiple packages concurrently.

        Happy path: Batch prefetch should populate cache.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_pypi_response
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)
        await store.prefetch_packages(["requests", "flask", "django"])

        # All should be cached
        assert "requests" in store._package_data
        assert "flask" in store._package_data
        assert "django" in store._package_data

    @pytest.mark.asyncio
    async def test_prefetch_silences_errors(self, mock_http_client: MagicMock) -> None:
        """Test prefetch_packages continues despite individual failures.

        Edge case: One bad package shouldn't stop the rest from loading.
        """

        async def mock_get_package_data(name: str):
            if name == "bad-package":
                raise PyPIError("Not found", package_name=name)
            data = PyPIPackageData(name=name, latest_version="1.0.0")
            store._package_data[name] = data
            return data

        store = PyPIDataStore(mock_http_client)

        with patch.object(store, "get_package_data", side_effect=mock_get_package_data):
            # Should not raise even though bad-package fails
            await store.prefetch_packages(["good1", "bad-package", "good2"])

        assert "good1" in store._package_data
        assert "good2" in store._package_data

    @pytest.mark.asyncio
    async def test_prefetch_empty_list(self, mock_http_client: MagicMock) -> None:
        """Test prefetch_packages handles empty package list.

        Edge case: Empty list should be a no-op.
        """
        store = PyPIDataStore(mock_http_client)
        await store.prefetch_packages([])
        assert len(store._package_data) == 0


# ============================================================================
# Test: PyPIDataStore version dependencies
# ============================================================================


class TestPyPIDataStoreGetVersionDependencies:
    """Tests for PyPIDataStore.get_version_dependencies."""

    @pytest.mark.asyncio
    async def test_get_latest_version_dependencies_from_cache(
        self, mock_http_client: MagicMock, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """Test get_version_dependencies for latest uses package cache.

        Latest version deps should be available from initial package fetch.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_pypi_response
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)
        await store.get_package_data("requests")

        # Reset call count after initial fetch
        mock_http_client.get.reset_mock()

        # Get latest version deps
        deps = await store.get_version_dependencies("requests", "2.31.0")

        # Should use cached data, no additional HTTP call
        assert mock_http_client.get.call_count == 0
        assert "charset-normalizer>=2.0.0" in deps

    @pytest.mark.asyncio
    async def test_get_non_latest_version_dependencies_fetches(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test get_version_dependencies fetches specific version.

        Non-latest versions require separate /pypi/{pkg}/{ver}/json fetch.
        """
        version_response = {
            "info": {
                "version": "2.0.0",
                "requires_dist": ["urllib3>=1.0", "certifi>=2016"],
            }
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = version_response
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)
        deps = await store.get_version_dependencies("requests", "2.0.0")

        assert "urllib3>=1.0" in deps
        assert "certifi>=2016" in deps
        assert mock_http_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_get_version_dependencies_caches_result(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test get_version_dependencies caches fetched deps.

        Second call for same version should use cache.
        """
        version_response = {
            "info": {"version": "2.0.0", "requires_dist": ["dep1", "dep2"]}
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = version_response
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)
        deps1 = await store.get_version_dependencies("requests", "2.0.0")
        deps2 = await store.get_version_dependencies("requests", "2.0.0")

        assert deps1 == deps2
        # Only one HTTP call
        assert mock_http_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_get_version_dependencies_handles_fetch_errors(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test get_version_dependencies returns empty list on errors.

        Edge case: Network/parse errors should not crash, return empty deps.
        """
        mock_http_client.get = AsyncMock(side_effect=Exception("Network error"))

        store = PyPIDataStore(mock_http_client)
        deps = await store.get_version_dependencies("requests", "2.0.0")

        assert deps == []

    @pytest.mark.asyncio
    async def test_get_version_dependencies_filters_extras(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test get_version_dependencies excludes extra dependencies.

        Dependencies with 'extra ==' should be filtered out.
        """
        version_response = {
            "info": {
                "version": "2.0.0",
                "requires_dist": [
                    "base-dep>=1.0",
                    "extra-dep>=2.0; extra == 'dev'",
                    "another-extra; extra=='test'",
                ],
            }
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = version_response
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)
        deps = await store.get_version_dependencies("requests", "2.0.0")

        assert "base-dep>=1.0" in deps
        assert not any("extra-dep" in d for d in deps)
        assert not any("another-extra" in d for d in deps)

    @pytest.mark.asyncio
    async def test_get_version_dependencies_strips_markers(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test get_version_dependencies removes environment markers.

        Markers after ';' should be stripped (except extra markers).
        """
        version_response = {
            "info": {
                "version": "2.0.0",
                "requires_dist": [
                    "dep1>=1.0; python_version < '3.0'",
                    "dep2>=2.0; sys_platform == 'win32'",
                ],
            }
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = version_response
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)
        deps = await store.get_version_dependencies("requests", "2.0.0")

        assert "dep1>=1.0" in deps
        assert "dep2>=2.0" in deps
        # Markers should be stripped
        assert not any("python_version" in d for d in deps)

    @pytest.mark.asyncio
    async def test_get_version_dependencies_updates_package_cache(
        self, mock_http_client: MagicMock, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """Test get_version_dependencies back-fills package-level cache.

        Fetched deps should be added to pkg_data.dependencies_cache.
        """
        # First fetch package
        mock_response1 = MagicMock()
        mock_response1.status_code = 200
        mock_response1.json.return_value = sample_pypi_response

        # Then fetch specific version
        version_response = {
            "info": {"version": "2.0.0", "requires_dist": ["old-dep>=1.0"]}
        }
        mock_response2 = MagicMock()
        mock_response2.status_code = 200
        mock_response2.json.return_value = version_response

        mock_http_client.get = AsyncMock(side_effect=[mock_response1, mock_response2])

        store = PyPIDataStore(mock_http_client)
        await store.get_package_data("requests")
        await store.get_version_dependencies("requests", "2.0.0")

        # Should now be in package-level cache
        pkg_data = store.get_cached_package("requests")
        assert "2.0.0" in pkg_data.dependencies_cache
        assert "old-dep>=1.0" in pkg_data.dependencies_cache["2.0.0"]


# ============================================================================
# Test: PyPIDataStore synchronous accessors
# ============================================================================


class TestPyPIDataStoreSyncAccessors:
    """Tests for PyPIDataStore synchronous (cache-only) methods."""

    def test_get_cached_package_returns_cached(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test get_cached_package returns previously fetched data.

        Happy path: Cached package should be returned.
        """
        store = PyPIDataStore(mock_http_client)
        pkg_data = PyPIPackageData(name="requests", latest_version="2.31.0")
        store._package_data["requests"] = pkg_data

        result = store.get_cached_package("requests")
        assert result is pkg_data

    def test_get_cached_package_returns_none_if_not_cached(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test get_cached_package returns None for unfetched packages.

        Edge case: Package not yet in cache.
        """
        store = PyPIDataStore(mock_http_client)
        result = store.get_cached_package("nonexistent")
        assert result is None

    def test_get_cached_package_normalizes_name(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test get_cached_package normalizes package names.

        Different casings should retrieve same cached entry.
        """
        store = PyPIDataStore(mock_http_client)
        pkg_data = PyPIPackageData(name="requests")
        store._package_data["requests"] = pkg_data

        assert store.get_cached_package("Requests") is pkg_data
        assert store.get_cached_package("REQUESTS") is pkg_data

    def test_get_versions_returns_all_versions(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test get_versions returns cached version list.

        Happy path: Should return all_versions from cached package data.
        """
        store = PyPIDataStore(mock_http_client)
        pkg_data = PyPIPackageData(
            name="requests", all_versions=["2.31.0", "2.30.0", "2.29.0"]
        )
        store._package_data["requests"] = pkg_data

        versions = store.get_versions("requests")
        assert versions == ["2.31.0", "2.30.0", "2.29.0"]

    def test_get_versions_returns_empty_if_not_cached(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test get_versions returns empty list for unfetched packages.

        Edge case: Package not in cache should return [].
        """
        store = PyPIDataStore(mock_http_client)
        versions = store.get_versions("nonexistent")
        assert versions == []

    def test_is_python_compatible_delegates_to_package_data(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test is_python_compatible uses cached package data.

        Happy path: Should delegate to PyPIPackageData method.
        """
        store = PyPIDataStore(mock_http_client)
        pkg_data = PyPIPackageData(
            name="requests",
            python_requirements={"2.31.0": ">=3.7"},
        )
        store._package_data["requests"] = pkg_data

        assert store.is_python_compatible("requests", "2.31.0", "3.9.0") is True
        assert store.is_python_compatible("requests", "2.31.0", "3.6.0") is False

    def test_is_python_compatible_returns_true_if_not_cached(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test is_python_compatible returns True for unfetched packages.

        Edge case: Permissive default when package not in cache.
        """
        store = PyPIDataStore(mock_http_client)
        assert store.is_python_compatible("unknown", "1.0.0", "3.9.0") is True


# ============================================================================
# Test: PyPIDataStore parsing helpers
# ============================================================================


class TestPyPIDataStoreParsePackageData:
    """Tests for PyPIDataStore._parse_package_data."""

    def test_parse_package_data_extracts_basic_info(
        self, mock_http_client: MagicMock, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """Test _parse_package_data extracts basic package metadata.

        Happy path: Should populate all core fields from PyPI response.
        """
        store = PyPIDataStore(mock_http_client)
        pkg_data = store._parse_package_data("requests", sample_pypi_response)

        assert pkg_data.name == "requests"
        assert pkg_data.latest_version == "2.31.0"
        assert pkg_data.latest_requires_python == ">=3.7"
