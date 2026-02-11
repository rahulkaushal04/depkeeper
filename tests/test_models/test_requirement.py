from __future__ import annotations

import pytest

from depkeeper.models.requirement import Requirement


@pytest.fixture
def simple_requirement() -> Requirement:
    """Create a simple Requirement with only a package name.

    Returns:
        Requirement: A minimal requirement instance for testing.
    """
    return Requirement(name="requests")


@pytest.fixture
def requirement_with_version() -> Requirement:
    """Create a Requirement with version specifiers.

    Returns:
        Requirement: A requirement with version constraints.
    """
    return Requirement(name="requests", specs=[(">=", "2.0.0")])


@pytest.fixture
def complex_requirement() -> Requirement:
    """Create a Requirement with multiple features.

    Returns:
        Requirement: A requirement with specs, extras, and markers.
    """
    return Requirement(
        name="requests",
        specs=[(">=", "2.0.0"), ("<", "3.0.0")],
        extras=["security", "socks"],
        markers='python_version >= "3.7"',
    )


@pytest.fixture
def requirement_with_hashes() -> Requirement:
    """Create a Requirement with hash verification.

    Returns:
        Requirement: A requirement with multiple hash values.
    """
    return Requirement(
        name="requests",
        specs=[(">=", "2.0.0")],
        hashes=["sha256:abc123", "sha256:def456"],
    )


@pytest.fixture
def requirement_with_comment() -> Requirement:
    """Create a Requirement with an inline comment.

    Returns:
        Requirement: A requirement with comment metadata.
    """
    return Requirement(
        name="requests",
        specs=[(">=", "2.0.0")],
        comment="Production dependency",
    )


@pytest.fixture
def editable_requirement() -> Requirement:
    """Create an editable Requirement.

    Returns:
        Requirement: An editable installation requirement.
    """
    return Requirement(
        name="mypackage",
        url="/path/to/local/package",
        editable=True,
    )


@pytest.fixture
def url_requirement() -> Requirement:
    """Create a URL-based Requirement.

    Returns:
        Requirement: A requirement with direct URL.
    """
    return Requirement(
        name="requests",
        url="https://github.com/psf/requests/archive/v2.28.0.tar.gz",
    )


@pytest.fixture
def full_featured_requirement() -> Requirement:
    """Create a Requirement with all features enabled.

    Returns:
        Requirement: A requirement using all available features.
    """
    return Requirement(
        name="requests",
        specs=[(">=", "2.0.0"), ("<", "3.0.0")],
        extras=["security", "socks"],
        markers='python_version >= "3.7"',
        url="https://github.com/psf/requests/archive/v2.28.0.tar.gz",
        editable=True,
        hashes=["sha256:abc123", "sha256:def456"],
        comment="Production dependency",
        line_number=42,
        raw_line="-e https://github.com/psf/requests/archive/v2.28.0.tar.gz",
    )


@pytest.fixture
def requirement_factory():
    """Factory fixture for creating Requirement instances with custom parameters.

    Returns:
        Callable: Function to create Requirements with specified attributes.
    """

    def _create(**kwargs):
        defaults = {"name": "requests"}
        defaults.update(kwargs)
        return Requirement(**defaults)

    return _create


@pytest.fixture
def spec_factory():
    """Factory for creating common version specifiers.

    Returns:
        dict: Common spec patterns for reuse.
    """
    return {
        "pinned": [("==", "2.28.0")],
        "range": [(">=", "2.0.0"), ("<", "3.0.0")],
        "exclude": [(">=", "2.0.0"), ("<", "3.0.0"), ("!=", "2.5.0")],
        "min_only": [(">=", "2.0.0")],
        "wildcard": [("==", "2.*")],
        "complex": [(">=", "3.2"), ("<", "5.0"), ("!=", "4.0")],
    }


@pytest.fixture
def url_factory():
    """Factory for creating common URL patterns.

    Returns:
        dict: Common URL patterns for testing.
    """
    return {
        "github_archive": "https://github.com/psf/requests/archive/v2.28.0.tar.gz",
        "github_main": "https://github.com/psf/requests/archive/main.zip",
        "git_https": "git+https://github.com/user/repo.git@main#egg=mypackage",
        "git_ssh": "git+ssh://git@github.com/user/repo.git",
        "git_branch": "git+https://github.com/user/my-lib.git@develop",
        "git_subdirectory": "git+https://github.com/user/repo.git@feature-branch#subdirectory=packages/mypackage",
        "local": ".",
    }


@pytest.fixture
def marker_factory():
    """Factory for creating common environment markers.

    Returns:
        dict: Common marker expressions for testing.
    """
    return {
        "python_version": 'python_version >= "3.7"',
        "python_version_38": 'python_version >= "3.8"',
        "python_version_39": 'python_version >= "3.9"',
        "linux": 'sys_platform == "linux"',
        "windows": 'sys_platform == "win32"',
        "not_windows": 'sys_platform != "win32"',
        "complex": 'python_version >= "3.7" and sys_platform == "linux" and platform_machine == "x86_64"',
        "or_condition": 'sys_platform == "win32" or sys_platform == "darwin"',
    }


@pytest.fixture
def extras_factory():
    """Factory for common extra specifications.

    Returns:
        dict: Common extra combinations for testing.
    """
    return {
        "single": ["security"],
        "multiple": ["security", "socks"],
        "dev": ["dev", "test"],
        "ordered": ["z-extra", "a-extra", "m-extra"],
        "django": ["bcrypt"],
        "numpy": ["dev"],
        "flask": ["async"],
    }


@pytest.fixture
def hash_factory():
    """Factory for hash values.

    Returns:
        dict: Common hash patterns for testing.
    """
    return {
        "single_sha256": ["sha256:abc123def456"],
        "multiple_sha256": ["sha256:abc123", "sha256:def456"],
        "multiple_sha256_three": ["sha256:abc123", "sha256:def456", "sha256:ghi789"],
        "mixed_algorithms": ["sha256:abc123", "sha256:def456"],
        "different_algorithms": ["sha256:abc123", "sha512:def456ghi789", "md5:xyz890"],
        "security": ["sha256:hash1", "sha256:hash2"],
    }


@pytest.fixture
def version_factory():
    """Factory for version strings.

    Returns:
        dict: Common version patterns for testing.
    """
    return {
        "stable": "2.28.0",
        "updated": "2.31.0",
        "new_major": "3.0.0",
        "prerelease": "3.0.0a1",
        "dev": "3.0.0.dev1",
        "local": "2.28.0+local",
        "epoch": "1!2.0.0",
        "wildcard": "2.*",
    }


# ============================================================================
# Reusable Data Fixtures
# ============================================================================


@pytest.fixture
def package_names():
    """Common package names for testing.

    Returns:
        dict: Package names categorized by use case.
    """
    return {
        "simple": "requests",
        "django": "django",
        "flask": "flask",
        "numpy": "numpy",
        "pytest": "pytest",
        "pillow": "pillow",
        "pywin32": "pywin32",
        "mypackage": "mypackage",
        "myproject": "myproject",
        "my-lib": "my-lib",
        "empty": "",
        "special_chars": "my-package.name_v2",
        "long": "package-" * 50 + "name",
    }


@pytest.fixture
def all_operators():
    """All valid PEP 440 operators.

    Returns:
        list: All comparison operators.
    """
    return ["==", "!=", ">=", "<=", ">", "<", "~=", "==="]


@pytest.fixture
def comment_factory():
    """Factory for common comment patterns.

    Returns:
        dict: Common comment strings for testing.
    """
    return {
        "simple": "Production dependency",
        "security": "Pinned for security",
        "web_framework": "Web framework",
        "testing": "Testing framework",
        "local_dev": "Local development",
        "develop_branch": "Latest develop branch",
        "breaking_changes": "Avoid Django 4.0 due to breaking changes",
        "cve": "Exclude vulnerable versions (CVE-2023-XXXXX)",
        "windows": "Windows-specific",
        "scientific": "Scientific computing",
        "special_chars": "Critical! ⚠️ Don't update (see issue #123)",
        "hash_symbols": "See issue #123 and PR #456",
        "long": "This is a very long comment " * 20,
    }


@pytest.mark.unit
class TestRequirementInit:
    """Tests for Requirement initialization."""

    @pytest.mark.unit
    def test_minimal_initialization(self, simple_requirement: Requirement) -> None:
        """Test Requirement with only package name.

        Happy path: Minimal requirement with just name.

        Args:
            simple_requirement: Fixture providing a minimal Requirement.
        """
        # Act & Assert
        assert simple_requirement.name == "requests"
        assert simple_requirement.specs == []
        assert simple_requirement.extras == []
        assert simple_requirement.markers is None
        assert simple_requirement.url is None
        assert simple_requirement.editable is False
        assert simple_requirement.hashes == []
        assert simple_requirement.comment is None
        assert simple_requirement.line_number == 0
        assert simple_requirement.raw_line is None

    @pytest.mark.unit
    def test_full_initialization(self, full_featured_requirement: Requirement) -> None:
        """Test Requirement with all parameters.

        Should accept and store all optional parameters.

        Args:
            full_featured_requirement: Fixture with all features.
        """
        # Act & Assert
        assert full_featured_requirement.name == "requests"
        assert full_featured_requirement.specs == [(">=", "2.0.0"), ("<", "3.0.0")]
        assert full_featured_requirement.extras == ["security", "socks"]
        assert full_featured_requirement.markers == 'python_version >= "3.7"'
        assert (
            full_featured_requirement.url
            == "https://github.com/psf/requests/archive/v2.28.0.tar.gz"
        )
        assert full_featured_requirement.editable is True
        assert full_featured_requirement.hashes == ["sha256:abc123", "sha256:def456"]
        assert full_featured_requirement.comment == "Production dependency"
        assert full_featured_requirement.line_number == 42

    @pytest.mark.unit
    def test_default_factories_create_new_instances(self, requirement_factory) -> None:
        """Test default factories create independent instances.

        Edge case: Multiple requirements shouldn't share lists.
        """
        req1 = requirement_factory(name="requests")
        req2 = requirement_factory(name="django")

        req1.specs.append((">=", "2.0.0"))
        req2.specs.append((">=", "4.0.0"))

        assert req1.specs != req2.specs
        assert req1.extras is not req2.extras
        assert req1.hashes is not req2.hashes

    @pytest.mark.unit
    def test_initialization_with_empty_lists(self, requirement_factory) -> None:
        """Test Requirement with explicitly empty lists.

        Edge case: Empty lists should be accepted.
        """
        req = requirement_factory(name="requests", specs=[], extras=[], hashes=[])

        assert req.specs == []
        assert req.extras == []
        assert req.hashes == []


@pytest.mark.unit
class TestToStringBasic:
    """Tests for Requirement.to_string method - basic cases."""

    @pytest.mark.unit
    def test_simple_package_name_only(self, simple_requirement) -> None:
        """Test rendering requirement with only package name.

        Happy path: Simplest possible requirement.
        """
        result = simple_requirement.to_string()
        assert result == "requests"

    @pytest.mark.unit
    def test_with_single_spec(self, requirement_with_version) -> None:
        """Test rendering requirement with single version specifier.

        Happy path: Common format with version constraint.
        """
        result = requirement_with_version.to_string()
        assert result == "requests>=2.0.0"

    @pytest.mark.unit
    def test_with_multiple_specs(self, requirement_factory, spec_factory) -> None:
        """Test rendering requirement with multiple version specifiers.

        Should concatenate specifiers with commas.
        """
        req = requirement_factory(
            name="requests", specs=[(">=", "2.0.0"), ("<", "3.0.0"), ("!=", "2.5.0")]
        )
        result = req.to_string()
        assert result == "requests>=2.0.0,<3.0.0,!=2.5.0"

    @pytest.mark.unit
    def test_with_single_extra(self, requirement_factory, extras_factory) -> None:
        """Test rendering requirement with single extra.

        Extras should be enclosed in square brackets.
        """
        req = requirement_factory(name="requests", extras=extras_factory["single"])
        result = req.to_string()
        assert result == "requests[security]"

    @pytest.mark.unit
    def test_with_multiple_extras(self, requirement_factory, extras_factory) -> None:
        """Test rendering requirement with multiple extras.

        Multiple extras should be comma-separated.
        """
        req = requirement_factory(name="requests", extras=extras_factory["multiple"])
        result = req.to_string()
        assert result == "requests[security,socks]"

    @pytest.mark.unit
    def test_with_extras_and_specs(
        self, requirement_factory, spec_factory, extras_factory
    ) -> None:
        """Test rendering requirement with both extras and specs.

        Format should be: package[extras]specs
        """
        req = requirement_factory(
            name="requests",
            specs=spec_factory["min_only"],
            extras=extras_factory["single"],
        )
        result = req.to_string()
        assert result == "requests[security]>=2.0.0"

    @pytest.mark.unit
    def test_with_markers(
        self, requirement_factory, marker_factory, spec_factory
    ) -> None:
        """Test rendering requirement with environment markers.

        Markers should be preceded by semicolon and space.
        """
        req = requirement_factory(
            name="requests",
            specs=spec_factory["min_only"],
            markers=marker_factory["python_version"],
        )
        result = req.to_string()
        assert result == 'requests>=2.0.0 ; python_version >= "3.7"'

    @pytest.mark.unit
    def test_with_url(self, requirement_factory, url_factory) -> None:
        """Test rendering URL-based requirement.

        URL should replace package name in output.
        """
        req = requirement_factory(name="requests", url=url_factory["github_main"])
        result = req.to_string()
        assert result == "https://github.com/psf/requests/archive/main.zip"

    @pytest.mark.unit
    def test_editable_package(self, requirement_factory) -> None:
        """Test rendering editable installation.

        Should prefix with -e flag.
        """
        req = requirement_factory(name="mypackage", editable=True)
        result = req.to_string()
        assert result == "-e mypackage"

    @pytest.mark.unit
    def test_editable_url(self, requirement_factory, url_factory) -> None:
        """Test rendering editable URL installation.

        Should prefix URL with -e flag.
        """
        req = requirement_factory(
            name="mypackage", url=url_factory["git_https"], editable=True
        )
        result = req.to_string()
        assert result == "-e git+https://github.com/user/repo.git@main#egg=mypackage"


@pytest.mark.unit
class TestToStringWithHashes:
    """Tests for Requirement.to_string with hash handling."""

    @pytest.mark.unit
    def test_single_hash(self, requirement_factory, spec_factory, hash_factory) -> None:
        """Test rendering requirement with single hash.

        Hash should be appended with --hash= prefix.
        """
        req = requirement_factory(
            name="requests",
            specs=spec_factory["pinned"],
            hashes=hash_factory["single_sha256"],
        )
        result = req.to_string(include_hashes=True)
        assert result == "requests==2.28.0 --hash=sha256:abc123def456"

    @pytest.mark.unit
    def test_multiple_hashes(
        self, requirement_factory, spec_factory, hash_factory
    ) -> None:
        """Test rendering requirement with multiple hashes.

        Multiple hashes should each have --hash= prefix.
        """
        req = requirement_factory(
            name="requests",
            specs=spec_factory["pinned"],
            hashes=hash_factory["multiple_sha256_three"],
        )
        result = req.to_string(include_hashes=True)

        assert "requests==2.28.0" in result
        assert "--hash=sha256:abc123" in result
        assert "--hash=sha256:def456" in result
        assert "--hash=sha256:ghi789" in result

    @pytest.mark.unit
    def test_hashes_excluded_when_flag_false(
        self, requirement_factory, spec_factory, hash_factory
    ) -> None:
        """Test hashes are omitted when include_hashes=False.

        Should not include hash entries when flag is False.
        """
        req = requirement_factory(
            name="requests",
            specs=spec_factory["pinned"],
            hashes=hash_factory["single_sha256"],
        )
        result = req.to_string(include_hashes=False)
        assert result == "requests==2.28.0"
        assert "--hash=" not in result

    @pytest.mark.unit
    def test_no_hashes_with_flag_true(self, requirement_factory, spec_factory) -> None:
        """Test rendering with include_hashes=True but no hashes.

        Edge case: Flag is True but no hashes to include.
        """
        req = requirement_factory(name="requests", specs=spec_factory["pinned"])
        result = req.to_string(include_hashes=True)
        assert result == "requests==2.28.0"
        assert "--hash=" not in result


@pytest.mark.unit
class TestToStringWithComments:
    """Tests for Requirement.to_string with comment handling."""

    @pytest.mark.unit
    def test_simple_comment(self, requirement_with_comment) -> None:
        """Test rendering requirement with comment.

        Comment should be appended with # prefix and space.
        """
        result = requirement_with_comment.to_string(include_comment=True)
        assert result == "requests>=2.0.0  # Production dependency"

    @pytest.mark.unit
    def test_comment_excluded_when_flag_false(self, requirement_with_comment) -> None:
        """Test comment is omitted when include_comment=False.

        Should not include comment when flag is False.
        """
        result = requirement_with_comment.to_string(include_comment=False)
        assert result == "requests>=2.0.0"
        assert "#" not in result

    @pytest.mark.unit
    def test_no_comment_with_flag_true(self, requirement_with_version) -> None:
        """Test rendering with include_comment=True but no comment.

        Edge case: Flag is True but no comment to include.
        """
        result = requirement_with_version.to_string(include_comment=True)
        assert result == "requests>=2.0.0"
        assert "#" not in result

    @pytest.mark.unit
    def test_comment_with_hashes(
        self, requirement_factory, spec_factory, hash_factory, comment_factory
    ) -> None:
        """Test rendering with both hashes and comment.

        Comment should come after hashes.
        """
        req = requirement_factory(
            name="requests",
            specs=spec_factory["pinned"],
            hashes=["sha256:abc123"],
            comment=comment_factory["security"],
        )
        result = req.to_string(include_hashes=True, include_comment=True)
        assert result.endswith("# Pinned for security")
        assert "--hash=sha256:abc123  #" in result

    @pytest.mark.unit
    def test_comment_without_hashes(
        self, requirement_factory, spec_factory, comment_factory
    ) -> None:
        """Test rendering with comment but hashes excluded.

        Comment should still appear when hashes are excluded.
        """
        req = requirement_factory(
            name="requests",
            specs=spec_factory["pinned"],
            hashes=["sha256:abc123"],
            comment="Pinned",
        )
        result = req.to_string(include_hashes=False, include_comment=True)
        assert result == "requests==2.28.0  # Pinned"


@pytest.mark.unit
class TestToStringComplex:
    """Tests for Requirement.to_string with complex combinations."""

    @pytest.mark.unit
    def test_all_features_combined(
        self,
        requirement_factory,
        spec_factory,
        extras_factory,
        marker_factory,
        comment_factory,
    ) -> None:
        """Test rendering with all features enabled.

        Integration test: extras, specs, markers, hashes, comment.
        """
        req = requirement_factory(
            name="requests",
            specs=spec_factory["range"],
            extras=extras_factory["single"],
            markers=marker_factory["python_version"],
            hashes=["sha256:abc123"],
            comment="Production",
        )
        result = req.to_string(include_hashes=True, include_comment=True)

        assert "requests[security]>=2.0.0,<3.0.0" in result
        assert '; python_version >= "3.7"' in result
        assert "--hash=sha256:abc123" in result
        assert "# Production" in result

    @pytest.mark.unit
    def test_editable_with_all_features(
        self, requirement_factory, url_factory, marker_factory, comment_factory
    ) -> None:
        """Test editable requirement with multiple features.

        Should handle -e flag with extras and markers.
        """
        req = requirement_factory(
            name="mypackage",
            url=url_factory["git_https"],
            editable=True,
            markers='sys_platform == "linux"',
            comment=comment_factory["local_dev"],
        )
        result = req.to_string(include_comment=True)

        assert result.startswith("-e")
        assert "git+https://github.com/user/repo.git" in result
        assert '; sys_platform == "linux"' in result
        assert "# Local development" in result

    @pytest.mark.unit
    def test_url_with_extras(
        self, requirement_factory, url_factory, extras_factory
    ) -> None:
        """Test URL-based requirement with extras.

        Edge case: Extras should be added to URL.
        """
        req = requirement_factory(
            name="requests",
            url=url_factory["github_main"],
            extras=extras_factory["single"],
        )
        result = req.to_string()
        # URL should include extras
        assert "https://github.com/psf/requests/archive/main.zip[security]" in result


@pytest.mark.unit
class TestUpdateVersion:
    """Tests for Requirement.update_version method."""

    @pytest.mark.unit
    def test_update_simple_requirement(
        self, requirement_factory, spec_factory, version_factory
    ) -> None:
        """Test updating version of simple requirement.

        Happy path: Basic version update with == operator.
        """
        req = requirement_factory(name="requests", specs=[("==", "2.20.0")])
        result = req.update_version(
            version_factory["stable"], preserve_trailing_newline=False
        )
        assert result == "requests==2.28.0"

    @pytest.mark.unit
    def test_update_replaces_all_specs(
        self, requirement_factory, spec_factory, version_factory
    ) -> None:
        """Test update replaces all existing specifiers.

        Multiple old specifiers should be replaced with single ==.
        """
        req = requirement_factory(name="requests", specs=spec_factory["exclude"])
        result = req.update_version(
            version_factory["stable"], preserve_trailing_newline=False
        )
        assert result == "requests==2.28.0"
        assert "<3.0.0" not in result
        assert "!=2.5.0" not in result

    @pytest.mark.unit
    def test_update_preserves_extras(
        self, requirement_factory, extras_factory, version_factory
    ) -> None:
        """Test update preserves extras.

        Extras should remain in updated requirement.
        """
        req = requirement_factory(
            name="requests", specs=[("==", "2.20.0")], extras=extras_factory["multiple"]
        )
        result = req.update_version(version_factory["stable"])
        assert result == "requests[security,socks]==2.28.0\n"

    @pytest.mark.unit
    def test_update_preserves_markers(
        self, requirement_factory, marker_factory, version_factory
    ) -> None:
        """Test update preserves environment markers.

        Markers should remain in updated requirement.
        """
        req = requirement_factory(
            name="requests",
            specs=[("==", "2.20.0")],
            markers=marker_factory["python_version"],
        )
        result = req.update_version(version_factory["stable"])
        assert 'python_version >= "3.7"' in result

    @pytest.mark.unit
    def test_update_preserves_url(
        self, requirement_factory, url_factory, version_factory
    ) -> None:
        """Test update preserves URL.

        URL-based requirements should keep URL.
        """
        req = requirement_factory(
            name="requests",
            url=url_factory["github_main"],
            specs=[("==", "2.20.0")],
        )
        result = req.update_version(version_factory["stable"])
        assert "https://github.com/psf/requests/archive/main.zip" in result

    @pytest.mark.unit
    def test_update_preserves_editable_flag(
        self, requirement_factory, version_factory
    ) -> None:
        """Test update preserves editable flag.

        Editable installs should remain editable.
        """
        req = requirement_factory(
            name="mypackage", specs=[("==", "1.0.0")], editable=True
        )
        result = req.update_version("1.5.0")
        assert result.startswith("-e")

    @pytest.mark.unit
    def test_update_removes_hashes(
        self, requirement_factory, hash_factory, version_factory
    ) -> None:
        """Test update removes hash entries.

        Hashes are version-specific and should be removed.
        """
        req = requirement_factory(
            name="requests",
            specs=[("==", "2.20.0")],
            hashes=hash_factory["multiple_sha256"],
        )
        result = req.update_version(version_factory["stable"])
        assert "--hash=" not in result

    @pytest.mark.unit
    def test_update_preserves_comment(
        self, requirement_with_comment, version_factory
    ) -> None:
        """Test update preserves inline comment.

        Comments should remain in updated requirement.
        """
        req = requirement_with_comment
        result = req.update_version(version_factory["stable"])
        assert "# Production dependency" in result

    @pytest.mark.unit
    def test_update_with_newline_preserved(
        self, requirement_factory, version_factory
    ) -> None:
        """Test update with trailing newline preservation.

        Default behavior should add trailing newline.
        """
        req = requirement_factory(name="requests", specs=[("==", "2.20.0")])
        result = req.update_version(
            version_factory["stable"], preserve_trailing_newline=True
        )
        assert result.endswith("\n")

    @pytest.mark.unit
    def test_update_without_newline(self, requirement_factory, version_factory) -> None:
        """Test update without trailing newline.

        preserve_trailing_newline=False should not add newline.
        """
        req = requirement_factory(name="requests", specs=[("==", "2.20.0")])
        result = req.update_version(
            version_factory["stable"], preserve_trailing_newline=False
        )
        assert not result.endswith("\n")
        assert result == "requests==2.28.0"

    @pytest.mark.unit
    def test_update_with_all_features(
        self,
        requirement_factory,
        spec_factory,
        extras_factory,
        marker_factory,
        comment_factory,
        version_factory,
    ) -> None:
        """Test update with complex requirement.

        Integration test: Update requirement with all features.
        """
        req = requirement_factory(
            name="requests",
            specs=spec_factory["range"],
            extras=extras_factory["single"],
            markers=marker_factory["python_version"],
            hashes=["sha256:abc123"],
            comment=comment_factory["security"],
            editable=False,
        )
        result = req.update_version(version_factory["stable"])

        # Should have new version
        assert "==2.28.0" in result
        # Should preserve extras, markers, comment
        assert "[security]" in result
        assert 'python_version >= "3.7"' in result
        assert "# Pinned for security" in result
        # Should not have old specs or hashes
        assert "<3.0.0" not in result
        assert "--hash=" not in result

    @pytest.mark.unit
    def test_update_preserves_line_number(self, requirement_factory) -> None:
        """Test update preserves original line number.

        Line number tracking should be maintained.
        """
        req = requirement_factory(
            name="requests", specs=[("==", "2.20.0")], line_number=42
        )
        # Create updated requirement object to verify
        updated_req = Requirement(
            name=req.name, specs=[(">=", "2.28.0")], line_number=req.line_number
        )
        assert updated_req.line_number == 42


@pytest.mark.unit
class TestStringRepresentations:
    """Tests for Requirement.__str__ and __repr__ methods."""

    @pytest.mark.unit
    def test_str_simple(self, requirement_with_version) -> None:
        """Test __str__ with simple requirement.

        Should delegate to to_string().
        """
        result = str(requirement_with_version)
        assert result == "requests>=2.0.0"

    @pytest.mark.unit
    def test_str_complex(
        self,
        requirement_factory,
        spec_factory,
        extras_factory,
        hash_factory,
        comment_factory,
    ) -> None:
        """Test __str__ with complex requirement.

        Should include all features via to_string().
        """
        req = requirement_factory(
            name="requests",
            specs=spec_factory["min_only"],
            extras=extras_factory["single"],
            hashes=["sha256:abc123"],
            comment="Production",
        )
        result = str(req)

        assert "requests[security]>=2.0.0" in result
        assert "--hash=sha256:abc123" in result
        assert "# Production" in result

    @pytest.mark.unit
    def test_repr_minimal(self, simple_requirement) -> None:
        """Test __repr__ with minimal data.

        Should show constructor format for debugging.
        """
        result = repr(simple_requirement)

        assert result.startswith("Requirement(")
        assert "name='requests'" in result
        assert "specs=[]" in result
        assert "extras=[]" in result
        assert "editable=False" in result
        assert "line_number=0" in result

    @pytest.mark.unit
    def test_repr_full(self, requirement_factory, spec_factory, extras_factory) -> None:
        """Test __repr__ with full data.

        Should show key fields in constructor format.
        """
        req = requirement_factory(
            name="requests",
            specs=spec_factory["range"],
            extras=extras_factory["single"],
            editable=True,
            line_number=42,
        )
        result = repr(req)

        assert "name='requests'" in result
        assert "specs=[('>=', '2.0.0'), ('<', '3.0.0')]" in result
        assert "extras=['security']" in result
        assert "editable=True" in result
        assert "line_number=42" in result

    @pytest.mark.unit
    def test_str_vs_repr_difference(self, requirement_with_version) -> None:
        """Test str() and repr() produce different outputs.

        str() should be user-friendly, repr() for debugging.
        """
        str_result = str(requirement_with_version)
        repr_result = repr(requirement_with_version)

        assert str_result == "requests>=2.0.0"
        assert "Requirement(" in repr_result
        assert str_result != repr_result


@pytest.mark.unit
class TestEdgeCases:
    """Tests for edge cases and unusual inputs."""

    @pytest.mark.unit
    def test_empty_package_name(self, requirement_factory, package_names) -> None:
        """Test requirement with empty package name.

        Edge case: Empty string as name.
        """
        req = requirement_factory(name=package_names["empty"])
        result = req.to_string()
        assert result == ""

    @pytest.mark.unit
    def test_package_name_with_special_characters(
        self, requirement_factory, package_names
    ) -> None:
        """Test package name with special characters.

        Edge case: Names with dots, dashes, underscores.
        """
        req = requirement_factory(name=package_names["special_chars"])
        result = req.to_string()
        assert result == "my-package.name_v2"

    @pytest.mark.unit
    def test_very_long_package_name(self, requirement_factory, package_names) -> None:
        """Test requirement with very long package name.

        Edge case: Extremely long names should be handled.
        """
        long_name = package_names["long"]
        req = requirement_factory(name=long_name)
        result = req.to_string()
        assert result == long_name

    @pytest.mark.unit
    def test_spec_with_wildcards(self, requirement_factory, spec_factory) -> None:
        """Test version specifier with wildcards.

        Edge case: Wildcard versions like ==2.*.
        """
        req = requirement_factory(name="requests", specs=spec_factory["wildcard"])
        result = req.to_string()
        assert result == "requests==2.*"

    @pytest.mark.unit
    def test_spec_with_local_version(
        self, requirement_factory, version_factory
    ) -> None:
        """Test version specifier with local identifier.

        Edge case: PEP 440 local versions like 1.0+local.
        """
        req = requirement_factory(
            name="requests", specs=[("==", version_factory["local"])]
        )
        result = req.to_string()
        assert result == "requests==2.28.0+local"

    @pytest.mark.unit
    def test_spec_with_epoch(self, requirement_factory, version_factory) -> None:
        """Test version specifier with epoch.

        Edge case: PEP 440 epochs like 1!2.0.0.
        """
        req = requirement_factory(
            name="requests", specs=[("==", version_factory["epoch"])]
        )
        result = req.to_string()
        assert result == "requests==1!2.0.0"

    @pytest.mark.unit
    def test_marker_with_complex_expression(
        self, requirement_factory, marker_factory
    ) -> None:
        """Test requirement with complex marker expression.

        Edge case: Multiple conditions in markers.
        """
        req = requirement_factory(
            name="requests",
            markers=marker_factory["complex"],
        )
        result = req.to_string()

        assert 'python_version >= "3.7"' in result
        assert 'sys_platform == "linux"' in result
        assert 'platform_machine == "x86_64"' in result

    @pytest.mark.unit
    def test_marker_with_or_condition(
        self, requirement_factory, marker_factory
    ) -> None:
        """Test requirement with OR marker expression.

        Edge case: Markers with or operator.
        """
        req = requirement_factory(
            name="requests",
            markers=marker_factory["or_condition"],
        )
        result = req.to_string()
        assert 'sys_platform == "win32" or sys_platform == "darwin"' in result

    @pytest.mark.unit
    def test_url_with_git_protocol(self, requirement_factory, url_factory) -> None:
        """Test URL with git+ protocol.

        Edge case: VCS URLs.
        """
        req = requirement_factory(
            name="mypackage",
            url=url_factory["git_https"],
        )
        result = req.to_string()
        assert "git+https://github.com/user/repo.git@main#egg=mypackage" in result

    @pytest.mark.unit
    def test_url_with_ssh(self, requirement_factory, url_factory) -> None:
        """Test URL with SSH protocol.

        Edge case: SSH-based VCS URLs.
        """
        req = requirement_factory(name="mypackage", url=url_factory["git_ssh"])
        result = req.to_string()
        assert "git+ssh://git@github.com/user/repo.git" in result

    @pytest.mark.unit
    def test_url_with_branch_and_subdirectory(
        self, requirement_factory, url_factory
    ) -> None:
        """Test URL with branch and subdirectory.

        Edge case: Complex VCS URL with path.
        """
        req = requirement_factory(
            name="mypackage",
            url=url_factory["git_subdirectory"],
        )
        result = req.to_string()

        assert "feature-branch" in result
        assert "subdirectory=packages/mypackage" in result

    @pytest.mark.unit
    def test_comment_with_special_characters(
        self, requirement_factory, comment_factory
    ) -> None:
        """Test comment with special characters.

        Edge case: Comments with unicode, symbols.
        """
        req = requirement_factory(
            name="requests", comment=comment_factory["special_chars"]
        )
        result = req.to_string(include_comment=True)
        assert "Critical! ⚠️ Don't update (see issue #123)" in result

    @pytest.mark.unit
    def test_comment_with_hash_symbol(
        self, requirement_factory, comment_factory
    ) -> None:
        """Test comment containing # symbol.

        Edge case: Hash symbols within comment text.
        """
        req = requirement_factory(
            name="requests", comment=comment_factory["hash_symbols"]
        )
        result = req.to_string(include_comment=True)
        assert "# See issue #123 and PR #456" in result

    @pytest.mark.unit
    def test_multiple_extras_ordering(
        self, requirement_factory, extras_factory
    ) -> None:
        """Test extras maintain insertion order.

        Edge case: Order of extras should be preserved.
        """
        req = requirement_factory(name="requests", extras=extras_factory["ordered"])
        result = req.to_string()
        assert result == "requests[z-extra,a-extra,m-extra]"

    @pytest.mark.unit
    def test_hash_with_different_algorithms(
        self, requirement_factory, spec_factory, hash_factory
    ) -> None:
        """Test hashes with different algorithms.

        Edge case: Multiple hash algorithms (sha256, sha512, md5).
        """
        req = requirement_factory(
            name="requests",
            specs=spec_factory["pinned"],
            hashes=hash_factory["different_algorithms"],
        )
        result = req.to_string(include_hashes=True)

        assert "--hash=sha256:abc123" in result
        assert "--hash=sha512:def456ghi789" in result
        assert "--hash=md5:xyz890" in result

    @pytest.mark.unit
    def test_very_long_comment(self, requirement_factory, comment_factory) -> None:
        """Test requirement with very long comment.

        Edge case: Comments can be arbitrarily long.
        """
        long_comment = comment_factory["long"]
        req = requirement_factory(name="requests", comment=long_comment)
        result = req.to_string(include_comment=True)
        assert long_comment in result

    @pytest.mark.unit
    def test_zero_line_number(self, requirement_factory) -> None:
        """Test requirement with line number 0.

        Edge case: Zero is valid line number (default).
        """
        req = requirement_factory(name="requests", line_number=0)
        assert req.line_number == 0

    @pytest.mark.unit
    def test_large_line_number(self, requirement_factory) -> None:
        """Test requirement with very large line number.

        Edge case: Large files can have high line numbers.
        """
        req = requirement_factory(name="requests", line_number=999999)
        assert req.line_number == 999999

    @pytest.mark.unit
    def test_raw_line_with_whitespace(self, requirement_factory) -> None:
        """Test raw_line preserves whitespace.

        Edge case: Original line might have leading/trailing space.
        """
        req = requirement_factory(
            name="requests", raw_line="  requests>=2.0.0 # comment  "
        )
        assert req.raw_line == "  requests>=2.0.0 # comment  "

    @pytest.mark.unit
    def test_operator_variations(self, requirement_factory, all_operators) -> None:
        """Test all valid PEP 440 operators.

        Edge case: All comparison operators should work.
        """
        for op in all_operators:
            req = requirement_factory(name="requests", specs=[(op, "2.0.0")])
            result = req.to_string()
            assert f"requests{op}2.0.0" in result

    @pytest.mark.unit
    def test_compatible_release_operator(self, requirement_factory) -> None:
        """Test compatible release operator ~=.

        Edge case: Tilde equal operator for compatible releases.
        """
        req = requirement_factory(name="requests", specs=[("~=", "2.28")])
        result = req.to_string()
        assert result == "requests~=2.28"

    @pytest.mark.unit
    def test_arbitrary_equality_operator(self, requirement_factory) -> None:
        """Test arbitrary equality operator ===.

        Edge case: Triple equals for string matching.
        """
        req = requirement_factory(name="requests", specs=[("===", "2.28.0-local")])
        result = req.to_string()
        assert result == "requests===2.28.0-local"

    @pytest.mark.unit
    def test_update_version_with_prerelease(
        self, requirement_factory, spec_factory, version_factory
    ) -> None:
        """Test updating to pre-release version.

        Edge case: Pre-release versions like 3.0.0a1.
        """
        req = requirement_factory(name="requests", specs=spec_factory["pinned"])
        result = req.update_version(version_factory["prerelease"])
        assert "==3.0.0a1" in result

    @pytest.mark.unit
    def test_update_version_with_dev_version(
        self, requirement_factory, spec_factory, version_factory
    ) -> None:
        """Test updating to development version.

        Edge case: Dev versions like 3.0.0.dev1.
        """
        req = requirement_factory(name="requests", specs=spec_factory["pinned"])
        result = req.update_version(version_factory["dev"])
        assert "==3.0.0.dev1" in result

    @pytest.mark.unit
    def test_empty_specs_list_to_string(self, simple_requirement) -> None:
        """Test to_string with explicitly empty specs list.

        Edge case: Empty list should produce name only.
        """
        result = simple_requirement.to_string()
        assert result == "requests"

    @pytest.mark.unit
    def test_empty_extras_list_to_string(self, requirement_factory) -> None:
        """Test to_string with explicitly empty extras list.

        Edge case: Empty list should not add brackets.
        """
        req = requirement_factory(name="requests", extras=[])
        result = req.to_string()
        assert result == "requests"
        assert "[" not in result

    @pytest.mark.unit
    def test_empty_hashes_list_to_string(self, requirement_factory) -> None:
        """Test to_string with explicitly empty hashes list.

        Edge case: Empty list should not add --hash entries.
        """
        req = requirement_factory(name="requests", hashes=[])
        result = req.to_string(include_hashes=True)
        assert result == "requests"
        assert "--hash=" not in result


@pytest.mark.unit
class TestIntegrationScenarios:
    """Integration tests for real-world requirement scenarios."""

    @pytest.mark.unit
    def test_typical_pinned_requirement(
        self, requirement_factory, spec_factory, hash_factory, version_factory
    ) -> None:
        """Test typical pinned requirement with hash.

        Integration: Common pattern for reproducible installs.
        """
        req = requirement_factory(
            name="requests",
            specs=spec_factory["pinned"],
            hashes=hash_factory["single_sha256"],
            line_number=15,
            raw_line="requests==2.28.0 --hash=sha256:abc123def456",
        )

        # Test string rendering
        result = req.to_string()
        assert "requests==2.28.0" in result
        assert "--hash=sha256:abc123def456" in result

        # Test version update
        updated = req.update_version(version_factory["updated"])
        assert "==2.31.0" in updated
        assert "--hash=" not in updated  # Hashes removed

    @pytest.mark.unit
    def test_development_dependency_workflow(
        self, requirement_factory, marker_factory, comment_factory, version_factory
    ) -> None:
        """Test development dependency with markers and comment.

        Integration: Dev dependency with platform markers.
        """
        req = requirement_factory(
            name="pytest",
            specs=[(">=", "7.0.0")],
            markers=marker_factory["python_version_38"],
            comment=comment_factory["testing"],
            line_number=25,
        )

        # Render with all features
        result = req.to_string()
        assert "pytest>=7.0.0" in result
        assert 'python_version >= "3.8"' in result
        assert "# Testing framework" in result

        # Update version
        updated = req.update_version("7.4.0")
        assert "==7.4.0" in updated
        assert "# Testing framework" in updated

    @pytest.mark.unit
    def test_editable_local_package_workflow(
        self, requirement_factory, url_factory, extras_factory, comment_factory
    ) -> None:
        """Test editable local package installation.

        Integration: Common development workflow.
        """
        req = requirement_factory(
            name="myproject",
            url=url_factory["local"],
            editable=True,
            extras=extras_factory["dev"],
            comment=comment_factory["local_dev"],
            line_number=1,
        )

        result = req.to_string()
        assert result.startswith("-e")
        assert ".[dev,test]" in result
        assert "# Local development" in result

    @pytest.mark.unit
    def test_vcs_requirement_with_branch(
        self, requirement_factory, url_factory, marker_factory, comment_factory
    ) -> None:
        """Test VCS requirement with specific branch.

        Integration: Installing from git repository.
        """
        req = requirement_factory(
            name="my-lib",
            url=url_factory["git_branch"],
            editable=False,
            markers=marker_factory["not_windows"],
            comment=comment_factory["develop_branch"],
        )

        result = req.to_string()
        assert "git+https://github.com/user/my-lib.git@develop" in result
        assert '; sys_platform != "win32"' in result
        assert "# Latest develop branch" in result

    @pytest.mark.unit
    def test_requirement_with_all_operators(
        self,
        requirement_factory,
        spec_factory,
        extras_factory,
        comment_factory,
        version_factory,
    ) -> None:
        """Test requirement using multiple operators.

        Integration: Complex version constraints.
        """
        req = requirement_factory(
            name="django",
            specs=spec_factory["complex"],
            extras=extras_factory["django"],
            comment=comment_factory["breaking_changes"],
        )

        result = req.to_string()
        assert "django[bcrypt]>=3.2,<5.0,!=4.0" in result
        assert "# Avoid Django 4.0" in result

        # Update should replace all specs
        updated = req.update_version("4.2.0")
        assert "==4.2.0" in updated
        assert "<5.0" not in updated
        assert "!=4.0" not in updated

    @pytest.mark.unit
    def test_security_constrained_requirement(
        self, requirement_factory, hash_factory, comment_factory
    ) -> None:
        """Test requirement with security-related constraints.

        Integration: Security fix with exclusions.
        """
        req = requirement_factory(
            name="pillow",
            specs=[(">=", "9.0.0"), ("!=", "9.1.0"), ("!=", "9.1.1")],
            comment=comment_factory["cve"],
            hashes=hash_factory["security"],
            line_number=50,
        )

        result = req.to_string()
        assert "pillow>=9.0.0,!=9.1.0,!=9.1.1" in result
        assert "CVE-2023-XXXXX" in result
        assert "--hash=sha256:hash1" in result

    @pytest.mark.unit
    def test_platform_specific_requirement(
        self, requirement_factory, marker_factory, comment_factory
    ) -> None:
        """Test requirement specific to certain platforms.

        Integration: Platform-conditional dependency.
        """
        req = requirement_factory(
            name="pywin32",
            specs=[(">=", "300")],
            markers=marker_factory["windows"],
            comment=comment_factory["windows"],
        )

        result = req.to_string()
        assert "pywin32>=300" in result
        assert '; sys_platform == "win32"' in result

    @pytest.mark.unit
    def test_requirement_update_preserves_context(
        self,
        requirement_factory,
        spec_factory,
        extras_factory,
        marker_factory,
        comment_factory,
    ) -> None:
        """Test version update preserves all context.

        Integration: Full update workflow maintaining metadata.
        """
        original = requirement_factory(
            name="flask",
            specs=spec_factory["range"],
            extras=extras_factory["flask"],
            markers=marker_factory["python_version_38"],
            comment=comment_factory["web_framework"],
            line_number=10,
            raw_line='flask[async]>=2.0.0,<3.0.0 ; python_version >= "3.8" # Web framework',
        )

        # Update version
        updated_str = original.update_version("2.3.0")

        # Verify preservation
        assert "flask[async]==2.3.0" in updated_str
        assert 'python_version >= "3.8"' in updated_str
        assert "# Web framework" in updated_str
        assert "<3.0.0" not in updated_str

    @pytest.mark.unit
    def test_roundtrip_string_consistency(
        self,
        requirement_factory,
        spec_factory,
        extras_factory,
        marker_factory,
        comment_factory,
    ) -> None:
        """Test to_string output can represent requirement.

        Integration: String rendering should be consistent.
        """
        req = requirement_factory(
            name="numpy",
            specs=spec_factory["range"],
            extras=extras_factory["numpy"],
            markers=marker_factory["python_version_39"],
            comment=comment_factory["scientific"],
        )

        # Render twice
        first = req.to_string()
        second = req.to_string()

        # Should be identical
        assert first == second
        # Should contain all components
        assert "numpy[dev]>=2.0.0,<3.0.0" in first
        assert 'python_version >= "3.9"' in first
        assert "# Scientific computing" in first
