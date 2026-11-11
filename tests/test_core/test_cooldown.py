"""Release cooldown (min_age) and upload-date capture."""

from datetime import datetime, timedelta, timezone
from typing import Optional, Union

import pytest

from depkeeper.config import parse_duration
from depkeeper.core.checker import VersionChecker
from depkeeper.core.data_store import PyPIDataStore, PyPIPackageData
from tests.support.pypi import FakePyPIStore, package_data

NOW = datetime(2025, 1, 10, tzinfo=timezone.utc)


def _data(**ages: Optional[int]) -> PyPIPackageData:
    d = package_data("x", ["1.0", "1.1", "1.2", "1.3"])
    d.upload_times = {
        v: (NOW - timedelta(days=a)) if a is not None else None for v, a in ages.items()
    }
    return d


def _checker(data: PyPIPackageData, days: int = 7) -> VersionChecker:
    return VersionChecker(
        FakePyPIStore({"x": data}), min_age=timedelta(days=days), clock=lambda: NOW
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("7d", timedelta(days=7)),
        ("12h", timedelta(hours=12)),
        (3, timedelta(days=3)),
        ("2w", timedelta(weeks=2)),
        ("5", timedelta(days=5)),
    ],
)
def test_parse_duration(raw: Union[str, int], expected: timedelta) -> None:
    assert parse_duration(raw) == expected


@pytest.mark.parametrize("raw", ["x", -1, True, "7y", "-3d"])
def test_parse_duration_invalid(raw: Union[str, int]) -> None:
    with pytest.raises(ValueError):
        parse_duration(raw)


@pytest.mark.asyncio
async def test_falls_back_to_older_eligible() -> None:
    pkg = await _checker(
        _data(**{"1.0": 100, "1.1": 30, "1.2": 10, "1.3": 2})
    ).get_package_info("x", "1.0")
    assert pkg.recommended_version == "1.2"
    assert pkg.cooldown_skipped == "1.3"
    assert pkg.recommended_age_days(NOW) == 10
    entry = pkg.to_json()
    assert entry["released"] == (NOW - timedelta(days=10)).isoformat()
    # to_json measures against the wall clock, so compare with the same call.
    assert entry["age_days"] == pkg.recommended_age_days()


@pytest.mark.asyncio
async def test_never_below_current() -> None:
    pkg = await _checker(
        _data(**{"1.0": 100, "1.1": 3, "1.2": 2, "1.3": 1})
    ).get_package_info("x", "1.1")
    assert pkg.recommended_version == "1.1"
    assert pkg.cooldown_skipped == "1.3"


@pytest.mark.asyncio
async def test_missing_dates_treated_old() -> None:
    pkg = await _checker(
        _data(**{"1.0": None, "1.1": None, "1.2": None, "1.3": None})
    ).get_package_info("x", "1.0")
    assert pkg.recommended_version == "1.3" and pkg.cooldown_skipped is None


def test_data_store_captures_upload_time() -> None:
    store = PyPIDataStore.__new__(PyPIDataStore)
    payload = {
        "info": {"version": "1.1"},
        "releases": {
            "1.0": [{"upload_time_iso_8601": "2024-01-02T03:04:05.123456Z"}],
            "1.1": [{"filename": "a"}],
            "1.2": [{"upload_time_iso_8601": "garbage"}],
        },
    }
    data = store._parse_package_data("x", payload)
    assert data.upload_times["1.0"] == datetime(
        2024, 1, 2, 3, 4, 5, 123456, tzinfo=timezone.utc
    )
    assert data.upload_times["1.1"] is None and data.upload_times["1.2"] is None
