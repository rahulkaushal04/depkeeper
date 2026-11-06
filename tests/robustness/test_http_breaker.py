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
    HTTPClient,
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
    assert sum(sleeps) <= 3.5  # two backoffs, none after the circuit opens


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
    assert c._conn_failures == 0


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
            raise ResponseTooLargeError("https://pypi.org/pypi/ddtrace/json", 64 << 20, 80 << 20)

    pkg = await VersionChecker(Store()).get_package_info("ddtrace")  # type: ignore[arg-type]
    err = pkg.to_json()["error"]
    assert "ddtrace" in err and "80 MB" in err and "64 MB limit" in err
