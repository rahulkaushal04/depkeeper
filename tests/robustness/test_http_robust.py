"""Adversarial tests of depkeeper.utils.http.HTTPClient over httpx.MockTransport."""

from __future__ import annotations

import asyncio
import gzip
from typing import Any, Callable, List

import httpx
import pytest

from depkeeper.constants import MAX_RETRY_AFTER_SECONDS
from depkeeper.exceptions import NetworkError, PyPIError
from depkeeper.utils import http as http_mod
from depkeeper.utils.http import FAILURE_TTL, HTTPClient, _parse_retry_after

URL = "https://pypi.org/pypi/six/json"
Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> List[float]:
    delays: List[float] = []
    real = asyncio.sleep

    async def fake(d: float, *a: Any) -> None:
        delays.append(d)
        await real(0)

    monkeypatch.setattr(http_mod.asyncio, "sleep", fake)
    return delays


async def _client(handler: Handler, **kw: Any) -> HTTPClient:
    c = HTTPClient(**kw)
    await c._ensure_client()
    assert c._client is not None
    await c._client.aclose()
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


@pytest.mark.parametrize(
    "value",
    [
        "1" + "0" * 400,
        "9" * 5000,
        "Mon, 99 Jan 99999999999 00:00:00 GMT",
        "Fri, 31 Dec 9999 23:59:59 GMT",
        "Mon, 01 Jan 0001 00:00:00 GMT",
        "nan",
        "inf",
        "-5",
        "-0",
        "1e5",
        "1.5",
        "",
        " ",
        "\x00",
        "٣",
        "abc",
        "Wed, 21 Oct 1990 07:28:00 GMT",
        None,
    ],
)
def test_retry_after_never_raises_and_is_clamped(value: Any) -> None:
    d = _parse_retry_after(value)
    assert 0.0 <= d <= MAX_RETRY_AFTER_SECONDS


def test_retry_after_values() -> None:
    assert _parse_retry_after("7") == 7.0
    assert _parse_retry_after("-5") == 0.0
    assert _parse_retry_after("1" + "0" * 400) == MAX_RETRY_AFTER_SECONDS
    assert _parse_retry_after("garbage") == 1.0
    assert (
        _parse_retry_after("Fri, 31 Dec 9999 23:59:59 GMT") == MAX_RETRY_AFTER_SECONDS
    )


async def test_huge_retry_after_header_does_not_crash(sleeps: List[float]) -> None:
    calls = []

    def h(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "1" + "0" * 400})
        return httpx.Response(200, json={"ok": 1})

    c = await _client(h)
    assert await c.get_json(URL) == {"ok": 1}
    assert sleeps == [MAX_RETRY_AFTER_SECONDS]
    await c.close()


@pytest.mark.parametrize(
    "exc",
    [
        httpx.RemoteProtocolError("peer closed connection"),
        httpx.DecodingError("bad gzip"),
        httpx.ReadError("reset"),
        httpx.ConnectError("dns"),
        httpx.ProxyError("proxy"),
        httpx.WriteError("w"),
        httpx.PoolTimeout("t"),
    ],
)
async def test_transport_faults_are_retried_then_wrapped(
    exc: Exception, sleeps: List[float]
) -> None:
    n = []

    def h(req: httpx.Request) -> httpx.Response:
        n.append(1)
        raise exc

    c = await _client(h, max_retries=2)
    with pytest.raises(NetworkError):
        await c.get_json(URL)
    assert len(n) == 3 and len(sleeps) == 2
    await c.close()


async def test_recovers_after_transient_fault(sleeps: List[float]) -> None:
    n = []

    def h(req: httpx.Request) -> httpx.Response:
        n.append(1)
        if len(n) < 3:
            raise httpx.RemoteProtocolError("incomplete chunked read")
        return httpx.Response(200, json={"a": 1})

    c = await _client(h)
    assert await c.get_json(URL) == {"a": 1}
    await c.close()


async def test_bad_gzip_body_is_a_network_error(sleeps: List[float]) -> None:
    c = await _client(
        lambda r: httpx.Response(
            200, headers={"content-encoding": "gzip"}, content=b"not gzip"
        ),
        max_retries=0,
    )
    with pytest.raises(NetworkError):
        await c.get_json(URL)
    await c.close()


@pytest.mark.parametrize(
    "url", ["pypi.org/x", "ftp://pypi.org/x", "", "file:///etc/passwd", "//pypi.org/x"]
)
async def test_non_http_urls_rejected_without_retry(
    url: str, sleeps: List[float]
) -> None:
    c = await _client(lambda r: httpx.Response(200, json={}))
    with pytest.raises(NetworkError):
        await c.get(url)
    assert not sleeps
    await c.close()


async def test_status_semantics(sleeps: List[float]) -> None:
    c = await _client(lambda r: httpx.Response(404))
    with pytest.raises(PyPIError):
        await c.get(URL)
    c2 = await _client(lambda r: httpx.Response(403, text="nope"))
    with pytest.raises(NetworkError) as ei:
        await c2.get(URL)
    assert ei.value.status_code == 403 and not sleeps
    n = []

    def h(r: httpx.Request) -> httpx.Response:
        n.append(1)
        return httpx.Response(503)

    c3 = await _client(h, max_retries=3)
    with pytest.raises(NetworkError):
        await c3.get(URL)
    assert len(n) == 4
    assert all(2**i <= d <= 2**i + 0.3 for i, d in enumerate(sleeps))
    for x in (c, c2, c3):
        await x.close()


async def test_429_budget_is_bounded(sleeps: List[float]) -> None:
    n = []

    def h(r: httpx.Request) -> httpx.Response:
        n.append(1)
        return httpx.Response(429, headers={"Retry-After": "0"})

    c = await _client(h, max_retries=20)
    with pytest.raises(NetworkError) as ei:
        await c.get(URL)
    assert ei.value.status_code == 429 and len(n) == 6
    await c.close()


async def test_size_cap_declared_and_streamed_and_gzip_bomb() -> None:
    c = await _client(
        lambda r: httpx.Response(200, content=b"{}" + b" " * 5000),
        max_response_bytes=1000,
    )
    with pytest.raises(NetworkError, match="too large"):
        await c.get(URL)

    # Undeclared length: stream over the cap.
    def chunked(r: httpx.Request) -> httpx.Response:
        async def gen() -> Any:
            for _ in range(100):
                yield b"x" * 100

        return httpx.Response(200, content=gen())

    c2 = await _client(chunked, max_response_bytes=1000)
    with pytest.raises(NetworkError, match="too large"):
        await c2.get(URL)
    bomb = gzip.compress(b"0" * 50_000_000)
    c3 = await _client(
        lambda r: httpx.Response(
            200, headers={"content-encoding": "gzip"}, content=bomb
        ),
        max_response_bytes=1_000_000,
    )
    with pytest.raises(NetworkError, match="too large"):
        await c3.get(URL)
    for x in (c, c2, c3):
        await x.close()


@pytest.mark.parametrize(
    "location",
    [
        "http://pypi.org/x",
        "https://evil.example/x",
        "https://pypi.org.evil.example/x",
        "https://pypi.org@evil.example/x",
        "//evil.example/x",
        "ftp://pypi.org/x",
        "javascript:alert(1)",
    ],
)
async def test_unsafe_redirects_refused(location: str) -> None:
    seen: List[str] = []

    def h(r: httpx.Request) -> httpx.Response:
        seen.append(str(r.url))
        return httpx.Response(302, headers={"location": location})

    c = await _client(h)
    with pytest.raises(NetworkError):
        await c.get(URL)
    assert seen == [URL]
    await c.close()


async def test_safe_redirects_followed_and_loops_capped() -> None:
    def h(r: httpx.Request) -> httpx.Response:
        if r.url.path == "/pypi/six/json":
            return httpx.Response(301, headers={"location": "/pypi/six/2/json"})
        if r.url.path.endswith("/2/json"):
            return httpx.Response(
                302, headers={"location": "https://files.pythonhosted.org/x"}
            )
        return httpx.Response(200, json={"ok": True})

    c = await _client(h)
    assert await c.get_json(URL) == {"ok": True}
    n = []

    def loop(r: httpx.Request) -> httpx.Response:
        n.append(1)
        return httpx.Response(302, headers={"location": "/again"})

    c2 = await _client(loop)
    with pytest.raises(NetworkError, match="Too many redirects"):
        await c2.get(URL)
    assert len(n) == http_mod.MAX_REDIRECTS + 1
    await c.close()
    await c2.close()


async def test_failure_memory_ttl_and_key(
    monkeypatch: pytest.MonkeyPatch, sleeps: List[float]
) -> None:
    now = [1000.0]
    monkeypatch.setattr(http_mod.time, "monotonic", lambda: now[0])
    n = []

    def h(r: httpx.Request) -> httpx.Response:
        n.append(str(r.url))
        return httpx.Response(500)

    c = await _client(h, max_retries=1)
    for _ in range(2):
        with pytest.raises(NetworkError):
            await c.get(URL)
    assert len(n) == 2  # second call answered from memory
    with pytest.raises(NetworkError):
        await c.get(URL, params={"a": "1"})  # different params: new key
    assert len(n) == 4
    now[0] += FAILURE_TTL + 1
    with pytest.raises(NetworkError):
        await c.get(URL)
    assert len(n) == 6
    with pytest.raises(NetworkError):
        await c.post(URL)  # POST never cached
    await c.close()


async def test_credentials_never_in_errors_or_logs(
    caplog: pytest.LogCaptureFixture, sleeps: List[float]
) -> None:
    caplog.set_level("DEBUG")
    secret = "hunter2zz"
    url = f"https://bob:{secret}@pypi.org/pypi/six/json?token={secret}"
    for h in (
        lambda r: httpx.Response(500),
        lambda r: httpx.Response(403),
        lambda r: httpx.Response(404),
        lambda r: httpx.Response(200, content=b"nope"),
        lambda r: httpx.Response(
            302, headers={"location": f"https://evil.example/?token={secret}"}
        ),
        lambda r: (_ for _ in ()).throw(httpx.ConnectError(f"boom {url}")),
    ):
        c = await _client(h, max_retries=1)
        with pytest.raises(NetworkError) as caught:
            await c.get_json(url)
        e = caught.value
        blob = f"{e} {getattr(e, 'url', '')} {getattr(e, 'details', '')}"
        assert secret not in blob, blob
        await c.close()
    assert secret not in caplog.text


async def test_batch_partial_failure_and_progress(sleeps: List[float]) -> None:
    def h(r: httpx.Request) -> httpx.Response:
        if "bad" in r.url.path:
            return httpx.Response(404)
        if "list" in r.url.path:
            return httpx.Response(200, json=[1])
        return httpx.Response(200, json={"p": r.url.path})

    c = await _client(h, max_retries=0)
    urls = [f"https://pypi.org/pypi/{n}/json" for n in ("a", "bad", "list", "b", "a")]
    prog: List[Any] = []
    out = await c.batch_get_json(
        urls, progress_callback=lambda d, t: prog.append((d, t))
    )
    assert out["https://pypi.org/pypi/bad/json"] == {}
    assert out["https://pypi.org/pypi/list/json"] == {}
    assert out["https://pypi.org/pypi/a/json"] == {"p": "/pypi/a/json"}
    assert prog[-1] == (5, 5) and len(prog) == 5
    assert await c.batch_get_json([]) == {}
    await c.close()


async def test_semaphore_limits_concurrency() -> None:
    live = peak = 0

    async def slow(r: httpx.Request) -> httpx.Response:
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.01)
        live -= 1
        return httpx.Response(200, json={})

    c = await _client(slow, max_concurrency=3)
    await c.batch_get_json([f"https://pypi.org/pypi/p{i}/json" for i in range(20)])
    assert 1 <= peak <= 3
    await c.close()


async def test_total_deadline_and_cancellation_close_responses() -> None:
    async def hang(r: httpx.Request) -> httpx.Response:
        await asyncio.sleep(30)
        return httpx.Response(200, json={})

    c = await _client(hang, total_timeout=0.2)
    with pytest.raises(NetworkError, match="timed out"):
        await c.get(URL)
    task = asyncio.ensure_future(_client_get(await _client(hang)))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await c.close()


async def _client_get(c: HTTPClient) -> None:
    try:
        await c.get(URL)
    finally:
        await c.close()


async def test_cancel_batch_cancels_children() -> None:
    started = []

    async def hang(r: httpx.Request) -> httpx.Response:
        started.append(1)
        await asyncio.sleep(30)
        return httpx.Response(200, json={})

    c = await _client(hang)
    t = asyncio.ensure_future(
        c.batch_get_json([f"https://pypi.org/p{i}" for i in range(3)])
    )
    await asyncio.sleep(0.05)
    t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t
    await asyncio.sleep(0.05)
    assert all(x.done() for x in [t])
    await c.close()


async def test_get_json_non_object_and_invalid() -> None:
    for body in (b"[1]", b"null", b"\xff\xfe", b"", b"{"):
        c = await _client(lambda r, b=body: httpx.Response(200, content=b))
        with pytest.raises(NetworkError):
            await c.get_json(URL)
        await c.close()


def test_user_agent_has_no_pii() -> None:
    ua = HTTPClient().user_agent
    assert "@" not in ua and "depkeeper" in ua.lower()


async def test_proxy_env_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    c = HTTPClient()
    await c._ensure_client()
    assert c._client is not None and c._client._trust_env  # type: ignore[attr-defined]
    await c.close()
