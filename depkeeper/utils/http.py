"""
HTTP client utilities for depkeeper.

This module provides an asynchronous HTTP client with retry logic,
rate limiting, concurrency control, and PyPI-specific error handling.
"""

from __future__ import annotations

import time
import httpx
import random
import asyncio
from typing import Any, Optional, Dict, Iterable, Callable, cast

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
    """Asynchronous HTTP client with retries, rate limiting, and concurrency control.

    Args:
        timeout: Request timeout in seconds.
        max_retries: Maximum number of retry attempts.
        rate_limit_delay: Minimum delay (seconds) between requests.
        verify_ssl: Whether to verify SSL certificates.
        user_agent: Custom User-Agent header value.
        max_concurrency: Maximum number of concurrent requests.

    Example:
        >>> async with HTTPClient() as client:
        ...     data = await client.get_json("https://pypi.org/pypi/requests/json")
    """

    def __init__(
        self,
        *,
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
        self._last_request_time: float = 0.0
        self._rate_limit_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._max_429_retries: int = 5

    async def __aenter__(self) -> "HTTPClient":
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    async def _ensure_client(self) -> None:
        """Initialize the underlying httpx client if needed."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                http2=True,
                verify=self.verify_ssl,
                follow_redirects=True,
                headers={"User-Agent": self.user_agent},
            )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _rate_limit(self) -> None:
        """Enforce a minimum delay between outgoing requests."""
        if self.rate_limit_delay <= 0:
            return

        async with self._rate_limit_lock:
            now = time.time()
            elapsed = now - self._last_request_time

            if elapsed < self.rate_limit_delay:
                delay = self.rate_limit_delay - elapsed
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
        """Execute an HTTP request with retry and backoff logic."""
        await self._ensure_client()
        assert self._client is not None

        clean_url = url.strip().strip("\"'")
        last_exc: Optional[Exception] = None
        retry_429_count = 0

        for attempt in range(self.max_retries + 1):
            try:
                await self._rate_limit()

                async with self._semaphore:
                    response = await self._client.request(method, clean_url, **kwargs)

                if response.status_code == 429:
                    retry_429_count += 1
                    if retry_429_count > self._max_429_retries:
                        raise NetworkError(
                            f"Rate limit exceeded after {self._max_429_retries} retries",
                            url=clean_url,
                            status_code=429,
                        )
                    retry_after = int(response.headers.get("Retry-After", "1"))
                    logger.warning(
                        "Rate limited (429), retrying after %ds (%d/%d)",
                        retry_after,
                        retry_429_count,
                        self._max_429_retries,
                    )
                    await asyncio.sleep(retry_after)
                    continue

                if response.status_code == 404:
                    raise PyPIError(
                        f"Resource not found: {clean_url}",
                        url=clean_url,
                        status_code=404,
                    )

                if response.status_code >= 400:
                    response.raise_for_status()

                return response

            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning(
                    "Request timeout (%d/%d): %s",
                    attempt + 1,
                    self.max_retries + 1,
                    clean_url,
                )

            except httpx.NetworkError as exc:
                last_exc = exc
                logger.warning(
                    "Network error (%d/%d): %s",
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                )

            except httpx.HTTPStatusError as exc:
                if 400 <= exc.response.status_code < 500:
                    raise NetworkError(
                        f"HTTP {exc.response.status_code} error for {clean_url}",
                        url=clean_url,
                        status_code=exc.response.status_code,
                        response_body=exc.response.text,
                    ) from exc
                last_exc = exc
                logger.warning(
                    "HTTP %d error (%d/%d): %s",
                    exc.response.status_code,
                    attempt + 1,
                    self.max_retries + 1,
                    clean_url,
                )

            if attempt < self.max_retries:
                delay = (2**attempt) + random.uniform(0.0, 0.3)
                logger.debug("Retrying in %.2fs", delay)
                await asyncio.sleep(delay)

        raise NetworkError(
            f"Request failed after {self.max_retries + 1} attempts: {clean_url}",
            url=clean_url,
        ) from last_exc

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Perform a GET request with retry logic."""
        return await self._request_with_retry("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Perform a POST request with retry logic."""
        return await self._request_with_retry("POST", url, **kwargs)

    async def get_json(self, url: str, **kwargs: Any) -> Dict[str, Any]:
        """Fetch a URL and parse the response as JSON."""
        response = await self.get(url, **kwargs)

        try:
            data = response.json()
        except Exception as exc:
            raise NetworkError(
                f"Invalid JSON response from {url}",
                url=url,
                response_body=response.text,
            ) from exc

        if not isinstance(data, dict):
            raise NetworkError(
                f"Expected JSON object from {url}",
                url=url,
                response_body=response.text,
            )

        return cast(Dict[str, Any], data)

    async def batch_get_json(
        self,
        urls: Iterable[str],
        *,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Fetch multiple JSON endpoints concurrently.

        Args:
            urls: Iterable of URLs to fetch.
            progress_callback: Optional callback invoked as (completed, total).

        Returns:
            Mapping of URL to parsed JSON data. Failed requests yield empty dicts.
        """
        url_list = list(urls)
        total = len(url_list)
        completed = 0
        results: Dict[str, Dict[str, Any]] = {}

        tasks = [self.get_json(url) for url in url_list]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        for url, result in zip(url_list, responses):
            if isinstance(result, BaseException):
                logger.error("Failed to fetch %s: %s", url, result)
                results[url] = {}
            else:
                results[url] = result

            completed += 1
            if progress_callback:
                progress_callback(completed, total)

        return results
