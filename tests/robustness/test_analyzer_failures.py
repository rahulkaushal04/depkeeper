"""Failure injection and scale tests for the dependency analyzer."""

from __future__ import annotations

import asyncio
import random
import time
from typing import Dict, List

import pytest

from depkeeper.core.dependency_analyzer import DependencyAnalyzer
from depkeeper.exceptions import NetworkError, PyPIError
from depkeeper.models.package import Package
from tests.support.pypi import FakePyPIStore, package_data


def _pkg(name: str, cur: str, rec: str) -> Package:
    return Package(name=name, current_version=cur, recommended_version=rec)


def _store() -> FakePyPIStore:
    return FakePyPIStore(
        {
            "a": package_data("a", ["1.0.0", "1.5.0"]),
            "b": package_data("b", ["1.0.0", "1.2.0"]),
            "c": package_data("c", ["1.0.0", "1.1.0"]),
        },
        dependencies={"a==1.5.0": ["b>=2"], "c==1.1.0": ["b>=1.2"]},
    )


def _trio() -> List[Package]:
    return [
        _pkg("a", "1.0.0", "1.5.0"),
        _pkg("b", "1.0.0", "1.2.0"),
        _pkg("c", "1.0.0", "1.1.0"),
    ]


async def test_a_failing_dependency_lookup_only_hides_that_version() -> None:
    store = _store()
    original = store.get_version_dependencies

    async def flaky(name: str, version: str) -> List[str]:
        if (name, version) == ("a", "1.5.0"):
            raise NetworkError("boom", url="https://pypi.org")
        return await original(name, version)

    store.get_version_dependencies = flaky  # type: ignore[method-assign]
    pkgs = _trio()
    res = await DependencyAnalyzer(store).resolve_and_annotate_conflicts(pkgs)
    assert [p.recommended_version for p in pkgs] == ["1.5.0", "1.2.0", "1.1.0"]
    assert res.converged


async def test_unreachable_package_forces_a_safe_fallback_for_its_dependents() -> None:
    store = _store()
    del store.available["a"]  # a's metadata is unreachable, its 1.5.0 still needs b>=2
    pkgs = _trio()
    res = await DependencyAnalyzer(store).resolve_and_annotate_conflicts(pkgs)
    # a cannot step back and b has no 2.x: both revert; c (needs b>=1.2) follows.
    assert [p.recommended_version for p in pkgs] == ["1.0.0", "1.0.0", "1.0.0"]
    assert res.converged


async def test_unreachable_unrelated_package_does_not_disturb_the_rest() -> None:
    store = _store()
    del store.available["c"]
    pkgs = _trio()
    res = await DependencyAnalyzer(store).resolve_and_annotate_conflicts(pkgs)
    assert (pkgs[0].recommended_version, pkgs[1].recommended_version) == (
        "1.0.0",
        "1.2.0",
    )
    assert res.total_packages == 3


async def test_unexpected_store_error_leaves_every_package_untouched() -> None:
    store = _store()

    async def broken(name: str, version: str) -> List[str]:
        if name == "c":
            raise RuntimeError("bug in store")
        return await FakePyPIStore.get_version_dependencies(store, name, version)

    store.get_version_dependencies = broken  # type: ignore[method-assign]
    pkgs = _trio()
    with pytest.raises(RuntimeError):
        await DependencyAnalyzer(store).resolve_and_annotate_conflicts(pkgs)
    assert [p.recommended_version for p in pkgs] == ["1.5.0", "1.2.0", "1.1.0"]
    assert not any(p.conflicts or p.conflict_held for p in pkgs)


async def test_non_pypi_error_subclass_is_swallowed_like_any_network_error() -> None:
    store = _store()
    store.error = PyPIError("nope", package_name="x")
    del store.available["b"]
    res = await DependencyAnalyzer(store).resolve_and_annotate_conflicts(_trio())
    assert res.total_packages == 3


async def test_cancellation_during_prefetch_propagates_and_changes_nothing() -> None:
    store = _store()

    async def slow(names: List[str]) -> None:
        await asyncio.sleep(30)

    store.prefetch_packages = slow  # type: ignore[method-assign]
    pkgs = _trio()
    task = asyncio.ensure_future(
        DependencyAnalyzer(store).resolve_and_annotate_conflicts(pkgs)
    )
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [p.recommended_version for p in pkgs] == ["1.5.0", "1.2.0", "1.1.0"]


async def test_cancellation_mid_resolution_changes_nothing() -> None:
    store = _store()
    gate = asyncio.Event()
    original = store.get_version_dependencies

    async def hang(name: str, version: str) -> List[str]:
        if name == "c":
            gate.set()
            await asyncio.sleep(30)
        return await original(name, version)

    store.get_version_dependencies = hang  # type: ignore[method-assign]
    pkgs = _trio()
    task = asyncio.ensure_future(
        DependencyAnalyzer(store).resolve_and_annotate_conflicts(pkgs)
    )
    await gate.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [p.recommended_version for p in pkgs] == ["1.5.0", "1.2.0", "1.1.0"]


async def test_keyboard_interrupt_is_not_swallowed() -> None:
    store = _store()

    async def interrupt(name: str, version: str) -> List[str]:
        raise KeyboardInterrupt

    store.get_version_dependencies = interrupt  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt):
        await DependencyAnalyzer(store).resolve_and_annotate_conflicts(_trio())


def test_data_store_none_is_rejected() -> None:
    with pytest.raises(TypeError):
        DependencyAnalyzer(None)  # type: ignore[arg-type]


def _big_ecosystem(n: int, seed: int) -> "tuple[FakePyPIStore, List[Package]]":
    rnd = random.Random(seed)
    versions = ["1.0.0", "1.1.0", "1.2.0"]
    deps: Dict[str, List[str]] = {}
    for i in range(n):
        for v in versions:
            deps["p%d==%s" % (i, v)] = [
                "p%d%s"
                % (rnd.randrange(n), rnd.choice([">=1.1", "<1.2", "==1.1.0", ""]))
                for _ in range(2)
            ]
    store = FakePyPIStore(
        {"p%d" % i: package_data("p%d" % i, versions) for i in range(n)},
        dependencies=deps,
    )
    return store, [_pkg("p%d" % i, "1.0.0", "1.2.0") for i in range(n)]


def test_500_packages_resolve_quickly_and_deterministically() -> None:
    store, pkgs = _big_ecosystem(500, 7)
    started = time.perf_counter()
    res = asyncio.run(DependencyAnalyzer(store).resolve_and_annotate_conflicts(pkgs))
    assert time.perf_counter() - started < 20
    assert res.iterations_used <= 100
    again_store, again = _big_ecosystem(500, 7)
    asyncio.run(DependencyAnalyzer(again_store).resolve_and_annotate_conflicts(again))
    assert [p.recommended_version for p in pkgs] == [
        p.recommended_version for p in again
    ]
    assert all(p.recommended_version in ("1.0.0", "1.1.0", "1.2.0") for p in pkgs)


def test_long_chain_of_cascading_fixes_stays_within_the_cap() -> None:
    n = 120
    versions = ["1.0.0", "1.1.0"]
    deps = {"p%d==1.1.0" % i: ["p%d==1.0.0" % (i + 1)] for i in range(n - 1)}
    store = FakePyPIStore(
        {"p%d" % i: package_data("p%d" % i, versions) for i in range(n)},
        dependencies=deps,
    )
    pkgs = [_pkg("p%d" % i, "1.0.0", "1.1.0") for i in range(n)]
    res = asyncio.run(DependencyAnalyzer(store).resolve_and_annotate_conflicts(pkgs))
    assert res.iterations_used <= 100
    assert res.converged
    # every p_i at 1.1.0 forces p_{i+1} to 1.0.0, so no two neighbours are both 1.1.0
    ranks = [p.recommended_version for p in pkgs]
    assert not any(a == b == "1.1.0" for a, b in zip(ranks, ranks[1:]))


async def test_failed_dependency_lookups_are_reported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _store()
    original = store.get_version_dependencies

    async def flaky(name: str, version: str) -> List[str]:
        if name in ("a", "c"):
            raise NetworkError("boom", url="https://pypi.org")
        return await original(name, version)

    store.get_version_dependencies = flaky  # type: ignore[method-assign]
    with caplog.at_level("WARNING"):
        res = await DependencyAnalyzer(store).resolve_and_annotate_conflicts(_trio())
    assert sorted(res.dependency_lookup_failures) == ["a", "c"]
    assert not res.conflict_check_complete
    warns = [r for r in caplog.records if "conflict check incomplete" in r.getMessage()]
    assert len(warns) == 1


async def test_complete_run_reports_no_lookup_failures() -> None:
    res = await DependencyAnalyzer(_store()).resolve_and_annotate_conflicts(_trio())
    assert res.dependency_lookup_failures == [] and res.conflict_check_complete


async def test_failures_do_not_leak_into_the_next_run() -> None:
    store = _store()
    original = store.get_version_dependencies
    broken = {"on": True}

    async def flaky(name: str, version: str) -> List[str]:
        if broken["on"] and name == "a":
            raise NetworkError("boom", url="https://pypi.org")
        return await original(name, version)

    store.get_version_dependencies = flaky  # type: ignore[method-assign]
    analyzer = DependencyAnalyzer(store)
    first = await analyzer.resolve_and_annotate_conflicts(_trio())
    broken["on"] = False
    second = await analyzer.resolve_and_annotate_conflicts(_trio())
    assert first.dependency_lookup_failures == ["a"]
    assert second.dependency_lookup_failures == []


def test_warning_helper_and_envelope(capsys: pytest.CaptureFixture[str]) -> None:
    from depkeeper.commands import _report
    from depkeeper.core import ResolutionResult

    ok = ResolutionResult({}, 0, 0, 0, True)
    _report.warn_conflict_check_incomplete(ok)
    assert capsys.readouterr().err == ""
    bad = ResolutionResult({}, 2, 0, 1, True, dependency_lookup_failures=["a", "b"])
    _report.warn_conflict_check_incomplete(bad)
    err = " ".join(capsys.readouterr().err.split())
    assert (
        "Conflict check incomplete: dependency metadata unavailable for 2 package(s): a, b"
        in err
    )
    env = _report.build_envelope([], (None, "x"), conflict_check_complete=False)
    assert env["summary"]["conflict_check_complete"] is False
    assert _report.build_envelope([], (None, "x"))["summary"]["conflict_check_complete"]
