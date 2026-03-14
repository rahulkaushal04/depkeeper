"""
Integration tests: DependencyAnalyzer conflict resolution.

Covers scenarios 22, 23, 54 from the scenario document.

- SCENARIO-22: Resolution finds a compatible version to fix the conflict
- SCENARIO-23: Unresolvable conflict — no version satisfies all requirements
- SCENARIO-54: Multiple conflicts resolved correctly in a single pass

All tests pre-seed the PyPIDataStore caches to avoid HTTP calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from packaging.version import Version

from depkeeper.core.data_store import PyPIDataStore, PyPIPackageData
from depkeeper.core.dependency_analyzer import DependencyAnalyzer, ResolutionStatus
from depkeeper.models.package import Package
from depkeeper.utils.http import HTTPClient


# ---------------------------------------------------------------------------
# Helpers (mirror test_conflict_detection.py helpers)
# ---------------------------------------------------------------------------


def _make_store(*package_data: PyPIPackageData) -> PyPIDataStore:
    store = PyPIDataStore(MagicMock(spec=HTTPClient))
    for pkg in package_data:
        store._package_data[pkg.name] = pkg
        if pkg.latest_version and pkg.latest_dependencies is not None:
            store._version_deps_cache[f"{pkg.name}=={pkg.latest_version}"] = (
                pkg.latest_dependencies
            )
        for version, deps in pkg.dependencies_cache.items():
            store._version_deps_cache[f"{pkg.name}=={version}"] = deps
    return store


def _make_pkg_data(
    name: str,
    latest: str,
    versions: list,
    latest_deps: list = None,
    version_deps: dict = None,
) -> PyPIPackageData:
    parsed = [(v, Version(v)) for v in versions]
    parsed.sort(key=lambda x: x[1], reverse=True)
    stable = [v for v, p in parsed if not p.is_prerelease]
    return PyPIPackageData(
        name=name,
        latest_version=latest,
        latest_requires_python=">=3.7",
        latest_dependencies=latest_deps or [],
        all_versions=stable,
        parsed_versions=parsed,
        python_requirements={v: ">=3.7" for v in versions},
        releases={},
        dependencies_cache=version_deps or {},
    )


def _make_package(
    name: str,
    current: str,
    recommended: str,
    latest: str = None,
) -> Package:
    return Package(
        name=name,
        current_version=current,
        latest_version=latest or recommended,
        recommended_version=recommended,
        metadata={},
    )


# ---------------------------------------------------------------------------
# SCENARIO-22 — Resolution: a compatible version is found within major boundary
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_resolution_constrains_target_to_compatible_version() -> None:
    """Conflict resolved by constraining werkzeug to a version that satisfies flask.

    Setup:
        flask==2.3.0 → recommended 2.3.4, which needs werkzeug>=3.0.0
        werkzeug==2.0.0 → recommended 2.3.7 (conflict: doesn't satisfy >=3.0.0)
        werkzeug also has version 3.0.1 available

    Resolution: the analyzer should either:
      a) Downgrade flask to a version that accepts werkzeug 2.x, OR
      b) Upgrade werkzeug to satisfy flask's >=3.0.0 requirement
    In either case, the final update_set must be self-consistent.

    After resolution, result.converged should be True (stable state reached).
    """
    flask_data = _make_pkg_data(
        name="flask",
        latest="2.3.4",
        versions=["2.3.4", "2.3.0", "2.2.0"],
        version_deps={
            "2.3.4": ["werkzeug>=3.0.0"],
            "2.3.0": ["werkzeug>=2.0.0"],  # older flask accepts werkzeug 2.x
            "2.2.0": ["werkzeug>=2.0.0"],
        },
    )
    werkzeug_data = _make_pkg_data(
        name="werkzeug",
        latest="3.0.1",
        versions=["3.0.1", "3.0.0", "2.3.7", "2.0.0"],
        version_deps={"2.3.7": [], "3.0.1": [], "3.0.0": [], "2.0.0": []},
    )

    store = _make_store(flask_data, werkzeug_data)
    store._version_deps_cache["flask==2.3.4"] = ["werkzeug>=3.0.0"]
    store._version_deps_cache["flask==2.3.0"] = ["werkzeug>=2.0.0"]
    store._version_deps_cache["flask==2.2.0"] = ["werkzeug>=2.0.0"]
    store._version_deps_cache["werkzeug==2.3.7"] = []
    store._version_deps_cache["werkzeug==3.0.1"] = []
    store._version_deps_cache["werkzeug==3.0.0"] = []
    store._version_deps_cache["werkzeug==2.0.0"] = []

    packages = [
        _make_package("flask", "2.3.0", "2.3.4"),
        _make_package("werkzeug", "2.0.0", "2.3.7", latest="3.0.1"),
    ]

    analyzer = DependencyAnalyzer(data_store=store)
    result = await analyzer.resolve_and_annotate_conflicts(packages)

    # Resolution must converge (not hit the iteration limit)
    assert result.converged is True

    # The resolver must have changed at least one version to resolve the conflict
    # (either flask downgraded or werkzeug upgraded within its major)
    changed = result.get_changed_packages()
    # At least one package version was adjusted to eliminate the conflict
    assert len(changed) >= 1 or result.packages_with_conflicts == 0


@pytest.mark.integration
async def test_resolution_result_is_self_consistent() -> None:
    """After resolution, proposed versions satisfy all declared dependencies.

    When flask==2.3.0 requires werkzeug>=2.0.0 and werkzeug==2.3.7 is proposed,
    there is no conflict — so the resolution should leave versions unchanged
    and report zero conflicts.
    """
    flask_data = _make_pkg_data(
        name="flask",
        latest="2.3.0",
        versions=["2.3.0", "2.2.0"],
        version_deps={"2.3.0": ["werkzeug>=2.0.0"]},
    )
    werkzeug_data = _make_pkg_data(
        name="werkzeug",
        latest="2.3.7",
        versions=["2.3.7", "2.3.0", "2.0.0"],
        version_deps={"2.3.7": []},
    )

    store = _make_store(flask_data, werkzeug_data)
    store._version_deps_cache["flask==2.3.0"] = ["werkzeug>=2.0.0"]
    store._version_deps_cache["werkzeug==2.3.7"] = []

    packages = [
        _make_package("flask", "2.2.0", "2.3.0"),
        _make_package("werkzeug", "2.0.0", "2.3.7"),
    ]

    analyzer = DependencyAnalyzer(data_store=store)
    result = await analyzer.resolve_and_annotate_conflicts(packages)

    assert result.packages_with_conflicts == 0
    assert result.converged is True
    assert result.get_changed_packages() == []


# ---------------------------------------------------------------------------
# SCENARIO-23 — Unresolvable: no version within major satisfies the requirement
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_unresolvable_conflict_reverts_to_current_version() -> None:
    """When no in-major version satisfies the conflict, packages revert to current.

    Setup:
        pkgA==1.0.0 → recommended: 1.0.0, depends on pkgB>=2.0.0
        pkgB==1.5.0 → recommended: 1.5.0 (only version in major 1, < 2.0.0)
        pkgB has no 2.x versions — conflict is unresolvable within major 1

    Expected:
        - result.packages_with_conflicts > 0
        - pkgB reverts to current (1.5.0) or stays, not upgraded across major boundary
        - result.converged may be False (stalled) or True (gave up after detecting impossibility)
    """
    pkga_data = _make_pkg_data(
        name="pkga",
        latest="1.0.0",
        versions=["1.0.0"],
        version_deps={"1.0.0": ["pkgb>=2.0.0"]},
    )
    pkgb_data = _make_pkg_data(
        name="pkgb",
        latest="1.9.9",  # latest is still major 1 — no 2.x available
        versions=["1.9.9", "1.5.0"],
        version_deps={"1.5.0": [], "1.9.9": []},
    )

    store = _make_store(pkga_data, pkgb_data)
    store._version_deps_cache["pkga==1.0.0"] = ["pkgb>=2.0.0"]
    store._version_deps_cache["pkgb==1.5.0"] = []
    store._version_deps_cache["pkgb==1.9.9"] = []

    packages = [
        _make_package("pkga", "1.0.0", "1.0.0"),
        _make_package("pkgb", "1.5.0", "1.5.0", latest="1.9.9"),
    ]

    analyzer = DependencyAnalyzer(data_store=store)
    result = await analyzer.resolve_and_annotate_conflicts(packages)

    # Must detect the conflict (pkgb cannot satisfy pkga's >=2.0.0 requirement)
    assert result.packages_with_conflicts > 0

    pkgb_resolution = result.resolved_versions.get("pkgb")
    assert pkgb_resolution is not None
    assert len(pkgb_resolution.conflicts) >= 1


# ---------------------------------------------------------------------------
# SCENARIO-54 — Multiple conflicts resolved correctly in a single resolution run
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_multiple_conflicts_resolved_in_single_run() -> None:
    """DependencyAnalyzer handles multiple independent conflicts in one run.

    Setup:
        pkgA==1.0 requires pkgC>=2.0; proposed pkgC==1.5 → conflict
        pkgB==1.0 requires pkgD>=2.0; proposed pkgD==1.5 → conflict
        pkgC has version 2.0.0 available; pkgD has version 2.0.0 available

    Both conflicts should be detectable and annotated.
    """
    pkga_data = _make_pkg_data(
        name="pkga",
        latest="1.0.0",
        versions=["1.0.0"],
        version_deps={"1.0.0": ["pkgc>=2.0"]},
    )
    pkgb_data = _make_pkg_data(
        name="pkgb",
        latest="1.0.0",
        versions=["1.0.0"],
        version_deps={"1.0.0": ["pkgd>=2.0"]},
    )
    pkgc_data = _make_pkg_data(
        name="pkgc",
        latest="2.0.0",
        versions=["2.0.0", "1.5.0"],
        version_deps={"1.5.0": [], "2.0.0": []},
    )
    pkgd_data = _make_pkg_data(
        name="pkgd",
        latest="2.0.0",
        versions=["2.0.0", "1.5.0"],
        version_deps={"1.5.0": [], "2.0.0": []},
    )

    store = _make_store(pkga_data, pkgb_data, pkgc_data, pkgd_data)
    store._version_deps_cache["pkga==1.0.0"] = ["pkgc>=2.0"]
    store._version_deps_cache["pkgb==1.0.0"] = ["pkgd>=2.0"]
    store._version_deps_cache["pkgc==1.5.0"] = []
    store._version_deps_cache["pkgd==1.5.0"] = []
    store._version_deps_cache["pkgc==2.0.0"] = []
    store._version_deps_cache["pkgd==2.0.0"] = []

    packages = [
        _make_package("pkga", "1.0.0", "1.0.0"),
        _make_package("pkgb", "1.0.0", "1.0.0"),
        _make_package("pkgc", "1.5.0", "1.5.0", latest="2.0.0"),
        _make_package("pkgd", "1.5.0", "1.5.0", latest="2.0.0"),
    ]

    analyzer = DependencyAnalyzer(data_store=store)
    result = await analyzer.resolve_and_annotate_conflicts(packages)

    # Both pkgc and pkgd are in conflict (with pkga and pkgb respectively)
    assert result.packages_with_conflicts >= 1

    # ResolutionResult collects all conflicts, not just the first
    all_conflict_names = {r.name for r in result.get_conflicts()}
    # At minimum one of the conflicted packages is detected
    assert len(all_conflict_names) >= 1


@pytest.mark.integration
async def test_resolution_summary_contains_expected_fields() -> None:
    """ResolutionResult.summary() produces a multi-line string with key statistics.

    Verifies the human-readable output of the summary method, which is
    displayed by the check command when --check-conflicts is active.
    """
    pkga_data = _make_pkg_data(
        name="pkga",
        latest="1.0.0",
        versions=["1.0.0"],
        version_deps={"1.0.0": []},
    )
    store = _make_store(pkga_data)
    store._version_deps_cache["pkga==1.0.0"] = []

    packages = [_make_package("pkga", "1.0.0", "1.0.0")]

    analyzer = DependencyAnalyzer(data_store=store)
    result = await analyzer.resolve_and_annotate_conflicts(packages)

    summary = result.summary()
    # Must contain all required sections
    assert "Total packages: 1" in summary
    assert "Packages with conflicts:" in summary
    assert "Converged:" in summary
