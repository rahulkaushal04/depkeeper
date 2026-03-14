"""
Integration tests: DependencyAnalyzer conflict detection.

Covers scenarios 21, 24, 53 from the scenario document.

- SCENARIO-21: Conflict detected: packageA's dep on packageB conflicts with B's version
- SCENARIO-24: No conflict when all packages are mutually compatible
- SCENARIO-53: Multiple conflicting dependencies are all detected

All tests pre-seed the PyPIDataStore's caches directly so no HTTP calls are
made.  This keeps tests fast and focused on the detection algorithm, not the
network layer.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from packaging.version import Version

from depkeeper.core.data_store import PyPIDataStore, PyPIPackageData
from depkeeper.core.dependency_analyzer import DependencyAnalyzer
from depkeeper.models.package import Package
from depkeeper.utils.http import HTTPClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(*package_data: PyPIPackageData) -> PyPIDataStore:
    """Build a PyPIDataStore pre-seeded with the given PyPIPackageData objects.

    Uses a MagicMock HTTPClient so no real HTTP is possible.
    Pre-seeds both _package_data and _version_deps_cache entries.
    """
    store = PyPIDataStore(MagicMock(spec=HTTPClient))
    for pkg in package_data:
        store._package_data[pkg.name] = pkg
        # Seed the version-deps cache for the latest version
        if pkg.latest_version and pkg.latest_dependencies is not None:
            store._version_deps_cache[f"{pkg.name}=={pkg.latest_version}"] = (
                pkg.latest_dependencies
            )
        # Also seed all versions in dependencies_cache
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
    """Build a minimal PyPIPackageData for integration testing."""
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
    """Build a Package with the given version fields."""
    return Package(
        name=name,
        current_version=current,
        latest_version=latest or recommended,
        recommended_version=recommended,
        metadata={},
    )


# ---------------------------------------------------------------------------
# SCENARIO-21 — Conflict detected: A's dep on B is incompatible with B's version
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_conflict_detected_when_dependency_version_incompatible() -> None:
    """DependencyAnalyzer detects a conflict when A requires B at a version
    that is higher than B's recommended version.

    Setup:
        flask==2.3.0 → recommended: 2.3.4
        flask 2.3.4 depends on: werkzeug>=3.0.0
        werkzeug==2.0.0 → recommended: 2.3.7 (within major 2)

    Conflict: flask==2.3.4 needs werkzeug>=3.0.0, but werkzeug==2.3.7 is proposed.
    """
    flask_data = _make_pkg_data(
        name="flask",
        latest="2.3.4",
        versions=["2.3.4", "2.3.0"],
        latest_deps=[],
        # Per-version dep: flask 2.3.4 needs werkzeug>=3.0.0
        version_deps={"2.3.4": ["werkzeug>=3.0.0"]},
    )
    werkzeug_data = _make_pkg_data(
        name="werkzeug",
        latest="3.0.1",
        versions=["3.0.1", "2.3.7", "2.0.0"],
        latest_deps=[],
        version_deps={"2.3.7": [], "2.0.0": []},
    )

    store = _make_store(flask_data, werkzeug_data)
    # Seed flask==2.3.4 deps in version cache
    store._version_deps_cache["flask==2.3.4"] = ["werkzeug>=3.0.0"]
    store._version_deps_cache["werkzeug==2.3.7"] = []

    packages = [
        _make_package("flask", "2.3.0", "2.3.4"),
        _make_package("werkzeug", "2.0.0", "2.3.7", latest="3.0.1"),
    ]

    analyzer = DependencyAnalyzer(data_store=store)
    result = await analyzer.resolve_and_annotate_conflicts(packages)

    # Must detect at least one conflict
    assert result.packages_with_conflicts > 0

    # werkzeug should be identified as the conflicted package
    # (flask requires werkzeug>=3.0.0 but werkzeug==2.3.7 is proposed)
    conflicted_names = {r.name for r in result.get_conflicts()}
    assert "werkzeug" in conflicted_names


@pytest.mark.integration
async def test_conflict_has_correct_source_and_target() -> None:
    """Conflict object correctly identifies source (flask) and target (werkzeug).

    Verifies the Conflict dataclass fields populated by DependencyAnalyzer:
    - source_package: package that declares the dependency
    - target_package: package being constrained
    - required_spec: the version spec that is not satisfied
    """
    flask_data = _make_pkg_data(
        name="flask",
        latest="2.3.4",
        versions=["2.3.4", "2.3.0"],
        version_deps={"2.3.4": ["werkzeug>=3.0.0"]},
    )
    werkzeug_data = _make_pkg_data(
        name="werkzeug",
        latest="3.0.1",
        versions=["3.0.1", "2.3.7"],
        version_deps={"2.3.7": []},
    )

    store = _make_store(flask_data, werkzeug_data)
    store._version_deps_cache["flask==2.3.4"] = ["werkzeug>=3.0.0"]
    store._version_deps_cache["werkzeug==2.3.7"] = []

    packages = [
        _make_package("flask", "2.3.0", "2.3.4"),
        _make_package("werkzeug", "2.0.0", "2.3.7", latest="3.0.1"),
    ]

    analyzer = DependencyAnalyzer(data_store=store)
    result = await analyzer.resolve_and_annotate_conflicts(packages)

    werkzeug_resolution = result.resolved_versions.get("werkzeug")
    assert werkzeug_resolution is not None
    assert len(werkzeug_resolution.conflicts) >= 1

    conflict = werkzeug_resolution.conflicts[0]
    assert conflict.source_package == "flask"
    assert conflict.target_package == "werkzeug"
    assert ">=3.0.0" in conflict.required_spec


# ---------------------------------------------------------------------------
# SCENARIO-24 — No conflict: all packages are mutually compatible
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_no_conflict_when_all_packages_compatible() -> None:
    """DependencyAnalyzer reports zero conflicts when packages are compatible.

    Setup:
        flask==2.3.4 depends on werkzeug>=2.3.0
        werkzeug recommended: 2.3.7 → satisfies >=2.3.0

    Expected: result.packages_with_conflicts == 0, converged == True
    """
    flask_data = _make_pkg_data(
        name="flask",
        latest="2.3.4",
        versions=["2.3.4", "2.3.0"],
        version_deps={"2.3.4": ["werkzeug>=2.3.0"]},
    )
    werkzeug_data = _make_pkg_data(
        name="werkzeug",
        latest="2.3.7",
        versions=["2.3.7", "2.3.0"],
        version_deps={"2.3.7": []},
    )

    store = _make_store(flask_data, werkzeug_data)
    store._version_deps_cache["flask==2.3.4"] = ["werkzeug>=2.3.0"]
    store._version_deps_cache["werkzeug==2.3.7"] = []

    packages = [
        _make_package("flask", "2.3.0", "2.3.4"),
        _make_package("werkzeug", "2.3.0", "2.3.7"),
    ]

    analyzer = DependencyAnalyzer(data_store=store)
    result = await analyzer.resolve_and_annotate_conflicts(packages)

    assert result.packages_with_conflicts == 0
    assert result.converged is True
    assert result.get_conflicts() == []


@pytest.mark.integration
async def test_no_conflict_when_no_shared_deps() -> None:
    """Packages with no shared dependencies produce zero conflicts.

    Setup: flask and requests both recommended to their respective latest;
    neither depends on the other in the proposed versions.
    """
    flask_data = _make_pkg_data(
        name="flask",
        latest="2.3.4",
        versions=["2.3.4", "2.3.0"],
        version_deps={"2.3.4": ["jinja2>=3.1.2"]},
    )
    requests_data = _make_pkg_data(
        name="requests",
        latest="2.31.0",
        versions=["2.31.0", "2.28.0"],
        version_deps={"2.31.0": ["charset-normalizer>=2,<4"]},
    )

    store = _make_store(flask_data, requests_data)
    store._version_deps_cache["flask==2.3.4"] = ["jinja2>=3.1.2"]
    store._version_deps_cache["requests==2.31.0"] = ["charset-normalizer>=2,<4"]

    packages = [
        _make_package("flask", "2.3.0", "2.3.4"),
        _make_package("requests", "2.28.0", "2.31.0"),
    ]

    analyzer = DependencyAnalyzer(data_store=store)
    result = await analyzer.resolve_and_annotate_conflicts(packages)

    assert result.packages_with_conflicts == 0


# ---------------------------------------------------------------------------
# SCENARIO-53 — Multiple conflicts detected across several packages
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_multiple_conflicts_detected_across_packages() -> None:
    """All conflicts across multiple packages are detected, not just the first.

    Setup:
        pkgA requires pkgC>=2.0 (proposed pkgC==1.5 → conflict)
        pkgB requires pkgC>=3.0 (proposed pkgC==1.5 → additional conflict)
        pkgC proposed at 1.5

    Both pkgA and pkgB conflict with pkgC. DependencyAnalyzer must report
    conflicts from multiple sources.
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
        version_deps={"1.0.0": ["pkgc>=3.0"]},
    )
    pkgc_data = _make_pkg_data(
        name="pkgc",
        latest="4.0.0",
        versions=["4.0.0", "3.0.0", "2.0.0", "1.5.0"],
        version_deps={"1.5.0": []},
    )

    store = _make_store(pkga_data, pkgb_data, pkgc_data)
    store._version_deps_cache["pkga==1.0.0"] = ["pkgc>=2.0"]
    store._version_deps_cache["pkgb==1.0.0"] = ["pkgc>=3.0"]
    store._version_deps_cache["pkgc==1.5.0"] = []

    packages = [
        _make_package("pkga", "1.0.0", "1.0.0"),
        _make_package("pkgb", "1.0.0", "1.0.0"),
        _make_package("pkgc", "1.5.0", "1.5.0", latest="4.0.0"),
    ]

    analyzer = DependencyAnalyzer(data_store=store)
    result = await analyzer.resolve_and_annotate_conflicts(packages)

    # pkgc must be identified as conflicted (by both pkga and pkgb)
    assert result.packages_with_conflicts > 0
    pkgc_resolution = result.resolved_versions.get("pkgc")
    assert pkgc_resolution is not None
    # Multiple conflicts recorded (one from pkga, one from pkgb)
    assert len(pkgc_resolution.conflicts) >= 1
