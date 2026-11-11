"""Conflict resolution through the real CLI against live PyPI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
from click.testing import CliRunner

from depkeeper.cli import cli


_ROOT = Path(__file__).resolve().parents[2]


pytestmark = [
    pytest.mark.network,
]


@pytest.fixture(autouse=True)
def _cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # isolate from the repo's own depkeeper config


def _check(*args: str) -> List[Dict[str, Any]]:
    try:
        runner = CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        runner = CliRunner()
    result = runner.invoke(cli, ["check", "--format", "json", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)  # type: ignore[no-any-return]


def _by_name(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {row["name"]: row for row in rows}


def test_unresolvable_cap_is_reported_and_nothing_is_invented(tmp_path: Path) -> None:
    (tmp_path / "r.txt").write_text("flask>=2.3,<3.0\nwerkzeug>=2.2,<2.3\n")
    rows = _by_name(_check("r.txt"))
    assert rows["flask"]["versions"]["recommended"] == "2.3"
    assert rows["werkzeug"]["versions"]["recommended"] == "2.2"
    assert rows["werkzeug"]["conflict_held"] is True
    assert rows["werkzeug"]["conflicts"][0]["source_package"] == "flask"


def test_no_check_conflicts_equals_the_checker_alone(tmp_path: Path) -> None:
    (tmp_path / "r.txt").write_text("flask>=2.3,<3.0\nwerkzeug>=2.2,<2.3\n")
    rows = _by_name(_check("r.txt", "--no-check-conflicts"))
    assert rows["flask"]["versions"]["recommended"].startswith("2.3.")
    assert rows["werkzeug"]["versions"]["recommended"].startswith("2.2.")
    assert not any("conflicts" in r or "conflict_held" in r for r in rows.values())


def test_config_switch_matches_the_flag(tmp_path: Path) -> None:
    (tmp_path / "r.txt").write_text("flask>=2.3,<3.0\nwerkzeug>=2.2,<2.3\n")
    flag = _check("r.txt", "--no-check-conflicts")
    (tmp_path / "depkeeper.toml").write_text("[depkeeper]\ncheck_conflicts = false\n")
    assert _check("r.txt") == flag
    assert _check("r.txt", "--check-conflicts") != flag


def test_step_back_finds_a_consistent_celery_kombu_pair(tmp_path: Path) -> None:
    (tmp_path / "c.txt").write_text("celery>=5.2,<6\nkombu>=5.2,<5.3\n")
    rows = _by_name(_check("c.txt"))
    assert rows["celery"]["versions"]["recommended"].startswith("5.2.")
    assert rows["kombu"]["versions"]["recommended"].startswith("5.2.")
    assert not any("conflicts" in r for r in rows.values())
    unchecked = _by_name(_check("c.txt", "--no-check-conflicts"))
    assert not unchecked["celery"]["versions"]["recommended"].startswith("5.2.")


def test_input_order_does_not_change_the_plan_in_a_real_subprocess(
    tmp_path: Path,
) -> None:
    lines = [
        "celery>=5.2,<6",
        "kombu>=5.2,<5.3",
        "flask>=2.3,<3.0",
        "werkzeug>=2.2,<2.3",
    ]
    plans = []
    for order in (lines, lines[::-1], lines[1:] + lines[:1]):
        (tmp_path / "r.txt").write_text("\n".join(order) + "\n")
        out = subprocess.run(
            [sys.executable, "-m", "depkeeper", "check", "r.txt", "--format", "json"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env={**os.environ, "PYTHONPATH": str(_ROOT)},
            timeout=120,
        )
        assert out.returncode == 0, out.stderr
        rows = _by_name(json.loads(out.stdout))
        plans.append({n: r["versions"]["recommended"] for n, r in rows.items()})
    assert plans[0] == plans[1] == plans[2]


def test_update_dry_run_with_conflicts_leaves_the_file_untouched(
    tmp_path: Path,
) -> None:
    body = "flask>=2.3,<3.0\nwerkzeug>=2.2,<2.3\nrequests==2.25.1\n"
    (tmp_path / "r.txt").write_text(body)
    result = CliRunner().invoke(cli, ["update", "r.txt", "--dry-run", "-y"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "r.txt").read_text() == body
