from __future__ import annotations

import time
import httpx
import random
import asyncio
from typing import Any, Optional, Dict, Tuple, List

from depkeeper.utils.logger import get_logger
from depkeeper.__version__ import __version__
from depkeeper.exceptions import NetworkError, PyPIError
from depkeeper.constants import (
    DEFAULT_TIMEOUT,
    DEFAULT_MAX_RETRIES,
    USER_AGENT_TEMPLATE,
)

logger = get_logger("http")


# ============================================================================
# HTTP Client
# ============================================================================


class HTTPClient:
    """
    High-performance async HTTP client with:
      - retries
      - caching
      - concurrency control
      - rate limiting
      - HTTP/2 support
    """

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        rate_limit_delay: float = 0.0,
        verify_ssl: bool = True,
        user_agent: Optional[str] = None,
        max_concurrency: int = 10,
        enable_caching: bool = False,
    ) -> None:

        self.timeout = timeout
        self.max_retries = max_retries
        self.rate_limit_delay = rate_limit_delay
        self.verify_ssl = verify_ssl
        self.user_agent = user_agent or USER_AGENT_TEMPLATE.format(version=__version__)
        self.max_concurrency = max_concurrency
        self.enable_caching = enable_caching

        self._client: Optional[httpx.AsyncClient] = None
        self._last_request_time = 0.0
        self._semaphore = asyncio.Semaphore(max_concurrency)

        # Caching: url → (etag, cached_response)
        self._etag_cache: Dict[str, Tuple[str, httpx.Response]] = {}

    # ----------------------------------------------------------------------
    # Context Manager
    # ----------------------------------------------------------------------

    async def __aenter__(self) -> "HTTPClient":
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore
        await self.close()

    # ----------------------------------------------------------------------
    # Client Management
    # ----------------------------------------------------------------------

    async def _ensure_client(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                http2=True,
                verify=self.verify_ssl,
                follow_redirects=True,
                headers={"User-Agent": self.user_agent},
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ----------------------------------------------------------------------
    # Rate Limiting
    # ----------------------------------------------------------------------

    async def _rate_limit(self) -> None:
        """Guarantee a min delay between requests."""
        if self.rate_limit_delay < 0:
            return

        now = time.time()
        elapsed = now - self._last_request_time

        if elapsed < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - elapsed)

        self._last_request_time = time.time()

    # ----------------------------------------------------------------------
    # Internal Request Logic with Retry
    # ----------------------------------------------------------------------

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        await self._ensure_client()
        assert self._client is not None

        # Strip surrounding quotes
        if url.startswith(("'", '"')) and url.endswith(("'", '"')):
            url = url[1:-1].strip()

        last_exc: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            try:
                await self._rate_limit()

                async with self._semaphore:
                    response = await self._client.request(method, url, **kwargs)

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "1"))
                    logger.warning(f"429 received; retrying after {retry_after}s")
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
                logger.warning(f"Timeout (attempt {attempt+1}/{self.max_retries+1})")

            except httpx.NetworkError as exc:
                last_exc = exc
                logger.warning(f"Network error (attempt {attempt+1}): {exc}")

            except httpx.HTTPStatusError as exc:
                # Do not retry client errors < 500 except 429
                if 400 <= exc.response.status_code < 500:
                    raise NetworkError(
                        f"HTTP error {exc.response.status_code} for {url}",
                        status_code=exc.response.status_code,
                        url=url,
                        response_body=exc.response.text,
                    ) from exc
                last_exc = exc

            # Exponential backoff with jitter
            if attempt < self.max_retries:
                delay = (2**attempt) + random.uniform(0, 0.3)
                await asyncio.sleep(delay)

        raise NetworkError(
            f"Request failed after {self.max_retries + 1} attempts: {url}",
            url=url,
        ) from last_exc

    # ----------------------------------------------------------------------
    # GET with caching
    # ----------------------------------------------------------------------

    async def get(
        self,
        url: str,
        *,
        use_cache: Optional[bool] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        # Default to client's caching setting
        if use_cache is None:
            use_cache = self.enable_caching

        # ETag check
        if use_cache and url in self._etag_cache:
            etag, _cached = self._etag_cache[url]
            hdrs = kwargs.setdefault("headers", {})
            hdrs["If-None-Match"] = etag

        response = await self._request_with_retry("GET", url, **kwargs)

        # 304 → use cached response
        if response.status_code == 304 and url in self._etag_cache:
            _, cached_resp = self._etag_cache[url]
            logger.debug(f"Using cached response for {url}")
            return cached_resp

        # Update cache
        if use_cache:
            etag = response.headers.get("ETag")
            if etag:
                # Store a clone to prevent mutation issues
                self._etag_cache[url] = (etag, response)

        return response

    # ----------------------------------------------------------------------
    # POST
    # ----------------------------------------------------------------------

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._request_with_retry("POST", url, **kwargs)

    # ----------------------------------------------------------------------
    # JSON Convenience Methods
    # ----------------------------------------------------------------------

    async def get_json(
        self,
        url: str,
        *,
        use_cache: Optional[bool] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:

        resp = await self.get(url, use_cache=use_cache, **kwargs)

        try:
            return resp.json()
        except Exception as exc:
            raise NetworkError(
                f"Invalid JSON response from {url}",
                url=url,
            ) from exc

    async def batch_get_json(
        self,
        urls: List[str],
        *,
        use_cache: Optional[bool] = None,
        progress_callback: Optional[callable] = None,
    ) -> Dict[str, Dict[str, Any]]:

        results: Dict[str, Dict[str, Any]] = {}
        completed = 0
        total = len(urls)

        # Concurrent fetching
        tasks = [self.get_json(url, use_cache=use_cache) for url in urls]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        for url, resp in zip(urls, responses):
            if isinstance(resp, Exception):
                logger.error(f"Failed: {url} — {resp}")
                results[url] = {}
            else:
                results[url] = resp

            completed = completed + 1
            if progress_callback:
                progress_callback(completed, total)

        return results


# ============================================================================
# Standalone Error Handler
# ============================================================================


def handle_errors(response: httpx.Response) -> None:
    """
    Convert HTTP errors into depkeeper exceptions.
    """
    code = response.status_code
    if code < 400:
        return

    if code == 404:
        raise NetworkError(
            "Resource not found", status_code=code, url=str(response.url)
        )

    if code == 429:
        raise NetworkError(
            "Rate limit exceeded", status_code=code, url=str(response.url)
        )

    if code >= 500:
        raise NetworkError("Server error", status_code=code, url=str(response.url))

    raise NetworkError(f"HTTP error {code}", status_code=code, url=str(response.url))
