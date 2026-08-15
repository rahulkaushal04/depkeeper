"""Tests for M10 — the reported version must be the version that is applied.

``resolve_and_annotate_conflicts()`` used to write ``Package.recommended_version``
twice: first from the resolution loop's decision, then again from an
*independent* "compatible alternative" search. The second write won, so
``depkeeper check``/``update`` displayed the resolver's version in the
resolution summary while writing the alternative to ``requirements.txt``.

The invariant these tests lock in::

    pkg.recommended_version == result.resolved_versions[pkg.name].resolved

for every package, on every code path.
"""

from __future__ import annotations

from typing import List, Tuple

import pytest

from depkeeper.core.dependency_analyzer import (
    DependencyAnalyzer,
    ResolutionResult,
    ResolutionStatus,
    _live_conflicts,
    _satisfies,
    _satisfies_all,
)
from depkeeper.models.conflict import Conflict
from depkeeper.models.package import Package
from tests.support.factories import make_conflict
from tests.support.pypi import FakePyPIStore, package_data as _pkg_data


def _conflict(
    source: str,
    source_version: str,
    target: str,
    spec: str,
    conflicting: str,
) -> Conflict:
    """Positional shim so the scenario tables below read in dependency order."""
    return make_conflict(
        source,
        spec,
        target,
        source_version=source_version,
        conflicting_version=conflicting,
    )


def _assert_single_source_of_truth(
    packages: List[Package], result: ResolutionResult
) -> None:
    """Every annotated package must mirror its :class:`PackageResolution`."""
    for pkg in packages:
        resolution = result.resolved_versions[pkg.name]
        assert pkg.recommended_version == resolution.resolved, (
            f"{pkg.name}: applied {pkg.recommended_version!r} but reported "
            f"{resolution.resolved!r}"
        )


# ---------------------------------------------------------------------------
# The original defect
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStaleConflictDoesNotOverrideResolution:
    """A conflict the loop *resolved* must not rewrite the applied version."""

    @staticmethod
    def _scenario() -> Tuple[FakePyPIStore, List[Package]]:
        # flask 2.3.3 caps werkzeug at <2.3, so the loop steps flask back to
        # 2.2.5 and keeps werkzeug at 2.3.7. The historical conflict still
        # names werkzeug, and its "compatible alternative" is 2.2.3.
        store = FakePyPIStore(
            available={
                "flask": _pkg_data("flask", ["2.0.0", "2.2.5", "2.3.3"]),
                "werkzeug": _pkg_data(
                    "werkzeug", ["2.0.0", "2.1.0", "2.2.3", "2.3.7"]
                ),
            },
            dependencies={
                "flask==2.3.3": ["werkzeug>=2.2,<2.3"],
                "flask==2.2.5": ["werkzeug>=2.0"],
                "flask==2.0.0": ["werkzeug>=2.0"],
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
                name="werkzeug",
                current_version="2.0.0",
                latest_version="2.3.7",
                recommended_version="2.3.7",
            ),
        ]
        return store, packages

    async def test_applied_version_matches_reported_version(self) -> None:
        """Regression: werkzeug was written as 2.2.3 but reported as 2.3.7."""
        store, packages = self._scenario()

        result = await DependencyAnalyzer(
            data_store=store
        ).resolve_and_annotate_conflicts(packages)

        assert result.converged is True
        assert result.resolved_versions["werkzeug"].resolved == "2.3.7"
        assert result.resolved_versions["flask"].resolved == "2.2.5"
        _assert_single_source_of_truth(packages, result)

    async def test_alternative_is_still_reported_as_advisory(self) -> None:
        """The suggestion survives for display — it just no longer wins."""
        store, packages = self._scenario()

        result = await DependencyAnalyzer(
            data_store=store
        ).resolve_and_annotate_conflicts(packages)

        werkzeug = result.resolved_versions["werkzeug"]
        assert werkzeug.compatible_alternative == "2.2.3"
        assert werkzeug.resolved == "2.3.7"

    async def test_update_would_write_the_reported_version(self) -> None:
        """End-to-end: ``_find_updates`` must agree with the summary."""
        from depkeeper.commands.update import _find_updates
        from depkeeper.models.requirement import Requirement

        store, packages = self._scenario()
        requirements = [
            Requirement(name="flask", specs=[("==", "2.0.0")], line_number=1),
            Requirement(name="werkzeug", specs=[("==", "2.0.0")], line_number=2),
        ]

        result = await DependencyAnalyzer(
            data_store=store
        ).resolve_and_annotate_conflicts(packages)
        updates = _find_updates(packages, requirements, pin=True)

        applied = {req.name: version for req, _pkg, version in updates}
        assert applied["werkzeug"] == result.resolved_versions["werkzeug"].resolved
        assert applied["flask"] == result.resolved_versions["flask"].resolved


# ---------------------------------------------------------------------------
# The rescue path the old override existed for
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnresolvedConflictAdoptsAlternative:
    """A conflict the loop never fixed still gets the alternative applied."""

    @staticmethod
    def _stalled_scenario() -> Tuple[FakePyPIStore, List[Package]]:
        # ``app`` needs an impossible libx (>=9.0 while libx is a 1.x series)
        # and a satisfiable liby (>=1.2). Only one conflict per source package
        # is processed per pass, and the libx one stalls the loop immediately,
        # so liby is never even attempted by the resolution strategies.
        store = FakePyPIStore(
            available={
                "app": _pkg_data("app", ["1.0.0"]),
                "libx": _pkg_data("libx", ["1.0.0"]),
                "liby": _pkg_data("liby", ["1.0.0", "1.2.0", "1.5.0"]),
            },
            dependencies={"app==1.0.0": ["libx>=9.0", "liby>=1.2"]},
        )
        packages = [
            Package(name="app", current_version="1.0.0", recommended_version="1.0.0"),
            Package(name="libx", current_version="1.0.0", recommended_version="1.0.0"),
            Package(name="liby", current_version="1.0.0", recommended_version="1.0.0"),
        ]
        return store, packages

    async def test_live_conflict_adopts_alternative_into_the_result(self) -> None:
        """The rescue is applied *and* reported, instead of only applied."""
        store, packages = self._stalled_scenario()

        result = await DependencyAnalyzer(
            data_store=store
        ).resolve_and_annotate_conflicts(packages)

        liby = result.resolved_versions["liby"]
        assert liby.compatible_alternative == "1.5.0"
        assert liby.resolved == "1.5.0"
        assert liby.status is ResolutionStatus.UPGRADED
        assert liby in result.get_changed_packages()
        _assert_single_source_of_truth(packages, result)

    async def test_impossible_conflict_stays_on_current(self) -> None:
        """No alternative exists for libx, so nothing is invented."""
        store, packages = self._stalled_scenario()

        result = await DependencyAnalyzer(
            data_store=store
        ).resolve_and_annotate_conflicts(packages)

        libx = result.resolved_versions["libx"]
        assert libx.compatible_alternative is None
        assert libx.resolved == "1.0.0"
        _assert_single_source_of_truth(packages, result)

    async def test_adoption_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """Operators must be able to see why the loop's answer was replaced."""
        import logging

        store, packages = self._stalled_scenario()

        with caplog.at_level(logging.INFO, logger="depkeeper.dependency_analyzer"):
            await DependencyAnalyzer(data_store=store).resolve_and_annotate_conflicts(
                packages
            )

        messages = [r.getMessage() for r in caplog.records]
        assert any("Adopting compatible alternative for liby" in m for m in messages)


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLivenessHelpers:
    """``_live_conflicts`` decides whether a recorded conflict still applies."""

    def test_conflict_is_dead_when_source_moved_on(self) -> None:
        conflict = _conflict("flask", "2.3.3", "werkzeug", ">=2.2,<2.3", "2.3.7")

        live = _live_conflicts(
            {"flask": "2.2.5", "werkzeug": "2.3.7"}, "werkzeug", "2.3.7", [conflict]
        )

        assert live == []

    def test_conflict_is_dead_when_target_now_satisfies_it(self) -> None:
        conflict = _conflict("flask", "2.3.3", "werkzeug", ">=2.2,<2.3", "2.3.7")

        live = _live_conflicts(
            {"flask": "2.3.3", "werkzeug": "2.2.3"}, "werkzeug", "2.2.3", [conflict]
        )

        assert live == []

    def test_conflict_is_live_when_both_halves_unchanged(self) -> None:
        conflict = _conflict("flask", "2.3.3", "werkzeug", ">=2.2,<2.3", "2.3.7")

        live = _live_conflicts(
            {"flask": "2.3.3", "werkzeug": "2.3.7"}, "werkzeug", "2.3.7", [conflict]
        )

        assert live == [conflict]

    def test_unparseable_specifier_never_vetoes_a_version(self) -> None:
        """Malformed upstream metadata must not drive the applied version."""
        conflict = _conflict("flask", "2.3.3", "werkzeug", "not-a-spec", "2.3.7")

        assert _satisfies("2.3.7", "not-a-spec") is True
        assert (
            _live_conflicts(
                {"flask": "2.3.3", "werkzeug": "2.3.7"},
                "werkzeug",
                "2.3.7",
                [conflict],
            )
            == []
        )

    def test_missing_target_version_is_treated_as_satisfied(self) -> None:
        conflict = _conflict("flask", "2.3.3", "werkzeug", ">=2.2", "2.3.7")

        assert _satisfies(None, ">=2.2") is True
        assert _live_conflicts({"flask": "2.3.3"}, "werkzeug", None, [conflict]) == []

    def test_satisfies_all_requires_every_specifier(self) -> None:
        conflicts = [
            _conflict("a", "1.0.0", "libx", ">=1.2", "1.0.0"),
            _conflict("b", "1.0.0", "libx", "<1.5", "1.0.0"),
        ]

        assert _satisfies_all("1.3.0", conflicts) is True
        assert _satisfies_all("1.5.0", conflicts) is False
        assert _satisfies_all("1.0.0", conflicts) is False


# ---------------------------------------------------------------------------
# Invariant on the untouched paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInvariantHoldsOnEveryPath:
    """The projection must hold for conflict-free and metadata-less runs too."""

    async def test_conflict_free_run(self) -> None:
        store = FakePyPIStore(
            available={
                "flask": _pkg_data("flask", ["2.0.0", "2.3.3"]),
                "werkzeug": _pkg_data("werkzeug", ["2.0.0", "2.3.7"]),
            },
            dependencies={"flask==2.3.3": ["werkzeug>=2.0"]},
        )
        packages = [
            Package(
                name="flask", current_version="2.0.0", recommended_version="2.3.3"
            ),
            Package(
                name="werkzeug", current_version="2.0.0", recommended_version="2.3.7"
            ),
        ]

        result = await DependencyAnalyzer(
            data_store=store
        ).resolve_and_annotate_conflicts(packages)

        assert result.packages_with_conflicts == 0
        _assert_single_source_of_truth(packages, result)

    async def test_package_without_any_version_information(self) -> None:
        """An unavailable stub keeps ``None`` rather than gaining a version."""
        store = FakePyPIStore(available={"ghost": _pkg_data("ghost", ["1.0.0"])})
        packages = [
            Package(name="ghost", current_version=None, recommended_version=None)
        ]

        result = await DependencyAnalyzer(
            data_store=store
        ).resolve_and_annotate_conflicts(packages)

        assert result.resolved_versions["ghost"].resolved is None
        assert packages[0].recommended_version is None

    async def test_package_with_no_recommendation_keeps_current(self) -> None:
        """Pre-existing behaviour: the current version becomes the target."""
        store = FakePyPIStore(available={"stable": _pkg_data("stable", ["1.0.0"])})
        packages = [
            Package(name="stable", current_version="1.0.0", recommended_version=None)
        ]

        result = await DependencyAnalyzer(
            data_store=store
        ).resolve_and_annotate_conflicts(packages)

        assert result.resolved_versions["stable"].resolved == "1.0.0"
        _assert_single_source_of_truth(packages, result)


# ---------------------------------------------------------------------------
# A non-PEP-440 current/proposed version must never fabricate a conflict.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNonPep440VersionNeverFabricatesAConflict:
    """A ``==`` pin the parser accepted but ``packaging`` cannot parse.

    ``core/parser.py`` does not validate the text after ``==``, so a
    requirements file can legitimately contain a pin like
    ``mylib==1.0.0.RELEASE``. That string flows into the resolver's update
    set unchanged and must not be treated as violating another package's
    dependency on it.
    """

    @staticmethod
    def _scenario() -> Tuple[FakePyPIStore, List[Package]]:
        store = FakePyPIStore(
            available={
                "pkg-a": _pkg_data("pkg-a", ["1.0.0", "2.0.0"]),
                "pkg-b": _pkg_data("pkg-b", ["1.0.0"]),
            },
            dependencies={
                "pkg-a==1.0.0": ["pkg-b>=1.0"],
                "pkg-a==2.0.0": ["pkg-b>=1.0"],
            },
        )
        packages = [
            Package(
                name="pkg-a",
                current_version="1.0.0",
                recommended_version="2.0.0",
            ),
            Package(
                name="pkg-b",
                current_version="1.0.0.RELEASE",
                recommended_version="1.0.0.RELEASE",
            ),
        ]
        return store, packages

    async def test_legitimate_upgrade_is_not_discarded(self) -> None:
        store, packages = self._scenario()

        result = await DependencyAnalyzer(
            data_store=store
        ).resolve_and_annotate_conflicts(packages)

        assert result.packages_with_conflicts == 0
        assert result.resolved_versions["pkg-a"].resolved == "2.0.0"
        assert result.resolved_versions["pkg-a"].status == ResolutionStatus.KEPT_RECOMMENDED
        _assert_single_source_of_truth(packages, result)

    async def test_find_cross_conflicts_treats_it_as_satisfied(self) -> None:
        store, packages = self._scenario()
        analyzer = DependencyAnalyzer(data_store=store)
        update_set = {"pkg-a": "2.0.0", "pkg-b": "1.0.0.RELEASE"}

        conflicts = await analyzer._find_cross_conflicts(packages, update_set)

        assert conflicts == []

    def test_satisfies_treats_unparseable_version_as_satisfied(self) -> None:
        assert _satisfies("1.0.0.RELEASE", ">=1.0") is True
        assert _satisfies_all("1.0.0.RELEASE", [
            make_conflict("pkg-a", ">=1.0", "pkg-b", conflicting_version="1.0.0.RELEASE")
        ]) is True
