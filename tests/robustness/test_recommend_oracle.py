"""Differential test: VersionChecker versus an independent brute-force oracle."""

from __future__ import annotations

from typing import Any, List

from depkeeper.config import PackagePolicy
from depkeeper.core.checker import VersionChecker
from depkeeper.core.data_store import PyPIDataStore
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

from tests.robustness._recommend_oracle import (
    NOW,
    Case,
    _spec_ok,
    _v,
    oracle,
    random_case,
)

N = 6000


class _NoHttp:
    """HTTP stand-in; the oracle tests never touch the network."""


def _run(case: Case) -> Any:
    store = PyPIDataStore(_NoHttp())  # type: ignore[arg-type]
    data = store._parse_package_data(
        "pkg", {"info": {"version": None}, "releases": case.releases}
    )
    pol = PackagePolicy(**case.policy)
    checker = VersionChecker(
        store,
        target_python=case.python,
        versioning=case.mode,
        min_age=case.min_age,
        policies={"pkg": pol},
        clock=lambda: NOW,
        allow_major=["pkg"] if case.allow_major else (),
        max_update=case.run_max_update,
    )
    return checker._build_package_from_data(
        data, case.current, case.constraints, case.series
    )


def _same(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is b
    return _v(a) == _v(b)


def test_checker_matches_oracle() -> None:
    bad: List[str] = []
    for seed in range(N):
        case = random_case(seed)
        want = oracle(case)
        got = _run(case)
        mine = {
            "scheme": got.versioning,
            "rec": got.recommended_version,
            "skipped": got.cooldown_skipped,
            "major": got.major_available,
        }
        ok = mine["scheme"] == want["scheme"] and all(
            _same(mine[k], want[k]) for k in ("rec", "skipped", "major")
        )
        if not ok:
            bad.append(f"seed={seed} got={mine} want={want}")
    assert not bad, f"{len(bad)} disagreements; first: " + "\n".join(bad[:5])


def test_recommendation_invariants_and_idempotence() -> None:
    """Independent of the oracle: structural properties of every recommendation."""
    for seed in range(N):
        case = random_case(seed)
        got = _run(case)
        rec = got.recommended_version
        cur = case.current
        if rec is None or cur is None or _v(rec) == _v(cur):
            continue
        rv, cv = _v(rec), _v(cur)
        assert rv is not None and cv is not None, seed
        assert not case.policy.get("hold") and not case.policy.get("ignore"), seed
        assert _spec_ok(case.constraints, rv), seed
        assert rv.is_prerelease is False or case.policy.get("allow_prerelease"), seed
        rp = next(
            (
                f["requires_python"]
                for f in case.releases[rec]
                if isinstance(f, dict) and f.get("requires_python")
            ),
            None,
        )
        if rp and not rp.endswith(".*"):
            try:
                spec = SpecifierSet(rp)
            except InvalidSpecifier:  # an unparseable Requires-Python is ignored
                spec = None
            if spec is not None:
                assert Version(case.python) in spec, seed
        if case.min_age is not None:
            assert rv > cv, seed
        if got.versioning == "semver" and not (
            case.allow_major or case.policy.get("allow_major")
        ):
            assert rv.release[0] == cv.release[0], seed
        if case.series:
            assert rv > cv, seed
        # Re-checking from the recommendation proposes nothing further.
        again = _run(Case(**{**case.__dict__, "current": rec}))
        assert _v(again.recommended_version) == rv, seed
