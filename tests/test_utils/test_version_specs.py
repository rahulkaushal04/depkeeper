"""Tests for the PEP 440 specifier-set helpers in ``utils.version_utils``.

Primary purpose: guard against regression M5 — a version update must move
only the *lower bound* of a declared range. Upper bounds, exclusions and
wildcard bands are deliberate compatibility statements and must survive.
"""

from __future__ import annotations

import pytest

from depkeeper.utils.version_utils import (
    is_lower_bound,
    retained_specs,
    rewrite_version_specs,
    specs_allow_version,
    specs_to_string,
)


@pytest.mark.unit
class TestSpecsToString:
    """Tests for ``specs_to_string``."""

    def test_joins_pairs_in_order(self) -> None:
        assert specs_to_string([(">=", "2.0"), ("<", "3.0")]) == ">=2.0,<3.0"

    def test_empty_specs_render_empty_string(self) -> None:
        assert specs_to_string([]) == ""


@pytest.mark.unit
class TestIsLowerBound:
    """Tests for ``is_lower_bound``."""

    @pytest.mark.parametrize("operator", [">=", ">", "~="])
    def test_lower_bound_operators(self, operator: str) -> None:
        assert is_lower_bound(operator) is True

    @pytest.mark.parametrize("operator", ["<", "<=", "!=", "==", "==="])
    def test_non_lower_bound_operators(self, operator: str) -> None:
        assert is_lower_bound(operator) is False


@pytest.mark.unit
class TestRetainedSpecs:
    """Tests for ``retained_specs``."""

    def test_upper_bound_is_retained(self) -> None:
        assert retained_specs([(">=", "5.0"), ("<", "6.0")]) == [("<", "6.0")]

    def test_exclusion_is_retained(self) -> None:
        assert retained_specs([(">=", "2.0"), ("!=", "2.5.0")]) == [("!=", "2.5.0")]

    def test_exact_pin_is_not_retained(self) -> None:
        assert retained_specs([("==", "2.20.0")]) == []

    def test_wildcard_band_is_retained(self) -> None:
        assert retained_specs([("==", "2.*")]) == [("==", "2.*")]

    def test_compatible_release_is_not_retained(self) -> None:
        assert retained_specs([("~=", "2.0")]) == []

    def test_empty_specs(self) -> None:
        assert retained_specs([]) == []


@pytest.mark.unit
class TestSpecsAllowVersion:
    """Tests for ``specs_allow_version``."""

    def test_version_inside_range(self) -> None:
        assert specs_allow_version([("<", "3.0")], "2.9.0") is True

    def test_version_above_upper_bound(self) -> None:
        assert specs_allow_version([("<", "3.0")], "3.1.0") is False

    def test_excluded_version(self) -> None:
        assert specs_allow_version([("!=", "2.5.0")], "2.5.0") is False

    def test_no_specs_allows_everything(self) -> None:
        assert specs_allow_version([], "1.0.0") is True

    def test_prerelease_target_is_allowed(self) -> None:
        """Pre-releases must not be rejected by SpecifierSet defaults."""
        assert specs_allow_version([("<", "3.0")], "2.9.0rc1") is True

    def test_unparseable_specifier_is_permissive(self) -> None:
        """Mirrors pip: an uninterpretable constraint does not block."""
        assert specs_allow_version([("<>", "bogus")], "1.0.0") is True

    def test_unparseable_version_is_permissive(self) -> None:
        assert specs_allow_version([("<", "3.0")], "not-a-version") is True


@pytest.mark.unit
class TestRewriteVersionSpecs:
    """M5 regression tests for ``rewrite_version_specs``."""

    def test_range_keeps_upper_bound(self) -> None:
        """The audit's exact scenario: ``>=5.0,<6.0`` must keep ``<6.0``."""
        assert rewrite_version_specs([(">=", "5.0"), ("<", "6.0")], "5.5.3") == [
            (">=", "5.5.3"),
            ("<", "6.0"),
        ]

    def test_exclusions_are_preserved(self) -> None:
        assert rewrite_version_specs(
            [(">=", "2.0"), ("!=", "2.5.0")], "2.31.0"
        ) == [(">=", "2.31.0"), ("!=", "2.5.0")]

    def test_strict_greater_widens_to_inclusive(self) -> None:
        """``>2.0`` must become ``>=X`` so ``X`` itself stays installable."""
        assert rewrite_version_specs([(">", "2.0")], "2.2.28") == [
            (">=", "2.2.28")
        ]

    def test_compatible_release_keeps_author_precision(self) -> None:
        """``~=2.0`` (two components) stays two components."""
        assert rewrite_version_specs([("~=", "2.0")], "2.3.3") == [("~=", "2.3")]

    def test_compatible_release_three_components(self) -> None:
        assert rewrite_version_specs([("~=", "2.0.0")], "2.3.3") == [
            ("~=", "2.3.3")
        ]

    def test_compatible_release_pads_short_target(self) -> None:
        assert rewrite_version_specs([("~=", "2.0.0")], "3") == [("~=", "3.0.0")]

    def test_compatible_release_preserves_epoch(self) -> None:
        assert rewrite_version_specs([("~=", "1!2.0")], "1!2.3.3") == [
            ("~=", "1!2.3")
        ]

    def test_exact_pin_is_repinned(self) -> None:
        assert rewrite_version_specs([("==", "1.26.0")], "1.26.18") == [
            ("==", "1.26.18")
        ]

    def test_arbitrary_equality_is_repinned(self) -> None:
        assert rewrite_version_specs([("===", "1.0")], "1.1") == [("===", "1.1")]

    def test_no_specs_gains_exact_pin(self) -> None:
        assert rewrite_version_specs([], "23.1.0") == [("==", "23.1.0")]

    def test_upper_bound_only_gains_floor(self) -> None:
        assert rewrite_version_specs([("<", "2.0")], "1.26.4") == [
            ("<", "2.0"),
            (">=", "1.26.4"),
        ]

    def test_wildcard_band_is_preserved_and_floored(self) -> None:
        assert rewrite_version_specs([("==", "2.*")], "2.5.0") == [
            ("==", "2.*"),
            (">=", "2.5.0"),
        ]

    def test_duplicate_floors_are_collapsed(self) -> None:
        assert rewrite_version_specs(
            [(">=", "1.0"), (">", "1.2"), ("<", "2")], "1.9.0"
        ) == [(">=", "1.9.0"), ("<", "2")]

    def test_unparseable_compatible_release_falls_back(self) -> None:
        assert rewrite_version_specs([("~=", "bogus")], "1.2.3") == [
            ("~=", "1.2.3")
        ]

    def test_original_specs_are_not_mutated(self) -> None:
        specs = [(">=", "5.0"), ("<", "6.0")]
        rewrite_version_specs(specs, "5.5.3")
        assert specs == [(">=", "5.0"), ("<", "6.0")]

    def test_result_allows_the_target_version(self) -> None:
        """The rewritten set must actually admit the version it targets."""
        rewritten = rewrite_version_specs([(">=", "5.0"), ("<", "6.0")], "5.5.3")
        assert specs_allow_version(rewritten, "5.5.3") is True
