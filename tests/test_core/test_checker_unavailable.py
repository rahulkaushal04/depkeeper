"""Tests for :meth:`VersionChecker.get_package_info` failure degradation.

Related to regression M6: PyPI unavailability must consistently degrade to an
*unavailable stub* instead of propagating. ``PyPIError`` (404 / unexpected
status) was already handled; timeouts, exhausted retries and rate limiting
arrive as plain ``NetworkError`` and must be handled identically.
"""

from __future__ import annotations

import pytest

from depkeeper.core.checker import VersionChecker
from depkeeper.exceptions import NetworkError, PyPIError
from depkeeper.models import Requirement
from tests.support.pypi import FakePyPIStore


def _failing_store(error: Exception) -> FakePyPIStore:
    """A store whose every lookup fails with *error* (nothing is available)."""
    return FakePyPIStore(error=error)


@pytest.mark.unit
class TestCheckerUnavailablePackages:
    @pytest.mark.parametrize(
        "error",
        [
            PyPIError("Package 'ghost' not found on PyPI", package_name="ghost"),
            NetworkError("Request failed after 4 attempts", url="https://pypi.org"),
        ],
        ids=["404", "network"],
    )
    async def test_failure_returns_stub(self, error: Exception) -> None:
        checker = VersionChecker(data_store=_failing_store(error))

        pkg = await checker.get_package_info("ghost", "1.0.0")

        assert pkg.name == "ghost"
        assert pkg.current_version == "1.0.0"
        assert pkg.latest_version is None
        assert pkg.recommended_version is None

    async def test_unexpected_error_still_propagates(self) -> None:
        checker = VersionChecker(data_store=_failing_store(RuntimeError("boom")))

        with pytest.raises(RuntimeError):
            await checker.get_package_info("ghost", "1.0.0")

    async def test_check_packages_keeps_stub_in_list(self) -> None:
        """The stub must stay in the list handed to the analyzer."""
        checker = VersionChecker(
            data_store=_failing_store(NetworkError("timeout", url="https://pypi.org"))
        )

        packages = await checker.check_packages(
            [Requirement(name="internal-lib", specs=[("==", "1.0.0")])]
        )

        assert [p.name for p in packages] == ["internal-lib"]
        assert packages[0].current_version == "1.0.0"
        assert packages[0].latest_version is None
