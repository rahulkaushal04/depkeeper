from __future__ import annotations

import time
import httpx
import pytest
import asyncio
from typing import Dict, Any
from unittest.mock import Mock, AsyncMock, patch

from depkeeper.utils.http import HTTPClient
from depkeeper.__version__ import __version__
from depkeeper.exceptions import NetworkError, PyPIError
from depkeeper.constants import (
    DEFAULT_TIMEOUT,
    DEFAULT_MAX_RETRIES,
    USER_AGENT_TEMPLATE,
)


@pytest.fixture
def mock_response():
    """Create a mock httpx.Response object."""

    def _create_response(
        status_code: int = 200,
        json_data: Dict[str, Any] = None,
        text: str = "",
        headers: Dict[str, str] = None,
    ):
        response = Mock(spec=httpx.Response)
        response.status_code = status_code
        response.json = Mock(return_value=json_data or {})
        response.text = text or (str(json_data) if json_data else "")
        response.headers = headers or {}
        response.raise_for_status = Mock()

        if status_code >= 400:
            response.raise_for_status.side_effect = httpx.HTTPStatusError(
                f"HTTP {status_code}", request=Mock(), response=response
            )

        return response

    return _create_response


@pytest.fixture
async def http_client():
    """Provide an HTTPClient instance with automatic cleanup."""
    client = HTTPClient()
    yield client
    await client.close()


@pytest.fixture
def mock_async_client():
    """Create a mock httpx.AsyncClient."""
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request = AsyncMock()
    client.aclose = AsyncMock()
    return client


class TestHTTPClientInitialization:
    """Test suite for HTTPClient initialization and configuration."""

    def test_init_default_parameters(self):
        """Test HTTPClient initializes with default parameters."""
        client = HTTPClient()

        assert client.timeout == DEFAULT_TIMEOUT
        assert client.max_retries == DEFAULT_MAX_RETRIES
        assert client.rate_limit_delay == 0.0
        assert client.verify_ssl is True
        assert client.user_agent == USER_AGENT_TEMPLATE.format(version=__version__)
        assert client.max_concurrency == 10
        assert client._client is None
        assert client._last_request_time == 0.0
        assert client._max_429_retries == 5

    def test_init_custom_timeout(self):
        """Test HTTPClient with custom timeout."""
        client = HTTPClient(timeout=60)
        assert client.timeout == 60

    def test_init_custom_max_retries(self):
        """Test HTTPClient with custom max_retries."""
        client = HTTPClient(max_retries=5)
        assert client.max_retries == 5

    def test_init_custom_rate_limit_delay(self):
        """Test HTTPClient with custom rate_limit_delay."""
        client = HTTPClient(rate_limit_delay=0.5)
        assert client.rate_limit_delay == 0.5

    def test_init_ssl_verification_disabled(self):
        """Test HTTPClient with SSL verification disabled."""
        client = HTTPClient(verify_ssl=False)
        assert client.verify_ssl is False

    def test_init_custom_user_agent(self):
        """Test HTTPClient with custom user agent."""
        custom_ua = "CustomAgent/1.0"
        client = HTTPClient(user_agent=custom_ua)
        assert client.user_agent == custom_ua

    def test_init_custom_max_concurrency(self):
        """Test HTTPClient with custom max_concurrency."""
        client = HTTPClient(max_concurrency=20)
        assert client.max_concurrency == 20
        assert client._semaphore._value == 20

    def test_init_all_custom_parameters(self):
        """Test HTTPClient with all custom parameters."""
        client = HTTPClient(
            timeout=45,
            max_retries=7,
            rate_limit_delay=1.0,
            verify_ssl=False,
            user_agent="TestAgent/1.0",
            max_concurrency=15,
        )

        assert client.timeout == 45
        assert client.max_retries == 7
        assert client.rate_limit_delay == 1.0
        assert client.verify_ssl is False
        assert client.user_agent == "TestAgent/1.0"
        assert client.max_concurrency == 15

    def test_init_zero_timeout(self):
        """Test HTTPClient with zero timeout."""
        client = HTTPClient(timeout=0)
        assert client.timeout == 0

    def test_init_zero_retries(self):
        """Test HTTPClient with zero retries."""
        client = HTTPClient(max_retries=0)
        assert client.max_retries == 0

    def test_init_negative_rate_limit(self):
        """Test HTTPClient with negative rate limit delay."""
        client = HTTPClient(rate_limit_delay=-1.0)
        assert client.rate_limit_delay == -1.0

    def test_init_very_high_concurrency(self):
        """Test HTTPClient with very high concurrency limit."""
        client = HTTPClient(max_concurrency=1000)
        assert client.max_concurrency == 1000


class TestHTTPClientContextManager:
    """Test suite for HTTPClient context manager operations."""

    @pytest.mark.asyncio
    async def test_context_manager_basic(self):
        """Test HTTPClient as async context manager."""
        async with HTTPClient() as client:
            assert client._client is not None
            assert isinstance(client._client, httpx.AsyncClient)

    @pytest.mark.asyncio
    async def test_context_manager_initializes_client(self):
        """Test context manager initializes the underlying client."""
        client = HTTPClient()
        assert client._client is None

        async with client:
            assert client._client is not None

        assert client._client is None

    @pytest.mark.asyncio
    async def test_context_manager_closes_client(self):
        """Test context manager closes client on exit."""
        client = HTTPClient()

        async with client:
            internal_client = client._client
            assert internal_client is not None

        assert client._client is None

    @pytest.mark.asyncio
    async def test_context_manager_with_exception(self):
        """Test context manager closes client even with exception."""
        client = HTTPClient()

        try:
            async with client:
                assert client._client is not None
                raise ValueError("Test exception")
        except ValueError:
            pass

        assert client._client is None

    @pytest.mark.asyncio
    async def test_context_manager_returns_self(self):
        """Test context manager __aenter__ returns self."""
        client = HTTPClient()

        async with client as ctx_client:
            assert ctx_client is client

    @pytest.mark.asyncio
    async def test_multiple_context_manager_uses(self):
        """Test HTTPClient can be used as context manager multiple times."""
        client = HTTPClient()

        async with client:
            assert client._client is not None

        assert client._client is None

        async with client:
            assert client._client is not None

        assert client._client is None


class TestEnsureClient:
    """Test suite for _ensure_client method."""

    @pytest.mark.asyncio
    async def test_ensure_client_creates_client(self):
        """Test _ensure_client creates httpx.AsyncClient."""
        client = HTTPClient()
        assert client._client is None

        await client._ensure_client()

        assert client._client is not None
        assert isinstance(client._client, httpx.AsyncClient)

        await client.close()

    @pytest.mark.asyncio
    async def test_ensure_client_idempotent(self):
        """Test _ensure_client is idempotent."""
        client = HTTPClient()

        await client._ensure_client()
        first_client = client._client

        await client._ensure_client()
        second_client = client._client

        assert first_client is second_client

        await client.close()

    @pytest.mark.asyncio
    async def test_ensure_client_configures_timeout(self):
        """Test _ensure_client configures timeout correctly."""
        client = HTTPClient(timeout=45)
        await client._ensure_client()

        assert client._client.timeout.read == 45

        await client.close()

    @pytest.mark.asyncio
    async def test_ensure_client_configures_http2(self):
        """Test _ensure_client enables HTTP/2."""
        client = HTTPClient()
        await client._ensure_client()
        await client.close()

    @pytest.mark.asyncio
    async def test_ensure_client_configures_ssl_verification(self):
        """Test _ensure_client configures SSL verification."""
        client = HTTPClient(verify_ssl=False)
        await client._ensure_client()

        assert client.verify_ssl is False

        await client.close()

    @pytest.mark.asyncio
    async def test_ensure_client_configures_user_agent(self):
        """Test _ensure_client sets User-Agent header."""
        custom_ua = "TestAgent/1.0"
        client = HTTPClient(user_agent=custom_ua)
        await client._ensure_client()

        assert "User-Agent" in client._client.headers
        assert client._client.headers["User-Agent"] == custom_ua

        await client.close()

    @pytest.mark.asyncio
    async def test_ensure_client_enables_redirects(self):
        """Test _ensure_client enables automatic redirect following."""
        client = HTTPClient()
        await client._ensure_client()

        assert client._client.follow_redirects is True

        await client.close()


class TestClose:
    """Test suite for close method."""

    @pytest.mark.asyncio
    async def test_close_closes_client(self):
        """Test close method closes the underlying client."""
        client = HTTPClient()
        await client._ensure_client()

        assert client._client is not None

        await client.close()

        assert client._client is None

    @pytest.mark.asyncio
    async def test_close_when_not_initialized(self):
        """Test close when client is not initialized."""
        client = HTTPClient()
        assert client._client is None

        await client.close()

        assert client._client is None

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        """Test close can be called multiple times."""
        client = HTTPClient()
        await client._ensure_client()

        await client.close()
        await client.close()
        await client.close()

        assert client._client is None

    @pytest.mark.asyncio
    async def test_close_allows_reinit(self):
        """Test client can be reinitialized after close."""
        client = HTTPClient()

        await client._ensure_client()
        first_client = client._client
        await client.close()

        await client._ensure_client()
        second_client = client._client

        assert first_client is not second_client

        await client.close()


class TestRateLimit:
    """Test suite for _rate_limit method."""

    @pytest.mark.asyncio
    async def test_rate_limit_no_delay(self):
        """Test _rate_limit with no delay configured."""
        client = HTTPClient(rate_limit_delay=0.0)

        start = time.time()
        await client._rate_limit()
        elapsed = time.time() - start

        # Should return immediately
        assert elapsed < 0.01

        await client.close()

    @pytest.mark.asyncio
    async def test_rate_limit_negative_delay(self):
        """Test _rate_limit with negative delay."""
        client = HTTPClient(rate_limit_delay=-1.0)

        start = time.time()
        await client._rate_limit()
        elapsed = time.time() - start

        # Should return immediately
        assert elapsed < 0.01

        await client.close()

    @pytest.mark.asyncio
    async def test_rate_limit_enforces_delay(self):
        """Test _rate_limit enforces minimum delay between requests."""
        client = HTTPClient(rate_limit_delay=0.1)

        # First call - should not delay
        start = time.time()
        await client._rate_limit()
        first_elapsed = time.time() - start
        assert first_elapsed < 0.05

        # Second call immediately - should delay
        start = time.time()
        await client._rate_limit()
        second_elapsed = time.time() - start
        assert second_elapsed >= 0.09  # Account for timing precision

        await client.close()

    @pytest.mark.asyncio
    async def test_rate_limit_resets_after_delay(self):
        """Test _rate_limit resets after sufficient time passes."""
        client = HTTPClient(rate_limit_delay=0.05)

        await client._rate_limit()

        # Wait longer than rate limit
        await asyncio.sleep(0.06)

        # Should not delay
        start = time.time()
        await client._rate_limit()
        elapsed = time.time() - start
        assert elapsed < 0.02

        await client.close()

    @pytest.mark.asyncio
    async def test_rate_limit_thread_safe(self):
        """Test _rate_limit is thread-safe with concurrent calls."""
        client = HTTPClient(rate_limit_delay=0.05)

        async def make_request():
            await client._rate_limit()

        # Make multiple concurrent calls
        start = time.time()
        await asyncio.gather(*[make_request() for _ in range(5)])
        elapsed = time.time() - start

        # Should have delayed appropriately for all requests
        # 5 requests with 0.05s delay = at least 0.2s
        assert elapsed >= 0.15

        await client.close()

    @pytest.mark.asyncio
    async def test_rate_limit_updates_last_request_time(self):
        """Test _rate_limit updates _last_request_time."""
        client = HTTPClient(rate_limit_delay=0.1)

        initial_time = client._last_request_time
        await client._rate_limit()

        assert client._last_request_time > initial_time

        await client.close()


class TestGetRequests:
    """Test suite for GET requests."""

    @pytest.mark.asyncio
    async def test_get_success(self, mock_response):
        """Test successful GET request."""
        response = mock_response(status_code=200, text="Success")

        client = HTTPClient()
        with patch.object(client, "_request_with_retry", return_value=response):
            result = await client.get("https://example.com")

            assert result.status_code == 200
            assert result.text == "Success"

        await client.close()

    @pytest.mark.asyncio
    async def test_get_with_custom_headers(self, mock_response):
        """Test GET request with custom headers."""
        response = mock_response(status_code=200)

        client = HTTPClient()
        with patch.object(client, "_request_with_retry", return_value=response) as mock:
            await client.get("https://example.com", headers={"X-Custom": "value"})

            mock.assert_called_once()
            call_kwargs = mock.call_args[1]
            assert "headers" in call_kwargs
            assert call_kwargs["headers"]["X-Custom"] == "value"

        await client.close()

    @pytest.mark.asyncio
    async def test_get_with_query_params(self, mock_response):
        """Test GET request with query parameters."""
        response = mock_response(status_code=200)

        client = HTTPClient()
        with patch.object(client, "_request_with_retry", return_value=response) as mock:
            await client.get("https://example.com", params={"q": "test", "limit": 10})

            mock.assert_called_once()
            call_kwargs = mock.call_args[1]
            assert "params" in call_kwargs

        await client.close()

    @pytest.mark.asyncio
    async def test_get_calls_request_with_retry(self):
        """Test get method calls _request_with_retry."""
        client = HTTPClient()

        with patch.object(
            client, "_request_with_retry", new_callable=AsyncMock
        ) as mock:
            mock.return_value = Mock(status_code=200)
            await client.get("https://example.com")

            mock.assert_called_once_with("GET", "https://example.com")

        await client.close()


class TestPostRequests:
    """Test suite for POST requests."""

    @pytest.mark.asyncio
    async def test_post_success(self, mock_response):
        """Test successful POST request."""
        response = mock_response(status_code=201, text="Created")

        client = HTTPClient()
        with patch.object(client, "_request_with_retry", return_value=response):
            result = await client.post("https://example.com")

            assert result.status_code == 201
            assert result.text == "Created"

        await client.close()

    @pytest.mark.asyncio
    async def test_post_with_json_data(self, mock_response):
        """Test POST request with JSON data."""
        response = mock_response(status_code=200)

        client = HTTPClient()
        with patch.object(client, "_request_with_retry", return_value=response) as mock:
            await client.post("https://example.com", json={"key": "value"})

            mock.assert_called_once()
            call_kwargs = mock.call_args[1]
            assert "json" in call_kwargs
            assert call_kwargs["json"] == {"key": "value"}

        await client.close()

    @pytest.mark.asyncio
    async def test_post_with_form_data(self, mock_response):
        """Test POST request with form data."""
        response = mock_response(status_code=200)

        client = HTTPClient()
        with patch.object(client, "_request_with_retry", return_value=response) as mock:
            await client.post("https://example.com", data={"field": "value"})

            mock.assert_called_once()
            call_kwargs = mock.call_args[1]
            assert "data" in call_kwargs

        await client.close()

    @pytest.mark.asyncio
    async def test_post_calls_request_with_retry(self):
        """Test post method calls _request_with_retry."""
        client = HTTPClient()

        with patch.object(
            client, "_request_with_retry", new_callable=AsyncMock
        ) as mock:
            mock.return_value = Mock(status_code=200)
            await client.post("https://example.com")

            mock.assert_called_once_with("POST", "https://example.com")

        await client.close()


class TestGetJson:
    """Test suite for get_json method."""

    @pytest.mark.asyncio
    async def test_get_json_success(self, mock_response):
        """Test successful JSON retrieval."""
        json_data = {"name": "test", "version": "1.0"}
        response = mock_response(status_code=200, json_data=json_data)

        client = HTTPClient()
        with patch.object(client, "get", return_value=response):
            result = await client.get_json("https://example.com/api")

            assert result == json_data

        await client.close()

    @pytest.mark.asyncio
    async def test_get_json_empty_object(self, mock_response):
        """Test get_json with empty JSON object."""
        response = mock_response(status_code=200, json_data={})

        client = HTTPClient()
        with patch.object(client, "get", return_value=response):
            result = await client.get_json("https://example.com/api")

            assert result == {}

        await client.close()

    @pytest.mark.asyncio
    async def test_get_json_nested_data(self, mock_response):
        """Test get_json with nested JSON structure."""
        json_data = {
            "info": {"name": "package", "version": "1.0"},
            "releases": {"1.0": [{"url": "https://example.com"}]},
        }
        response = mock_response(status_code=200, json_data=json_data)

        client = HTTPClient()
        with patch.object(client, "get", return_value=response):
            result = await client.get_json("https://example.com/api")

            assert result["info"]["name"] == "package"
            assert "releases" in result

        await client.close()

    @pytest.mark.asyncio
    async def test_get_json_invalid_json(self, mock_response):
        """Test get_json raises NetworkError for invalid JSON."""
        response = mock_response(status_code=200, text="Not JSON")
        response.json.side_effect = ValueError("Invalid JSON")

        client = HTTPClient()
        with patch.object(client, "get", return_value=response):
            with pytest.raises(NetworkError) as exc_info:
                await client.get_json("https://example.com/api")

            assert "Invalid JSON response" in str(exc_info.value)

        await client.close()

    @pytest.mark.asyncio
    async def test_get_json_with_kwargs(self, mock_response):
        """Test get_json passes kwargs to get method."""
        response = mock_response(status_code=200, json_data={"test": "data"})

        client = HTTPClient()
        with patch.object(client, "get", return_value=response) as mock:
            await client.get_json(
                "https://example.com/api", headers={"X-Custom": "value"}
            )

            mock.assert_called_once()
            call_kwargs = mock.call_args[1]
            assert "headers" in call_kwargs

        await client.close()


class TestBatchGetJson:
    """Test suite for batch_get_json method."""

    @pytest.mark.asyncio
    async def test_batch_get_json_single_url(self, mock_response):
        """Test batch_get_json with single URL."""
        json_data = {"name": "package"}
        response = mock_response(status_code=200, json_data=json_data)

        client = HTTPClient()
        with patch.object(client, "get_json", return_value=json_data):
            results = await client.batch_get_json(["https://example.com/api"])

            assert len(results) == 1
            assert results["https://example.com/api"] == json_data

        await client.close()

    @pytest.mark.asyncio
    async def test_batch_get_json_multiple_urls(self):
        """Test batch_get_json with multiple URLs."""
        urls = [
            "https://example.com/api/1",
            "https://example.com/api/2",
            "https://example.com/api/3",
        ]

        client = HTTPClient()

        async def mock_get_json(url):
            return {"url": url, "data": "test"}

        with patch.object(client, "get_json", side_effect=mock_get_json):
            results = await client.batch_get_json(urls)

            assert len(results) == 3
            for url in urls:
                assert url in results
                assert results[url]["url"] == url

        await client.close()

    @pytest.mark.asyncio
    async def test_batch_get_json_empty_list(self):
        """Test batch_get_json with empty URL list."""
        client = HTTPClient()
        results = await client.batch_get_json([])

        assert results == {}

        await client.close()

    @pytest.mark.asyncio
    async def test_batch_get_json_handles_failures(self):
        """Test batch_get_json handles individual failures gracefully."""
        urls = ["https://example.com/1", "https://example.com/2"]

        client = HTTPClient()

        async def mock_get_json(url):
            if "1" in url:
                raise NetworkError("Failed", url=url)
            return {"data": "success"}

        with patch.object(client, "get_json", side_effect=mock_get_json):
            results = await client.batch_get_json(urls)

            # Failed URL should have empty dict
            assert results["https://example.com/1"] == {}
            # Successful URL should have data
            assert results["https://example.com/2"] == {"data": "success"}

        await client.close()

    @pytest.mark.asyncio
    async def test_batch_get_json_all_failures(self):
        """Test batch_get_json when all requests fail."""
        urls = ["https://example.com/1", "https://example.com/2"]

        client = HTTPClient()

        async def mock_get_json(url):
            raise NetworkError("Failed", url=url)

        with patch.object(client, "get_json", side_effect=mock_get_json):
            results = await client.batch_get_json(urls)

            assert all(results[url] == {} for url in urls)

        await client.close()

    @pytest.mark.asyncio
    async def test_batch_get_json_with_progress_callback(self):
        """Test batch_get_json calls progress callback."""
        urls = [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3",
        ]
        progress_calls = []

        def progress_callback(completed, total):
            progress_calls.append((completed, total))

        client = HTTPClient()

        async def mock_get_json(url):
            await asyncio.sleep(0.01)
            return {"data": "test"}

        with patch.object(client, "get_json", side_effect=mock_get_json):
            await client.batch_get_json(urls, progress_callback=progress_callback)

            # Should have been called 3 times
            assert len(progress_calls) == 3
            # Check progression
            assert progress_calls[0][0] == 1
            assert progress_calls[1][0] == 2
            assert progress_calls[2][0] == 3
            # Total should always be 3
            assert all(call[1] == 3 for call in progress_calls)

        await client.close()

    @pytest.mark.asyncio
    async def test_batch_get_json_respects_concurrency_limit(self):
        """Test batch_get_json respects max_concurrency."""
        urls = [f"https://example.com/{i}" for i in range(20)]
        max_concurrent = 0

        client = HTTPClient(max_concurrency=5)
        await client._ensure_client()

        # Track the semaphore's locked count directly
        original_acquire = client._semaphore.acquire
        original_release = client._semaphore.release

        async def tracked_acquire():
            nonlocal max_concurrent
            result = await original_acquire()
            # After acquiring, check how many are locked (max_concurrency - _value)
            locked = 5 - client._semaphore._value
            max_concurrent = max(max_concurrent, locked)
            return result

        # Mock the actual HTTP request to return quickly
        mock_response = Mock()
        mock_response.json.return_value = {"version": "1.0.0"}
        mock_response.text = '{"version": "1.0.0"}'
        mock_response.status_code = 200

        async def mock_request(*args, **kwargs):
            await asyncio.sleep(0.01)  # Small delay
            return mock_response

        with patch.object(
            client._semaphore, "acquire", side_effect=tracked_acquire
        ), patch.object(client._client, "request", side_effect=mock_request):

            await client.batch_get_json(urls)

            # Should not exceed concurrency limit
            assert max_concurrent <= 5

        await client.close()


class TestRequestWithRetry:
    """Test suite for _request_with_retry method."""

    @pytest.mark.asyncio
    async def test_request_with_retry_success_first_attempt(self, mock_response):
        """Test successful request on first attempt."""
        response = mock_response(status_code=200)

        client = HTTPClient()
        await client._ensure_client()

        with patch.object(client._client, "request", return_value=response):
            result = await client._request_with_retry("GET", "https://example.com")

            assert result.status_code == 200

        await client.close()

    @pytest.mark.asyncio
    async def test_request_with_retry_strips_quotes_from_url(self, mock_response):
        """Test request strips quotes from URL."""
        response = mock_response(status_code=200)

        client = HTTPClient()
        await client._ensure_client()

        with patch.object(client._client, "request", return_value=response) as mock:
            await client._request_with_retry("GET", '"https://example.com"')

            # Should strip quotes
            call_args = mock.call_args[0]
            assert call_args[1] == "https://example.com"

        await client.close()

    @pytest.mark.asyncio
    async def test_request_with_retry_404_raises_pypi_error(self):
        """Test 404 response raises PyPIError."""
        response = Mock(spec=httpx.Response)
        response.status_code = 404

        client = HTTPClient()
        await client._ensure_client()

        with patch.object(client._client, "request", return_value=response):
            with pytest.raises(PyPIError) as exc_info:
                await client._request_with_retry("GET", "https://example.com")

            assert exc_info.value.details["status_code"] == 404

        await client.close()

    @pytest.mark.asyncio
    async def test_request_with_retry_500_retries(self, mock_response):
        """Test 5xx errors trigger retries."""
        response_500 = mock_response(status_code=500)
        response_200 = mock_response(status_code=200)

        client = HTTPClient(max_retries=2)
        await client._ensure_client()

        with patch.object(
            client._client,
            "request",
            side_effect=[response_500, response_500, response_200],
        ):
            result = await client._request_with_retry("GET", "https://example.com")

            # Should eventually succeed
            assert result.status_code == 200

        await client.close()

    @pytest.mark.asyncio
    async def test_request_with_retry_timeout_retries(self):
        """Test timeout errors trigger retries."""
        client = HTTPClient(max_retries=2)
        await client._ensure_client()

        response = Mock(spec=httpx.Response)
        response.status_code = 200

        with patch.object(
            client._client,
            "request",
            side_effect=[
                httpx.TimeoutException("Timeout"),
                httpx.TimeoutException("Timeout"),
                response,
            ],
        ):
            result = await client._request_with_retry("GET", "https://example.com")

            assert result.status_code == 200

        await client.close()

    @pytest.mark.asyncio
    async def test_request_with_retry_network_error_retries(self):
        """Test network errors trigger retries."""
        client = HTTPClient(max_retries=2)
        await client._ensure_client()

        response = Mock(spec=httpx.Response)
        response.status_code = 200

        with patch.object(
            client._client,
            "request",
            side_effect=[
                httpx.NetworkError("Connection failed"),
                httpx.NetworkError("Connection failed"),
                response,
            ],
        ):
            result = await client._request_with_retry("GET", "https://example.com")

            assert result.status_code == 200

        await client.close()

    @pytest.mark.asyncio
    async def test_request_with_retry_429_rate_limit(self):
        """Test 429 rate limiting with retry."""
        response_429 = Mock(spec=httpx.Response)
        response_429.status_code = 429
        response_429.headers = {"Retry-After": "1"}

        response_200 = Mock(spec=httpx.Response)
        response_200.status_code = 200

        client = HTTPClient()
        await client._ensure_client()

        with patch.object(
            client._client, "request", side_effect=[response_429, response_200]
        ):
            with patch("asyncio.sleep") as mock_sleep:
                result = await client._request_with_retry("GET", "https://example.com")

                # Should have slept for retry-after duration
                mock_sleep.assert_called()
                assert result.status_code == 200

        await client.close()

    @pytest.mark.asyncio
    async def test_request_with_retry_429_max_retries_exceeded(self):
        """Test 429 rate limiting exceeds max retries."""
        response_429 = Mock(spec=httpx.Response)
        response_429.status_code = 429
        response_429.headers = {"Retry-After": "1"}

        client = HTTPClient(
            max_retries=10
        )  # Use higher value to allow 429 logic to trigger
        await client._ensure_client()

        # Return 429 more than max_429_retries (5) times
        with patch.object(client._client, "request", return_value=response_429):
            with patch("asyncio.sleep"):
                with pytest.raises(NetworkError) as exc_info:
                    await client._request_with_retry("GET", "https://example.com")

                # Check that it's a rate limit error
                error = exc_info.value
                # Should specifically mention rate limiting
                assert (
                    "Rate limit exceeded" in str(error)
                    or error.details.get("status_code") == 429
                )

        await client.close()

    @pytest.mark.asyncio
    async def test_request_with_retry_4xx_no_retry(self):
        """Test 4xx errors (except 429) don't retry."""
        response_400 = Mock(spec=httpx.Response)
        response_400.status_code = 400
        response_400.text = "Bad request"
        response_400.raise_for_status.side_effect = httpx.HTTPStatusError(
            "HTTP 400", request=Mock(), response=response_400
        )

        client = HTTPClient(max_retries=3)
        await client._ensure_client()

        with patch.object(client._client, "request", return_value=response_400):
            with pytest.raises(NetworkError) as exc_info:
                await client._request_with_retry("GET", "https://example.com")

            # Should fail immediately without retries
            assert exc_info.value.details["status_code"] == 400

        await client.close()

    @pytest.mark.asyncio
    async def test_request_with_retry_exponential_backoff(self):
        """Test exponential backoff between retries."""
        client = HTTPClient(max_retries=3)
        await client._ensure_client()

        response = Mock(spec=httpx.Response)
        response.status_code = 200

        sleep_times = []

        async def mock_sleep(duration):
            sleep_times.append(duration)

        with patch.object(
            client._client,
            "request",
            side_effect=[
                httpx.NetworkError("Error"),
                httpx.NetworkError("Error"),
                httpx.NetworkError("Error"),
                response,
            ],
        ):
            with patch("asyncio.sleep", side_effect=mock_sleep):
                await client._request_with_retry("GET", "https://example.com")

                # Should have exponential backoff
                # First retry: 2^0 + jitter
                # Second retry: 2^1 + jitter
                # Third retry: 2^2 + jitter
                assert len(sleep_times) == 3
                # Check roughly exponential (accounting for jitter)
                assert sleep_times[0] < sleep_times[1] < sleep_times[2]

        await client.close()

    @pytest.mark.asyncio
    async def test_request_with_retry_max_retries_exceeded(self):
        """Test max retries exceeded raises NetworkError."""
        client = HTTPClient(max_retries=2)
        await client._ensure_client()

        with patch.object(
            client._client,
            "request",
            side_effect=httpx.NetworkError("Connection failed"),
        ):
            with patch("asyncio.sleep"):
                with pytest.raises(NetworkError) as exc_info:
                    await client._request_with_retry("GET", "https://example.com")

                assert "failed after" in str(exc_info.value).lower()

        await client.close()

    @pytest.mark.asyncio
    async def test_request_with_retry_uses_semaphore(self, mock_response):
        """Test request uses semaphore for concurrency control."""
        response = mock_response(status_code=200)

        client = HTTPClient(max_concurrency=5)
        await client._ensure_client()

        # Check semaphore is acquired
        initial_value = client._semaphore._value

        with patch.object(client._client, "request", return_value=response):
            await client._request_with_retry("GET", "https://example.com")

        # Semaphore should be released back
        assert client._semaphore._value == initial_value

        await client.close()

    @pytest.mark.asyncio
    async def test_request_with_retry_enforces_rate_limit(self, mock_response):
        """Test request enforces rate limiting."""
        response = mock_response(status_code=200)

        client = HTTPClient(rate_limit_delay=0.1)
        await client._ensure_client()

        with patch.object(client._client, "request", return_value=response):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock) as mock_rl:
                await client._request_with_retry("GET", "https://example.com")

                # Should have called rate limit
                mock_rl.assert_called_once()

        await client.close()


class TestErrorHandling:
    """Test suite for error handling scenarios."""

    @pytest.mark.asyncio
    async def test_network_error_details(self):
        """Test NetworkError includes proper details."""
        client = HTTPClient(max_retries=0)
        await client._ensure_client()

        with patch.object(
            client._client,
            "request",
            side_effect=httpx.NetworkError("Connection refused"),
        ):
            with pytest.raises(NetworkError) as exc_info:
                await client._request_with_retry("GET", "https://example.com")

            assert "example.com" in exc_info.value.details["url"]

        await client.close()

    @pytest.mark.asyncio
    async def test_pypi_error_details(self):
        """Test PyPIError includes proper details."""
        response = Mock(spec=httpx.Response)
        response.status_code = 404

        client = HTTPClient()
        await client._ensure_client()

        with patch.object(client._client, "request", return_value=response):
            with pytest.raises(PyPIError) as exc_info:
                await client._request_with_retry("GET", "https://pypi.org/test")

            error = exc_info.value
            assert error.details["status_code"] == 404
            assert "pypi.org" in error.details["url"]

        await client.close()

    @pytest.mark.asyncio
    async def test_http_status_error_with_response_body(self):
        """Test NetworkError includes response body for debugging."""
        response = Mock(spec=httpx.Response)
        response.status_code = 403
        response.text = "Forbidden: Access denied"
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "HTTP 403", request=Mock(), response=response
        )

        client = HTTPClient(max_retries=0)
        await client._ensure_client()

        with patch.object(client._client, "request", return_value=response):
            with pytest.raises(NetworkError) as exc_info:
                await client._request_with_retry("GET", "https://example.com")

            error = exc_info.value
            assert error.details["status_code"] == 403
            # Response body is stored as 'response' (truncated) in details
            assert "response" in error.details
            assert "Forbidden" in error.details["response"]
            # Full response body is in the attribute
            assert error.response_body == "Forbidden: Access denied"

        await client.close()


class TestEdgeCases:
    """Test suite for edge cases and corner cases."""

    @pytest.mark.asyncio
    async def test_url_with_single_quotes(self, mock_response):
        """Test URL with single quotes is stripped."""
        response = mock_response(status_code=200)

        client = HTTPClient()
        await client._ensure_client()

        with patch.object(client._client, "request", return_value=response) as mock:
            await client._request_with_retry("GET", "'https://example.com'")

            call_args = mock.call_args[0]
            assert call_args[1] == "https://example.com"

        await client.close()

    @pytest.mark.asyncio
    async def test_url_with_double_quotes(self, mock_response):
        """Test URL with double quotes is stripped."""
        response = mock_response(status_code=200)

        client = HTTPClient()
        await client._ensure_client()

        with patch.object(client._client, "request", return_value=response) as mock:
            await client._request_with_retry("GET", '"https://example.com"')

            call_args = mock.call_args[0]
            assert call_args[1] == "https://example.com"

        await client.close()

    @pytest.mark.asyncio
    async def test_empty_url(self):
        """Test empty URL raises appropriate error."""
        client = HTTPClient()
        await client._ensure_client()

        with patch.object(client._client, "request", side_effect=httpx.InvalidURL("")):
            with pytest.raises((NetworkError, httpx.InvalidURL)):
                await client._request_with_retry("GET", "")

        await client.close()

    @pytest.mark.asyncio
    async def test_very_long_url(self, mock_response):
        """Test very long URL is handled."""
        long_url = "https://example.com/" + "a" * 10000
        response = mock_response(status_code=200)

        client = HTTPClient()
        await client._ensure_client()

        with patch.object(client._client, "request", return_value=response):
            result = await client._request_with_retry("GET", long_url)
            assert result.status_code == 200

        await client.close()

    @pytest.mark.asyncio
    async def test_unicode_in_url(self, mock_response):
        """Test Unicode characters in URL."""
        response = mock_response(status_code=200)

        client = HTTPClient()
        await client._ensure_client()

        with patch.object(client._client, "request", return_value=response):
            await client._request_with_retry("GET", "https://example.com/テスト")

        await client.close()

    @pytest.mark.asyncio
    async def test_retry_after_header_missing(self):
        """Test 429 with missing Retry-After header uses default."""
        response_429 = Mock(spec=httpx.Response)
        response_429.status_code = 429
        response_429.headers = {}  # No Retry-After header

        response_200 = Mock(spec=httpx.Response)
        response_200.status_code = 200

        client = HTTPClient()
        await client._ensure_client()

        with patch.object(
            client._client, "request", side_effect=[response_429, response_200]
        ):
            with patch("asyncio.sleep") as mock_sleep:
                await client._request_with_retry("GET", "https://example.com")

                # Should use default of 1 second
                call_args = mock_sleep.call_args[0]
                assert call_args[0] == 1

        await client.close()

    @pytest.mark.asyncio
    async def test_zero_timeout(self):
        """Test client with zero timeout."""
        client = HTTPClient(timeout=0)
        await client._ensure_client()

        # Should create client even with zero timeout
        assert client._client is not None

        await client.close()

    @pytest.mark.asyncio
    async def test_zero_max_retries(self):
        """Test client with zero max_retries fails immediately."""
        client = HTTPClient(max_retries=0)
        await client._ensure_client()

        with patch.object(
            client._client,
            "request",
            side_effect=httpx.NetworkError("Connection failed"),
        ):
            with pytest.raises(NetworkError):
                await client._request_with_retry("GET", "https://example.com")

        await client.close()

    @pytest.mark.asyncio
    async def test_very_high_max_retries(self):
        """Test client with very high max_retries."""
        client = HTTPClient(max_retries=100)
        assert client.max_retries == 100
        await client.close()

    @pytest.mark.asyncio
    async def test_batch_get_json_single_failure_doesnt_stop_others(self):
        """Test single failure in batch doesn't prevent other requests."""
        urls = [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3",
        ]

        client = HTTPClient()

        async def mock_get_json(url):
            if "2" in url:
                raise NetworkError("Failed", url=url)
            await asyncio.sleep(0.01)
            return {"url": url, "success": True}

        with patch.object(client, "get_json", side_effect=mock_get_json):
            results = await client.batch_get_json(urls)

            # URL 1 and 3 should succeed
            assert results["https://example.com/1"]["success"] is True
            assert results["https://example.com/3"]["success"] is True
            # URL 2 should fail
            assert results["https://example.com/2"] == {}

        await client.close()

    @pytest.mark.asyncio
    async def test_get_json_with_array_response(self, mock_response):
        """Test get_json handles JSON array responses."""
        json_data = [{"id": 1}, {"id": 2}]
        response = mock_response(status_code=200)
        response.json.return_value = json_data

        client = HTTPClient()
        with patch.object(client, "get", return_value=response):
            result = await client.get_json("https://example.com/api")

            # Should work even though it's an array
            assert result == json_data

        await client.close()

    @pytest.mark.asyncio
    async def test_concurrent_requests_share_rate_limit(self):
        """Test concurrent requests share the same rate limit."""
        client = HTTPClient(rate_limit_delay=0.1)

        start = time.time()

        # Mock the actual request to avoid real network calls
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200

        async with client:
            # Patch the client's request method before making calls
            with patch.object(client._client, "request", return_value=mock_response):

                async def make_request():
                    await client._request_with_retry("GET", "https://example.com")

                # Make 3 concurrent requests
                await asyncio.gather(*[make_request() for _ in range(3)])

        elapsed = time.time() - start

        # Should take at least 0.2s (3 requests with 0.1s delay between them)
        assert elapsed >= 0.15

    @pytest.mark.asyncio
    async def test_response_without_text_attribute(self):
        """Test handling response that has no text attribute."""
        response = Mock(spec=httpx.Response)
        response.status_code = 200
        response.json.side_effect = ValueError("Invalid JSON")
        # Remove text attribute
        del response.text

        client = HTTPClient()
        with patch.object(client, "get", return_value=response):
            with pytest.raises(NetworkError) as exc_info:
                await client.get_json("https://example.com")

            # Should handle missing text gracefully
            assert "Invalid JSON" in str(exc_info.value)

        await client.close()
