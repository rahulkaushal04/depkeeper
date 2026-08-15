from __future__ import annotations

import pytest
import asyncio
from typing import Any, Dict, List
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


class RecordingHTTPClient:
    """Async HTTP stub whose ``get`` really suspends.

    ``AsyncMock`` resolves without ever yielding to the event loop, so a
    coroutine awaiting it runs straight through and no two callers can
    ever interleave.  Concurrency tests therefore need a stub with a real
    suspension point (``asyncio.sleep``), exactly like a socket read.
    """

    def __init__(
        self,
        payload: Dict[str, Any],
        *,
        delay: float = 0.01,
        status_code: int = 200,
    ) -> None:
        self.payload = payload
        self.delay = delay
        self.status_code = status_code
        self.urls: List[str] = []
        self.in_flight = 0
        self.peak_in_flight = 0

    async def get(self, url: str, **kwargs: Any) -> MagicMock:
        self.urls.append(url)
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.in_flight -= 1

        response = MagicMock()
        response.status_code = self.status_code
        response.json.return_value = self.payload
        return response

    @property
    def call_count(self) -> int:
        return len(self.urls)


def make_recording_client(
    payload: Dict[str, Any],
    **kwargs: Any,
) -> Any:
    """Build a ``HTTPClient``-shaped mock backed by RecordingHTTPClient."""
    recorder = RecordingHTTPClient(payload, **kwargs)
    client = MagicMock(spec=HTTPClient)
    client.get = recorder.get
    client.recorder = recorder
    return client


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
        self, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """Test concurrent requests for same package trigger only one fetch."""
        # A stub that actually suspends: with AsyncMock the first caller
        # would never yield, hiding any lack of deduplication.
        client = make_recording_client(sample_pypi_response)

        store = PyPIDataStore(client)

        # Fire multiple concurrent requests
        results = await asyncio.gather(
            *[store.get_package_data("requests") for _ in range(5)]
        )

        # All return same cached object
        assert all(r is results[0] for r in results)
        # Only one HTTP call
        assert client.recorder.call_count == 1


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


# ---------------------------------------------------------------------------
# M8 regression: "at most one fetch per package" must actually hold
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPyPIDataStoreRequestCoalescing:
    """Regression tests for M8 (semaphore was used as a mutex).

    A counting ``Semaphore(n)`` admits *n* coroutines at once, so the old
    "double check inside the semaphore" allowed up to *n* duplicate
    fetches of the same package.  These tests pin the real contract: one
    concurrent fetch per key, no matter how many callers or how large the
    concurrency limit.
    """

    @pytest.mark.asyncio
    async def test_many_waiters_share_a_single_fetch(
        self, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """20 concurrent callers → one HTTP request, one shared object."""
        client = make_recording_client(sample_pypi_response)
        store = PyPIDataStore(client)

        results = await asyncio.gather(
            *[store.get_package_data("requests") for _ in range(20)]
        )

        assert client.recorder.call_count == 1
        assert all(r is results[0] for r in results)
        assert store.get_cached_package("requests") is results[0]

    @pytest.mark.asyncio
    async def test_waiters_beyond_semaphore_limit_still_coalesce(
        self, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """More waiters than semaphore slots must not fan out into fetches."""
        client = make_recording_client(sample_pypi_response)
        store = PyPIDataStore(client, concurrent_limit=3)

        await asyncio.gather(*[store.get_package_data("requests") for _ in range(8)])

        # Pre-fix this was exactly `concurrent_limit` (3) duplicate requests.
        assert client.recorder.call_count == 1

    @pytest.mark.asyncio
    async def test_name_variants_are_coalesced(
        self, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """Spellings that normalise to one key share a single fetch."""
        client = make_recording_client(sample_pypi_response)
        store = PyPIDataStore(client)

        results = await asyncio.gather(
            store.get_package_data("Requests"),
            store.get_package_data("REQUESTS"),
            store.get_package_data("requests"),
        )

        assert client.recorder.call_count == 1
        assert all(r is results[0] for r in results)

    @pytest.mark.asyncio
    async def test_semaphore_still_bounds_distinct_fetches(
        self, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """Coalescing must not weaken the outbound concurrency cap."""
        client = make_recording_client(sample_pypi_response)
        store = PyPIDataStore(client, concurrent_limit=2)

        names = [f"pkg-{i}" for i in range(8)]
        await asyncio.gather(*[store.get_package_data(n) for n in names])

        assert client.recorder.call_count == 8
        assert client.recorder.peak_in_flight <= 2

    @pytest.mark.asyncio
    async def test_inflight_registry_is_empty_after_success(
        self, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """No task leaks: the in-flight map is transient state only."""
        client = make_recording_client(sample_pypi_response)
        store = PyPIDataStore(client)

        await asyncio.gather(*[store.get_package_data("requests") for _ in range(4)])

        assert store._inflight_packages == {}

    @pytest.mark.asyncio
    async def test_failures_are_not_cached_and_retry_works(self) -> None:
        """Coalesced failures stay retryable (no negative caching)."""
        client = MagicMock(spec=HTTPClient)
        state = {"fail": True}
        urls: List[str] = []

        async def flaky_get(url: str, **kwargs: Any) -> MagicMock:
            urls.append(url)
            await asyncio.sleep(0)
            response = MagicMock()
            response.status_code = 500 if state["fail"] else 200
            response.json.return_value = {
                "info": {"name": "requests", "version": "2.31.0"},
                "releases": {"2.31.0": [{"filename": "x"}]},
            }
            return response

        client.get = flaky_get
        store = PyPIDataStore(client)

        results = await asyncio.gather(
            *[store.get_package_data("requests") for _ in range(3)],
            return_exceptions=True,
        )

        assert len(urls) == 1  # the failure was shared, not repeated 3x
        assert all(isinstance(r, PyPIError) for r in results)
        assert store._inflight_packages == {}
        assert store.get_cached_package("requests") is None

        # A later call must re-attempt rather than replay the failure
        state["fail"] = False
        data = await store.get_package_data("requests")

        assert data.latest_version == "2.31.0"
        assert len(urls) == 2

    @pytest.mark.asyncio
    async def test_cancelling_one_waiter_does_not_abort_the_shared_fetch(
        self, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """One caller giving up must not strand the others."""
        client = make_recording_client(sample_pypi_response, delay=0.05)
        store = PyPIDataStore(client)

        first = asyncio.ensure_future(store.get_package_data("requests"))
        second = asyncio.ensure_future(store.get_package_data("requests"))
        await asyncio.sleep(0)  # let both register on the same fetch

        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

        data = await second

        assert data.latest_version == "2.31.0"
        assert client.recorder.call_count == 1

    @pytest.mark.asyncio
    async def test_all_waiters_cancelled_still_populates_cache(
        self, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """The shared fetch survives losing every waiter (shielded)."""
        client = make_recording_client(sample_pypi_response, delay=0.02)
        store = PyPIDataStore(client)

        waiters = [
            asyncio.ensure_future(store.get_package_data("requests")) for _ in range(3)
        ]
        await asyncio.sleep(0)

        shared = store._inflight_packages["requests"]
        for waiter in waiters:
            waiter.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)

        data = await shared

        assert data.latest_version == "2.31.0"
        assert client.recorder.call_count == 1
        assert store._inflight_packages == {}

    @pytest.mark.asyncio
    async def test_concurrent_version_dependency_fetches_are_coalesced(self) -> None:
        """Layer-3 dependency fetches share the same coalescing guarantee."""
        client = make_recording_client(
            {"info": {"name": "requests", "requires_dist": ["idna>=2.5"]}}
        )
        store = PyPIDataStore(client)

        results = await asyncio.gather(
            *[store.get_version_dependencies("requests", "2.30.0") for _ in range(5)]
        )

        assert client.recorder.call_count == 1
        assert all(r == ["idna>=2.5"] for r in results)
        assert store._inflight_version_deps == {}
        assert store._version_deps_cache["requests==2.30.0"] == ["idna>=2.5"]

    @pytest.mark.asyncio
    async def test_version_dependency_backfill_uses_current_cache_entry(self) -> None:
        """Back-fill targets the package entry cached at completion time."""
        client = make_recording_client(
            {"info": {"name": "requests", "requires_dist": ["idna>=2.5"]}}
        )
        store = PyPIDataStore(client)
        store._package_data["requests"] = PyPIPackageData(
            name="requests", latest_version="2.31.0"
        )

        await store.get_version_dependencies("requests", "2.30.0")

        cached = store.get_cached_package("requests")
        assert cached is not None
        assert cached.dependencies_cache["2.30.0"] == ["idna>=2.5"]

    @pytest.mark.asyncio
    async def test_different_versions_are_fetched_independently(self) -> None:
        """Coalescing is per name==version, not per package."""
        client = make_recording_client(
            {"info": {"name": "requests", "requires_dist": ["idna>=2.5"]}}
        )
        store = PyPIDataStore(client)

        await asyncio.gather(
            store.get_version_dependencies("requests", "2.30.0"),
            store.get_version_dependencies("requests", "2.29.0"),
            store.get_version_dependencies("requests", "2.30.0"),
        )

        assert client.recorder.call_count == 2


@pytest.mark.unit
class TestPyPIDataStorePrefetchDeduplication:
    """Regression tests for M8's secondary finding (duplicate prefetch names)."""

    @pytest.mark.asyncio
    async def test_prefetch_deduplicates_repeated_and_variant_names(
        self, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """Repeated names (typical with `-r` includes) cost one fetch each."""
        client = make_recording_client(sample_pypi_response)
        store = PyPIDataStore(client)

        await store.prefetch_packages(
            ["flask", "requests", "Flask", "flask_login", "requests", "FLASK"]
        )

        assert client.recorder.call_count == 3
        # First spelling wins and input order is preserved
        assert client.recorder.urls == [
            "https://pypi.org/pypi/flask/json",
            "https://pypi.org/pypi/requests/json",
            "https://pypi.org/pypi/flask_login/json",
        ]

    @pytest.mark.asyncio
    async def test_prefetch_handles_empty_input(
        self, sample_pypi_response: Dict[str, Any]
    ) -> None:
        """An empty batch is a no-op, not an error."""
        client = make_recording_client(sample_pypi_response)
        store = PyPIDataStore(client)

        await store.prefetch_packages([])

        assert client.recorder.call_count == 0

    @pytest.mark.asyncio
    async def test_prefetch_failure_does_not_block_other_packages(self) -> None:
        """One 404 must not stop the rest of the batch (unchanged contract)."""
        client = MagicMock(spec=HTTPClient)
        urls: List[str] = []

        async def get(url: str, **kwargs: Any) -> MagicMock:
            urls.append(url)
            await asyncio.sleep(0)
            response = MagicMock()
            response.status_code = 404 if "bad-package" in url else 200
            response.json.return_value = {
                "info": {"name": "ok", "version": "1.0.0"},
                "releases": {"1.0.0": [{"filename": "x"}]},
            }
            return response

        client.get = get
        store = PyPIDataStore(client)

        await store.prefetch_packages(["good1", "bad-package", "good2", "good1"])

        assert len(urls) == 3
        assert store.get_cached_package("good1") is not None
        assert store.get_cached_package("good2") is not None
        assert store.get_cached_package("bad-package") is None
        assert store._inflight_packages == {}


@pytest.mark.unit
class TestPyPIDataStoreConstructorValidation:
    """A concurrency limit below 1 would deadlock every fetch."""

    @pytest.mark.parametrize("limit", [0, -1])
    def test_rejects_non_positive_concurrent_limit(
        self, mock_http_client: MagicMock, limit: int
    ) -> None:
        with pytest.raises(ValueError, match="concurrent_limit"):
            PyPIDataStore(mock_http_client, concurrent_limit=limit)

    def test_accepts_limit_of_one(self, mock_http_client: MagicMock) -> None:
        store = PyPIDataStore(mock_http_client, concurrent_limit=1)
        assert store._semaphore._value == 1
