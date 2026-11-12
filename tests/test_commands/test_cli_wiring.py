"""CLI wiring of library features: --python-version, --min-age, calver, policy markers."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import pytest

from depkeeper.cli import cli
from depkeeper.commands import _report
from depkeeper.config import DepKeeperConfig
from depkeeper.models import Package
from tests.test_commands.test_check_output_streams import (
    _FakeDataStore,
    _FakeHTTPClient,
    _fake_analyzer,
    _isolated_console,  # noqa: F401  (autouse fixture)
    _make_runner,
    _run_check,
)
from tests.test_commands.test_update_cli_options import _run_update


def _pkg(name: str = "a", cur: str = "1.0.0", rec: str = "1.0.1", **kw: Any) -> Package:
    return Package(
        name=name,
        current_version=cur,
        latest_version=rec,
        recommended_version=rec,
        **kw,
    )


def _recording_checker(packages: List[Package], seen: Dict[str, Any]) -> Any:
    class C:
        @classmethod
        def from_config(cls, data_store: Any, config: Any, **overrides: Any) -> Any:
            seen.update(overrides)
            seen["config"] = config
            return cls()

        async def check_packages(self, requirements: Any) -> List[Package]:
            return list(packages)

    return C


def _invoke(
    cmd: str,
    tmp_path: Path,
    args: List[str],
    seen: Dict[str, Any],
    contents: str = "a==1.0.0\n",
) -> Any:
    req = tmp_path / "requirements.txt"
    req.write_text(contents)
    base = f"depkeeper.commands.{cmd}"
    with ExitStack() as _stack:
        _stack.enter_context(mock.patch(f"{base}.HTTPClient", _FakeHTTPClient))
        _stack.enter_context(mock.patch(f"{base}.PyPIDataStore", _FakeDataStore))
        _stack.enter_context(
            mock.patch(f"{base}.VersionChecker", _recording_checker([_pkg()], seen))
        )
        _stack.enter_context(
            mock.patch(f"{base}.DependencyAnalyzer", _fake_analyzer(None))
        )
        return _make_runner().invoke(
            cli, [cmd, *args, str(req)], catch_exceptions=False
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "spec,expected",
    [
        (">=3.9", "3.9"),
        (">3.8", "3.9"),
        ("~=3.10", "3.10"),
        ("==3.11.*", "3.11"),
        (">=3.8,<3.12", "3.8"),
        ("3.10", "3.10"),
        ("garbage", None),
    ],
)
def test_minimum_python(spec: str, expected: Any) -> None:
    assert _report.minimum_python(spec) == expected


@pytest.mark.unit
class TestPythonPrecedence:
    class _Adapter:
        def __init__(self, spec: str) -> None:
            self.spec = spec

        def requires_python(self, path: Path) -> str:
            return self.spec

    def _resolve(self, flag: Any, cfg: Any, tmp_path: Path, spec: str = ">=3.9") -> Any:
        f = tmp_path / "requirements.txt"
        f.write_text("a\n")
        with mock.patch(
            "depkeeper.core.sources.get_adapter", lambda p: self._Adapter(spec)
        ):
            return _report.resolve_target_python(flag, cfg, f)

    def test_flag_beats_config_beats_adapter(self, tmp_path: Path) -> None:
        cfg = DepKeeperConfig(python_version="3.10")
        assert self._resolve("3.8", cfg, tmp_path) == ("3.8", "--python-version")
        assert self._resolve(None, cfg, tmp_path) == ("3.10", "config python_version")
        v, src = self._resolve(None, DepKeeperConfig(), tmp_path)
        assert (v, "requires-python" in src) == ("3.9", True)

    def test_falls_back_to_running_interpreter(self, tmp_path: Path) -> None:
        assert self._resolve(None, DepKeeperConfig(), tmp_path, spec="") == (
            None,
            "running interpreter",
        )


@pytest.mark.unit
@pytest.mark.parametrize("cmd", ["check", "update"])
class TestFlagsReachChecker:
    def test_flags_become_overrides(self, tmp_path: Path, cmd: str) -> None:
        seen: Dict[str, Any] = {}
        extra = ["--dry-run"] if cmd == "update" else []
        r = _invoke(
            cmd, tmp_path, ["--python-version", "3.8", "--min-age", "7d", *extra], seen
        )
        assert r.exit_code == 0, r.output
        assert seen["target_python"] == "3.8"
        assert seen["min_age"] == timedelta(days=7)

    @pytest.mark.parametrize(
        "flag,value", [("--python-version", "three"), ("--min-age", "soon")]
    )
    def test_bad_values_are_usage_errors(
        self, tmp_path: Path, cmd: str, flag: str, value: str
    ) -> None:
        r = _invoke(cmd, tmp_path, [flag, value], {})
        assert r.exit_code == 2

    def test_config_python_version_used(
        self, tmp_path: Path, cmd: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "depkeeper.toml").write_text(
            '[depkeeper]\npython_version = "3.10"\n'
        )
        monkeypatch.chdir(tmp_path)
        seen: Dict[str, Any] = {}
        extra = ["--dry-run"] if cmd == "update" else []
        assert _invoke(cmd, tmp_path, extra, seen).exit_code == 0
        assert seen["target_python"] == "3.10"


CALVER = dict(versioning="calver")


@pytest.mark.unit
class TestCalverGating:
    def _cal(self, cur: str, rec: str) -> Package:
        return _pkg("cal", cur, rec, **CALVER)

    @pytest.mark.parametrize("level,code", [("minor", 3), ("major", 0), ("updates", 3)])
    def test_year_bump_is_minor_for_fail_on(
        self, tmp_path: Path, level: str, code: int
    ) -> None:
        r = _run_check(
            tmp_path,
            ["check", "--fail-on", level],
            packages=[self._cal("2023.1.0", "2024.2.0")],
        )
        assert r.exit_code == code

    def test_calver_month_counts_as_minor_for_max_update(self, tmp_path: Path) -> None:
        pkgs = [self._cal("2024.1.0", "2024.5.0")]
        _, req = _run_update(
            tmp_path, "cal==2024.1.0\n", pkgs, "-y", "--max-update", "patch"
        )
        assert req.read_text() == "cal==2024.1.0\n"
        _, req = _run_update(
            tmp_path, "cal==2024.1.0\n", pkgs, "-y", "--max-update", "minor"
        )
        assert req.read_text() == "cal==2024.5.0\n"

    def test_table_shows_calver_label(self, tmp_path: Path) -> None:
        r = _run_check(
            tmp_path, ["check"], packages=[self._cal("2023.1.0", "2024.2.0")]
        )
        assert "year" in r.stdout


@pytest.mark.unit
class TestPolicyAndAgeOutput:
    def _held(self) -> Package:
        return _pkg("pinned", "1.0.0", "1.0.0", held=True)

    @pytest.mark.parametrize("fmt", ["table", "simple"])
    def test_held_marker(self, tmp_path: Path, fmt: str) -> None:
        r = _run_check(tmp_path, ["check", "-f", fmt], packages=[self._held()])
        assert "HELD" in r.stdout
        if fmt == "table":
            assert "held by policy: pinned" in r.stdout

    def test_ignored_marker(self, tmp_path: Path) -> None:
        r = _run_check(
            tmp_path,
            ["check", "-f", "simple"],
            packages=[_pkg("x", "1", "1", ignored=True)],
        )
        assert "[IGNORED]" in r.stdout

    def test_age_and_cooldown_notice(self, tmp_path: Path, monkeypatch) -> None:
        # The table is asserted for content, so give it room: a narrow terminal
        # switches to the compact layout, which wraps "1.0.2 held".
        monkeypatch.setenv("COLUMNS", "200")
        released = datetime.now(timezone.utc) - timedelta(days=12)
        p = _pkg(
            "a",
            "1.0.0",
            "1.0.1",
            recommended_released=released,
            cooldown_skipped="1.0.2",
        )
        r = _run_check(tmp_path, ["check", "-f", "simple"], packages=[p])
        assert "released 12 days ago" in r.stdout
        assert "1.0.2 withheld" in r.stdout
        t = _run_check(tmp_path, ["check"], packages=[p])
        assert "min_age cooldown" in t.stdout
        assert "12d old" in t.stdout
        assert "1.0.2 held" in t.stdout

    def test_multi_file_shows_source(self, tmp_path: Path) -> None:
        (tmp_path / "requirements-dev.txt").write_text("b==1.0.0\n")
        pkgs = [_pkg("a"), _pkg("b")]
        r = _run_check(
            tmp_path, ["check", "-f", "simple", str(tmp_path)], packages=pkgs
        )
        assert r.exit_code == 0, r.output
        assert "Source:" in r.stdout and "requirements-dev.txt" in r.stdout
        single = _run_check(
            tmp_path,
            ["check", "-f", "simple", str(tmp_path / "requirements.txt")],
            packages=[_pkg("a")],
        )
        assert "Source:" not in single.stdout


@pytest.mark.unit
@pytest.mark.parametrize("cmd,extra", [("check", []), ("update", ["--dry-run"])])
def test_target_python_reaches_the_analyzer(
    tmp_path: Path, cmd: str, extra: Any
) -> None:
    got: Dict[str, Any] = {}

    class Rec(_fake_analyzer(None)):  # type: ignore[misc]
        def __init__(self, *a: Any, **kw: Any) -> None:
            got.update(kw)

    req = tmp_path / "requirements.txt"
    req.write_text("a==1.0.0\n")
    base = f"depkeeper.commands.{cmd}"
    with ExitStack() as _stack:
        _stack.enter_context(mock.patch(f"{base}.HTTPClient", _FakeHTTPClient))
        _stack.enter_context(mock.patch(f"{base}.PyPIDataStore", _FakeDataStore))
        _stack.enter_context(
            mock.patch(f"{base}.VersionChecker", _recording_checker([_pkg()], {}))
        )
        _stack.enter_context(mock.patch(f"{base}.DependencyAnalyzer", Rec))
        _make_runner().invoke(
            cli,
            [cmd, *extra, "--python-version", "3.8", str(req)],
            catch_exceptions=False,
        )
    # behaviour of a 3.8 target inside the analyzer: tests/test_core/test_analyzer_policy.py
    assert got["target_python"] == "3.8"
    assert got["checker"] is not None  # cooldown/policy reuse in conflict resolution
