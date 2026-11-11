"""Conflict resolution honours cooldown, per-package policy and target Python."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import pytest

from depkeeper.config import PackagePolicy
from depkeeper.core.checker import VersionChecker
from depkeeper.core.data_store import PyPIPackageData
from depkeeper.core.dependency_analyzer import DependencyAnalyzer, ResolutionResult
from depkeeper.models.package import Package
from tests.support.pypi import FakePyPIStore, package_data

NOW = datetime(2025, 1, 10, tzinfo=timezone.utc)


def _ages(data: PyPIPackageData, **ages: int) -> PyPIPackageData:
    data.upload_times = {
        v.replace("_", "."): NOW - timedelta(days=a) for v, a in ages.items()
    }
    return data


def _setup(
    *,
    dep: str = "b<1.5",
    policies: Optional[Dict[str, PackagePolicy]] = None,
    min_age: Optional[timedelta] = timedelta(days=30),
    b_versions: Optional[List[str]] = None,
    b_ages: Optional[Dict[str, int]] = None,
) -> Tuple[FakePyPIStore, VersionChecker]:
    """a 1.0 depends on b<1.5; b has an old 1.9 and a very fresh 1.4.1 backport."""
    b = _ages(
        package_data("b", b_versions or ["1.2", "1.3", "1.4.1", "1.9"]),
        **(b_ages or {"1_2": 400, "1_3": 300, "1_4_1": 2, "1_9": 100}),
    )
    store = FakePyPIStore(
        {"a": package_data("a", ["1.0"]), "b": b},
        dependencies={"a==1.0": [dep]},
    )
    checker = VersionChecker(
        store, min_age=min_age, policies=policies, clock=lambda: NOW
    )
    return store, checker


async def _pkgs(checker: VersionChecker) -> List[Package]:
    a = await checker.get_package_info("a", "1.0")
    b = await checker.get_package_info("b", "1.0.0")
    return [a, b]


async def _resolve(
    store: FakePyPIStore, checker: VersionChecker, pkgs: List[Package]
) -> ResolutionResult:
    analyzer = DependencyAnalyzer(store, checker=checker)
    return await analyzer.resolve_and_annotate_conflicts(pkgs)


@pytest.mark.asyncio
async def test_backport_cannot_bypass_cooldown() -> None:
    store, checker = _setup()
    pkgs = await _pkgs(checker)
    b = pkgs[1]
    assert b.recommended_version == "1.9"  # 100d old, outside window
    await _resolve(store, checker, pkgs)
    # 1.4.1 satisfies <1.5 but is 2d old: the analyzer must take 1.3 instead.
    assert b.recommended_version == "1.3"
    assert b.recommended_released == NOW - timedelta(days=300)


@pytest.mark.asyncio
async def test_without_checker_old_behaviour_unchanged() -> None:
    store, checker = _setup()
    pkgs = await _pkgs(checker)
    await DependencyAnalyzer(store).resolve_and_annotate_conflicts(pkgs)
    assert pkgs[1].recommended_version == "1.4.1"


@pytest.mark.asyncio
async def test_cooldown_skipped_consistent_after_move() -> None:
    # The 1.9 proposal was fine; but if 1.9 itself were fresh, skipped=1.9 and
    # the analyzer moving to 1.3 must keep describing a withheld newer version.
    store, checker = _setup(b_ages={"1_2": 400, "1_3": 300, "1_4_1": 2, "1_9": 5})
    pkgs = await _pkgs(checker)
    b = pkgs[1]
    assert b.recommended_version == "1.3" and b.cooldown_skipped == "1.9"
    await _resolve(store, checker, pkgs)
    assert b.recommended_version == "1.3"
    assert b.cooldown_skipped == "1.9"


@pytest.mark.asyncio
async def test_cooldown_skipped_cleared_when_not_newer_than_resolved() -> None:
    store, checker = _setup()
    pkgs = await _pkgs(checker)
    b = pkgs[1]
    b.cooldown_skipped = "1.2"  # stale: older than whatever is resolved
    await _resolve(store, checker, pkgs)
    assert b.cooldown_skipped is None


@pytest.mark.asyncio
async def test_hold_policy_blocks_analyzer_move() -> None:
    store, checker = _setup(min_age=None, policies={"b": PackagePolicy(hold=True)})
    pkgs = await _pkgs(checker)
    await _resolve(store, checker, pkgs)
    assert pkgs[1].recommended_version == "1.0.0"


@pytest.mark.asyncio
async def test_max_update_policy_applies_to_analyzer() -> None:
    # a forbids 1.2.1; without the cap the analyzer would jump to 1.9.
    store, checker = _setup(
        dep="b!=1.2.1",
        min_age=None,
        policies={"b": PackagePolicy(max_update="patch")},
        b_versions=["1.2", "1.2.1", "1.3", "1.4.1", "1.9"],
        b_ages={"1_2": 400, "1_2_1": 300, "1_3": 200, "1_4_1": 100, "1_9": 50},
    )
    a = await checker.get_package_info("a", "1.0")
    b = await checker.get_package_info("b", "1.2")
    assert b.recommended_version == "1.2.1"
    await _resolve(store, checker, [a, b])
    assert b.recommended_version == "1.2"  # not 1.9: patch cap still holds


@pytest.mark.asyncio
async def test_prerelease_only_with_policy() -> None:
    versions = ["1.2", "1.4", "1.4.1rc1", "1.9"]
    ages = {"1_2": 400, "1_4": 300, "1_4_1rc1": 200, "1_9": 100}
    store, checker = _setup(min_age=None, b_versions=versions, b_ages=ages)
    pkgs = await _pkgs(checker)
    await _resolve(store, checker, pkgs)
    assert pkgs[1].recommended_version == "1.4"

    store, checker = _setup(
        min_age=None,
        b_versions=versions,
        b_ages=ages,
        policies={"b": PackagePolicy(allow_prerelease=True)},
    )
    pkgs = await _pkgs(checker)
    await _resolve(store, checker, pkgs)
    assert pkgs[1].recommended_version == "1.4.1rc1"


@pytest.mark.asyncio
async def test_analyzer_target_python_is_used() -> None:
    b = package_data(
        "b",
        ["1.2", "1.3", "1.4"],
        requires_python={"1.4": ">=3.10", "1.2": None, "1.3": None},
    )
    store = FakePyPIStore({"b": b})
    analyzer = DependencyAnalyzer(store, target_python="3.8")
    await store.get_package_data("b")
    assert await analyzer._find_constrained_target_within_major("b", 1, "<1.5") == "1.3"
