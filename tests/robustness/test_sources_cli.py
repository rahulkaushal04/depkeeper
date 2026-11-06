"""Real-CLI check of mixed-format directory updates against live PyPI."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest


def _online() -> bool:
    try:
        socket.create_connection(("pypi.org", 443), timeout=3).close()
        return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(not _online(), reason="PyPI unreachable"),
]

PYPROJECT = """\
[project]
name = "demo"
dependencies = ["six==1.10.0; python_version<\\"4\\""]
[tool.uv]
dev-dependencies = ["tomli>=1.0"]
"""
ENV = """\
name: x
dependencies:
  - python=3.11
  - librosa=0.9
  - pip:
    - Requests>=2.0  # http
    - ./local
"""


def test_directory_update_edits_each_format_in_place(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT)
    (tmp_path / "environment.yml").write_text(ENV)
    run = subprocess.run(
        [sys.executable, "-m", "depkeeper", "update", "-y", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[2])},
    )
    assert run.returncode == 0, run.stdout + run.stderr
    py = (tmp_path / "pyproject.toml").read_text()
    env = (tmp_path / "environment.yml").read_text()
    assert 'six==1.17.0; python_version<\\"4\\""' in py
    assert 'dev-dependencies = ["tomli>=1.2.3"]' in py
    assert "librosa=0.9" not in env and "  - librosa=0." in env
    assert "Requests>=2.0" not in env and "# http" in env and "- ./local" in env
