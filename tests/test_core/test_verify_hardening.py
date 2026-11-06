"""verify_plan never builds sdists, honours -c constraints and classifies errors."""

import os
from typing import Any, Callable, List, Tuple
from unittest.mock import patch

import pytest

from depkeeper.core import verify
from depkeeper.core.verify import redact, verify_plan

PIP = "pip 24.0 from /x/pip (python 3.11)"


def _capture(
    result: Tuple[int, str, str],
) -> Tuple[List[List[str]], Callable[[List[str], float], Tuple[int, str, str]]]:
    calls = []

    def fake(args: List[str], timeout: float) -> Tuple[int, str, str]:
        calls.append(list(args))
        return (0, PIP, "") if "--version" in args else result

    return calls, fake


def test_only_binary_flag_always_passed() -> None:
    calls, fake = _capture((0, "", ""))
    with patch.object(verify, "_run", fake):
        assert verify_plan(["foo==1"]).ok
    assert "--only-binary=:all:" in calls[-1]


def test_no_matching_distribution_is_failure_not_network_skip() -> None:
    err = "ERROR: No matching distribution found for requests==99.0.0"
    _, fake = _capture((1, "", err))
    with patch.object(verify, "_run", fake):
        r = verify_plan(["requests==99.0.0"])
    assert not r.ok and not r.skipped
    assert "requests==99.0.0" in r.message and "source" in r.message


def test_real_network_error_still_skipped_even_with_no_matching_line() -> None:
    err = (
        "WARNING: Failed to establish a new connection\n"
        "ERROR: No matching distribution found for foo"
    )
    _, fake = _capture((1, "", err))
    with patch.object(verify, "_run", fake):
        assert verify_plan(["foo"]).skipped


def test_constraints_written_as_dash_c_and_cleaned() -> None:
    seen = {}

    def fake(args: List[str], timeout: float) -> Tuple[int, str, str]:
        if "--version" in args:
            return 0, PIP, ""
        path = args[args.index("-c") + 1]
        with open(path, encoding="utf-8") as fh:
            seen["text"] = fh.read()
        seen["path"] = path
        return 0, "", ""

    with patch.object(verify, "_run", fake):
        verify_plan(["foo"], constraints=["bar<2", "baz!=1.0"])
    assert seen["text"].split() == ["bar<2", "baz!=1.0"]
    assert not os.path.exists(seen["path"])


def test_no_constraints_no_dash_c() -> None:
    calls, fake = _capture((0, "", ""))
    with patch.object(verify, "_run", fake):
        verify_plan(["foo"])
    assert "-c" not in calls[-1]


def test_env_keeps_index_config_strips_only_breaking_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIP_INDEX_URL", "https://u:p@private/simple")
    monkeypatch.setenv("PIP_EXTRA_INDEX_URL", "https://x/simple")
    monkeypatch.setenv("PIP_CONSTRAINT", "c.txt")
    monkeypatch.setenv("PIP_REQUIRE_VIRTUALENV", "1")
    monkeypatch.setenv("PIP_NO_DEPS", "1")
    monkeypatch.setenv("PIP_REQUIRE_HASHES", "1")
    got = {}

    def fake_popen(args: List[str], **kw: Any) -> Any:
        got.update(kw["env"])

        class P:
            returncode = 0

            def __enter__(self) -> "P":
                return self

            def __exit__(self, *a: Any) -> None:
                pass

            def communicate(self, timeout: Any = None) -> Any:
                return "", ""

        return P()

    with patch.object(verify.subprocess, "Popen", fake_popen):
        verify._run(["pip"], 1.0)
    assert got["PIP_INDEX_URL"] == "https://u:p@private/simple"
    assert got["PIP_EXTRA_INDEX_URL"] and got["PIP_CONSTRAINT"] == "c.txt"
    for k in ("PIP_REQUIRE_VIRTUALENV", "PIP_NO_DEPS", "PIP_REQUIRE_HASHES"):
        assert k not in got
    assert got["PIP_DISABLE_PIP_VERSION_CHECK"] == "1"


def test_redact_password_with_slash() -> None:
    assert "s3cr/et" not in redact("https://user:s3cr/et@host/simple")
