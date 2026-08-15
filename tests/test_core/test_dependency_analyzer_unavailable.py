"""Tests for graceful degradation when PyPI metadata is unavailable.

Primary purpose: guard against regression M6 — an unguarded
``get_package_data()`` inside the resolver let a ``PyPIError`` escape
``resolve_and_annotate_conflicts()`` and abort the whole ``check`` /
``update`` run with "Unexpected error".

A package can legitimately reach the resolver with no cached metadata:
``prefetch_packages()`` swallows per-package failures and
``VersionChecker.get_package_info()`` returns an *unavailable stub*, so the
package is still present in the package list handed to the analyzer.
"""

from __future__ import annotations

import logging
from typing import List

import pytest

from depkeeper.core.dependency_analyzer import DependencyAnalyzer
from depkeeper.exceptions import NetworkError, PyPIError
from depkeeper.models.package import Package
from tests.support.pypi import FakePyPIStore, package_data as _pkg_data


CONFLICTING_DEPS = {
    "flask==2.3.3": ["internal-lib>=2.0"],
    "flask==2.0.0": ["internal-lib>=2.0"],
    "internal-lib==1.0.0": [],
}


def _conflicting_packages() -> List[Package]:
    """flask wants ``internal-lib>=2.0``; the pinned ``internal-lib`` is 1.0.0."""
    return [
        Package(
            name="flask",
            current_version="2.0.0",
            latest_version="2.3.3",
            recommended_version="2.3.3",
        ),
        Package(
            name="internal-lib",  # unavailable stub produced by the checker
            current_version="1.0.0",
            latest_version=None,
            recommended_version=None,
        ),
    ]


@pytest.mark.unit
class TestUnavailableMetadataDegradation:
    """M6: missing metadata must degrade, never abort."""

    async def test_resolution_survives_unavailable_target(self) -> None:
        """The full resolver must not raise when the target 404s."""
        store = FakePyPIStore(
            available={"flask": _pkg_data("flask", ["2.0.0", "2.3.3"])},
            dependencies=CONFLICTING_DEPS,
        )
        analyzer = DependencyAnalyzer(data_store=store)

        result = await analyzer.resolve_and_annotate_conflicts(_conflicting_packages())

        # Conflict is reported rather than swallowed …
        assert result.packages_with_conflicts == 1
        assert [r.name for r in result.get_conflicts()] == ["internal-lib"]
        assert result.resolved_versions["flask"].conflicts == []
        # … and the unresolvable pair falls back to the installed versions.
        assert result.resolved_versions["flask"].resolved == "2.0.0"
        assert result.resolved_versions["internal-lib"].resolved == "1.0.0"

    async def test_constrained_target_search_returns_none(self) -> None:
        """Direct call site 1: target metadata missing → ``None``."""
        analyzer = DependencyAnalyzer(data_store=FakePyPIStore())

        found = await analyzer._find_constrained_target_within_major(
            target_name="internal-lib",
            target_major=1,
            required_spec=">=2.0",
        )

        assert found is None

    async def test_compatible_source_search_returns_none(self) -> None:
        """Direct call site 2: source metadata missing → ``None``."""
        analyzer = DependencyAnalyzer(data_store=FakePyPIStore())
        source = Package(name="ghost", current_version="1.0.0")

        found = await analyzer._find_compatible_source_within_major(
            source_pkg=source,
            source_major=1,
            target_name="internal-lib",
            target_proposed_version="1.0.0",
        )

        assert found is None

    @pytest.mark.parametrize(
        "error",
        [
            PyPIError("not found", package_name="ghost"),
            NetworkError("Request failed after 4 attempts", url="https://pypi.org"),
            NetworkError("Rate limit exceeded", url="https://pypi.org", status_code=429),
        ],
        ids=["404", "timeout", "rate-limited"],
    )
    async def test_all_network_failures_degrade(self, error: Exception) -> None:
        """Timeouts and 429s leave the cache cold just like a 404 does."""
        store = FakePyPIStore(error=error)
        analyzer = DependencyAnalyzer(data_store=store)

        assert await analyzer._get_package_data_or_none("ghost") is None

    async def test_unexpected_errors_still_propagate(self) -> None:
        """Only network failures are absorbed — real bugs must stay visible."""
        store = FakePyPIStore(error=ValueError("boom"))
        analyzer = DependencyAnalyzer(data_store=store)

        with pytest.raises(ValueError):
            await analyzer._get_package_data_or_none("ghost")

    async def test_failure_is_cached_and_warned_once(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A known-bad package must not trigger a retry storm in the loop."""
        store = FakePyPIStore()
        analyzer = DependencyAnalyzer(data_store=store)

        with caplog.at_level(logging.WARNING, logger="depkeeper.dependency_analyzer"):
            for _ in range(5):
                assert await analyzer._get_package_data_or_none("Internal_Lib") is None

        assert store.fetch_calls == ["Internal_Lib"]
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "internal_lib" in warnings[0].getMessage().lower()

    async def test_available_metadata_path_is_unchanged(self) -> None:
        """Baseline: the guard must not alter behaviour for healthy packages."""
        store = FakePyPIStore(
            available={
                "flask": _pkg_data("flask", ["2.0.0", "2.2.5", "2.3.3"]),
                "werkzeug": _pkg_data("werkzeug", ["2.0.0", "2.3.7"]),
            },
            dependencies={
                "flask==2.3.3": ["werkzeug>=3.0"],
                "flask==2.2.5": ["werkzeug>=2.0"],
                "flask==2.0.0": ["werkzeug>=2.0"],
                "werkzeug==2.3.7": [],
            },
        )
        analyzer = DependencyAnalyzer(data_store=store)

        packages = [
            Package(
                name="flask",
                current_version="2.0.0",
                latest_version="2.3.3",
                recommended_version="2.3.3",
            ),
            Package(
                name="werkzeug",
                current_version="2.0.0",
                latest_version="2.3.7",
                recommended_version="2.3.7",
            ),
        ]

        result = await analyzer.resolve_and_annotate_conflicts(packages)

        # flask 2.3.3 needs werkzeug>=3.0 (outside werkzeug's major 2), so the
        # resolver steps flask back to 2.2.5 — unchanged pre-existing behaviour.
        assert result.resolved_versions["flask"].resolved == "2.2.5"
        assert result.resolved_versions["werkzeug"].resolved == "2.3.7"
        assert result.converged is True
