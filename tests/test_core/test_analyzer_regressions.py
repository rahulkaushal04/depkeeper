"""Regression tests for checker, data store and dependency analyzer edge cases."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import pytest
from packaging.specifiers import SpecifierSet

from depkeeper.core.checker import VersionChecker
from depkeeper.core.data_store import PyPIDataStore
from depkeeper.core.dependency_analyzer import (
    DependencyAnalyzer,
    ResolutionResult,
    _specifier_allows,
)
from depkeeper.models import Requirement
from depkeeper.models.package import Package
from tests.support.pypi import FakePyPIStore, package_data as _pkg_data


def _pkg(name: str, current: str, rec: Optional[str], **kw: Any) -> Package:
    return Package(name=name, current_version=current, recommended_version=rec, **kw)


async def _resolve(store: FakePyPIStore, *packages: Package) -> ResolutionResult:
    return await DependencyAnalyzer(data_store=store).resolve_and_annotate_conflicts(
        list(packages)
    )


@pytest.mark.unit
class TestChecker:
    def test_multi_spec_pin_keeps_anchor(self) -> None:
        checker = VersionChecker(data_store=PyPIDataStore.__new__(PyPIDataStore))
        req = Requirement(name="pkg", specs=[("==", "1.0"), ("!=", "1.0.1")])
        assert checker.extract_current_version(req) == "1.0"

    def test_cancelled_error_becomes_stub(self) -> None:
        checker = VersionChecker(data_store=PyPIDataStore.__new__(PyPIDataStore))
        req = Requirement(name="pkg", specs=[("==", "1.0")])
        (pkg,) = checker._process_check_results([req], [asyncio.CancelledError()])
        assert pkg.current_version == "1.0" and pkg.recommended_version is None


@pytest.mark.unit
class TestAnalyzer:
    def test_prerelease_pin_satisfies_lower_bound(self) -> None:
        assert _specifier_allows("2.0rc1", SpecifierSet(">=1"))

    async def test_unavailable_stub_is_not_masked_as_latest(self) -> None:
        stub = _pkg("ghost", "1.0.0", None)
        await _resolve(FakePyPIStore(), stub)
        assert stub.recommended_version is None

    async def test_conflict_target_skips_python_incompatible_versions(self) -> None:
        store = FakePyPIStore(
            {
                "a": _pkg_data("a", ["1.0.0", "1.5.0"]),
                "b": _pkg_data(
                    "b", ["2.0.0", "2.4.0"], requires_python={"2.4.0": ">=99"}
                ),
            },
            dependencies={"a==1.5.0": ["b>=2.4"], "a==1.0.0": ["b>=2.4"]},
        )
        b = _pkg("b", "2.0.0", "2.0.0")
        await _resolve(store, _pkg("a", "1.0.0", "1.5.0"), b)
        assert b.recommended_version != "2.4.0"

    async def test_conflict_target_honours_requirement_bounds(self) -> None:
        store = FakePyPIStore(
            {
                "a": _pkg_data("a", ["1.0.0", "1.5.0"]),
                "b": _pkg_data("b", ["2.0.0", "2.3.0", "2.4.0"]),
            },
            dependencies={"a==1.5.0": ["b>=2.3"], "a==1.0.0": ["b>=2.3"]},
        )
        b = _pkg("b", "2.0.0", "2.0.0", retained_specs=[("<", "2.4")])
        await _resolve(store, _pkg("a", "1.0.0", "1.5.0"), b)
        assert b.recommended_version == "2.3.0"

    async def test_source_never_downgraded_below_installed(self) -> None:
        store = FakePyPIStore(
            {
                "a": _pkg_data("a", ["2.5.0", "2.7.0", "2.9.0"]),
                "b": _pkg_data("b", ["2.0.0"]),
            },
            dependencies={
                "a==2.9.0": ["b>=3"],
                "a==2.7.0": ["b>=3"],
                "a==2.5.0": ["b>=2"],
            },
        )
        a = _pkg("a", "2.7.0", "2.9.0")
        await _resolve(store, a, _pkg("b", "2.0.0", "2.0.0"))
        assert a.recommended_version == "2.7.0"

    async def test_fallback_revert_reports_progress(self) -> None:
        store = FakePyPIStore(
            {
                "flask": _pkg_data("flask", ["3.0.3", "3.1.3"]),
                "werkzeug": _pkg_data("werkzeug", ["2.0.3", "2.3.8"]),
            },
            dependencies={
                "flask==3.1.3": ["werkzeug>=3.1.0"],
                "flask==3.0.3": ["werkzeug>=3.0.0"],
            },
        )
        flask, werkzeug = (
            _pkg("flask", "3.0.3", "3.1.3"),
            _pkg("werkzeug", "2.0.3", "2.3.8"),
        )
        analyzer = DependencyAnalyzer(data_store=store)
        update_set = {"flask": "3.1.3", "werkzeug": "2.3.8"}
        conflicts = await analyzer._find_cross_conflicts([flask, werkzeug], update_set)
        changed = await analyzer._resolve_conflicts_within_major(
            {"flask": flask, "werkzeug": werkzeug}, update_set, conflicts
        )
        assert changed is True

    async def test_constraint_file_caps_recommendation(self) -> None:
        store = FakePyPIStore(
            {"django": _pkg_data("django", ["4.0.0", "4.2.0", "4.9.0"])}
        )
        checker = VersionChecker(data_store=store)
        req = Requirement(
            name="django", specs=[(">=", "4.0.0")], constraint_specs=[("<", "4.5")]
        )
        (pkg,) = await checker.check_packages([req])
        assert pkg.recommended_version == "4.2.0"
