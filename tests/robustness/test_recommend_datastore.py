"""PyPI JSON parsing hardening and data-store caching rules."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import pytest

from depkeeper.core.data_store import PyPIDataStore
from depkeeper.exceptions import PyPIError


class Resp:
    """Minimal HTTP response."""

    def __init__(self, status: int = 200, body: Any = None, bad_json: bool = False):
        self.status_code = status
        self._body = body
        self._bad = bad_json

    def json(self) -> Any:
        if self._bad:
            raise ValueError("not json")
        return self._body


class FakeHttp:
    """Scripted HTTP client recording calls and peak concurrency."""

    def __init__(self, handler: Callable[[str], Any], delay: float = 0.0):
        self.handler = handler
        self.delay = delay
        self.calls: List[str] = []
        self.active = 0
        self.peak = 0

    async def get(self, url: str, **_: Any) -> Resp:
        self.calls.append(url)
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            out = self.handler(url)
            if isinstance(out, BaseException):
                raise out
            return out  # type: ignore[no-any-return]
        finally:
            self.active -= 1


def _store(http: FakeHttp, limit: int = 10) -> PyPIDataStore:
    return PyPIDataStore(http, concurrent_limit=limit)  # type: ignore[arg-type]


def _payload(**kw: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "info": {
            "version": "1.1",
            "requires_python": ">=3.8",
            "requires_dist": ["a>=1"],
        },
        "releases": {
            "1.0": [
                {
                    "requires_python": ">=3.8",
                    "upload_time_iso_8601": "2024-01-01T00:00:00Z",
                }
            ],
            "1.1": [{"upload_time_iso_8601": "2024-02-01T00:00:00.123456Z"}],
        },
    }
    body.update(kw)
    return body


@pytest.mark.parametrize(
    "files",
    [
        5,
        1.5,
        True,
        "abc",
        {"a": 1},
        [None],
        [1, 2],
        ["x"],
        [[]],
        [{"requires_python": 5}],
    ],
)
def test_odd_file_lists_never_crash_parsing(files: Any) -> None:
    data = _store(FakeHttp(lambda u: Resp()))._parse_package_data(
        "p", _payload(releases={"1.0": files, "2.0": [{"filename": "ok"}]})
    )
    assert "2.0" in data.all_versions
    # Whatever the odd entry did, version queries stay answerable.
    data.get_python_compatible_versions("3.9")


@pytest.mark.parametrize("bad", [5, ["x"], {"a": 1}, True])
def test_non_string_requires_python_is_ignored(bad: Any) -> None:
    data = _store(FakeHttp(lambda u: Resp()))._parse_package_data(
        "p", _payload(releases={"1.0": [{"requires_python": bad}]})
    )
    assert data.is_python_compatible("1.0", "3.9") is True
    assert data.python_requirements.get("1.0") is None


@pytest.mark.parametrize(
    "info",
    [
        {"version": 5},
        {"version": ["1"]},
        {"requires_python": 3},
        {"requires_dist": "abc"},
        {"requires_dist": [5, None, "ok>=1"]},
        {"requires_dist": {"a": 1}},
        {"project_urls": ["x"], "home_page": 5},
        {"project_urls": {"a": 5, 3: "http://x"}},
    ],
)
def test_odd_info_fields_never_crash(info: Dict[str, Any]) -> None:
    data = _store(FakeHttp(lambda u: Resp()))._parse_package_data(
        "p", _payload(info=info)
    )
    assert data.latest_version is None or isinstance(data.latest_version, str)
    assert all(isinstance(d, str) for d in data.latest_dependencies)
    assert "a" not in data.latest_dependencies and "b" not in data.latest_dependencies


@pytest.mark.parametrize(
    "payload",
    [
        {"info": None, "releases": None},
        {},
        {"info": {}, "releases": {}},
        {"releases": {"1.0": None}},
    ],
)
def test_empty_payloads_give_empty_data(payload: Dict[str, Any]) -> None:
    data = _store(FakeHttp(lambda u: Resp()))._parse_package_data("P_k", payload)
    assert (
        data.name == "p-k" and data.all_versions == [] and data.latest_version is None
    )


@pytest.mark.parametrize(
    "payload", [{"releases": [1]}, {"info": [1], "releases": {}}, {"info": "x"}]
)
def test_wrong_container_types_raise_pypi_error(payload: Dict[str, Any]) -> None:
    with pytest.raises(PyPIError):
        _store(FakeHttp(lambda u: Resp()))._parse_package_data("p", payload)


@pytest.mark.parametrize("body", [[], "x", 5, None])
def test_non_dict_json_body_is_pypi_error(body: Any) -> None:
    store = _store(FakeHttp(lambda u: Resp(200, body)))
    with pytest.raises(PyPIError):
        asyncio.run(store.get_package_data("p"))


def test_upload_time_formats() -> None:
    def t(raw: Any) -> Optional[datetime]:
        d = _store(FakeHttp(lambda u: Resp()))._parse_package_data(
            "p", _payload(releases={"1.0": [{"upload_time_iso_8601": raw}]})
        )
        return d.upload_times["1.0"]

    utc = timezone.utc
    assert t("2024-01-01T00:00:00Z") == datetime(2024, 1, 1, tzinfo=utc)
    assert t("2024-01-01T05:00:00+05:00") == datetime(2024, 1, 1, tzinfo=utc)
    assert t("2024-01-01T00:00:00") == datetime(2024, 1, 1, tzinfo=utc)  # naive = UTC
    assert t("2024-01-01T00:00:00.123456Z") == datetime(
        2024, 1, 1, 0, 0, 0, 123456, utc
    )
    for junk in (None, "", "garbage", "2024-13-01T00:00:00Z", 12345, ["x"]):
        assert t(junk) is None


def test_earliest_upload_across_files_wins() -> None:
    files = [
        {"upload_time_iso_8601": "2024-03-01T00:00:00Z"},
        {"upload_time_iso_8601": "garbage"},
        {"upload_time_iso_8601": "2024-01-01T00:00:00Z"},
    ]
    d = _store(FakeHttp(lambda u: Resp()))._parse_package_data(
        "p", _payload(releases={"1.0": files})
    )
    assert d.upload_times["1.0"] == datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_phantom_yanked_and_invalid_versions_skipped() -> None:
    rel = {
        "1.0": [],
        "1.1": [{"yanked": True}, {"yanked": True}],
        "1.2": [{"yanked": True}, {"yanked": False}],
        "foo": [{}],
        "1.3": [{}],
        "1.4rc1": [{}],
    }
    d = _store(FakeHttp(lambda u: Resp()))._parse_package_data(
        "p", _payload(releases=rel)
    )
    assert d.all_versions == ["1.3", "1.2"]
    assert [v for v, _ in d.parsed_versions] == ["1.4rc1", "1.3", "1.2"]


def test_five_thousand_versions_parse_and_query_quickly() -> None:
    rel = {
        f"{i // 100}.{i % 100}.{i % 7}": [{"requires_python": f">=3.{6 + i % 6}"}]
        for i in range(5000)
    }
    store = _store(FakeHttp(lambda u: Resp()))
    import time

    start = time.perf_counter()
    d = store._parse_package_data("p", _payload(releases=rel))
    for _ in range(5):
        d.get_python_compatible_versions("3.9", major=3)
    assert time.perf_counter() - start < 5


@pytest.mark.asyncio
async def test_failures_are_not_cached_and_success_is() -> None:
    answers = [Resp(500), Resp(200, _payload())]
    http = FakeHttp(lambda u: answers.pop(0) if answers else Resp(200, _payload()))
    store = _store(http)
    with pytest.raises(PyPIError):
        await store.get_package_data("p")
    first = await store.get_package_data("p")
    assert await store.get_package_data("P") is first
    assert len(http.calls) == 2


@pytest.mark.asyncio
async def test_invalid_json_and_404_raise_and_are_retried() -> None:
    http = FakeHttp(lambda u: Resp(404))
    store = _store(http)
    for _ in range(2):
        with pytest.raises(PyPIError):
            await store.get_package_data("p")
    http2 = FakeHttp(lambda u: Resp(200, bad_json=True))
    with pytest.raises(PyPIError):
        await _store(http2).get_package_data("p")


@pytest.mark.asyncio
async def test_concurrent_callers_coalesce_and_limit_holds() -> None:
    http = FakeHttp(lambda u: Resp(200, _payload()), delay=0.01)
    store = _store(http, limit=3)
    names = [f"pkg{i}" for i in range(20)]
    results = await asyncio.gather(
        *(store.get_package_data(n) for n in names for _ in range(3))
    )
    assert len(http.calls) == 20
    assert http.peak <= 3
    assert len({id(r) for r in results}) == 20


@pytest.mark.asyncio
async def test_prefetch_swallows_errors_and_collapses_spellings() -> None:
    def handler(url: str) -> Any:
        return Resp(404) if "bad" in url else Resp(200, _payload())

    http = FakeHttp(handler)
    store = _store(http)
    await store.prefetch_packages(["Flask", "flask", "FLASK", "bad", "Fl_ask"])
    assert store.get_cached_package("flask") is not None
    assert store.get_cached_package("bad") is None
    assert len([c for c in http.calls if "bad" not in c]) == 2  # flask, fl-ask


@pytest.mark.asyncio
async def test_version_deps_404_cached_errors_not() -> None:
    state = {"n": 0}

    def handler(url: str) -> Any:
        state["n"] += 1
        if url.endswith("/1.0/json"):
            return Resp(404)
        if url.endswith("/2.0/json"):
            return (
                Resp(500)
                if state["n"] <= 2
                else Resp(200, {"info": {"requires_dist": ["x>=1", "y; extra=='e'"]}})
            )
        return RuntimeError("boom")

    http = FakeHttp(handler)
    store = _store(http)
    assert await store.get_version_dependencies("p", "1.0") == []
    assert await store.get_version_dependencies("p", "1.0") == []
    assert len(http.calls) == 1
    assert await store.get_version_dependencies("p", "2.0") == []  # transient: unknown
    assert await store.get_version_dependencies("p", "2.0") == [
        "x>=1"
    ]  # retried, now real
    assert await store.get_version_dependencies("p", "2.0") == ["x>=1"]
    assert await store.get_version_dependencies("p", "3.0") == []
    assert await store.get_version_dependencies("p", "3.0") == []
    assert len([c for c in http.calls if "/3.0/" in c]) == 2


@pytest.mark.asyncio
async def test_version_deps_garbage_body_not_cached() -> None:
    bodies: List[Any] = [[1], {"info": [1]}, {"info": {"requires_dist": ["ok>=1"]}}]
    http = FakeHttp(lambda u: Resp(200, bodies.pop(0)))
    store = _store(http)
    outs = [await store.get_version_dependencies("p", "9.9") for _ in range(3)]
    assert outs == [[], [], ["ok>=1"]]


@pytest.mark.asyncio
async def test_digests_cache_rules() -> None:
    good = "a" * 64
    bodies: List[Any] = [
        Resp(500),
        Resp(
            200, {"urls": [{"digests": {"sha256": "short"}}, "junk", {"digests": None}]}
        ),
        Resp(
            200,
            {
                "urls": [
                    {"digests": {"sha256": good.upper()}},
                    {"digests": {"sha256": "b" * 64}},
                ]
            },
        ),
    ]
    http = FakeHttp(lambda u: bodies.pop(0))
    store = _store(http)
    assert await store.get_version_digests("p", "1.0") is None
    assert await store.get_version_digests("p", "1.0") is None
    expected = sorted([good, "b" * 64])
    assert await store.get_version_digests("p", "1.0") == expected
    assert await store.get_version_digests("p", "1.0") == expected
    assert len(http.calls) == 3


@pytest.mark.asyncio
async def test_digests_use_cached_package_json_without_fetch() -> None:
    d = "c" * 64
    rel = {"1.0": [{"digests": {"sha256": d}}, {"digests": {"sha256": d}}]}
    http = FakeHttp(lambda u: Resp(200, _payload(releases=rel)))
    store = _store(http)
    await store.get_package_data("p")
    assert await store.get_version_digests("P", "1.0") == [d]
    assert len(http.calls) == 1


def test_urls_with_odd_names_are_quoted() -> None:
    http = FakeHttp(lambda u: Resp(404))
    store = _store(http)
    with pytest.raises(PyPIError):
        asyncio.run(store.get_package_data("a/../b?x#y"))
    assert (
        "/" not in http.calls[0].split("/pypi/", 1)[1].rsplit("/json", 1)[0]
        or "%2F" in http.calls[0]
    )
    assert "?" not in http.calls[0] and "#" not in http.calls[0]


def test_concurrent_limit_validation() -> None:
    for bad in (0, -1):
        with pytest.raises(ValueError):
            PyPIDataStore(object(), concurrent_limit=bad)  # type: ignore[arg-type]


def test_project_urls_keep_only_http() -> None:
    info = {
        "project_urls": {
            "Changelog": "https://x/c",
            "Bad": "javascript:alert(1)",
            "File": "file:///etc/passwd",
        },
        "home_page": "ftp://x",
    }
    d = _store(FakeHttp(lambda u: Resp()))._parse_package_data("p", _payload(info=info))
    assert d.project_urls == {"Changelog": "https://x/c"}
    assert d.release_links() == {"changelog": "https://x/c"}
    info = {"project_urls": None, "home_page": "https://home"}
    d = _store(FakeHttp(lambda u: Resp()))._parse_package_data("p", _payload(info=info))
    assert d.release_links() == {"homepage": "https://home"}
    assert timedelta(0) == timedelta(0)
