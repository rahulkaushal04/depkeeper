"""HTTP client utilities for depkeeper.

This module provides an async HTTP client optimized for making PyPI API calls
with robust error handling, automatic retries, rate limiting, and concurrency
control. Built on httpx with HTTP/2 support for improved performance.

The HTTPClient class implements enterprise-grade features including exponential
backoff, connection pooling, and comprehensive error handling to ensure reliable
communication with PyPI and other package indexes.

Examples
--------
Basic usage with context manager:

    >>> import asyncio
    >>> from depkeeper.utils.http import HTTPClient
    >>>
    >>> async def fetch_package():
    ...     async with HTTPClient() as client:
    ...         data = await client.get_json("https://pypi.org/pypi/requests/json")
    ...         return data['info']['version']
    >>>
    >>> version = asyncio.run(fetch_package())
    >>> print(version)

Batch fetching multiple packages:

    >>> async def fetch_multiple():
    ...     urls = [
    ...         "https://pypi.org/pypi/requests/json",
    ...         "https://pypi.org/pypi/click/json",
    ...         "https://pypi.org/pypi/flask/json"
    ...     ]
    ...     async with HTTPClient(max_concurrency=5) as client:
    ...         results = await client.batch_get_json(urls)
    ...         return results
    >>>
    >>> results = asyncio.run(fetch_multiple())

Custom configuration:

    >>> async def custom_client():
    ...     async with HTTPClient(
    ...         timeout=60,
    ...         max_retries=5,
    ...         rate_limit_delay=0.5,
    ...         max_concurrency=20
    ...     ) as client:
    ...         response = await client.get("https://pypi.org/pypi/requests/json")
    ...         return response.json()

Progress tracking for batch operations:

    >>> async def with_progress():
    ...     def progress_callback(completed, total):
    ...         print(f"Progress: {completed}/{total}")
    ...
    ...     async with HTTPClient() as client:
    ...         results = await client.batch_get_json(
    ...             urls,
    ...             progress_callback=progress_callback
    ...         )
    ...         return results

Notes
-----
The client automatically handles common HTTP errors and implements retry logic
with exponential backoff. Rate limiting (429) responses are handled with respect
to Retry-After headers.

All network operations are asynchronous using asyncio, allowing for efficient
concurrent requests while respecting concurrency limits.

See Also
--------
depkeeper.exceptions.NetworkError : Generic network error exception
depkeeper.exceptions.PyPIError : PyPI-specific error exception
httpx.AsyncClient : Underlying HTTP client library
"""

from __future__ import annotations

import time
import httpx
import random
import asyncio
from typing import Any, Optional, Dict, List, Callable

from depkeeper.utils.logger import get_logger
from depkeeper.__version__ import __version__
from depkeeper.exceptions import NetworkError, PyPIError
from depkeeper.constants import (
    DEFAULT_TIMEOUT,
    DEFAULT_MAX_RETRIES,
    USER_AGENT_TEMPLATE,
)

logger = get_logger("http")


class HTTPClient:
    """Async HTTP client for PyPI API calls with enterprise features.

    A lightweight, production-ready HTTP client built on httpx that provides
    automatic retry logic, rate limiting, concurrency control, and comprehensive
    error handling. Optimized for making API calls to PyPI and other package
    indexes.

    The client implements exponential backoff for retries, respects HTTP 429
    rate limiting with Retry-After headers, and uses HTTP/2 for improved
    performance when available.

    Parameters
    ----------
    timeout : int, optional
        Request timeout in seconds. Applies to both connection and read
        timeouts. Default is DEFAULT_TIMEOUT (typically 30 seconds).
    max_retries : int, optional
        Maximum number of retry attempts for failed requests. Does not include
        the initial request. Default is DEFAULT_MAX_RETRIES (typically 3).
    rate_limit_delay : float, optional
        Minimum delay between consecutive requests in seconds. Useful for
        respecting rate limits. If 0, no artificial delay is added.
        Default is 0.0 (no delay).
    verify_ssl : bool, optional
        Whether to verify SSL certificates. Should only be set to False for
        testing or when using self-signed certificates. Default is True.
    user_agent : str, optional
        Custom User-Agent header string. If None, uses default depkeeper
        User-Agent with version. Default is None.
    max_concurrency : int, optional
        Maximum number of concurrent requests allowed. Prevents overwhelming
        the server or exhausting system resources. Default is 10.

    Attributes
    ----------
    timeout : int
        Request timeout in seconds.
    max_retries : int
        Maximum retry attempts.
    rate_limit_delay : float
        Minimum delay between requests.
    verify_ssl : bool
        SSL verification setting.
    user_agent : str
        User-Agent header value.
    max_concurrency : int
        Concurrency limit.

    Examples
    --------
    Basic usage with defaults:

    >>> import asyncio
    >>> from depkeeper.utils.http import HTTPClient
    >>> async def main():
    ...     async with HTTPClient() as client:
    ...         data = await client.get_json("https://pypi.org/pypi/requests/json")
    ...         print(data['info']['name'])
    >>> asyncio.run(main())
    requests

    Custom configuration for production:

    >>> async with HTTPClient(
    ...     timeout=60,
    ...     max_retries=5,
    ...     rate_limit_delay=0.5,
    ...     max_concurrency=20
    ... ) as client:
    ...     response = await client.get("https://pypi.org/simple/requests/")

    Using without context manager:

    >>> client = HTTPClient()
    >>> await client._ensure_client()
    >>> try:
    ...     data = await client.get_json("https://pypi.org/pypi/click/json")
    ... finally:
    ...     await client.close()

    Notes
    -----
    The client should be used as an async context manager to ensure proper
    resource cleanup. When used with the context manager, the underlying
    httpx.AsyncClient is automatically closed on exit.

    Retry logic uses exponential backoff: 2^attempt seconds with random
    jitter up to 0.3 seconds to prevent thundering herd.

    Rate limiting (HTTP 429) is handled specially with up to 5 retries
    that respect the Retry-After header from the server.

    See Also
    --------
    get_json : Fetch and parse JSON from URL
    batch_get_json : Fetch multiple URLs concurrently
    """

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        rate_limit_delay: float = 0.0,
        verify_ssl: bool = True,
        user_agent: Optional[str] = None,
        max_concurrency: int = 10,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.rate_limit_delay = rate_limit_delay
        self.verify_ssl = verify_ssl
        self.user_agent = user_agent or USER_AGENT_TEMPLATE.format(version=__version__)
        self.max_concurrency = max_concurrency

        self._client: Optional[httpx.AsyncClient] = None
        self._last_request_time = 0.0
        self._rate_limit_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrency)

        # Track 429 retries separately to prevent infinite loops
        self._max_429_retries = 5

    async def __aenter__(self) -> "HTTPClient":
        """Enter async context manager.

        Initializes the underlying HTTP client and returns the HTTPClient
        instance for use in async with statements.

        Returns
        -------
        HTTPClient
            The initialized client instance.

        Examples
        --------
        >>> async with HTTPClient() as client:
        ...     data = await client.get_json("https://pypi.org/pypi/requests/json")
        """
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore
        """Exit async context manager.

        Automatically closes the HTTP client and cleans up resources when
        exiting the async with block.

        Parameters
        ----------
        exc_type : type, optional
            Exception type if an exception was raised.
        exc : Exception, optional
            Exception instance if an exception was raised.
        tb : traceback, optional
            Traceback if an exception was raised.

        Returns
        -------
        None
        """
        await self.close()

    async def _ensure_client(self) -> None:
        """Ensure HTTP client is initialized (lazy initialization).

        Creates the underlying httpx.AsyncClient if it doesn't exist yet.
        This allows delaying client creation until the first request,
        avoiding resource allocation if the client is never used.

        The client is configured with:
        - Specified timeout
        - HTTP/2 support enabled
        - SSL verification based on verify_ssl
        - Automatic redirect following
        - Custom User-Agent header

        Returns
        -------
        None

        Notes
        -----
        This is an internal method called automatically before requests.
        Users should not need to call this directly.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                http2=True,
                verify=self.verify_ssl,
                follow_redirects=True,
                headers={"User-Agent": self.user_agent},
            )

    async def close(self) -> None:
        """Close the HTTP client and release resources.

        Closes the underlying httpx.AsyncClient and frees all associated
        resources including connection pools. Should be called when the
        client is no longer needed, or use the context manager for
        automatic cleanup.

        Returns
        -------
        None

        Examples
        --------
        Manual cleanup:

        >>> client = HTTPClient()
        >>> await client._ensure_client()
        >>> # ... use client ...
        >>> await client.close()

        Automatic cleanup (recommended):

        >>> async with HTTPClient() as client:
        ...     # Client is automatically closed on exit
        ...     pass

        Notes
        -----
        After calling close(), the client can be reused. The next request
        will automatically reinitialize the underlying client.
        """
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _rate_limit(self) -> None:
        """Enforce minimum delay between consecutive requests.

        Implements thread-safe rate limiting by ensuring a minimum delay
        between requests. Uses an async lock to prevent race conditions
        in concurrent scenarios.

        Returns
        -------
        None

        Notes
        -----
        This is an internal method called automatically before each request.
        The delay is only enforced if rate_limit_delay > 0.

        The implementation tracks the last request time and sleeps for the
        remaining duration if needed. The sleep is performed with the lock
        released to avoid blocking other operations.
        """
        if self.rate_limit_delay <= 0:
            return

        async with self._rate_limit_lock:
            now = time.time()
            elapsed = now - self._last_request_time

            if elapsed < self.rate_limit_delay:
                delay = self.rate_limit_delay - elapsed
                # Set time before sleep to prevent race conditions
                self._last_request_time = now + delay
                await asyncio.sleep(delay)
            else:
                self._last_request_time = now

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Execute HTTP request with automatic retry logic.

        Internal method that handles request execution with comprehensive error
        handling and retry logic. Implements exponential backoff with jitter
        for transient failures and special handling for rate limiting (429).

        Parameters
        ----------
        method : str
            HTTP method to use (GET, POST, PUT, DELETE, etc.).
        url : str
            Target URL for the request.
        **kwargs : Any
            Additional keyword arguments passed to httpx.request(), such as
            headers, params, json, data, etc.

        Returns
        -------
        httpx.Response
            Successful HTTP response object.

        Raises
        ------
        NetworkError
            On network failures, timeouts, or HTTP errors (excluding 404).
            Includes status code and response body when available.
        PyPIError
            Specifically for 404 Not Found errors, indicating the requested
            resource doesn't exist on PyPI.

        Notes
        -----
        Retry behavior:
        - Network errors and timeouts: Retry up to max_retries times
        - 5xx server errors: Retry up to max_retries times
        - 429 rate limiting: Retry up to 5 times with Retry-After header
        - 4xx client errors (except 429): No retry, immediate failure
        - 404 Not Found: No retry, raises PyPIError

        Exponential backoff formula: 2^attempt + random(0, 0.3) seconds

        The separate 429 retry counter prevents infinite loops when
        encountering persistent rate limiting.

        Examples
        --------
        This is an internal method, but usage is illustrated by public methods:

        >>> response = await client._request_with_retry(
        ...     "GET", "https://pypi.org/pypi/requests/json"
        ... )
        >>> print(response.status_code)
        200
        """
        await self._ensure_client()
        assert self._client is not None

        last_exc: Optional[Exception] = None
        retry_429_count = 0  # Track 429 retries across all attempts

        for attempt in range(self.max_retries + 1):
            try:
                await self._rate_limit()

                async with self._semaphore:
                    response = await self._client.request(method, url, **kwargs)

                # Handle 429 with separate retry limit to prevent infinite loops
                if response.status_code == 429:
                    retry_429_count += 1
                    if retry_429_count > self._max_429_retries:
                        raise NetworkError(
                            f"Rate limit exceeded after "
                            f"{self._max_429_retries} retries",
                            status_code=429,
                            url=url,
                        )
                    retry_after = int(response.headers.get("Retry-After", "1"))
                    logger.warning(
                        "Rate limited (429) - attempt %d/%d, retrying after %ds",
                        retry_429_count,
                        self._max_429_retries,
                        retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue

                if response.status_code == 404:
                    raise PyPIError(
                        f"Resource not found: {url}",
                        status_code=404,
                        url=url,
                    )

                if response.status_code >= 400:
                    response.raise_for_status()

                return response

            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning(
                    "Request timeout (attempt %d/%d): %s",
                    attempt + 1,
                    self.max_retries + 1,
                    url,
                )

            except httpx.NetworkError as exc:
                last_exc = exc
                logger.warning(
                    "Network error (attempt %d/%d): %s",
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                )

            except httpx.HTTPStatusError as exc:
                # Do not retry client errors (4xx) except 429
                if 400 <= exc.response.status_code < 500:
                    raise NetworkError(
                        f"HTTP {exc.response.status_code} error for {url}",
                        status_code=exc.response.status_code,
                        url=url,
                        response_body=exc.response.text,
                    ) from exc
                last_exc = exc
                logger.warning(
                    "HTTP %d error (attempt %d/%d): %s",
                    exc.response.status_code,
                    attempt + 1,
                    self.max_retries + 1,
                    url,
                )

            # Exponential backoff with jitter
            if attempt < self.max_retries:
                delay = (2**attempt) + random.uniform(0, 0.3)
                logger.debug("Retrying in %.2fs...", delay)
                await asyncio.sleep(delay)

        raise NetworkError(
            f"Request failed after {self.max_retries + 1} attempts: {url}",
            url=url,
        ) from last_exc

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Execute GET request with automatic retry logic.

        Performs an HTTP GET request with automatic retries, rate limiting,
        and comprehensive error handling.

        Parameters
        ----------
        url : str
            Target URL to fetch.
        **kwargs : Any
            Additional arguments passed to httpx, such as:
            - headers: dict of HTTP headers
            - params: dict of query parameters
            - timeout: custom timeout (overrides client default)

        Returns
        -------
        httpx.Response
            Successful HTTP response object containing status code, headers,
            and body.

        Raises
        ------
        NetworkError
            On network failures, timeouts, or HTTP errors.
        PyPIError
            If the resource is not found (404).

        Examples
        --------
        Simple GET request:

        >>> async with HTTPClient() as client:
        ...     response = await client.get("https://pypi.org/pypi/requests/json")
        ...     print(response.status_code)
        200

        With custom headers:

        >>> response = await client.get(
        ...     "https://api.example.com/data",
        ...     headers={"Authorization": "Bearer token"}
        ... )

        With query parameters:

        >>> response = await client.get(
        ...     "https://api.example.com/search",
        ...     params={"q": "query", "limit": 10}
        ... )

        See Also
        --------
        get_json : Convenience method that automatically parses JSON
        post : Execute POST requests
        """
        return await self._request_with_retry("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Execute POST request with automatic retry logic.

        Performs an HTTP POST request with automatic retries, rate limiting,
        and comprehensive error handling.

        Parameters
        ----------
        url : str
            Target URL for the POST request.
        **kwargs : Any
            Additional arguments passed to httpx, such as:
            - headers: dict of HTTP headers
            - json: dict to send as JSON body
            - data: form data or bytes to send as body
            - files: files to upload

        Returns
        -------
        httpx.Response
            Successful HTTP response object.

        Raises
        ------
        NetworkError
            On network failures, timeouts, or HTTP errors.
        PyPIError
            If the resource is not found (404).

        Examples
        --------
        POST JSON data:

        >>> async with HTTPClient() as client:
        ...     response = await client.post(
        ...         "https://api.example.com/data",
        ...         json={"key": "value"}
        ...     )

        POST form data:

        >>> response = await client.post(
        ...     "https://api.example.com/form",
        ...     data={"field1": "value1", "field2": "value2"}
        ... )

        See Also
        --------
        get : Execute GET requests
        """
        return await self._request_with_retry("POST", url, **kwargs)

    async def get_json(self, url: str, **kwargs: Any) -> Dict[str, Any]:
        """Fetch and automatically parse JSON data from URL.

        Convenience method that performs a GET request and automatically
        parses the response body as JSON. Commonly used for PyPI API
        endpoints which return JSON data.

        Parameters
        ----------
        url : str
            Target URL that returns JSON data.
        **kwargs : Any
            Additional arguments passed to the GET request, such as
            headers or params.

        Returns
        -------
        dict[str, Any]
            Parsed JSON data as a dictionary. The structure depends on
            the API endpoint.

        Raises
        ------
        NetworkError
            If the request fails, times out, or the response body is not
            valid JSON. Includes the response text for debugging.
        PyPIError
            If the resource is not found (404).

        Examples
        --------
        Fetch package information from PyPI:

        >>> async with HTTPClient() as client:
        ...     data = await client.get_json("https://pypi.org/pypi/requests/json")
        ...     print(data['info']['version'])
        2.31.0

        With error handling:

        >>> try:
        ...     data = await client.get_json("https://pypi.org/pypi/nonexistent/json")
        ... except PyPIError:
        ...     print("Package not found")
        ... except NetworkError as e:
        ...     print(f"Network error: {e}")

        Notes
        -----
        This method assumes the response Content-Type is JSON or that the
        body can be parsed as JSON. If the endpoint returns non-JSON data,
        use the `get()` method instead and parse manually.

        See Also
        --------
        get : Lower-level GET method returning raw response
        batch_get_json : Fetch multiple JSON endpoints concurrently
        """
        response = await self.get(url, **kwargs)

        try:
            data: Dict[str, Any] = response.json()
            return data
        except Exception as exc:
            raise NetworkError(
                f"Invalid JSON response from {url}",
                url=url,
                response_body=response.text if hasattr(response, "text") else None,
            ) from exc
        response = await self.get(url, **kwargs)

        try:
            data: Dict[str, Any] = response.json()
            return data
        except Exception as exc:
            raise NetworkError(
                f"Invalid JSON response from {url}",
                url=url,
                response_body=response.text if hasattr(response, "text") else None,
            ) from exc

    async def batch_get_json(
        self,
        urls: List[str],
        *,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Fetch multiple JSON endpoints concurrently with progress tracking.

        Efficiently fetches multiple URLs in parallel while respecting the
        configured concurrency limit. Failed requests are logged but don't
        prevent other requests from completing. Ideal for checking multiple
        packages on PyPI simultaneously.

        Parameters
        ----------
        urls : list[str]
            List of URLs to fetch. Each should return JSON data.
        progress_callback : callable[[int, int], None], optional
            Optional callback function for progress tracking. Called after
            each completed request with (completed_count, total_count).
            Useful for updating progress bars or status displays.

        Returns
        -------
        dict[str, dict[str, Any]]
            Dictionary mapping each URL to its parsed JSON response.
            URLs that failed to fetch are mapped to empty dictionaries {}.
            Check logs for details on failures.

        Examples
        --------
        Fetch multiple package versions:

        >>> async with HTTPClient() as client:
        ...     urls = [
        ...         "https://pypi.org/pypi/requests/json",
        ...         "https://pypi.org/pypi/click/json",
        ...         "https://pypi.org/pypi/flask/json"
        ...     ]
        ...     results = await client.batch_get_json(urls)
        ...     for url, data in results.items():
        ...         if data:
        ...             print(data['info']['name'], data['info']['version'])

        With progress tracking:

        >>> def show_progress(completed, total):
        ...     print(f"Progress: {completed}/{total} ({completed/total*100:.0f}%)")
        ...
        >>> results = await client.batch_get_json(
        ...     urls,
        ...     progress_callback=show_progress
        ... )

        Handle failures gracefully:

        >>> results = await client.batch_get_json(urls)
        >>> successful = {url: data for url, data in results.items() if data}
        >>> failed = [url for url, data in results.items() if not data]
        >>> print(f"Succeeded: {len(successful)}, Failed: {len(failed)}")

        Notes
        -----
        The method uses asyncio.gather with return_exceptions=True to ensure
        all requests complete even if some fail. Failed requests return empty
        dictionaries and errors are logged at ERROR level.

        Concurrency is controlled by the client's semaphore (max_concurrency),
        preventing overwhelming the server or local system resources.

        Progress callbacks are called synchronously after each completion.
        Keep callback logic lightweight to avoid blocking the event loop.

        See Also
        --------
        get_json : Fetch single JSON endpoint
        asyncio.gather : Underlying concurrent execution mechanism
        """
        results: Dict[str, Dict[str, Any]] = {}
        completed = 0
        total = len(urls)

        # Fetch all URLs concurrently (semaphore limits concurrency)
        tasks = [self.get_json(url) for url in urls]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        for url, resp in zip(urls, responses):
            if isinstance(resp, Exception):
                logger.error("Failed to fetch %s: %s", url, resp)
                results[url] = {}
            else:
                results[url] = resp  # type: ignore[assignment]

            completed += 1
            if progress_callback:
                progress_callback(completed, total)

        return results
