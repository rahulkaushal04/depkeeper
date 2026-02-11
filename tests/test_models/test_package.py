from __future__ import annotations

import pytest

from packaging.version import Version

from depkeeper.models.conflict import Conflict
from depkeeper.models.package import Package, _normalize_name


@pytest.fixture
def basic_package() -> Package:
    """Create a basic package with standard versions for reusable testing.

    Returns:
        Package: Package with consistent test data.
    """
    return Package(
        name="requests",
        current_version="2.20.0",
        latest_version="2.31.0",
        recommended_version="2.28.0",
    )


@pytest.fixture
def package_with_conflicts() -> Package:
    """Create a package with pre-configured conflicts for testing.

    Returns:
        Package: Package with two sample conflicts.
    """
    pkg = Package(name="requests", current_version="3.0.0", latest_version="3.0.0")
    conflicts = [
        Conflict("django", "requests", ">=2.0", "1.5", "4.0"),
        Conflict("flask", "requests", ">=2.5", "1.5", "2.0"),
    ]
    pkg.set_conflicts(conflicts, resolved_version="2.28.0")
    return pkg


@pytest.fixture
def package_with_metadata() -> Package:
    """Create a package with full metadata for testing.

    Returns:
        Package: Package with Python requirements in metadata.
    """
    return Package(
        name="requests",
        current_version="2.28.0",
        latest_version="2.31.0",
        recommended_version="2.28.0",
        metadata={
            "current_metadata": {"requires_python": ">=3.7"},
            "latest_metadata": {"requires_python": ">=3.8"},
            "recommended_metadata": {"requires_python": ">=3.7"},
        },
    )


@pytest.fixture
def up_to_date_package() -> Package:
    """Create a package that is up to date (current == recommended == latest)."""
    return Package(
        name="requests",
        current_version="2.28.0",
        latest_version="2.28.0",
        recommended_version="2.28.0",
    )


@pytest.fixture
def outdated_package() -> Package:
    """Create a package that needs an update (current < recommended)."""
    return Package(
        name="requests",
        current_version="2.20.0",
        latest_version="2.31.0",
        recommended_version="2.28.0",
    )


@pytest.fixture
def downgrade_package() -> Package:
    """Create a package that needs a downgrade (current > recommended)."""
    return Package(
        name="requests",
        current_version="3.0.0",
        latest_version="3.0.0",
        recommended_version="2.28.0",
    )


@pytest.fixture
def minimal_package() -> Package:
    """Create a minimal package with only name."""
    return Package(name="requests")


@pytest.fixture
def new_package() -> Package:
    """Create a package for installation (no current version)."""
    return Package(
        name="requests",
        latest_version="2.28.0",
        recommended_version="2.28.0",
    )


@pytest.fixture
def sample_conflict() -> Conflict:
    """Create a sample conflict for testing."""
    return Conflict("django", "requests", ">=2.0", "1.5")


@pytest.fixture
def sample_conflicts() -> list[Conflict]:
    """Create multiple sample conflicts for testing."""
    return [
        Conflict("django", "requests", ">=2.0", "1.5", "4.0"),
        Conflict("flask", "requests", ">=2.5", "1.5", "2.0"),
    ]


@pytest.fixture
def sample_metadata() -> dict:
    """Create sample metadata with Python requirements."""
    return {
        "current_metadata": {"requires_python": ">=3.7"},
        "latest_metadata": {"requires_python": ">=3.8"},
        "recommended_metadata": {"requires_python": ">=3.7"},
    }


@pytest.fixture
def partial_metadata() -> dict:
    """Create metadata with only current version info."""
    return {
        "current_metadata": {"requires_python": ">=3.7"},
    }


@pytest.mark.unit
class TestNormalizeName:
    """Tests for _normalize_name package normalization."""

    @pytest.mark.parametrize(
        "input_name,expected",
        [
            ("Django", "django"),
            ("REQUESTS", "requests"),
            ("NumPy", "numpy"),
        ],
        ids=["mixed-case", "uppercase", "camelcase"],
    )
    def test_lowercase_conversion(self, input_name: str, expected: str) -> None:
        """Test package names are converted to lowercase.

        Per PEP 503, package names should be case-insensitive.
        """
        # Act
        result = _normalize_name(input_name)
        # Assert
        assert result == expected

    @pytest.mark.parametrize(
        "input_name,expected",
        [
            ("python_package", "python-package"),
            ("my_test_pkg", "my-test-pkg"),
        ],
        ids=["single-underscore", "multiple-underscores"],
    )
    def test_underscore_to_dash(self, input_name: str, expected: str) -> None:
        """Test underscores are replaced with dashes.

        PEP 503 normalization converts underscores to hyphens.
        """
        # Act
        result = _normalize_name(input_name)
        # Assert
        assert result == expected

    @pytest.mark.parametrize(
        "input_name,expected",
        [
            ("My_Package", "my-package"),
            ("Test_PKG_Name", "test-pkg-name"),
        ],
        ids=["mixed-case-underscore", "complex-mix"],
    )
    def test_combined_normalization(self, input_name: str, expected: str) -> None:
        """Test combined case and underscore normalization.

        Should handle both transformations simultaneously.
        """
        # Act
        result = _normalize_name(input_name)
        # Assert
        assert result == expected

    @pytest.mark.parametrize(
        "input_name",
        ["requests", "django-rest-framework", "pytest-cov"],
        ids=["simple", "with-dashes", "multiple-parts"],
    )
    def test_already_normalized(self, input_name: str) -> None:
        """Test already normalized names remain unchanged.

        Happy path: Properly formatted names should pass through.
        """
        # Act
        result = _normalize_name(input_name)
        # Assert
        assert result == input_name

    def test_empty_string(self) -> None:
        """Test empty string normalization.

        Edge case: Empty strings should remain empty.
        """
        # Act
        result = _normalize_name("")
        # Assert
        assert result == ""


@pytest.mark.unit
class TestPackageInit:
    """Tests for Package initialization."""

    def test_minimal_initialization(self, minimal_package: Package) -> None:
        """Test Package can be created with only name.

        Happy path: Minimal package with defaults.
        """
        # Assert
        assert minimal_package.name == "requests"
        assert minimal_package.current_version is None
        assert minimal_package.latest_version is None
        assert minimal_package.recommended_version is None
        assert minimal_package.metadata == {}
        assert minimal_package.conflicts == []

    def test_full_initialization(
        self, sample_conflict: Conflict, sample_metadata: dict
    ) -> None:
        """Test Package with all parameters.

        Should accept and store all optional parameters.
        """
        # Arrange
        conflicts = [sample_conflict]
        metadata = {"info": {"author": "Test"}}
        # Act
        pkg = Package(
            name="requests",
            current_version="2.0.0",
            latest_version="2.28.0",
            recommended_version="2.25.0",
            metadata=metadata,
            conflicts=conflicts,
        )
        # Assert
        assert pkg.name == "requests"
        assert pkg.current_version == "2.0.0"
        assert pkg.latest_version == "2.28.0"
        assert pkg.recommended_version == "2.25.0"
        assert pkg.metadata == metadata
        assert pkg.conflicts == conflicts

    @pytest.mark.parametrize(
        "input_name,expected",
        [
            ("Django_App", "django-app"),
            ("MY_PACKAGE", "my-package"),
            ("Test_PKG", "test-pkg"),
        ],
        ids=["mixed-case-underscore", "uppercase-underscore", "short-name"],
    )
    def test_name_normalization_on_init(self, input_name: str, expected: str) -> None:
        """Test package name is normalized in __post_init__.

        Name should be normalized according to PEP 503.
        """
        # Act
        pkg = Package(name=input_name)
        # Assert
        assert pkg.name == expected

    def test_default_factory_creates_new_instances(self) -> None:
        """Test default factories create independent instances.

        Edge case: Multiple packages shouldn't share metadata/conflicts.
        """
        # Act
        pkg1 = Package(name="requests")
        pkg2 = Package(name="django")
        pkg1.metadata["key"] = "value1"
        pkg2.metadata["key"] = "value2"
        # Assert
        assert pkg1.metadata != pkg2.metadata
        assert pkg1.conflicts is not pkg2.conflicts

    def test_parsed_versions_cache_initialized(self, minimal_package: Package) -> None:
        """Test _parsed_versions cache is initialized empty.

        Internal cache should start empty.
        """
        # Assert
        assert minimal_package._parsed_versions == {}


@pytest.mark.unit
class TestParseVersion:
    """Tests for Package._parse_version method."""

    def test_parse_valid_version(self, minimal_package: Package) -> None:
        """Test parsing a valid version string.

        Happy path: Standard version should parse correctly.
        """
        # Act
        result = minimal_package._parse_version("2.28.0")
        # Assert
        assert result is not None
        assert isinstance(result, Version)
        assert str(result) == "2.28.0"

    def test_parse_none_returns_none(self, minimal_package: Package) -> None:
        """Test parsing None returns None.

        Edge case: None input should return None.
        """
        # Act
        result = minimal_package._parse_version(None)
        # Assert
        assert result is None

    @pytest.mark.parametrize(
        "invalid_version",
        ["invalid.version", "not-a-version", "abc"],
        ids=["dots", "dashes", "letters"],
    )
    def test_parse_invalid_version_returns_none(
        self, minimal_package: Package, invalid_version: str
    ) -> None:
        """Test parsing invalid version string returns None.

        Edge case: Invalid versions should not raise, return None.
        """
        # Act
        result = minimal_package._parse_version(invalid_version)
        # Assert
        assert result is None

    def test_version_caching(self, minimal_package: Package) -> None:
        """Test parsed versions are cached.

        Multiple calls with same version should use cache.
        """
        # Act
        result1 = minimal_package._parse_version("2.28.0")
        result2 = minimal_package._parse_version("2.28.0")
        # Assert - Should be same object from cache
        assert result1 is result2
        assert "2.28.0" in minimal_package._parsed_versions

    def test_invalid_version_cached(self, minimal_package: Package) -> None:
        """Test invalid versions are cached as None.

        Should cache None for invalid versions to avoid reparsing.
        """
        # Act
        minimal_package._parse_version("invalid")
        # Assert
        assert "invalid" in minimal_package._parsed_versions
        assert minimal_package._parsed_versions["invalid"] is None

    @pytest.mark.parametrize(
        "version_string",
        [
            "1.0.0a1",  # Pre-release
            "1.0.0b2",  # Beta
            "1.0.0rc3",  # Release candidate
            "1.0.0.post1",  # Post-release
            "1.0.0.dev1",  # Dev release
            "1!2.0.0",  # Epoch
            "1.0.0+local",  # Local version
        ],
        ids=["alpha", "beta", "rc", "post", "dev", "epoch", "local"],
    )
    def test_complex_version_formats(
        self, minimal_package: Package, version_string: str
    ) -> None:
        """Test parsing various PEP 440 version formats.

        Should handle pre-releases, post-releases, epochs, local.
        """
        # Act
        result = minimal_package._parse_version(version_string)
        # Assert
        assert result is not None, f"Failed to parse {version_string}"
        assert isinstance(result, Version)


@pytest.mark.unit
class TestVersionProperties:
    """Tests for Package version accessor properties."""

    def test_current_property(self, basic_package: Package) -> None:
        """Test current property returns parsed current_version.

        Happy path: Should parse and return Version object.
        """
        # Act
        current = basic_package.current
        # Assert
        assert current is not None
        assert isinstance(current, Version)
        assert str(current) == "2.20.0"

    def test_current_property_none(self, minimal_package: Package) -> None:
        """Test current property returns None when not set.

        Edge case: No current version should return None.
        """
        # Act & Assert
        assert minimal_package.current is None

    def test_latest_property(self, basic_package: Package) -> None:
        """Test latest property returns parsed latest_version.

        Happy path: Should parse and return Version object.
        """
        # Act
        latest = basic_package.latest
        # Assert
        assert latest is not None
        assert isinstance(latest, Version)
        assert str(latest) == "2.31.0"

    def test_recommended_property(self, basic_package: Package) -> None:
        """Test recommended property returns parsed recommended_version.

        Happy path: Should parse and return Version object.
        """
        # Act
        recommended = basic_package.recommended
        # Assert
        assert recommended is not None
        assert isinstance(recommended, Version)
        assert str(recommended) == "2.28.0"

    def test_properties_use_cache(self, basic_package: Package) -> None:
        """Test properties use version parsing cache.

        Multiple property accesses should use cached values.
        """
        # Act
        current1 = basic_package.current
        current2 = basic_package.current
        # Assert - Should be same cached object
        assert current1 is current2

    def test_invalid_version_property_returns_none(self) -> None:
        """Test properties return None for invalid versions.

        Edge case: Invalid version strings should return None.
        """
        # Arrange
        pkg = Package(name="requests", current_version="invalid")
        # Act & Assert
        assert pkg.current is None


@pytest.mark.unit
class TestRequiresDowngrade:
    """Tests for Package.requires_downgrade property."""

    def test_requires_downgrade_true(self, downgrade_package: Package) -> None:
        """Test requires_downgrade when recommended < current.

        Happy path: Downgrade is needed.
        """
        # Act & Assert
        assert downgrade_package.requires_downgrade is True

    def test_requires_downgrade_false_same_version(
        self, up_to_date_package: Package
    ) -> None:
        """Test requires_downgrade when versions are equal.

        Same version should not require downgrade.
        """
        # Act & Assert
        assert up_to_date_package.requires_downgrade is False

    def test_requires_downgrade_false_upgrade(self, outdated_package: Package) -> None:
        """Test requires_downgrade when recommended > current.

        Upgrade case should not require downgrade.
        """
        # Act & Assert
        assert outdated_package.requires_downgrade is False

    def test_requires_downgrade_no_current(self, new_package: Package) -> None:
        """Test requires_downgrade when current version is None.

        Edge case: No current version means no downgrade.
        """
        # Act & Assert
        assert new_package.requires_downgrade is False

    def test_requires_downgrade_no_recommended(self) -> None:
        """Test requires_downgrade when recommended version is None.

        Edge case: No recommended version means no downgrade.
        """
        # Arrange
        pkg = Package(name="requests", current_version="2.28.0")
        # Act & Assert
        assert pkg.requires_downgrade is False

    def test_requires_downgrade_invalid_versions(self) -> None:
        """Test requires_downgrade with invalid version strings.

        Edge case: Invalid versions should result in False.
        """
        # Arrange
        pkg = Package(
            name="requests", current_version="invalid", recommended_version="2.28.0"
        )
        # Act & Assert
        assert pkg.requires_downgrade is False


@pytest.mark.unit
class TestHasConflicts:
    """Tests for Package.has_conflicts method."""

    def test_has_conflicts_empty(self, minimal_package: Package) -> None:
        """Test has_conflicts returns False when no conflicts.

        Happy path: Empty conflicts list.
        """
        # Act & Assert
        assert minimal_package.has_conflicts() is False

    def test_has_conflicts_populated(
        self, minimal_package: Package, sample_conflict: Conflict
    ) -> None:
        """Test has_conflicts returns True when conflicts exist.

        Happy path: Non-empty conflicts list.
        """
        # Arrange
        minimal_package.conflicts = [sample_conflict]
        # Act & Assert
        assert minimal_package.has_conflicts() is True

    def test_has_conflicts_multiple(
        self, minimal_package: Package, sample_conflicts: list[Conflict]
    ) -> None:
        """Test has_conflicts with multiple conflicts.

        Multiple conflicts should return True.
        """
        # Arrange
        minimal_package.conflicts = sample_conflicts
        # Act & Assert
        assert minimal_package.has_conflicts() is True


@pytest.mark.unit
class TestSetConflicts:
    """Tests for Package.set_conflicts method."""

    def test_set_conflicts_basic(
        self, minimal_package: Package, sample_conflict: Conflict
    ) -> None:
        """Test setting conflicts updates conflicts list.

        Happy path: Basic conflict assignment.
        """
        # Arrange
        conflicts = [sample_conflict]
        # Act
        minimal_package.set_conflicts(conflicts)
        # Assert
        assert minimal_package.conflicts == conflicts
        assert minimal_package.has_conflicts()

    def test_set_conflicts_with_resolved_version(
        self, minimal_package: Package, sample_conflict: Conflict
    ) -> None:
        """Test setting conflicts with resolved version.

        Should update both conflicts and recommended_version.
        """
        # Arrange
        conflicts = [sample_conflict]
        # Act
        minimal_package.set_conflicts(conflicts, resolved_version="2.28.0")
        # Assert
        assert minimal_package.conflicts == conflicts
        assert minimal_package.recommended_version == "2.28.0"

    def test_set_conflicts_replaces_existing(self, minimal_package: Package) -> None:
        """Test setting conflicts replaces previous conflicts.

        Should completely replace, not append.
        """
        # Arrange
        old_conflicts = [Conflict("django", "requests", ">=2.0", "1.5")]
        new_conflicts = [Conflict("flask", "requests", ">=2.5", "1.5")]
        # Act
        minimal_package.set_conflicts(old_conflicts)
        minimal_package.set_conflicts(new_conflicts)
        # Assert
        assert minimal_package.conflicts == new_conflicts
        assert len(minimal_package.conflicts) == 1

    def test_set_conflicts_empty_list(
        self, minimal_package: Package, sample_conflict: Conflict
    ) -> None:
        """Test setting empty conflicts list.

        Edge case: Should clear conflicts.
        """
        # Arrange
        minimal_package.conflicts = [sample_conflict]
        # Act
        minimal_package.set_conflicts([])
        # Assert
        assert minimal_package.conflicts == []
        assert not minimal_package.has_conflicts()

    def test_set_conflicts_without_resolved_version(
        self, sample_conflict: Conflict
    ) -> None:
        """Test setting conflicts without resolved version.

        Should not modify recommended_version.
        """
        # Arrange
        pkg = Package(name="requests", recommended_version="2.20.0")
        conflicts = [sample_conflict]
        # Act
        pkg.set_conflicts(conflicts)
        # Assert
        assert pkg.recommended_version == "2.20.0"


@pytest.mark.unit
class TestConflictReporting:
    """Tests for conflict summary and detail methods."""

    def test_get_conflict_summary_empty(self, minimal_package: Package) -> None:
        """Test conflict summary with no conflicts.

        Empty conflicts should return empty list.
        """
        # Act
        summary = minimal_package.get_conflict_summary()
        # Assert
        assert summary == []

    def test_get_conflict_summary_single(
        self, minimal_package: Package, sample_conflict: Conflict
    ) -> None:
        """Test conflict summary with one conflict.

        Happy path: Should return list with one short string.
        """
        # Arrange
        minimal_package.conflicts = [sample_conflict]
        # Act
        summary = minimal_package.get_conflict_summary()
        # Assert
        assert len(summary) == 1
        assert "django needs >=2.0" in summary[0]

    def test_get_conflict_summary_multiple(
        self, minimal_package: Package, sample_conflicts: list[Conflict]
    ) -> None:
        """Test conflict summary with multiple conflicts.

        Should return list of all conflict summaries.
        """
        # Arrange
        minimal_package.conflicts = sample_conflicts
        # Act
        summary = minimal_package.get_conflict_summary()
        # Assert
        assert len(summary) == 2
        assert any("django" in s for s in summary)
        assert any("flask" in s for s in summary)

    def test_get_conflict_details_empty(self, minimal_package: Package) -> None:
        """Test conflict details with no conflicts.

        Empty conflicts should return empty list.
        """
        # Act
        details = minimal_package.get_conflict_details()
        # Assert
        assert details == []

    def test_get_conflict_details_single(self, minimal_package: Package) -> None:
        """Test conflict details with one conflict.

        Happy path: Should return detailed description.
        """
        # Arrange
        minimal_package.conflicts = [
            Conflict("django", "requests", ">=2.0", "1.5", "4.0")
        ]
        # Act
        details = minimal_package.get_conflict_details()
        # Assert
        assert len(details) == 1
        assert "django==4.0 requires requests>=2.0" in details[0]

    def test_get_conflict_details_multiple(
        self, minimal_package: Package, sample_conflicts: list[Conflict]
    ) -> None:
        """Test conflict details with multiple conflicts.

        Should return all detailed descriptions.
        """
        # Arrange
        minimal_package.conflicts = sample_conflicts
        # Act
        details = minimal_package.get_conflict_details()
        # Assert
        assert len(details) == 2
        assert any("django==4.0" in d for d in details)
        assert any("flask==2.0" in d for d in details)


@pytest.mark.unit
class TestHasUpdate:
    """Tests for Package.has_update method."""

    def test_has_update_true(self, outdated_package: Package) -> None:
        """Test has_update when recommended > current.

        Happy path: Update is available.
        """
        # Act & Assert
        assert outdated_package.has_update() is True

    def test_has_update_false_same_version(self, up_to_date_package: Package) -> None:
        """Test has_update when versions are equal.

        Same version means no update.
        """
        # Act & Assert
        assert up_to_date_package.has_update() is False

    def test_has_update_false_downgrade(self, downgrade_package: Package) -> None:
        """Test has_update when recommended < current.

        Downgrade case should return False for has_update.
        """
        # Act & Assert
        assert downgrade_package.has_update() is False

    def test_has_update_no_current(self, new_package: Package) -> None:
        """Test has_update when current version is None.

        Edge case: No current version means no update.
        """
        # Act & Assert
        assert new_package.has_update() is False

    def test_has_update_no_recommended(self) -> None:
        """Test has_update when recommended version is None.

        Edge case: No recommended version means no update.
        """
        # Arrange
        pkg = Package(name="requests", current_version="2.28.0")
        # Act & Assert
        assert pkg.has_update() is False

    def test_has_update_invalid_versions(self) -> None:
        """Test has_update with invalid version strings.

        Edge case: Invalid versions should result in False.
        """
        # Arrange
        pkg = Package(
            name="requests", current_version="invalid", recommended_version="2.28.0"
        )
        # Act & Assert
        assert pkg.has_update() is False


@pytest.mark.unit
class TestGetVersionPythonReq:
    """Tests for Package.get_version_python_req method."""

    def test_get_current_python_req(self, partial_metadata: dict) -> None:
        """Test retrieving Python requirement for current version.

        Happy path: Should return requires_python from metadata.
        """
        # Arrange
        pkg = Package(name="requests", metadata=partial_metadata)
        # Act
        result = pkg.get_version_python_req("current")
        # Assert
        assert result == ">=3.7"

    def test_get_latest_python_req(self) -> None:
        """Test retrieving Python requirement for latest version.

        Should access latest_metadata.
        """
        # Arrange
        pkg = Package(
            name="requests", metadata={"latest_metadata": {"requires_python": ">=3.8"}}
        )
        # Act
        result = pkg.get_version_python_req("latest")
        # Assert
        assert result == ">=3.8"

    def test_get_recommended_python_req(self) -> None:
        """Test retrieving Python requirement for recommended version.

        Should access recommended_metadata.
        """
        # Arrange
        pkg = Package(
            name="requests",
            metadata={"recommended_metadata": {"requires_python": ">=3.7"}},
        )
        # Act
        result = pkg.get_version_python_req("recommended")
        # Assert
        assert result == ">=3.7"

    @pytest.mark.parametrize(
        "version_key",
        ["current", "latest", "recommended"],
        ids=["current", "latest", "recommended"],
    )
    def test_get_python_req_no_metadata(
        self, minimal_package: Package, version_key: str
    ) -> None:
        """Test returns None when metadata doesn't exist.

        Edge case: Missing metadata key should return None.
        """
        # Act
        result = minimal_package.get_version_python_req(version_key)
        # Assert
        assert result is None

    def test_get_python_req_no_requires_python(self, partial_metadata: dict) -> None:
        """Test returns None when requires_python not in metadata.

        Edge case: Metadata exists but no requires_python field.
        """
        # Arrange
        pkg = Package(
            name="requests", metadata={"current_metadata": {"author": "Test"}}
        )
        # Act
        result = pkg.get_version_python_req("current")
        # Assert
        assert result is None

    def test_get_python_req_invalid_metadata_type(self) -> None:
        """Test returns None when metadata is not a dict.

        Edge case: Malformed metadata should return None.
        """
        # Arrange
        pkg = Package(name="requests", metadata={"current_metadata": "invalid"})
        # Act
        result = pkg.get_version_python_req("current")
        # Assert
        assert result is None

    def test_get_python_req_invalid_value_type(self) -> None:
        """Test returns None when requires_python is not a string.

        Edge case: Non-string value should return None.
        """
        # Arrange
        pkg = Package(
            name="requests",
            metadata={"current_metadata": {"requires_python": 3.7}},  # Invalid type
        )
        # Act
        result = pkg.get_version_python_req("current")
        # Assert
        assert result is None

    def test_get_python_req_all_versions(self, sample_metadata: dict) -> None:
        """Test retrieving requirements for all version types.

        Integration test: Multiple version requirements.
        """
        # Arrange
        pkg = Package(
            name="requests",
            metadata={
                "current_metadata": {"requires_python": ">=3.6"},
                "latest_metadata": {"requires_python": ">=3.8"},
                "recommended_metadata": {"requires_python": ">=3.7"},
            },
        )
        # Act & Assert
        assert pkg.get_version_python_req("current") == ">=3.6"
        assert pkg.get_version_python_req("latest") == ">=3.8"
        assert pkg.get_version_python_req("recommended") == ">=3.7"


@pytest.mark.unit
class TestGetStatusSummary:
    """Tests for Package.get_status_summary method."""

    def test_status_install_new_package(self, new_package: Package) -> None:
        """Test status for package not yet installed.

        No current version should give 'install' status.
        """
        status, installed, latest, recommended = new_package.get_status_summary()
        assert status == "install"
        assert installed == "none"
        assert latest == "2.28.0"
        assert recommended == "2.28.0"

    def test_status_latest_up_to_date(self, up_to_date_package: Package) -> None:
        """Test status when package is up to date.

        Current == recommended should give 'latest' status.
        """
        status, installed, latest, recommended = up_to_date_package.get_status_summary()
        assert status == "latest"
        assert installed == "2.28.0"
        assert latest == "2.28.0"
        assert recommended == "2.28.0"

    def test_status_outdated(self, outdated_package: Package) -> None:
        """Test status when package needs update.

        recommended > current should give 'outdated' status.
        """
        status, installed, latest, recommended = outdated_package.get_status_summary()
        assert status == "outdated"
        assert installed == "2.20.0"
        assert latest == "2.31.0"
        assert recommended == "2.28.0"

    def test_status_downgrade(self, downgrade_package: Package) -> None:
        """Test status when downgrade is needed.

        recommended < current should give 'downgrade' status.
        """
        status, installed, latest, recommended = downgrade_package.get_status_summary()
        assert status == "downgrade"
        assert installed == "3.0.0"
        assert latest == "3.0.0"
        assert recommended == "2.28.0"

    def test_status_no_update_no_recommended(self) -> None:
        """Test status when no recommended version available.

        No recommended version should give 'no-update' status.
        """
        pkg = Package(
            name="requests", current_version="2.28.0", latest_version="2.28.0"
        )
        status, installed, latest, recommended = pkg.get_status_summary()
        assert status == "no-update"
        assert installed == "2.28.0"
        assert latest == "2.28.0"
        assert recommended is None

    def test_status_error_no_latest(self) -> None:
        """Test status when latest version unavailable.

        Edge case: No latest version should show 'error'.
        """
        pkg = Package(name="requests", current_version="2.28.0")
        status, installed, latest, recommended = pkg.get_status_summary()
        assert latest == "error"


@pytest.mark.unit
class TestToJSON:
    """Tests for Package.to_json serialization."""

    def test_to_json_minimal(self, minimal_package: Package) -> None:
        """Test JSON serialization with minimal data.

        Only name and no-update status.
        """
        result = minimal_package.to_json()
        assert result["name"] == "requests"
        assert result["status"] == "no-update"
        assert result["error"] == "Package information unavailable"
        assert "versions" not in result

    def test_to_json_install_status(self, new_package: Package) -> None:
        """Test JSON for new package installation.

        Should show install status with versions.
        """
        result = new_package.to_json()
        assert result["name"] == "requests"
        assert result["status"] == "install"
        assert result["versions"]["latest"] == "2.28.0"
        assert result["versions"]["recommended"] == "2.28.0"
        assert "current" not in result["versions"]
        assert "update_type" not in result

    def test_to_json_latest_status(self, up_to_date_package: Package) -> None:
        """Test JSON for up-to-date package.

        Should show latest status.
        """
        result = up_to_date_package.to_json()
        assert result["status"] == "latest"
        assert result["versions"]["current"] == "2.28.0"
        assert "update_type" not in result

    def test_to_json_outdated_status(self, outdated_package: Package) -> None:
        """Test JSON for outdated package.

        Should show outdated status with update_type.
        """
        result = outdated_package.to_json()
        assert result["status"] == "outdated"
        assert "update_type" in result
        assert result["update_type"] in ["major", "minor", "patch"]

    def test_to_json_downgrade_status(self, downgrade_package: Package) -> None:
        """Test JSON for package requiring downgrade.

        Should show downgrade status with update_type.
        """
        result = downgrade_package.to_json()
        assert result["status"] == "downgrade"
        assert "update_type" in result

    def test_to_json_with_python_requirements(
        self, package_with_metadata: Package
    ) -> None:
        """Test JSON includes Python requirements when present.

        Should serialize requires_python metadata.
        """
        result = package_with_metadata.to_json()
        assert "python_requirements" in result
        assert result["python_requirements"]["current"] == ">=3.7"
        assert result["python_requirements"]["latest"] == ">=3.8"
        assert result["python_requirements"]["recommended"] == ">=3.7"

    def test_to_json_with_conflicts(
        self, minimal_package: Package, sample_conflicts: list[Conflict]
    ) -> None:
        """Test JSON includes conflicts when present.

        Should serialize conflict list.
        """
        # Arrange
        minimal_package.conflicts = sample_conflicts
        minimal_package.recommended_version = "2.28.0"
        # Act
        result = minimal_package.to_json()
        # Assert
        assert "conflicts" in result
        assert len(result["conflicts"]) == 2
        assert result["conflicts"][0]["source_package"] == "django"
        assert result["conflicts"][1]["source_package"] == "flask"

    def test_to_json_no_python_requirements(self, up_to_date_package: Package) -> None:
        """Test JSON omits python_requirements when not present.

        Edge case: Empty requirements should not create key.
        """
        result = up_to_date_package.to_json()
        assert "python_requirements" not in result

    def test_to_json_partial_versions(self) -> None:
        """Test JSON with only some versions present.

        Edge case: Missing versions shouldn't appear in versions dict.
        """
        pkg = Package(
            name="requests", current_version="2.28.0", recommended_version="2.28.0"
        )
        result = pkg.to_json()
        assert "versions" in result
        assert "current" in result["versions"]
        assert "recommended" in result["versions"]
        assert "latest" not in result["versions"]


@pytest.mark.unit
class TestRenderPythonCompatibility:
    """Tests for Package.render_python_compatibility method."""

    def test_render_no_requirements(self, minimal_package: Package) -> None:
        """Test rendering when no Python requirements exist.

        Should return dim placeholder.
        """
        result = minimal_package.render_python_compatibility()
        assert result == "[dim]-[/dim]"

    def test_render_current_only(self, partial_metadata: dict) -> None:
        """Test rendering with only current requirement.

        Should show current line only.
        """
        pkg = Package(
            name="requests",
            current_version="2.28.0",
            metadata=partial_metadata,
        )
        result = pkg.render_python_compatibility()
        assert "Current: >=3.7" in result
        assert "Latest:" not in result

    def test_render_current_and_latest(self) -> None:
        """Test rendering with current and latest requirements.

        Should show both lines.
        """
        pkg = Package(
            name="requests",
            current_version="2.28.0",
            latest_version="2.31.0",
            metadata={
                "current_metadata": {"requires_python": ">=3.7"},
                "latest_metadata": {"requires_python": ">=3.8"},
            },
        )
        result = pkg.render_python_compatibility()
        assert "Current: >=3.7" in result
        assert "Latest: >=3.8" in result

    def test_render_with_update_includes_recommended(
        self, sample_metadata: dict
    ) -> None:
        """Test rendering includes recommended when update available.

        Should show recommended line when has_update() is True.
        """
        pkg = Package(
            name="requests",
            current_version="2.20.0",
            latest_version="2.31.0",
            recommended_version="2.28.0",
            metadata={
                "current_metadata": {"requires_python": ">=3.6"},
                "latest_metadata": {"requires_python": ">=3.8"},
                "recommended_metadata": {"requires_python": ">=3.7"},
            },
        )
        result = pkg.render_python_compatibility()
        assert "Current: >=3.6" in result
        assert "Latest: >=3.8" in result
        assert "Recommended:>=3.7" in result

    def test_render_no_update_excludes_recommended(self) -> None:
        """Test rendering excludes recommended when no update.

        Should not show recommended when current == recommended.
        """
        pkg = Package(
            name="requests",
            current_version="2.28.0",
            latest_version="2.31.0",
            recommended_version="2.28.0",
            metadata={
                "current_metadata": {"requires_python": ">=3.7"},
                "latest_metadata": {"requires_python": ">=3.8"},
                "recommended_metadata": {"requires_python": ">=3.7"},
            },
        )
        result = pkg.render_python_compatibility()
        assert "Recommended:" not in result

    def test_render_multiline_format(self) -> None:
        """Test rendering produces newline-separated output.

        Multiple requirements should be separated by newlines.
        """
        pkg = Package(
            name="requests",
            current_version="2.28.0",
            latest_version="2.31.0",
            metadata={
                "current_metadata": {"requires_python": ">=3.7"},
                "latest_metadata": {"requires_python": ">=3.8"},
            },
        )
        result = pkg.render_python_compatibility()
        lines = result.split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("Current:")
        assert lines[1].startswith("Latest:")


@pytest.mark.unit
class TestGetDisplayData:
    """Tests for Package.get_display_data method."""

    def test_display_data_no_update(self, up_to_date_package: Package) -> None:
        """Test display data when package is up to date.

        Should show no update available.
        """
        data = up_to_date_package.get_display_data()
        assert data["update_available"] is False
        assert data["requires_downgrade"] is False
        assert data["update_target"] == "2.28.0"
        assert data["update_type"] is None
        assert data["has_conflicts"] is False
        assert data["conflict_summary"] == []

    def test_display_data_update_available(self, outdated_package: Package) -> None:
        """Test display data when update is available.

        Should show update details.
        """
        data = outdated_package.get_display_data()
        assert data["update_available"] is True
        assert data["requires_downgrade"] is False
        assert data["update_target"] == "2.28.0"
        assert data["update_type"] in ["major", "minor", "patch"]

    def test_display_data_downgrade_required(self, downgrade_package: Package) -> None:
        """Test display data when downgrade is needed.

        Should show downgrade requirement.
        """
        data = downgrade_package.get_display_data()
        assert data["update_available"] is False
        assert data["requires_downgrade"] is True
        assert data["update_target"] == "2.28.0"
        assert data["update_type"] is not None

    def test_display_data_with_conflicts(
        self, minimal_package: Package, sample_conflicts: list[Conflict]
    ) -> None:
        """Test display data includes conflict information.

        Should show conflict details.
        """
        # Arrange
        minimal_package.conflicts = sample_conflicts
        minimal_package.recommended_version = "2.28.0"
        # Act
        data = minimal_package.get_display_data()
        # Assert
        assert data["has_conflicts"] is True
        assert len(data["conflict_summary"]) == 2
        assert any("django" in s for s in data["conflict_summary"])

    def test_display_data_structure(self, minimal_package: Package) -> None:
        """Test display data has all expected keys.

        Should contain all required fields.
        """
        data = minimal_package.get_display_data()
        expected_keys = {
            "update_available",
            "requires_downgrade",
            "update_target",
            "update_type",
            "has_conflicts",
            "conflict_summary",
        }
        assert set(data.keys()) == expected_keys


@pytest.mark.unit
class TestStringRepresentations:
    """Tests for Package.__str__ and __repr__ methods."""

    def test_str_minimal(self, minimal_package: Package) -> None:
        """Test __str__ with only package name.

        Minimal package should show just name.
        """
        result = str(minimal_package)
        assert result == "requests"

    def test_str_with_latest_only(self) -> None:
        """Test __str__ with only latest version.

        Should show name with latest version.
        """
        pkg = Package(name="requests", latest_version="2.28.0")
        result = str(pkg)
        assert result == "requests (latest: 2.28.0)"

    def test_str_up_to_date(self, up_to_date_package: Package) -> None:
        """Test __str__ for up-to-date package.

        Should show up-to-date status.
        """
        result = str(up_to_date_package)
        assert "requests" in result
        assert "2.28.0" in result
        assert "up-to-date" in result

    def test_str_outdated(self, outdated_package: Package) -> None:
        """Test __str__ for outdated package.

        Should show outdated status with recommended.
        """
        result = str(outdated_package)
        assert "requests" in result
        assert "2.20.0" in result
        assert "2.31.0" in result
        assert "outdated" in result
        assert "recommended: 2.28.0" in result

    def test_repr_minimal(self, minimal_package: Package) -> None:
        """Test __repr__ with minimal data.

        Should show Package constructor format.
        """
        result = repr(minimal_package)
        assert result.startswith("Package(")
        assert "name='requests'" in result
        assert "current_version=None" in result
        assert "outdated=False" in result

    def test_repr_full(self, outdated_package: Package) -> None:
        """Test __repr__ with all version data.

        Should show all version fields.
        """
        result = repr(outdated_package)
        assert "name='requests'" in result
        assert "current_version='2.20.0'" in result
        assert "latest_version='2.31.0'" in result
        assert "recommended_version='2.28.0'" in result
        assert "outdated=True" in result


@pytest.mark.integration
class TestIntegrationScenarios:
    """Integration tests for complex real-world scenarios."""

    def test_complete_outdated_package_workflow(self) -> None:
        """Test complete workflow for outdated package.

        Integration test: From initialization to reporting.
        """
        # Create outdated package
        pkg = Package(
            name="Django_Package",
            current_version="3.0.0",
            latest_version="4.2.0",
            recommended_version="4.0.0",
            metadata={
                "current_metadata": {"requires_python": ">=3.8"},
                "latest_metadata": {"requires_python": ">=3.10"},
                "recommended_metadata": {"requires_python": ">=3.8"},
            },
        )
        # Check name normalized
        assert pkg.name == "django-package"
        # Check status
        assert pkg.has_update()
        assert not pkg.requires_downgrade
        assert not pkg.has_conflicts()
        # Check display data
        data = pkg.get_display_data()
        assert data["update_available"]
        assert data["update_target"] == "4.0.0"
        # Check JSON output
        json_data = pkg.to_json()
        assert json_data["status"] == "outdated"
        assert "update_type" in json_data
        assert "python_requirements" in json_data
        # Check string representation
        str_repr = str(pkg)
        assert "outdated" in str_repr
        assert "recommended: 4.0.0" in str_repr

    def test_complete_conflict_resolution_workflow(self) -> None:
        """Test complete workflow with conflicts.

        Integration test: Conflict detection and resolution.
        """
        # Create package with conflicts
        pkg = Package(name="requests", current_version="3.0.0", latest_version="3.0.0")
        # Add conflicts with resolved version
        conflicts = [
            Conflict("django", "requests", ">=2.20.0,<3.0.0", "3.0.0", "4.0"),
            Conflict("flask", "requests", ">=2.25.0,<3.0.0", "3.0.0", "2.0"),
        ]
        pkg.set_conflicts(conflicts, resolved_version="2.28.0")
        # Check conflict state
        assert pkg.has_conflicts()
        assert pkg.requires_downgrade
        assert pkg.recommended_version == "2.28.0"
        # Check conflict reporting
        summary = pkg.get_conflict_summary()
        assert len(summary) == 2
        details = pkg.get_conflict_details()
        assert any("django==4.0" in d for d in details)
        # Check display data
        data = pkg.get_display_data()
        assert data["requires_downgrade"]
        assert data["has_conflicts"]
        assert len(data["conflict_summary"]) == 2
        # Check JSON includes conflicts
        json_data = pkg.to_json()
        assert json_data["status"] == "downgrade"
        assert "conflicts" in json_data
        assert len(json_data["conflicts"]) == 2

    def test_new_package_installation_workflow(self) -> None:
        """Test workflow for installing new package.

        Integration test: Package not yet installed.
        """
        pkg = Package(
            name="new_package",
            latest_version="1.0.0",
            recommended_version="1.0.0",
            metadata={
                "latest_metadata": {"requires_python": ">=3.8"},
                "recommended_metadata": {"requires_python": ">=3.8"},
            },
        )
        # Check status
        assert not pkg.has_update()
        assert not pkg.requires_downgrade
        assert pkg.current is None
        # Check status summary
        status, installed, latest, recommended = pkg.get_status_summary()
        assert status == "install"
        assert installed == "none"
        # Check JSON
        json_data = pkg.to_json()
        assert json_data["status"] == "install"
        assert "current" not in json_data.get("versions", {})


@pytest.mark.unit
class TestEdgeCases:
    """Additional edge case tests."""

    def test_version_with_local_identifier(self) -> None:
        """Test package with local version identifier.

        Edge case: PEP 440 local versions like 1.0+local.
        """
        pkg = Package(
            name="requests", current_version="2.28.0+local", latest_version="2.28.0"
        )
        # Should parse successfully
        assert pkg.current is not None
        assert isinstance(pkg.current, Version)

    def test_version_with_epoch(self) -> None:
        """Test package with epoch in version.

        Edge case: PEP 440 epochs like 1!2.0.0.
        """
        pkg = Package(
            name="requests", current_version="1!2.0.0", recommended_version="1!2.5.0"
        )
        # Should handle epochs correctly
        assert pkg.has_update()

    def test_prerelease_versions(self) -> None:
        """Test package with pre-release versions.

        Edge case: Alpha, beta, rc versions.
        """
        pkg = Package(
            name="requests",
            current_version="2.28.0",
            latest_version="3.0.0a1",
            recommended_version="2.28.0",
        )
        # Should parse pre-release versions
        assert pkg.latest is not None
        assert pkg.latest.is_prerelease

    def test_very_long_package_name(self) -> None:
        """Test package with very long name.

        Edge case: Extremely long names should be handled.
        """
        long_name = "very-" * 50 + "long-package-name"
        pkg = Package(name=long_name)
        assert len(pkg.name) > 100

    def test_metadata_with_nested_structures(self) -> None:
        """Test package with deeply nested metadata.

        Edge case: Complex metadata structures.
        """
        pkg = Package(
            name="requests",
            metadata={
                "current_metadata": {
                    "requires_python": ">=3.7",
                    "info": {"nested": {"deep": "value"}},
                },
            },
        )
        # Should handle nested structures without errors
        req = pkg.get_version_python_req("current")
        assert req == ">=3.7"

    def test_empty_metadata_dict(self, minimal_package: Package) -> None:
        """Test package with empty metadata.

        Edge case: Empty metadata should not cause issues.
        """
        pkg = Package(name="requests", metadata={})
        assert pkg.get_version_python_req("current") is None
        assert pkg.render_python_compatibility() == "[dim]-[/dim]"

    def test_many_conflicts(self, minimal_package: Package) -> None:
        """Test package with many conflicts.

        Edge case: Large number of conflicts.
        """
        # Arrange
        conflicts = [
            Conflict(f"package{i}", "requests", f">={i}.0", "1.0") for i in range(50)
        ]
        # Act
        minimal_package.set_conflicts(conflicts)
        # Assert
        assert len(minimal_package.conflicts) == 50
        assert len(minimal_package.get_conflict_summary()) == 50

    def test_version_comparison_with_invalid(self) -> None:
        """Test version comparisons when some versions invalid.

        Edge case: Invalid versions should not break comparisons.
        """
        # Arrange
        pkg = Package(
            name="requests", current_version="invalid", recommended_version="2.28.0"
        )
        # Act & Assert - Should return False for comparisons with invalid versions
        assert not pkg.has_update()
        assert not pkg.requires_downgrade

    def test_simultaneous_update_and_conflict(self, sample_conflict: Conflict) -> None:
        """Test package with both update and conflicts.

        Edge case: Complex scenario with multiple issues.
        """
        # Arrange
        pkg = Package(
            name="requests",
            current_version="2.20.0",
            latest_version="3.0.0",
            recommended_version="2.28.0",
        )
        pkg.conflicts = [sample_conflict]
        # Act
        data = pkg.get_display_data()
        # Assert
        assert pkg.has_update()
        assert pkg.has_conflicts()
        assert data["update_available"]
        assert data["has_conflicts"]

    def test_json_with_none_values(self, minimal_package: Package) -> None:
        """Test JSON serialization handles None values correctly.

        Edge case: None values should be omitted or handled properly.
        """
        # Act
        json_data = minimal_package.to_json()
        # Assert - Should not include version keys when None
        assert "versions" not in json_data or len(json_data.get("versions", {})) == 0

    def test_unicode_in_package_name(self) -> None:
        """Test package with unicode characters in name.

        Edge case: International characters in package names.
        """
        # Arrange & Act
        pkg = Package(name="pàckage-naмe-日本")
        str_repr = str(pkg)
        # Assert - Should handle unicode without errors
        assert len(pkg.name) > 0
        assert len(str_repr) > 0
