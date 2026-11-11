"""Dependency environment markers follow the target Python, not the running one."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from click.testing import CliRunner

from depkeeper.cli import cli
from depkeeper.core.data_store import PyPIDataStore


class _Resp:
    def __init__(self, body: Any, status: int = 200) -> None:
        self.status_code = status
        self._body = body

    def json(self) -> Any:
        return self._body


class _Http:
    """Fake transport serving per-package JSON built from ``DB``."""

    def __init__(self, db: Dict[str, Dict[str, List[str]]]) -> None:
        self.db = db
        self.calls: List[str] = []

    async def __aenter__(self) -> "_Http":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def get(self, url: str, **_: Any) -> _Resp:
        self.calls.append(url)
        parts = url.split("/pypi/")[1].split("/")
        name = parts[0]
        versions = self.db[name]
        if len(parts) == 3:  # /pypi/name/version/json
            return _Resp({"info": {"requires_dist": versions[parts[1]]}})
        latest = sorted(versions)[-1]
        return _Resp(
            {
                "info": {
                    "name": name,
                    "version": latest,
                    "requires_dist": versions[latest],
                },
                "releases": {
                    v: [{"filename": f"{name}-{v}.whl", "requires_python": None}]
                    for v in versions
                },
            }
        )


def _deps(
    requires: List[str], target: Optional[str] = None, store: Any = None
) -> List[str]:
    store = store or PyPIDataStore(_Http({}), target_python=target)  # type: ignore[arg-type]
    return store._extract_dependencies({"requires_dist": requires})  # type: ignore[no-any-return]


class TestExtractDependencies:
    def test_xbug_repro_old_target(self) -> None:
        reqs = ["foo>=2; python_version < '3.9'", "bar>=1; python_version >= '3.9'"]
        assert _deps(reqs, "3.8") == ["foo>=2"]
        assert _deps(reqs, "3.12") == ["bar>=1"]

    def test_default_follows_running_interpreter(self) -> None:
        import sys

        reqs = ["foo; python_version < '3.9'"]
        expected = ["foo"] if sys.version_info < (3, 9) else []
        assert _deps(reqs) == expected

    def test_full_version_markers(self) -> None:
        reqs = ["a; python_full_version >= '3.8.1'", "b; python_full_version < '3.8.1'"]
        # target is X.Y.0: no patch level is assumed
        assert _deps(reqs, "3.8") == ["b"]
        assert _deps(reqs, "3.9") == ["a"]

    def test_equality_marker(self) -> None:
        reqs = ["x; python_version == '3.8'", "y; python_version != '3.8'"]
        assert _deps(reqs, "3.8") == ["x"]
        assert _deps(reqs, "3.10") == ["y"]

    def test_double_digit_minor_compares_numerically(self) -> None:
        assert _deps(["z; python_version >= '3.10'"], "3.9") == []
        assert _deps(["z; python_version >= '3.10'"], "3.10") == ["z"]

    def test_extras_still_dropped(self) -> None:
        reqs = ["e; extra == 'test'", "k; python_version >= '3.8' and extra == 'x'"]
        assert _deps(reqs, "3.8") == []

    def test_host_markers_unchanged(self) -> None:
        reqs = [
            "w; sys_platform == 'nonexistent-os'",
            "p; sys_platform != 'nonexistent-os'",
        ]
        assert _deps(reqs, "3.8") == ["p"]

    def test_invalid_marker_kept_as_before(self) -> None:
        assert _deps(["not a ( req; python_version < '3.9'"], "3.12") == ["not a ( req"]

    @pytest.mark.parametrize("bad", ["", "3", "abc", "3.x"])
    def test_unusable_target_falls_back_to_running(self, bad: str) -> None:
        assert _deps(["foo"], bad) == ["foo"]

    def test_patch_in_target_is_ignored(self) -> None:
        assert _deps(["a; python_version < '3.9'"], "3.8.5") == ["a"]


class TestStoreCache:
    def test_cache_is_per_store_target(self) -> None:
        db = {"app": {"1.0": ["lib>=2; python_version < '3.9'"]}}
        old = PyPIDataStore(_Http(db), target_python="3.8")  # type: ignore[arg-type]
        new = PyPIDataStore(_Http(db), target_python="3.12")  # type: ignore[arg-type]
        assert asyncio.run(old.get_version_dependencies("app", "1.0")) == ["lib>=2"]
        assert asyncio.run(new.get_version_dependencies("app", "1.0")) == []
        pkg = asyncio.run(old.get_package_data("app"))
        assert pkg.latest_dependencies == ["lib>=2"]


_DB = {
    "app": {"1.0": ["lib>=2; python_version < '3.9'"]},
    "lib": {"1.0": [], "2.0": []},
}


def _check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, py: str) -> Dict[str, Any]:
    import depkeeper.commands.check as check_mod

    monkeypatch.setattr(check_mod, "HTTPClient", lambda: _Http(_DB))
    monkeypatch.chdir(tmp_path)
    req = tmp_path / "requirements.txt"
    req.write_text("app==1.0\nlib<2\n")
    res = CliRunner().invoke(
        cli,
        ["check", str(req), "--python-version", py, "--format", "json"],
    )
    return {"out": res.output, "code": res.exit_code}


def test_cli_python_version_changes_conflict_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = _check(tmp_path, monkeypatch, "3.8")
    new = _check(tmp_path, monkeypatch, "3.12")
    assert old["code"] == new["code"] == 0

    def lib_row(out: str) -> Dict[str, Any]:
        rows = json.loads(out[out.index("[") :])  # logs may precede the JSON
        return next(r for r in rows if r["name"] == "lib")

    held, free = lib_row(old["out"]), lib_row(new["out"])
    assert held["conflict_held"] is True
    assert [c["required_spec"] for c in held["conflicts"]] == [">=2"]
    assert "conflict_held" not in free and "conflicts" not in free
