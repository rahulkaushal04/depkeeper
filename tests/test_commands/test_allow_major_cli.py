"""``--allow-major`` on check/update: wiring, warnings, reporting, gates."""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import pytest

from depkeeper.cli import cli
from depkeeper.models import Package
from tests.test_commands.test_check_output_streams import (
    _FakeDataStore,
    _FakeHTTPClient,
    _fake_analyzer,
    _fake_checker,
    _isolated_console,  # noqa: F401  (autouse fixture)
    _make_runner,
)


def _run(
    tmp_path: Path,
    cmd: str,
    packages: List[Package],
    *args: str,
    body: str = "a==1.0.0\n",
) -> Any:
    """Invoke *cmd*; returns (result, requirements file, checker overrides)."""
    seen: Dict[str, Any] = {}
    base = _fake_checker(packages)

    class Recording(base):  # type: ignore[valid-type, misc]
        @classmethod
        def from_config(cls, data_store: Any, config: Any, **overrides: Any) -> Any:
            seen.update(overrides)
            return super().from_config(data_store, config, **overrides)

    req = tmp_path / "requirements.txt"
    req.write_text(body, encoding="utf-8")
    mod = f"depkeeper.commands.{cmd}"
    with ExitStack() as stack:
        stack.enter_context(mock.patch(f"{mod}.HTTPClient", _FakeHTTPClient))
        stack.enter_context(mock.patch(f"{mod}.PyPIDataStore", _FakeDataStore))
        stack.enter_context(mock.patch(f"{mod}.VersionChecker", Recording))
        stack.enter_context(
            mock.patch(f"{mod}.DependencyAnalyzer", _fake_analyzer(None))
        )
        result = _make_runner().invoke(
            cli, [cmd, *args, str(req)], catch_exceptions=False
        )
    return result, req, seen


def _pkg(rec: str = "2.0.0", major: str = "") -> Package:
    p = Package(
        name="a",
        current_version="1.0.0",
        latest_version="3.0.0",
        recommended_version=rec,
    )
    p.major_available = major or None
    return p


@pytest.mark.unit
@pytest.mark.parametrize("cmd", ["check", "update"])
def test_option_repeatable_and_forwarded(tmp_path: Path, cmd: str) -> None:
    extra = ["-y", "--dry-run"] if cmd == "update" else []
    _, _, seen = _run(
        tmp_path, cmd, [_pkg()], *extra, "--allow-major", "A", "--allow-major", "*"
    )
    assert sorted(seen["allow_major"]) == ["*", "a"]


@pytest.mark.unit
def test_no_option_forwards_nothing(tmp_path: Path) -> None:
    _, _, seen = _run(tmp_path, "check", [_pkg()])
    assert not seen.get("allow_major")


@pytest.mark.unit
@pytest.mark.parametrize("cmd", ["check", "update"])
def test_unknown_name_warns_once(tmp_path: Path, cmd: str) -> None:
    extra = ["-y", "--dry-run"] if cmd == "update" else []
    result, _, _ = _run(
        tmp_path,
        cmd,
        [_pkg()],
        *extra,
        "--allow-major",
        "ghost",
        "--allow-major",
        "ghost",
    )
    out = result.stdout + result.stderr
    assert out.count("--allow-major ghost") == 1
    assert "not in" in out


@pytest.mark.unit
def test_star_and_known_name_do_not_warn(tmp_path: Path) -> None:
    result, _, _ = _run(
        tmp_path, "check", [_pkg()], "--allow-major", "*", "--allow-major", "A"
    )
    assert "--allow-major" not in result.stdout + result.stderr


@pytest.mark.unit
def test_update_warns_when_major_applied(tmp_path: Path) -> None:
    result, req, _ = _run(tmp_path, "update", [_pkg()], "-y", "--allow-major", "a")
    assert req.read_text() == "a==2.0.0\n"
    out = result.stdout + result.stderr
    assert "1 major upgrade(s) applied: a. Run --verify and your tests." in out


@pytest.mark.unit
def test_update_no_major_warning_for_minor(tmp_path: Path) -> None:
    result, _, _ = _run(tmp_path, "update", [_pkg("1.1.0")], "-y")
    assert "major upgrade" not in result.stdout + result.stderr


@pytest.mark.unit
def test_update_max_update_caps_major_and_reports_it(tmp_path: Path) -> None:
    result, req, _ = _run(
        tmp_path,
        "update",
        [_pkg()],
        "-y",
        "--max-update",
        "minor",
        "--allow-major",
        "a",
    )
    assert req.read_text() == "a==1.0.0\n"
    assert "major available: a 2.0.0" in result.stdout + result.stderr


@pytest.mark.unit
def test_check_table_note_and_json(tmp_path: Path) -> None:
    pkgs = [_pkg("1.5.0", major="2.0.0")]
    result, _, _ = _run(tmp_path, "check", pkgs)
    assert "major available: a 2.0.0 (use --allow-major a)" in (
        result.stdout + result.stderr
    )
    result, _, _ = _run(tmp_path, "check", pkgs, "--format", "json")
    assert json.loads(result.stdout)[0]["major_available"] == "2.0.0"
    result, _, _ = _run(tmp_path, "check", pkgs, "--format", "json-v2")
    assert json.loads(result.stdout)["packages"][0]["major_available"] == "2.0.0"


@pytest.mark.unit
def test_check_markdown_section(tmp_path: Path) -> None:
    result, _, _ = _run(
        tmp_path, "check", [_pkg("1.5.0", major="2.0.0")], "--format", "markdown"
    )
    assert "Major updates available (not applied)" in result.stdout
    assert "`a`: 2.0.0" in result.stdout


@pytest.mark.unit
def test_no_note_without_major_available(tmp_path: Path) -> None:
    result, _, _ = _run(tmp_path, "check", [_pkg("1.5.0")], "--format", "json")
    assert "major_available" not in result.stdout


@pytest.mark.unit
def test_fail_on_major_trips_on_proposed_major_not_on_available(tmp_path: Path) -> None:
    r, _, _ = _run(tmp_path, "check", [_pkg("2.0.0")], "--fail-on", "major")
    assert r.exit_code == 3
    r, _, _ = _run(
        tmp_path, "check", [_pkg("1.5.0", major="2.0.0")], "--fail-on", "major"
    )
    assert r.exit_code == 0


@pytest.mark.unit
def test_capped_major_hint_says_raise_cap(tmp_path: Path) -> None:
    p = _pkg("1.5.0", major="2.0.0")
    p.major_capped = True
    result, _, _ = _run(tmp_path, "check", [p])
    out = result.stdout + result.stderr
    assert "major available: a 2.0.0" in out
    assert "use --allow-major" not in out
    assert "--max-update" in out


@pytest.mark.unit
def test_update_forwards_cli_cap_to_checker(tmp_path: Path) -> None:
    _, _, seen = _run(
        tmp_path,
        "update",
        [_pkg()],
        "-y",
        "--max-update",
        "minor",
        "--allow-major",
        "a",
    )
    assert seen["max_update"] == "minor"


@pytest.mark.unit
def test_dry_run_says_would_apply(tmp_path: Path) -> None:
    result, _, _ = _run(tmp_path, "update", [_pkg()], "--dry-run", "--allow-major", "a")
    out = result.stdout + result.stderr
    assert "1 major upgrade(s) would be applied: a" in out
    assert "major upgrade(s) applied" not in out
