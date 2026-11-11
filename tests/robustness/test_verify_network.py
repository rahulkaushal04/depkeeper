"""Real pip against real PyPI: verification verdicts, constraints and the CLI path."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from depkeeper.core.verify import verify_plan


pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(
        importlib.util.find_spec("pip") is None, reason="pip not installed"
    ),
]


def test_good_plan_and_extras() -> None:
    r = verify_plan(["requests[socks]==2.31.0", "urllib3<2"])
    assert r.ok and not r.skipped and r.checked >= 3 and r.pip_version


def test_known_conflict_reports_both_sides() -> None:
    r = verify_plan(["requests==2.31.0", "urllib3==1.20"])
    assert not r.ok and not r.skipped
    assert any("requests==2.31.0" in c and "urllib3==1.20" in c for c in r.conflicts)


def test_nonexistent_version_is_failure_not_skip() -> None:
    r = verify_plan(["requests==99.0.0"])
    assert not r.ok and not r.skipped and "does not exist" in r.message


def test_nonexistent_transitive_pin_via_constraint() -> None:
    r = verify_plan(["requests==2.31.0"], constraints=["urllib3<1.20"])
    assert not r.ok and not r.skipped


def test_constraint_on_unlisted_package_applies() -> None:
    r = verify_plan(["requests==2.31.0"], constraints=["certifi>=2020"])
    assert r.ok and r.constraints == 1


@pytest.mark.parametrize("req", ["pyyaml==3.10", "lxml==2.3"])
def test_sdist_only_release_is_skipped_never_built(req: str) -> None:
    r = verify_plan([req])
    assert r.skipped and not r.ok and "without building" in r.message


def test_release_needing_newer_python_than_target_fails() -> None:
    r = verify_plan(["numpy==2.1.0"], python_version="3.9")
    assert not r.ok and not r.skipped and "Requires-Python" in r.message


def test_markers_for_other_platform_are_not_a_problem() -> None:
    r = verify_plan(['pywin32==306; sys_platform=="win32"', "six"])
    assert r.ok


def test_empty_plan_is_ok_and_honest() -> None:
    r = verify_plan([])
    assert r.ok and r.checked == 0


def test_hostile_lines_do_not_change_index(tmp_path: Path) -> None:
    r = verify_plan(["six", "--index-url http://127.0.0.1:9/evil"])
    assert r.skipped and "plain requirement" in r.message


def test_cli_verify_full_plan_even_with_package_selection(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "requests==2.25.0\nurllib3==1.20\nsix==1.10.0\n"
    )
    p = subprocess.run(
        [
            str(Path(sys.executable).parent / "depkeeper"),
            "update",
            "-p",
            "six",
            "--dry-run",
            "--verify",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = p.stdout + p.stderr
    # urllib3==1.20 conflicts with requests (any version in the file); the whole
    # plan is verified, not only the selected package.
    assert p.returncode == 1, out
    assert "do not resolve" in out
    assert (tmp_path / "requirements.txt").read_text().count("six==1.10.0") == 1
