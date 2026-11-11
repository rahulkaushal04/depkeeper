"""Circuit breaker and size-cap behaviour of HTTPClient and its reporting."""

from __future__ import annotations

import time
from typing import Any, List

import httpx
import pytest

from depkeeper.core.checker import VersionChecker
from depkeeper.exceptions import NetworkError
from depkeeper.utils import http as http_mod
from depkeeper.utils.http import (
    BREAKER_THRESHOLD,
    MAX_RESPONSE_BYTES,
    ResponseTooLargeError,
)

from .test_http_robust import Handler, _client, sleeps  # noqa: F401


async def test_connection_failures_open_circuit() -> None:
    calls: List[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        raise httpx.ConnectError("refused")

    c = await _client(handler)
    for i in range(6):
        with pytest.raises(NetworkError):
            await c.get(f"https://pypi.org/pypi/p{i}/json")
    assert len(calls) == BREAKER_THRESHOLD


async def test_circuit_skips_backoff(sleeps: List[float]) -> None:  # noqa: F811
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    c = await _client(handler)
    with pytest.raises(NetworkError):
        await c.get("https://pypi.org/pypi/a/json")
    assert len(sleeps) == 2  # two backoffs, none after the circuit opens


async def test_http_errors_do_not_open_circuit(sleeps: List[float]) -> None:  # noqa: F811
    calls: List[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503)

    c = await _client(handler, max_retries=1)
    for i in range(5):
        with pytest.raises(NetworkError):
            await c.get(f"https://pypi.org/pypi/p{i}/json")
    assert len(calls) == 10


async def test_success_resets_and_circuit_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"down": True}

    def handler(req: httpx.Request) -> httpx.Response:
        if state["down"]:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={})

    c = await _client(handler, max_retries=0)
    for i in range(BREAKER_THRESHOLD):
        with pytest.raises(NetworkError):
            await c.get(f"https://pypi.org/pypi/a{i}/json")
    state["down"] = False
    with pytest.raises(NetworkError, match="unreachable"):
        await c.get("https://pypi.org/pypi/b/json")
    real = time.monotonic
    monkeypatch.setattr(
        http_mod.time, "monotonic", lambda: real() + http_mod.BREAKER_TTL + 1
    )
    assert (await c.get("https://pypi.org/pypi/c/json")).status_code == 200
    assert not c._hosts


async def test_oversize_is_explicit() -> None:
    assert MAX_RESPONSE_BYTES == 64 * 1024 * 1024
    c = await _client(lambda r: httpx.Response(200, content=b"x" * 3000), max_retries=0)
    c.max_response_bytes = 1000
    with pytest.raises(ResponseTooLargeError) as ei:
        await c.get("https://pypi.org/pypi/big/json")
    assert ei.value.limit == 1000


async def test_checker_stub_carries_size_reason() -> None:
    class Store:
        async def get_package_data(self, name: str) -> Any:
            raise ResponseTooLargeError(
                "https://pypi.org/pypi/ddtrace/json", 64 << 20, 80 << 20
            )

    pkg = await VersionChecker(Store()).get_package_info("ddtrace")  # type: ignore[arg-type]
    err = pkg.to_json()["error"]
    assert "ddtrace" in err and "80 MB" in err and "64 MB limit" in err


async def test_circuit_is_per_host() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "down.example":
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={})

    c = await _client(handler, max_retries=0)
    for i in range(BREAKER_THRESHOLD):
        with pytest.raises(NetworkError):
            await c.get(f"https://down.example/{i}")
    with pytest.raises(NetworkError, match="unreachable"):
        await c.get("https://down.example/again")
    assert (await c.get("https://pypi.org/pypi/a/json")).status_code == 200


async def test_flaky_requests_among_successes_never_trip() -> None:
    n = {"i": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        n["i"] += 1
        if n["i"] % 3 != 0:
            return httpx.Response(200, json={})
        raise httpx.ConnectError("blip")

    c = await _client(handler, max_retries=0)
    for i in range(30):
        try:
            await c.get(f"https://pypi.org/pypi/p{i}/json")
        except NetworkError as exc:
            assert "unreachable" not in str(exc)


async def test_half_open_admits_exactly_one_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    state = {"down": True, "sent": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        state["sent"] += 1
        if state["down"]:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={})

    c = await _client(handler, max_retries=0)
    for i in range(BREAKER_THRESHOLD):
        with pytest.raises(NetworkError):
            await c.get(f"https://pypi.org/pypi/a{i}/json")
    real = time.monotonic
    monkeypatch.setattr(
        http_mod.time, "monotonic", lambda: real() + http_mod.BREAKER_TTL + 1
    )
    before = state["sent"]
    # Probe fails -> circuit re-opens with a restarted cool-down; the rest fail fast.
    res = await asyncio.gather(
        *(c.get(f"https://pypi.org/pypi/q{i}/json") for i in range(5)),
        return_exceptions=True,
    )
    assert all(isinstance(r, NetworkError) for r in res)
    assert state["sent"] - before == 1
    with pytest.raises(NetworkError, match="unreachable"):
        await c.get("https://pypi.org/pypi/after/json")
    assert state["sent"] - before == 1


async def test_probe_success_closes_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    state = {"down": True}

    def handler(req: httpx.Request) -> httpx.Response:
        if state["down"]:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={})

    c = await _client(handler, max_retries=0)
    for i in range(BREAKER_THRESHOLD):
        with pytest.raises(NetworkError):
            await c.get(f"https://pypi.org/pypi/a{i}/json")
    state["down"] = False
    real = time.monotonic
    monkeypatch.setattr(
        http_mod.time, "monotonic", lambda: real() + http_mod.BREAKER_TTL + 1
    )
    await c.get("https://pypi.org/pypi/probe/json")
    res = await asyncio.gather(
        *(c.get(f"https://pypi.org/pypi/z{i}/json") for i in range(5))
    )
    assert all(r.status_code == 200 for r in res)


async def test_inconclusive_probe_releases_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mode = {"v": "down"}

    def handler(req: httpx.Request) -> httpx.Response:
        if mode["v"] == "down":
            raise httpx.ConnectError("refused")
        if mode["v"] == "big":
            return httpx.Response(200, content=b"x" * 100)
        return httpx.Response(200, json={})

    c = await _client(handler, max_retries=0)
    for i in range(BREAKER_THRESHOLD):
        with pytest.raises(NetworkError):
            await c.get(f"https://pypi.org/pypi/a{i}/json")
    c.max_response_bytes = 10
    mode["v"] = "big"
    real = time.monotonic
    monkeypatch.setattr(
        http_mod.time, "monotonic", lambda: real() + http_mod.BREAKER_TTL + 1
    )
    with pytest.raises(ResponseTooLargeError):
        await c.get("https://pypi.org/pypi/p1/json")
    # A response arrived, so the host is reachable and the slot is free.
    c.max_response_bytes = MAX_RESPONSE_BYTES
    mode["v"] = "ok"
    assert (await c.get("https://pypi.org/pypi/p2/json")).status_code == 200


@pytest.mark.parametrize(
    "value, expected",
    [
        # Huge digit strings are clamped and rejected as oversize, never a ValueError.
        ("9" * 5000, 10**18),
        ("١٢", None),
        ("²", None),
        ("12abc", None),
        ("-5", None),
        ("", None),
        ("1e9", None),
        (" ", None),
        ("12", 12),
    ],
)
def test_garbage_content_length_does_not_crash(value: str, expected: Any) -> None:
    assert http_mod._declared_length(value) == expected
    assert http_mod._declared_length(" 42 ") == 42


async def test_unparseable_content_length_header_is_ignored() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{}", headers={"content-length": "12abc"})

    c = await _client(handler, max_retries=0)
    assert (await c.get("https://pypi.org/pypi/a/json")).status_code == 200


def test_broken_pipe_on_console_flush_raises_broken_pipe_error() -> None:
    import io

    from depkeeper.utils.console import _SafeConsole

    class Closed(io.StringIO):
        def flush(self) -> None:
            raise BrokenPipeError

    with pytest.raises(BrokenPipeError):
        _SafeConsole(file=Closed()).print("x")


def test_main_maps_broken_pipe_to_141(monkeypatch: pytest.MonkeyPatch) -> None:
    import depkeeper.cli as cli_mod

    def boom(**_: Any) -> None:
        raise BrokenPipeError

    monkeypatch.setattr(cli_mod, "cli", boom)
    monkeypatch.setattr(cli_mod.os, "dup2", lambda *a: None)
    assert cli_mod.main() == 141
