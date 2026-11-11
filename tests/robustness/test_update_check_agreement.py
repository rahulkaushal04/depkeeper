"""After `update`, `check` reports nothing to update and a second `update` is a no-op."""

from __future__ import annotations

import itertools
import json
import socket
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple
from unittest import mock

import pytest
from click.testing import CliRunner

from depkeeper.cli import cli
from tests.robustness.update_harness import _HTTP
from tests.support.pypi import FakePyPIStore, package_data

HISTORIES: Dict[str, List[str]] = {
    "pyyaml": ["5.1", "5.2", "5.3", "5.3.1", "5.4", "5.4.1", "6.0", "6.0.1"],
    "pygments": ["2.17.0", "2.17.2", "2.18.0", "2.19.0", "2.19.1", "2.19.2"],
    "twopart": ["1.0", "1.1", "1.2", "2.0", "2.1"],
    "zerox": ["0.8.0", "0.9.0", "0.9.1", "0.10.0", "0.10.1"],
    "fourpart": ["1.0.0.0", "1.0.0.1", "1.0.1.0", "1.1.0.0", "2.0.0.0"],
    "single": ["1.0.0"],
}

# Templates; {v} is the declared version, {m} its major, {m1} the next major.
FORMS = [
    "{n}",
    "{n}>={v}",
    "{n}>{v}",
    "{n}=={v}",
    "{n}==={v}",
    "{n}~={v}",
    "{n}=={m}.*",
    "{n}>={v},<{m1}",
    "{n}>={v},!=0.0.99",
    "{n}!=0.0.99",
    "{n}<{m1}",
    "{n}[extra]>={v}",
    '{n}>={v} ; python_version >= "3.8"',
    "{n} ~= {v}  # keep",
    "{n}>={v},<{m1},!=0.0.99",
]


def _two(version: str) -> str:
    return ".".join(version.split(".")[:2])


def _lines() -> List[Tuple[str, str]]:
    cases = []
    for name, history in HISTORIES.items():
        starts = sorted({history[0], history[len(history) // 2], history[-1]})
        for form, start in itertools.product(FORMS, starts):
            for v in {start, _two(start)}:
                major = v.split(".")[0]
                line = form.format(n=name, v=v, m=major, m1=int(major) + 1)
                cases.append((name, line))
    return sorted(set(cases))


def _runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        return CliRunner()


def _store() -> FakePyPIStore:
    return FakePyPIStore({n: package_data(n, h) for n, h in HISTORIES.items()})


def invoke(store: FakePyPIStore, *args: str) -> Any:
    with ExitStack() as stack:
        for cmd in ("update", "check"):
            stack.enter_context(
                mock.patch(f"depkeeper.commands.{cmd}.HTTPClient", _HTTP)
            )
            stack.enter_context(
                mock.patch(
                    f"depkeeper.commands.{cmd}.PyPIDataStore",
                    lambda *a, **k: store,
                )
            )
        return _runner().invoke(cli, list(args))


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)


@pytest.mark.parametrize("name,line", _lines())
def test_update_then_check_agrees(tmp_path: Path, name: str, line: str) -> None:
    f = tmp_path / "requirements.txt"
    f.write_text(line + "\n")
    store = _store()
    first = invoke(store, "update", "-y", str(f))
    assert first.exit_code == 0, (line, first.stdout, first.stderr)
    written = f.read_bytes()

    chk = invoke(store, "check", "--fail-on", "updates", str(f))
    assert chk.exit_code == 0, (line, written, chk.stdout)

    second = invoke(store, "update", "-y", str(f))
    assert second.exit_code == 0, (line, second.stdout, second.stderr)
    assert f.read_bytes() == written, line


def test_compatible_release_same_series_is_not_an_update(tmp_path: Path) -> None:
    f = tmp_path / "requirements.txt"
    f.write_text("pyyaml~=5.4\n")
    store = _store()
    r = invoke(store, "check", "--fail-on", "updates", str(f))
    assert r.exit_code == 0, r.stdout
    out = invoke(store, "check", "--format", "json", str(f))
    entry = json.loads(out.stdout)[0]
    assert entry["status"] == "latest"


def test_compatible_release_with_patch_moves_at_patch_granularity(
    tmp_path: Path,
) -> None:
    f = tmp_path / "requirements.txt"
    f.write_text("pyyaml~=5.4.0\n")
    store = _store()
    assert invoke(store, "update", "-y", str(f)).exit_code == 0
    assert f.read_text() == "pyyaml~=5.4.1\n"


def test_pin_still_takes_the_newest_in_series(tmp_path: Path) -> None:
    f = tmp_path / "requirements.txt"
    f.write_text("pyyaml~=5.4\n")
    assert invoke(_store(), "update", "-y", "--pin", str(f)).exit_code == 0
    assert f.read_text() == "pyyaml==5.4.1\n"


def _online() -> bool:
    try:
        socket.create_connection(("pypi.org", 443), timeout=3).close()
        return True
    except OSError:
        return False


@pytest.mark.network
@pytest.mark.skipif(not _online(), reason="PyPI unreachable")
@pytest.mark.parametrize(
    "line",
    [
        "PyYAML~=5.3",
        "Pygments~=2.10",
        "requests>=2.25,<3",
        "requests~=2.25.0",
        "click==8.*",
        "six",
    ],
)
def test_live_update_then_check_agrees(tmp_path: Path, line: str) -> None:
    f = tmp_path / "requirements.txt"
    f.write_text(line + "\n")
    exe: Sequence[str] = [sys.executable, "-m", "depkeeper"]

    def run(*args: str) -> "subprocess.CompletedProcess[str]":
        return subprocess.run(
            [*exe, *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=120,
            env={"NO_COLOR": "1", "PATH": "/usr/bin:/bin"},
        )

    assert run("update", "-y", str(f)).returncode == 0
    written = f.read_bytes()
    assert run("check", "--fail-on", "updates", str(f)).returncode == 0, written
    assert run("update", "-y", str(f)).returncode == 0
    assert f.read_bytes() == written
