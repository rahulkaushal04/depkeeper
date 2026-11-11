"""``check --format markdown`` and ``update --format markdown`` (PR-body output)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from depkeeper.models import Package
from depkeeper.models.conflict import Conflict
from tests.test_commands.test_check_output_streams import _isolated_console, _run_check  # noqa: F401
from tests.test_commands.test_update_cli_options import STUB, _run_update


def _pkg(name: str, cur: str, rec: str, **kw: Any) -> Package:
    return Package(
        name=name,
        current_version=cur,
        latest_version=rec,
        recommended_version=rec,
        **kw,
    )


def _md(tmp_path: Path, pkgs: Any, *args: str, contents: str = "a==1.0.0\n") -> Any:
    return _run_check(
        tmp_path, ["check", "-f", "markdown", *args], packages=pkgs, contents=contents
    )


@pytest.mark.unit
class TestCheckMarkdown:
    def test_grouped_by_update_type_with_links_and_age(self, tmp_path: Path) -> None:
        released = datetime.now(timezone.utc) - timedelta(days=3)
        pkgs = [
            _pkg("a", "1.0.0", "2.0.0"),
            _pkg("b", "1.0.0", "1.0.1", recommended_released=released),
        ]
        r = _md(tmp_path, pkgs)
        assert r.exit_code == 0
        out = r.stdout
        assert out.index("### Major updates") < out.index("### Patch updates")
        assert "| `b` | 1.0.0 | 1.0.1 | 3 days ago |" in out
        assert "[PyPI](https://pypi.org/project/b/)" in out
        assert "[WARNING]" not in out  # status goes to stderr

    def test_calver_labels(self, tmp_path: Path) -> None:
        r = _md(tmp_path, [_pkg("cal", "2023.1.0", "2024.2.0", versioning="calver")])
        assert "### Year updates (calver)" in r.stdout

    def test_policy_failures_and_conflicts(self, tmp_path: Path) -> None:
        conflict = Conflict(
            source_package="x",
            target_package="a",
            required_spec=">=2",
            conflicting_version="1.0.0",
        )
        a = _pkg("a", "1.0.0", "1.0.0")
        a.conflicts.append(conflict)
        pkgs = [
            a,
            _pkg("h", "1.0.0", "1.0.0", held=True),
            _pkg("c", "1.0.0", "1.0.1", cooldown_skipped="1.0.2"),
            STUB,
        ]
        r = _md(tmp_path, pkgs)
        out = r.stdout
        assert "### Held by policy" in out and "`h` stays on 1.0.0" in out
        assert "### Cooldown" in out and "1.0.2 withheld" in out
        assert "### Conflicts" in out
        assert "### Lookup failures" in out and "`ghost`" in out
        assert r.exit_code == 4

    def test_up_to_date_and_empty(self, tmp_path: Path) -> None:
        assert (
            "All packages are up to date."
            in _md(tmp_path, [_pkg("a", "1", "1")]).stdout
        )
        r = _md(tmp_path, [_pkg("a", "1", "1")], "--outdated-only")
        assert "All packages are up to date." in r.stdout

    def test_pipes_escaped(self) -> None:
        from depkeeper.commands._report import _cell

        assert _cell("a|b") == "a\\|b"


@pytest.mark.unit
class TestUpdateMarkdown:
    def test_dry_run_lists_changes_and_skips(self, tmp_path: Path) -> None:
        pkgs = [
            _pkg("a", "1.0.0", "1.0.1"),
            _pkg("b", "1.0.0", "1.1.0"),
            _pkg("c", "1.0.0", "2.0.0"),
        ]
        r, req = _run_update(
            tmp_path,
            "a==1.0.0\nb==1.0.0\nc==1.0.0\n",
            pkgs,
            "--dry-run",
            "-f",
            "markdown",
            "--max-update",
            "minor",
        )
        assert r.exit_code == 0
        assert "## depkeeper updates (dry run)" in r.stdout
        assert "### Minor updates" in r.stdout and "### Patch updates" in r.stdout
        assert "`c`: update exceeds --max-update minor" in r.stdout
        assert "Dry run" not in r.stdout  # diagnostics on stderr
        assert req.read_text() == "a==1.0.0\nb==1.0.0\nc==1.0.0\n"

    def test_applied_with_yes(self, tmp_path: Path) -> None:
        r, req = _run_update(
            tmp_path,
            "a==1.0.0\n",
            [_pkg("a", "1.0.0", "1.0.1")],
            "-y",
            "-f",
            "markdown",
        )
        assert r.exit_code == 0
        assert req.read_text() == "a==1.0.1\n"
        assert r.stdout.startswith("## depkeeper updates\n")
        assert "| `a` | 1.0.0 | 1.0.1 |" in r.stdout

    def test_requires_yes_or_dry_run(self, tmp_path: Path) -> None:
        r, req = _run_update(
            tmp_path, "a==1.0.0\n", [_pkg("a", "1.0.0", "1.0.1")], "-f", "markdown"
        )
        assert r.exit_code == 2
        assert req.read_text() == "a==1.0.0\n"

    def test_nothing_to_update(self, tmp_path: Path) -> None:
        r, _ = _run_update(
            tmp_path,
            "a==1.0.0\n",
            [_pkg("a", "1.0.0", "1.0.0")],
            "-y",
            "-f",
            "markdown",
        )
        assert r.exit_code == 0
        assert "All packages are up to date." in r.stdout
