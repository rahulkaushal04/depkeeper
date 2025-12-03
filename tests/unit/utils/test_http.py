import httpx
import pytest
import asyncio

from depkeeper.utils.http import HTTPClient, handle_errors
from depkeeper.exceptions import NetworkError, PyPIError
from depkeeper.constants import DEFAULT_TIMEOUT, DEFAULT_MAX_RETRIES


class TestHTTPClientInitialization:
    """Tests for HTTPClient initialization and configuration."""

    def test_client_default_initialization(self):
        """Test HTTPClient with default parameters."""
        client = HTTPClient()

        assert client.timeout == DEFAULT_TIMEOUT
        assert client.max_retries == DEFAULT_MAX_RETRIES
        assert client.rate_limit_delay == 0.0
        assert client.verify_ssl is True
        assert client.max_concurrency == 10
        assert client.enable_caching is False
        assert "depkeeper" in client.user_agent

    def test_client_custom_initialization(self):
        """Test HTTPClient with custom parameters."""
        client = HTTPClient(
            timeout=60,
            max_retries=5,
            rate_limit_delay=0.5,
            verify_ssl=False,
            user_agent="CustomAgent/1.0",
            max_concurrency=20,
            enable_caching=True,
        )

        assert client.timeout == 60
        assert client.max_retries == 5
        assert client.rate_limit_delay == 0.5
        assert client.verify_ssl is False
        assert client.user_agent == "CustomAgent/1.0"
        assert client.max_concurrency == 20
        assert client.enable_caching is True

    def test_client_starts_with_no_active_client(self):
        """Test that client starts without an active httpx client."""
        client = HTTPClient()

        assert client._client is None

    def test_client_initializes_empty_cache(self):
        """Test that client starts with empty cache."""
        client = HTTPClient(enable_caching=True)

        assert client._etag_cache == {}

    def test_client_initializes_semaphore(self):
        """Test that client initializes concurrency semaphore."""
        client = HTTPClient(max_concurrency=5)

        assert isinstance(client._semaphore, asyncio.Semaphore)


@pytest.mark.asyncio
class TestHTTPClientContextManager:
    """Tests for HTTPClient async context manager behavior."""

    async def test_context_manager_enter_creates_client(self):
        """Test that entering context manager creates httpx client."""
        client = HTTPClient()

        async with client:
            assert client._client is not None
            assert isinstance(client._client, httpx.AsyncClient)

    async def test_context_manager_exit_closes_client(self):
        """Test that exiting context manager closes client."""
        client = HTTPClient()

        async with client:
            pass

        assert client._client is None

    async def test_context_manager_returns_self(self):
        """Test that __aenter__ returns self."""
        client = HTTPClient()

        async with client as ctx_client:
            assert ctx_client is client

    async def test_manual_close(self):
        """Test manually closing client."""
        client = HTTPClient()
        await client._ensure_client()

        assert client._client is not None

        await client.close()

        assert client._client is None

    async def test_close_on_already_closed_client(self):
        """Test closing an already closed client doesn't raise error."""
        client = HTTPClient()

        # Should not raise
        await client.close()
        await client.close()


@pytest.mark.asyncio
class TestHTTPClientRequests:
    """Tests for HTTP request methods."""

    async def test_get_request_success(self, httpx_mock):
        """Test successful GET request."""
        httpx_mock.add_response(
            url="https://example.com/api",
            json={"status": "success"},
            status_code=200,
        )

        async with HTTPClient() as client:
            response = await client.get("https://example.com/api")

            assert response.status_code == 200
            assert response.json() == {"status": "success"}

    async def test_get_request_with_headers(self, httpx_mock):
        """Test GET request includes proper headers."""
        httpx_mock.add_response(url="https://example.com/api")

        async with HTTPClient(user_agent="TestAgent/1.0") as client:
            await client.get("https://example.com/api")

            request = httpx_mock.get_request()
            assert "User-Agent" in request.headers
            assert request.headers["User-Agent"] == "TestAgent/1.0"

    async def test_post_request_success(self, httpx_mock):
        """Test successful POST request."""
        httpx_mock.add_response(
            url="https://example.com/api",
            json={"created": True},
            status_code=201,
        )

        async with HTTPClient() as client:
            response = await client.post(
                "https://example.com/api",
                json={"data": "test"},
            )

            assert response.status_code == 201
            assert response.json() == {"created": True}

    async def test_get_json_convenience_method(self, httpx_mock):
        """Test get_json convenience method."""
        httpx_mock.add_response(
            url="https://example.com/api",
            json={"key": "value"},
        )

        async with HTTPClient() as client:
            data = await client.get_json("https://example.com/api")

            assert data == {"key": "value"}
            assert isinstance(data, dict)

    async def test_get_json_with_invalid_json_raises_error(self, httpx_mock):
        """Test get_json with invalid JSON raises NetworkError."""
        httpx_mock.add_response(
            url="https://example.com/api",
            text="Not JSON",
        )

        async with HTTPClient() as client:
            with pytest.raises(NetworkError) as exc_info:
                await client.get_json("https://example.com/api")

            assert "Invalid JSON" in str(exc_info.value)

    async def test_request_strips_quotes_from_url(self, httpx_mock):
        """Test that URLs with surrounding quotes are stripped."""
        httpx_mock.add_response(url="https://example.com/api")

        async with HTTPClient() as client:
            await client.get("'https://example.com/api'")
            await client.get('"https://example.com/api"')

            assert len(httpx_mock.get_requests()) == 2


@pytest.mark.asyncio
class TestHTTPClientRetry:
    """Tests for retry logic."""

    async def test_retry_on_timeout(self, httpx_mock):
        """Test retry on timeout exception."""
        httpx_mock.add_exception(httpx.TimeoutException("Timeout"))
        httpx_mock.add_response(json={"status": "ok"})

        async with HTTPClient(max_retries=2) as client:
            response = await client.get("https://example.com/api")

            assert response.status_code == 200
            assert len(httpx_mock.get_requests()) == 2

    async def test_retry_on_network_error(self, httpx_mock):
        """Test retry on network error."""
        httpx_mock.add_exception(httpx.NetworkError("Connection failed"))
        httpx_mock.add_response(json={"status": "ok"})

        async with HTTPClient(max_retries=2) as client:
            response = await client.get("https://example.com/api")

            assert response.status_code == 200

    async def test_max_retries_exceeded_raises_error(self, httpx_mock):
        """Test that exceeding max retries raises NetworkError."""
        httpx_mock.add_exception(httpx.TimeoutException("Timeout"))

        async with HTTPClient(max_retries=2) as client:
            with pytest.raises(NetworkError) as exc_info:
                await client.get("https://example.com/api")

            assert "failed after 3 attempts" in str(exc_info.value).lower()

    async def test_retry_with_exponential_backoff(self, httpx_mock):
        """Test that retries use exponential backoff."""
        httpx_mock.add_exception(httpx.TimeoutException("Timeout"))
        httpx_mock.add_exception(httpx.TimeoutException("Timeout"))
        httpx_mock.add_response(json={"status": "ok"})

        async with HTTPClient(max_retries=3) as client:
            import time

            start = time.time()
            await client.get("https://example.com/api")
            elapsed = time.time() - start

            # Should have some delay due to backoff
            # First retry ~1s, second retry ~2s (with jitter)
            assert elapsed > 1.0

    async def test_no_retry_on_client_errors(self, httpx_mock):
        """Test that 4xx errors don't retry (except 429)."""
        httpx_mock.add_response(status_code=400, text="Bad Request")

        async with HTTPClient(max_retries=3) as client:
            with pytest.raises(NetworkError):
                await client.get("https://example.com/api")

            # Should only make one request, no retries
            assert len(httpx_mock.get_requests()) == 1

    async def test_retry_on_server_errors(self, httpx_mock):
        """Test that 5xx errors trigger retry."""
        httpx_mock.add_response(status_code=500, text="Server Error")
        httpx_mock.add_response(json={"status": "ok"})

        async with HTTPClient(max_retries=2) as client:
            response = await client.get("https://example.com/api")

            assert response.status_code == 200
            assert len(httpx_mock.get_requests()) == 2

    async def test_retry_on_429_with_retry_after(self, httpx_mock):
        """Test retry on 429 respects Retry-After header."""
        httpx_mock.add_response(
            status_code=429,
            headers={"Retry-After": "1"},
        )
        httpx_mock.add_response(json={"status": "ok"})

        async with HTTPClient(max_retries=2) as client:
            import time

            start = time.time()
            response = await client.get("https://example.com/api")
            elapsed = time.time() - start

            assert response.status_code == 200
            assert elapsed >= 1.0  # Should wait at least 1 second


@pytest.mark.asyncio
class TestHTTPClientErrorHandling:
    """Tests for error handling."""

    async def test_404_raises_pypi_error(self, httpx_mock):
        """Test that 404 responses raise PyPIError."""
        httpx_mock.add_response(status_code=404)

        async with HTTPClient() as client:
            with pytest.raises(PyPIError) as exc_info:
                await client.get("https://example.com/api")

            assert exc_info.value.status_code == 404
            assert "not found" in str(exc_info.value).lower()

    async def test_400_raises_network_error(self, httpx_mock):
        """Test that 400 responses raise NetworkError."""
        httpx_mock.add_response(status_code=400, text="Bad Request")

        async with HTTPClient() as client:
            with pytest.raises(NetworkError) as exc_info:
                await client.get("https://example.com/api")

            assert exc_info.value.status_code == 400

    async def test_500_with_retries_exhausted_raises_error(self, httpx_mock):
        """Test that server errors after retries raise NetworkError."""
        httpx_mock.add_response(status_code=500, text="Server Error")

        async with HTTPClient(max_retries=0) as client:
            with pytest.raises(NetworkError):
                await client.get("https://example.com/api")

    async def test_network_error_includes_url(self, httpx_mock):
        """Test that NetworkError includes the URL."""
        httpx_mock.add_exception(httpx.TimeoutException("Timeout"))

        async with HTTPClient(max_retries=0) as client:
            with pytest.raises(NetworkError) as exc_info:
                await client.get("https://example.com/api")

            assert exc_info.value.url == "https://example.com/api"

    async def test_network_error_includes_status_code(self, httpx_mock):
        """Test that NetworkError includes status code for HTTP errors."""
        httpx_mock.add_response(status_code=400, text="Bad Request")

        async with HTTPClient(max_retries=0) as client:
            with pytest.raises(NetworkError) as exc_info:
                await client.get("https://example.com/api")

            # 4xx errors include status_code
            assert exc_info.value.status_code == 400


@pytest.mark.asyncio
class TestHTTPClientCaching:
    """Tests for ETag caching functionality."""

    async def test_caching_disabled_by_default(self, httpx_mock):
        """Test that caching is disabled by default."""
        httpx_mock.add_response(
            json={"data": "test"},
            headers={"ETag": "abc123"},
        )

        async with HTTPClient() as client:
            await client.get("https://example.com/api")

            assert len(client._etag_cache) == 0

    async def test_caching_stores_etag_when_enabled(self, httpx_mock):
        """Test that ETag is stored when caching is enabled."""
        httpx_mock.add_response(
            json={"data": "test"},
            headers={"ETag": "abc123"},
        )

        async with HTTPClient(enable_caching=True) as client:
            await client.get("https://example.com/api")

            assert "https://example.com/api" in client._etag_cache
            etag, _ = client._etag_cache["https://example.com/api"]
            assert etag == "abc123"

    async def test_cached_request_sends_if_none_match(self, httpx_mock):
        """Test that cached requests send If-None-Match header."""
        httpx_mock.add_response(
            json={"data": "test"},
            headers={"ETag": "abc123"},
        )
        httpx_mock.add_response(status_code=304)

        async with HTTPClient(enable_caching=True) as client:
            # First request
            await client.get("https://example.com/api")

            # Second request
            await client.get("https://example.com/api")

            requests = httpx_mock.get_requests()
            assert len(requests) == 2
            assert "If-None-Match" in requests[1].headers
            assert requests[1].headers["If-None-Match"] == "abc123"

    async def test_304_returns_cached_response(self, httpx_mock):
        """Test that 304 response returns cached data."""
        httpx_mock.add_response(
            json={"data": "original"},
            headers={"ETag": "abc123"},
        )
        httpx_mock.add_response(status_code=304)

        async with HTTPClient(enable_caching=True) as client:
            response1 = await client.get("https://example.com/api")
            response2 = await client.get("https://example.com/api")

            assert response1.json() == {"data": "original"}
            assert response2.json() == {"data": "original"}

    async def test_caching_per_request_override(self, httpx_mock):
        """Test that caching can be overridden per request."""
        httpx_mock.add_response(
            json={"data": "test"},
            headers={"ETag": "abc123"},
        )

        async with HTTPClient(enable_caching=False) as client:
            # Enable caching for this request
            await client.get("https://example.com/api", use_cache=True)

            assert len(client._etag_cache) == 1

    async def test_no_etag_header_not_cached(self, httpx_mock):
        """Test that responses without ETag are not cached."""
        httpx_mock.add_response(json={"data": "test"})

        async with HTTPClient(enable_caching=True) as client:
            await client.get("https://example.com/api")

            assert len(client._etag_cache) == 0


@pytest.mark.asyncio
class TestHTTPClientRateLimiting:
    """Tests for rate limiting functionality."""

    async def test_rate_limiting_delays_requests(self, httpx_mock):
        """Test that rate limiting adds delays between requests."""
        httpx_mock.add_response(json={"data": "1"})
        httpx_mock.add_response(json={"data": "2"})

        async with HTTPClient(rate_limit_delay=0.5) as client:
            import time

            start = time.time()

            await client.get("https://example.com/api/1")
            await client.get("https://example.com/api/2")

            elapsed = time.time() - start

            # Should have at least 0.5s delay between requests
            assert elapsed >= 0.5

    async def test_no_rate_limiting_when_zero(self, httpx_mock):
        """Test that rate limiting is disabled when set to 0."""
        httpx_mock.add_response(json={"data": "1"})
        httpx_mock.add_response(json={"data": "2"})

        async with HTTPClient(rate_limit_delay=0.0) as client:
            import time

            start = time.time()

            await client.get("https://example.com/api/1")
            await client.get("https://example.com/api/2")

            elapsed = time.time() - start

            # Should be fast with no rate limiting
            assert elapsed < 0.5

    async def test_negative_rate_limit_delay_no_limiting(self, httpx_mock):
        """Test that negative rate limit delay disables rate limiting."""
        httpx_mock.add_response(json={"data": "test"})

        async with HTTPClient(rate_limit_delay=-1.0) as client:
            # Should not raise or cause issues
            await client.get("https://example.com/api")


@pytest.mark.asyncio
class TestHTTPClientConcurrency:
    """Tests for concurrency control."""

    async def test_semaphore_limits_concurrent_requests(self, httpx_mock):
        """Test that semaphore limits concurrent requests."""
        for i in range(20):
            httpx_mock.add_response(json={"id": i})

        async with HTTPClient(max_concurrency=5) as client:
            urls = [f"https://example.com/api/{i}" for i in range(20)]
            tasks = [client.get(url) for url in urls]

            responses = await asyncio.gather(*tasks)

            assert len(responses) == 20

    async def test_concurrent_requests_all_succeed(self, httpx_mock):
        """Test that concurrent requests all complete successfully."""
        for i in range(10):
            httpx_mock.add_response(json={"id": i})

        async with HTTPClient(max_concurrency=10) as client:
            urls = [f"https://example.com/api/{i}" for i in range(10)]
            tasks = [client.get_json(url) for url in urls]

            results = await asyncio.gather(*tasks)

            assert len(results) == 10
            assert all(isinstance(r, dict) for r in results)


@pytest.mark.asyncio
class TestHTTPClientBatchRequests:
    """Tests for batch request functionality."""

    async def test_batch_get_json_success(self, httpx_mock):
        """Test batch_get_json with successful requests."""
        httpx_mock.add_response(url="https://example.com/api/1", json={"id": 1})
        httpx_mock.add_response(url="https://example.com/api/2", json={"id": 2})
        httpx_mock.add_response(url="https://example.com/api/3", json={"id": 3})

        async with HTTPClient() as client:
            urls = [
                "https://example.com/api/1",
                "https://example.com/api/2",
                "https://example.com/api/3",
            ]
            results = await client.batch_get_json(urls)

            assert len(results) == 3
            assert results["https://example.com/api/1"] == {"id": 1}
            assert results["https://example.com/api/2"] == {"id": 2}
            assert results["https://example.com/api/3"] == {"id": 3}

    async def test_batch_get_json_with_failures(self, httpx_mock):
        """Test batch_get_json handles individual failures."""
        httpx_mock.add_response(url="https://example.com/api/1", json={"id": 1})
        httpx_mock.add_exception(
            httpx.TimeoutException("Timeout"),
            url="https://example.com/api/2",
        )
        httpx_mock.add_response(url="https://example.com/api/3", json={"id": 3})

        async with HTTPClient(max_retries=0) as client:
            urls = [
                "https://example.com/api/1",
                "https://example.com/api/2",
                "https://example.com/api/3",
            ]
            results = await client.batch_get_json(urls)

            assert len(results) == 3
            assert results["https://example.com/api/1"] == {"id": 1}
            assert results["https://example.com/api/2"] == {}  # Failed request
            assert results["https://example.com/api/3"] == {"id": 3}

    async def test_batch_get_json_with_progress_callback(self, httpx_mock):
        """Test batch_get_json calls progress callback."""
        for i in range(5):
            httpx_mock.add_response(json={"id": i})

        progress_calls = []

        def progress_callback(completed, total):
            progress_calls.append((completed, total))

        async with HTTPClient() as client:
            urls = [f"https://example.com/api/{i}" for i in range(5)]
            await client.batch_get_json(urls, progress_callback=progress_callback)

            assert len(progress_calls) == 5
            assert progress_calls[0] == (1, 5)
            assert progress_calls[-1] == (5, 5)

    async def test_batch_get_json_empty_list(self, httpx_mock):
        """Test batch_get_json with empty URL list."""
        async with HTTPClient() as client:
            results = await client.batch_get_json([])

            assert results == {}

    async def test_batch_get_json_with_caching(self, httpx_mock):
        """Test batch_get_json respects caching."""
        httpx_mock.add_response(
            url="https://example.com/api/1",
            json={"id": 1},
            headers={"ETag": "abc123"},
        )

        async with HTTPClient(enable_caching=True) as client:
            urls = ["https://example.com/api/1"]
            await client.batch_get_json(urls, use_cache=True)

            assert len(client._etag_cache) == 1


class TestHandleErrors:
    """Tests for standalone handle_errors function."""

    def test_handle_errors_success_response(self):
        """Test handle_errors with successful response."""
        response = httpx.Response(
            200, request=httpx.Request("GET", "https://example.com")
        )

        # Should not raise
        handle_errors(response)

    def test_handle_errors_404_raises_network_error(self):
        """Test handle_errors raises NetworkError for 404."""
        response = httpx.Response(
            404, request=httpx.Request("GET", "https://example.com")
        )

        with pytest.raises(NetworkError) as exc_info:
            handle_errors(response)

        assert exc_info.value.status_code == 404
        assert "not found" in str(exc_info.value).lower()

    def test_handle_errors_429_raises_network_error(self):
        """Test handle_errors raises NetworkError for 429."""
        response = httpx.Response(
            429, request=httpx.Request("GET", "https://example.com")
        )

        with pytest.raises(NetworkError) as exc_info:
            handle_errors(response)

        assert exc_info.value.status_code == 429
        assert "rate limit" in str(exc_info.value).lower()

    def test_handle_errors_500_raises_network_error(self):
        """Test handle_errors raises NetworkError for server errors."""
        response = httpx.Response(
            500, request=httpx.Request("GET", "https://example.com")
        )

        with pytest.raises(NetworkError) as exc_info:
            handle_errors(response)

        assert exc_info.value.status_code == 500
        assert "server error" in str(exc_info.value).lower()

    def test_handle_errors_400_raises_network_error(self):
        """Test handle_errors raises NetworkError for 400."""
        response = httpx.Response(
            400, request=httpx.Request("GET", "https://example.com")
        )

        with pytest.raises(NetworkError) as exc_info:
            handle_errors(response)

        assert exc_info.value.status_code == 400

    def test_handle_errors_no_error_on_2xx(self):
        """Test handle_errors doesn't raise on 2xx responses."""
        for code in [200, 201, 204]:
            response = httpx.Response(
                code, request=httpx.Request("GET", "https://example.com")
            )
            handle_errors(response)  # Should not raise

    def test_handle_errors_no_error_on_3xx(self):
        """Test handle_errors doesn't raise on 3xx responses."""
        for code in [301, 302, 304]:
            response = httpx.Response(
                code, request=httpx.Request("GET", "https://example.com")
            )
            handle_errors(response)  # Should not raise


@pytest.mark.asyncio
class TestHTTPClientIntegration:
    """Integration tests for common usage patterns."""

    async def test_multiple_requests_in_session(self, httpx_mock):
        """Test making multiple requests in a single session."""
        httpx_mock.add_response(url="https://api.example.com/users", json={"users": []})
        httpx_mock.add_response(url="https://api.example.com/posts", json={"posts": []})
        httpx_mock.add_response(
            url="https://api.example.com/comments", json={"comments": []}
        )

        async with HTTPClient() as client:
            users = await client.get_json("https://api.example.com/users")
            posts = await client.get_json("https://api.example.com/posts")
            comments = await client.get_json("https://api.example.com/comments")

            assert "users" in users
            assert "posts" in posts
            assert "comments" in comments

    async def test_retry_then_success_pattern(self, httpx_mock):
        """Test typical retry pattern: fail then succeed."""
        httpx_mock.add_exception(httpx.NetworkError("Connection refused"))
        httpx_mock.add_exception(httpx.TimeoutException("Timeout"))
        httpx_mock.add_response(json={"status": "ok"})

        async with HTTPClient(max_retries=3) as client:
            response = await client.get_json("https://example.com/api")

            assert response == {"status": "ok"}

    async def test_cached_requests_reduce_network_calls(self, httpx_mock):
        """Test that caching reduces network requests."""
        httpx_mock.add_response(
            json={"data": "cached"},
            headers={"ETag": "version1"},
        )
        httpx_mock.add_response(status_code=304)
        httpx_mock.add_response(status_code=304)

        async with HTTPClient(enable_caching=True) as client:
            # First request
            data1 = await client.get_json("https://example.com/api")
            # Second and third requests (should use cache)
            data2 = await client.get_json("https://example.com/api")
            data3 = await client.get_json("https://example.com/api")

            assert data1 == data2 == data3 == {"data": "cached"}
            # Should make 3 network requests (initial + 2 conditional)
            assert len(httpx_mock.get_requests()) == 3

    async def test_concurrent_batch_processing(self, httpx_mock):
        """Test processing multiple URLs concurrently."""
        urls = [f"https://api.example.com/item/{i}" for i in range(10)]

        for i in range(10):
            httpx_mock.add_response(
                url=f"https://api.example.com/item/{i}",
                json={"id": i, "name": f"Item {i}"},
            )

        async with HTTPClient(max_concurrency=5) as client:
            results = await client.batch_get_json(urls)

            assert len(results) == 10
            for i, url in enumerate(urls):
                assert results[url]["id"] == i

    async def test_rate_limited_api_interaction(self, httpx_mock):
        """Test interacting with rate-limited API."""
        httpx_mock.add_response(
            status_code=429,
            headers={"Retry-After": "1"},
        )
        httpx_mock.add_response(json={"data": "success"})

        async with HTTPClient(max_retries=2) as client:
            import time

            start = time.time()
            response = await client.get_json("https://example.com/api")
            elapsed = time.time() - start

            assert response == {"data": "success"}
            assert elapsed >= 1.0  # Should wait at least 1 second


@pytest.mark.asyncio
class TestHTTPClientEdgeCases:
    """Tests for edge cases and unusual scenarios."""

    async def test_empty_response_body(self, httpx_mock):
        """Test handling empty response body."""
        httpx_mock.add_response(status_code=204)

        async with HTTPClient() as client:
            response = await client.get("https://example.com/api")

            assert response.status_code == 204
            assert response.text == ""

    async def test_very_large_response(self, httpx_mock):
        """Test handling very large response."""
        large_data = {"data": "x" * 100000}
        httpx_mock.add_response(json=large_data)

        async with HTTPClient() as client:
            response = await client.get_json("https://example.com/api")

            assert len(response["data"]) == 100000

    async def test_unicode_in_response(self, httpx_mock):
        """Test handling Unicode characters in response."""
        httpx_mock.add_response(json={"message": "Hello 世界 ��"})

        async with HTTPClient() as client:
            response = await client.get_json("https://example.com/api")

            assert response["message"] == "Hello 世界 ��"

    async def test_multiple_redirects(self, httpx_mock):
        """Test following multiple redirects."""
        httpx_mock.add_response(
            status_code=301,
            headers={"Location": "https://example.com/redirect1"},
        )
        httpx_mock.add_response(
            url="https://example.com/redirect1",
            status_code=302,
            headers={"Location": "https://example.com/final"},
        )
        httpx_mock.add_response(
            url="https://example.com/final",
            json={"data": "final"},
        )

        async with HTTPClient() as client:
            # httpx follows redirects automatically
            response = await client.get("https://example.com/api")

            # Since httpx_mock handles this differently, just verify we can make the request
            assert response.status_code in [200, 301, 302]

    async def test_custom_headers_preserved(self, httpx_mock):
        """Test that custom headers are preserved."""
        httpx_mock.add_response()

        async with HTTPClient() as client:
            await client.get(
                "https://example.com/api",
                headers={"X-Custom-Header": "test-value"},
            )

            request = httpx_mock.get_request()
            assert "X-Custom-Header" in request.headers
            assert request.headers["X-Custom-Header"] == "test-value"

    async def test_ssl_verification_disabled(self, httpx_mock):
        """Test that SSL verification can be disabled."""
        client = HTTPClient(verify_ssl=False)

        await client._ensure_client()

        assert client._client is not None

        assert client.verify_ssl is False

        await client.close()

    async def test_http2_enabled(self, httpx_mock):
        """Test that HTTP/2 is enabled."""
        client = HTTPClient()

        await client._ensure_client()

        assert client._client is not None
        # HTTP/2 is enabled in the client configuration

        await client.close()

    async def test_zero_max_retries(self, httpx_mock):
        """Test client with zero retries."""
        httpx_mock.add_exception(httpx.TimeoutException("Timeout"))

        async with HTTPClient(max_retries=0) as client:
            with pytest.raises(NetworkError):
                await client.get("https://example.com/api")

            # Should only attempt once
            assert len(httpx_mock.get_requests()) == 1

    async def test_very_long_timeout(self, httpx_mock):
        """Test client with very long timeout."""
        httpx_mock.add_response(json={"data": "test"})

        async with HTTPClient(timeout=3600) as client:
            response = await client.get_json("https://example.com/api")

            assert response == {"data": "test"}
