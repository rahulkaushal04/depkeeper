"""Adversarial tests of depkeeper.core.verify with the pip boundary mocked."""

from __future__ import annotations

import os
import random
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

from depkeeper.core import verify
from depkeeper.core.verify import VerifyResult, redact, verify_plan

Run = Callable[[List[str], float], Tuple[int, str, str]]

VERSION_OUT = "pip 24.0 from /x/pip (python 3.12)\n"


def _fake(
    install: Optional[Run] = None, calls: Optional[List[List[str]]] = None
) -> Run:
    def run(args: List[str], timeout: float) -> Tuple[int, str, str]:
        if calls is not None:
            calls.append(args)
        if "--version" in args:
            return 0, VERSION_OUT, ""
        assert install is not None
        return install(args, timeout)

    return run


def _arg(args: List[str], flag: str) -> str:
    return args[args.index(flag) + 1]


def _tmp_files() -> List[str]:
    import tempfile

    return sorted(
        f for f in os.listdir(tempfile.gettempdir()) if f.startswith("depkeeper-")
    )


@pytest.mark.parametrize(
    "line",
    [
        "six\n--index-url http://evil.example/simple",
        "--index-url http://evil.example/simple",
        "-r /etc/passwd",
        "--find-links http://evil.example/",
        "-e .",
        "--extra-index-url http://evil.example",
        "six --hash=sha256:00",
        "",
        "   ",
        "six\r\nseven",
        "http://evil.example/x.whl",
        "-c other.txt",
    ],
)
def test_non_requirement_lines_never_reach_pip(
    monkeypatch: pytest.MonkeyPatch, line: str
) -> None:
    calls: List[List[str]] = []
    monkeypatch.setattr(verify, "_run", _fake(calls=calls))
    for kw in (
        {"requirements": [line]},
        {"requirements": ["six"], "constraints": [line]},
    ):
        r = verify_plan(**kw)  # type: ignore[arg-type]
        assert r.skipped and not r.ok
        assert "plain requirement" in r.message
    assert not calls


def test_unicode_and_odd_requirement_strings_never_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify, "_run", _fake(lambda a, t: (0, "", "")))
    for line in ["pkgé==1.0", "\u202epkg", "pkg==\x00", "pkg\x1b[0m"]:
        r = verify_plan([line])
        assert r.skipped and not r.ok and r.checked == 0, line
        assert "not a plain requirement" in r.message, line
    r = verify_plan(["a" * 100000])  # a valid (if absurd) name still verifies
    assert r.ok and not r.skipped and r.checked == 1


def test_requirement_file_is_private_and_removed_on_every_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = _tmp_files()
    seen: Dict[str, Any] = {}

    def install(args: List[str], timeout: float) -> Tuple[int, str, str]:
        for flag in ("-r", "-c", "--report"):
            if flag in args:
                p = _arg(args, flag)
                seen[flag] = (p, stat.S_IMODE(os.stat(p).st_mode))
        outcome = seen.setdefault("outcome", iter(outcomes))
        return next(outcome)()  # type: ignore[no-any-return]

    def boom() -> Tuple[int, str, str]:
        raise RuntimeError("disk on fire")

    def interrupt() -> Tuple[int, str, str]:
        raise KeyboardInterrupt

    def timeout() -> Tuple[int, str, str]:
        raise subprocess.TimeoutExpired("pip", 1)

    outcomes: List[Callable[[], Tuple[int, str, str]]] = [
        lambda: (0, "", ""),
        lambda: (1, "", "boom"),
        boom,
        timeout,
        lambda: (
            1,
            "",
            "ERROR: Cannot install a and b because these package versions have conflicting dependencies.",
        ),
    ]
    monkeypatch.setattr(verify, "_run", _fake(install))
    for out in outcomes:
        seen.clear()
        seen["outcome"] = iter([out])
        r = verify_plan(["six"], constraints=["six>=1"])
        assert isinstance(r, VerifyResult)
        for flag in ("-r", "-c", "--report"):
            path, mode = seen[flag]
            if sys.platform != "win32":  # Windows reports 0o666 for every file
                assert mode == 0o600, flag
            assert not os.path.exists(path), flag
    seen.clear()
    seen["outcome"] = iter([interrupt])
    with pytest.raises(KeyboardInterrupt):
        verify_plan(["six"], constraints=["six>=1"])
    assert not os.path.exists(seen["-r"][0]) and not os.path.exists(seen["-c"][0])
    assert _tmp_files() == before


@pytest.mark.parametrize(
    "version_out",
    ["", "garbage", "pip", "pip x.y", "pip 21.0 from x", "\x00\xff"],
)
def test_garbage_version_output_skips(
    monkeypatch: pytest.MonkeyPatch, version_out: str
) -> None:
    monkeypatch.setattr(verify, "_run", lambda a, t: (0, version_out, ""))
    r = verify_plan(["six"])
    assert r.skipped and not r.ok


def test_pip_version_nonzero_and_oserror_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify, "_run", lambda a, t: (1, VERSION_OUT, ""))
    assert verify_plan(["six"]).skipped

    def missing(a: List[str], t: float) -> Tuple[int, str, str]:
        raise FileNotFoundError("no python")

    monkeypatch.setattr(verify, "_run", missing)
    assert verify_plan(["six"], python_executable="/nonexistent/python").skipped


@pytest.mark.parametrize(
    "report, checked",
    [
        ("", 2),
        ("not json", 2),
        ("[]", 2),
        ("null", 2),
        ('{"install": null}', 2),
        ('{"install": 5}', 2),
        ('{"environment": 3}', 2),
        ('{"install": [], "environment": []}', 0),
    ],
)
def test_garbage_report_still_ok_and_never_raises(
    monkeypatch: pytest.MonkeyPatch, report: str, checked: int
) -> None:
    def install(args: List[str], t: float) -> Tuple[int, str, str]:
        Path(_arg(args, "--report")).write_text(report)
        return 0, "", ""

    monkeypatch.setattr(verify, "_run", _fake(install))
    r = verify_plan(["six", "attrs"])
    assert r.ok and not r.skipped
    assert r.checked == checked  # unreadable -> plan size; readable -> install list


def test_failure_output_never_leaks_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "s3cr3tPASS"
    outputs = [
        f"ERROR: Could not find a version from https://bob:{secret}@idx.example/simple/x",
        f"ERROR: weird https://tok{secret}@idx.example/x?token={secret}&a=1",
        f"Traceback (most recent call last):\nValueError: https://u:{secret}@h/x",
        f"ERROR: No matching distribution found for six==9 via https://u:{secret}@h/x",
        f"ERROR: Cannot install a because these package versions have conflicting dependencies.\n  a depends on b @ https://u:{secret}@h/b.whl",
    ]
    for text in outputs:
        monkeypatch.setattr(
            verify, "_run", _fake(lambda a, t, text=text: (1, "", text))
        )
        monkeypatch.setattr(verify, "_index_versions", lambda *a, **k: None)
        r = verify_plan(["six"])
        blob = r.message + "\n".join(r.conflicts)
        assert secret not in blob, blob


def test_exception_message_with_credentials_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def bad(a: List[str], t: float) -> Tuple[int, str, str]:
        raise OSError("cannot exec https://bob:hunter2@host/x")

    monkeypatch.setattr(verify, "_run", bad)
    assert "hunter2" not in verify_plan(["six"]).message


def test_redact_variants() -> None:
    assert "pw" not in redact("https://u:pw@h/x")
    assert "pw" not in redact("https://u:p/w@h/x")
    assert "pw" not in redact("see https://pw@h/x and more")
    assert "pw" not in redact("https://h/x?api_key=pw&b=1")
    assert redact("https://h/simple/six") == "https://h/simple/six"


def test_timeout_message_and_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    def install(args: List[str], t: float) -> Tuple[int, str, str]:
        raise subprocess.TimeoutExpired(args, t)

    monkeypatch.setattr(verify, "_run", _fake(install))
    r = verify_plan(["six"], timeout=0.5)
    assert r.skipped and "0.5s" in r.message


def test_500_requirement_plan_is_fast_and_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reqs = [f"pkg{i}==1.{i}; python_version >= '3.8'" for i in range(500)]
    captured: List[str] = []

    def install(args: List[str], t: float) -> Tuple[int, str, str]:
        captured.extend(Path(_arg(args, "-r")).read_text().splitlines())
        return 0, "", ""

    monkeypatch.setattr(verify, "_run", _fake(install))
    t0 = time.perf_counter()
    r = verify_plan(reqs, python_version="3.12")
    assert time.perf_counter() - t0 < 5
    assert r.ok and len(captured) == 500 and r.checked == 500
    assert all(";" not in c for c in captured)


def test_marker_for_other_python_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: List[str] = []

    def install(args: List[str], t: float) -> Tuple[int, str, str]:
        captured.extend(Path(_arg(args, "-r")).read_text().splitlines())
        return 0, "", ""

    monkeypatch.setattr(verify, "_run", _fake(install))
    r = verify_plan(
        ["a==1; python_version < '3.8'", "b==1; python_version >= '3.8'"],
        python_version="3.12",
    )
    assert captured == ["b==1"] and r.not_applicable == 1


def test_all_markers_false_is_skipped_not_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify, "_run", _fake(lambda a, t: (0, "", "")))
    r = verify_plan(["a==1; python_version < '3.8'"], python_version="3.12")
    assert r.skipped and not r.ok


def test_summary_is_truthful() -> None:
    r = VerifyResult(True, False, "m", [], "24.0", "3.12", "linux-x86_64", 1, 2, 3)
    s = r.summary(excluded=2)
    assert "1 requirement " in s + " " and "2 constraints" in s
    assert "3 skipped by markers" in s and "2 direct URL/editable requirements" in s
    assert (
        "constraint"
        not in VerifyResult(True, False, "m", [], "24.0", "3.12", "", 0).summary()
    )


def test_index_versions_and_classification_edge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = "ERROR: No matching distribution found for six==9"
    monkeypatch.setattr(verify, "_run", _fake(lambda a, t: (1, "", out)))
    monkeypatch.setattr(verify, "_index_versions", lambda *a, **k: ["1.0", "2.0"])
    r = verify_plan(["six==9"])
    assert not r.ok and not r.skipped and "does not exist" in r.message
    monkeypatch.setattr(verify, "_index_versions", lambda *a, **k: ["9"])
    r = verify_plan(["six==9"])
    assert r.skipped and "without building" in r.message


def test_fuzzed_pip_outputs_never_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    rnd = random.Random(1234)
    frags = [
        "ERROR: No matching distribution found for ",
        "Cannot install ",
        " because these package versions have conflicting dependencies.",
        "  a depends on b>=1",
        "Traceback (most recent call last):",
        "ValueError: x",
        "pip 24.0",
        "\x00",
        "é中",
        "-r /tmp/x (line 99999)",
        "-r /tmp/x (line 0)",
        "Failed to establish a new connection",
        "[",
        "==",
    ]
    monkeypatch.setattr(
        verify, "_index_versions", lambda *a, **k: rnd.choice([None, [], ["1"]])
    )
    for _ in range(300):
        text = "".join(rnd.choice(frags) for _ in range(rnd.randint(0, 8)))
        rc = rnd.choice([0, 1, 2])
        monkeypatch.setattr(
            verify, "_run", _fake(lambda a, t, text=text, rc=rc: (rc, text, text))
        )
        r = verify_plan(["six"])
        if rc == 0:
            assert r.ok and not r.skipped, (text, r)
        else:
            assert not r.ok, (rc, text, r)


def test_run_env_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIP_REQUIRE_VIRTUALENV", "1")
    monkeypatch.setenv("pip_user", "1")
    monkeypatch.setenv("PIP_INDEX_URL", "https://u:pw@idx.example/simple")
    monkeypatch.setenv("PIP_CONFIG_FILE", "/some/pip.conf")
    code, out, _ = verify._run(
        [sys.executable, "-c", "import os,json;print(json.dumps(dict(os.environ)))"], 30
    )
    import json

    env = json.loads(out)
    assert not {k for k in env if k.upper() in verify._STRIP_ENV}
    assert env["PIP_INDEX_URL"] == "https://u:pw@idx.example/simple"
    assert env["PIP_CONFIG_FILE"] == "/some/pip.conf"
    assert env["PIP_DISABLE_PIP_VERSION_CHECK"] == "1"


@pytest.mark.skipif(sys.platform == "win32", reason="posix process groups")
def test_timeout_kills_whole_process_tree_no_orphans() -> None:
    marker = "DKORPHAN%d" % os.getpid()
    code = (
        "import subprocess,sys,time;"
        f"subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)  # {marker}']);"
        "time.sleep(60)"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        verify._run([sys.executable, "-c", code], 1.0)
    time.sleep(0.3)
    ps = subprocess.run(
        ["ps", "-ax", "-o", "command"], capture_output=True, text=True
    ).stdout
    assert marker not in ps


@pytest.mark.skipif(sys.platform == "win32", reason="posix process groups")
def test_keyboard_interrupt_kills_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = "DKINT%d" % os.getpid()
    code = f"import time;time.sleep(60)  # {marker}"
    real = subprocess.Popen.communicate
    state = {"n": 0}

    def communicate(self: Any, *a: Any, **k: Any) -> Any:
        state["n"] += 1
        if state["n"] == 1:
            raise KeyboardInterrupt
        return real(self, *a, **k)

    monkeypatch.setattr(subprocess.Popen, "communicate", communicate)
    with pytest.raises(KeyboardInterrupt):
        verify._run([sys.executable, "-c", code], 30)
    time.sleep(0.3)
    ps = subprocess.run(
        ["ps", "-ax", "-o", "command"], capture_output=True, text=True
    ).stdout
    assert marker not in ps
