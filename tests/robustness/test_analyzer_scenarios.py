"""Hand-built conflict scenarios: cycles, diamonds, ping-pong and odd metadata."""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Sequence

import pytest

import depkeeper.core.dependency_analyzer as da
from depkeeper.core.dependency_analyzer import DependencyAnalyzer, ResolutionResult
from depkeeper.models.package import Package
from tests.support.pypi import FakePyPIStore, package_data
from tests.robustness.test_analyzer_oracle import check_invariants, gen, run


def _store(
    versions: Dict[str, Sequence[str]], deps: Optional[Dict[str, List[str]]] = None
) -> FakePyPIStore:
    return FakePyPIStore(
        {n: package_data(n, list(v)) for n, v in versions.items()},
        dependencies=deps or {},
    )


def _pkg(name: str, cur: Optional[str], rec: Optional[str], **kw: object) -> Package:
    return Package(name=name, current_version=cur, recommended_version=rec, **kw)  # type: ignore[arg-type]


async def _go(store: FakePyPIStore, *pkgs: Package, **kw: object) -> ResolutionResult:
    return await DependencyAnalyzer(store, **kw).resolve_and_annotate_conflicts(  # type: ignore[arg-type]
        list(pkgs)
    )


@pytest.mark.parametrize("seed", [52, 120, 317, 995, 3557])
def test_seeds_that_used_to_oscillate_or_end_inconsistent(seed: int) -> None:
    eco = gen(seed, calver=False)
    pkgs, before, res, checker = asyncio.run(run(eco))
    check_invariants(eco, pkgs, before, res, checker)
    assert res.iterations_used < 20


async def test_two_dependents_wanting_different_targets_do_not_ping_pong() -> None:
    # a needs t!=1.1.0, b needs t<2: only t==1.0.0 satisfies both.
    store = _store(
        {"a": ["1.0.0"], "b": ["1.0.0"], "t": ["1.0.0", "1.1.0", "2.3.0"]},
        {"a==1.0.0": ["t!=1.1.0"], "b==1.0.0": ["t<2"]},
    )
    a, b = _pkg("a", "1.0.0", "1.0.0"), _pkg("b", "1.0.0", "1.0.0")
    t = _pkg("t", "1.0.0", "2.3.0")
    res = await _go(store, a, b, t, checker=None)
    assert t.recommended_version == "1.0.0"
    assert res.converged and res.iterations_used <= 3


async def test_source_step_back_does_not_trade_one_conflict_for_another() -> None:
    # a 1.2 wants b>=2 (violated); a 1.1 fits b but wants c==5 (violated); a 1.0 is free.
    store = _store(
        {"a": ["1.0.0", "1.1.0", "1.2.0"], "b": ["1.0.0"], "c": ["4.0.0"]},
        {"a==1.2.0": ["b>=2"], "a==1.1.0": ["b<2", "c==5"], "a==1.0.0": []},
    )
    a, b, c = (
        _pkg("a", "1.0.0", "1.2.0"),
        _pkg("b", "1.0.0", "1.0.0"),
        _pkg("c", "4.0.0", "4.0.0"),
    )
    res = await _go(store, a, b, c)
    assert a.recommended_version == "1.0.0"
    assert res.converged and res.iterations_used <= 3


async def test_target_constraint_does_not_break_the_targets_own_requirements() -> None:
    # t 1.2 is the highest match for a's t>=1.1 but needs z>=2 (z only has 1.x).
    store = _store(
        {"a": ["1.0.0", "1.5.0"], "t": ["1.0.0", "1.1.0", "1.2.0"], "z": ["1.0.0"]},
        {"a==1.0.0": ["t>=1.1"], "a==1.5.0": ["t>=1.1"], "t==1.2.0": ["z>=2"]},
    )
    a, t, z = (
        _pkg("a", "1.0.0", "1.5.0"),
        _pkg("t", "1.0.0", "1.0.0"),
        _pkg("z", "1.0.0", "1.0.0"),
    )
    res = await _go(store, a, t, z)
    assert (a.recommended_version, t.recommended_version) == ("1.0.0", "1.1.0")
    assert res.converged


async def test_self_requirement_is_not_a_conflict() -> None:
    store = _store({"a": ["1.0.0", "1.3.0"]}, {"a==1.3.0": ["a<1.3", "A[extra]>=9"]})
    a = _pkg("a", "1.0.0", "1.3.0")
    res = await _go(store, a)
    assert a.recommended_version == "1.3.0"
    assert res.converged and res.packages_with_conflicts == 0 and not a.conflicts


@pytest.mark.parametrize("flag", ["held", "ignored"])
async def test_held_or_ignored_target_is_never_lowered(flag: str) -> None:
    store = _store(
        {"a": ["1.0.0", "1.5.0"], "t": ["1.0.0", "1.3.0"]},
        {"a==1.5.0": ["t<1.3"], "a==1.0.0": ["t<1.3"]},
    )
    a = _pkg("a", "1.0.0", "1.5.0")
    t = _pkg("t", "1.3.0", "1.3.0", **{flag: True})
    res = await _go(store, a, t)
    assert t.recommended_version == "1.3.0"
    assert a.recommended_version == "1.0.0"
    assert not res.converged  # the file itself is inconsistent; reported, not "fixed"
    assert t.conflicts


async def test_unheld_target_may_still_be_lowered_to_satisfy_a_dependent() -> None:
    store = _store(
        {"a": ["1.0.0", "1.5.0"], "t": ["1.0.0", "1.3.0"]},
        {"a==1.5.0": ["t<1.3"], "a==1.0.0": ["t<1.3"]},
    )
    a, t = _pkg("a", "1.0.0", "1.5.0"), _pkg("t", "1.3.0", "1.3.0")
    res = await _go(store, a, t)
    assert t.recommended_version == "1.0.0"
    assert res.converged


async def test_iteration_cap_exhaustion_reports_the_last_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One move fixes the conflict, but the cap stops the loop before it rescans.
    monkeypatch.setattr(da, "_MAX_RESOLUTION_ITERATIONS", 1)
    store = _store(
        {"a": ["1.0.0", "1.5.0"], "b": ["1.0.0"]},
        {"a==1.5.0": ["b>=2"]},
    )
    a, b = _pkg("a", "1.0.0", "1.5.0"), _pkg("b", "1.0.0", "1.0.0")
    res = await _go(store, a, b)
    assert a.recommended_version == "1.0.0"
    assert res.converged and res.iterations_used == 1


async def test_iteration_cap_exhaustion_keeps_unresolved_conflicts_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(da, "_MAX_RESOLUTION_ITERATIONS", 1)
    store = _store(
        {"a": ["1.0.0", "1.5.0"], "b": ["1.0.0"], "c": ["1.0.0"]},
        {"a==1.5.0": ["b>=2"], "b==1.0.0": ["c>=2"]},
    )
    a, b, c = (
        _pkg("a", "1.0.0", "1.5.0"),
        _pkg("b", "1.0.0", "1.0.0"),
        _pkg("c", "1.0.0", "1.0.0"),
    )
    res = await _go(store, a, b, c)
    assert not res.converged
    assert [x.source_package for x in c.conflicts] == ["b"]


async def test_mutual_requirement_cycle_terminates_consistently() -> None:
    # a needs b>=2, b needs a<2: moving either alone just flips the conflict.
    store = _store(
        {"a": ["1.0.0", "2.0.0"], "b": ["1.0.0", "2.0.0"]},
        {
            "a==2.0.0": ["b>=2"],
            "a==1.0.0": [],
            "b==2.0.0": ["a<2"],
            "b==1.0.0": [],
        },
    )
    a = _pkg("a", "1.0.0", "1.0.0", retained_specs=[])
    b = _pkg("b", "1.0.0", "1.0.0")
    res = await _go(store, a, b)
    assert (a.recommended_version, b.recommended_version) == ("1.0.0", "1.0.0")
    assert res.converged


async def test_diamond_with_incompatible_branches_falls_back_to_installed() -> None:
    store = _store(
        {
            "top": ["1.0.0", "1.1.0"],
            "left": ["1.0.0"],
            "right": ["1.0.0"],
            "base": ["1.0.0", "2.0.0"],
        },
        {
            "top==1.1.0": ["left", "right"],
            "left==1.0.0": ["base<2"],
            "right==1.0.0": ["base>=2"],
        },
    )
    pkgs = [
        _pkg("top", "1.0.0", "1.1.0"),
        _pkg("left", "1.0.0", "1.0.0"),
        _pkg("right", "1.0.0", "1.0.0"),
        _pkg("base", "1.0.0", "1.0.0"),
    ]
    res = await _go(store, *pkgs)
    # base 2.0.0 is another major, so left and right cannot both be satisfied.
    assert not res.converged
    assert [p.recommended_version for p in pkgs] == ["1.1.0", "1.0.0", "1.0.0", "1.0.0"]
    assert {c.source_package for c in pkgs[3].conflicts} == {"right"}


async def test_packages_outside_the_file_never_conflict() -> None:
    store = _store(
        {"a": ["1.0.0", "1.1.0"]},
        {"a==1.1.0": ["ghost>=99", "other==1"], "a==1.0.0": []},
    )
    a = _pkg("a", "1.0.0", "1.1.0")
    res = await _go(store, a)
    assert a.recommended_version == "1.1.0" and res.converged
    assert set(res.resolved_versions) == {"a"}


async def test_unavailable_stub_gains_no_recommendation_even_when_conflicting() -> None:
    store = _store({"a": ["1.0.0", "1.5.0"]}, {"a==1.5.0": ["ghost>=2"]})
    a, ghost = _pkg("a", "1.0.0", "1.5.0"), _pkg("ghost", "1.0.0", None)
    res = await _go(store, a, ghost)
    assert ghost.recommended_version is None
    assert a.recommended_version == "1.0.0"
    assert res.resolved_versions["ghost"].resolved == "1.0.0"
    assert res.converged


async def test_stub_without_any_version_is_ignored() -> None:
    store = _store({"a": ["1.0.0", "1.5.0"]}, {"a==1.5.0": ["ghost>=2"]})
    a, ghost = _pkg("a", "1.0.0", "1.5.0"), _pkg("ghost", None, None)
    res = await _go(store, a, ghost)
    assert a.recommended_version == "1.5.0" and ghost.recommended_version is None
    assert res.converged


async def test_bare_name_conflict_stalls_without_inventing_versions() -> None:
    store = _store({"a": ["1.0.0", "2.0.0"], "b": ["1.0.0"]}, {"a==2.0.0": ["b>=2"]})
    a, b = _pkg("a", None, "2.0.0"), _pkg("b", None, "1.0.0")
    res = await _go(store, a, b)
    assert (a.recommended_version, b.recommended_version) == ("2.0.0", "1.0.0")
    assert not res.converged and b.conflicts


@pytest.mark.parametrize(
    "dep, violated",
    [
        ("b[security,socks]>=2", True),
        ("B>=2", True),
        ("b @ https://example.com/b.whl", False),
        ("b (>=2)", True),
        ("b>=2 ; python_version<'3'", True),  # markers are the store's job
        ("not a requirement!!", False),
        ("", False),
        ("b>=1rc1", False),
    ],
)
async def test_dependency_string_forms(dep: str, violated: bool) -> None:
    store = _store({"a": ["1.0.0", "1.1.0"], "b": ["1.0.0"]}, {"a==1.1.0": [dep]})
    a, b = _pkg("a", "1.0.0", "1.1.0"), _pkg("b", "1.0.0", "1.0.0")
    res = await _go(store, a, b)
    assert (a.recommended_version == "1.0.0") is violated
    assert res.converged


async def test_dotted_and_cased_names_in_metadata_match_the_file() -> None:
    store = _store(
        {"a": ["1.0.0", "1.1.0"], "zope-interface": ["5.0.0"]},
        {"a==1.1.0": ["Zope.Interface>=6"]},
    )
    a, z = _pkg("a", "1.0.0", "1.1.0"), _pkg("Zope_Interface", "5.0.0", "5.0.0")
    await _go(store, a, z)
    assert a.recommended_version == "1.0.0"


async def test_prerelease_pin_is_judged_by_pep440() -> None:
    store = _store(
        {"a": ["1.0.0", "1.1.0"], "b": ["2.0.0rc1"]},
        {"a==1.1.0": ["b>=2.0.0rc1"], "a==1.0.0": []},
    )
    a, b = _pkg("a", "1.0.0", "1.1.0"), _pkg("b", "2.0.0rc1", "2.0.0rc1")
    assert (await _go(store, a, b)).converged and a.recommended_version == "1.1.0"
    store.dependencies["a==1.1.0"] = ["b>=2"]
    a2 = _pkg("a", "1.0.0", "1.1.0")
    await _go(store, a2, _pkg("b", "2.0.0rc1", "2.0.0rc1"))
    assert a2.recommended_version == "1.0.0"  # 2.0.0rc1 < 2


async def test_source_search_is_bounded() -> None:
    versions = ["1.%d.0" % i for i in range(200)]
    store = _store(
        {"a": versions, "b": ["1.0.0"]},
        {"a==1.%d.0" % i: ["b>=2"] for i in range(1, 200)},
    )
    a, b = _pkg("a", "1.0.0", "1.199.0"), _pkg("b", "1.0.0", "1.0.0")
    calls: List[str] = []
    original = store.get_version_dependencies

    async def spy(name: str, version: str) -> List[str]:
        calls.append("%s==%s" % (name, version))
        return await original(name, version)

    store.get_version_dependencies = spy  # type: ignore[method-assign]
    res = await _go(store, a, b)
    assert a.recommended_version == "1.0.0"
    assert res.converged
    # first scan + up to _MAX_SOURCE_CANDIDATES walked candidates (+ rescans)
    assert (
        len({c for c in calls if c.startswith("a==")}) <= da._MAX_SOURCE_CANDIDATES + 3
    )


async def test_duplicate_declarations_keep_their_own_proposal_when_clean() -> None:
    store = _store({"a": ["1.0.0", "1.2.0", "1.5.0"]})
    first, second = _pkg("a", "1.0.0", "1.5.0"), _pkg("a", "1.0.0", "1.2.0")
    res = await _go(store, first, second)
    assert (first.recommended_version, second.recommended_version) == ("1.5.0", "1.2.0")
    assert res.total_packages == 2 and len(res.resolved_versions) == 1


async def test_empty_input() -> None:
    res = await _go(_store({}))
    assert res.resolved_versions == {} and res.converged
    assert res.total_packages == 0 and res.iterations_used == 1
    assert "Total packages: 0" in res.summary()


async def test_target_python_filters_stepped_back_sources() -> None:
    # a 1.1 fits b but needs a newer Python than the target, so 1.0 wins.
    store = FakePyPIStore(
        {
            "a": package_data(
                "a", ["1.0.0", "1.1.0", "1.2.0"], requires_python={"1.1.0": ">=3.12"}
            ),
            "b": package_data("b", ["1.0.0"]),
        },
        dependencies={"a==1.2.0": ["b>=2"], "a==1.1.0": ["b<2"], "a==1.0.0": ["b<2"]},
    )
    a, b = _pkg("a", "1.0.0", "1.2.0"), _pkg("b", "1.0.0", "1.0.0")
    await _go(store, a, b, target_python="3.9")
    assert a.recommended_version == "1.0.0"
    a2, b2 = _pkg("a", "1.0.0", "1.2.0"), _pkg("b", "1.0.0", "1.0.0")
    await _go(store, a2, b2, target_python="3.13")
    assert a2.recommended_version == "1.1.0"


def test_final_conflicts_listed_once_in_stable_order() -> None:
    """Stale per-iteration duplicates collapse to one entry per requirement."""
    from depkeeper.core.dependency_analyzer import _live_conflicts
    from depkeeper.models.conflict import Conflict

    def c(ver: str) -> Conflict:
        return Conflict("flask", "werkzeug", ">=3.0.0", ver, "3.1.0")

    out = _live_conflicts(
        {"flask": "3.1.0", "werkzeug": "2.0.0"},
        "werkzeug",
        "2.0.0",
        [c("2.3.8"), c("2.0.0")],
    )
    assert [x.conflicting_version for x in out] == ["2.0.0"]
