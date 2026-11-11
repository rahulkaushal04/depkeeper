"""Opt-in major upgrades: checker boundary, analyzer search, major_available."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

import pytest

from depkeeper.config import PackagePolicy
from depkeeper.core.checker import VersionChecker
from depkeeper.core.dependency_analyzer import _boundary, _UNBOUNDED
from depkeeper.models import Package
from tests.support.pypi import FakePyPIStore, package_data

DJANGO = ["3.2.25", "4.2.16", "5.0.1"]
RANGE = [(">=", "3.2"), ("<", "5.0")]


def _checker(versions: List[str] = DJANGO, **kw: Any) -> VersionChecker:
    return VersionChecker(
        FakePyPIStore({"django": package_data("django", versions)}), **kw
    )


@pytest.mark.asyncio
async def test_default_stays_in_major_and_reports_major_available() -> None:
    pkg = await _checker().get_package_info("django", "3.2", RANGE)
    assert pkg.recommended_version == "3.2.25"
    assert pkg.major_available == "4.2.16"


@pytest.mark.asyncio
async def test_opt_in_crosses_major_but_respects_declared_upper_bound() -> None:
    pkg = await _checker(allow_major=["Django"]).get_package_info(
        "django", "3.2", RANGE
    )
    assert pkg.recommended_version == "4.2.16"
    assert pkg.major_available is None  # 5.0.1 violates the user's own "<5.0"


@pytest.mark.asyncio
async def test_unbounded_spec_opt_in_takes_newest() -> None:
    pkg = await _checker(allow_major=["django"]).get_package_info("django", "3.2", [])
    assert pkg.recommended_version == "5.0.1"
    assert pkg.major_available is None


@pytest.mark.asyncio
async def test_star_applies_to_everything() -> None:
    pkg = await _checker(allow_major=["*"]).get_package_info("django", "3.2", [])
    assert pkg.recommended_version == "5.0.1"


@pytest.mark.asyncio
async def test_policy_allow_major() -> None:
    c = _checker(policies={"django": PackagePolicy(allow_major=True)})
    pkg = await c.get_package_info("django", "3.2", [])
    assert pkg.recommended_version == "5.0.1"


@pytest.mark.asyncio
async def test_cap_below_major_wins_and_is_reported() -> None:
    c = _checker(
        allow_major=["django"], policies={"django": PackagePolicy(max_update="minor")}
    )
    pkg = await c.get_package_info("django", "3.2", [])
    assert pkg.recommended_version == "3.2.25"
    assert pkg.major_available == "5.0.1"


@pytest.mark.asyncio
async def test_requires_python_still_filters_under_opt_in() -> None:
    d = package_data(
        "django", DJANGO, requires_python={"5.0.1": ">=3.10", "4.2.16": ">=3.8"}
    )
    c = VersionChecker(
        FakePyPIStore({"django": d}), target_python="3.9", allow_major=["django"]
    )
    pkg = await c.get_package_info("django", "3.2", [])
    assert pkg.recommended_version == "4.2.16"


@pytest.mark.asyncio
async def test_cooldown_still_filters_under_opt_in() -> None:
    now = datetime(2025, 1, 10, tzinfo=timezone.utc)
    d = package_data("django", DJANGO)
    d.upload_times = {
        "3.2.25": now - timedelta(days=900),
        "4.2.16": now - timedelta(days=100),
        "5.0.1": now - timedelta(days=1),
    }
    c = VersionChecker(
        FakePyPIStore({"django": d}),
        allow_major=["django"],
        min_age=timedelta(days=7),
        clock=lambda: now,
    )
    pkg = await c.get_package_info("django", "3.2", [])
    assert pkg.recommended_version == "4.2.16"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "policy", [PackagePolicy(hold=True), PackagePolicy(ignore=True)]
)
async def test_opt_in_on_held_or_ignored_does_nothing(policy: PackagePolicy) -> None:
    policy.allow_major = True
    pkg = await _checker(policies={"django": policy}).get_package_info(
        "django", "3.2", []
    )
    assert pkg.recommended_version == "3.2"
    assert pkg.major_available is None


@pytest.mark.asyncio
async def test_calver_unchanged() -> None:
    store = FakePyPIStore({"black": package_data("black", ["23.12.0", "24.1.0"])})
    pkg = await VersionChecker(store, allow_major=["black"]).get_package_info(
        "black", "23.12.0"
    )
    assert pkg.recommended_version == "24.1.0"
    assert pkg.major_available is None


@pytest.mark.asyncio
@pytest.mark.parametrize("current", ["3.2", "4.2.0", None])
async def test_default_recommendation_identical_without_opt_in(
    current: Optional[str],
) -> None:
    # Regression: opting in elsewhere must not change another package, and
    # no opt-in must keep the old recommendation.
    plain = await _checker().get_package_info("django", current, RANGE)
    other = await _checker(allow_major=["flask"]).get_package_info(
        "django", current, RANGE
    )
    assert other.recommended_version == plain.recommended_version
    expected = {"3.2": "3.2.25", "4.2.0": "4.2.16", None: "4.2.16"}[current]
    assert plain.recommended_version == expected


def test_analyzer_boundary_honours_opt_in() -> None:
    pkg = Package(name="django", current_version="3.2")
    assert _boundary(pkg) == 3
    assert _boundary(pkg, _checker(allow_major=["django"])) == _UNBOUNDED
    assert _boundary(pkg, _checker(allow_major=["flask"])) == 3


def test_package_major_available_serialised_only_when_set() -> None:
    p = Package(name="a", current_version="1.0", recommended_version="1.1")
    assert "major_available" not in p.to_json()
    p.major_available = "2.0"
    assert p.to_json()["major_available"] == "2.0"


@pytest.mark.asyncio
async def test_cli_cap_picks_best_in_cap_version_and_reports_major() -> None:
    c = _checker(
        ["3.2.25", "3.3.0", "4.2.16"], allow_major=["django"], max_update="minor"
    )
    pkg = await c.get_package_info("django", "3.2", [])
    assert pkg.recommended_version == "3.3.0"
    assert pkg.major_available == "4.2.16"
    assert pkg.major_capped is True


@pytest.mark.asyncio
async def test_cli_cap_applies_without_opt_in() -> None:
    # The cap picks the best version within it for every package.
    c = _checker(["3.2.25", "3.3.0"], max_update="patch")
    pkg = await c.get_package_info("django", "3.2", [])
    assert pkg.recommended_version == "3.2.25"


@pytest.mark.asyncio
async def test_not_capped_flag_without_opt_in() -> None:
    pkg = await _checker().get_package_info("django", "3.2", RANGE)
    assert pkg.major_available == "4.2.16"
    assert pkg.major_capped is False


def test_compatible_release_stays_valid_when_crossing_major() -> None:
    from depkeeper.utils.version_utils import rewrite_version_specs

    assert rewrite_version_specs([("~=", "2.0")], "3.1.2") == [("~=", "3.1")]
    assert rewrite_version_specs([("~=", "3.2.0")], "6.0.4") == [("~=", "6.0.4")]


# --- `~=` implies an upper bound the user declared -------------------------

CLICK = ["7.1.2", "7.9.0", "8.1.7"]


def _click(**kw: Any) -> VersionChecker:
    return VersionChecker(FakePyPIStore({"click": package_data("click", CLICK)}), **kw)


async def _check(specs: List[Any], **kw: Any) -> Package:
    from depkeeper.models import Requirement

    req = Requirement(name="click", specs=specs)
    return await _click(**kw)._create_package_check_task(req)


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", ["7.0", "7.0.2", "7"])
async def test_compatible_release_bound_never_crossed(spec: str) -> None:
    for kw in ({}, {"allow_major": ["click"]}):
        pkg = await _check([("~=", spec)], **kw)
        assert (pkg.recommended_version or "").startswith("7."), (spec, kw)
        assert pkg.major_available is None, (spec, kw)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "specs,opt_rec,default_avail",
    [
        ([("==", "7.1.2")], "8.1.7", "8.1.7"),
        ([(">=", "7.0"), ("<", "9")], "8.1.7", "8.1.7"),
        ([(">=", "7.0"), ("<=", "8.5")], "8.1.7", "8.1.7"),
        ([(">=", "7.0"), ("!=", "8.1.7")], "7.9.0", None),
    ],
)
async def test_other_operators_unchanged(
    specs: List[Any], opt_rec: str, default_avail: Optional[str]
) -> None:
    assert (await _check(specs, allow_major=["click"])).recommended_version == opt_rec
    assert (await _check(specs)).major_available == default_avail
