"""verify_plan verifies for the *target* Python and classifies outcomes precisely."""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import patch

import pytest

from depkeeper.core import verify
from depkeeper.core.verify import VerifyResult, verify_plan

PIP = "pip 24.0 from /x/pip (python 3.11)"
OLD_PIP = "pip 23.1.2 from /x/pip (python 3.11)"
Result = Tuple[int, str, str]


def _fake(
    install: Result,
    pip: str = PIP,
    index: Optional[Result] = None,
    report: Optional[Dict[str, Any]] = None,
) -> Tuple[List[List[str]], Callable[[List[str], float], Result]]:
    calls: List[List[str]] = []

    def run(args: List[str], timeout: float) -> Result:
        calls.append(list(args))
        if "--version" in args:
            return 0, pip, ""
        if "index" in args:
            return index or (1, "", "")
        if report is not None and "--report" in args:
            with open(args[args.index("--report") + 1], "w", encoding="utf-8") as fh:
                json.dump(report, fh)
        return install

    return calls, run


def _install_call(calls: List[List[str]]) -> List[str]:
    return next(c for c in calls if "install" in c)


class TestFlagConstruction:
    def test_target_differs_from_pip_python_adds_flag(self) -> None:
        calls, run = _fake((0, "", ""))
        with patch.object(verify, "_run", run):
            r = verify_plan(["foo==1"], python_version="3.9")
        args = _install_call(calls)
        assert args[args.index("--python-version") + 1] == "3.9"
        assert "--only-binary=:all:" in args and "--no-deps" not in args
        assert r.ok and r.python_version == "3.9"

    def test_patch_level_is_normalised_to_major_minor(self) -> None:
        calls, run = _fake((0, "", ""))
        with patch.object(verify, "_run", run):
            verify_plan(["foo==1"], python_version="3.9.18")
        args = _install_call(calls)
        assert args[args.index("--python-version") + 1] == "3.9"

    @pytest.mark.parametrize("target", [None, "3.11"])
    def test_same_as_pip_python_needs_no_flag(self, target: Optional[str]) -> None:
        calls, run = _fake((0, "", ""), pip=OLD_PIP)
        with patch.object(verify, "_run", run):
            r = verify_plan(["foo==1"], python_version=target)
        assert "--python-version" not in _install_call(calls)
        assert r.ok and r.python_version == "3.11"

    def test_old_pip_with_other_target_is_skipped_before_resolving(self) -> None:
        calls, run = _fake((0, "", ""), pip=OLD_PIP)
        with patch.object(verify, "_run", run):
            r = verify_plan(["foo==1"], python_version="3.9")
        assert r.skipped and "23.3" in r.message and "3.9" in r.message
        assert not any("install" in c for c in calls)

    def test_unparseable_target_is_skipped(self) -> None:
        _, run = _fake((0, "", ""))
        with patch.object(verify, "_run", run):
            r = verify_plan(["foo==1"], python_version="banana")
        assert r.skipped and "banana" in r.message

    def test_pip_rejecting_the_flag_is_skipped_with_reason(self) -> None:
        err = "ERROR: Can not use any platform or abi specific options unless installing via '--target'"
        _, run = _fake((2, "", err))
        with patch.object(verify, "_run", run):
            r = verify_plan(["foo==1"], python_version="3.9")
        assert r.skipped and "does not support" in r.message and "3.9" in r.message


class TestOutcomes:
    NO_MATCH = "ERROR: No matching distribution found for pycrypto==2.6.1"

    def test_sdist_only_is_skipped_never_failed(self) -> None:
        idx = (0, "pycrypto (2.6.1)\nAvailable versions: 2.6.1, 2.6, 2.5\n", "")
        _, run = _fake((1, "", self.NO_MATCH), index=idx)
        with patch.object(verify, "_run", run):
            r = verify_plan(["pycrypto==2.6.1"], python_version="3.9")
        assert r.skipped and not r.ok
        assert "pycrypto==2.6.1" in r.message and "without building" in r.message

    def test_missing_version_is_a_failure(self) -> None:
        idx = (0, "pycrypto (2.6.1)\nAvailable versions: 2.6.1, 2.6\n", "")
        err = "ERROR: No matching distribution found for pycrypto==9.9"
        _, run = _fake((1, "", err), index=idx)
        with patch.object(verify, "_run", run):
            r = verify_plan(["pycrypto==9.9"])
        assert not r.ok and not r.skipped and "does not exist" in r.message

    def test_python_incompatible_release_is_a_failure_naming_target(self) -> None:
        err = (
            "ERROR: Ignored the following versions that require a different "
            "python version: 2.2.0 Requires-Python >=3.10\n"
            "ERROR: No matching distribution found for numpy==2.2.0"
        )
        _, run = _fake((1, "", err))
        with patch.object(verify, "_run", run):
            r = verify_plan(["numpy==2.2.0"], python_version="3.9")
        assert not r.ok and not r.skipped and "Python 3.9" in r.message

    def test_unknown_index_answer_keeps_failure(self) -> None:
        _, run = _fake((1, "", self.NO_MATCH), index=(1, "", "boom"))
        with patch.object(verify, "_run", run):
            r = verify_plan(["pycrypto==2.6.1"])
        assert not r.ok and not r.skipped

    def test_index_message_is_redacted(self) -> None:
        err = (
            "No matching distribution found for foo==1 via https://u:secret@idx/simple"
        )
        _, run = _fake((1, "", err))
        with patch.object(verify, "_run", run):
            r = verify_plan(["foo==1"])
        assert "secret" not in r.message

    def test_success_reports_what_was_verified(self) -> None:
        report = {
            "install": [{}, {}, {}],
            "environment": {"sys_platform": "linux", "platform_machine": "x86_64"},
        }
        _, run = _fake((0, "", ""), report=report)
        with patch.object(verify, "_run", run):
            r = verify_plan(["a", "b"], python_version="3.9", constraints=["c<2"])
        assert (r.pip_version, r.python_version, r.checked) == ("24.0", "3.9", 3)
        s = r.summary()
        assert s.startswith("pip 24.0 resolved 3 requirements for Python 3.9 (")
        assert "1 constraint" in s
        assert "2 constraints" in r.summary(constraints=2)
        assert "1 direct URL/editable" in r.summary(excluded=1)

    def test_old_constructions_stay_valid(self) -> None:
        r = VerifyResult(True, False, "x", [])
        assert r.pip_version == "" and r.checked == 0
        assert "pip resolved" in r.summary()


class TestTimeoutKillsProcessTree:
    def test_killpg_called_with_group_of_session_leader(self) -> None:
        class P:
            pid = 4321
            returncode = None
            calls = 0

            def communicate(self, timeout: Optional[float] = None) -> Any:
                P.calls += 1
                if P.calls == 1:
                    raise subprocess.TimeoutExpired("pip", timeout or 0)
                return "", ""

            def kill(self) -> None:
                pass

            def __enter__(self) -> "P":
                return self

            def __exit__(self, *a: Any) -> None:
                pass

        seen: Dict[str, Any] = {}

        def popen(args: List[str], **kw: Any) -> P:
            seen.update(kw)
            return P()

        with patch.object(verify.subprocess, "Popen", popen), patch.object(
            verify.os, "killpg", create=True
        ) as kp:
            with pytest.raises(subprocess.TimeoutExpired):
                verify._run(["pip"], 0.1)
        if sys.platform != "win32":
            assert seen["start_new_session"] is True
            kp.assert_called_once_with(4321, signal.SIGKILL)

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
    def test_grandchild_dies_with_timeout(self, tmp_path: Any) -> None:
        pidfile = tmp_path / "pid"
        code = (
            "import subprocess,sys,time;"
            "p=subprocess.Popen(['sleep','60']);"
            f"open({str(pidfile)!r},'w').write(str(p.pid));time.sleep(60)"
        )
        with pytest.raises(subprocess.TimeoutExpired):
            verify._run([sys.executable, "-c", code], 1.5)
        pid = int(pidfile.read_text())
        for _ in range(30):
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.1)
        os.kill(pid, signal.SIGKILL)
        pytest.fail("grandchild survived the timeout")


def _pip_ok() -> bool:
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        ).stdout
        ver = tuple(int(x) for x in out.split()[1].split(".")[:2])
        socket.create_connection(("pypi.org", 443), timeout=5).close()
    except Exception:  # noqa: BLE001
        return False
    return ver >= (23, 3)


@pytest.mark.network
@pytest.mark.skipif(not _pip_ok(), reason="needs pip>=23.3 and PyPI access")
class TestRealPip:
    def test_known_conflict_is_a_conflict(self) -> None:
        r = verify_plan(["flask==3.0.3", "werkzeug==2.0.3"], python_version="3.9")
        assert not r.ok and not r.skipped and r.conflicts

    def test_good_plan_passes_and_reports(self) -> None:
        r = verify_plan(["flask==3.0.3"], python_version="3.9")
        assert r.ok and r.checked >= 2 and r.python_version == "3.9"

    def test_release_needing_newer_python_is_rejected_for_old_target(self) -> None:
        r = verify_plan(["numpy==2.2.0"], python_version="3.9")
        assert not r.ok and not r.skipped


class TestReviewFixes:
    """Range specs, transitive names, markers, Python-filtered releases, Ctrl-C."""

    def test_sdist_only_with_range_spec_is_skipped(self) -> None:
        idx = (0, "docopt (0.6.2)\nAvailable versions: 0.6.2, 0.6.1\n", "")
        err = "ERROR: No matching distribution found for docopt>=0.6"
        _, run = _fake((1, "", err), index=idx)
        with patch.object(verify, "_run", run):
            r = verify_plan(["docopt>=0.6"])
        assert r.skipped and "docopt" in r.message and "without building" in r.message

    def test_transitive_sdist_only_names_the_right_package(self) -> None:
        idx = (0, "docopt (0.6.2)\nAvailable versions: 0.6.2\n", "")
        err = (
            "ERROR: Ignored the following versions that require a different "
            "python version: 9.9 Requires-Python >=3.99\n"
            "ERROR: Could not find a version that satisfies the requirement "
            "docopt (from pipreqs) (from versions: none)\n"
            "ERROR: No matching distribution found for docopt"
        )
        _, run = _fake((1, "", err), index=idx)
        with patch.object(verify, "_run", run):
            r = verify_plan(["pipreqs==0.4.13"], python_version="3.9")
        assert r.skipped and "docopt" in r.message
        assert "Requires-Python" not in r.message

    def test_index_is_queried_without_python_version(self) -> None:
        idx = (0, "numpy (2.0.0)\nAvailable versions: 2.0.0\n", "")
        err = (
            "ERROR: Ignored the following versions that require a different "
            "python version: 2.0.0 Requires-Python >=3.9\n"
            "ERROR: Could not find a version that satisfies the requirement "
            "numpy==2.0.0 (from versions: 1.24.4)\n"
            "ERROR: No matching distribution found for numpy==2.0.0"
        )
        calls, run = _fake((1, "", err), index=idx)
        with patch.object(verify, "_run", run):
            r = verify_plan(["numpy==2.0.0"], python_version="3.8")
        assert all("--python-version" not in c for c in calls if "index" in c)
        assert not r.ok and not r.skipped
        assert "does not exist" not in r.message and "3.8" in r.message

    def test_markers_follow_target_python(self) -> None:
        calls, run = _fake((0, "", ""), report={"install": [{}]})
        reqs = [
            'tomli==2.0.1; python_version < "3.11"',
            'x==1; python_version >= "3.9"',
        ]
        with patch.object(verify, "_run", run):
            r = verify_plan(reqs, python_version="3.8")
        assert r.not_applicable == 1 and "1 skipped by markers" in r.summary()

    def test_only_applicable_lines_reach_pip(self) -> None:
        seen: Dict[str, str] = {}

        def run(args: List[str], timeout: float) -> Result:
            if "--version" in args:
                return 0, PIP, ""
            with open(args[args.index("-r") + 1], encoding="utf-8") as fh:
                seen["t"] = fh.read()
            return 0, "", ""

        with patch.object(verify, "_run", run):
            verify_plan(
                ['a==1; python_version < "3.9"', 'b==1; python_version >= "3.9"', "c"],
                python_version="3.8",
            )
        # settled markers are stripped: pip would re-evaluate them on the host
        assert seen["t"].split("\n")[:-1] == ["a==1", "c"]

    def test_everything_excluded_is_skipped_not_ok(self) -> None:
        calls, run = _fake((0, "", ""))
        with patch.object(verify, "_run", run):
            r = verify_plan(['a==1; python_version >= "3.9"'], python_version="3.8")
        assert r.skipped and not r.ok and "nothing to verify" in r.message
        assert not any("install" in c for c in calls)

    def test_platform_comes_from_pip_report(self) -> None:
        rep = {
            "install": [{}],
            "environment": {"sys_platform": "linux", "platform_machine": "x86_64"},
        }
        _, run = _fake((0, "", ""), report=rep)
        with patch.object(verify, "_run", run):
            r = verify_plan(["a"])
        assert r.platform == "linux-x86_64"

    def test_redaction_covers_user_only_and_query_tokens(self) -> None:
        assert "bob" not in verify.redact("https://bob@host/simple")
        out = verify.redact("https://h/x?private_token=abc123&a=1")
        assert "abc123" not in out and "a=1" in out

    def test_keyboard_interrupt_kills_tree_and_reraises(self) -> None:
        class P:
            pid = 99
            returncode = None
            n = 0

            def communicate(self, timeout: Optional[float] = None) -> Any:
                P.n += 1
                if P.n == 1:
                    raise KeyboardInterrupt
                return "", ""

            def kill(self) -> None:
                pass

            def __enter__(self) -> "P":
                return self

            def __exit__(self, *a: Any) -> None:
                pass

        with patch.object(
            verify.subprocess, "Popen", lambda *a, **k: P()
        ), patch.object(verify, "_kill_tree") as kt:
            with pytest.raises(KeyboardInterrupt):
                verify._run(["pip"], 5)
        kt.assert_called_once()


@pytest.mark.network
@pytest.mark.skipif(not _pip_ok(), reason="needs pip>=23.3 and PyPI access")
class TestRealPipReviewCases:
    def test_sdist_only_range_is_skipped(self) -> None:
        r = verify_plan(["docopt>=0.6"], python_version="3.9")
        assert r.skipped and "docopt" in r.message

    def test_transitive_sdist_only_is_skipped_naming_it(self) -> None:
        r = verify_plan(["pipreqs==0.4.13"], python_version="3.9")
        assert r.skipped and "docopt" in r.message

    def test_marker_for_other_python_is_not_verified_on_host(self) -> None:
        r = verify_plan(['numpy==2.0.0; python_version >= "3.9"'], python_version="3.8")
        assert r.skipped and not r.ok

    def test_marker_applies_for_target(self) -> None:
        r = verify_plan(['tomli==2.0.1; python_version < "3.11"'], python_version="3.8")
        assert r.ok and r.checked == 1

    def test_newer_python_release_not_reported_as_missing(self) -> None:
        r = verify_plan(["numpy==2.0.0"], python_version="3.8")
        assert not r.ok and not r.skipped and "does not exist" not in r.message
