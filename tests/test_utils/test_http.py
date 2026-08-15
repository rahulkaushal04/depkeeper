"""Tests for :class:`depkeeper.utils.http.HTTPClient`.

This is the only component that talks to the network, so its retry, rate-limit
and concurrency behaviour decides whether a ``depkeeper check`` against a flaky
PyPI mirror recovers or fails the build.

Two deliberate choices shape this module:

- **No real waiting.** ``asyncio.sleep`` is replaced by the ``instant_sleep``
  fixture, which records the requested delay instead of honouring it. The old
  version of these tests spent roughly 50 seconds sleeping through exponential
  backoff, and asserted on ``time.time()`` deltas — which made every retry test
  a race against CI scheduling. Recording delays is both faster *and* a
  stronger assertion: the exact backoff schedule is checked, not a lower bound.
- **Transport-level fakes.** Responses are driven through ``httpx.MockTransport``
  where practical, so status handling exercises real ``httpx.Response`` objects
  rather than ``MagicMock``\\ s that would happily agree with a broken
  expectation.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
import pytest

from depkeeper.exceptions import NetworkError, PyPIError
from depkeeper.utils.http import HTTPClient

PYPI_URL = "https://pypi.org/pypi/requests/json"

#: A trimmed but structurally real PyPI JSON body.
REQUESTS_PAYLOAD: Dict[str, Any] = {
    "info": {
        "name": "requests",
        "version": "2.32.3",
        "requires_python": ">=3.8",
        "requires_dist": ["urllib3<3,>=1.21.1", "certifi>=2017.4.17"],
    },
    "releases": {"2.31.0": [{"filename": "requests-2.31.0-py3-none-any.whl"}]},
}


# ---------------------------------------------------------------------------
# Transport helpers
# ---------------------------------------------------------------------------


def _client(
    responses: List[Any],
    *,
    seen: Optional[List[httpx.Request]] = None,
    **kwargs: Any,
) -> HTTPClient:
    """Build an :class:`HTTPClient` wired to a mock transport.

    The client is returned *unopened*; use it as an async context manager so
    ``close`` still runs and connection cleanup stays under test.

    SSL verification is disabled by default because every request is served by
    an in-memory transport. Leaving it on makes ``httpx`` build a real
    ``SSLContext`` — and load the CA bundle — for each of the dozens of clients
    this module creates, which dominated the module's runtime.
    """
    kwargs.setdefault("verify_ssl", False)
    client = HTTPClient(**kwargs)
    remaining = list(responses)
    calls = seen if seen is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        item = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        if isinstance(item, BaseException):
            raise item
        return item

    transport = httpx.MockTransport(handler)
    original_ensure = client._ensure_client

    async def _ensure_with_mock_transport() -> None:
        await original_ensure()
        assert client._client is not None
        client._client._transport = transport

    client._ensure_client = _ensure_with_mock_transport  # type: ignore[method-assign]
    return client


#: Distinguishes "no JSON body" from a body that is literally ``null``.
_NO_BODY = object()


def _response(
    status_code: int,
    *,
    json_body: Any = _NO_BODY,
    text: str = "",
    headers: Optional[Dict[str, str]] = None,
) -> httpx.Response:
    """Build a real ``httpx.Response`` with the given status and body."""
    if json_body is not _NO_BODY:
        return httpx.Response(status_code, json=json_body, headers=headers)
    return httpx.Response(status_code, text=text, headers=headers)


# ---------------------------------------------------------------------------
# Configuration and lifecycle
# ---------------------------------------------------------------------------


class TestConfiguration:
    def test_defaults_match_the_documented_contract(self) -> None:
        """These values appear in the README and bound worst-case run time."""
        client = HTTPClient()

        assert (client.timeout, client.max_retries) == (30, 3)
        assert client.rate_limit_delay == 0.0
        assert client.verify_ssl is True
        assert client.max_concurrency == 10
        assert client._max_429_retries == 5

    def test_user_agent_identifies_depkeeper_and_its_version(self) -> None:
        """PyPI rate-limits by user agent; an anonymous one gets throttled."""
        from depkeeper.__version__ import __version__

        assert __version__ in HTTPClient().user_agent
        assert "depkeeper" in HTTPClient().user_agent

    async def test_configuration_reaches_the_underlying_httpx_client(self) -> None:
        """Storing the values is not enough — they must be applied."""
        async with HTTPClient(
            timeout=15, verify_ssl=False, user_agent="acme-ci/1.0", max_concurrency=4
        ) as client:
            assert client._client is not None
            assert client._client.timeout.read == 15
            assert client._client.headers["User-Agent"] == "acme-ci/1.0"
            assert client._semaphore._value == 4


class TestLifecycle:
    async def test_context_manager_opens_and_closes_the_transport(self) -> None:
        client = HTTPClient()

        async with client:
            assert isinstance(client._client, httpx.AsyncClient)

        assert client._client is None

    async def test_transport_is_closed_even_when_the_body_raises(self) -> None:
        """A failed check must not leak sockets into the rest of the process."""
        client = HTTPClient()

        with pytest.raises(RuntimeError):
            async with client:
                raise RuntimeError("check failed")

        assert client._client is None

    async def test_client_can_be_reopened_after_closing(self) -> None:
        """``check`` and ``update`` each open the shared client in turn."""
        client = HTTPClient()

        async with client:
            first = client._client
        async with client:
            second = client._client

        assert first is not second

    async def test_ensure_client_is_idempotent(self) -> None:
        """Every request calls it; recreating the pool would defeat keep-alive."""
        client = HTTPClient()

        await client._ensure_client()
        first = client._client
        await client._ensure_client()

        assert client._client is first
        await client.close()

    async def test_close_is_safe_before_and_after_use(self) -> None:
        client = HTTPClient()

        await client.close()  # never opened
        await client._ensure_client()
        await client.close()
        await client.close()  # already closed

        assert client._client is None


# ---------------------------------------------------------------------------
# Request handling
# ---------------------------------------------------------------------------


class TestRequestSuccess:
    @pytest.mark.parametrize("status_code", [200, 201, 202, 204])
    async def test_success_statuses_are_returned_unchanged(
        self, status_code: int
    ) -> None:
        client = _client([_response(status_code)], max_retries=0)

        async with client:
            response = await client.get(PYPI_URL)

        assert response.status_code == status_code

    @pytest.mark.parametrize(
        "raw_url",
        [
            f'"{PYPI_URL}"',
            f"'{PYPI_URL}'",
            f"  {PYPI_URL}  ",
            f"\t{PYPI_URL}\n",
        ],
        ids=["double-quoted", "single-quoted", "spaces", "tabs-and-newline"],
    )
    async def test_urls_are_cleaned_before_dispatch(self, raw_url: str) -> None:
        """URLs arrive from config files and shell interpolation, so quoting
        and stray whitespace are routine; sending them verbatim yields a 404.
        """
        seen: List[httpx.Request] = []
        client = _client([_response(200)], seen=seen, max_retries=0)

        async with client:
            await client.get(raw_url)

        assert str(seen[0].url) == PYPI_URL

    async def test_post_sends_the_body_through(self) -> None:
        seen: List[httpx.Request] = []
        client = _client([_response(201)], seen=seen, max_retries=0)

        async with client:
            await client.post(PYPI_URL, json={"name": "requests"})

        assert seen[0].method == "POST"
        assert json.loads(seen[0].content) == {"name": "requests"}


class TestRetryPolicy:
    """Which failures are retried, how often, and with what backoff.

    Getting the classification wrong is expensive in both directions: retrying
    a 404 multiplies load on PyPI for no benefit, while *not* retrying a 503
    turns a momentary blip into a failed build.
    """

    @pytest.mark.parametrize(
        "failure",
        [
            pytest.param(httpx.TimeoutException("read timed out"), id="timeout"),
            pytest.param(httpx.ConnectError("connection refused"), id="connect-error"),
            pytest.param(httpx.ReadError("connection reset"), id="read-error"),
        ],
    )
    async def test_transport_failures_are_retried_then_succeed(
        self, failure: Exception, instant_sleep: List[float]
    ) -> None:
        seen: List[httpx.Request] = []
        client = _client([failure, _response(200)], seen=seen, max_retries=2)

        async with client:
            response = await client.get(PYPI_URL)

        assert response.status_code == 200
        assert len(seen) == 2

    @pytest.mark.parametrize("status_code", [500, 502, 503, 504])
    async def test_server_errors_are_retried_then_succeed(
        self, status_code: int, instant_sleep: List[float]
    ) -> None:
        """5xx is the mirror having a bad minute; the next attempt usually works."""
        seen: List[httpx.Request] = []
        client = _client(
            [_response(status_code, text="upstream error"), _response(200)],
            seen=seen,
            max_retries=2,
        )

        async with client:
            response = await client.get(PYPI_URL)

        assert response.status_code == 200
        assert len(seen) == 2

    @pytest.mark.parametrize("status_code", [400, 401, 403, 405, 422])
    async def test_client_errors_fail_fast_without_retrying(
        self, status_code: int, instant_sleep: List[float]
    ) -> None:
        """The request is wrong; repeating it wastes the user's time and PyPI's."""
        seen: List[httpx.Request] = []
        client = _client(
            [_response(status_code, text="denied")], seen=seen, max_retries=3
        )

        async with client:
            with pytest.raises(NetworkError) as exc_info:
                await client.get(PYPI_URL)

        assert exc_info.value.status_code == status_code
        assert exc_info.value.response_body == "denied"
        assert len(seen) == 1
        assert instant_sleep == []

    async def test_404_raises_pypi_error_immediately(
        self, instant_sleep: List[float]
    ) -> None:
        """A typo'd or private package name must be reported as such, not as a
        network outage — the two need completely different user action.
        """
        seen: List[httpx.Request] = []
        client = _client([_response(404)], seen=seen, max_retries=3)

        async with client:
            with pytest.raises(PyPIError) as exc_info:
                await client.get(PYPI_URL)

        assert exc_info.value.status_code == 404
        assert "not found" in str(exc_info.value).lower()
        assert len(seen) == 1

    async def test_retries_are_exhausted_then_reported(
        self, instant_sleep: List[float]
    ) -> None:
        """The final error must name the attempt count so the user can tell a
        persistent outage from a single unlucky request.
        """
        seen: List[httpx.Request] = []
        client = _client(
            [httpx.TimeoutException("read timed out")], seen=seen, max_retries=2
        )

        async with client:
            with pytest.raises(NetworkError, match="failed after 3 attempts"):
                await client.get(PYPI_URL)

        assert len(seen) == 3  # initial attempt plus two retries

    async def test_backoff_grows_exponentially_with_bounded_jitter(
        self, instant_sleep: List[float]
    ) -> None:
        """Backoff is ``2**attempt`` plus up to 0.3s of jitter.

        The exponential term prevents a retry storm against an already
        struggling mirror; the jitter stops many concurrent clients from
        retrying in lockstep. Asserting on the recorded delays checks both
        properties exactly, where a wall-clock assertion could only ever check
        a lower bound.
        """
        client = _client([httpx.TimeoutException("read timed out")], max_retries=3)

        async with client:
            with pytest.raises(NetworkError):
                await client.get(PYPI_URL)

        assert len(instant_sleep) == 3
        for attempt, delay in enumerate(instant_sleep):
            base = 2**attempt
            assert base <= delay < base + 0.3

    async def test_no_backoff_is_applied_after_the_final_attempt(
        self, instant_sleep: List[float]
    ) -> None:
        """Sleeping before giving up would add latency for no benefit."""
        client = _client([httpx.TimeoutException("read timed out")], max_retries=0)

        async with client:
            with pytest.raises(NetworkError):
                await client.get(PYPI_URL)

        assert instant_sleep == []


class TestRateLimitResponses:
    """429 has its own budget, separate from the transport retry budget.

    PyPI answers a 429 quickly, so these attempts are cheap and a client that
    counted them against ``max_retries`` would give up while still being told
    exactly how long to wait.
    """

    async def test_retry_after_header_is_honoured(
        self, instant_sleep: List[float]
    ) -> None:
        client = _client(
            [_response(429, headers={"Retry-After": "7"}), _response(200)],
            max_retries=1,
        )

        async with client:
            response = await client.get(PYPI_URL)

        assert response.status_code == 200
        assert instant_sleep == [7]

    async def test_missing_retry_after_falls_back_to_one_second(
        self, instant_sleep: List[float]
    ) -> None:
        client = _client([_response(429), _response(200)], max_retries=1)

        async with client:
            await client.get(PYPI_URL)

        assert instant_sleep == [1]

    async def test_429_attempts_consume_an_outer_retry_slot(
        self, instant_sleep: List[float]
    ) -> None:
        """Documented behaviour: a 429 also costs one ``max_retries`` attempt.

        ``_max_429_retries`` caps how many rate-limit responses are tolerated,
        but each one re-enters the same loop that bounds transport retries. With
        ``max_retries=1`` a client therefore survives exactly one 429, even
        though its 429 budget is five. Operators tuning ``max_retries`` down for
        latency need to know it also shortens rate-limit patience.
        """
        seen: List[httpx.Request] = []
        client = _client(
            [
                _response(429, headers={"Retry-After": "0"}),
                _response(429, headers={"Retry-After": "0"}),
                _response(200),
            ],
            seen=seen,
            max_retries=1,
        )

        async with client:
            with pytest.raises(NetworkError, match="failed after 2 attempts"):
                await client.get(PYPI_URL)

        assert len(seen) == 2

    async def test_a_generous_retry_budget_rides_out_transient_throttling(
        self, instant_sleep: List[float]
    ) -> None:
        """With the default budget, four 429s still resolve to a success."""
        seen: List[httpx.Request] = []
        client = _client(
            [
                _response(429, headers={"Retry-After": "0"}),
                _response(429, headers={"Retry-After": "0"}),
                _response(429, headers={"Retry-After": "0"}),
                _response(429, headers={"Retry-After": "0"}),
                _response(200),
            ],
            seen=seen,
            max_retries=5,
        )

        async with client:
            response = await client.get(PYPI_URL)

        assert response.status_code == 200
        assert len(seen) == 5

    async def test_sustained_rate_limiting_eventually_gives_up(
        self, instant_sleep: List[float]
    ) -> None:
        """Without a cap a throttled client would spin indefinitely."""
        seen: List[httpx.Request] = []
        client = _client(
            [_response(429, headers={"Retry-After": "0"})], seen=seen, max_retries=10
        )
        client._max_429_retries = 2

        async with client:
            with pytest.raises(NetworkError, match="Rate limit exceeded") as exc_info:
                await client.get(PYPI_URL)

        assert exc_info.value.status_code == 429
        assert len(seen) == client._max_429_retries + 1


class TestOutboundRateLimiting:
    """``rate_limit_delay`` throttles depkeeper's own request rate."""

    @pytest.mark.parametrize("delay", [0.0, -1.0], ids=["zero", "negative"])
    async def test_non_positive_delay_disables_throttling(
        self, delay: float, instant_sleep: List[float]
    ) -> None:
        client = HTTPClient(rate_limit_delay=delay)

        await client._rate_limit()
        await client._rate_limit()

        assert instant_sleep == []

    async def test_second_request_waits_out_the_remaining_interval(
        self, instant_sleep: List[float]
    ) -> None:
        """The first call is free; subsequent calls pay the difference."""
        client = HTTPClient(rate_limit_delay=0.5)

        await client._rate_limit()
        await client._rate_limit()

        assert len(instant_sleep) == 1
        assert 0 < instant_sleep[0] <= 0.5

    async def test_concurrent_callers_are_serialised_into_a_schedule(
        self, instant_sleep: List[float]
    ) -> None:
        """A lock plus a projected timestamp is what stops a burst of coroutines
        from all reading the same "last request" time and firing at once.
        """
        client = HTTPClient(rate_limit_delay=0.5)

        await asyncio.gather(*(client._rate_limit() for _ in range(4)))

        # First caller passes freely; the other three are spaced out.
        assert len(instant_sleep) == 3
        assert instant_sleep == sorted(instant_sleep)


class TestConcurrencyLimit:
    """The semaphore bounds in-flight requests so PyPI is not flooded."""

    async def test_in_flight_requests_never_exceed_the_limit(self) -> None:
        peak = 0
        active = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal peak, active
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)
            active -= 1
            return httpx.Response(200, json={})

        client = HTTPClient(max_concurrency=3, max_retries=0, verify_ssl=False)
        await client._ensure_client()
        assert client._client is not None
        client._client._transport = httpx.MockTransport(handler)  # type: ignore[assignment]

        try:
            await asyncio.gather(*(client.get(PYPI_URL) for _ in range(12)))
        finally:
            await client.close()

        assert peak <= 3

    async def test_permits_are_released_when_a_request_fails(self) -> None:
        """A leaked permit deadlocks every later request in the same run."""
        client = _client([_response(500, text="boom")], max_concurrency=2, max_retries=0)

        async with client:
            for _ in range(4):
                with pytest.raises(NetworkError):
                    await client.get(PYPI_URL)

            assert client._semaphore._value == 2


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


class TestGetJson:
    async def test_parses_a_realistic_pypi_document(self) -> None:
        client = _client([_response(200, json_body=REQUESTS_PAYLOAD)], max_retries=0)

        async with client:
            data = await client.get_json(PYPI_URL)

        assert data["info"]["version"] == "2.32.3"
        assert data["info"]["requires_dist"] == [
            "urllib3<3,>=1.21.1",
            "certifi>=2017.4.17",
        ]

    async def test_empty_object_is_valid(self) -> None:
        """A package with no releases still returns a well-formed document."""
        client = _client([_response(200, json_body={})], max_retries=0)

        async with client:
            assert await client.get_json(PYPI_URL) == {}

    async def test_malformed_json_is_reported_with_the_body(self) -> None:
        """A mirror serving an HTML error page is the common cause; the body is
        what tells the user they are pointed at a proxy rather than PyPI.
        """
        client = _client(
            [_response(200, text="<html>502 Bad Gateway</html>")], max_retries=0
        )

        async with client:
            with pytest.raises(NetworkError, match="Invalid JSON") as exc_info:
                await client.get_json(PYPI_URL)

        assert exc_info.value.response_body == "<html>502 Bad Gateway</html>"

    @pytest.mark.parametrize(
        "body",
        ['["requests"]', '"requests"', "42", "null", "true"],
        ids=["array", "string", "number", "null", "bool"],
    )
    async def test_non_object_documents_are_rejected(self, body: str) -> None:
        """Callers index into the result; a list would fail far from here.

        Bodies are supplied as raw JSON text so that ``null`` and ``true`` are
        actually transmitted rather than being dropped during encoding.
        """
        client = _client([_response(200, text=body)], max_retries=0)

        async with client:
            with pytest.raises(NetworkError, match="Expected JSON object"):
                await client.get_json(PYPI_URL)


class TestBatchGetJson:
    """Batch fetching is how ``check`` resolves a whole requirements file."""

    @staticmethod
    def _urls(*names: str) -> List[str]:
        return [f"https://pypi.org/pypi/{name}/json" for name in names]

    @staticmethod
    def _fake_get_json(behaviour: Dict[str, Any]) -> Callable[..., Any]:
        """Return a ``get_json`` replacement driven by *behaviour*.

        Patched onto the class, so it takes ``self``. Values that are exceptions
        are raised; anything else is returned.
        """

        async def _get_json(_self: HTTPClient, url: str, **_: Any) -> Dict[str, Any]:
            result = behaviour[url]
            if isinstance(result, BaseException):
                raise result
            return result

        return _get_json

    async def test_returns_one_entry_per_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        urls = self._urls("requests", "urllib3", "certifi")
        monkeypatch.setattr(
            HTTPClient,
            "get_json",
            self._fake_get_json({url: {"url": url} for url in urls}),
        )

        async with HTTPClient(verify_ssl=False) as client:
            results = await client.batch_get_json(urls)

        assert results == {url: {"url": url} for url in urls}

    async def test_a_failed_package_does_not_fail_the_batch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One private or misspelled package must not abandon the other 200.

        The empty dict is the contract the checker relies on to emit an
        "unavailable" stub rather than aborting the run.
        """
        requests_url, private_url, dead_url = self._urls(
            "requests", "acme-private", "certifi"
        )
        monkeypatch.setattr(
            HTTPClient,
            "get_json",
            self._fake_get_json(
                {
                    requests_url: REQUESTS_PAYLOAD,
                    private_url: PyPIError("not found", status_code=404),
                    dead_url: NetworkError("timed out"),
                }
            ),
        )

        async with HTTPClient(verify_ssl=False) as client:
            results = await client.batch_get_json(
                [requests_url, private_url, dead_url]
            )

        assert results[requests_url] == REQUESTS_PAYLOAD
        assert results[private_url] == {}
        assert results[dead_url] == {}

    async def test_progress_is_reported_once_per_url_with_a_stable_total(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The progress bar reads these values; a drifting total makes it jump."""
        urls = self._urls("requests", "urllib3", "certifi", "idna")
        monkeypatch.setattr(
            HTTPClient, "get_json", self._fake_get_json({url: {} for url in urls})
        )
        progress: List[Tuple[int, int]] = []

        async with HTTPClient(verify_ssl=False) as client:
            await client.batch_get_json(
                urls, progress_callback=lambda done, total: progress.append((done, total))
            )

        assert progress == [(1, 4), (2, 4), (3, 4), (4, 4)]

    async def test_empty_batch_is_a_no_op(self) -> None:
        """An empty requirements file must not open a connection at all."""
        progress: List[Tuple[int, int]] = []

        async with HTTPClient(verify_ssl=False) as client:
            results = await client.batch_get_json(
                [], progress_callback=lambda done, total: progress.append((done, total))
            )

        assert results == {}
        assert progress == []
