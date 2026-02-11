from __future__ import annotations

from typing import List

import pytest

from depkeeper.models.conflict import Conflict, ConflictSet, _normalize_name


@pytest.fixture
def sample_conflict() -> Conflict:
    """Create a sample Conflict instance for testing.

    Returns:
        Conflict: A configured conflict with standard test data.

    Note:
        Uses common test values: django requires requests>=2.0.0.
    """
    return Conflict(
        source_package="django",
        target_package="requests",
        required_spec=">=2.0.0",
        conflicting_version="1.5.0",
    )


@pytest.fixture
def sample_conflict_with_version() -> Conflict:
    """Create a sample Conflict with source version for testing.

    Returns:
        Conflict: A conflict instance including source_version.
    """
    return Conflict(
        source_package="django",
        target_package="requests",
        required_spec=">=2.0.0",
        conflicting_version="1.5.0",
        source_version="4.0.0",
    )


@pytest.fixture
def sample_conflict_set() -> ConflictSet:
    """Create an empty ConflictSet for testing.

    Returns:
        ConflictSet: An empty conflict set for the 'requests' package.
    """
    return ConflictSet(package_name="requests")


@pytest.fixture
def populated_conflict_set() -> ConflictSet:
    """Create a ConflictSet with pre-populated conflicts.

    Returns:
        ConflictSet: A conflict set with multiple conflicts for testing.
    """
    conflict_set = ConflictSet(package_name="requests")
    conflict_set.add_conflict(Conflict("django", "requests", ">=2.0.0", "1.5.0"))
    conflict_set.add_conflict(Conflict("flask", "requests", "<3.0.0", "3.5.0"))
    return conflict_set


@pytest.mark.unit
class TestNormalizeName:
    """Tests for _normalize_name package normalization."""

    @pytest.mark.parametrize(
        "input_name,expected",
        [
            # Lowercase conversion
            ("Django", "django"),
            ("REQUESTS", "requests"),
            ("NumPy", "numpy"),
            # Underscore to dash
            ("python_package", "python-package"),
            ("my_test_pkg", "my-test-pkg"),
            # Combined normalization
            ("My_Package", "my-package"),
            ("Test_PKG_Name", "test-pkg-name"),
            # Already normalized
            ("requests", "requests"),
            ("django-rest-framework", "django-rest-framework"),
            # Edge cases
            ("", ""),
            ("my__package___name", "my--package---name"),
            ("pkg.name", "pkg.name"),
            ("pkg-v2", "pkg-v2"),
        ],
        ids=[
            "uppercase",
            "all-caps",
            "mixed-case",
            "underscores",
            "multiple-underscores",
            "combined-mixed",
            "combined-caps",
            "already-normalized",
            "hyphenated",
            "empty-string",
            "multiple-consecutive-underscores",
            "dots-preserved",
            "existing-hyphens",
        ],
    )
    def test_normalize_name_variations(self, input_name: str, expected: str) -> None:
        """Test package name normalization with various inputs.

        Parametrized test covering lowercase conversion, underscore replacement,
        combined transformations, and edge cases. Per PEP 503, package names
        should be case-insensitive and use hyphens.

        Args:
            input_name: Package name to normalize.
            expected: Expected normalized result.
        """
        # Act
        result = _normalize_name(input_name)

        # Assert
        assert result == expected

    @pytest.mark.unit
    def test_normalization_idempotent(self) -> None:
        """Test normalization is idempotent.

        Applying normalization multiple times should produce same result.
        """
        # Arrange
        name = "My_Package_NAME"

        # Act
        first_pass = _normalize_name(name)
        second_pass = _normalize_name(first_pass)

        # Assert
        assert first_pass == second_pass
        assert first_pass == "my-package-name"


@pytest.mark.unit
class TestConflictInit:
    """Tests for Conflict initialization and post-init processing."""

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
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


@pytest.mark.unit
class TestConflictDisplayMethods:
    """Tests for Conflict string representation methods."""

    @pytest.mark.unit
    def test_to_display_string_without_source_version(
        self, sample_conflict: Conflict
    ) -> None:
        """Test display string when source version is not known.

        Should show only source package name, not version.

        Args:
            sample_conflict: Fixture providing a basic Conflict instance.
        """
        # Act
        result = sample_conflict.to_display_string()

        # Assert
        assert result == "django requires requests>=2.0.0"

    @pytest.mark.unit
    def test_to_display_string_with_source_version(
        self, sample_conflict_with_version: Conflict
    ) -> None:
        """Test display string when source version is known.

        Should show source package with version pinned.

        Args:
            sample_conflict_with_version: Fixture providing a Conflict with source_version.
        """
        # Act
        result = sample_conflict_with_version.to_display_string()

        # Assert
        assert result == "django==4.0.0 requires requests>=2.0.0"

    @pytest.mark.unit
    def test_to_short_string(self, sample_conflict: Conflict) -> None:
        """Test compact conflict summary.

        Should provide abbreviated format with just source and spec.

        Args:
            sample_conflict: Fixture providing a basic Conflict instance.
        """
        # Act
        result = sample_conflict.to_short_string()

        # Assert
        assert result == "django needs >=2.0.0"

    @pytest.mark.unit
    def test_str_method(self, sample_conflict_with_version: Conflict) -> None:
        """Test __str__ delegates to to_display_string.

        String conversion should use the full display format.

        Args:
            sample_conflict_with_version: Fixture providing a Conflict with source_version.
        """
        # Act
        result = str(sample_conflict_with_version)

        # Assert
        assert result == sample_conflict_with_version.to_display_string()
        assert "django==4.0.0" in result

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
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


@pytest.mark.unit
class TestConflictJSONSerialization:
    """Tests for Conflict.to_json method."""

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
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


@pytest.mark.unit
class TestConflictSetInit:
    """Tests for ConflictSet initialization."""

    @pytest.mark.unit
    def test_basic_initialization(self) -> None:
        """Test ConflictSet can be created with package name.

        Happy path: Basic ConflictSet with empty conflicts list.
        """
        conflict_set = ConflictSet(package_name="requests")
        assert conflict_set.package_name == "requests"
        assert conflict_set.conflicts == []

    @pytest.mark.unit
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

    @pytest.mark.unit
    def test_package_name_normalization(self) -> None:
        """Test package name is normalized in __post_init__.

        Package name should follow PEP 503 normalization.
        """
        conflict_set = ConflictSet(package_name="My_Package")
        assert conflict_set.package_name == "my-package"

    @pytest.mark.unit
    def test_mutable_dataclass(self) -> None:
        """Test ConflictSet is mutable (not frozen).

        Should allow modification of conflicts list.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.package_name = "flask"  # Should not raise
        assert conflict_set.package_name == "flask"

    @pytest.mark.unit
    def test_empty_package_name(self) -> None:
        """Test ConflictSet with empty package name.

        Edge case: Empty string should be accepted.
        """
        conflict_set = ConflictSet(package_name="")
        assert conflict_set.package_name == ""


@pytest.mark.unit
class TestConflictSetAddConflict:
    """Tests for ConflictSet.add_conflict method."""

    @pytest.mark.unit
    def test_add_single_conflict(
        self, sample_conflict_set: ConflictSet, sample_conflict: Conflict
    ) -> None:
        """Test adding a single conflict to the set.

        Happy path: Conflict should be appended to conflicts list.

        Args:
            sample_conflict_set: Fixture providing an empty ConflictSet.
            sample_conflict: Fixture providing a basic Conflict instance.
        """
        # Act
        sample_conflict_set.add_conflict(sample_conflict)

        # Assert
        assert len(sample_conflict_set.conflicts) == 1
        assert sample_conflict_set.conflicts[0] == sample_conflict

    @pytest.mark.unit
    def test_add_multiple_conflicts(self, sample_conflict_set: ConflictSet) -> None:
        """Test adding multiple conflicts sequentially.

        All conflicts should be preserved in order.

        Args:
            sample_conflict_set: Fixture providing an empty ConflictSet.
        """
        # Arrange
        conflict1 = Conflict("django", "requests", ">=2.0", "1.5")
        conflict2 = Conflict("flask", "requests", ">=2.5", "1.5")
        conflict3 = Conflict("fastapi", "requests", ">=3.0", "1.5")

        # Act
        sample_conflict_set.add_conflict(conflict1)
        sample_conflict_set.add_conflict(conflict2)
        sample_conflict_set.add_conflict(conflict3)

        # Assert
        assert len(sample_conflict_set.conflicts) == 3
        assert sample_conflict_set.conflicts == [conflict1, conflict2, conflict3]

    @pytest.mark.unit
    def test_add_duplicate_conflicts(
        self, sample_conflict_set: ConflictSet, sample_conflict: Conflict
    ) -> None:
        """Test adding duplicate conflicts.

        Edge case: Duplicates should be allowed (no deduplication).

        Args:
            sample_conflict_set: Fixture providing an empty ConflictSet.
            sample_conflict: Fixture providing a basic Conflict instance.
        """
        # Act
        sample_conflict_set.add_conflict(sample_conflict)
        sample_conflict_set.add_conflict(sample_conflict)

        # Assert
        assert len(sample_conflict_set.conflicts) == 2
        assert sample_conflict_set.conflicts[0] is sample_conflict_set.conflicts[1]


@pytest.mark.unit
class TestConflictSetHasConflicts:
    """Tests for ConflictSet.has_conflicts method."""

    @pytest.mark.unit
    def test_has_conflicts_when_empty(self, sample_conflict_set: ConflictSet) -> None:
        """Test has_conflicts returns False for empty set.

        Empty conflicts list should return False.

        Args:
            sample_conflict_set: Fixture providing an empty ConflictSet.
        """
        # Act & Assert
        assert sample_conflict_set.has_conflicts() is False

    @pytest.mark.unit
    def test_has_conflicts_when_populated(
        self, sample_conflict_set: ConflictSet, sample_conflict: Conflict
    ) -> None:
        """Test has_conflicts returns True when conflicts exist.

        Non-empty conflicts list should return True.

        Args:
            sample_conflict_set: Fixture providing an empty ConflictSet.
            sample_conflict: Fixture providing a basic Conflict instance.
        """
        # Arrange
        sample_conflict_set.add_conflict(sample_conflict)

        # Act & Assert
        assert sample_conflict_set.has_conflicts() is True

    @pytest.mark.unit
    def test_has_conflicts_after_initialization(self) -> None:
        """Test has_conflicts with conflicts provided at init.

        Should return True when initialized with conflicts.
        """
        # Arrange
        conflicts = [Conflict("django", "requests", ">=2.0", "1.5")]
        conflict_set = ConflictSet(package_name="requests", conflicts=conflicts)

        # Act & Assert
        assert conflict_set.has_conflicts() is True


@pytest.mark.unit
class TestConflictSetGetMaxCompatibleVersion:
    """Tests for ConflictSet.get_max_compatible_version method."""

    @pytest.mark.unit
    def test_no_conflicts_returns_none(self) -> None:
        """Test returns None when no conflicts exist.

        Empty conflict set should return None.
        """
        conflict_set = ConflictSet(package_name="requests")
        result = conflict_set.get_max_compatible_version(["1.0.0", "2.0.0"])
        assert result is None

    @pytest.mark.unit
    def test_single_conflict_compatible_version(self) -> None:
        """Test finds compatible version with single conflict.

        Happy path: Should return highest compatible version.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=2.0.0", "1.5.0"))

        available = ["1.5.0", "2.0.0", "2.5.0", "3.0.0"]
        result = conflict_set.get_max_compatible_version(available)

        assert result == "3.0.0"

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
    def test_empty_available_versions(self) -> None:
        """Test with empty available versions list.

        Edge case: No available versions should return None.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=2.0.0", "1.5.0"))

        result = conflict_set.get_max_compatible_version([])
        assert result is None

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
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


@pytest.mark.unit
class TestConflictSetMagicMethods:
    """Tests for ConflictSet magic methods."""

    @pytest.mark.unit
    def test_len_empty(self) -> None:
        """Test __len__ returns 0 for empty conflict set.

        len() should return number of conflicts.
        """
        conflict_set = ConflictSet(package_name="requests")
        assert len(conflict_set) == 0

    @pytest.mark.unit
    def test_len_with_conflicts(self) -> None:
        """Test __len__ returns count of conflicts.

        len() should accurately reflect number of conflicts.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=2.0", "1.5"))
        conflict_set.add_conflict(Conflict("flask", "requests", ">=2.5", "1.5"))

        assert len(conflict_set) == 2

    @pytest.mark.unit
    def test_iter_empty(self) -> None:
        """Test __iter__ on empty conflict set.

        Iteration over empty set should yield nothing.
        """
        conflict_set = ConflictSet(package_name="requests")
        conflicts = list(conflict_set)
        assert conflicts == []

    @pytest.mark.unit
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

    @pytest.mark.unit
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


@pytest.mark.unit
class TestConflictEquality:
    """Tests for Conflict equality comparison."""

    @pytest.mark.unit
    def test_equal_conflicts(self) -> None:
        """Test two conflicts with same data are equal.

        Dataclass should implement structural equality.
        """
        conflict1 = Conflict("django", "requests", ">=2.0", "1.5", "4.0")
        conflict2 = Conflict("django", "requests", ">=2.0", "1.5", "4.0")

        assert conflict1 == conflict2

    @pytest.mark.unit
    def test_unequal_source_package(self) -> None:
        """Test conflicts differ when source package differs.

        Different source packages should make conflicts unequal.
        """
        conflict1 = Conflict("django", "requests", ">=2.0", "1.5")
        conflict2 = Conflict("flask", "requests", ">=2.0", "1.5")

        assert conflict1 != conflict2

    @pytest.mark.unit
    def test_unequal_required_spec(self) -> None:
        """Test conflicts differ when required spec differs.

        Different specifiers should make conflicts unequal.
        """
        conflict1 = Conflict("django", "requests", ">=2.0", "1.5")
        conflict2 = Conflict("django", "requests", ">=3.0", "1.5")

        assert conflict1 != conflict2

    @pytest.mark.unit
    def test_normalized_names_affect_equality(self) -> None:
        """Test normalization affects equality comparison.

        Conflicts with differently-cased names should be equal after normalization.
        """
        conflict1 = Conflict("Django", "Requests", ">=2.0", "1.5")
        conflict2 = Conflict("django", "requests", ">=2.0", "1.5")

        # Both should normalize to same values
        assert conflict1 == conflict2


@pytest.mark.integration
class TestConflictSetIntegration:
    """Integration tests combining multiple ConflictSet features."""

    @pytest.mark.integration
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

    @pytest.mark.integration
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

    @pytest.mark.integration
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


@pytest.mark.unit
class TestEdgeCases:
    """Additional edge case tests."""

    @pytest.mark.unit
    def test_conflict_with_local_version(self) -> None:
        """Test conflict with local version identifier.

        Edge case: PEP 440 local versions like 1.0+local.
        """
        conflict = Conflict("django", "requests", ">=2.0", "1.0+local")
        assert conflict.conflicting_version == "1.0+local"

    @pytest.mark.unit
    def test_conflict_with_epoch(self) -> None:
        """Test conflict with epoch version.

        Edge case: PEP 440 epochs like 1!2.0.0.
        """
        conflict = Conflict("django", "requests", ">=2.0", "1!2.0.0")
        assert conflict.conflicting_version == "1!2.0.0"

    @pytest.mark.unit
    def test_very_long_package_names(self) -> None:
        """Test conflicts with very long package names.

        Edge case: Extremely long names should be handled.
        """
        long_name = "a" * 200
        conflict = Conflict(long_name, "requests", ">=2.0", "1.5")
        assert len(conflict.source_package) == 200

    @pytest.mark.unit
    def test_unicode_in_version_spec(self) -> None:
        """Test handling of unicode characters in specifiers.

        Edge case: Should handle or reject unicode gracefully.
        """
        # This might be invalid, but shouldn't crash
        conflict = Conflict("django", "requests", ">=2.0™", "1.5")
        assert conflict.required_spec == ">=2.0™"

    @pytest.mark.unit
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

    @pytest.mark.unit
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

    @pytest.mark.unit
    def test_version_with_many_segments(self) -> None:
        """Test versions with many segments like 1.2.3.4.5.6.

        Edge case: Non-standard version formats.
        """
        # Arrange
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=1.2.3.4", "1.0"))

        available = ["1.2.3.3", "1.2.3.4", "1.2.3.5", "1.2.4.0"]

        # Act
        result = conflict_set.get_max_compatible_version(available)

        # Assert - Should handle multi-segment versions
        assert result == "1.2.4.0"


@pytest.mark.unit
class TestConflictSetParametrized:
    """Parametrized tests for ConflictSet with various version specifiers."""

    @pytest.mark.parametrize(
        "spec,available,expected",
        [
            # Greater than or equal
            (">=2.0.0", ["1.0.0", "2.0.0", "3.0.0"], "3.0.0"),
            (">=2.5.0", ["2.0.0", "2.5.0", "2.6.0"], "2.6.0"),
            # Less than
            ("<3.0.0", ["2.0.0", "2.9.0", "3.0.0"], "2.9.0"),
            ("<2.0", ["1.5.0", "1.9.0", "2.0.0"], "1.9.0"),
            # Exact match
            ("==2.5.0", ["2.0.0", "2.5.0", "3.0.0"], "2.5.0"),
            ("==1.0", ["0.9.0", "1.0", "1.1.0"], "1.0"),
            # Not equal (should get highest that isn't excluded)
            ("!=2.5.0", ["2.4.0", "2.5.0", "2.6.0"], "2.6.0"),
            # Compatible release
            ("~=2.5", ["2.0.0", "2.5.0", "2.9.0", "3.0.0"], "2.9.0"),
            ("~=1.4.2", ["1.4.0", "1.4.2", "1.4.9", "1.5.0"], "1.4.9"),
            # Compound specifiers
            (">=2.0,<3.0", ["1.5.0", "2.5.0", "3.0.0"], "2.5.0"),
            (">=1.0,<=2.0", ["0.5.0", "1.5.0", "2.0.0", "2.5.0"], "2.0.0"),
            (">=1.0,<2.0,!=1.5.0", ["1.0.0", "1.5.0", "1.9.0", "2.0.0"], "1.9.0"),
        ],
        ids=[
            "gte-simple",
            "gte-specific",
            "lt-major",
            "lt-minor",
            "exact-patch",
            "exact-minor",
            "not-equal",
            "compatible-minor",
            "compatible-patch",
            "compound-range",
            "compound-inclusive",
            "compound-exclusion",
        ],
    )
    def test_version_specifier_matching(
        self, spec: str, available: List[str], expected: str
    ) -> None:
        """Test version resolution with various specifiers.

        Parametrized test covering all common version specifier patterns.

        Args:
            spec: Version specifier string to test.
            available: List of available version strings.
            expected: Expected maximum compatible version.
        """
        # Arrange
        conflict_set = ConflictSet(package_name="test-pkg")
        conflict_set.add_conflict(Conflict("django", "test-pkg", spec, "0.0.0"))

        # Act
        result = conflict_set.get_max_compatible_version(available)

        # Assert
        assert result == expected

    @pytest.mark.parametrize(
        "spec,available",
        [
            # No compatible versions
            (">=5.0.0", ["1.0.0", "2.0.0", "3.0.0"]),
            ("<1.0.0", ["1.0.0", "2.0.0", "3.0.0"]),
            ("==4.0.0", ["1.0.0", "2.0.0", "3.0.0"]),
            # Only pre-releases available
            (">=1.0.0", ["1.0.0a1", "1.0.0b1", "1.0.0rc1"]),
            # Contradictory specifiers
            (">=3.0.0,<2.0.0", ["1.0.0", "2.0.0", "3.0.0"]),
        ],
        ids=[
            "gte-too-high",
            "lt-too-low",
            "exact-missing",
            "only-prereleases",
            "contradictory",
        ],
    )
    def test_no_compatible_version_cases(self, spec: str, available: List[str]) -> None:
        """Test cases where no compatible version should be found.

        Parametrized test for various scenarios that should return None.

        Args:
            spec: Version specifier string to test.
            available: List of available version strings.
        """
        # Arrange
        conflict_set = ConflictSet(package_name="test-pkg")
        conflict_set.add_conflict(Conflict("django", "test-pkg", spec, "0.0.0"))

        # Act
        result = conflict_set.get_max_compatible_version(available)

        # Assert
        assert result is None


@pytest.mark.unit
class TestConflictDataConsistency:
    """Tests for data consistency and immutability expectations."""

    @pytest.mark.unit
    def test_conflict_hash_consistency(self) -> None:
        """Test that equal conflicts have equal hashes.

        Frozen dataclasses should be hashable and consistent.
        """
        # Arrange
        conflict1 = Conflict("django", "requests", ">=2.0", "1.5", "4.0")
        conflict2 = Conflict("django", "requests", ">=2.0", "1.5", "4.0")

        # Act & Assert
        assert hash(conflict1) == hash(conflict2)
        # Should be usable in sets/dicts
        conflict_set = {conflict1, conflict2}
        assert len(conflict_set) == 1  # Should deduplicate

    @pytest.mark.unit
    def test_conflict_set_mutations_dont_affect_conflicts(self) -> None:
        """Test that ConflictSet mutations don't affect stored Conflicts.

        Edge case: Frozen Conflicts should remain immutable after being added.
        """
        # Arrange
        conflict = Conflict("django", "requests", ">=2.0", "1.5")
        conflict_set = ConflictSet(package_name="requests")

        # Act
        conflict_set.add_conflict(conflict)
        # Try to mutate the set
        conflict_set.package_name = "different"

        # Assert - Original conflict should be unchanged
        assert conflict.target_package == "requests"
        assert conflict_set.conflicts[0] is conflict

    @pytest.mark.unit
    def test_conflict_set_clear_behavior(self) -> None:
        """Test clearing all conflicts from a ConflictSet.

        Should be able to remove all conflicts and reset state.
        """
        # Arrange
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=2.0", "1.5"))
        conflict_set.add_conflict(Conflict("flask", "requests", ">=2.5", "1.5"))

        # Act
        conflict_set.conflicts.clear()

        # Assert
        assert len(conflict_set) == 0
        assert not conflict_set.has_conflicts()


@pytest.mark.unit
class TestConflictSetRobustness:
    """Tests for robustness and error handling."""

    @pytest.mark.unit
    def test_get_max_compatible_with_mixed_valid_invalid_versions(self) -> None:
        """Test version resolution with mix of valid and invalid versions.

        Should skip invalid versions and process valid ones normally.
        """
        # Arrange
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=2.0", "1.5"))

        # Mix of valid and invalid versions
        # Note: "v3.0.0" is parsed as valid by packaging (v prefix is allowed)
        available = [
            "invalid",
            "2.0.0",
            "not-a-version",
            "2.5.0",
            "version-string",  # Invalid
            "3.0.0",
            "bad-version",
        ]

        # Act
        result = conflict_set.get_max_compatible_version(available)

        # Assert - Should return highest valid version
        assert result == "3.0.0"

    @pytest.mark.unit
    def test_conflict_set_with_empty_string_versions(self) -> None:
        """Test handling of empty string versions in available list.

        Edge case: Empty strings should be skipped gracefully.
        """
        # Arrange
        conflict_set = ConflictSet(package_name="requests")
        conflict_set.add_conflict(Conflict("django", "requests", ">=2.0", "1.5"))

        available = ["", "2.0.0", "", "2.5.0", ""]

        # Act
        result = conflict_set.get_max_compatible_version(available)

        # Assert
        assert result == "2.5.0"

    @pytest.mark.unit
    def test_conflict_set_iteration_after_modifications(self) -> None:
        """Test that iteration works correctly after adding/removing conflicts.

        Should reflect current state of conflicts list.
        """
        # Arrange
        conflict_set = ConflictSet(package_name="requests")
        conflict1 = Conflict("django", "requests", ">=2.0", "1.5")
        conflict2 = Conflict("flask", "requests", ">=2.5", "1.5")

        # Act - Add, iterate, add more, iterate again
        conflict_set.add_conflict(conflict1)
        first_iteration = list(conflict_set)
        assert len(first_iteration) == 1

        conflict_set.add_conflict(conflict2)
        second_iteration = list(conflict_set)
        assert len(second_iteration) == 2

        # Assert
        assert first_iteration[0] is conflict1
        assert second_iteration[0] is conflict1
        assert second_iteration[1] is conflict2

    @pytest.mark.parametrize(
        "package_name,expected",
        [
            ("CamelCase", "camelcase"),
            ("under_score", "under-score"),
            ("Mixed_CASE_under", "mixed-case-under"),
            ("dots.in.name", "dots.in.name"),
            ("123-numeric", "123-numeric"),
        ],
        ids=["camelcase", "underscore", "mixed", "dots", "numeric"],
    )
    def test_conflict_set_name_normalization_parametrized(
        self, package_name: str, expected: str
    ) -> None:
        """Test ConflictSet normalizes various package name formats.

        Parametrized test for PEP 503 normalization in ConflictSet.__post_init__.

        Args:
            package_name: Input package name to test.
            expected: Expected normalized package name.
        """
        # Act
        conflict_set = ConflictSet(package_name=package_name)

        # Assert
        assert conflict_set.package_name == expected


@pytest.mark.unit
class TestConflictJSONRobustness:
    """Tests for JSON serialization robustness and edge cases."""

    @pytest.mark.unit
    def test_to_json_with_none_values(self) -> None:
        """Test JSON serialization explicitly includes None values.

        Should have source_version key even when None.
        """
        # Arrange
        conflict = Conflict("django", "requests", ">=2.0", "1.5")

        # Act
        result = conflict.to_json()

        # Assert
        assert "source_version" in result
        assert result["source_version"] is None

    @pytest.mark.unit
    def test_to_json_preserves_all_data(
        self, sample_conflict_with_version: Conflict
    ) -> None:
        """Test JSON serialization preserves all conflict data.

        No data should be lost during serialization.

        Args:
            sample_conflict_with_version: Fixture providing a complete Conflict.
        """
        # Act
        result = sample_conflict_with_version.to_json()

        # Assert
        assert result["source_package"] == sample_conflict_with_version.source_package
        assert result["target_package"] == sample_conflict_with_version.target_package
        assert result["required_spec"] == sample_conflict_with_version.required_spec
        assert (
            result["conflicting_version"]
            == sample_conflict_with_version.conflicting_version
        )
        assert result["source_version"] == sample_conflict_with_version.source_version

    @pytest.mark.parametrize(
        "source,target,spec,conflicting,source_ver",
        [
            ("pkg-a", "pkg-b", ">=1.0", "0.5", None),
            ("Pkg_A", "Pkg_B", ">=1.0", "0.5", "2.0"),
            ("", "", "", "", None),
            ("a" * 100, "b" * 100, ">=1.0" * 10, "0.0.1", "1!2.3"),
        ],
        ids=["basic", "needs-normalization", "empty", "extreme"],
    )
    def test_json_serialization_various_inputs(
        self,
        source: str,
        target: str,
        spec: str,
        conflicting: str,
        source_ver: str | None,
    ) -> None:
        """Test JSON serialization with various input combinations.

        Parametrized test ensuring JSON serialization works for edge cases.

        Args:
            source: Source package name.
            target: Target package name.
            spec: Version specifier.
            conflicting: Conflicting version string.
            source_ver: Optional source version.
        """
        # Arrange
        conflict = Conflict(source, target, spec, conflicting, source_ver)

        # Act
        result = conflict.to_json()

        # Assert - Should always be a dict with correct keys
        assert isinstance(result, dict)
        assert len(result) == 5
        assert all(
            key in result
            for key in [
                "source_package",
                "target_package",
                "required_spec",
                "conflicting_version",
                "source_version",
            ]
        )
