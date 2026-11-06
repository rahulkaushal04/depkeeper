"""End-to-end tests for pyproject handling in the ``check`` command."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from depkeeper.cli import cli


@pytest.mark.unit
@pytest.mark.parametrize(
    "body",
    [
        "[tool.black]\nline-length = 88\n",
        '[project]\nname = "x"\n',
        '[project]\nname = "x"\ndynamic = ["dependencies"]\n',
    ],
    ids=["tool-only", "name-only", "dynamic-deps"],
)
def test_pyproject_without_dependency_tables_is_not_an_error(
    tmp_path: Path, body: str
) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_text(body)
    result = CliRunner().invoke(cli, ["check", str(path)])
    assert result.exit_code == 0, result.output


@pytest.mark.unit
def test_directory_mode_skips_dependency_less_pyproject(tmp_path: Path) -> None:
    from depkeeper.core.sources.registry import discover

    (tmp_path / "pyproject.toml").write_text("[tool.black]\nline-length = 88\n")
    (tmp_path / "requirements.txt").write_text("requests==2.0\n")
    assert [p.name for p in discover(tmp_path)] == ["requirements.txt"]
