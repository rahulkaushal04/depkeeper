"""Calver max_update ranking and undated-release warnings in the checker."""

import logging
from datetime import datetime, timedelta, timezone

import pytest

from depkeeper.config import PackagePolicy
from depkeeper.core.checker import VersionChecker
from tests.support.pypi import FakePyPIStore, package_data


@pytest.mark.asyncio
async def test_calver_year_change_ranks_as_minor_like_cli_gate() -> None:
    store = FakePyPIStore({"black": package_data("black", ["23.12.0", "24.1.0"])})
    checker = VersionChecker(
        store,
        versioning="calver",
        policies={"black": PackagePolicy(max_update="minor")},
    )
    pkg = await checker.get_package_info("black", "23.12.0")
    assert pkg.recommended_version == "24.1.0"


@pytest.mark.asyncio
async def test_calver_year_change_blocked_by_patch_cap() -> None:
    store = FakePyPIStore({"black": package_data("black", ["23.12.0", "24.1.0"])})
    checker = VersionChecker(
        store,
        versioning="calver",
        policies={"black": PackagePolicy(max_update="patch")},
    )
    pkg = await checker.get_package_info("black", "23.12.0")
    assert pkg.recommended_version == "23.12.0"


@pytest.mark.asyncio
async def test_undated_release_warns_once_per_package(
    caplog: pytest.LogCaptureFixture,
) -> None:
    now = datetime(2025, 1, 10, tzinfo=timezone.utc)
    d = package_data("x", ["1.0", "1.1", "1.2"])
    d.upload_times = {"1.0": None, "1.1": None, "1.2": None}
    checker = VersionChecker(
        FakePyPIStore({"x": d}), min_age=timedelta(days=7), clock=lambda: now
    )
    logger = logging.getLogger("depkeeper.version_checker")
    prev = logger.propagate
    logger.propagate = True
    try:
        with caplog.at_level(logging.WARNING):
            await checker.get_package_info("x", "1.0")
            await checker.get_package_info("x", "1.0")
    finally:
        logger.propagate = prev
    msgs = [r for r in caplog.records if "no upload date" in r.getMessage()]
    assert len(msgs) == 1
