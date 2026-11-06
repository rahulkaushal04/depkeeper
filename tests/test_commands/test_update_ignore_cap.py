"""``update``: ignored failed lookups, config ``ignore``, capped-update report."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_commands.test_update_cli_options import (
    BODY,
    PKGS,
    STUB,
    _isolated_console,  # noqa: F401  (autouse fixture)
    _run_update,
)


@pytest.mark.unit
def test_ignored_failed_lookup_is_not_exit_4(tmp_path: Path) -> None:
    result, _ = _run_update(
        tmp_path, "ghost==1.0\na==1.0.0\n", [STUB, PKGS[0]], "-y", "--ignore", "ghost"
    )
    assert result.exit_code == 0


@pytest.mark.unit
def test_config_ignore_is_honoured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "depkeeper.toml").write_text('[depkeeper]\nignore = ["b"]\n')
    monkeypatch.chdir(tmp_path)
    result, req = _run_update(tmp_path, BODY, PKGS, "-y")
    assert result.exit_code == 0
    assert req.read_text() == "a==1.0.1\nb==1.0.0\nc==2.0.0\n"


@pytest.mark.unit
def test_all_updates_capped_is_not_reported_up_to_date(tmp_path: Path) -> None:
    result, req = _run_update(
        tmp_path, "c==1.0.0\n", [PKGS[2]], "-y", "--max-update", "patch"
    )
    out = result.stdout + result.stderr
    assert "up to date" not in out.lower()
    assert "1 update(s) skipped by --max-update patch" in out
    assert req.read_text() == "c==1.0.0\n"
