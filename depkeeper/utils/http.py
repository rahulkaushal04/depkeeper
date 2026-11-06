"""HTTP client utilities for depkeeper.

Provides an asynchronous HTTP client with retry logic, rate limiting,
concurrency control, and PyPI-specific error handling. Every network call
depkeeper makes goes through `HTTPClient`, so retry and throttling
policy is defined in exactly one place.
"""

from __future__ import annotations

import time
import logging
import httpx
import random
import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional, Dict, Iterable, Callable, Tuple, cast
from urllib.parse import urljoin, urlsplit

from depkeeper.utils.logger import get_logger
from depkeeper.utils.redact import redact
from depkeeper.__version__ import __version__
from depkeeper.exceptions import NetworkError, PyPIError
from depkeeper.constants import (
    DEFAULT_TIMEOUT,
    DEFAULT_MAX_RETRIES,
    MAX_RETRY_AFTER_SECONDS,
    USER_AGENT_TEMPLATE,
)

logger = get_logger("http")


class _RedactFilter(logging.Filter):
    """Mask URL credentials in httpx/httpcore's own request log lines."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg, record.args = redact(record.getMessage()), None
        return True


for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).addFilter(_RedactFilter())

#: Largest response body accepted. PyPI JSON is 1-4 MB for typical large
#: projects (boto3, tensorflow) but 41 MB for ddtrace.
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
#: Wall-clock cap for one logical request including retries and backoff.
DEFAULT_TOTAL_TIMEOUT = 180.0
#: Maximum redirect hops followed for one request.
MAX_REDIRECTS = 5
#: Hosts a redirect may land on (besides the request's own host).
_REDIRECT_HOSTS = frozenset({"pypi.org", "files.pythonhosted.org"})

#: Consecutive connection-level failures (refused, DNS, proxy) that open the
#: circuit; while open, requests fail at once instead of each waiting out retries.
BREAKER_THRESHOLD = 3
#: Seconds the circuit stays open before one probe request is allowed.
BREAKER_TTL = 30.0

#: Seconds a request that exhausted its retries is remembered as failed.
FAILURE_TTL = 30.0


class ResponseTooLargeError(NetworkError):
    """A response body exceeded the client's size cap."""

    def __init__(self, url: str, limit: int, size: Optional[int] = None) -> None:
        mb = 1024 * 1024
        what = f"{size / mb:.0f} MB" if size else f"more than {limit / mb:.0f} MB"
        super().__init__(
            f"Response too large ({what}, limit {limit / mb:.0f} MB): {url}",
            url=url,
        )
        self.size = size
        self.limit = limit


def _failure_key(url: str, params: Any) -> Tuple[str, str]:
    """Return a hashable key identifying a request by URL and query params."""
    items = sorted(params.items()) if hasattr(params, "items") else params
    return (url, repr(items))


def _parse_retry_after(header_value: Optional[str]) -> float:
    """Parse a ``Retry-After`` header value into a clamped delay in seconds.

    Per RFC 7231 section 7.1.3, the value is either ``delay-seconds`` or an
    HTTP-date. Falls back to 1 second when missing or unparseable. The
    result is always clamped to ``[0, MAX_RETRY_AFTER_SECONDS]`` so a
    malformed or extreme value can never stall the client indefinitely.

    Args:
        header_value: The raw ``Retry-After`` header value, or ``None``.

    Returns:
        Delay in seconds, in ``[0, MAX_RETRY_AFTER_SECONDS]``.
    """
    if header_value is None:
        return 1.0

    header_value = header_value.strip()

    try:
        # Compared as an int: float(int) overflows for absurdly long digit strings.
        delay = float(min(int(header_value), MAX_RETRY_AFTER_SECONDS))
    except ValueError:
        try:
            target = parsedate_to_datetime(header_value)
        except (TypeError, ValueError, OverflowError):
            return 1.0

        if target.tzinfo is None:
            # Obsolete RFC 850 dates are assumed GMT, per RFC 7231 section 7.1.1.1.
            target = target.replace(tzinfo=timezone.utc)

        try:
            delay = (target - datetime.now(timezone.utc)).total_seconds()
        except OverflowError:
            return 1.0

    return max(0.0, min(delay, float(MAX_RETRY_AFTER_SECONDS)))


class HTTPClient:
    """Asynchronous HTTP client with retries, rate limiting, and concurrency control.

    Args:
        timeout: Request timeout in seconds.
        max_retries: Maximum number of retry attempts.
        rate_limit_delay: Minimum delay (seconds) between requests.
        verify_ssl: Whether to verify SSL certificates.
        user_agent: Custom User-Agent header value.
        max_concurrency: Maximum number of concurrent requests.
        total_timeout: Wall-clock limit in seconds for one request including
            all retries and backoff.
        max_response_bytes: Largest response body accepted.

    Example::
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
        total_timeout: float = DEFAULT_TOTAL_TIMEOUT,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        self.total_timeout = total_timeout
        self.max_response_bytes = max_response_bytes
        # Requests that exhausted every retry, with the failure time. Repeating
        # one within FAILURE_TTL (prefetch then check) would re-wait the
        # backoff; the TTL stops one outage poisoning a long-lived client.
        self._failed: Dict[Any, Tuple[float, NetworkError]] = {}
        self._conn_failures = 0
        self._breaker_open_until = 0.0
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
        """Create the underlying ``httpx`` client on first use.

        Construction is deferred so an `HTTPClient` can be built
        outside a running event loop and still bind its connection pool to
        the loop that actually issues requests.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                http2=True,
                verify=self.verify_ssl,
                follow_redirects=False,
                headers={"User-Agent": self.user_agent},
            )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _rate_limit(self) -> None:
        """Enforce a minimum delay between outgoing requests.

        The next slot is reserved (``_last_request_time`` is moved forward
        before sleeping) while the lock is held, so concurrent callers queue
        into distinct slots instead of all waking at the same instant.
        """
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

    def _note_connect_failure(self) -> bool:
        """Count a connection-level failure; return True when it opens the circuit."""
        self._conn_failures += 1
        if self._conn_failures < BREAKER_THRESHOLD:
            return False
        self._breaker_open_until = time.monotonic() + BREAKER_TTL
        logger.warning("Network unreachable; failing fast")
        return True

    async def _send_once(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send one request, following only safe redirects and capping the body.

        Redirects must stay on https and land on the original host or a PyPI
        host; the body is read incrementally and rejected above
        ``max_response_bytes``.
        """
        assert self._client is not None
        origin_host = urlsplit(url).hostname
        for _hop in range(MAX_REDIRECTS + 1):
            request = self._client.build_request(method, url, **kwargs)
            response = await self._client.send(request, stream=True)
            try:
                if response.is_redirect and "location" in response.headers:
                    target = urljoin(url, response.headers["location"])
                    parts = urlsplit(target)
                    if parts.scheme != "https" or parts.hostname not in (
                        _REDIRECT_HOSTS | {origin_host}
                    ):
                        raise NetworkError(
                            f"Refusing unsafe redirect to {redact(target)}",
                            url=redact(url),
                            status_code=response.status_code,
                        )
                    url = target
                    continue

                declared = response.headers.get("content-length", "")
                if (
                    declared.isascii()
                    and declared.isdigit()
                    and int(declared) > self.max_response_bytes
                ):
                    raise ResponseTooLargeError(
                        redact(url), self.max_response_bytes, int(declared)
                    )
                chunks = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self.max_response_bytes:
                        raise ResponseTooLargeError(
                            redact(url), self.max_response_bytes
                        )
                    chunks.append(chunk)
                headers = httpx.Headers(response.headers)
                # aiter_bytes already decoded the body.
                headers.pop("content-encoding", None)
                headers.pop("content-length", None)
                return httpx.Response(
                    response.status_code,
                    headers=headers,
                    content=b"".join(chunks),
                    request=request,
                )
            finally:
                await response.aclose()
        raise NetworkError(f"Too many redirects: {redact(url)}", url=redact(url))

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Run `_request_attempts` under the total wall-clock deadline."""
        clean_url = url.strip().strip("\"'")
        if urlsplit(clean_url).scheme not in ("http", "https"):
            raise NetworkError(
                f"Unsupported URL (expected http or https): {redact(clean_url)}",
                url=redact(clean_url),
            )
        key = _failure_key(clean_url, kwargs.get("params"))
        entry = self._failed.get(key) if method == "GET" else None
        if entry is not None:
            if time.monotonic() - entry[0] < FAILURE_TTL:
                # Fresh instance: re-raising one object grows its traceback.
                raise NetworkError(entry[1].message, url=redact(clean_url)) from entry[
                    1
                ].__cause__
            del self._failed[key]
        try:
            return await asyncio.wait_for(
                self._request_attempts(method, url, **kwargs), self.total_timeout
            )
        except asyncio.TimeoutError as exc:
            raise NetworkError(
                f"Request timed out after {self.total_timeout:.0f}s: {redact(clean_url)}",
                url=redact(clean_url),
            ) from exc

    async def _request_attempts(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Execute an HTTP request, retrying transient failures.

        Retry policy:

        - Timeouts, network errors and 5xx responses are retried up to
          ``max_retries`` times with exponential backoff plus jitter.
        - ``429`` responses honor the ``Retry-After`` header (see
          `_parse_retry_after`) and are capped separately by
          ``_max_429_retries``. Because the loop ``continue``s, a 429 retry
          also consumes one of the outer ``max_retries`` attempts.
        - ``404`` raises `PyPIError` immediately; other 4xx responses
          raise `NetworkError`. Client errors are not retried because
          repeating them cannot change the outcome.

        Args:
            method: HTTP method, e.g. ``"GET"``.
            url: Target URL. Surrounding whitespace and quotes are stripped,
                since requirement files often carry quoted URLs.
            **kwargs: Forwarded to ``httpx.AsyncClient.request``.

        Returns:
            The successful `httpx.Response`.

        Raises:
            PyPIError: The resource returned ``404``.
            NetworkError: A non-retryable client error, exhausted 429 budget,
                or every attempt failed.
        """
        await self._ensure_client()
        assert self._client is not None

        clean_url = url.strip().strip("\"'")
        last_exc: Optional[Exception] = None
        retry_429_count = 0

        for attempt in range(self.max_retries + 1):
            try:
                if time.monotonic() < self._breaker_open_until:
                    raise NetworkError(
                        "Network unreachable (too many consecutive connection "
                        f"failures): {redact(clean_url)}",
                        url=redact(clean_url),
                    )
                await self._rate_limit()

                async with self._semaphore:
                    response = await self._send_once(method, clean_url, **kwargs)
                self._conn_failures = 0

                if response.status_code == 429:
                    retry_429_count += 1
                    if retry_429_count > self._max_429_retries:
                        raise NetworkError(
                            f"Rate limit exceeded after {self._max_429_retries} retries",
                            url=redact(clean_url),
                            status_code=429,
                        )
                    retry_after = _parse_retry_after(
                        response.headers.get("Retry-After")
                    )
                    logger.warning(
                        "Rate limited (429), retrying after %.1fs (%d/%d)",
                        retry_after,
                        retry_429_count,
                        self._max_429_retries,
                    )
                    await asyncio.sleep(retry_after)
                    continue

                if response.status_code == 404:
                    raise PyPIError(
                        f"Resource not found: {redact(clean_url)}",
                        url=redact(clean_url),
                        status_code=404,
                    )

                if response.status_code >= 400:
                    response.raise_for_status()

                return response

            except httpx.TimeoutException as exc:
                last_exc = exc
                if isinstance(exc, httpx.ConnectTimeout) and self._note_connect_failure():
                    break
                logger.warning(
                    "Request timeout (%d/%d): %s",
                    attempt + 1,
                    self.max_retries + 1,
                    redact(clean_url),
                )

            except httpx.InvalidURL as exc:
                raise NetworkError(
                    f"Invalid URL: {redact(clean_url)}", url=redact(clean_url)
                ) from exc

            except (httpx.TransportError, httpx.DecodingError) as exc:
                last_exc = exc
                if isinstance(exc, (httpx.ConnectError, httpx.ProxyError)):
                    if self._note_connect_failure():
                        break
                else:
                    self._conn_failures = 0
                logger.warning(
                    "Network error (%d/%d): %s",
                    attempt + 1,
                    self.max_retries + 1,
                    redact(str(exc)),
                )

            except httpx.HTTPStatusError as exc:
                if 400 <= exc.response.status_code < 500:
                    raise NetworkError(
                        f"HTTP {exc.response.status_code} error for {redact(clean_url)}",
                        url=redact(clean_url),
                        status_code=exc.response.status_code,
                        response_body=exc.response.text,
                    ) from exc
                last_exc = exc
                logger.warning(
                    "HTTP %d error (%d/%d): %s",
                    exc.response.status_code,
                    attempt + 1,
                    self.max_retries + 1,
                    redact(clean_url),
                )

            if attempt < self.max_retries:
                delay = (2**attempt) + random.uniform(0.0, 0.3)
                logger.debug("Retrying in %.2fs", delay)
                await asyncio.sleep(delay)

        failure = NetworkError(
            f"Request failed after {attempt + 1} attempts: {redact(clean_url)}",
            url=redact(clean_url),
        )
        failure.__cause__ = last_exc
        if method == "GET":
            self._failed[_failure_key(clean_url, kwargs.get("params"))] = (
                time.monotonic(),
                failure,
            )
        raise failure

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Perform a GET request.

        Args:
            url: Target URL.
            **kwargs: Forwarded to ``httpx.AsyncClient.request``.

        Returns:
            The successful response.

        Raises:
            NetworkError: The request failed; see `_request_with_retry`.
        """
        return await self._request_with_retry("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Perform a POST request.

        Args:
            url: Target URL.
            **kwargs: Forwarded to ``httpx.AsyncClient.request``.

        Returns:
            The successful response.

        Raises:
            NetworkError: The request failed; see `_request_with_retry`.
        """
        return await self._request_with_retry("POST", url, **kwargs)

    async def get_json(self, url: str, **kwargs: Any) -> Dict[str, Any]:
        """Fetch a URL and decode the response as a JSON object.

        Args:
            url: Target URL.
            **kwargs: Forwarded to ``httpx.AsyncClient.request``.

        Returns:
            The decoded JSON object.

        Raises:
            NetworkError: The request failed, the body is not valid JSON, or
                the payload is a JSON value other than an object.
        """
        response = await self.get(url, **kwargs)

        try:
            data = response.json()
        except Exception as exc:
            raise NetworkError(
                f"Invalid JSON response from {redact(url)}",
                url=redact(url),
                response_body=response.text,
            ) from exc

        if not isinstance(data, dict):
            raise NetworkError(
                f"Expected JSON object from {redact(url)}",
                url=redact(url),
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

        Individual failures are logged and reported as an empty dict rather
        than raised, so one bad URL cannot abort a batch.

        Args:
            urls: Iterable of URLs to fetch.
            progress_callback: Optional callback invoked as
                ``(completed, total)`` after each response settles.

        Returns:
            Mapping of URL to parsed JSON data. Failed requests map to ``{}``.
        """
        url_list = list(urls)
        total = len(url_list)
        completed = 0
        results: Dict[str, Dict[str, Any]] = {}

        tasks = [self.get_json(url) for url in url_list]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        for url, result in zip(url_list, responses):
            if isinstance(result, BaseException):
                logger.debug("Failed to fetch %s: %s", url, result)
                results[url] = {}
            else:
                results[url] = result

            completed += 1
            if progress_callback:
                progress_callback(completed, total)

        return results
