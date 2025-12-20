from depkeeper.utils.version_utils import get_update_type


class TestGetUpdateType:
    """Comprehensive test suite for get_update_type function."""

    def test_major_update(self):
        """Test major version updates (X.0.0 changes)."""
        assert get_update_type("1.0.0", "2.0.0") == "major"
        assert get_update_type("1.2.3", "2.0.0") == "major"
        assert get_update_type("1.9.9", "2.0.0") == "major"
        assert get_update_type("2.5.1", "3.0.0") == "major"
        assert get_update_type("9.9.9", "10.0.0") == "major"

    def test_minor_update(self):
        """Test minor version updates (0.X.0 changes)."""
        assert get_update_type("1.0.0", "1.1.0") == "minor"
        assert get_update_type("1.0.0", "1.2.0") == "minor"
        assert get_update_type("2.5.0", "2.6.0") == "minor"
        assert get_update_type("1.1.5", "1.2.0") == "minor"
        assert get_update_type("3.0.1", "3.1.0") == "minor"

    def test_patch_update(self):
        """Test patch version updates (0.0.X changes)."""
        assert get_update_type("1.0.0", "1.0.1") == "patch"
        assert get_update_type("1.2.3", "1.2.4") == "patch"
        assert get_update_type("2.5.9", "2.5.10") == "patch"
        assert get_update_type("1.0.0", "1.0.99") == "patch"
        assert get_update_type("3.1.0", "3.1.1") == "patch"

    def test_new_installation_current_none(self):
        """Test when current version is None (new installation)."""
        assert get_update_type(None, "1.0.0") == "new"
        assert get_update_type(None, "2.5.1") == "new"
        assert get_update_type(None, "0.1.0") == "new"
        assert get_update_type(None, "10.20.30") == "new"

    def test_target_none(self):
        """Test when target version is None."""
        assert get_update_type("1.0.0", None) == "unknown"
        assert get_update_type("2.5.1", None) == "unknown"
        assert get_update_type("0.1.0", None) == "unknown"

    def test_both_none(self):
        """Test when both versions are None."""
        assert get_update_type(None, None) == "unknown"

    def test_downgrade_major(self):
        """Test downgrade with major version decrease."""
        assert get_update_type("2.0.0", "1.0.0") == "downgrade"
        assert get_update_type("3.5.1", "2.9.9") == "downgrade"
        assert get_update_type("10.0.0", "9.9.9") == "downgrade"

    def test_downgrade_minor(self):
        """Test downgrade with minor version decrease."""
        assert get_update_type("1.2.0", "1.1.0") == "downgrade"
        assert get_update_type("2.5.0", "2.4.9") == "downgrade"
        assert get_update_type("1.10.0", "1.9.99") == "downgrade"

    def test_downgrade_patch(self):
        """Test downgrade with patch version decrease."""
        assert get_update_type("1.0.1", "1.0.0") == "downgrade"
        assert get_update_type("2.5.10", "2.5.9") == "downgrade"
        assert get_update_type("1.2.4", "1.2.3") == "downgrade"

    def test_same_version(self):
        """Test when versions are identical."""
        assert get_update_type("1.0.0", "1.0.0") == "same"
        assert get_update_type("2.5.1", "2.5.1") == "same"
        assert get_update_type("0.1.0", "0.1.0") == "same"

    def test_prerelease_to_stable(self):
        """Test upgrade from pre-release to stable version."""
        assert get_update_type("1.0.0a1", "1.0.0") == "patch"
        assert get_update_type("1.0.0b1", "1.0.0") == "patch"
        assert get_update_type("1.0.0rc1", "1.0.0") == "patch"
        assert get_update_type("2.0.0a1", "2.0.0") == "patch"

    def test_prerelease_to_prerelease(self):
        """Test upgrade between pre-release versions."""
        assert get_update_type("1.0.0a1", "1.0.0a2") == "patch"
        assert get_update_type("1.0.0b1", "1.0.0b2") == "patch"
        assert get_update_type("1.0.0rc1", "1.0.0rc2") == "patch"

    def test_stable_to_prerelease_next_version(self):
        """Test upgrade from stable to pre-release of next version."""
        assert get_update_type("1.0.0", "1.1.0a1") == "minor"
        assert get_update_type("1.0.0", "2.0.0a1") == "major"
        assert get_update_type("1.0.0", "1.0.1a1") == "patch"

    def test_prerelease_downgrade(self):
        """Test downgrade in pre-release versions."""
        assert get_update_type("1.0.0", "1.0.0a1") == "downgrade"
        assert get_update_type("1.0.0rc2", "1.0.0rc1") == "downgrade"

    def test_post_release_versions(self):
        """Test post-release version handling."""
        assert get_update_type("1.0.0", "1.0.0.post1") == "patch"
        assert get_update_type("1.0.0.post1", "1.0.0.post2") == "patch"
        assert get_update_type("1.0.0.post1", "1.0.1") == "patch"

    def test_dev_versions(self):
        """Test development version handling."""
        assert get_update_type("1.0.0.dev1", "1.0.0") == "patch"
        assert get_update_type("1.0.0.dev1", "1.0.0.dev2") == "patch"
        assert get_update_type("1.0.0", "1.1.0.dev1") == "minor"

    def test_two_part_versions(self):
        """Test versions with only major.minor (no patch)."""
        assert get_update_type("1.0", "2.0") == "major"
        assert get_update_type("1.0", "1.1") == "minor"
        assert get_update_type("1.5", "1.6") == "minor"

    def test_two_part_to_three_part(self):
        """Test conversion between two-part and three-part versions."""
        assert get_update_type("1.0", "2.0.0") == "major"
        assert get_update_type("1.0", "1.1.0") == "minor"
        assert get_update_type("1.0.0", "1.1") == "minor"

    def test_single_part_versions(self):
        """Test versions with only major version."""
        assert get_update_type("1", "2") == "major"
        assert get_update_type("1", "1") == "same"
        assert get_update_type("2", "1") == "downgrade"

    def test_single_part_to_multi_part(self):
        """Test conversion between single-part and multi-part versions."""
        assert get_update_type("1", "2.0.0") == "major"
        assert get_update_type("1", "1.1.0") == "minor"
        assert get_update_type("1.0.0", "2") == "major"

    def test_four_part_versions(self):
        """Test versions with four or more parts."""
        assert get_update_type("1.0.0.0", "2.0.0.0") == "major"
        assert get_update_type("1.0.0.0", "1.1.0.0") == "minor"
        assert get_update_type("1.0.0.0", "1.0.1.0") == "patch"
        # Fourth part change is ignored for classification
        assert get_update_type("1.0.0.0", "1.0.0.1") == "update"

    def test_zero_major_versions(self):
        """Test versions with major version 0 (pre-1.0)."""
        assert get_update_type("0.1.0", "0.2.0") == "minor"
        assert get_update_type("0.1.0", "0.1.1") == "patch"
        assert get_update_type("0.0.1", "0.0.2") == "patch"
        assert get_update_type("0.9.9", "1.0.0") == "major"

    def test_zero_minor_versions(self):
        """Test versions with minor version 0."""
        assert get_update_type("1.0.0", "1.0.1") == "patch"
        assert get_update_type("1.0.5", "1.0.6") == "patch"
        assert get_update_type("1.0.9", "1.1.0") == "minor"

    def test_invalid_current_version(self):
        """Test with invalid current version strings."""
        assert get_update_type("invalid", "1.0.0") == "unknown"
        assert get_update_type("not.a.version", "1.0.0") == "unknown"
        assert get_update_type("1.2.bad", "1.3.0") == "unknown"
        assert get_update_type("", "1.0.0") == "unknown"

    def test_invalid_target_version(self):
        """Test with invalid target version strings."""
        assert get_update_type("1.0.0", "invalid") == "unknown"
        assert get_update_type("1.0.0", "not.a.version") == "unknown"
        assert get_update_type("1.0.0", "1.2.bad") == "unknown"
        assert get_update_type("1.0.0", "") == "unknown"

    def test_both_invalid(self):
        """Test with both versions invalid."""
        assert get_update_type("invalid", "also.invalid") == "unknown"
        assert get_update_type("", "") == "unknown"

    def test_versions_with_whitespace(self):
        """Test versions with leading/trailing whitespace."""
        assert get_update_type(" 1.0.0 ", "2.0.0") == "major"
        assert get_update_type("1.0.0", " 1.1.0 ") == "minor"
        assert get_update_type(" 1.0.0 ", " 1.0.1 ") == "patch"

    def test_versions_with_v_prefix(self):
        """Test versions with 'v' prefix."""
        assert get_update_type("v1.0.0", "v2.0.0") == "major"
        assert get_update_type("v1.0.0", "v1.1.0") == "minor"
        assert get_update_type("v1.0.0", "v1.0.1") == "patch"

    def test_versions_with_mixed_prefix(self):
        """Test versions with and without prefix."""
        assert get_update_type("v1.0.0", "2.0.0") == "major"
        assert get_update_type("1.0.0", "v1.1.0") == "minor"

    def test_large_version_numbers(self):
        """Test with very large version numbers."""
        assert get_update_type("100.200.300", "101.0.0") == "major"
        assert get_update_type("100.200.300", "100.201.0") == "minor"
        assert get_update_type("100.200.300", "100.200.301") == "patch"
        assert get_update_type("999.999.999", "1000.0.0") == "major"

    def test_calendar_versioning(self):
        """Test calendar-style versions (YYYY.MM.DD or similar)."""
        assert get_update_type("2023.1.1", "2024.1.1") == "major"
        assert get_update_type("2023.1.1", "2023.2.1") == "minor"
        assert get_update_type("2023.1.1", "2023.1.2") == "patch"

    def test_complex_version_comparison(self):
        """Test complex version comparisons with multiple components."""

        assert get_update_type("1.0.0a1", "1.0.0b1") == "patch"
        assert get_update_type("1.0.0b1", "1.0.0rc1") == "patch"
        assert get_update_type("1.0.0rc1", "1.0.0") == "patch"
        assert get_update_type("1.0.0", "1.0.0.post1") == "patch"

    def test_many_version_comparisons(self):
        versions = [
            ("1.0.0", "2.0.0", "major"),
            ("1.0.0", "1.1.0", "minor"),
            ("1.0.0", "1.0.1", "patch"),
        ]
        for current, target, expected in versions:
            assert get_update_type(current, target) == expected

    def test_real_world_django_versions(self):
        """Test with real Django version patterns."""
        assert get_update_type("3.2.0", "4.0.0") == "major"
        assert get_update_type("3.2.0", "3.2.23") == "patch"
        assert get_update_type("4.0.0", "4.1.0") == "minor"

    def test_real_world_requests_versions(self):
        """Test with real requests library versions."""
        assert get_update_type("2.28.0", "2.31.0") == "minor"
        assert get_update_type("2.31.0", "3.0.0") == "major"
        assert get_update_type("2.28.0", "2.28.1") == "patch"

    def test_real_world_flask_versions(self):
        """Test with real Flask versions."""
        assert get_update_type("2.0.0", "2.0.1") == "patch"
        assert get_update_type("2.0.0", "2.1.0") == "minor"
        assert get_update_type("2.3.0", "3.0.0") == "major"

    def test_real_world_numpy_versions(self):
        """Test with real NumPy versions."""
        assert get_update_type("1.23.0", "1.24.0") == "minor"
        assert get_update_type("1.24.0", "1.24.1") == "patch"
        assert get_update_type("1.26.0", "2.0.0") == "major"

    def test_type_hints_compatibility(self):
        """Test that function works with Optional[str] type hints."""
        current: str = "1.0.0"
        target: str = "2.0.0"
        result = get_update_type(current, target)
        assert isinstance(result, str)
        assert result == "major"

    def test_documented_examples(self):
        """Test all examples from the function docstring."""
        # From docstring examples
        assert get_update_type("1.0.0", "2.0.0") == "major"
        assert get_update_type("2.5.0", "2.6.0") == "minor"
        assert get_update_type("1.2.3", "1.2.4") == "patch"
        assert get_update_type(None, "1.0.0") == "new"
        assert get_update_type("2.0.0", "1.0.0") == "downgrade"
        assert get_update_type("invalid", "1.0.0") == "unknown"
        assert get_update_type("1.0.0", None) == "unknown"
        assert get_update_type("1.0.0a1", "1.0.0") == "patch"

    def test_all_return_paths(self):
        """Ensure all return statements are covered."""
        # Test each unique return path in the function
        assert get_update_type(None, "1.0.0") == "new"  # Early return for None current
        assert (
            get_update_type("1.0.0", None) == "unknown"
        )  # Early return for None target
        assert get_update_type("2.0.0", "1.0.0") == "downgrade"  # Downgrade check
        assert get_update_type("1.0.0", "2.0.0") == "major"  # Major change
        assert get_update_type("1.0.0", "1.1.0") == "minor"  # Minor change
        assert get_update_type("1.0.0", "1.0.1") == "patch"  # Patch change
        assert get_update_type("1.0.0.0", "1.0.0.1") == "update"  # Generic update
        assert (
            get_update_type("invalid", "also-invalid") == "unknown"
        )  # Exception handling

    def test_exception_handling_paths(self):
        """Test all exception handling code paths."""
        assert get_update_type("not-a-version", "1.0.0") == "unknown"


class TestVersionUtilsProperties:
    """Property-based tests for version comparison invariants."""

    def test_version_comparison_symmetry(self):
        """Test that downgrade detection is symmetric with upgrade."""
        # If A -> B is upgrade, then B -> A should be downgrade
        test_cases = [
            ("1.0.0", "2.0.0"),
            ("1.0.0", "1.1.0"),
            ("1.0.0", "1.0.1"),
        ]
        for v1, v2 in test_cases:
            forward = get_update_type(v1, v2)
            backward = get_update_type(v2, v1)

            # If forward is an upgrade type, backward should be downgrade
            if forward in ("major", "minor", "patch"):
                assert backward == "downgrade"

            # If forward is downgrade, backward should be upgrade type
            if forward == "downgrade":
                assert backward in ("major", "minor", "patch", "update")

    def test_transitive_property(self):
        """Test version ordering transitivity."""
        # If A < B and B < C, then A < C
        versions = ["1.0.0", "1.1.0", "2.0.0"]

        # 1.0.0 < 1.1.0 (minor)
        assert get_update_type(versions[0], versions[1]) == "minor"
        # 1.1.0 < 2.0.0 (major)
        assert get_update_type(versions[1], versions[2]) == "major"
        # 1.0.0 < 2.0.0 (major)
        assert get_update_type(versions[0], versions[2]) == "major"

    def test_version_identity(self):
        """Test that version compared to itself returns 'update'."""
        versions = ["1.0.0", "2.5.1", "3.2.1", "0.1.0"]
        for version in versions:
            result = get_update_type(version, version)
            # Same version should return "update" (no change detected)
            assert result == "same"


class TestVersionUtilsIntegration:
    """Integration tests with real-world scenarios."""

    def test_update_strategy_minor_filtering(self):
        """Simulate filtering updates by strategy (minor only)."""
        # User wants only minor updates
        updates = [
            ("requests", "2.28.0", "3.0.0"),  # major
            ("flask", "2.0.0", "2.1.0"),  # minor - ACCEPT
            ("django", "3.2.0", "3.2.5"),  # patch - ACCEPT
        ]

        acceptable = []
        for pkg, current, target in updates:
            update_type = get_update_type(current, target)
            if update_type in ("minor", "patch"):
                acceptable.append(pkg)

        assert "flask" in acceptable
        assert "django" in acceptable
        assert "requests" not in acceptable

    def test_security_update_detection(self):
        """Simulate detecting which packages need security updates."""
        # Assume we have vulnerable versions to check
        current_versions = {
            "requests": "2.25.0",  # Vulnerable
            "django": "3.2.0",  # Vulnerable
            "flask": "2.0.3",  # Secure
        }

        security_fixes = {
            "requests": "2.28.0",
            "django": "3.2.5",
        }

        needs_update = []
        for pkg, current in current_versions.items():
            if pkg in security_fixes:
                target = security_fixes[pkg]
                update_type = get_update_type(current, target)
                if update_type != "downgrade":
                    needs_update.append((pkg, update_type))

        assert len(needs_update) == 2
        assert ("requests", "minor") in needs_update
        assert ("django", "patch") in needs_update
