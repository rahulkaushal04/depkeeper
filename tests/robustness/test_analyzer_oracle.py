"""Seeded brute-force oracle for cross-package conflict resolution."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

import pytest
from packaging.requirements import Requirement as PkgReq
from packaging.specifiers import SpecifierSet
from packaging.version import parse

from depkeeper.config import PackagePolicy
from depkeeper.core.checker import VersionChecker
from depkeeper.core.dependency_analyzer import (
    _MAX_RESOLUTION_ITERATIONS,
    DependencyAnalyzer,
    ResolutionResult,
)
from depkeeper.models import Requirement
from depkeeper.models.package import Package
from tests.support.pypi import FakePyPIStore, package_data

NOW = datetime(2025, 1, 1, tzinfo=timezone.utc)
TARGET = "3.10"
_CALVER_SPECS = [
    "",
    ">=2024",
    ">=2024.2",
    "<2025",
    "<2024.3",
    "==2024.1.0",
    "!=2023.1.0",
]
_DEP_SPECS = [
    "",
    ">=1.1",
    ">=2",
    "<2",
    ">=1.2,<2",
    "==1.2.0",
    "!=1.1.0",
    ">=2.1",
    "<1.3",
]
# Mostly-satisfiable dependency specs for the properties that need a settled case.
_SOFT_SPECS = ["", "", ">=1.0", "<3", ">=1.0,<3", "!=9.9"]
_RP = [None, None, ">=3.8", ">=3.11", "<3.10", ">=3.9,<3.12"]


@dataclass
class Eco:
    """A random synthetic ecosystem plus the file that declares part of it."""

    versions: Dict[str, List[str]] = field(default_factory=dict)
    rp: Dict[str, Dict[str, Optional[str]]] = field(default_factory=dict)
    ages: Dict[str, Dict[str, int]] = field(default_factory=dict)
    deps: Dict[str, List[str]] = field(default_factory=dict)
    reqs: List[Requirement] = field(default_factory=list)
    policies: Dict[str, PackagePolicy] = field(default_factory=dict)
    min_age: Optional[timedelta] = None
    allow_major: Tuple[str, ...] = ()
    max_update: Optional[str] = None

    def store(self) -> FakePyPIStore:
        avail = {}
        for n, vs in self.versions.items():
            d = package_data(n, vs, requires_python=self.rp[n])
            d.upload_times = {v: NOW - timedelta(days=self.ages[n][v]) for v in vs}
            avail[n] = d
        return FakePyPIStore(avail, dependencies=self.deps)


def gen(
    seed: int, *, policies: bool = True, calver: bool = False, soft: bool = False
) -> Eco:
    rnd = random.Random(seed)
    eco = Eco()
    n = rnd.randint(2, 6)
    names = ["p%d" % i for i in range(n)]
    for name in names:
        vs = sorted(
            {
                (
                    "%d.%d.0" % (rnd.randint(2023, 2025), rnd.randint(1, 3))
                    if calver
                    else "%d.%d.0" % (rnd.randint(1, 2), rnd.randint(0, 3))
                )
                for _ in range(rnd.randint(2, 6))
            }
            | ({"2.0.0rc1"} if rnd.random() < 0.15 else set()),
            key=parse,
        )
        eco.versions[name] = vs
        eco.rp[name] = {v: rnd.choice(_RP) for v in vs}
        eco.ages[name] = {v: rnd.choice([1, 5, 40, 400]) for v in vs}
    for name in names:
        for v in eco.versions[name]:
            deps = []
            for other in names + ["ghost"]:
                if rnd.random() < (0.05 if other == name else 0.4 if not soft else 0.2):
                    pool = _CALVER_SPECS if calver else _DEP_SPECS
                    if soft and other == "ghost":
                        pool = [""]
                    elif soft and rnd.random() < 0.9:
                        pool = _SOFT_SPECS
                    deps.append(other + rnd.choice(pool))
            eco.deps["%s==%s" % (name, v)] = deps
    for name in names:
        if rnd.random() < 0.15:
            continue  # not declared: only a dependency target
        stable = [v for v in eco.versions[name] if not parse(v).is_prerelease]
        cur = rnd.choice(stable)
        specs = rnd.choice(
            [
                [("==", cur)],
                [("==", cur)],
                [(">=", cur)],
                [(">=", cur), ("<", "%d" % (parse(cur).major + 1))],
                [(">=", cur), ("!=", "1.2.0")],
            ]
        )
        eco.reqs.append(Requirement(name=name, specs=specs))
    if policies:
        for name in names:
            r = rnd.random()
            if r < 0.1:
                eco.policies[name] = PackagePolicy(hold=True)
            elif r < 0.15:
                eco.policies[name] = PackagePolicy(ignore=True)
            elif r < 0.25:
                eco.policies[name] = PackagePolicy(max_update="minor")
            elif r < 0.3:
                eco.policies[name] = PackagePolicy(allow_prerelease=True)
            elif r < 0.4:
                eco.policies[name] = PackagePolicy(allow_major=True)
        if rnd.random() < 0.3:
            eco.min_age = timedelta(days=30)
        if rnd.random() < 0.15:
            eco.allow_major = (rnd.choice(names),)
    return eco


async def run(eco: Eco, order: Optional[Sequence[int]] = None):
    store = eco.store()
    checker = VersionChecker(
        store,
        target_python=TARGET,
        policies=eco.policies,
        min_age=eco.min_age,
        clock=lambda: NOW,
        allow_major=eco.allow_major,
    )
    reqs = list(eco.reqs)
    if order is not None:
        reqs = [reqs[i] for i in order]
    pkgs = await checker.check_packages(reqs)
    before = {p.name: (p.current_version, p.recommended_version) for p in pkgs}
    res = await DependencyAnalyzer(
        store, target_python=TARGET, checker=checker
    ).resolve_and_annotate_conflicts(pkgs)
    return pkgs, before, res, checker


def violations(eco: Eco, final: Dict[str, Optional[str]]) -> List[Tuple[str, str, str]]:
    """Independent re-derivation of every cross-package violation."""
    out = []
    for name, ver in final.items():
        if not ver:
            continue
        for dep in eco.deps.get("%s==%s" % (name, ver), []):
            r = PkgReq(dep)
            tgt = final.get(r.name) if r.name != name else None
            if (
                tgt
                and r.specifier
                and not r.specifier.contains(parse(tgt), prereleases=True)
            ):
                out.append((name, dep, r.name))
    return out


def check_invariants(
    eco: Eco, pkgs: List[Package], before, res: ResolutionResult, checker
) -> None:
    final = {p.name: p.recommended_version for p in pkgs}
    for p in pkgs:
        cur, rec0 = before[p.name]
        r = p.recommended_version
        assert r is not None
        pol = eco.policies.get(p.name, PackagePolicy())
        base = min(parse(x) for x in (cur, rec0) if x)
        if parse(r) < base:
            assert res.resolved_versions[p.name].conflicts, (p.name, cur, rec0, r)
        if (pol.hold and cur) or pol.ignore:
            assert r == rec0, (p.name, cur, rec0, r)
        if r not in (cur, rec0):
            if (
                cur is not None
                and p.versioning != "calver"
                and not checker.allows_major(p.name)
            ):
                assert parse(r).major == parse(cur).major, (p.name, cur, rec0, r)
            rp = eco.rp[p.name][r]
            assert rp is None or TARGET in SpecifierSet(rp), (p.name, r, rp)
            retained = SpecifierSet(",".join(op + v for op, v in p.retained_specs))
            assert retained.contains(r, prereleases=True), (
                p.name,
                r,
                p.retained_specs,
            )
        if r not in (cur, rec0) and cur is not None and parse(r) > parse(cur):
            assert not pol.hold and not pol.ignore, (p.name, cur, rec0, r)
            if parse(r).is_prerelease:
                assert pol.allow_prerelease
            if eco.min_age is not None and cur is not None and parse(r) > parse(cur):
                assert (
                    NOW - (NOW - timedelta(days=eco.ages[p.name][r]))
                ) >= eco.min_age, (p.name, r)
            if pol.max_update == "minor" and cur and p.versioning != "calver":
                assert parse(r).major == parse(cur).major
        assert res.resolved_versions[p.name].resolved == r
    viol = violations(eco, final)
    assert res.converged == (not viol), viol
    if not res.converged:
        # every real violation is reported on its target
        for src, dep, tgt in viol:
            tp = next(x for x in pkgs if x.name == tgt)
            assert any(c.source_package == src for c in tp.conflicts), (src, dep, tgt)
    assert res.iterations_used <= _MAX_RESOLUTION_ITERATIONS


SEEDS = range(300)


def _final(pkgs: List[Package]) -> Dict[str, Optional[str]]:
    return {p.name: p.recommended_version for p in pkgs}


@pytest.mark.parametrize("seed", SEEDS)
def test_oracle(seed: int) -> None:
    eco = gen(seed)
    pkgs, before, res, checker = asyncio.run(run(eco))
    check_invariants(eco, pkgs, before, res, checker)


@pytest.mark.parametrize("seed", range(150))
def test_calver_oracle(seed: int) -> None:
    eco = gen(seed, calver=True)
    pkgs, before, res, checker = asyncio.run(run(eco))
    check_invariants(eco, pkgs, before, res, checker)


@pytest.mark.parametrize("seed", SEEDS)
def test_bookkeeping_matches_recorded_conflicts(seed: int) -> None:
    eco = gen(seed)
    pkgs, before, res, _ = asyncio.run(run(eco))
    final = _final(pkgs)
    recorded = {n: r.conflicts for n, r in res.resolved_versions.items()}
    assert res.total_packages == len(pkgs)
    assert res.packages_with_conflicts == sum(1 for c in recorded.values() if c)
    assert len(res.get_conflicts()) == res.packages_with_conflicts
    # "unresolved" counts what is still displayed, never the cumulative history
    assert res.packages_unresolved == sum(1 for p in pkgs if p.conflicts)
    assert res.packages_unresolved <= res.packages_with_conflicts
    for p in pkgs:
        assert p.conflict_held == bool(recorded[p.name])
        for c in p.conflicts:
            # only conflicts the final set really violates are shown
            assert c in recorded[p.name]
            assert final[c.source_package] == c.source_version
            req = next(
                PkgReq(d)
                for d in eco.deps["%s==%s" % (c.source_package, c.source_version)]
                if PkgReq(d).name == p.name
                and str(PkgReq(d).specifier) == c.required_spec
            )
            assert not req.specifier.contains(parse(final[p.name]), prereleases=True)
        assert p.recommended_version == res.resolved_versions[p.name].resolved
    assert 1 <= res.iterations_used <= _MAX_RESOLUTION_ITERATIONS


@pytest.mark.parametrize("seed", SEEDS)
def test_input_order_and_reruns_do_not_change_the_outcome(seed: int) -> None:
    eco = gen(seed)
    pkgs, _, res, _ = asyncio.run(run(eco))
    order = list(range(len(eco.reqs)))
    random.Random(seed).shuffle(order)
    pkgs2, _, res2, _ = asyncio.run(run(eco, order))
    pkgs3, _, res3, _ = asyncio.run(run(eco))
    assert _final(pkgs) == _final(pkgs2) == _final(pkgs3)
    assert res.converged == res2.converged == res3.converged
    assert {n: r.status for n, r in res.resolved_versions.items()} == {
        n: r.status for n, r in res2.resolved_versions.items()
    }


MIN_EFFECTIVE = 0.9


def test_consistent_proposals_are_left_alone() -> None:
    effective = 0
    for seed in SEEDS:
        eco = gen(seed, soft=True)
        store = eco.store()
        checker = VersionChecker(
            store,
            target_python=TARGET,
            policies=eco.policies,
            min_age=eco.min_age,
            clock=lambda: NOW,
            allow_major=eco.allow_major,
        )
        pkgs = asyncio.run(checker.check_packages(list(eco.reqs)))
        proposals = _final(pkgs)
        if violations(eco, proposals):
            continue  # counted below: the generator must make these rare
        effective += 1
        res = asyncio.run(
            DependencyAnalyzer(
                store, target_python=TARGET, checker=checker
            ).resolve_and_annotate_conflicts(pkgs)
        )
        assert _final(pkgs) == proposals, seed
        assert res.converged and res.packages_with_conflicts == 0, seed
        assert not res.get_changed_packages(), seed
    assert effective >= MIN_EFFECTIVE * len(SEEDS), effective


def test_a_converged_result_is_a_fixed_point() -> None:
    effective = 0
    for seed in SEEDS:
        eco = gen(seed, soft=True)
        pkgs, _, res, checker = asyncio.run(run(eco))
        if not res.converged:
            continue
        effective += 1
        before = _final(pkgs)
        again = asyncio.run(
            DependencyAnalyzer(
                eco.store(), target_python=TARGET, checker=checker
            ).resolve_and_annotate_conflicts(pkgs)
        )
        assert _final(pkgs) == before, seed
        assert again.converged and not again.get_changed_packages(), seed
    assert effective >= MIN_EFFECTIVE * len(SEEDS), effective


def test_a_clean_installed_set_is_never_left_broken() -> None:
    """If every package staying put is consistent, the resolver must end consistent."""
    effective = 0
    for seed in range(150):
        eco = gen(seed, soft=True)
        pkgs, before, res, _ = asyncio.run(run(eco))
        installed = {n: c for n, (c, _) in before.items()}
        if violations(eco, installed):
            continue
        effective += 1
        assert not violations(eco, _final(pkgs)), seed
        assert res.converged, seed
    assert effective >= MIN_EFFECTIVE * 150, effective
