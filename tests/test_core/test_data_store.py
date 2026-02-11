from __future__ import annotations

import pytest
import asyncio
from typing import Any, Dict
from packaging.version import Version
from unittest.mock import AsyncMock, MagicMock, patch

from depkeeper.core.data_store import (
    PyPIDataStore,
    PyPIPackageData,
    _normalize,
)
from depkeeper.exceptions import PyPIError
from depkeeper.utils.http import HTTPClient


@pytest.fixture
def mock_http_client() -> MagicMock:
    """Create a mock HTTPClient for testing."""
    return MagicMock(spec=HTTPClient)


@pytest.fixture
def sample_pypi_response() -> Dict[str, Any]:
    """Create a sample PyPI JSON API response."""
    return {
        "info": {
            "name": "requests",
            "version": "2.31.0",
            "requires_python": ">=3.7",
            "requires_dist": [
                "charset-normalizer>=2.0.0",
                "idna>=2.5",
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
            "2.0.0": [{"requires_python": None, "filename": "requests-2.0.0.tar.gz"}],
            "1.2.3": [
                {"requires_python": ">=2.7", "filename": "requests-1.2.3.tar.gz"}
            ],
            "3.0.0a1": [
                {"requires_python": ">=3.8", "filename": "requests-3.0.0a1.tar.gz"}
            ],
            "invalid-version": [],  # No files - should be skipped
        },
    }


@pytest.fixture
def sample_package_data() -> PyPIPackageData:
    """Create a sample PyPIPackageData instance for testing."""
    return PyPIPackageData(
        name="requests",
        latest_version="2.31.0",
        latest_requires_python=">=3.7",
        latest_dependencies=["charset-normalizer>=2.0.0", "idna>=2.5"],
        all_versions=["2.31.0", "2.30.0", "2.0.0", "1.2.3"],
        parsed_versions=[
            ("2.31.0", Version("2.31.0")),
            ("2.30.0", Version("2.30.0")),
            ("2.0.0", Version("2.0.0")),
            ("1.2.3", Version("1.2.3")),
            ("3.0.0a1", Version("3.0.0a1")),  # Pre-release
        ],
        python_requirements={
            "2.31.0": ">=3.7",
            "2.30.0": ">=3.7",
            "2.0.0": None,
            "1.2.3": ">=2.7",
        },
        releases={},
        dependencies_cache={"2.31.0": ["charset-normalizer>=2.0.0", "idna>=2.5"]},
    )


@pytest.mark.unit
class TestNormalizeFunction:
    """Tests for _normalize package name normalization."""

    def test_combined_normalization(self) -> None:
        """Test _normalize handles case and underscores together."""
        assert _normalize("Flask_Login") == "flask-login"
        assert _normalize("My_PACKAGE_Name") == "my-package-name"
        assert _normalize("requests") == "requests"
        assert _normalize("DJANGO") == "django"


@pytest.mark.unit
class TestPyPIPackageData:
    """Tests for PyPIPackageData dataclass and query methods."""

    def test_initialization(self) -> None:
        """Test PyPIPackageData initializes with defaults."""
        data = PyPIPackageData(name="test-package")

        assert data.name == "test-package"
        assert data.latest_version is None
        assert data.all_versions == []
        assert data.dependencies_cache == {}

    def test_get_versions_in_major(self, sample_package_data: PyPIPackageData) -> None:
        """Test get_versions_in_major filters by major version number."""
        v2_versions = sample_package_data.get_versions_in_major(2)
        v1_versions = sample_package_data.get_versions_in_major(1)
        v99_versions = sample_package_data.get_versions_in_major(99)

        # Version 2.x
        assert "2.31.0" in v2_versions
        assert "2.30.0" in v2_versions
        assert "1.2.3" not in v2_versions

        # Version 1.x
        assert "1.2.3" in v1_versions

        # Pre-releases excluded
        assert "3.0.0a1" not in sample_package_data.get_versions_in_major(3)

        # Non-existent major
        assert v99_versions == []

    def test_is_python_compatible(self, sample_package_data: PyPIPackageData) -> None:
        """Test is_python_compatible checks Python version requirements."""
        # Compatible
        assert sample_package_data.is_python_compatible("2.31.0", "3.9.0") is True
        assert sample_package_data.is_python_compatible("2.31.0", "3.11.4") is True

        # Incompatible
        assert sample_package_data.is_python_compatible("2.31.0", "3.6.0") is False
        assert sample_package_data.is_python_compatible("2.31.0", "2.7.18") is False

        # No requirement (permissive)
        assert sample_package_data.is_python_compatible("2.0.0", "2.7.0") is True

    def test_get_python_compatible_versions(
        self, sample_package_data: PyPIPackageData
    ) -> None:
        """Test get_python_compatible_versions filters by Python version."""
        # All majors
        compatible_all = sample_package_data.get_python_compatible_versions("3.9.0")
        assert "2.31.0" in compatible_all
        assert "1.2.3" in compatible_all

        # Specific major
        compatible_v2 = sample_package_data.get_python_compatible_versions(
            "3.9.0", major=2
        )
        assert "2.31.0" in compatible_v2
        assert "1.2.3" not in compatible_v2

        # Incompatible Python version
        old_python = sample_package_data.get_python_compatible_versions(
            "2.7.18", major=2
        )
        assert "2.31.0" not in old_python  # Requires >=3.7
        assert "2.0.0" in old_python  # No requirement


@pytest.mark.unit
class TestPyPIDataStoreInit:
    """Tests for PyPIDataStore initialization."""

    def test_initialization(self, mock_http_client: MagicMock) -> None:
        """Test PyPIDataStore initializes with correct defaults."""
        store = PyPIDataStore(mock_http_client)

        assert store.http_client is mock_http_client
        assert store._semaphore._value == 10  # Default
        assert store._package_data == {}
        assert store._version_deps_cache == {}

    def test_initialization_with_custom_limit(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test PyPIDataStore accepts custom concurrent_limit."""
        store = PyPIDataStore(mock_http_client, concurrent_limit=5)

        assert store._semaphore._value == 5


@pytest.mark.unit
class TestPyPIDataStoreGetPackageData:
    """Tests for PyPIDataStore.get_package_data async fetching."""

    @pytest.mark.asyncio
    async def test_fetch_and_cache(
        self, mock_http_client: MagicMock, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """Test get_package_data fetches and caches package data."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_pypi_response
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)
        data = await store.get_package_data("requests")

        assert data.name == "requests"
        assert data.latest_version == "2.31.0"
        assert "charset-normalizer>=2.0.0" in data.latest_dependencies

    @pytest.mark.asyncio
    async def test_normalizes_package_name(
        self, mock_http_client: MagicMock, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """Test get_package_data normalizes package names."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_pypi_response
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)
        data1 = await store.get_package_data("Requests")
        data2 = await store.get_package_data("REQUESTS")

        # Same cached object
        assert data1 is data2
        assert mock_http_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_returns_cached_data(
        self, mock_http_client: MagicMock, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """Test get_package_data returns cached data on second call."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_pypi_response
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)
        data1 = await store.get_package_data("requests")
        data2 = await store.get_package_data("requests")

        assert data1 is data2
        assert mock_http_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_raises_pypi_error_on_404(self, mock_http_client: MagicMock) -> None:
        """Test get_package_data raises PyPIError on 404."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)

        with pytest.raises(PyPIError) as exc_info:
            await store.get_package_data("nonexistent-package")

        assert "not found" in str(exc_info.value).lower()
        assert exc_info.value.package_name == "nonexistent-package"

    @pytest.mark.asyncio
    async def test_concurrent_requests_deduplicated(
        self, mock_http_client: MagicMock, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """Test concurrent requests for same package trigger only one fetch."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_pypi_response
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)

        # Fire multiple concurrent requests
        results = await asyncio.gather(
            *[store.get_package_data("requests") for _ in range(5)]
        )

        # All return same cached object
        assert all(r is results[0] for r in results)
        # Only one HTTP call
        assert mock_http_client.get.call_count == 1


@pytest.mark.unit
class TestPyPIDataStorePrefetch:
    """Tests for PyPIDataStore.prefetch_packages batch loading."""

    @pytest.mark.asyncio
    async def test_prefetch_multiple_packages(
        self, mock_http_client: MagicMock, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """Test prefetch_packages loads multiple packages concurrently."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_pypi_response
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)
        await store.prefetch_packages(["requests", "flask", "django"])

        # All cached
        assert "requests" in store._package_data
        assert "flask" in store._package_data
        assert "django" in store._package_data

    @pytest.mark.asyncio
    async def test_prefetch_silences_errors(self, mock_http_client: MagicMock) -> None:
        """Test prefetch_packages continues despite individual failures."""

        async def mock_get_package_data(name: str):
            if name == "bad-package":
                raise PyPIError("Not found", package_name=name)
            data = PyPIPackageData(name=name, latest_version="1.0.0")
            store._package_data[name] = data
            return data

        store = PyPIDataStore(mock_http_client)

        with patch.object(store, "get_package_data", side_effect=mock_get_package_data):
            await store.prefetch_packages(["good1", "bad-package", "good2"])

        assert "good1" in store._package_data
        assert "good2" in store._package_data


@pytest.mark.unit
class TestPyPIDataStoreGetVersionDependencies:
    """Tests for PyPIDataStore.get_version_dependencies."""

    @pytest.mark.asyncio
    async def test_get_latest_version_from_cache(
        self, mock_http_client: MagicMock, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """Test get_version_dependencies for latest uses cached data."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_pypi_response
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)
        await store.get_package_data("requests")

        mock_http_client.get.reset_mock()

        # Get latest version deps - should use cache
        deps = await store.get_version_dependencies("requests", "2.31.0")

        assert mock_http_client.get.call_count == 0
        assert "charset-normalizer>=2.0.0" in deps

    @pytest.mark.asyncio
    async def test_fetch_non_latest_version(self, mock_http_client: MagicMock) -> None:
        """Test get_version_dependencies fetches non-latest versions."""
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

    @pytest.mark.asyncio
    async def test_caches_fetched_dependencies(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test get_version_dependencies caches fetched deps."""
        version_response = {
            "info": {"version": "2.0.0", "requires_dist": ["dep1>=1.0"]}
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = version_response
        mock_http_client.get = AsyncMock(return_value=mock_response)

        store = PyPIDataStore(mock_http_client)
        deps1 = await store.get_version_dependencies("requests", "2.0.0")
        deps2 = await store.get_version_dependencies("requests", "2.0.0")

        assert deps1 == deps2
        assert mock_http_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_filters_extras_and_strips_markers(
        self, mock_http_client: MagicMock
    ) -> None:
        """Test get_version_dependencies filters extras and strips markers."""
        version_response = {
            "info": {
                "version": "2.0.0",
                "requires_dist": [
                    "base-dep>=1.0",
                    "extra-dep>=2.0; extra == 'dev'",
                    "platform-dep>=3.0; sys_platform == 'win32'",
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
        assert "platform-dep>=3.0" in deps
        # Extra filtered out
        assert not any("extra-dep" in d for d in deps)
        # Marker stripped
        assert not any("sys_platform" in d for d in deps)


@pytest.mark.unit
class TestPyPIDataStoreSyncAccessors:
    """Tests for PyPIDataStore synchronous (cache-only) methods."""

    def test_get_cached_package(self, mock_http_client: MagicMock) -> None:
        """Test get_cached_package returns cached data or None."""
        store = PyPIDataStore(mock_http_client)
        pkg_data = PyPIPackageData(name="requests", latest_version="2.31.0")
        store._package_data["requests"] = pkg_data

        # Cached package
        assert store.get_cached_package("requests") is pkg_data
        assert store.get_cached_package("REQUESTS") is pkg_data  # Normalized

        # Not cached
        assert store.get_cached_package("nonexistent") is None

    def test_get_versions(self, mock_http_client: MagicMock) -> None:
        """Test get_versions returns cached version list."""
        store = PyPIDataStore(mock_http_client)
        pkg_data = PyPIPackageData(
            name="requests", all_versions=["2.31.0", "2.30.0", "2.29.0"]
        )
        store._package_data["requests"] = pkg_data

        # Cached versions
        versions = store.get_versions("requests")
        assert versions == ["2.31.0", "2.30.0", "2.29.0"]

        # Not cached
        assert store.get_versions("nonexistent") == []

    def test_is_python_compatible(self, mock_http_client: MagicMock) -> None:
        """Test is_python_compatible uses cached package data."""
        store = PyPIDataStore(mock_http_client)
        pkg_data = PyPIPackageData(
            name="requests",
            python_requirements={"2.31.0": ">=3.7"},
        )
        store._package_data["requests"] = pkg_data

        # Cached - compatible
        assert store.is_python_compatible("requests", "2.31.0", "3.9.0") is True
        # Cached - incompatible
        assert store.is_python_compatible("requests", "2.31.0", "3.6.0") is False
        # Not cached - permissive
        assert store.is_python_compatible("unknown", "1.0.0", "3.9.0") is True
