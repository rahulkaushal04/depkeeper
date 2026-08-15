"""Tests for constraint-aware recommendations in ``VersionChecker``.

Primary purpose: guard against regression M5 — declared upper bounds and
exclusions survive an update, so a recommendation that violates them would
produce an unsatisfiable requirement line such as ``flask>=2.3.3,<2.3``.
The checker must therefore never propose a version the requirements file
itself forbids.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import pytest

from depkeeper.core.checker import VersionChecker
from depkeeper.core.data_store import PyPIDataStore
from depkeeper.models import Requirement
from tests.support.pypi import package_data as _pkg_data


@pytest.fixture
def checker() -> VersionChecker:
    return VersionChecker(data_store=PyPIDataStore.__new__(PyPIDataStore))


VERSIONS = ["2.0.0", "2.1.0", "2.2.5", "2.3.3", "3.0.0"]


@pytest.mark.unit
class TestConstraintAwareRecommendation:
    """``_build_package_from_data`` must honour retained constraints."""

    def test_without_constraints_picks_highest_in_major(
        self, checker: VersionChecker
    ) -> None:
        """Baseline: unchanged behaviour when no constraints are declared."""
        pkg = checker._build_package_from_data(
            _pkg_data("flask", VERSIONS), "2.0.0", None
        )
        assert pkg.recommended_version == "2.3.3"

    def test_upper_bound_caps_the_recommendation(
        self, checker: VersionChecker
    ) -> None:
        """M5: ``<2.3`` must cap the recommendation at 2.2.5, not 2.3.3."""
        pkg = checker._build_package_from_data(
            _pkg_data("flask", VERSIONS), "2.0.0", [("<", "2.3")]
        )
        assert pkg.recommended_version == "2.2.5"

    def test_exclusion_skips_the_excluded_version(
        self, checker: VersionChecker
    ) -> None:
        pkg = checker._build_package_from_data(
            _pkg_data("flask", VERSIONS), "2.0.0", [("!=", "2.3.3")]
        )
        assert pkg.recommended_version == "2.2.5"

    def test_unsatisfiable_constraint_stays_on_current(
        self, checker: VersionChecker
    ) -> None:
        """No eligible candidate must not crash and must not downgrade."""
        pkg = checker._build_package_from_data(
            _pkg_data("flask", VERSIONS), "2.0.0", [("<", "1.0")]
        )
        assert pkg.recommended_version == "2.0.0"

    def test_constraints_apply_without_current_version(
        self, checker: VersionChecker
    ) -> None:
        """The unpinned path is filtered too, and still ignores other majors."""
        pkg = checker._build_package_from_data(
            _pkg_data("flask", VERSIONS), None, [("<", "3.0")]
        )
        assert pkg.recommended_version == "2.3.3"

    def test_major_boundary_still_wins(self, checker: VersionChecker) -> None:
        """Constraint filtering must not allow crossing a major boundary."""
        pkg = checker._build_package_from_data(
            _pkg_data("flask", VERSIONS), "2.0.0", [("<", "4.0")]
        )
        assert pkg.recommended_version == "2.3.3"


@pytest.mark.unit
class TestWildcardPinStillGetsRecommendations:
    """``pkg==2.*`` must not silently disable update checking."""

    def test_wildcard_pin_still_receives_a_recommendation(
        self, checker: VersionChecker
    ) -> None:
        pkg = checker._build_package_from_data(
            _pkg_data("flask", VERSIONS), "2.*", None
        )

        assert pkg.recommended_version == "2.3.3"
        assert pkg.current_version == "2.*"

    def test_wildcard_pin_respects_declared_constraints(
        self, checker: VersionChecker
    ) -> None:
        pkg = checker._build_package_from_data(
            _pkg_data("flask", VERSIONS), "2.*", [("<", "2.3")]
        )

        assert pkg.recommended_version == "2.2.5"

    def test_wildcard_pin_never_crosses_a_major_boundary(
        self, checker: VersionChecker
    ) -> None:
        pkg = checker._build_package_from_data(
            _pkg_data("flask", VERSIONS), "3.*", None
        )

        assert pkg.recommended_version == "3.0.0"

    def test_multi_segment_wildcard_pin_anchors_on_the_right_major(
        self, checker: VersionChecker
    ) -> None:
        pkg = checker._build_package_from_data(
            _pkg_data("flask", VERSIONS), "2.2.*", None
        )

        assert pkg.recommended_version == "2.3.3"

    def test_recommendation_is_visible_as_an_outdated_update(
        self, checker: VersionChecker
    ) -> None:
        pkg = checker._build_package_from_data(
            _pkg_data("flask", VERSIONS), "2.*", None
        )

        assert pkg.has_update() is True
        assert pkg.requires_downgrade is False
        status, installed, latest, recommended = pkg.get_status_summary()
        assert status == "outdated"
        assert installed == "2.*"
        assert recommended == "2.3.3"

    def test_update_command_selects_it_for_writing(
        self, checker: VersionChecker
    ) -> None:
        from depkeeper.commands.update import _find_updates
        from depkeeper.models.requirement import Requirement

        req = Requirement(name="flask", specs=[("==", "2.*")], line_number=1)
        pkg = checker._build_package_from_data(
            _pkg_data("flask", VERSIONS), "2.*", None
        )

        updates = _find_updates([pkg], [req])

        assert updates == [(req, pkg, "2.3.3")]


@pytest.mark.unit
class TestConstraintForwarding:
    """The retained constraints of a requirement reach the checker."""

    def test_task_forwards_retained_specs(
        self, checker: VersionChecker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: List[Optional[List[Tuple[str, str]]]] = []

        async def fake_get_package_info(
            name: str,
            current_version: Optional[str] = None,
            constraints: Optional[List[Tuple[str, str]]] = None,
        ) -> None:
            captured.append(constraints)

        monkeypatch.setattr(checker, "get_package_info", fake_get_package_info)

        req = Requirement(
            name="celery", specs=[(">=", "5.0"), ("<", "6.0"), ("!=", "5.2.0")]
        )

        import asyncio

        async def run() -> None:
            await checker._create_package_check_task(req)

        asyncio.run(run())

        assert captured == [[("<", "6.0"), ("!=", "5.2.0")]]
