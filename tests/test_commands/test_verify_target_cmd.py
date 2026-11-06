"""``update --verify`` threads the run's target Python into verification."""

from typing import Any, Dict, List
from unittest.mock import patch

from depkeeper.commands import update
from depkeeper.core.verify import VerifyResult
from depkeeper.models.requirement import Requirement


def _req(name: str, *, url: str = "") -> Requirement:
    return Requirement(name=name, specs=[("==", "1.0")], url=url or None)


def _run(result: VerifyResult, reqs: List[Requirement], py: Any) -> Dict[str, Any]:
    seen: Dict[str, Any] = {"ok": [], "warn": []}

    def fake(plan: List[str], constraints: Any = (), **kw: Any) -> VerifyResult:
        seen["kw"] = kw
        return result

    with patch.object(update, "_run_verify", fake):
        seen["rc"] = update._verify_ok(
            reqs, [], seen["warn"].append, seen["ok"].append, py
        )
    return seen


def test_target_python_is_passed_through() -> None:
    r = VerifyResult(True, False, "", [], "24.0", "3.9", "linux-x86_64", 2)
    seen = _run(r, [_req("a")], "3.9")
    assert seen["kw"] == {"python_version": "3.9"} and seen["rc"] is True


def test_no_target_passes_nothing_and_success_line_says_what_was_verified() -> None:
    r = VerifyResult(True, False, "", [], "24.0", "3.9", "linux-x86_64", 14)
    seen = _run(r, [_req("a"), _req("b", url="https://x/y.whl")], None)
    assert seen["kw"] == {}
    line = seen["ok"][0]
    assert line.startswith("--verify: pip 24.0 resolved 14 requirements for Python 3.9")
    assert "1 direct URL/editable requirement not checked" in line


def test_skipped_warns_and_continues() -> None:
    seen = _run(VerifyResult(False, True, "cannot verify x", []), [_req("a")], "3.9")
    assert seen["rc"] is True and "cannot verify x" in seen["warn"][0]
