"""Tests for pip dry-run plan verification and conflict parsing."""

import subprocess
from typing import Callable, List, Tuple, Union
from unittest.mock import patch

from depkeeper.core import verify
from depkeeper.core.verify import parse_conflicts, redact, verify_plan

CONFLICT = """\
ERROR: Cannot install foo==1.0 and bar==2.0 because these package versions have conflicting dependencies.

The conflict is caused by:
    foo 1.0 depends on shared<2
    bar 2.0 depends on shared>=2

To fix this you could try to:
1. loosen the range of package versions you've specified
ERROR: ResolutionImpossible: for help visit https://pip.pypa.io/
"""
PIP = "pip 24.0 from /x/pip (python 3.11)"


_Result = Tuple[int, str, str]


def _seq(*results: Union[_Result, Exception]) -> Callable[[List[str], float], _Result]:
    it = iter(results)

    def fake(args: List[str], timeout: float) -> _Result:
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r

    return fake


def test_parse_conflicts() -> None:
    c = parse_conflicts(CONFLICT)
    assert c[0] == "Cannot install foo==1.0 and bar==2.0"
    assert "foo 1.0 depends on shared<2" in c
    assert "bar 2.0 depends on shared>=2" in c


def test_parse_resolution_impossible_only() -> None:
    assert parse_conflicts("ERROR: ResolutionImpossible") == [
        "pip reported ResolutionImpossible"
    ]


def test_redact() -> None:
    assert redact("https://u:p@host/x") == "https://***@host/x"


def test_ok() -> None:
    with patch.object(verify, "_run", _seq((0, PIP, ""), (0, "", ""))):
        r = verify_plan(["foo==1"])
    assert r.ok and not r.skipped


def test_conflict() -> None:
    with patch.object(verify, "_run", _seq((0, PIP, ""), (1, "", CONFLICT))):
        r = verify_plan(["foo==1.0", "bar==2.0"])
    assert not r.ok and not r.skipped and len(r.conflicts) == 3


def test_old_pip_skipped() -> None:
    with patch.object(verify, "_run", _seq((0, "pip 21.0 from x", ""))):
        r = verify_plan(["foo"])
    assert r.skipped and "22.2" in r.message


def test_timeout_and_oserror_skipped() -> None:
    to = subprocess.TimeoutExpired("pip", 1)
    with patch.object(verify, "_run", _seq((0, PIP, ""), to)):
        assert verify_plan(["foo"]).skipped
    with patch.object(verify, "_run", _seq(FileNotFoundError("nope"))):
        assert verify_plan(["foo"]).skipped


def test_network_skipped_and_redacted() -> None:
    err = "Failed to establish a new connection https://u:secret@idx/simple"
    with patch.object(verify, "_run", _seq((0, PIP, ""), (1, "", err))):
        r = verify_plan(["foo"])
    assert r.skipped and "secret" not in r.message


def test_temp_files_removed() -> None:
    seen = []

    def fake(args: List[str], timeout: float) -> _Result:
        if "-r" in args:
            seen.append(args[args.index("-r") + 1])
            import os

            assert os.path.exists(seen[0])
            return 0, "", ""
        return 0, PIP, ""

    with patch.object(verify, "_run", fake):
        verify_plan(["foo"])
    import os

    assert not os.path.exists(seen[0])
