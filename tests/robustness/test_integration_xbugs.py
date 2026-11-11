"""Full-stack defects found against real PyPI; each is a strict xfail until fixed."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, List

import pytest
from click.testing import CliRunner

from depkeeper.cli import cli


pytestmark = [
    pytest.mark.network,
]


@pytest.fixture(autouse=True)
def _cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def _invoke(*args: str) -> Any:
    try:
        runner = CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:  # click >= 8.2 always separates the streams
        runner = CliRunner()
    return runner.invoke(cli, list(args))


def _check(tmp_path: Path, body: str, *extra: str) -> List[dict]:
    (tmp_path / "requirements.txt").write_text(body)
    res = _invoke("check", "-f", "json", *extra, str(tmp_path / "requirements.txt"))
    return json.loads(res.stdout)


def test_direct_references_are_not_looked_up(tmp_path: Path) -> None:
    out = _check(
        tmp_path,
        "-e git+https://github.com/pallets/click.git@main#egg=click\n"
        "mylib @ https://example.com/mylib-1.0.tar.gz\n",
    )
    assert all("versions" not in p for p in out), out


def test_poetry_python_constraint_is_target(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "d"\nversion = "0"\n\n'
        '[tool.poetry.dependencies]\npython = "~3.9"\nrequests = "^2.25.0"\n'
    )
    res = _invoke("check", "-f", "json", str(tmp_path / "pyproject.toml"))
    rec = json.loads(res.stdout)[0]["python_requirements"]["recommended"]
    from packaging.specifiers import SpecifierSet

    assert SpecifierSet(rec).contains("3.9.0"), rec


def test_directory_update_is_idempotent_with_cross_file_duplicate(
    tmp_path: Path,
) -> None:
    (tmp_path / "requirements.txt").write_text(
        "django==4.2.0\ndjangorestframework>=3.14,<3.16\n"
    )
    (tmp_path / "requirements-dev.txt").write_text("django==2.0\n")
    first = _invoke("update", "-y", str(tmp_path))
    assert first.exit_code == 0, first.output
    snap = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    second = _invoke("update", "-y", str(tmp_path))
    assert second.exit_code == 0
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == snap


def test_conflicts_match_final_recommendation(tmp_path: Path) -> None:
    out = _check(tmp_path, "flask>=3.0\nclick==7.1.2\nwerkzeug==2.0.0\n")
    for pkg in out:
        for c in pkg.get("conflicts") or []:
            assert c["conflicting_version"] == pkg["versions"]["recommended"], pkg


def test_simple_format_has_no_double_comma(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("celery==5.2.0\n")
    res = _invoke("check", "-f", "simple", str(tmp_path / "requirements.txt"))
    assert ",," not in res.stdout.replace("\n", " "), res.stdout


def test_allow_major_unknown_package_warns(tmp_path: Path) -> None:
    f = tmp_path / "requirements.txt"
    f.write_text("requests==2.25.0\n")
    res = _invoke("check", "-f", "json", "--allow-major", "nonexistentpkg", str(f))
    assert "nonexistentpkg" in res.stderr


@pytest.mark.slow
def test_outage_fails_fast(tmp_path: Path) -> None:
    f = tmp_path / "requirements.txt"
    f.write_text("requests==2.25.0\nflask==1.0.0\nclick==7.0\n")
    env = dict(
        os.environ, HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9"
    )
    start = time.time()
    p = subprocess.run(
        [sys.executable, "-m", "depkeeper", "check", str(f)],
        env=env,
        capture_output=True,
        timeout=300,
    )
    assert p.returncode == 4
    assert time.time() - start < 25


def test_huge_pypi_document_is_not_a_lookup_failure(tmp_path: Path) -> None:
    f = tmp_path / "requirements.txt"
    f.write_text("ddtrace>=1.0\n")
    res = _invoke("check", "-f", "json", "--no-check-conflicts", str(f))
    assert res.exit_code != 4, res.stderr


def test_pin_applies_when_already_at_recommended(tmp_path: Path) -> None:
    f = tmp_path / "requirements.txt"
    f.write_text("requests>=2.34.2\n")
    res = _invoke("update", "-y", "--pin", str(f))
    assert res.exit_code == 0, res.stderr
    assert "==" in f.read_text()
