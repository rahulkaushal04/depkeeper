"""Poetry's python constraint is the target Python, like requires-python."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional
from unittest import mock

import pytest

from depkeeper.cli import cli
from depkeeper.commands._report import resolve_target_python
from depkeeper.core.sources.pyproject_toml import PyprojectTomlAdapter
from tests.test_commands.test_check_output_streams import (
    _fake_analyzer,
    _fake_checker,
    _FakeHTTPClient,
    _make_runner,
)

A = PyprojectTomlAdapter()


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "pyproject.toml"
    p.write_text('[tool.poetry]\nname = "d"\nversion = "0"\n\n' + body)
    return p


@pytest.mark.parametrize(
    "constraint,spec,minimum",
    [
        ('"^3.9"', ">=3.9,<4", "3.9"),
        ('"^3.9.1"', ">=3.9.1,<4", "3.9"),
        ('"~3.9"', ">=3.9,<3.10", "3.9"),
        ('"~3.9.2"', ">=3.9.2,<3.10", "3.9"),
        ('">=3.9,<4"', ">=3.9,<4", "3.9"),
        ('"3.9.*"', "==3.9.*", "3.9"),
        ('"^0.2"', ">=0.2,<0.3", None),
        ('{version = "^3.10"}', ">=3.10,<4", "3.10"),
        ('"*"', None, None),
        ('"^3.8 || ^3.10"', None, None),
    ],
)
def test_poetry_python_is_pep440(
    tmp_path: Path, constraint: str, spec: Optional[str], minimum: Optional[str]
) -> None:
    f = _write(tmp_path, f"[tool.poetry.dependencies]\npython = {constraint}\n")
    assert A.requires_python(f) == spec
    assert resolve_target_python(None, None, f)[0] == minimum


def test_project_requires_python_beats_poetry(tmp_path: Path) -> None:
    f = tmp_path / "pyproject.toml"
    f.write_text(
        '[project]\nname = "d"\nrequires-python = ">=3.11"\n'
        '[tool.poetry.dependencies]\npython = "^3.9"\n'
    )
    assert A.requires_python(f) == ">=3.11"


def test_flag_and_group_python_keys(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        '[tool.poetry.dependencies]\npython = "^3.9"\nrequests = "^2.25"\n'
        '[tool.poetry.group.dev.dependencies]\npython = "^3.12"\npytest = "^7"\n',
    )
    assert [r.name for r in A.parse(f)] == ["requests", "pytest"]
    assert A.requires_python(f) == ">=3.9,<4"
    assert resolve_target_python("3.12", None, f) == ("3.12", "--python-version")
    assert resolve_target_python(None, None, f)[1] == "pyproject.toml requires-python"


def test_cli_check_targets_poetry_python(tmp_path: Path) -> None:
    f = _write(tmp_path, '[tool.poetry.dependencies]\npython = "~3.9"\nflask = "^2"\n')
    seen: List[Any] = []

    class _Store:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            seen.append(kwargs.get("target_python"))

        async def prefetch_packages(self, names: List[str]) -> None:
            return None

    with mock.patch("depkeeper.commands.check.HTTPClient", _FakeHTTPClient), mock.patch(
        "depkeeper.commands.check.PyPIDataStore", _Store
    ), mock.patch(
        "depkeeper.commands.check.VersionChecker", _fake_checker([])
    ), mock.patch("depkeeper.commands.check.DependencyAnalyzer", _fake_analyzer(None)):
        res = _make_runner().invoke(cli, ["check", str(f)], catch_exceptions=False)
    assert res.exit_code == 0, res.output
    assert seen == ["3.9"]
