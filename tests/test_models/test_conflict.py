"""Unit tests for depkeeper.models.conflict module.

This test suite provides comprehensive coverage of dependency conflict
data models, including conflict representation, normalization, version
compatibility checking, and specifier set operations.

Test Coverage:
- Conflict initialization and validation
- Package name normalization (PEP 503)
- Conflict string representations
- JSON serialization
- ConflictSet management and operations
- Version compatibility resolution
- Specifier set parsing and validation
- Edge cases (invalid versions, pre-releases, empty data)
"""

from __future__ import annotations

import pytest

from depkeeper.models.conflict import Conflict, ConflictSet, _normalize_name


class TestNormalizeName:
    """Tests for _normalize_name package normalization."""

    def test_lowercase_conversion(self) -> None:
        """Test package names are converted to lowercase.

        Per PEP 503, package names should be case-insensitive.
        """
        assert _normalize_name("Django") == "django"
        assert _normalize_name("REQUESTS") == "requests"
        assert _normalize_name("NumPy") == "numpy"

    def test_underscore_to_dash(self) -> None:
        """Test underscores are replaced with dashes.

        PEP 503 normalization converts underscores to hyphens.
        """
        assert _normalize_name("python_package") == "python-package"
        assert _normalize_name("my_test_pkg") == "my-test-pkg"

    def test_combined_normalization(self) -> None:
        """Test combined case and underscore normalization.

        Should handle both transformations simultaneously.
        """
        assert _normalize_name("My_Package") == "my-package"
        assert _normalize_name("Test_PKG_Name") == "test-pkg-name"

    def test_already_normalized(self) -> None:
        """Test already normalized names remain unchanged.

        Happy path: Properly formatted names should pass through.
        """
        assert _normalize_name("requests") == "requests"
        assert _normalize_name("django-rest-framework") == "django-rest-framework"

    def test_empty_string(self) -> None:
        """Test empty string normalization.

        Edge case: Empty strings should remain empty.
        """
        assert _normalize_name("") == ""

    def test_multiple_underscores(self) -> None:
        """Test multiple consecutive underscores.

        Edge case: Multiple underscores should all convert to dashes.
        """
        assert _normalize_name("my__package___name") == "my--package---name"

    def test_special_characters_preserved(self) -> None:
        """Test other special characters are preserved.

        Edge case: Only underscores should be replaced, other chars unchanged.
        """
        assert _normalize_name("pkg.name") == "pkg.name"
        assert _normalize_name("pkg-v2") == "pkg-v2"


class TestConflictInit:
    """Tests for Conflict initialization and post-init processing."""

    def test_basic_initialization(self) -> None:
        """Test Conflict can be created with required parameters.

        Happy path: Basic conflict creation with all required fields.
        """
        conflict = Conflict(
            source_package="django",
            target_package="requests",
            required_spec=">=2.0.0",
            conflicting_version="1.5.0",
        )
        assert conflict.source_package == "django"
        assert conflict.target_package == "requests"
        assert conflict.required_spec == ">=2.0.0"
        assert conflict.conflicting_version == "1.5.0"
        assert conflict.source_version is None

    def test_with_source_version(self) -> None:
        """Test Conflict initialization with source version.

        Should properly store optional source_version parameter.
        """
        conflict = Conflict(
            source_package="django",
            target_package="requests",
            required_spec=">=2.0.0",
            conflicting_version="1.5.0",
            source_version="4.0.0",
        )
        assert conflict.source_version == "4.0.0"

    def test_package_name_normalization_on_init(self) -> None:
        """Test package names are normalized in __post_init__.

        Package names should be normalized according to PEP 503.
        """
        conflict = Conflict(
            source_package="Django_App",
            target_package="REQUESTS_Lib",
            required_spec=">=2.0.0",
            conflicting_version="1.5.0",
        )
        assert conflict.source_package == "django-app"
        assert conflict.target_package == "requests-lib"

    def test_immutability(self) -> None:
        """Test Conflict is frozen (immutable).

        Frozen dataclass should prevent attribute modification.
        """
        conflict = Conflict(
            source_package="django",
            target_package="requests",
            required_spec=">=2.0.0",
            conflicting_version="1.5.0",
        )
        with pytest.raises(AttributeError):
            conflict.source_package = "flask"

    def test_empty_required_spec(self) -> None:
        """Test Conflict with empty specifier string.

        Edge case: Empty spec string (though invalid for version checks).
        """
        conflict = Conflict(
            source_package="django",
            target_package="requests",
            required_spec="",
            conflicting_version="1.0.0",
        )
        assert conflict.required_spec == ""

    def test_complex_version_specifier(self) -> None:
        """Test Conflict with complex version specifier.

        Should handle compound specifiers like >=2.0,<3.0.
        """
        conflict = Conflict(
            source_package="django",
            target_package="requests",
            required_spec=">=2.0.0,<3.0.0,!=2.5.0",
            conflicting_version="2.5.0",
        )
        assert conflict.required_spec == ">=2.0.0,<3.0.0,!=2.5.0"

    def test_wildcard_version(self) -> None:
        """Test Conflict with wildcard version specifier.

        Edge case: Wildcards like ==2.* should be preserved.
        """
        conflict = Conflict(
            source_package="django",
            target_package="requests",
            required_spec="==2.*",
            conflicting_version="3.0.0",
        )
        assert conflict.required_spec == "==2.*"


class TestConflictDisplayMethods:
    """Tests for Conflict string representation methods."""

    def test_to_display_string_without_source_version(self) -> None:
        """Test display string when source version is not known.

        Should show only source package name, not version.
        """
        conflict = Conflict(
            source_package="django",
            target_package="requests",
            required_spec=">=2.0.0",
            conflicting_version="1.5.0",
        )
        result = conflict.to_display_string()
        assert result == "django requires requests>=2.0.0"

    def test_to_display_string_with_source_version(self) -> None:
        """Test display string when source version is known.

        Should show source package with version pinned.
        """
        conflict = Conflict(
            source_package="django",
            target_package="requests",
            required_spec=">=2.0.0",
            conflicting_version="1.5.0",
            source_version="4.0.0",
        )
        result = conflict.to_display_string()
        assert result == "django==4.0.0 requires requests>=2.0.0"

    def test_to_short_string(self) -> None:
        """Test compact conflict summary.

        Should provide abbreviated format with just source and spec.
        """
        conflict = Conflict(
            source_package="django",
            target_package="requests",
            required_spec=">=2.0.0",
            conflicting_version="1.5.0",
        )
        result = conflict.to_short_string()
        assert result == "django needs >=2.0.0"

    def test_str_method(self) -> None:
        """Test __str__ delegates to to_display_string.

        String conversion should use the full display format.
        """
        conflict = Conflict(
            source_package="django",
            target_package="requests",
            required_spec=">=2.0.0",
            conflicting_version="1.5.0",
            source_version="4.0.0",
        )
        result = str(conflict)
        assert result == conflict.to_display_string()
        assert "django==4.0.0" in result

    def test_repr_method(self) -> None:
        """Test __repr__ provides developer-friendly representation.

        Should show Conflict constructor format for debugging.
        """
        conflict = Conflict(
            source_package="django",
            target_package="requests",
            required_spec=">=2.0.0",
            conflicting_version="1.5.0",
        )
        result = repr(conflict)
        assert result.startswith("Conflict(")
        assert "source_package='django'" in result
        assert "target_package='requests'" in result
        assert "required_spec='>=2.0.0'" in result
        assert "conflicting_version='1.5.0'" in result

    def test_display_string_with_complex_spec(self) -> None:
        """Test display string with compound version specifier.

        Edge case: Complex specifiers should be shown in full.
        """
        conflict = Conflict(
            source_package="django",
            target_package="requests",
            required_spec=">=2.0,<3.0,!=2.5.0",
            conflicting_version="2.5.0",
        )
        result = conflict.to_display_string()
        assert ">=2.0,<3.0,!=2.5.0" in result

    def test_display_string_with_special_characters(self) -> None:
        """Test display string with packages containing special chars.

        Edge case: Normalized names should appear in output.
        """
        conflict = Conflict(
            source_package="My_Package",
            target_package="Other_Lib",
            required_spec=">=1.0",
            conflicting_version="0.5",
        )
        result = conflict.to_display_string()
        # Should show normalized names
        assert "my-package" in result
        assert "other-lib" in result


class TestConflictJSONSerialization:
    """Tests for Conflict.to_json method."""

    def test_to_json_without_source_version(self) -> None:
        """Test JSON serialization without source version.

        Happy path: All fields should be present, source_version is None.
        """
        conflict = Conflict(
            source_package="django",
            target_package="requests",
            required_spec=">=2.0.0",
            conflicting_version="1.5.0",
        )
        result = conflict.to_json()

        assert result["source_package"] == "django"
        assert result["target_package"] == "requests"
        assert result["required_spec"] == ">=2.0.0"
        assert result["conflicting_version"] == "1.5.0"
        assert result["source_version"] is None

    def test_to_json_with_source_version(self) -> None:
        """Test JSON serialization with source version.

        All fields including source_version should be serialized.
        """
        conflict = Conflict(
            source_package="django",
            target_package="requests",
            required_spec=">=2.0.0",
            conflicting_version="1.5.0",
            source_version="4.0.0",
        )
        result = conflict.to_json()

        assert result["source_version"] == "4.0.0"

    def test_to_json_dict_structure(self) -> None:
        """Test JSON output is a dictionary with correct keys.

        Should return dict with all expected keys.
        """
        conflict = Conflict(
            source_package="django",
            target_package="requests",
            required_spec=">=2.0.0",
            conflicting_version="1.5.0",
        )
        result = conflict.to_json()

        assert isinstance(result, dict)
        expected_keys = {
            "source_package",
            "source_version",
            "target_package",
            "required_spec",
            "conflicting_version",
        }
        assert set(result.keys()) == expected_keys

    def test_to_json_with_normalized_names(self) -> None:
        """Test JSON serialization uses normalized package names.

        Normalized names should appear in JSON output.
        """
        conflict = Conflict(
            source_package="Django_App",
            target_package="REQUESTS_Lib",
            required_spec=">=2.0.0",
            conflicting_version="1.5.0",
        )
        result = conflict.to_json()

        assert result["source_package"] == "django-app"
        assert result["target_package"] == "requests-lib"

    def test_to_json_roundtrip_compatibility(self) -> None:
        """Test JSON output can be used to reconstruct Conflict.

        Integration test: JSON should contain all data for reconstruction.
        """
        original = Conflict(
            source_package="django",
            target_package="requests",
            required_spec=">=2.0.0",
            conflicting_version="1.5.0",
            source_version="4.0.0",
        )
        json_data = original.to_json()

        # Remove source_version if None for reconstruction
        kwargs = {k: v for k, v in json_data.items() if v is not None}
        reconstructed = Conflict(**kwargs)

        assert reconstructed.source_package == original.source_package
        assert reconstructed.target_package == original.target_package
        assert reconstructed.required_spec == original.required_spec
        assert reconstructed.conflicting_version == original.conflicting_version
        assert reconstructed.source_version == original.source_version


class TestConflictSetInit:
    """Tests for ConflictSet initialization."""

    def test_basic_initialization(self) -> None:
        """Test ConflictSet can be created with package name.

        Happy path: Basic ConflictSet with empty conflicts list.
        """
        conflict_set = ConflictSet(package_name="requests")
        assert conflict_set.package_name == "requests"
        assert conflict_set.conflicts == []

    def test_initialization_with_conflicts(self) -> None:
        """Test ConflictSet can be initialized with existing conflicts.

        Should accept a list of conflicts during construction.
        """
        conflicts = [
            Conflict("django", "requests", ">=2.0", "1.5"),
            Conflict("flask", "requests", ">=2.5", "1.5"),
        ]
        conflict_set = ConflictSet(package_name="requests", conflicts=conflicts)
        assert len(conflict_set.conflicts) == 2
        assert conflict_set.conflicts == conflicts

    def test_package_name_normalization(self) -> None:
        """Test package name is normalized in __post_init__.

        Package name should follow PEP 503 normalization.
        """
        conflict_set = ConflictSet(package_name="My_Package")
        assert conflict_set.package_name == "my-package"

    def test_mutable_dataclass(self) -> None:
        """Test ConflictSet is mutable (not frozen).

        Should allow modification of conflicts list.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.package_name = "flask"  # Should not raise
        assert conflict_set.package_name == "flask"

    def test_empty_package_name(self) -> None:
        """Test ConflictSet with empty package name.

        Edge case: Empty string should be accepted.
        """
        conflict_set = ConflictSet(package_name="")
        assert conflict_set.package_name == ""


class TestConflictSetAddConflict:
    """Tests for ConflictSet.add_conflict method."""

    def test_add_single_conflict(self) -> None:
        """Test adding a single conflict to the set.

        Happy path: Conflict should be appended to conflicts list.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict = Conflict("django", "requests", ">=2.0", "1.5")

        conflict_set.add_conflict(conflict)

        assert len(conflict_set.conflicts) == 1
        assert conflict_set.conflicts[0] == conflict

    def test_add_multiple_conflicts(self) -> None:
        """Test adding multiple conflicts sequentially.

        All conflicts should be preserved in order.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict1 = Conflict("django", "requests", ">=2.0", "1.5")
        conflict2 = Conflict("flask", "requests", ">=2.5", "1.5")
        conflict3 = Conflict("fastapi", "requests", ">=3.0", "1.5")

        conflict_set.add_conflict(conflict1)
        conflict_set.add_conflict(conflict2)
        conflict_set.add_conflict(conflict3)

        assert len(conflict_set.conflicts) == 3
        assert conflict_set.conflicts == [conflict1, conflict2, conflict3]

    def test_add_duplicate_conflicts(self) -> None:
        """Test adding duplicate conflicts.

        Edge case: Duplicates should be allowed (no deduplication).
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict = Conflict("django", "requests", ">=2.0", "1.5")

        conflict_set.add_conflict(conflict)
        conflict_set.add_conflict(conflict)

        assert len(conflict_set.conflicts) == 2
        assert conflict_set.conflicts[0] is conflict_set.conflicts[1]


class TestConflictSetHasConflicts:
    """Tests for ConflictSet.has_conflicts method."""

    def test_has_conflicts_when_empty(self) -> None:
        """Test has_conflicts returns False for empty set.

        Empty conflicts list should return False.
        """
        conflict_set = ConflictSet(package_name="requests")
        assert conflict_set.has_conflicts() is False

    def test_has_conflicts_when_populated(self) -> None:
        """Test has_conflicts returns True when conflicts exist.

        Non-empty conflicts list should return True.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict = Conflict("django", "requests", ">=2.0", "1.5")
        conflict_set.add_conflict(conflict)

        assert conflict_set.has_conflicts() is True

    def test_has_conflicts_after_initialization(self) -> None:
        """Test has_conflicts with conflicts provided at init.

        Should return True when initialized with conflicts.
        """
        conflicts = [Conflict("django", "requests", ">=2.0", "1.5")]
        conflict_set = ConflictSet(package_name="requests", conflicts=conflicts)

        assert conflict_set.has_conflicts() is True


class TestConflictSetGetMaxCompatibleVersion:
    """Tests for ConflictSet.get_max_compatible_version method."""

    def test_no_conflicts_returns_none(self) -> None:
        """Test returns None when no conflicts exist.

        Empty conflict set should return None.
        """
        conflict_set = ConflictSet(package_name="requests")
        result = conflict_set.get_max_compatible_version(["1.0.0", "2.0.0"])
        assert result is None

    def test_single_conflict_compatible_version(self) -> None:
        """Test finds compatible version with single conflict.

        Happy path: Should return highest compatible version.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=2.0.0", "1.5.0"))

        available = ["1.5.0", "2.0.0", "2.5.0", "3.0.0"]
        result = conflict_set.get_max_compatible_version(available)

        assert result == "3.0.0"

    def test_multiple_conflicts_intersection(self) -> None:
        """Test finds version satisfying multiple constraints.

        Should find version compatible with all conflicts.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=2.0.0", "1.5.0"))
        conflict_set.add_conflict(Conflict("flask", "requests", "<3.0.0", "3.5.0"))

        available = ["1.5.0", "2.0.0", "2.5.0", "3.0.0", "3.5.0"]
        result = conflict_set.get_max_compatible_version(available)

        # Should be >=2.0.0 AND <3.0.0, so 2.5.0 is max
        assert result == "2.5.0"

    def test_no_compatible_version_returns_none(self) -> None:
        """Test returns None when no version satisfies all constraints.

        Conflicting specifiers with no intersection should return None.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=3.0.0", "1.5.0"))
        conflict_set.add_conflict(Conflict("flask", "requests", "<2.0.0", "3.5.0"))

        available = ["1.5.0", "2.0.0", "2.5.0", "3.0.0"]
        result = conflict_set.get_max_compatible_version(available)

        # No version satisfies both >=3.0.0 AND <2.0.0
        assert result is None

    def test_excludes_prerelease_versions(self) -> None:
        """Test pre-release versions are ignored.

        Should skip versions with pre-release tags like alpha, beta, rc.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=2.0.0", "1.5.0"))

        available = ["2.0.0", "2.5.0", "3.0.0a1", "3.0.0b2", "3.0.0rc1"]
        result = conflict_set.get_max_compatible_version(available)

        # Should return 2.5.0, not any 3.0.0 pre-release
        assert result == "2.5.0"

    def test_handles_invalid_version_strings(self) -> None:
        """Test gracefully handles invalid version strings.

        Edge case: Invalid versions should be skipped, not raise.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=2.0.0", "1.5.0"))

        available = ["invalid", "2.0.0", "not-a-version", "2.5.0", "bad"]
        result = conflict_set.get_max_compatible_version(available)

        # Should skip invalid and return 2.5.0
        assert result == "2.5.0"

    def test_handles_invalid_specifier_returns_none(self) -> None:
        """Test returns None when conflict has invalid specifier.

        Edge case: Invalid specifier syntax should return None gracefully.
        """
        conflict_set = ConflictSet(package_name="requests")
        # Invalid specifier syntax
        conflict_set.add_conflict(
            Conflict("django", "requests", "invalid>>spec", "1.5.0")
        )

        available = ["1.0.0", "2.0.0", "3.0.0"]
        result = conflict_set.get_max_compatible_version(available)

        assert result is None

    def test_empty_available_versions(self) -> None:
        """Test with empty available versions list.

        Edge case: No available versions should return None.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=2.0.0", "1.5.0"))

        result = conflict_set.get_max_compatible_version([])
        assert result is None

    def test_complex_specifier_combinations(self) -> None:
        """Test complex version specifiers with multiple operators.

        Should handle compound specifiers like >=2.0,<3.0,!=2.5.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(
            Conflict("django", "requests", ">=2.0.0,<3.0.0,!=2.5.0", "1.5.0")
        )

        available = ["1.5.0", "2.0.0", "2.4.0", "2.5.0", "2.6.0", "3.0.0"]
        result = conflict_set.get_max_compatible_version(available)

        # Should return 2.6.0 (not 2.5.0 which is excluded, not 3.0.0 which is >=3.0)
        assert result == "2.6.0"

    def test_wildcard_specifiers(self) -> None:
        """Test wildcard version specifiers like ==2.*.

        Edge case: Wildcard specifiers should match correct versions.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", "==2.*", "1.5.0"))

        available = ["1.5.0", "2.0.0", "2.5.0", "2.9.9", "3.0.0"]
        result = conflict_set.get_max_compatible_version(available)

        # Should return highest 2.x version
        assert result == "2.9.9"

    def test_exact_version_match(self) -> None:
        """Test exact version specifier ==X.Y.Z.

        Should only match the exact specified version.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", "==2.5.0", "1.5.0"))

        available = ["2.0.0", "2.4.0", "2.5.0", "2.6.0", "3.0.0"]
        result = conflict_set.get_max_compatible_version(available)

        # Should return exactly 2.5.0
        assert result == "2.5.0"

    def test_less_than_specifier(self) -> None:
        """Test less-than version specifier <X.Y.Z.

        Should return highest version below threshold.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", "<3.0.0", "3.5.0"))

        available = ["2.0.0", "2.5.0", "2.9.9", "3.0.0", "3.5.0"]
        result = conflict_set.get_max_compatible_version(available)

        # Should return 2.9.9 (highest < 3.0.0)
        assert result == "2.9.9"

    def test_tilde_compatible_release(self) -> None:
        """Test tilde compatible release specifier ~=X.Y.

        Edge case: ~= allows last version component to increment.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", "~=2.5", "1.5.0"))

        available = ["2.0.0", "2.4.0", "2.5.0", "2.5.9", "2.6.0", "3.0.0"]
        result = conflict_set.get_max_compatible_version(available)

        # ~=2.5 means >=2.5,<3.0, so 2.6.0 is max
        assert result == "2.6.0"

    def test_version_sorting(self) -> None:
        """Test versions are correctly sorted to find max.

        Should use proper version comparison, not string sorting.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=1.0", "0.5.0"))

        # Versions not in sorted order
        available = ["2.10.0", "2.2.0", "2.1.0", "10.0.0", "2.20.0"]
        result = conflict_set.get_max_compatible_version(available)

        # Should return 10.0.0 (not "2.9" by string comparison)
        assert result == "10.0.0"

    def test_dev_versions_excluded(self) -> None:
        """Test development versions are excluded.

        Edge case: .devN versions should be treated like pre-releases.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=2.0", "1.5.0"))

        available = ["2.0.0", "2.5.0", "3.0.0.dev1", "3.0.0.dev2"]
        result = conflict_set.get_max_compatible_version(available)

        # Should not include dev versions
        assert result == "2.5.0"

    def test_post_release_versions_included(self) -> None:
        """Test post-release versions are included.

        Post-releases (.postN) are not pre-releases and should be considered.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=2.0", "1.5.0"))

        available = ["2.0.0", "2.5.0", "2.5.0.post1", "2.5.0.post2"]
        result = conflict_set.get_max_compatible_version(available)

        # Post-releases should be considered
        assert result == "2.5.0.post2"


class TestConflictSetMagicMethods:
    """Tests for ConflictSet magic methods."""

    def test_len_empty(self) -> None:
        """Test __len__ returns 0 for empty conflict set.

        len() should return number of conflicts.
        """
        conflict_set = ConflictSet(package_name="requests")
        assert len(conflict_set) == 0

    def test_len_with_conflicts(self) -> None:
        """Test __len__ returns count of conflicts.

        len() should accurately reflect number of conflicts.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=2.0", "1.5"))
        conflict_set.add_conflict(Conflict("flask", "requests", ">=2.5", "1.5"))

        assert len(conflict_set) == 2

    def test_iter_empty(self) -> None:
        """Test __iter__ on empty conflict set.

        Iteration over empty set should yield nothing.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflicts = list(conflict_set)
        assert conflicts == []

    def test_iter_with_conflicts(self) -> None:
        """Test __iter__ yields all conflicts.

        Should be able to iterate over conflicts.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict1 = Conflict("django", "requests", ">=2.0", "1.5")
        conflict2 = Conflict("flask", "requests", ">=2.5", "1.5")
        conflict_set.add_conflict(conflict1)
        conflict_set.add_conflict(conflict2)

        conflicts = list(conflict_set)
        assert len(conflicts) == 2
        assert conflicts[0] is conflict1
        assert conflicts[1] is conflict2

    def test_iter_in_for_loop(self) -> None:
        """Test __iter__ works in for loop.

        Integration test: Should work with standard Python iteration.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=2.0", "1.5"))
        conflict_set.add_conflict(Conflict("flask", "requests", ">=2.5", "1.5"))

        count = 0
        for conflict in conflict_set:
            assert isinstance(conflict, Conflict)
            count += 1

        assert count == 2


class TestConflictEquality:
    """Tests for Conflict equality comparison."""

    def test_equal_conflicts(self) -> None:
        """Test two conflicts with same data are equal.

        Dataclass should implement structural equality.
        """
        conflict1 = Conflict("django", "requests", ">=2.0", "1.5", "4.0")
        conflict2 = Conflict("django", "requests", ">=2.0", "1.5", "4.0")

        assert conflict1 == conflict2

    def test_unequal_source_package(self) -> None:
        """Test conflicts differ when source package differs.

        Different source packages should make conflicts unequal.
        """
        conflict1 = Conflict("django", "requests", ">=2.0", "1.5")
        conflict2 = Conflict("flask", "requests", ">=2.0", "1.5")

        assert conflict1 != conflict2

    def test_unequal_required_spec(self) -> None:
        """Test conflicts differ when required spec differs.

        Different specifiers should make conflicts unequal.
        """
        conflict1 = Conflict("django", "requests", ">=2.0", "1.5")
        conflict2 = Conflict("django", "requests", ">=3.0", "1.5")

        assert conflict1 != conflict2

    def test_normalized_names_affect_equality(self) -> None:
        """Test normalization affects equality comparison.

        Conflicts with differently-cased names should be equal after normalization.
        """
        conflict1 = Conflict("Django", "Requests", ">=2.0", "1.5")
        conflict2 = Conflict("django", "requests", ">=2.0", "1.5")

        # Both should normalize to same values
        assert conflict1 == conflict2


class TestConflictSetIntegration:
    """Integration tests combining multiple ConflictSet features."""

    def test_full_workflow(self) -> None:
        """Test complete workflow from creation to version resolution.

        Integration test: Create, populate, and resolve conflicts.
        """
        # Create conflict set
        conflict_set = ConflictSet(package_name="requests")
        assert not conflict_set.has_conflicts()

        # Add conflicts
        conflict_set.add_conflict(Conflict("django", "requests", ">=2.20.0", "2.0.0"))
        conflict_set.add_conflict(Conflict("flask", "requests", "<3.0.0", "3.5.0"))
        conflict_set.add_conflict(Conflict("fastapi", "requests", ">=2.25.0", "2.0.0"))
        assert conflict_set.has_conflicts()
        assert len(conflict_set) == 3

        # Resolve compatible version
        available = ["2.0.0", "2.20.0", "2.25.0", "2.28.0", "2.31.0", "3.0.0", "3.1.0"]
        compatible = conflict_set.get_max_compatible_version(available)

        # Should satisfy: >=2.20.0 AND <3.0.0 AND >=2.25.0
        # So max is 2.31.0
        assert compatible == "2.31.0"

    def test_iterate_and_display_conflicts(self) -> None:
        """Test iterating and displaying all conflicts.

        Integration test: Iteration with string formatting.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=2.0", "1.5", "4.0"))
        conflict_set.add_conflict(Conflict("flask", "requests", ">=2.5", "1.5", "2.0"))

        displays = [conflict.to_display_string() for conflict in conflict_set]
        assert len(displays) == 2
        assert "django==4.0 requires requests>=2.0" in displays
        assert "flask==2.0 requires requests>=2.5" in displays

    def test_json_serialization_workflow(self) -> None:
        """Test serializing all conflicts to JSON.

        Integration test: Convert all conflicts to JSON format.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=2.0", "1.5"))
        conflict_set.add_conflict(Conflict("flask", "requests", ">=2.5", "1.5"))

        json_list = [conflict.to_json() for conflict in conflict_set]
        assert len(json_list) == 2
        assert all(isinstance(item, dict) for item in json_list)
        assert json_list[0]["source_package"] == "django"
        assert json_list[1]["source_package"] == "flask"


class TestEdgeCases:
    """Additional edge case tests."""

    def test_conflict_with_local_version(self) -> None:
        """Test conflict with local version identifier.

        Edge case: PEP 440 local versions like 1.0+local.
        """
        conflict = Conflict("django", "requests", ">=2.0", "1.0+local")
        assert conflict.conflicting_version == "1.0+local"

    def test_conflict_with_epoch(self) -> None:
        """Test conflict with epoch version.

        Edge case: PEP 440 epochs like 1!2.0.0.
        """
        conflict = Conflict("django", "requests", ">=2.0", "1!2.0.0")
        assert conflict.conflicting_version == "1!2.0.0"

    def test_very_long_package_names(self) -> None:
        """Test conflicts with very long package names.

        Edge case: Extremely long names should be handled.
        """
        long_name = "a" * 200
        conflict = Conflict(long_name, "requests", ">=2.0", "1.5")
        assert len(conflict.source_package) == 200

    def test_unicode_in_version_spec(self) -> None:
        """Test handling of unicode characters in specifiers.

        Edge case: Should handle or reject unicode gracefully.
        """
        # This might be invalid, but shouldn't crash
        conflict = Conflict("django", "requests", ">=2.0™", "1.5")
        assert conflict.required_spec == ">=2.0™"

    def test_max_compatible_with_only_prereleases(self) -> None:
        """Test version resolution when only pre-releases available.

        Edge case: If all versions are pre-release, should return None.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=2.0", "1.5"))

        available = ["2.0.0a1", "2.5.0b1", "3.0.0rc1"]
        result = conflict_set.get_max_compatible_version(available)

        # All are pre-releases, should return None
        assert result is None

    def test_conflict_set_with_hundreds_of_conflicts(self) -> None:
        """Test ConflictSet performance with many conflicts.

        Edge case: Should handle large numbers of conflicts.
        """
        conflict_set = ConflictSet(package_name="requests")

        # Add 100 conflicts
        for i in range(100):
            conflict_set.add_conflict(
                Conflict(f"package{i}", "requests", f">={i}.0", "1.5")
            )

        assert len(conflict_set) == 100
        assert conflict_set.has_conflicts()

    def test_version_with_many_segments(self) -> None:
        """Test versions with many segments like 1.2.3.4.5.6.

        Edge case: Non-standard version formats.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=1.2.3.4", "1.0"))

        available = ["1.2.3.3", "1.2.3.4", "1.2.3.5", "1.2.4.0"]
        result = conflict_set.get_max_compatible_version(available)

        # Should handle multi-segment versions
        assert result == "1.2.4.0"
