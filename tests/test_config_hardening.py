"""Edge cases for ``min_age`` parsing and config discovery boundaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from depkeeper.config import discover_config_file, parse_duration


@pytest.mark.parametrize(
    "raw", [float("inf"), float("nan"), 1e30, "99999999999d", "1e400", "٣d", 10**12]
)
def test_parse_duration_extreme_is_value_error(raw: Any) -> None:
    with pytest.raises(ValueError):
        parse_duration(raw)


def test_parse_duration_uppercase_unit() -> None:
    from datetime import timedelta

    assert parse_duration("7D") == timedelta(days=7)


def test_min_age_overflow_in_file_is_config_error(tmp_path: Path) -> None:
    from depkeeper.config import load_config
    from depkeeper.exceptions import ConfigError

    f = tmp_path / "depkeeper.toml"
    f.write_text("[depkeeper]\nmin_age = 1e30\n")
    with pytest.raises(ConfigError):
        load_config(f)


def test_discovery_stops_at_home_without_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    work = home / "proj" / "sub"
    work.mkdir(parents=True)
    (tmp_path / "depkeeper.toml").write_text(
        "[depkeeper]\nfail_on='none'\n"
    )  # above $HOME
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(work)
    assert discover_config_file() is None


def test_discovery_still_finds_config_inside_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    work = home / "proj" / "sub"
    work.mkdir(parents=True)
    cfg = home / "proj" / "depkeeper.toml"
    cfg.write_text("[depkeeper]\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(work)
    assert discover_config_file() == cfg
