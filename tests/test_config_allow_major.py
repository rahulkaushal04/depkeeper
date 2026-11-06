"""``allow_major`` per-package policy parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from depkeeper.config import load_config
from depkeeper.exceptions import ConfigError


def test_allow_major_parsed_and_name_normalised(tmp_path: Path) -> None:
    f = tmp_path / "depkeeper.toml"
    f.write_text('[depkeeper.packages."Django_X"]\nallow_major = true\n')
    cfg = load_config(f)
    assert cfg.packages["django-x"].allow_major is True


def test_allow_major_defaults_false(tmp_path: Path) -> None:
    f = tmp_path / "depkeeper.toml"
    f.write_text("[depkeeper.packages.a]\nhold = true\n")
    assert load_config(f).packages["a"].allow_major is False


def test_allow_major_must_be_bool(tmp_path: Path) -> None:
    f = tmp_path / "depkeeper.toml"
    f.write_text('[depkeeper.packages.a]\nallow_major = "yes"\n')
    with pytest.raises(ConfigError):
        load_config(f)
