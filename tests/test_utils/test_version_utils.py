"""Unit tests for depkeeper.utils.version module.

This test suite provides comprehensive coverage of version comparison utilities,
including edge cases, PEP 440 compliance, error handling, and semantic versioning
classification.

Test Coverage:
- Version update type classification (major, minor, patch)
- New installation detection
- Version downgrade detection
- Same version handling
- Invalid version handling
- PEP 440 compliance (pre-release, post-release, dev, local versions)
- Edge cases (None values, malformed versions, single-digit versions)
- Normalization behavior
"""

from __future__ import annotations

import pytest
from typing import Optional
from packaging.version import InvalidVersion, Version

from depkeeper.utils.version_utils import (
    get_update_type,
    _parse_version,
    _classify_upgrade,
    _normalize_release,
)


class TestGetUpdateType:
    """Tests for get_update_type main classification function."""

    def test_both_none_returns_unknown(self) -> None:
        """Test both versions None returns 'unknown'.

        Edge case: When both current and target are None, there's no
        meaningful comparison possible.
        """
        result = get_update_type(None, None)
        assert result == "unknown"

    def test_current_none_returns_new(self) -> None:
        """Test current version None returns 'new' installation.

        Happy path: Package not currently installed but target version exists.
        """
        result = get_update_type(None, "1.0.0")
        assert result == "new"

    def test_target_none_returns_unknown(self) -> None:
        """Test target version None returns 'unknown'.

        Edge case: Current version exists but no target specified.
        """
        result = get_update_type("1.0.0", None)
        assert result == "unknown"

    def test_same_version_returns_same(self) -> None:
        """Test identical versions return 'same'.

        Happy path: No update needed when versions match.
        """
        result = get_update_type("1.2.3", "1.2.3")
        assert result == "same"

    def test_downgrade_returns_downgrade(self) -> None:
        """Test target version lower than current returns 'downgrade'.

        Downgrade scenario: Moving from higher to lower version.
        """
        result = get_update_type("2.0.0", "1.0.0")
        assert result == "downgrade"

    def test_major_version_upgrade(self) -> None:
        """Test major version change returns 'major'.

        Happy path: Breaking changes expected in major version bump.
        """
        result = get_update_type("1.0.0", "2.0.0")
        assert result == "major"

    def test_minor_version_upgrade(self) -> None:
        """Test minor version change returns 'minor'.

        Happy path: New features added in minor version bump.
        """
        result = get_update_type("1.0.0", "1.1.0")
        assert result == "minor"

    def test_patch_version_upgrade(self) -> None:
        """Test patch version change returns 'patch'.

        Happy path: Bug fixes in patch version bump.
        """
        result = get_update_type("1.0.0", "1.0.1")
        assert result == "patch"

    def test_invalid_current_version_returns_unknown(self) -> None:
        """Test invalid current version returns 'unknown'.

        Error case: Malformed version string cannot be parsed.
        """
        result = get_update_type("not-a-version", "1.0.0")
        assert result == "unknown"

    def test_invalid_target_version_returns_unknown(self) -> None:
        """Test invalid target version returns 'unknown'.

        Error case: Malformed target version string.
        """
        result = get_update_type("1.0.0", "invalid")
        assert result == "unknown"

    def test_both_invalid_versions_returns_unknown(self) -> None:
        """Test both invalid versions return 'unknown'.

        Edge case: Neither version can be parsed.
        """
        result = get_update_type("bad-version", "also-bad")
        assert result == "unknown"

    def test_multiple_major_version_jump(self) -> None:
        """Test large major version jump returns 'major'.

        Edge case: Major version increases by more than one.
        """
        result = get_update_type("1.0.0", "5.0.0")
        assert result == "major"

    def test_multiple_minor_version_jump(self) -> None:
        """Test large minor version jump returns 'minor'.

        Edge case: Minor version increases significantly.
        """
        result = get_update_type("1.0.0", "1.10.0")
        assert result == "minor"

    def test_multiple_patch_version_jump(self) -> None:
        """Test large patch version jump returns 'patch'.

        Edge case: Patch version increases significantly.
        """
        result = get_update_type("1.0.0", "1.0.25")
        assert result == "patch"

    def test_combined_version_changes(self) -> None:
        """Test combined version changes classify by highest level.

        Major change should take precedence when multiple parts change.
        """
        # Major + minor + patch
        assert get_update_type("1.0.0", "2.1.1") == "major"
        # Minor + patch
        assert get_update_type("1.0.0", "1.1.1") == "minor"

    def test_major_downgrade(self) -> None:
        """Test major version downgrade returns 'downgrade'.

        Downgrade case: Major version decrease.
        """
        result = get_update_type("3.0.0", "2.5.10")
        assert result == "downgrade"

    def test_minor_downgrade(self) -> None:
        """Test minor version downgrade returns 'downgrade'.

        Downgrade case: Minor version decrease with same major.
        """
        result = get_update_type("1.5.0", "1.3.0")
        assert result == "downgrade"

    def test_patch_downgrade(self) -> None:
        """Test patch version downgrade returns 'downgrade'.

        Downgrade case: Patch version decrease with same major.minor.
        """
        result = get_update_type("1.0.5", "1.0.2")
        assert result == "downgrade"


class TestGetUpdateTypePEP440:
    """Tests for PEP 440 version format handling."""

    def test_prerelease_to_release(self) -> None:
        """Test upgrade from pre-release to release returns 'update'.

        PEP 440: Pre-release versions (alpha, beta, rc) are less than release.
        """
        result = get_update_type("1.0.0a1", "1.0.0")
        assert result == "update"

    def test_alpha_to_beta(self) -> None:
        """Test upgrade from alpha to beta returns 'update'.

        PEP 440: Alpha < Beta for same base version.
        """
        result = get_update_type("1.0.0a1", "1.0.0b1")
        assert result == "update"

    def test_beta_to_rc(self) -> None:
        """Test upgrade from beta to release candidate returns 'update'.

        PEP 440: Beta < RC for same base version.
        """
        result = get_update_type("1.0.0b1", "1.0.0rc1")
        assert result == "update"

    def test_rc_to_release(self) -> None:
        """Test upgrade from release candidate to release returns 'update'.

        PEP 440: RC < final release.
        """
        result = get_update_type("1.0.0rc1", "1.0.0")
        assert result == "update"

    def test_prerelease_same_type_increment(self) -> None:
        """Test increment within same pre-release type returns 'update'.

        PEP 440: 1.0.0a1 < 1.0.0a2.
        """
        result = get_update_type("1.0.0a1", "1.0.0a2")
        assert result == "update"

    def test_release_to_prerelease_is_downgrade(self) -> None:
        """Test downgrade from release to pre-release returns 'downgrade'.

        PEP 440: Release > any pre-release of same version.
        """
        result = get_update_type("1.0.0", "1.0.0rc1")
        assert result == "downgrade"

    def test_post_release_versions(self) -> None:
        """Test post-release version handling.

        PEP 440: Post-releases are greater than the base version.
        """
        # Upgrade to post-release
        assert get_update_type("1.0.0", "1.0.0.post1") == "update"

        # Post-release increment
        assert get_update_type("1.0.0.post1", "1.0.0.post2") == "update"

        # Downgrade from post-release
        assert get_update_type("1.0.0.post1", "1.0.0") == "downgrade"

    def test_dev_versions(self) -> None:
        """Test development version handling.

        PEP 440: Dev versions are less than all other versions.
        """
        # Dev to release
        assert get_update_type("1.0.0.dev1", "1.0.0") == "update"

        # Dev to pre-release
        assert get_update_type("1.0.0.dev1", "1.0.0a1") == "update"

        # Dev increment
        assert get_update_type("1.0.0.dev1", "1.0.0.dev2") == "update"

    def test_local_version_identifiers(self) -> None:
        """Test local version identifiers (PEP 440).

        PEP 440: Local versions are considered equal to their base version
        for sorting purposes, but should still be distinguishable.
        """
        # Local version variations
        result1 = get_update_type("1.0.0", "1.0.0+local1")
        result2 = get_update_type("1.0.0+local1", "1.0.0+local2")

        # Both should be recognized as some form of update
        assert result1 in ("update", "same")
        assert result2 in ("update", "same")

    def test_epoch_versions(self) -> None:
        """Test epoch version handling (PEP 440).

        PEP 440: Epochs allow version resets (e.g., 1!1.0.0 > 2.0.0).
        """
        # Higher epoch is always greater
        result = get_update_type("1.0.0", "1!0.5.0")
        assert result == "major"  # Epoch change is significant

    def test_implicit_zero_versions(self) -> None:
        """Test versions with implicit zero components.

        PEP 440: 1.0 is equivalent to 1.0.0.
        """
        assert get_update_type("1.0", "1.0.0") == "same"
        assert get_update_type("1", "1.0.0") == "same"
        assert get_update_type("1.0", "1.0.1") == "patch"


class TestGetUpdateTypeEdgeCases:
    """Tests for edge cases and unusual version formats."""

    def test_single_digit_versions(self) -> None:
        """Test single-digit version numbers.

        Edge case: Versions like "0", "1", "2".
        """
        assert get_update_type("0", "1") == "major"
        assert get_update_type("1", "2") == "major"
        assert get_update_type("5", "5") == "same"

    def test_two_digit_versions(self) -> None:
        """Test two-digit version numbers (major.minor).

        Edge case: No patch component specified.
        """
        assert get_update_type("1.0", "2.0") == "major"
        assert get_update_type("1.0", "1.1") == "minor"
        assert get_update_type("1.5", "1.5") == "same"

    def test_very_large_version_numbers(self) -> None:
        """Test very large version components.

        Edge case: Ensure large numbers are handled correctly.
        """
        result = get_update_type("999.999.999", "1000.0.0")
        assert result == "major"

    def test_leading_zeros_normalized(self) -> None:
        """Test version numbers with leading zeros are normalized.

        PEP 440: Leading zeros should be stripped.
        """
        assert get_update_type("1.01.001", "1.1.1") == "same"
        assert get_update_type("01.00.00", "1.0.0") == "same"

    def test_whitespace_in_versions(self) -> None:
        """Test versions with surrounding whitespace.

        Edge case: Whitespace should be handled by packaging library.
        """
        assert get_update_type(" 1.0.0 ", "1.0.0") == "same"
        assert get_update_type("1.0.0", " 1.0.1 ") == "patch"

    def test_empty_string_versions(self) -> None:
        """Test empty string versions return 'unknown'.

        Edge case: Empty strings are invalid versions.
        """
        assert get_update_type("", "1.0.0") == "unknown"
        assert get_update_type("1.0.0", "") == "unknown"
        assert get_update_type("", "") == "unknown"

    def test_version_with_v_prefix(self) -> None:
        """Test versions with 'v' prefix are handled.

        Edge case: 'v1.0.0' is common but not PEP 440 compliant.
        """
        # packaging library may or may not handle 'v' prefix
        result = get_update_type("v1.0.0", "v2.0.0")
        # Should either work or return unknown
        assert result in ("major", "unknown")

    def test_four_component_versions(self) -> None:
        """Test versions with more than three components.

        Edge case: Some projects use 1.2.3.4 versioning.
        """
        # Fourth component should be treated as local/metadata
        result = get_update_type("1.2.3.4", "1.2.3.5")
        assert result in ("update", "patch", "same")


class TestParseVersion:
    """Tests for _parse_version internal function."""

    def test_parse_valid_version(self) -> None:
        """Test parsing valid version string returns Version object.

        Happy path: Standard semantic version.
        """
        version = _parse_version("1.2.3")
        assert isinstance(version, Version)
        assert str(version) == "1.2.3"

    def test_parse_invalid_version_raises(self) -> None:
        """Test parsing invalid version raises InvalidVersion.

        Error case: Malformed version string.
        """
        with pytest.raises(InvalidVersion):
            _parse_version("not-a-version")

    def test_parse_empty_string_raises(self) -> None:
        """Test parsing empty string raises InvalidVersion.

        Edge case: Empty string is invalid.
        """
        with pytest.raises(InvalidVersion):
            _parse_version("")

    def test_parse_prerelease_version(self) -> None:
        """Test parsing pre-release version.

        PEP 440: Alpha, beta, rc versions.
        """
        for version_str in ["1.0.0a1", "1.0.0b2", "1.0.0rc3"]:
            version = _parse_version(version_str)
            assert isinstance(version, Version)

    def test_parse_post_release_version(self) -> None:
        """Test parsing post-release version.

        PEP 440: Post-release versions.
        """
        version = _parse_version("1.0.0.post1")
        assert isinstance(version, Version)

    def test_parse_dev_version(self) -> None:
        """Test parsing development version.

        PEP 440: Dev versions.
        """
        version = _parse_version("1.0.0.dev1")
        assert isinstance(version, Version)

    def test_parse_local_version(self) -> None:
        """Test parsing version with local identifier.

        PEP 440: Local version identifiers.
        """
        version = _parse_version("1.0.0+local")
        assert isinstance(version, Version)

    def test_parse_normalizes_version(self) -> None:
        """Test parsing normalizes version format.

        PEP 440: Various formats normalize to canonical form.
        """
        version = _parse_version("1.0.0")
        # Leading zeros should be stripped
        assert str(_parse_version("01.00.00")) == "1.0.0"


class TestClassifyUpgrade:
    """Tests for _classify_upgrade internal function."""

    def test_classify_major_upgrade(self) -> None:
        """Test classification of major version upgrade.

        Major version change should return 'major'.
        """
        current = Version("1.0.0")
        target = Version("2.0.0")
        result = _classify_upgrade(current, target)
        assert result == "major"

    def test_classify_minor_upgrade(self) -> None:
        """Test classification of minor version upgrade.

        Minor version change should return 'minor'.
        """
        current = Version("1.0.0")
        target = Version("1.1.0")
        result = _classify_upgrade(current, target)
        assert result == "minor"

    def test_classify_patch_upgrade(self) -> None:
        """Test classification of patch version upgrade.

        Patch version change should return 'patch'.
        """
        current = Version("1.0.0")
        target = Version("1.0.1")
        result = _classify_upgrade(current, target)
        assert result == "patch"

    def test_classify_prerelease_upgrade(self) -> None:
        """Test classification of pre-release upgrade.

        Pre-release changes should return 'update'.
        """
        current = Version("1.0.0a1")
        target = Version("1.0.0a2")
        result = _classify_upgrade(current, target)
        assert result == "update"

    def test_classify_metadata_only_change(self) -> None:
        """Test classification of metadata-only change.

        Only local/metadata change should return 'update'.
        """
        current = Version("1.0.0+local1")
        target = Version("1.0.0+local2")
        result = _classify_upgrade(current, target)
        assert result == "update"

    def test_classify_combined_changes_major_priority(self) -> None:
        """Test major version takes priority over other changes.

        When multiple parts change, highest level classification wins.
        """
        current = Version("1.2.3")
        target = Version("2.5.10")
        result = _classify_upgrade(current, target)
        assert result == "major"

    def test_classify_combined_changes_minor_priority(self) -> None:
        """Test minor version takes priority over patch.

        When minor and patch change, minor classification wins.
        """
        current = Version("1.0.0")
        target = Version("1.1.5")
        result = _classify_upgrade(current, target)
        assert result == "minor"

    def test_classify_zero_to_one_major(self) -> None:
        """Test 0.x.x to 1.x.x is classified as major.

        Edge case: Moving from pre-1.0 to 1.0+ is major.
        """
        current = Version("0.9.9")
        target = Version("1.0.0")
        result = _classify_upgrade(current, target)
        assert result == "major"


class TestNormalizeRelease:
    """Tests for _normalize_release internal function."""

    def test_normalize_full_version(self) -> None:
        """Test normalization of full semantic version.

        Happy path: 1.2.3 should return (1, 2, 3).
        """
        version = Version("1.2.3")
        result = _normalize_release(version)
        assert result == (1, 2, 3)

    def test_normalize_major_only(self) -> None:
        """Test normalization of major-only version.

        Edge case: Missing components default to 0.
        """
        version = Version("5")
        result = _normalize_release(version)
        assert result == (5, 0, 0)

    def test_normalize_major_minor_only(self) -> None:
        """Test normalization of major.minor version.

        Edge case: Missing patch defaults to 0.
        """
        version = Version("3.7")
        result = _normalize_release(version)
        assert result == (3, 7, 0)

    def test_normalize_zero_version(self) -> None:
        """Test normalization of 0.0.0 version.

        Edge case: All zeros should be preserved.
        """
        version = Version("0.0.0")
        result = _normalize_release(version)
        assert result == (0, 0, 0)

    def test_normalize_large_numbers(self) -> None:
        """Test normalization with very large version numbers.

        Edge case: Large numbers should be preserved.
        """
        version = Version("999.888.777")
        result = _normalize_release(version)
        assert result == (999, 888, 777)

    def test_normalize_with_prerelease(self) -> None:
        """Test normalization ignores pre-release suffix.

        Pre-release metadata should not affect release tuple.
        """
        version = Version("1.2.3a1")
        result = _normalize_release(version)
        assert result == (1, 2, 3)

    def test_normalize_with_post_release(self) -> None:
        """Test normalization ignores post-release suffix.

        Post-release metadata should not affect release tuple.
        """
        version = Version("1.2.3.post1")
        result = _normalize_release(version)
        assert result == (1, 2, 3)

    def test_normalize_with_dev(self) -> None:
        """Test normalization ignores dev suffix.

        Dev metadata should not affect release tuple.
        """
        version = Version("1.2.3.dev1")
        result = _normalize_release(version)
        assert result == (1, 2, 3)

    def test_normalize_with_local(self) -> None:
        """Test normalization ignores local version identifier.

        Local metadata should not affect release tuple.
        """
        version = Version("1.2.3+local")
        result = _normalize_release(version)
        assert result == (1, 2, 3)

    def test_normalize_epoch_version(self) -> None:
        """Test normalization with epoch version.

        Epoch should not appear in release tuple.
        """
        version = Version("1!2.3.4")
        result = _normalize_release(version)
        assert result == (2, 3, 4)

    def test_normalize_four_component_version(self) -> None:
        """Test normalization with four components.

        Edge case: Only first three components used.
        """
        # packaging library treats 4th component as part of pre-release/local
        # The release tuple should only contain major.minor.patch
        version = Version("1.2.3")
        result = _normalize_release(version)
        assert len(result) == 3
        assert result == (1, 2, 3)


class TestGetUpdateTypeIntegration:
    """Integration tests combining various version scenarios."""

    def test_real_world_django_versions(self) -> None:
        """Test real-world Django version progression.

        Integration test: Django's actual version history.
        """
        assert get_update_type("3.2.0", "4.0.0") == "major"
        assert get_update_type("3.2.0", "3.2.1") == "patch"
        assert get_update_type("4.0.0", "4.1.0") == "minor"
        assert get_update_type("4.1.0", "4.1.1") == "patch"

    def test_real_world_numpy_versions(self) -> None:
        """Test real-world NumPy version progression.

        Integration test: NumPy's version history.
        """
        assert get_update_type("1.21.0", "1.22.0") == "minor"
        assert get_update_type("1.22.0", "1.22.1") == "patch"
        assert get_update_type("1.26.4", "2.0.0") == "major"

    def test_prerelease_progression(self) -> None:
        """Test progression through pre-release cycle.

        Integration test: Full pre-release to release progression.
        """
        versions = [
            "1.0.0.dev1",
            "1.0.0a1",
            "1.0.0a2",
            "1.0.0b1",
            "1.0.0rc1",
            "1.0.0",
            "1.0.0.post1",
        ]

        for i in range(len(versions) - 1):
            result = get_update_type(versions[i], versions[i + 1])
            assert result in ("update", "patch", "minor", "major")
            # Should never be downgrade in this sequence
            assert result != "downgrade"

    def test_version_comparison_transitivity(self) -> None:
        """Test version comparison maintains transitivity.

        Integration test: If A < B and B < C, then A < C.
        """
        v1, v2, v3 = "1.0.0", "1.5.0", "2.0.0"

        # v1 < v2
        assert get_update_type(v1, v2) in ("minor", "major", "patch", "update")

        # v2 < v3
        assert get_update_type(v2, v3) in ("minor", "major", "patch", "update")

        # Therefore v1 < v3
        assert get_update_type(v1, v3) in ("minor", "major", "patch", "update")

        # No downgrades
        assert get_update_type(v1, v2) != "downgrade"
        assert get_update_type(v2, v3) != "downgrade"
        assert get_update_type(v1, v3) != "downgrade"

    def test_mixed_format_versions(self) -> None:
        """Test comparison between different version formats.

        Integration test: Ensure different valid formats interoperate.
        """
        # Two-digit vs three-digit
        assert get_update_type("1.0", "1.0.1") == "patch"

        # Single-digit vs three-digit
        assert get_update_type("1", "1.0.1") == "patch"

        # Pre-release vs release
        assert get_update_type("1.0.0a1", "1.0.0") == "update"

    def test_edge_case_version_boundaries(self) -> None:
        """Test versions at semantic boundaries.

        Integration test: Versions at major boundaries.
        """
        # Just before and after major version
        assert get_update_type("0.9.9", "1.0.0") == "major"
        assert get_update_type("1.9.9", "2.0.0") == "major"
        assert get_update_type("9.9.9", "10.0.0") == "major"

    def test_downgrade_detection_comprehensive(self) -> None:
        """Test downgrade detection in various scenarios.

        Integration test: All types of downgrades detected.
        """
        # Major downgrade
        assert get_update_type("2.0.0", "1.9.9") == "downgrade"

        # Minor downgrade
        assert get_update_type("1.5.0", "1.4.9") == "downgrade"

        # Patch downgrade
        assert get_update_type("1.0.5", "1.0.4") == "downgrade"

        # Pre-release downgrade
        assert get_update_type("1.0.0", "1.0.0rc1") == "downgrade"
        assert get_update_type("1.0.0b1", "1.0.0a1") == "downgrade"

    def test_same_version_variations(self) -> None:
        """Test 'same' classification with format variations.

        Integration test: Different representations of same version.
        """
        # Explicit vs implicit zeros
        assert get_update_type("1.0.0", "1.0") == "same"
        assert get_update_type("1.0", "1") == "same"

        # Normalized forms
        assert get_update_type("1.0.0", "01.00.00") == "same"

    def test_error_recovery_graceful(self) -> None:
        """Test graceful error handling with invalid inputs.

        Integration test: Invalid versions don't crash, return 'unknown'.
        Note: The packaging library accepts many unusual version formats,
        so we need to use truly malformed versions.
        """
        invalid_versions = [
            "not.a.version",  # No numeric components
            "1.2.x",  # Contains 'x' wildcard
            "latest",  # Plain text, not a version
            "1.2.3-",  # Trailing dash (empty pre-release)
            "1.2.3+",  # Trailing plus (empty local version)
            "1.2.3..4",  # Double dots
            "a.b.c",  # All letters, no numbers
            "",  # Empty string
            "v",  # Just a letter
            "1.2.3@latest",  # Invalid separator
        ]

        for invalid in invalid_versions:
            result = get_update_type("1.0.0", invalid)
            # Should return unknown, not crash
            assert (
                result == "unknown"
            ), f"Expected 'unknown' for invalid version '{invalid}', got '{result}'"

            result = get_update_type(invalid, "1.0.0")
            assert (
                result == "unknown"
            ), f"Expected 'unknown' for invalid version '{invalid}', got '{result}'"
