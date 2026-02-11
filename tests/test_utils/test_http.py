from __future__ import annotations

import json
import httpx
import pytest
import asyncio
from typing import Any, Dict, Generator, List
from unittest.mock import AsyncMock, MagicMock, patch

from depkeeper.utils.http import HTTPClient
from depkeeper.exceptions import NetworkError, PyPIError


@pytest.fixture
def http_client() -> Generator[HTTPClient, None, None]:
    """Create an HTTPClient instance for testing.

    Yields:
        HTTPClient: A configured client instance with short timeouts for testing.

    Note:
        Ensures proper cleanup by closing the client after test completion.
    """
    client = HTTPClient(timeout=5, max_retries=2)
    yield client
    # Ensure client is closed to prevent resource leaks
    if client._client is not None:
        asyncio.get_event_loop().run_until_complete(client.close())


@pytest.mark.unit
class TestHTTPClientInit:
    """Tests for HTTPClient initialization and configuration."""

    def test_default_values(self) -> None:
        """Test HTTPClient initializes with correct default values.

        Verifies that all default parameters match expected constants
        and that the user agent includes the package name.
        """
        client = HTTPClient()

        assert client.timeout == 30  # DEFAULT_TIMEOUT
        assert client.max_retries == 3  # DEFAULT_MAX_RETRIES
        assert client.rate_limit_delay == 0.0
        assert client.verify_ssl is True
        assert client.max_concurrency == 10
        assert "depkeeper" in client.user_agent
        assert client._max_429_retries == 5

    def test_custom_values(self) -> None:
        """Test HTTPClient accepts and stores custom configuration values.

        Ensures all constructor parameters are properly stored and
        can be customized independently.
        """
        client = HTTPClient(
            timeout=10,
            max_retries=5,
            rate_limit_delay=0.5,
            verify_ssl=False,
            user_agent="CustomAgent/1.0",
            max_concurrency=20,
        )

        assert client.timeout == 10
        assert client.max_retries == 5
        assert client.rate_limit_delay == 0.5
        assert client.verify_ssl is False
        assert client.user_agent == "CustomAgent/1.0"
        assert client.max_concurrency == 20

    def test_initial_state(self) -> None:
        """Test HTTPClient starts in correct initial state.

        Verifies that internal state variables are properly initialized
        before any requests are made.
        """
        client = HTTPClient()

        assert client._client is None
        assert client._last_request_time == 0.0
        assert client._rate_limit_lock is not None
        assert client._semaphore is not None
        assert client._semaphore._value == 10  # Default max_concurrency

    def test_edge_case_zero_timeout(self) -> None:
        """Test HTTPClient handles zero timeout configuration.

        Edge case: Zero timeout should be accepted but may cause
        immediate timeouts in practice.
        """
        client = HTTPClient(timeout=0)
        assert client.timeout == 0

    def test_edge_case_zero_max_retries(self) -> None:
        """Test HTTPClient handles zero max_retries (no retries).

        Edge case: Zero retries means fail immediately on first error.
        """
        client = HTTPClient(max_retries=0)
        assert client.max_retries == 0

    def test_edge_case_negative_rate_limit(self) -> None:
        """Test HTTPClient handles negative rate limit delay.

        Edge case: Negative delays should be treated as no delay.
        """
        client = HTTPClient(rate_limit_delay=-1.0)
        assert client.rate_limit_delay == -1.0


@pytest.mark.unit
class TestHTTPClientContextManager:
    """Tests for HTTPClient async context manager protocol."""

    @pytest.mark.asyncio
    async def test_context_manager_creates_client(self) -> None:
        """Test async context manager initializes httpx client on entry.

        Verifies that the underlying httpx.AsyncClient is created
        when entering the async context.
        """
        async with HTTPClient() as client:
            assert client._client is not None
            assert isinstance(client._client, httpx.AsyncClient)

    @pytest.mark.asyncio
    async def test_context_manager_closes_client(self) -> None:
        """Test async context manager properly closes client on exit.

        Ensures resources are cleaned up when exiting the context,
        preventing connection leaks.
        """
        client = HTTPClient()
        async with client:
            assert client._client is not None

        assert client._client is None

    @pytest.mark.asyncio
    async def test_context_manager_closes_on_exception(self) -> None:
        """Test client is closed even when exception occurs in context.

        Edge case: Resource cleanup should happen even during error conditions.
        """
        client = HTTPClient()

        try:
            async with client:
                assert client._client is not None
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Client should still be closed
        assert client._client is None

    @pytest.mark.asyncio
    async def test_multiple_context_manager_entries(self) -> None:
        """Test client can be used with context manager multiple times.

        Edge case: Should be able to reuse client with multiple
        async with blocks sequentially.
        """
        client = HTTPClient()

        async with client:
            first_client = client._client
            assert first_client is not None

        assert client._client is None

        async with client:
            second_client = client._client
            assert second_client is not None

        # Should create new client instance
        assert first_client is not second_client


@pytest.mark.unit
class TestHTTPClientEnsureClient:
    """Tests for HTTPClient._ensure_client internal method."""

    @pytest.mark.asyncio
    async def test_ensure_client_creates_once(self) -> None:
        """Test _ensure_client is idempotent (creates only once).

        Multiple calls should reuse the same httpx.AsyncClient instance.
        """
        client = HTTPClient()

        await client._ensure_client()
        first_client = client._client
        assert first_client is not None

        await client._ensure_client()
        second_client = client._client

        assert first_client is second_client
        await client.close()

    @pytest.mark.asyncio
    async def test_ensure_client_configures_correctly(self) -> None:
        """Test _ensure_client passes configuration to httpx.AsyncClient.

        Verifies that timeout, SSL verification, and other settings
        are properly configured in the underlying client.
        """
        client = HTTPClient(timeout=15, verify_ssl=False, user_agent="TestAgent")
        await client._ensure_client()

        assert client._client is not None
        assert client._client.timeout.read == 15
        assert client._client.headers["User-Agent"] == "TestAgent"
        await client.close()

    @pytest.mark.asyncio
    async def test_ensure_client_enables_http2(self) -> None:
        """Test _ensure_client enables HTTP/2 support.

        HTTP/2 should be enabled for better performance with modern servers.
        """
        client = HTTPClient()
        await client._ensure_client()

        assert client._client is not None
        # HTTP/2 is enabled in the constructor
        await client.close()


@pytest.mark.unit
class TestHTTPClientClose:
    """Tests for HTTPClient.close cleanup method."""

    @pytest.mark.asyncio
    async def test_close_sets_client_to_none(self) -> None:
        """Test close nullifies the _client reference.

        After closing, _client should be None to prevent use-after-close.
        """
        client = HTTPClient()
        await client._ensure_client()
        assert client._client is not None

        await client.close()
        assert client._client is None

    @pytest.mark.asyncio
    async def test_close_when_no_client(self) -> None:
        """Test close is safe to call when no client exists.

        Edge case: Should be a no-op when client was never initialized.
        """
        client = HTTPClient()
        assert client._client is None

        # Should not raise
        await client.close()
        assert client._client is None

    @pytest.mark.asyncio
    async def test_close_multiple_times(self) -> None:
        """Test close can be called multiple times safely.

        Edge case: Multiple close calls should be idempotent.
        """
        client = HTTPClient()
        await client._ensure_client()

        await client.close()
        assert client._client is None

        # Second close should not raise
        await client.close()
        assert client._client is None


@pytest.mark.unit
class TestHTTPClientRateLimit:
    """Tests for HTTPClient._rate_limit rate limiting mechanism."""

    @pytest.mark.asyncio
    async def test_rate_limit_no_delay(self) -> None:
        """Test rate limit with zero delay is effectively disabled.

        When rate_limit_delay is 0, requests should proceed immediately.
        """
        client = HTTPClient(rate_limit_delay=0.0)

        import time

        start = time.time()
        await client._rate_limit()
        elapsed = time.time() - start

        # Should be nearly instant
        assert elapsed < 0.05

    @pytest.mark.asyncio
    async def test_rate_limit_enforces_delay(self) -> None:
        """Test rate limit enforces minimum delay between requests.

        Sequential calls should be separated by at least rate_limit_delay seconds.
        """
        client = HTTPClient(rate_limit_delay=0.1)

        import time

        # First call should be instant
        await client._rate_limit()

        # Second call should wait
        start = time.time()
        await client._rate_limit()
        elapsed = time.time() - start

        # Should have waited approximately 0.1 seconds
        assert elapsed >= 0.08  # Allow some tolerance for timing jitter

    @pytest.mark.asyncio
    async def test_rate_limit_concurrent_calls(self) -> None:
        """Test rate limit serializes concurrent calls properly.

        Multiple concurrent calls should be serialized by the lock
        and each should wait the full delay.
        """
        client = HTTPClient(rate_limit_delay=0.05)

        import time

        start = time.time()

        # Fire off 3 concurrent rate_limit calls
        await asyncio.gather(
            client._rate_limit(),
            client._rate_limit(),
            client._rate_limit(),
        )

        elapsed = time.time() - start

        # Should take at least 2 * delay (3 calls - 1st is immediate)
        assert elapsed >= 0.08

    @pytest.mark.asyncio
    async def test_rate_limit_updates_last_request_time(self) -> None:
        """Test rate limit correctly tracks last request time.

        _last_request_time should be updated after each rate limit check.
        """
        client = HTTPClient(rate_limit_delay=0.01)

        initial_time = client._last_request_time
        await client._rate_limit()
        after_first = client._last_request_time

        assert after_first > initial_time

    @pytest.mark.asyncio
    async def test_rate_limit_with_negative_delay(self) -> None:
        """Test rate limit handles negative delay gracefully.

        Edge case: Negative delays should be treated as zero (no delay).
        """
        client = HTTPClient(rate_limit_delay=-0.5)

        import time

        start = time.time()
        await client._rate_limit()
        await client._rate_limit()
        elapsed = time.time() - start

        # Should not delay
        assert elapsed < 0.05


@pytest.mark.unit
class TestHTTPClientRequestWithRetry:
    """Tests for HTTPClient._request_with_retry core retry logic."""

    @pytest.mark.asyncio
    async def test_successful_request(self) -> None:
        """Test successful request returns response without retries.

        Happy path: 200 OK should return immediately.
        """
        client = HTTPClient(max_retries=1)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200

        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            async with client:
                response = await client._request_with_retry(
                    "GET", "https://example.com"
                )

            assert response.status_code == 200
            assert mock_request.call_count == 1

    @pytest.mark.asyncio
    async def test_strips_quotes_from_url(self) -> None:
        """Test URL cleaning removes surrounding quotes.

        Edge case: URLs may arrive with surrounding quotes that need
        to be stripped before making the request.
        """
        client = HTTPClient(max_retries=0)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200

        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            async with client:
                await client._request_with_retry("GET", '"https://example.com"')
                await client._request_with_retry("GET", "'https://example.com'")

            # Both should be called with clean URL
            assert all(
                args[0][1] == "https://example.com"
                for args in mock_request.call_args_list
            )

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_url(self) -> None:
        """Test URL cleaning removes whitespace.

        Edge case: URLs with leading/trailing whitespace.
        """
        client = HTTPClient(max_retries=0)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200

        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            async with client:
                await client._request_with_retry("GET", "  https://example.com  ")

            call_url = mock_request.call_args[0][1]
            assert call_url == "https://example.com"

    @pytest.mark.asyncio
    async def test_404_raises_pypi_error(self) -> None:
        """Test 404 response raises PyPIError immediately without retry.

        404 errors are not transient - should fail fast without retries.
        """
        client = HTTPClient(max_retries=3)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 404

        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            async with client:
                with pytest.raises(PyPIError) as exc_info:
                    await client._request_with_retry("GET", "https://pypi.org/test")

            assert "not found" in str(exc_info.value).lower()
            assert exc_info.value.status_code == 404
            # Should not retry 404s
            assert mock_request.call_count == 1

    @pytest.mark.asyncio
    async def test_429_retries_with_backoff(self) -> None:
        """Test 429 (rate limit) response triggers retry with Retry-After.

        Rate limit responses should respect Retry-After header and retry.
        """
        client = HTTPClient(max_retries=1)
        client._max_429_retries = 2

        rate_limited_response = MagicMock(spec=httpx.Response)
        rate_limited_response.status_code = 429
        rate_limited_response.headers = {"Retry-After": "0"}

        success_response = MagicMock(spec=httpx.Response)
        success_response.status_code = 200

        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.side_effect = [rate_limited_response, success_response]

            async with client:
                response = await client._request_with_retry(
                    "GET", "https://example.com"
                )

            assert response.status_code == 200
            assert mock_request.call_count == 2

    @pytest.mark.asyncio
    async def test_429_default_retry_after(self) -> None:
        """Test 429 response uses default 1s delay when Retry-After missing.

        Edge case: Server may not provide Retry-After header.
        """
        client = HTTPClient(max_retries=1)
        client._max_429_retries = 2

        rate_limited_response = MagicMock(spec=httpx.Response)
        rate_limited_response.status_code = 429
        rate_limited_response.headers = {}  # No Retry-After

        success_response = MagicMock(spec=httpx.Response)
        success_response.status_code = 200

        import time

        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.side_effect = [rate_limited_response, success_response]

            async with client:
                start = time.time()
                await client._request_with_retry("GET", "https://example.com")
                elapsed = time.time() - start

            # Should wait at least 1 second (default)
            assert elapsed >= 0.9

    @pytest.mark.asyncio
    async def test_429_max_retries_exceeded(self) -> None:
        """Test 429 raises NetworkError after max 429 retries.

        Should give up after _max_429_retries attempts, even if
        max_retries would allow more.
        """
        client = HTTPClient(max_retries=10)
        client._max_429_retries = 1

        rate_limited_response = MagicMock(spec=httpx.Response)
        rate_limited_response.status_code = 429
        rate_limited_response.headers = {"Retry-After": "0"}

        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = rate_limited_response

            async with client:
                with pytest.raises(NetworkError) as exc_info:
                    await client._request_with_retry("GET", "https://example.com")

            assert "Rate limit exceeded" in str(exc_info.value)
            assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_timeout_retries(self) -> None:
        """Test timeout exception triggers retry with exponential backoff.

        Transient timeout errors should be retried.
        """
        client = HTTPClient(max_retries=1)

        success_response = MagicMock(spec=httpx.Response)
        success_response.status_code = 200

        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.side_effect = [
                httpx.TimeoutException("Timeout"),
                success_response,
            ]

            async with client:
                response = await client._request_with_retry(
                    "GET", "https://example.com"
                )

            assert response.status_code == 200
            assert mock_request.call_count == 2

    @pytest.mark.asyncio
    async def test_network_error_retries(self) -> None:
        """Test network error triggers retry.

        Connection failures and other network errors should be retried.
        """
        client = HTTPClient(max_retries=1)

        success_response = MagicMock(spec=httpx.Response)
        success_response.status_code = 200

        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.side_effect = [
                httpx.NetworkError("Connection failed"),
                success_response,
            ]

            async with client:
                response = await client._request_with_retry(
                    "GET", "https://example.com"
                )

            assert response.status_code == 200
            assert mock_request.call_count == 2

    @pytest.mark.asyncio
    async def test_4xx_error_raises_network_error(self) -> None:
        """Test 4xx client errors (except 404, 429) raise NetworkError.

        Client errors are not retried as they indicate bad requests.
        """
        client = HTTPClient(max_retries=3)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Forbidden",
            request=MagicMock(),
            response=mock_response,
        )

        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            async with client:
                with pytest.raises(NetworkError) as exc_info:
                    await client._request_with_retry("GET", "https://example.com")

            assert "403" in str(exc_info.value)
            assert exc_info.value.status_code == 403
            # Should not retry 4xx
            assert mock_request.call_count == 1

    @pytest.mark.asyncio
    async def test_multiple_4xx_codes(self) -> None:
        """Test various 4xx status codes all raise NetworkError.

        Edge case: Test multiple client error codes.
        """
        client = HTTPClient(max_retries=0)

        for status_code in [400, 401, 403, 405, 422]:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = status_code
            mock_response.text = f"Error {status_code}"
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                f"Error {status_code}",
                request=MagicMock(),
                response=mock_response,
            )

            with patch.object(
                httpx.AsyncClient, "request", new_callable=AsyncMock
            ) as mock_request:
                mock_request.return_value = mock_response

                async with client:
                    with pytest.raises(NetworkError) as exc_info:
                        await client._request_with_retry("GET", "https://example.com")

                assert str(status_code) in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_5xx_error_retries(self) -> None:
        """Test 5xx server errors trigger retry.

        Server errors are transient and should be retried.
        """
        client = HTTPClient(max_retries=1)

        error_response = MagicMock(spec=httpx.Response)
        error_response.status_code = 503
        error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Service Unavailable",
            request=MagicMock(),
            response=error_response,
        )

        success_response = MagicMock(spec=httpx.Response)
        success_response.status_code = 200

        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.side_effect = [error_response, success_response]

            async with client:
                response = await client._request_with_retry(
                    "GET", "https://example.com"
                )

            assert response.status_code == 200
            assert mock_request.call_count == 2

    @pytest.mark.asyncio
    async def test_multiple_5xx_codes(self) -> None:
        """Test various 5xx status codes all trigger retry.

        Edge case: Different server error codes.
        """
        for status_code in [500, 502, 503, 504]:
            client = HTTPClient(max_retries=1)

            error_response = MagicMock(spec=httpx.Response)
            error_response.status_code = status_code
            error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                f"Server Error {status_code}",
                request=MagicMock(),
                response=error_response,
            )

            success_response = MagicMock(spec=httpx.Response)
            success_response.status_code = 200

            with patch.object(
                httpx.AsyncClient, "request", new_callable=AsyncMock
            ) as mock_request:
                mock_request.side_effect = [error_response, success_response]

                async with client:
                    response = await client._request_with_retry(
                        "GET", "https://example.com"
                    )

                assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_raises_error(self) -> None:
        """Test NetworkError is raised after exhausting all retries.

        After max_retries attempts, should give up and raise.
        """
        client = HTTPClient(max_retries=2)

        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.side_effect = httpx.TimeoutException("Timeout")

            async with client:
                with pytest.raises(NetworkError) as exc_info:
                    await client._request_with_retry("GET", "https://example.com")

            assert "failed after" in str(exc_info.value).lower()
            # Should try max_retries + 1 times (initial + retries)
            assert mock_request.call_count == 3

    @pytest.mark.asyncio
    async def test_exponential_backoff_timing(self) -> None:
        """Test retry delays follow exponential backoff pattern.

        Delays should increase: 2^0, 2^1, 2^2, etc. (plus random jitter).
        """
        client = HTTPClient(max_retries=3)

        import time

        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.side_effect = httpx.TimeoutException("Timeout")

            async with client:
                start = time.time()
                try:
                    await client._request_with_retry("GET", "https://example.com")
                except NetworkError:
                    pass
                elapsed = time.time() - start

            # Total wait should be at least: 2^0 + 2^1 + 2^2 = 7 seconds
            # (minus jitter which is at most 0.3 per retry)
            assert elapsed >= 6.0

    @pytest.mark.asyncio
    async def test_success_status_codes(self) -> None:
        """Test various 2xx success codes are handled correctly.

        Edge case: Different success codes should all return without error.
        """
        client = HTTPClient(max_retries=0)

        for status_code in [200, 201, 202, 204]:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = status_code

            with patch.object(
                httpx.AsyncClient, "request", new_callable=AsyncMock
            ) as mock_request:
                mock_request.return_value = mock_response

                async with client:
                    response = await client._request_with_retry(
                        "GET", "https://example.com"
                    )

                assert response.status_code == status_code

    @pytest.mark.asyncio
    async def test_redirect_status_codes(self) -> None:
        """Test 3xx redirect codes are handled by httpx.

        Edge case: Redirects should be followed automatically by httpx.
        """
        client = HTTPClient(max_retries=0)

        # httpx with follow_redirects=True handles this automatically
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200  # After redirect

        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            async with client:
                response = await client._request_with_retry(
                    "GET", "https://example.com"
                )

            assert response.status_code == 200


@pytest.mark.unit
class TestHTTPClientGet:
    """Tests for HTTPClient.get convenience method."""

    @pytest.mark.asyncio
    async def test_get_request(self) -> None:
        """Test GET request delegates to _request_with_retry.

        GET method should pass through to the retry logic.
        """
        client = HTTPClient(max_retries=0)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200

        with patch.object(
            HTTPClient, "_request_with_retry", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            async with client:
                response = await client.get("https://example.com")

            assert response.status_code == 200
            mock_request.assert_called_once_with("GET", "https://example.com")

    @pytest.mark.asyncio
    async def test_get_with_params(self) -> None:
        """Test GET request passes through kwargs.

        Additional parameters should be forwarded to the underlying request.
        """
        client = HTTPClient(max_retries=0)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200

        with patch.object(
            HTTPClient, "_request_with_retry", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            async with client:
                await client.get(
                    "https://example.com",
                    params={"key": "value"},
                    headers={"X-Custom": "header"},
                )

            call_kwargs = mock_request.call_args[1]
            assert "params" in call_kwargs
            assert "headers" in call_kwargs


@pytest.mark.unit
class TestHTTPClientPost:
    """Tests for HTTPClient.post convenience method."""

    @pytest.mark.asyncio
    async def test_post_request(self) -> None:
        """Test POST request delegates to _request_with_retry.

        POST method should pass through to the retry logic.
        """
        client = HTTPClient(max_retries=0)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201

        with patch.object(
            HTTPClient, "_request_with_retry", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            async with client:
                response = await client.post(
                    "https://example.com",
                    json={"key": "value"},
                )

            assert response.status_code == 201
            mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_post_with_data(self) -> None:
        """Test POST request with different data types.

        Edge case: POST can send JSON, form data, or raw bytes.
        """
        client = HTTPClient(max_retries=0)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201

        with patch.object(
            HTTPClient, "_request_with_retry", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            async with client:
                # Test JSON
                await client.post("https://example.com", json={"key": "value"})

                # Test form data
                await client.post("https://example.com", data={"key": "value"})

                # Test raw content
                await client.post("https://example.com", content=b"raw bytes")

            assert mock_request.call_count == 3


@pytest.mark.unit
class TestHTTPClientGetJson:
    """Tests for HTTPClient.get_json JSON parsing method."""

    @pytest.mark.asyncio
    async def test_get_json_success(self) -> None:
        """Test successful JSON fetch and parse.

        Happy path: Valid JSON response should be parsed into dict.
        """
        client = HTTPClient(max_retries=0)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = {"name": "package", "version": "1.0.0"}

        with patch.object(HTTPClient, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            async with client:
                data = await client.get_json("https://example.com/api")

            assert data == {"name": "package", "version": "1.0.0"}

    @pytest.mark.asyncio
    async def test_get_json_invalid_json(self) -> None:
        """Test error when response contains invalid JSON.

        Malformed JSON should raise NetworkError with details.
        """
        client = HTTPClient(max_retries=0)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.side_effect = json.JSONDecodeError("Error", "doc", 0)
        mock_response.text = "Invalid JSON"

        with patch.object(HTTPClient, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            async with client:
                with pytest.raises(NetworkError) as exc_info:
                    await client.get_json("https://example.com/api")

            assert "Invalid JSON" in str(exc_info.value)
            assert exc_info.value.response_body == "Invalid JSON"

    @pytest.mark.asyncio
    async def test_get_json_non_object_response(self) -> None:
        """Test error when JSON is not an object/dict.

        Arrays and primitives should raise NetworkError as we expect objects.
        """
        client = HTTPClient(max_retries=0)

        for invalid_data in [["list"], "string", 123, None]:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.json.return_value = invalid_data
            mock_response.text = json.dumps(invalid_data)

            with patch.object(HTTPClient, "get", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = mock_response

                async with client:
                    with pytest.raises(NetworkError) as exc_info:
                        await client.get_json("https://example.com/api")

                assert "Expected JSON object" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_json_empty_object(self) -> None:
        """Test successful parse of empty JSON object.

        Edge case: Empty dict {} is valid.
        """
        client = HTTPClient(max_retries=0)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = {}

        with patch.object(HTTPClient, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            async with client:
                data = await client.get_json("https://example.com/api")

            assert data == {}

    @pytest.mark.asyncio
    async def test_get_json_nested_structure(self) -> None:
        """Test parsing complex nested JSON structures.

        Edge case: Deeply nested objects should parse correctly.
        """
        client = HTTPClient(max_retries=0)

        complex_data = {
            "info": {"name": "test", "meta": {"version": "1.0"}},
            "releases": {"1.0": [{"url": "https://..."}]},
        }

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.json.return_value = complex_data

        with patch.object(HTTPClient, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            async with client:
                data = await client.get_json("https://example.com/api")

            assert data == complex_data
            assert data["info"]["meta"]["version"] == "1.0"


@pytest.mark.unit
class TestHTTPClientBatchGetJson:
    """Tests for HTTPClient.batch_get_json concurrent fetch method."""

    @pytest.mark.asyncio
    async def test_batch_get_json_success(self) -> None:
        """Test successful concurrent fetch of multiple JSON endpoints.

        Happy path: All requests succeed and return their data.
        """
        client = HTTPClient(max_retries=0)

        urls = [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3",
        ]

        async def mock_get_json(url: str, **kwargs: Any) -> Dict[str, Any]:
            return {"url": url, "data": f"response from {url}"}

        with patch.object(HTTPClient, "get_json", side_effect=mock_get_json):
            async with client:
                results = await client.batch_get_json(urls)

            assert len(results) == 3
            assert results["https://example.com/1"]["url"] == "https://example.com/1"
            assert results["https://example.com/2"]["url"] == "https://example.com/2"
            assert results["https://example.com/3"]["url"] == "https://example.com/3"

    @pytest.mark.asyncio
    async def test_batch_get_json_with_failures(self) -> None:
        """Test batch fetch handles individual failures gracefully.

        Failed requests should return empty dict, successful ones return data.
        """
        client = HTTPClient(max_retries=0)

        urls = [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3",
        ]

        call_count = [0]

        async def mock_get_json(url: str, **kwargs: Any) -> Dict[str, Any]:
            call_count[0] += 1
            if "1" in url:
                raise NetworkError("Failed", url=url)
            if "3" in url:
                raise PyPIError("Not found", url=url, status_code=404)
            return {"url": url}

        with patch.object(HTTPClient, "get_json", side_effect=mock_get_json):
            async with client:
                results = await client.batch_get_json(urls)

            # All URLs attempted
            assert call_count[0] == 3

            # Failed requests return empty dict
            assert results["https://example.com/1"] == {}
            assert results["https://example.com/2"]["url"] == "https://example.com/2"
            assert results["https://example.com/3"] == {}

    @pytest.mark.asyncio
    async def test_batch_get_json_with_progress_callback(self) -> None:
        """Test batch fetch invokes progress callback correctly.

        Callback should be called after each completion with current progress.
        """
        client = HTTPClient(max_retries=0)

        urls = [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3",
        ]
        progress_calls: List[tuple] = []

        def progress_callback(completed: int, total: int) -> None:
            progress_calls.append((completed, total))

        async def mock_get_json(url: str, **kwargs: Any) -> Dict[str, Any]:
            return {"url": url}

        with patch.object(HTTPClient, "get_json", side_effect=mock_get_json):
            async with client:
                await client.batch_get_json(urls, progress_callback=progress_callback)

            # Should be called once per URL
            assert len(progress_calls) == 3

            # Total should always be 3
            assert all(total == 3 for _, total in progress_calls)

            # Completed should go from 1 to 3
            assert [completed for completed, _ in progress_calls] == [1, 2, 3]

            # Final call should be (3, 3)
            assert progress_calls[-1] == (3, 3)

    @pytest.mark.asyncio
    async def test_batch_get_json_progress_callback_with_failures(self) -> None:
        """Test progress callback is called even when requests fail.

        Edge case: Failures should still increment progress counter.
        """
        client = HTTPClient(max_retries=0)

        urls = ["https://example.com/1", "https://example.com/2"]
        progress_calls: List[tuple] = []

        def progress_callback(completed: int, total: int) -> None:
            progress_calls.append((completed, total))

        async def mock_get_json(url: str, **kwargs: Any) -> Dict[str, Any]:
            if "1" in url:
                raise NetworkError("Failed", url=url)
            return {"url": url}

        with patch.object(HTTPClient, "get_json", side_effect=mock_get_json):
            async with client:
                await client.batch_get_json(urls, progress_callback=progress_callback)

            assert len(progress_calls) == 2
            assert progress_calls == [(1, 2), (2, 2)]

    @pytest.mark.asyncio
    async def test_batch_get_json_empty_urls(self) -> None:
        """Test batch fetch with empty URL list.

        Edge case: Empty input should return empty results.
        """
        client = HTTPClient()

        async with client:
            results = await client.batch_get_json([])

        assert results == {}

    @pytest.mark.asyncio
    async def test_batch_get_json_single_url(self) -> None:
        """Test batch fetch with single URL.

        Edge case: Should work with just one URL.
        """
        client = HTTPClient(max_retries=0)

        urls = ["https://example.com/1"]

        async def mock_get_json(url: str, **kwargs: Any) -> Dict[str, Any]:
            return {"url": url}

        with patch.object(HTTPClient, "get_json", side_effect=mock_get_json):
            async with client:
                results = await client.batch_get_json(urls)

            assert len(results) == 1
            assert results["https://example.com/1"]["url"] == "https://example.com/1"

    @pytest.mark.asyncio
    async def test_batch_get_json_preserves_url_order(self) -> None:
        """Test batch fetch returns results keyed by original URLs.

        Results dict should contain all original URLs as keys.
        """
        client = HTTPClient(max_retries=0)

        urls = ["https://a.com", "https://b.com", "https://c.com"]

        async def mock_get_json(url: str, **kwargs: Any) -> Dict[str, Any]:
            return {"url": url}

        with patch.object(HTTPClient, "get_json", side_effect=mock_get_json):
            async with client:
                results = await client.batch_get_json(urls)

            # All original URLs should be keys
            assert set(results.keys()) == set(urls)

    @pytest.mark.asyncio
    async def test_batch_get_json_large_batch(self) -> None:
        """Test batch fetch handles large number of URLs.

        Edge case: Should handle many concurrent requests (limited by semaphore).
        """
        client = HTTPClient(max_retries=0, max_concurrency=5)

        # Create 50 URLs
        urls = [f"https://example.com/{i}" for i in range(50)]

        async def mock_get_json(url: str, **kwargs: Any) -> Dict[str, Any]:
            await asyncio.sleep(0.001)  # Tiny delay
            return {"url": url}

        with patch.object(HTTPClient, "get_json", side_effect=mock_get_json):
            async with client:
                results = await client.batch_get_json(urls)

            assert len(results) == 50


@pytest.mark.unit
class TestHTTPClientConcurrency:
    """Tests for HTTPClient concurrency control and semaphore."""

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self) -> None:
        """Test semaphore limits number of concurrent requests.

        With max_concurrency=2, should never have more than 2 concurrent requests.
        """
        client = HTTPClient(max_concurrency=2, max_retries=0)

        concurrent_count = [0]
        max_concurrent = [0]

        async def mock_request(method: str, url: str, **kwargs: Any) -> MagicMock:
            concurrent_count[0] += 1
            max_concurrent[0] = max(max_concurrent[0], concurrent_count[0])
            await asyncio.sleep(0.01)  # Simulate network delay
            concurrent_count[0] -= 1

            response = MagicMock(spec=httpx.Response)
            response.status_code = 200
            return response

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            async with client:
                # Run 5 requests with max_concurrency=2
                tasks = [
                    client._request_with_retry("GET", f"https://example.com/{i}")
                    for i in range(5)
                ]
                await asyncio.gather(*tasks)

        # Max concurrent should not exceed semaphore limit
        assert max_concurrent[0] <= 2

    @pytest.mark.asyncio
    async def test_different_concurrency_limits(self) -> None:
        """Test different max_concurrency values work correctly.

        Edge case: Test with concurrency of 1, 5, and 10.
        """
        for max_conc in [1, 5, 10]:
            client = HTTPClient(max_concurrency=max_conc, max_retries=0)

            concurrent_count = [0]
            max_concurrent = [0]

            async def mock_request(method: str, url: str, **kwargs: Any) -> MagicMock:
                concurrent_count[0] += 1
                max_concurrent[0] = max(max_concurrent[0], concurrent_count[0])
                await asyncio.sleep(0.005)
                concurrent_count[0] -= 1

                response = MagicMock(spec=httpx.Response)
                response.status_code = 200
                return response

            with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
                async with client:
                    tasks = [
                        client._request_with_retry("GET", f"https://example.com/{i}")
                        for i in range(15)
                    ]
                    await asyncio.gather(*tasks)

            assert max_concurrent[0] <= max_conc

    @pytest.mark.asyncio
    async def test_semaphore_releases_on_error(self) -> None:
        """Test semaphore is released even when request fails.

        Edge case: Errors should not cause semaphore leaks.
        """
        client = HTTPClient(max_concurrency=2, max_retries=0)

        concurrent_count = [0]

        async def mock_request(method: str, url: str, **kwargs: Any) -> MagicMock:
            concurrent_count[0] += 1
            await asyncio.sleep(0.01)
            concurrent_count[0] -= 1
            raise httpx.TimeoutException("Timeout")

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            async with client:
                tasks = [
                    client._request_with_retry("GET", f"https://example.com/{i}")
                    for i in range(5)
                ]
                # All should fail but not block
                results = await asyncio.gather(*tasks, return_exceptions=True)

        # All should have failed
        assert all(isinstance(r, NetworkError) for r in results)

        # Concurrent count should be back to 0
        assert concurrent_count[0] == 0


@pytest.mark.integration
@pytest.mark.network
class TestHTTPClientIntegration:
    """Integration tests combining multiple features."""

    @pytest.mark.asyncio
    async def test_rate_limit_and_retry_together(self) -> None:
        """Test rate limiting works correctly with retry logic.

        Integration test: Retries should still respect rate limits.
        """
        client = HTTPClient(rate_limit_delay=0.05, max_retries=2)

        import time

        success_response = MagicMock(spec=httpx.Response)
        success_response.status_code = 200

        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock
        ) as mock_request:
            # First call fails, second succeeds
            mock_request.side_effect = [
                httpx.TimeoutException("Timeout"),
                success_response,
            ]

            async with client:
                start = time.time()
                await client._request_with_retry("GET", "https://example.com")
                elapsed = time.time() - start

            # Should have waited for rate limit + backoff
            assert elapsed >= 0.04

    @pytest.mark.asyncio
    async def test_concurrent_requests_with_rate_limit(self) -> None:
        """Test concurrent requests all respect rate limit.

        Integration test: Rate limit should serialize requests even
        when fired concurrently.
        """
        client = HTTPClient(rate_limit_delay=0.05, max_concurrency=10, max_retries=0)

        import time

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200

        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            async with client:
                start = time.time()

                tasks = [
                    client._request_with_retry("GET", f"https://example.com/{i}")
                    for i in range(3)
                ]
                await asyncio.gather(*tasks)

                elapsed = time.time() - start

            # Should take at least 2 * rate_limit_delay (3 requests - first is immediate)
            assert elapsed >= 0.08

    @pytest.mark.asyncio
    async def test_batch_with_mixed_success_and_failure(self) -> None:
        """Test batch fetch with mix of successes and failures.

        Integration test: Complex scenario with various outcomes.
        Note: batch_get_json catches exceptions at the individual request level,
        so retry logic needs to be simulated within the mock itself.
        """
        client = HTTPClient(max_retries=1, max_concurrency=3)

        async def mock_get_json(url: str, **kwargs: Any) -> Dict[str, Any]:
            if "success" in url:
                return {"url": url, "status": "ok"}
            elif "partial" in url:
                # Simulate partial data return
                return {"url": url, "status": "ok", "incomplete": True}
            else:  # "fail" in url
                # This will be caught by batch_get_json and return empty dict
                raise NetworkError("Permanent failure", url=url)

        urls = [
            "https://example.com/success",
            "https://example.com/partial",
            "https://example.com/fail",
        ]

        with patch.object(HTTPClient, "get_json", side_effect=mock_get_json):
            async with client:
                results = await client.batch_get_json(urls)

        # Success case
        assert results["https://example.com/success"]["status"] == "ok"

        # Partial data case
        assert results["https://example.com/partial"]["status"] == "ok"
        assert results["https://example.com/partial"]["incomplete"] is True

        # Failure case - should return empty dict
        assert results["https://example.com/fail"] == {}

    @pytest.mark.asyncio
    async def test_retry_logic_with_actual_request(self) -> None:
        """Test retry logic integration with real request flow.

        Integration test: Verifies retry happens at the request level
        and succeeds after transient failure.
        """
        client = HTTPClient(max_retries=2, max_concurrency=3)

        call_count = [0]

        async def mock_request(method: str, url: str, **kwargs: Any) -> MagicMock:
            call_count[0] += 1

            if "retry" in url and call_count[0] < 2:
                # First attempt fails
                raise httpx.TimeoutException("Timeout")

            # Second attempt succeeds
            response = MagicMock(spec=httpx.Response)
            response.status_code = 200
            response.json.return_value = {"url": url, "status": "ok after retry"}
            return response

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            async with client:
                data = await client.get_json("https://example.com/retry")

        # Should succeed after retry
        assert data["status"] == "ok after retry"
        # Should have been called twice (initial + 1 retry)
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_client_reuse_across_multiple_operations(self) -> None:
        """Test client can be reused for multiple operations.

        Integration test: Client should maintain state correctly across calls.
        """
        client = HTTPClient(rate_limit_delay=0.01, max_retries=1)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "test"}

        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            async with client:
                # Multiple different operations
                await client.get("https://example.com/1")
                await client.post("https://example.com/2", json={"key": "value"})
                data = await client.get_json("https://example.com/3")

                results = await client.batch_get_json(
                    [
                        "https://example.com/4",
                        "https://example.com/5",
                    ]
                )

        # All operations should have succeeded
        assert data == {"data": "test"}
        assert len(results) == 2

        # Total of 5 requests made
        assert mock_request.call_count == 5
