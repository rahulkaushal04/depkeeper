"""CLI-level tests for ``update``: --ignore, --max-update, exit 4, hashed dry-run."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import Any, List
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


def _pkg(name: str, cur: str, rec: str) -> Package:
    return Package(
        name=name, current_version=cur, latest_version=rec, recommended_version=rec
    )


STUB = Package(
    name="ghost", current_version="1.0", latest_version=None, recommended_version=None
)


def _run_update(
    tmp_path: Path, contents: str, packages: List[Package], *args: str
) -> Any:
    req = tmp_path / "requirements.txt"
    req.write_text(contents, encoding="utf-8")
    with ExitStack() as _stack:
        _stack.enter_context(
            mock.patch("depkeeper.commands.update.HTTPClient", _FakeHTTPClient)
        )
        _stack.enter_context(
            mock.patch("depkeeper.commands.update.PyPIDataStore", _FakeDataStore)
        )
        _stack.enter_context(
            mock.patch(
                "depkeeper.commands.update.VersionChecker", _fake_checker(packages)
            )
        )
        _stack.enter_context(
            mock.patch(
                "depkeeper.commands.update.DependencyAnalyzer", _fake_analyzer(None)
            )
        )
        result = _make_runner().invoke(
            cli, ["update", *args, str(req)], catch_exceptions=False
        )
    return result, req


PKGS = [
    _pkg("a", "1.0.0", "1.0.1"),
    _pkg("b", "1.0.0", "1.1.0"),
    _pkg("c", "1.0.0", "2.0.0"),
]
BODY = "a==1.0.0\nb==1.0.0\nc==1.0.0\n"


@pytest.mark.unit
class TestIgnore:
    def test_ignored_package_is_left_untouched(self, tmp_path: Path) -> None:
        result, req = _run_update(tmp_path, BODY, PKGS, "-y", "--ignore", "b")
        assert result.exit_code == 0
        assert req.read_text() == "a==1.0.1\nb==1.0.0\nc==2.0.0\n"

    def test_ignore_is_repeatable_and_name_normalised(self, tmp_path: Path) -> None:
        result, req = _run_update(
            tmp_path, BODY, PKGS, "-y", "--ignore", "A", "--ignore", "c"
        )
        assert result.exit_code == 0
        assert req.read_text() == "a==1.0.0\nb==1.1.0\nc==1.0.0\n"


@pytest.mark.unit
class TestMaxUpdate:
    @pytest.mark.parametrize(
        "level,expected",
        [
            ("patch", "a==1.0.1\nb==1.0.0\nc==1.0.0\n"),
            ("minor", "a==1.0.1\nb==1.1.0\nc==1.0.0\n"),
            ("major", "a==1.0.1\nb==1.1.0\nc==2.0.0\n"),
        ],
    )
    def test_skips_bumps_above_level(
        self, tmp_path: Path, level: str, expected: str
    ) -> None:
        result, req = _run_update(tmp_path, BODY, PKGS, "-y", "--max-update", level)
        assert result.exit_code == 0
        assert req.read_text() == expected

    def test_invalid_level_is_usage_error(self, tmp_path: Path) -> None:
        result, req = _run_update(tmp_path, BODY, PKGS, "-y", "--max-update", "huge")
        assert result.exit_code == 2
        assert req.read_text() == BODY


@pytest.mark.unit
class TestLookupFailure:
    def test_exit_4_and_file_unchanged(self, tmp_path: Path) -> None:
        body = "ghost==1.0\na==1.0.0\n"
        result, req = _run_update(tmp_path, body, [STUB, PKGS[0]], "-y")
        assert result.exit_code == 4
        assert "ghost" in result.stdout + result.stderr

    def test_exit_4_when_every_lookup_fails(self, tmp_path: Path) -> None:
        result, req = _run_update(tmp_path, "ghost==1.0\n", [STUB], "-y")
        assert result.exit_code == 4
        assert req.read_text() == "ghost==1.0\n"
        assert "up to date" not in (result.stdout + result.stderr).lower()


@pytest.mark.unit
class TestHashedDryRun:
    HASHED = (
        "a==1.0.0 \\\n    --hash=sha256:aaaa \\\n    --hash=sha256:bbbb\nb==1.0.0\n"
    )

    def test_dry_run_warns_and_does_not_write(self, tmp_path: Path) -> None:
        result, req = _run_update(tmp_path, self.HASHED, PKGS[:2], "--dry-run")
        out = result.stdout + result.stderr
        assert result.exit_code == 0
        assert "--allow-hash-removal" in out
        assert req.read_text() == self.HASHED

    def test_real_run_refuses_without_flag(self, tmp_path: Path) -> None:
        result, req = _run_update(tmp_path, self.HASHED, PKGS[:2], "-y")
        assert result.exit_code == 1
        assert req.read_text() == self.HASHED

    def test_allow_hash_removal_leaves_parseable_file(self, tmp_path: Path) -> None:
        """Hash continuation lines are removed with the pin."""
        from depkeeper.core.parser import RequirementsParser

        result, req = _run_update(
            tmp_path, self.HASHED, PKGS[:2], "-y", "--allow-hash-removal"
        )
        assert result.exit_code == 0
        assert "--hash" not in req.read_text()
        RequirementsParser().parse_file(req)
