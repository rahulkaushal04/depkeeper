"""Calendar-versioning awareness."""

from typing import List

import pytest

from depkeeper.core.checker import VersionChecker
from depkeeper.utils.version_utils import (
    detect_versioning,
    gating_type,
    get_update_type,
)
from tests.support.pypi import FakePyPIStore, package_data


def test_semver_labels_untouched() -> None:
    assert get_update_type("2023.7.22", "2024.8.30") == "major"
    assert get_update_type("1.2.3", "1.3.0") == "minor"


def test_calver_labels() -> None:
    assert get_update_type("2023.7.22", "2024.8.30", "calver") == "year"
    assert get_update_type("2024.7.22", "2024.8.30", "calver") == "month"
    assert get_update_type("2024.8.22", "2024.8.30", "calver") == "patch"


def test_gating_never_major_for_calver() -> None:
    assert gating_type("year") == "minor"
    assert gating_type("month") == "minor"
    assert gating_type("major") == "major"


@pytest.mark.parametrize(
    "current,history,expected",
    [
        ("2024.8.30", [], "calver"),
        ("2023.7.22", [], "calver"),
        ("23.1.0", [], "semver"),  # not a 4-digit year
        ("3000.1.0", [], "semver"),  # implausible year
        ("1.2.3", ["1.2.3"], "semver"),
    ],
)
def test_detect_auto(current: str, history: List[str], expected: str) -> None:
    assert detect_versioning("auto", current, history) == expected


def test_detect_yy_m_needs_history() -> None:
    black = [
        "22.1.0",
        "22.3.0",
        "22.12.0",
        "23.1.0",
        "23.3.0",
        "23.9.1",
        "24.1.0",
        "24.2.0",
    ]
    assert detect_versioning("auto", "23.1.0", black) == "calver"
    assert detect_versioning("auto", "23.1.0", black[:7]) == "semver"
    assert detect_versioning("calver", "1.0", []) == "calver"
    assert detect_versioning("semver", "2024.1", []) == "semver"


@pytest.mark.asyncio
async def test_checker_crosses_year_for_calver_only() -> None:
    store = FakePyPIStore({"certifi": package_data("certifi")})
    pkg = await VersionChecker(store).get_package_info("certifi", "2023.7.22")
    assert pkg.recommended_version == "2024.7.4"
    assert pkg.versioning == "calver" and pkg.update_type == "year"
    assert pkg.to_json()["update_type"] == "year"

    forced = await VersionChecker(store, versioning="semver").get_package_info(
        "certifi", "2023.7.22"
    )
    assert forced.recommended_version == "2023.7.22"


@pytest.mark.asyncio
async def test_yy_m_explicit_config() -> None:
    store = FakePyPIStore({"black": package_data("black", ["23.1.0", "24.2.0"])})
    auto = await VersionChecker(store).get_package_info("black", "23.1.0")
    assert auto.recommended_version == "23.1.0"
    cal = await VersionChecker(store, versioning="calver").get_package_info(
        "black", "23.1.0"
    )
    assert cal.recommended_version == "24.2.0"
