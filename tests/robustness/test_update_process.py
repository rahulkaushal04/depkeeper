"""Real-process behaviour: exit codes, SIGINT, concurrent writers, option validation."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, List

import pytest

from depkeeper.utils import filesystem as fs
from tests.robustness.update_harness import invoke, strays


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)


def test_concurrent_writers_never_leave_partial_or_stray_files(tmp_path: Path) -> None:
    target = tmp_path / "requirements.txt"
    variants = [("v%d\n" % i) * (2000 + i) for i in range(8)]
    target.write_text("start\n")
    errors: List[BaseException] = []

    def work(i: int) -> None:
        for _ in range(15):
            try:
                fs.safe_write_file(target, variants[i], create_backup=False)
            except fs.FileOperationError:
                pass
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert target.read_text() in variants
    assert strays(tmp_path) == []


@pytest.mark.parametrize(
    "args",
    [
        ["--python-version", "banana"],
        ["--python-version", "3"],
        ["--min-age", "soon"],
        ["--max-update", "huge"],
        ["--format", "yaml"],
        ["--allow-hash-removal", "--refresh-hashes"],
    ],
)
def test_bad_options_exit_2_and_touch_nothing(tmp_path: Path, args: List[str]) -> None:
    f = tmp_path / "requirements.txt"
    f.write_bytes(b"requests==2.0.0\n")
    r = invoke({"requests": "2.31.0"}, ["update", "-y", *args, str(f)])
    assert r.exit_code == 2
    assert f.read_bytes() == b"requests==2.0.0\n"


def test_missing_file_is_usage_error(tmp_path: Path) -> None:
    r = invoke({}, ["update", "-y", str(tmp_path / "nope.txt")])
    assert r.exit_code == 2


def test_empty_requirements_is_noop_exit_0(tmp_path: Path) -> None:
    f = tmp_path / "requirements.txt"
    f.write_bytes(b"# nothing\n")
    r = invoke({}, ["update", "-y", str(f)])
    assert r.exit_code == 0 and f.read_bytes() == b"# nothing\n"


def test_flags_combine_without_error(tmp_path: Path) -> None:
    f = tmp_path / "requirements.txt"
    f.write_bytes(b"requests>=2.0\nflask==1.0\n")
    r = invoke(
        {"requests": "2.31.0", "flask": "3.0.0"},
        [
            "update", "-y", "--backup", "--pin", "--no-check-conflicts",
            "--python-version", "3.9", "--min-age", "7d", "--allow-major", "flask",
            "--max-update", "major", "-p", "flask", "--ignore", "zzz", str(f),
        ],
    )  # fmt: skip
    assert r.exit_code == 0, r.stdout + r.stderr
    assert f.read_bytes() == b"requests>=2.0\nflask==3.0.0\n"


_ENV = {
    **os.environ,
    "NO_COLOR": "1",
    "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
}


def _cli(*args: str, cwd: Path, stdin: Any = subprocess.DEVNULL) -> Any:
    return subprocess.run(
        [sys.executable, "-m", "depkeeper", *args], cwd=cwd, capture_output=True, text=True, stdin=stdin,
        timeout=120, env=_ENV,
    )  # fmt: skip


@pytest.mark.network
class TestRealProcess:
    def test_non_tty_without_yes_refuses_cleanly(self, tmp_path: Path) -> None:
        f = tmp_path / "requirements.txt"
        f.write_bytes(b"requests==2.0.0\n")
        p = _cli("update", cwd=tmp_path)
        assert p.returncode == 1 and "--yes" in p.stdout + p.stderr
        assert f.read_bytes() == b"requests==2.0.0\n"

    def test_update_then_check_is_up_to_date_and_second_update_noop(
        self, tmp_path: Path
    ) -> None:
        f = tmp_path / "requirements.txt"
        f.write_bytes(b"requests==2.20.0\r\nidna>=2.0,<4\r\n")
        p = _cli("update", "-y", cwd=tmp_path)
        assert p.returncode == 0, p.stdout + p.stderr
        first = f.read_bytes()
        assert (
            first != b"requests==2.20.0\r\nidna>=2.0,<4\r\n"
            and first.count(b"\r\n") == 2
        )
        p2 = _cli("update", "-y", cwd=tmp_path)
        assert p2.returncode == 0 and f.read_bytes() == first
        assert _cli("check", "--fail-on", "minor", cwd=tmp_path).returncode == 0


# Stalls the first HTTP request after printing a marker, so SIGINT lands mid-run.
_STALL = """
import asyncio, sys
from depkeeper.utils import http

async def _send_once(self, *a, **k):
    sys.stderr.write("READY\\n")
    sys.stderr.flush()
    await asyncio.sleep(120)

http.HTTPClient._send_once = _send_once
from depkeeper.__main__ import main
sys.exit(main())
"""


def test_sigint_exits_130_and_leaves_file_whole(tmp_path: Path) -> None:
    f = tmp_path / "requirements.txt"
    f.write_bytes(b"requests==2.0.0\n")
    proc = subprocess.Popen(
        [sys.executable, "-c", _STALL, "update", "-y"], cwd=tmp_path, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, env=_ENV, text=True,
    )  # fmt: skip
    assert proc.stderr is not None
    try:
        for line in proc.stderr:  # blocks until the process is mid-request
            if line.strip() == "READY":
                break
        else:
            pytest.fail("process exited before reaching the network layer")
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert proc.returncode == 130
    assert f.read_bytes() == b"requests==2.0.0\n"
    assert strays(tmp_path) == []
