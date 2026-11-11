"""``update --pin`` rewrites every supported requirement, including unchanged versions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.robustness.update_harness import invoke

T = {"requests": "2.34.2", "flask": "3.0.0", "numpy": "1.26.4"}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)


def run(*args: str) -> Any:
    return invoke(T, ["update", *args])


@pytest.mark.parametrize(
    "line, expected",
    [
        ("requests>=2.34.2", "requests==2.34.2"),
        ("requests~=2.34.2", "requests==2.34.2"),
        ("requests>=2.34.2,<3", "requests==2.34.2"),
        ("requests[socks]>=2.34.2", "requests[socks]==2.34.2"),
        (
            'requests>=2.34.2; python_version >= "3.8"',
            'requests==2.34.2; python_version >= "3.8"',
        ),
        ("requests==2.34.*", "requests==2.34.2"),
        ("requests>=2.0  # keep", "requests==2.34.2  # keep"),
    ],
)
def test_requirements_txt_pin_semantics(
    tmp_path: Path, line: str, expected: str
) -> None:
    f = tmp_path / "requirements.txt"
    f.write_text(line + "\n")
    r = run("-y", "--pin", str(f))
    assert r.exit_code == 0, r.stdout + r.stderr
    assert f.read_text() == expected + "\n"
    assert "up to date" not in r.stdout + r.stderr
    again = run("-y", "--pin", str(f))
    assert f.read_text() == expected + "\n"
    assert "up to date" in again.stdout + again.stderr


def test_already_exact_is_untouched(tmp_path: Path) -> None:
    f = tmp_path / "requirements.txt"
    f.write_text("requests==2.34.2\n")
    r = run("-y", "--pin", str(f))
    assert "up to date" in r.stdout + r.stderr
    assert f.read_text() == "requests==2.34.2\n"


def test_dry_run_shows_plan_without_writing(tmp_path: Path) -> None:
    f = tmp_path / "requirements.txt"
    f.write_text("requests>=2.34.2\n")
    r = run("--dry-run", "--pin", str(f))
    assert r.exit_code == 0
    assert "Update Plan" in r.stdout and "up to date" not in r.stdout + r.stderr
    assert f.read_text() == "requests>=2.34.2\n"


def test_direct_references_never_touched(tmp_path: Path) -> None:
    body = "-e git+https://example.com/x.git#egg=requests\nrequests @ https://e.com/r.tar.gz\n"
    f = tmp_path / "requirements.txt"
    f.write_text(body)
    run("-y", "--pin", str(f))
    assert f.read_text() == body


def test_pyproject_range_is_pinned_when_unchanged(tmp_path: Path) -> None:
    f = tmp_path / "pyproject.toml"
    f.write_text(
        '[project]\nname = "d"\nversion = "0"\ndependencies = ["requests>=2.34.2"]\n'
    )
    run("-y", "--pin", str(f))
    assert '"requests==2.34.2"' in f.read_text()


def test_conda_range_is_pinned_when_unchanged(tmp_path: Path) -> None:
    f = tmp_path / "environment.yml"
    f.write_text("name: e\ndependencies:\n  - python=3.11\n  - numpy>=1.26.4\n")
    run("-y", "--pin", str(f))
    assert "numpy==1.26.4" in f.read_text()
