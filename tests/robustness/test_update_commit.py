"""Two-phase commit, rollback and temp-file hygiene under injected failures."""

from __future__ import annotations

import sys
import errno
import os
from pathlib import Path
from typing import Any, Callable, Dict, List
from unittest import mock

import pytest

from depkeeper.utils import filesystem as fs
from tests.robustness.update_harness import invoke, snapshot, strays

T = {"requests": "2.31.0", "flask": "3.0.0", "idna": "3.7"}
FILES = {
    "requirements.txt": b"-r a.txt\n-r b.txt\nrequests==2.0.0\n",
    "a.txt": b"flask==1.0.0\r\n",
    "b.txt": b"idna==2.0\n",
}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)
    for name, data in FILES.items():
        (tmp_path / name).write_bytes(data)


def go(tmp: Path, *extra: str) -> Any:
    return invoke(T, ["update", "-y", *extra, str(tmp / "requirements.txt")])


def counting(real: Callable[..., Any], fail_on: int, exc: BaseException) -> Any:
    calls: List[int] = []

    def wrapper(*a: Any, **k: Any) -> Any:
        calls.append(1)
        if len(calls) == fail_on:
            raise exc
        return real(*a, **k)

    return wrapper


def assert_untouched(tmp: Path, before: Dict[str, Any]) -> None:
    assert snapshot(tmp) == before
    assert strays(tmp) == []


# Sorted commit order is: a.txt, b.txt, requirements.txt
@pytest.mark.parametrize("fail_on", [1, 2, 3])
@pytest.mark.parametrize(
    "exc",
    [
        OSError(errno.ENOSPC, "No space left on device"),
        PermissionError(errno.EACCES, "Permission denied"),
        OSError(errno.EXDEV, "Cross-device link"),
    ],
    ids=["enospc", "eacces", "exdev"],
)
def test_rename_failure_rolls_everything_back(
    tmp_path: Path, fail_on: int, exc: OSError
) -> None:
    before = snapshot(tmp_path)
    with mock.patch.object(
        fs, "_replace_with_retry", counting(fs._replace_with_retry, fail_on, exc)
    ), mock.patch("time.sleep"):
        r = go(tmp_path)
    assert r.exit_code == 1, r.stdout + r.stderr
    assert_untouched(tmp_path, before)


@pytest.mark.parametrize("fail_on", [1, 3, 5])  # file fsyncs; dir fsyncs follow each
def test_enospc_on_fsync_of_temp_file(tmp_path: Path, fail_on: int) -> None:
    if sys.platform == "win32":
        fail_on = (fail_on + 1) // 2  # Windows has no directory fsync: file fsyncs only
    before = snapshot(tmp_path)
    with mock.patch.object(
        os, "fsync", counting(os.fsync, fail_on, OSError(errno.ENOSPC, "full"))
    ):
        r = go(tmp_path)
    assert r.exit_code == 1
    assert_untouched(tmp_path, before)


@pytest.mark.parametrize("fail_on", [1, 2, 3])
@pytest.mark.parametrize("where", ["_replace_with_retry", "_fsync_directory"])
def test_keyboard_interrupt_between_and_inside_writes(
    tmp_path: Path, fail_on: int, where: str
) -> None:
    """Ctrl-C at any step, including right after a rename, restores every file."""
    before = snapshot(tmp_path)
    real = getattr(fs, where)
    with mock.patch.object(fs, where, counting(real, fail_on, KeyboardInterrupt())):
        r = go(tmp_path)
    assert r.exit_code != 0
    assert_untouched(tmp_path, before)


@pytest.mark.parametrize("victim", ["a.txt", "b.txt", "requirements.txt"])
def test_external_edit_before_commit_is_never_overwritten(
    tmp_path: Path, victim: str
) -> None:
    """A file edited after it was read aborts the batch; nothing is clobbered."""
    import depkeeper.commands.update as upd

    real = upd._commit_pending_writes
    edited = b"# edited by someone else\n" + FILES[victim]

    def racing(pending: Any) -> Any:
        (tmp_path / victim).write_bytes(edited)
        return real(pending)

    with mock.patch.object(upd, "_commit_pending_writes", racing):
        r = go(tmp_path)
    assert r.exit_code == 1
    assert "modified while" in r.stdout + r.stderr
    for name, data in FILES.items():
        assert (tmp_path / name).read_bytes() == (edited if name == victim else data)
    assert strays(tmp_path) == []


@pytest.mark.parametrize("victim", ["b.txt", "requirements.txt"])
def test_external_edit_after_first_write_rolls_first_back(
    tmp_path: Path, victim: str
) -> None:
    import depkeeper.commands.update as upd

    real = upd.safe_write_file
    edited = b"# edited by someone else\n" + FILES[victim]
    calls: List[int] = []

    def racing(path: Any, *a: Any, **k: Any) -> Any:
        calls.append(1)
        res = real(path, *a, **k)
        if len(calls) == 1:
            (tmp_path / victim).write_bytes(edited)
        return res

    with mock.patch.object(upd, "safe_write_file", racing):
        r = go(tmp_path)
    assert r.exit_code == 1
    for name, data in FILES.items():
        assert (tmp_path / name).read_bytes() == (edited if name == victim else data)
    assert strays(tmp_path) == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_read_only_second_file_rolls_back_first(tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses permissions")
    before = snapshot(tmp_path)
    os.chmod(tmp_path / "b.txt", 0o444)
    before = snapshot(tmp_path)
    r = go(tmp_path)
    assert r.exit_code == 1
    assert_untouched(tmp_path, before)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_read_only_directory_leaves_files_intact(tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses permissions")
    before = snapshot(tmp_path)
    os.chmod(tmp_path, 0o555)
    try:
        r = go(tmp_path)
    finally:
        os.chmod(tmp_path, 0o755)
    assert r.exit_code == 1
    assert_untouched(tmp_path, before)


def test_crash_at_every_atomic_step_leaves_old_or_new(tmp_path: Path) -> None:
    """Killing safe_write_file at any internal step never leaves a partial file."""
    sub = tmp_path / "sub"
    sub.mkdir()
    target = sub / "t.txt"
    old, new = "old\n" * 50, "new\n" * 5000
    steps = ["write", "fsync", "copymode", "replace", "dirsync"]
    for step in steps:
        target.write_text(old)
        boom = KeyboardInterrupt()
        target_fn = {
            "write": (os, "fsync"),
            "fsync": (os, "fsync"),
            "copymode": (fs.shutil, "copymode"),
            "replace": (fs, "_replace_with_retry"),
            "dirsync": (fs, "_fsync_directory"),
        }[step]
        with mock.patch.object(*target_fn, side_effect=boom):
            with pytest.raises(KeyboardInterrupt):
                fs.safe_write_file(target, new, create_backup=False)
        # Only an interrupt after the rename may leave the new content.
        assert target.read_text() == (new if step == "dirsync" else old), step
        assert os.listdir(sub) == ["t.txt"]


def test_backup_survives_failed_apply_and_is_reported(tmp_path: Path) -> None:
    before = snapshot(tmp_path)
    with mock.patch.object(
        fs,
        "_replace_with_retry",
        counting(fs._replace_with_retry, 2, OSError(errno.ENOSPC, "full")),
    ):
        r = go(tmp_path, "--backup")
    assert r.exit_code == 1
    backups = sorted(p for p in tmp_path.iterdir() if p.name.endswith(".backup"))
    assert len(backups) == 3
    assert "saved at" in r.stdout + r.stderr
    for b in backups:
        assert b.read_bytes() in FILES.values()
    assert {
        k: v for k, v in snapshot(tmp_path).items() if not k.endswith(".backup")
    } == before
