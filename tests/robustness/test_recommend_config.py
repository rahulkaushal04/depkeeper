"""Config parsing for min_age, python_version, versioning and per-package policy."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from depkeeper.config import PackagePolicy, load_config, parse_duration
from depkeeper.exceptions import ConfigError


def _load(tmp_path: Path, body: str) -> Any:
    path = tmp_path / "depkeeper.toml"
    path.write_text("[depkeeper]\n" + body, encoding="utf-8")
    return load_config(path)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("7d", timedelta(days=7)),
        ("7D", timedelta(days=7)),
        (" 7 d ", timedelta(days=7)),
        ("12h", timedelta(hours=12)),
        ("2w", timedelta(weeks=2)),
        ("30m", timedelta(minutes=30)),
        ("45s", timedelta(seconds=45)),
        ("0", timedelta(0)),
        ("0d", timedelta(0)),
        ("1.5d", timedelta(hours=36)),
        ("7", timedelta(days=7)),
        (7, timedelta(days=7)),
        (0, timedelta(0)),
        (0.5, timedelta(hours=12)),
        (999999999, timedelta(days=999999999)),
    ],
)
def test_duration_accepts(raw: Any, expected: timedelta) -> None:
    assert parse_duration(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        " ",
        "d",
        "-1",
        "-7d",
        "+7d",
        "7dd",
        "7 days",
        "1e3",
        "inf",
        "nan",
        "infd",
        ".5d",
        "5.d",
        "1,5d",
        "7y",
        "٧d",  # arabic-indic digit
        "７d",  # fullwidth digit
        "7 d\u2028x",
        "9" * 400 + "d",
        "99999999999999d",
        -1,
        -0.5,
        float("inf"),
        float("-inf"),
        float("nan"),
        10**30,
        True,
        False,
        None,
        [7],
        {"d": 7},
        b"7d",
    ],
)
def test_duration_rejects_with_value_error(raw: Any) -> None:
    with pytest.raises(ValueError):
        parse_duration(raw)


def test_duration_newline_suffix_is_tolerated_like_whitespace() -> None:
    assert parse_duration("7d\n") == timedelta(days=7)


@pytest.mark.parametrize("value", ['"7d"', "7", "0.5", '" 12H "'])
def test_min_age_toml_accepts(tmp_path: Path, value: str) -> None:
    assert _load(tmp_path, f"min_age = {value}\n").min_age is not None


@pytest.mark.parametrize(
    "value",
    [
        '"x"',
        "-1",
        "true",
        "inf",
        "nan",
        "[1]",
        "{a = 1}",
        "1979-05-27",
        '"7y"',
        "1e400",
    ],
)
def test_min_age_toml_rejects(tmp_path: Path, value: str) -> None:
    with pytest.raises(ConfigError, match="min_age"):
        _load(tmp_path, f"min_age = {value}\n")


@pytest.mark.parametrize("value", ['"3.9"', '"3.12"', '"3.8.5"', '"2.7"', '"10.0"'])
def test_python_version_accepts(tmp_path: Path, value: str) -> None:
    assert _load(tmp_path, f"python_version = {value}\n").python_version == value.strip(
        '"'
    )


@pytest.mark.parametrize(
    "value",
    [
        '"3"',
        '"3."',
        '".9"',
        '"3.9."',
        '"3.9.1.2"',
        '"3.9\\n"',
        '" 3.9"',
        '"3.9 "',
        '"٣.٩"',
        '"３.９"',
        '">=3.9"',
        '"3.9rc1"',
        '"3.x"',
        "3.9",
        "3",
        "true",
        '""',
    ],
)
def test_python_version_rejects(tmp_path: Path, value: str) -> None:
    with pytest.raises(ConfigError, match="python_version"):
        _load(tmp_path, f"python_version = {value}\n")


@pytest.mark.parametrize("mode", ["auto", "semver", "calver"])
def test_versioning_accepts(tmp_path: Path, mode: str) -> None:
    assert _load(tmp_path, f'versioning = "{mode}"\n').versioning == mode


@pytest.mark.parametrize(
    "value", ['"AUTO"', '"Calver"', '""', "1", "true", "[]", '"semver "']
)
def test_versioning_rejects(tmp_path: Path, value: str) -> None:
    with pytest.raises(ConfigError, match="versioning"):
        _load(tmp_path, f"versioning = {value}\n")


def test_every_policy_key_roundtrips(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        '[depkeeper.packages.Foo_Bar]\nmax_update = "minor"\nhold = true\nallow_prerelease = true\n'
        'versioning = "calver"\nignore = true\nallow_major = true\n',
    )
    assert cfg.packages == {
        "foo-bar": PackagePolicy("minor", True, True, "calver", True, True)
    }


def test_policy_defaults_are_inherit(tmp_path: Path) -> None:
    cfg = _load(tmp_path, "[depkeeper.packages.x]\n")
    assert cfg.packages["x"] == PackagePolicy()
    assert cfg.packages["x"].versioning is None and cfg.packages["x"].max_update is None


@pytest.mark.parametrize(
    "body,needle",
    [
        ('max_update = "major "', "max_update"),
        ('max_update = "month"', "max_update"),
        ('max_update = "PATCH"', "max_update"),
        ("max_update = 1", "max_update"),
        ("max_update = []", "max_update"),
        ('hold = "true"', "hold"),
        ("hold = 1", "hold"),
        ("ignore = 0", "ignore"),
        ("allow_prerelease = []", "allow_prerelease"),
        ("allow_major = 1.0", "allow_major"),
        ('versioning = "x"', "versioning"),
        ("versioning = 3", "versioning"),
        ("hold = true\nfrobnicate = 1", "Unknown keys"),
        ("Hold = true", "Unknown keys"),
    ],
)
def test_policy_rejects(tmp_path: Path, body: str, needle: str) -> None:
    with pytest.raises(ConfigError, match=needle):
        _load(tmp_path, f"[depkeeper.packages.x]\n{body}\n")


def test_packages_must_be_tables(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="packages"):
        _load(tmp_path, "packages = 3\n")
    with pytest.raises(ConfigError, match="packages.x"):
        _load(tmp_path, "[depkeeper.packages]\nx = true\n")


def test_duplicate_normalized_names_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="duplicates"):
        _load(
            tmp_path,
            '[depkeeper.packages."Foo_Bar"]\nhold = true\n[depkeeper.packages."foo.bar"]\nhold = true\n',
        )


def test_pyproject_tool_table_same_validation(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_text(
        '[tool.depkeeper]\nmin_age = "3d"\n[tool.depkeeper.packages.A]\nhold = true\n'
    )
    cfg = load_config(path)
    assert cfg.min_age == timedelta(days=3) and cfg.packages["a"].hold
    path.write_text('[tool.depkeeper]\nmin_age = "bad"\n')
    with pytest.raises(ConfigError):
        load_config(path)
