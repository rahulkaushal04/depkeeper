"""Versioning detection, update types, gating, checker regressions and Package model."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytest

from depkeeper.config import PackagePolicy
from depkeeper.core.checker import VersionChecker
from depkeeper.models.package import Package
from depkeeper.utils.version_utils import (
    detect_versioning,
    gating_type,
    get_update_type,
    implied_major_bounds,
    specs_allow_version,
    update_rank,
)
from tests.robustness.test_recommend_datastore import FakeHttp, Resp, _store

NOW = datetime(2025, 6, 1, tzinfo=timezone.utc)
YY = dt.date.today().year % 100


def _hist(*versions: str) -> List[str]:
    return list(versions)


@pytest.mark.parametrize(
    "current,history,expected",
    [
        ("2024.8.30", _hist("2024.8.30"), "calver"),  # certifi
        (None, _hist("2025.1.31", "2024.12.14", "2024.8.30"), "calver"),
        ("2024.2", _hist("2024.2", "2023.4"), "calver"),  # tzdata / pytz
        ("2024.0.0", _hist("2024.0.0"), "calver"),  # documented 4-digit rule
        ("1990.1", _hist("1990.1"), "calver"),
        ("1989.1", _hist("1989.1"), "semver"),
        ("2100.1", _hist("2100.1"), "semver"),
        ("1.0", _hist("1.0"), "semver"),
        ("20.3", _hist("20.3", "20.2"), "semver"),  # lone YY.M is never guessed
        ("23.1.0", _hist("23.1.0"), "semver"),
        ("2.0.0", _hist("2.0.0"), "semver"),
        ("24.0", _hist("24.0", "23.3", "23.2", "9.0.1", "10.0.0"), "semver"),  # pip
        ("24.0", _hist("24.0", "23.3", "23.2", "23.1", "22.3", "1.0"), "semver"),
        (
            "24.2.0",
            _hist("24.2.0", "24.1.1", "23.12.1", "23.12.0", "23.11.0", "23.10.1"),
            "calver",  # black
        ),
        ("24.2.0", _hist("24.2.0", "24.1.1", "24.1.0", "24.3.0", "24.4.0"), "semver"),
        ("foo", _hist("2024.1", "2023.1"), "semver"),
        (None, [], "semver"),
        ("1!2024.1", _hist("1!2024.1"), "calver"),
    ],
)
def test_auto_detection(
    current: Optional[str], history: List[str], expected: str
) -> None:
    assert detect_versioning("auto", current, history) == expected


def test_detection_year_window_tracks_today() -> None:
    year = dt.date.today().year
    assert detect_versioning("auto", f"{year + 1}.1", []) == "calver"
    assert detect_versioning("auto", f"{year + 2}.1", []) == "semver"
    assert detect_versioning("auto", f"{year}.1.1", []) == "calver"


def test_yy_m_needs_five_releases_two_years_and_valid_months() -> None:
    a, b = YY, YY - 1
    ok = [f"{a}.1", f"{a}.2", f"{b}.12", f"{b}.11", f"{b}.10"]
    assert detect_versioning("auto", None, ok) == "calver"
    assert detect_versioning("auto", None, ok[:4]) == "semver"
    assert (
        detect_versioning("auto", None, [f"{a}.{m}" for m in (1, 2, 3, 4, 5)])
        == "semver"
    )
    assert detect_versioning("auto", None, ok[:4] + [f"{b}.13"]) == "semver"
    assert detect_versioning("auto", None, ok[:4] + [f"{YY + 2}.1"]) == "semver"
    assert detect_versioning("auto", None, ok[:4] + ["14.1"]) == "semver"


@pytest.mark.parametrize("mode", ["semver", "calver"])
def test_explicit_mode_wins(mode: str) -> None:
    assert detect_versioning(mode, "2024.1", ["2024.1"]) == mode
    assert detect_versioning(mode, "1.0", ["1.0"]) == mode


@pytest.mark.parametrize(
    "cur,tgt,scheme,expected",
    [
        (None, None, "semver", "unknown"),
        (None, "1.0", "semver", "new"),
        ("1.0", None, "semver", "unknown"),
        ("1.0", "1.0.0", "semver", "same"),
        ("1.0", "1.0.0.0", "semver", "same"),
        ("1.0", "0.9", "semver", "downgrade"),
        ("1.0", "2.0", "semver", "major"),
        ("1.0", "1.1", "semver", "minor"),
        ("1.0", "1.0.1", "semver", "patch"),
        ("1.0rc1", "1.0", "semver", "update"),
        ("1.0", "1.0.post1", "semver", "update"),
        ("1.0", "1.0+local", "semver", "update"),
        ("1.0+local", "1.0", "semver", "downgrade"),
        ("1.2.3.4", "1.2.3.5", "semver", "update"),
        ("1.0", "1!0.5", "semver", "major"),
        ("1!0.5", "9.0", "semver", "downgrade"),
        ("foo", "1.0", "semver", "unknown"),
        ("1.0", "bar", "semver", "unknown"),
        ("1.0", "2.*", "semver", "unknown"),
        ("2024.8.30", "2025.1.2", "calver", "year"),
        ("2024.8.30", "2024.9.1", "calver", "month"),
        ("2024.8.30", "2024.8.31", "calver", "patch"),
        ("2024.8", "2024.8.1", "calver", "patch"),
        ("2024.8.30", "2024.8.30.post1", "calver", "update"),
        ("2024.8.30", "2023.1", "calver", "downgrade"),
    ],
)
def test_update_type_table(cur: Any, tgt: Any, scheme: str, expected: str) -> None:
    assert get_update_type(cur, tgt, scheme) == expected


def test_gating_and_rank() -> None:
    assert [
        gating_type(x) for x in ("year", "month", "patch", "minor", "major", "update")
    ] == [
        "minor",
        "minor",
        "patch",
        "minor",
        "major",
        "update",
    ]
    assert [
        update_rank(x)
        for x in ("patch", "minor", "month", "major", "year", "update", "")
    ] == [0, 1, 1, 2, 2, -1, -1]


def test_specs_allow_version_per_spec_leniency() -> None:
    assert specs_allow_version([("<", "garbage"), ("<", "2")], "1.0")
    assert not specs_allow_version([("<", "garbage"), ("<", "2")], "2.5")
    assert specs_allow_version([("<", "2")], "weird-version")
    assert specs_allow_version([("<", "2")], "1.9rc1")
    assert not specs_allow_version([("<", "2")], "2.0")
    assert specs_allow_version([("!=", "1.*")], "2.0") and not specs_allow_version(
        [("!=", "1.*")], "1.5"
    )
    assert specs_allow_version([("===", "1.0")], "1.0") and not specs_allow_version(
        [("===", "1.0")], "1.0.0"
    )
    assert specs_allow_version([("~=", "1.4.2")], "1.4.9") and not specs_allow_version(
        [("~=", "1.4.2")], "1.5"
    )
    assert specs_allow_version([("<=", "1.0")], "1.0.post1") is False


def test_implied_major_bounds() -> None:
    assert implied_major_bounds(
        [("~=", "7.0"), (">=", "1"), ("~=", "bad"), ("~=", "1.4.2")]
    ) == [("<", "8"), ("<", "2")]


# ------------------------------------------------------------------ checker
def _checker(releases: Dict[str, Any], **kw: Any) -> Tuple[VersionChecker, Any]:
    store = _store(FakeHttp(lambda u: Resp()))
    data = store._parse_package_data(
        "x", {"info": {"version": None}, "releases": releases}
    )
    kw.setdefault("clock", lambda: NOW)
    return VersionChecker(store, **kw), data


def _rel(*pairs: Tuple[str, int]) -> Dict[str, Any]:
    return {
        v: [{"upload_time_iso_8601": (NOW - timedelta(days=d)).isoformat()}]
        for v, d in pairs
    }


def test_up_to_date_package_reports_no_cooldown_skip() -> None:
    chk, data = _checker(_rel(("1.0", 90), ("1.1", 2)), min_age=timedelta(days=7))
    pkg = chk._build_package_from_data(data, "1.1")
    assert pkg.recommended_version == "1.1" and pkg.cooldown_skipped is None
    assert "cooldown_skipped" not in pkg.to_json()
    pkg = chk._build_package_from_data(data, "1.0")
    assert pkg.recommended_version == "1.0" and pkg.cooldown_skipped == "1.1"


def test_current_newer_than_everything_is_not_reported_as_withheld() -> None:
    chk, data = _checker(_rel(("1.0", 90), ("1.1", 2)), min_age=timedelta(days=7))
    pkg = chk._build_package_from_data(data, "1.9")
    assert pkg.recommended_version == "1.9" and pkg.cooldown_skipped is None


def test_equal_valued_duplicates_are_not_a_withheld_release() -> None:
    chk, data = _checker(
        _rel(("2.2", 90), ("2.2.0", 90), ("2.1", 90)), min_age=timedelta(days=7)
    )
    pkg = chk._build_package_from_data(data, "2.1")
    assert pkg.cooldown_skipped is None


def test_one_malformed_constraint_does_not_disable_the_others() -> None:
    chk, data = _checker(_rel(("1.0", 90), ("1.5", 90), ("1.9", 90)))
    pkg = chk._build_package_from_data(data, "1.0", [("<", "1.6"), ("<", "???")])
    assert pkg.recommended_version == "1.5"


def test_wildcard_current_still_honours_max_update() -> None:
    chk, data = _checker(
        _rel(("1.0", 90), ("1.1.5", 90), ("1.2", 90)),
        policies={"x": PackagePolicy(max_update="patch")},
    )
    assert chk._build_package_from_data(data, "1.0.*").recommended_version == "1.0"


def test_series_never_recommends_below_current_across_epochs() -> None:
    chk, data = _checker({"1!1.2.1": [{}], "1.4.1": [{}]})
    pkg = chk._build_package_from_data(data, "1!1.2.1", series=2)
    assert pkg.recommended_version == "1!1.2.1"


def test_prerelease_python_target_is_compatible() -> None:
    chk, data = _checker(
        {"1.0": [{"requires_python": ">=3.8"}]}, target_python="3.13.0rc1"
    )
    assert chk._build_package_from_data(data, None).recommended_version == "1.0"


def test_ignore_and_hold_keep_current_and_flag() -> None:
    rel = _rel(("1.0", 90), ("1.5", 90))
    for pol, attr in (
        (PackagePolicy(hold=True), "held"),
        (PackagePolicy(ignore=True), "ignored"),
    ):
        chk, data = _checker(rel, policies={"x": pol})
        pkg = chk._build_package_from_data(data, "1.0")
        assert pkg.recommended_version == "1.0" and getattr(pkg, attr) is True
        assert not pkg.has_update()


def test_hold_without_current_version_cannot_hold() -> None:
    chk, data = _checker(
        _rel(("1.0", 90), ("1.5", 90)), policies={"x": PackagePolicy(hold=True)}
    )
    pkg = chk._build_package_from_data(data, None)
    assert pkg.recommended_version == "1.5" and pkg.held is False


def test_cooldown_clock_edge_exactly_min_age_is_eligible() -> None:
    chk, data = _checker(_rel(("1.0", 90), ("1.1", 7)), min_age=timedelta(days=7))
    assert chk._build_package_from_data(data, "1.0").recommended_version == "1.1"
    chk, data = _checker(
        {
            "1.0": [{}],
            "1.1": [
                {
                    "upload_time_iso_8601": (
                        NOW - timedelta(days=7) + timedelta(seconds=1)
                    ).isoformat()
                }
            ],
        },
        min_age=timedelta(days=7),
    )
    assert chk._build_package_from_data(data, "1.0").recommended_version == "1.0"


def test_future_upload_date_counts_as_new_and_garbled_as_old(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rel = {
        "1.0": [{"upload_time_iso_8601": NOW.isoformat()}],
        "1.1": [{"upload_time_iso_8601": (NOW + timedelta(days=30)).isoformat()}],
        "1.2": [{"upload_time_iso_8601": "garbage"}],
    }
    chk, data = _checker(rel, min_age=timedelta(days=7))
    with caplog.at_level(logging.WARNING):
        pkg = chk._build_package_from_data(data, "1.0")
    assert pkg.recommended_version == "1.2" and pkg.cooldown_skipped is None
    chk2, data2 = _checker(
        {k: v for k, v in rel.items() if k != "1.2"}, min_age=timedelta(days=7)
    )
    assert chk2._build_package_from_data(data2, "1.0").cooldown_skipped == "1.1"


def test_check_packages_requests_are_one_per_package() -> None:
    from depkeeper.models.requirement import Requirement

    calls: List[str] = []

    def handler(url: str) -> Any:
        calls.append(url)
        return Resp(
            200,
            {"info": {"version": "1.2"}, "releases": _rel(("1.0", 90), ("1.2", 90))},
        )

    store = _store(FakeHttp(handler))
    reqs = [
        Requirement(
            name=n, specs=[("==", "1.0")], line_number=i + 1, raw_line=f"{n}==1.0"
        )
        for i, n in enumerate(["A", "a", "A_"])
    ]
    pkgs = asyncio.run(VersionChecker(store).check_packages(reqs))
    assert [p.recommended_version for p in pkgs] == ["1.2"] * 3
    assert len(calls) == 2  # 'A' and 'a' coalesce; 'A_' normalizes to 'a-'


@pytest.mark.parametrize(
    "specs,strict,expected",
    [
        ([("==", "2.28.0")], False, "2.28.0"),
        ([("==", "2.28.0"), ("!=", "2.28.1")], False, "2.28.0"),
        ([("!=", "2.28.1"), ("==", "2.28.0")], True, "2.28.0"),
        ([("===", "2.28.0")], False, "2.28.0"),
        ([("==", "2.*")], False, None),
        ([(">=", "2.0"), ("<", "2.3")], False, "2.0"),
        ([(">=", "2.0"), ("<", "2.3")], True, None),
        ([("~=", "8.0")], False, "8.0"),
        ([(">", "1.0"), (">=", "2.0")], False, "1.0"),
        ([("<", "5.0")], False, None),
        ([("!=", "1.0")], False, None),
        ([], False, None),
    ],
)
def test_extract_current_version(
    specs: List[Tuple[str, str]], strict: bool, expected: Optional[str]
) -> None:
    from depkeeper.models.requirement import Requirement

    chk = VersionChecker(
        _store(FakeHttp(lambda u: Resp())), infer_version_from_constraints=not strict
    )
    assert chk.extract_current_version(Requirement(name="x", specs=specs)) == expected


# -------------------------------------------------------------------- Package
def _pkg(**kw: Any) -> Package:
    return Package(name="Some_Pkg", **kw)


@pytest.mark.parametrize(
    "kw,status",
    [
        ({}, "no-update"),
        ({"current_version": "1.0"}, "no-update"),
        ({"recommended_version": "1.0"}, "install"),
        ({"current_version": "1.0", "recommended_version": "1.0.0"}, "latest"),
        ({"current_version": "1.0", "recommended_version": "1.1"}, "outdated"),
        ({"current_version": "1.1", "recommended_version": "1.0"}, "downgrade"),
        ({"current_version": "bad", "recommended_version": "1.0"}, "latest"),
        ({"current_version": "2.*", "recommended_version": "2.5"}, "outdated"),
    ],
)
def test_status_ladder_agrees_between_summary_and_json(
    kw: Dict[str, Any], status: str
) -> None:
    p = _pkg(**kw)
    assert p.get_status_summary()[0] == status
    assert p.to_json()["status"] == status
    assert p.name == "some-pkg"


def test_json_keys_are_stable_and_minimal() -> None:
    assert set(_pkg().to_json()) == {"name", "status", "error"}
    p = _pkg(
        current_version="1.0",
        latest_version="2.0",
        recommended_version="1.5",
        metadata={
            "recommended_metadata": {"requires_python": ">=3.8"},
            "current_metadata": {"requires_python": 5},
        },
        versioning="calver",
        held=True,
        cooldown_skipped="1.6",
        major_available="2.0",
        recommended_released=NOW - timedelta(days=3),
        conflict_held=True,
    )
    j = p.to_json()
    assert set(j) == {
        "name",
        "status",
        "versions",
        "update_type",
        "versioning",
        "held",
        "released",
        "age_days",
        "cooldown_skipped",
        "conflict_held",
        "major_available",
        "python_requirements",
    }
    assert j["python_requirements"] == {"recommended": ">=3.8"}
    assert j["update_type"] == "month" and j["versions"] == {
        "current": "1.0",
        "latest": "2.0",
        "recommended": "1.5",
    }


def test_to_json_semver_default_omits_versioning_and_flags() -> None:
    j = _pkg(current_version="1.0", recommended_version="1.0").to_json()
    assert set(j) == {"name", "status", "versions"}
    j = _pkg(current_version="1.0", recommended_version="1.1").to_json()
    assert j["update_type"] == "minor"


def test_display_data_and_age() -> None:
    p = _pkg(
        current_version="1.1",
        recommended_version="1.0",
        recommended_released=NOW - timedelta(days=40, hours=5),
    )
    d = p.get_display_data()
    assert (
        d["requires_downgrade"]
        and not d["update_available"]
        and d["update_type"] == "downgrade"
    )
    assert p.recommended_age_days(NOW) == 40
    assert (
        _pkg(recommended_released=NOW + timedelta(days=3)).recommended_age_days(NOW)
        == 0
    )
    assert _pkg().recommended_age_days(NOW) is None
    q = _pkg(current_version="1.0", recommended_version="1.0")
    assert q.get_display_data()["update_type"] is None


def test_python_compat_render_and_str() -> None:
    p = _pkg(
        current_version="1.0",
        latest_version="3.0",
        recommended_version="2.0",
        metadata={
            "current_metadata": {"requires_python": ">=3.6"},
            "latest_metadata": {"requires_python": ">=3.9"},
            "recommended_metadata": {"requires_python": ">=3.8"},
        },
    )
    assert (
        p.render_python_compatibility()
        == "Current: >=3.6\nLatest: >=3.9\nRecommended: >=3.8"
    )
    assert "recommended: 2.0" in str(p) and "outdated" in str(p)
    assert _pkg().render_python_compatibility() == "[dim]-[/dim]"
    assert (
        _pkg(metadata={"current_metadata": "oops"}).get_version_python_req("current")
        is None
    )
    assert "outdated=False" in repr(_pkg())
