"""Target Python override."""

import pytest

from depkeeper.core.checker import VersionChecker
from tests.support.pypi import FakePyPIStore, package_data

DATA = package_data(
    "x", ["1.0", "1.1", "1.2"], requires_python={"1.1": ">=3.8", "1.2": ">=3.10"}
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target,expected", [("3.9", "1.1"), ("3.12", "1.2"), ("3.7", "1.0")]
)
async def test_target_python(target: str, expected: str) -> None:
    checker = VersionChecker(FakePyPIStore({"x": DATA}), target_python=target)
    assert (await checker.get_package_info("x", "1.0")).recommended_version == expected


@pytest.mark.asyncio
async def test_default_is_running_interpreter() -> None:
    # 1.0 is unconstrained, so running interpreter (>=3.8 here) gets >=1.1
    pkg = await VersionChecker(FakePyPIStore({"x": DATA})).get_package_info("x", "1.0")
    assert pkg.recommended_version in ("1.1", "1.2")
