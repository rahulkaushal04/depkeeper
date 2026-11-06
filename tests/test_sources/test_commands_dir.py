"""check/update accept a directory (discovery)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from depkeeper.cli import cli


def test_update_missing_default_is_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    res = CliRunner().invoke(cli, ["update", "--dry-run"])
    assert res.exit_code == 2


def test_check_empty_directory_exits_1(tmp_path: Path) -> None:
    res = CliRunner().invoke(cli, ["check", str(tmp_path)])
    assert res.exit_code == 1
    assert "No supported dependency files" in res.output
