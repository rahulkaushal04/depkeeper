"""Cross-layer package-name normalisation tests.

Primary purpose: guard against regression M9 — the update set is keyed by
the parser's PEP 503 name (``zope-interface``) while upstream
``requires_dist`` metadata spells the same distribution ``zope.interface``.
Three of the four normalisers folded ``_`` but not ``.``, so
``_find_cross_conflicts()`` looked up a key that could never exist and the
tool reported a clean, conflict-free result — a false negative, the worst
failure mode for a conflict checker.

These tests exercise the real code paths (parser → checker names → analyzer
lookup → data-store cache keys) rather than the normaliser in isolation.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pytest
from packaging.version import parse

from depkeeper.core.data_store import PyPIDataStore, PyPIPackageData
from depkeeper.core.dependency_analyzer import (
    DependencyAnalyzer,
    _extract_specifier_for,
)
from depkeeper.core.parser import RequirementsParser
from depkeeper.models.conflict import Conflict
from depkeeper.models.package import Package

# Real distributions whose canonical name differs from their published
# spelling only by a dot.
DOTTED_DISTRIBUTIONS = [
    ("zope.interface", "zope-interface"),
    ("ruamel.yaml", "ruamel-yaml"),
    ("backports.zoneinfo", "backports-zoneinfo"),
    ("jaraco.classes", "jaraco-classes"),
]


def _pkg_data(name: str, versions: List[str]) -> PyPIPackageData:
    """Build package metadata with no ``requires_python`` restrictions."""
    ordered = sorted(versions, key=parse, reverse=True)
    return PyPIPackageData(
        name=name,
        latest_version=ordered[0],
        all_versions=ordered,
        parsed_versions=[(v, parse(v)) for v in ordered],
        python_requirements={v: None for v in ordered},
    )


class FakeStore(PyPIDataStore):
    """In-memory stand-in for :class:`PyPIDataStore` (no HTTP, no event loop).

    Lookups are performed on the *canonical* name so the fake cannot mask a
    normalisation bug in the code under test; ``dep_calls`` records the raw
    spelling each caller passed in.
    """

    def __init__(
        self,
        available: Optional[Dict[str, PyPIPackageData]] = None,
        deps: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        self.available: Dict[str, PyPIPackageData] = available or {}
        self.deps: Dict[str, List[str]] = deps or {}
        self.dep_calls: List[str] = []

    async def get_package_data(self, name: str) -> PyPIPackageData:
        return self.available[name]

    async def prefetch_packages(self, names: List[str]) -> None:
        return None

    async def get_version_dependencies(self, name: str, version: str) -> List[str]:
        self.dep_calls.append(name)
        return self.deps.get(f"{name}=={version}", [])

    def get_versions(self, name: str) -> List[str]:
        data = self.available.get(name)
        return data.all_versions if data else []


@pytest.mark.unit
class TestParserProducesCanonicalNames:
    """The parser is the origin of every update-set key."""

    @pytest.mark.parametrize("raw,canonical", DOTTED_DISTRIBUTIONS)
    def test_dotted_requirement_is_canonicalised(
        self, raw: str, canonical: str
    ) -> None:
        """``zope.interface==5.4.0`` is parsed as ``zope-interface``."""
        reqs = RequirementsParser().parse_string(f"{raw}==5.4.0\n")

        assert [r.name for r in reqs] == [canonical]

    def test_package_model_agrees_with_parser(self) -> None:
        """A ``Package`` built from either spelling gets one identity."""
        assert Package(name="zope.interface").name == "zope-interface"
        assert Package(name="Zope_Interface").name == "zope-interface"
        assert Package(name="zope-interface").name == "zope-interface"

    def test_conflict_endpoints_agree_with_parser(self) -> None:
        """Conflict endpoints must be lookup-compatible with ``pkg_lookup``."""
        conflict = Conflict(
            source_package="Flask",
            target_package="zope.interface",
            required_spec=">=6.0",
            conflicting_version="5.4.0",
        )

        assert conflict.source_package == "flask"
        assert conflict.target_package == "zope-interface"


@pytest.mark.unit
class TestCrossConflictDetectionForDottedNames:
    """M9 regression: the conflict must actually be found."""

    @staticmethod
    def _analyzer(dotted: str) -> DependencyAnalyzer:
        """flask 2.0.0 requires ``<dotted>>=6.0``; the file pins 5.4.0."""
        return DependencyAnalyzer(
            data_store=FakeStore(deps={"flask==2.0.0": [f"{dotted}>=6.0"]})
        )

    @pytest.mark.parametrize("dotted,canonical", DOTTED_DISTRIBUTIONS)
    async def test_conflict_is_detected(self, dotted: str, canonical: str) -> None:
        """Upstream dotted spelling resolves against the canonical update set."""
        packages = [
            Package(name="flask", current_version="2.0.0", recommended_version="2.0.0"),
            Package(
                name=canonical, current_version="5.4.0", recommended_version="5.4.0"
            ),
        ]
        update_set = {p.name: p.recommended_version for p in packages}

        conflicts = await self._analyzer(dotted)._find_cross_conflicts(
            packages, update_set
        )

        assert len(conflicts) == 1
        assert conflicts[0].source_package == "flask"
        assert conflicts[0].target_package == canonical
        assert conflicts[0].required_spec == ">=6.0"
        assert conflicts[0].conflicting_version == "5.4.0"

    async def test_satisfied_dotted_dependency_is_not_a_conflict(self) -> None:
        """No false positives: a satisfied specifier must stay silent."""
        packages = [
            Package(name="flask", current_version="2.0.0", recommended_version="2.0.0"),
            Package(
                name="zope-interface",
                current_version="6.1.0",
                recommended_version="6.1.0",
            ),
        ]
        update_set = {p.name: p.recommended_version for p in packages}

        conflicts = await self._analyzer("zope.interface")._find_cross_conflicts(
            packages, update_set
        )

        assert conflicts == []

    async def test_underscore_dependency_still_detected(self) -> None:
        """Baseline: the pre-existing underscore case must not regress."""
        analyzer = DependencyAnalyzer(
            data_store=FakeStore(deps={"flask==2.0.0": ["Flask_Login>=1.0"]})
        )
        packages = [
            Package(name="flask", current_version="2.0.0", recommended_version="2.0.0"),
            Package(
                name="flask-login",
                current_version="0.6.0",
                recommended_version="0.6.0",
            ),
        ]
        update_set = {p.name: p.recommended_version for p in packages}

        conflicts = await analyzer._find_cross_conflicts(packages, update_set)

        assert len(conflicts) == 1
        assert conflicts[0].target_package == "flask-login"


@pytest.mark.unit
class TestResolutionEndToEndForDottedNames:
    """The conflict must survive all the way into the ``ResolutionResult``."""

    async def test_dotted_conflict_is_annotated_and_resolved(self) -> None:
        """flask is downgraded within its major to satisfy zope-interface."""
        store = FakeStore(
            available={
                "flask": _pkg_data("flask", ["2.0.0", "2.2.5", "2.3.3"]),
                "zope-interface": _pkg_data("zope-interface", ["5.4.0", "5.5.2"]),
            },
            deps={
                "flask==2.3.3": ["zope.interface>=6.0"],
                "flask==2.2.5": ["zope.interface>=5.0"],
                "flask==2.0.0": ["zope.interface>=5.0"],
            },
        )
        packages = [
            Package(
                name="flask",
                current_version="2.0.0",
                latest_version="2.3.3",
                recommended_version="2.3.3",
            ),
            Package(
                name="zope-interface",
                current_version="5.4.0",
                latest_version="5.5.2",
                recommended_version="5.5.2",
            ),
        ]

        result = await DependencyAnalyzer(
            data_store=store
        ).resolve_and_annotate_conflicts(packages)

        assert result.converged
        # The conflict was seen (previously it was invisible) and resolved by
        # stepping flask back to a release compatible with zope-interface 5.x.
        assert result.resolved_versions["flask"].resolved == "2.2.5"
        assert result.resolved_versions["zope-interface"].resolved == "5.5.2"

    async def test_no_conflict_run_is_unaffected(self) -> None:
        """Baseline: a compatible set still converges with zero conflicts."""
        store = FakeStore(
            available={
                "flask": _pkg_data("flask", ["2.0.0", "2.3.3"]),
                "zope-interface": _pkg_data("zope-interface", ["5.4.0", "6.1.0"]),
            },
            deps={"flask==2.3.3": ["zope.interface>=6.0"]},
        )
        packages = [
            Package(
                name="flask", current_version="2.0.0", recommended_version="2.3.3"
            ),
            Package(
                name="zope-interface",
                current_version="5.4.0",
                recommended_version="6.1.0",
            ),
        ]

        result = await DependencyAnalyzer(
            data_store=store
        ).resolve_and_annotate_conflicts(packages)

        assert result.converged
        assert result.packages_with_conflicts == 0
        assert result.resolved_versions["flask"].resolved == "2.3.3"


@pytest.mark.unit
class TestExtractSpecifierForCanonicalisation:
    """``_extract_specifier_for`` matches upstream deps to a canonical target."""

    @pytest.mark.parametrize("dotted,canonical", DOTTED_DISTRIBUTIONS)
    def test_dotted_dependency_matches_canonical_target(
        self, dotted: str, canonical: str
    ) -> None:
        spec = _extract_specifier_for([f"{dotted}>=6.0", "click>=8.0"], canonical)

        assert spec is not None
        assert "6.0" in spec

    def test_unrelated_target_still_returns_none(self) -> None:
        assert _extract_specifier_for(["click>=8.0"], "zope-interface") is None


@pytest.mark.unit
class TestDataStoreCacheKeys:
    """Both spellings of a dotted distribution share one cache entry."""

    def test_cached_package_lookup_is_spelling_agnostic(self) -> None:
        store = PyPIDataStore.__new__(PyPIDataStore)
        store._package_data = {"zope-interface": _pkg_data("zope-interface", ["5.4.0"])}

        assert store.get_cached_package("zope.interface") is not None
        assert store.get_cached_package("Zope_Interface") is not None
        assert store.get_cached_package("zope-interface") is not None

    def test_versions_lookup_is_spelling_agnostic(self) -> None:
        store = PyPIDataStore.__new__(PyPIDataStore)
        store._package_data = {
            "ruamel-yaml": _pkg_data("ruamel-yaml", ["0.17.32", "0.18.5"])
        }

        assert store.get_versions("ruamel.yaml") == ["0.18.5", "0.17.32"]
