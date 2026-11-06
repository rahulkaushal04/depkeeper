"""Adversarial tests for source discovery, adapter selection and target resolution."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from depkeeper.core.sources import (
    default_target,
    get_adapter,
    parse_targets,
    resolve_targets,
)
from depkeeper.core.sources.registry import discover
from depkeeper.exceptions import DepKeeperError

PYPROJECT = '[project]\ndependencies = ["tomlpkg>=1.0"]\n'
ENV = "dependencies:\n  - condapkg=1.0\n"


def w(root: Path, name: str, text: str = "") -> Path:
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_discovery_order_is_adapter_then_sorted_name(tmp_path: Path) -> None:
    w(tmp_path, "environment.yml", ENV)
    w(tmp_path, "pyproject.toml", PYPROJECT)
    w(tmp_path, "requirements-b.txt", "b\n")
    w(tmp_path, "requirements.txt", "a\n")
    w(tmp_path, "environment.yaml", ENV)
    assert [p.name for p in discover(tmp_path)] == [
        "requirements-b.txt",
        "requirements.txt",
        "pyproject.toml",
        "environment.yml",
        "environment.yaml",
    ]


def test_files_without_dependencies_are_not_discovered(tmp_path: Path) -> None:
    w(tmp_path, "pyproject.toml", "[tool.black]\nline-length = 88\n")
    w(tmp_path, "environment.yml", "name: x\nchannels: [a]\n")
    w(tmp_path, "notes.txt", "x\n")
    w(tmp_path, "ci.yml", "jobs: {}\n")
    assert [p.name for p in discover(tmp_path)] == ["environment.yml"]


def test_nothing_found_error_names_directory(tmp_path: Path) -> None:
    w(tmp_path, "pyproject.toml", "[tool.black]\n")
    with pytest.raises(DepKeeperError, match="No supported dependency files"):
        resolve_targets(tmp_path)


def test_nested_directories_are_not_scanned(tmp_path: Path) -> None:
    w(tmp_path, "sub/pyproject.toml", PYPROJECT)
    w(tmp_path, "sub/requirements.txt", "a\n")
    assert discover(tmp_path) == []


def test_directories_and_broken_links_named_like_files_are_ignored(
    tmp_path: Path,
) -> None:
    (tmp_path / "requirements-dir.txt").mkdir()
    os.symlink(tmp_path / "missing", tmp_path / "requirements-broken.txt")
    (tmp_path / "pyproject.toml").mkdir()
    assert discover(tmp_path) == []


def test_symlinked_file_is_discovered_once(tmp_path: Path) -> None:
    real = w(tmp_path, "requirements.txt", "a==1\n")
    os.symlink(real, tmp_path / "requirements-link.txt")
    assert [p.name for p in discover(tmp_path)] == [
        "requirements-link.txt",
        "requirements.txt",
    ]
    assert len(parse_targets(tmp_path)) == 2


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="needs chmod")
def test_unreadable_files_do_not_break_discovery(tmp_path: Path) -> None:
    bad = w(tmp_path, "pyproject.toml", PYPROJECT)
    w(tmp_path, "environment.yml", ENV)
    os.chmod(bad, 0)
    try:
        assert [p.name for p in discover(tmp_path)] == ["environment.yml"]
    finally:
        os.chmod(bad, 0o644)


def test_broken_pyproject_with_dependency_sections_is_discovered_and_reported(
    tmp_path: Path,
) -> None:
    w(tmp_path, "pyproject.toml", '[project]\ndependencies = ["a"\n')
    assert [p.name for p in discover(tmp_path)] == ["pyproject.toml"]
    with pytest.raises(DepKeeperError, match="Invalid TOML"):
        parse_targets(tmp_path)


def test_one_broken_file_in_directory_names_that_file(tmp_path: Path) -> None:
    w(tmp_path, "requirements.txt", "a==1\n")
    w(tmp_path, "environment.yml", "dependencies:\n\t- x\n")
    with pytest.raises(DepKeeperError, match=r"environment\.yml.*Tabs"):
        parse_targets(tmp_path)


def test_same_package_in_several_files_keeps_provenance(tmp_path: Path) -> None:
    w(tmp_path, "requirements.txt", "tomlpkg==1.0\n")
    w(tmp_path, "pyproject.toml", PYPROJECT)
    w(tmp_path, "environment.yml", "dependencies:\n  - tomlpkg=1.0\n")
    reqs = parse_targets(tmp_path)
    assert [(Path(r.source_file or "").name, r.source_format) for r in reqs] == [
        ("requirements.txt", "requirements.txt"),
        ("pyproject.toml", "pyproject"),
        ("environment.yml", "conda"),
    ]


@pytest.mark.parametrize(
    "name,adapter",
    [
        ("pyproject.toml", "pyproject"),
        ("PyProject.TOML", "pyproject"),
        ("environment.yml", "environment.yml"),
        ("Environment.YAML", "environment.yml"),
        ("requirements-dev.txt", "requirements.txt"),
        ("deps.in", "requirements.txt"),
        ("whatever", "requirements.txt"),
    ],
)
def test_adapter_selection_by_name(tmp_path: Path, name: str, adapter: str) -> None:
    text = PYPROJECT if name.lower().endswith(".toml") else ENV
    assert get_adapter(w(tmp_path, name, text)).name == adapter


def test_arbitrary_yaml_name_needs_dependencies_key(tmp_path: Path) -> None:
    assert get_adapter(w(tmp_path, "conda.yml", ENV)).name == "environment.yml"
    assert get_adapter(w(tmp_path, "ci.yml", "jobs: {}\n")).name == "requirements.txt"


def test_pyproject_without_dependencies_is_still_pyproject_when_explicit(
    tmp_path: Path,
) -> None:
    p = w(tmp_path, "pyproject.toml", "[tool.black]\n")
    assert get_adapter(p).name == "pyproject"
    assert parse_targets(p) == []


def test_explicit_empty_files(tmp_path: Path) -> None:
    for name in ("requirements.txt", "environment.yml", "pyproject.toml"):
        p = w(tmp_path, name, "")
        assert parse_targets(p) == [], name


def test_missing_file_is_a_clean_error(tmp_path: Path) -> None:
    assert resolve_targets(tmp_path / "nope.txt") == [tmp_path / "nope.txt"]
    with pytest.raises(DepKeeperError):
        parse_targets(tmp_path / "nope.txt")


def test_default_target_prefers_requirements_then_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert default_target(None) == Path("requirements.txt")
    w(tmp_path, "pyproject.toml", PYPROJECT)
    assert default_target(None) == Path(".")
    w(tmp_path, "requirements.txt", "a\n")
    assert default_target(None) == Path("requirements.txt")
    assert default_target(Path("x.yml")) == Path("x.yml")
