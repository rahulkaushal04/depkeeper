import pytest
import tempfile
from typing import List
from pathlib import Path

from depkeeper.core.parser import RequirementsParser
from depkeeper.models.requirement import Requirement
from depkeeper.exceptions import ParseError, FileOperationError


@pytest.fixture
def parser() -> RequirementsParser:
    """Create a fresh parser instance for each test."""
    return RequirementsParser()


@pytest.fixture
def temp_requirements_file(tmp_path: Path):
    """Create a temporary requirements.txt file."""

    def _create_file(content: str) -> Path:
        req_file = tmp_path / "requirements.txt"
        req_file.write_text(content, encoding="utf-8")
        return req_file

    return _create_file


class TestSimpleRequirements:
    """Tests for basic package name requirements."""

    def test_simple_package_name(self, parser: RequirementsParser):
        """Test parsing a simple package name without version."""
        req = parser.parse_line("requests", 1)

        assert req is not None
        assert req.name == "requests"
        assert req.specs == []
        assert req.extras == []
        assert req.markers is None
        assert req.url is None
        assert not req.editable
        assert req.line_number == 1

    def test_package_with_single_version(self, parser: RequirementsParser):
        """Test parsing package with exact version."""
        req = parser.parse_line("requests==2.28.0", 1)

        assert req is not None
        assert req.name == "requests"
        assert req.specs == [("==", "2.28.0")]

    def test_package_with_multiple_specifiers(self, parser: RequirementsParser):
        """Test parsing package with multiple version specifiers."""
        req = parser.parse_line("django>=3.2,<5.0", 1)

        assert req is not None
        assert req.name == "django"
        assert (">=", "3.2") in req.specs
        assert ("<", "5.0") in req.specs

    def test_package_with_compatible_release(self, parser: RequirementsParser):
        """Test parsing package with compatible release operator (~=)."""
        req = parser.parse_line("flask~=2.0", 1)

        assert req is not None
        assert req.name == "flask"
        assert req.specs == [("~=", "2.0")]

    def test_package_with_not_equal(self, parser: RequirementsParser):
        """Test parsing package with not-equal operator."""
        req = parser.parse_line("numpy!=1.19.0", 1)

        assert req is not None
        assert req.name == "numpy"
        assert req.specs == [("!=", "1.19.0")]

    def test_package_with_arbitrary_equality(self, parser: RequirementsParser):
        """Test parsing package with arbitrary equality (===)."""
        req = parser.parse_line("package===1.0.0+local", 1)

        assert req is not None
        assert req.name == "package"
        assert req.specs == [("===", "1.0.0+local")]


class TestNameNormalization:
    """Tests for PEP 503 package name normalization."""

    def test_underscore_normalization(self, parser: RequirementsParser):
        """Test that underscores are normalized to hyphens."""
        req = parser.parse_line("my_package==1.0.0", 1)

        assert req is not None
        assert req.name == "my-package"

    def test_dot_normalization(self, parser: RequirementsParser):
        """Test that dots are normalized to hyphens."""
        req = parser.parse_line("my.package==1.0.0", 1)

        assert req is not None
        assert req.name == "my-package"

    def test_mixed_separators_normalization(self, parser: RequirementsParser):
        """Test normalization with mixed separators."""
        req = parser.parse_line("My_Package.Name==1.0.0", 1)

        assert req is not None
        assert req.name == "my-package-name"

    def test_case_normalization(self, parser: RequirementsParser):
        """Test that package names are lowercased."""
        req = parser.parse_line("REQUESTS==2.28.0", 1)

        assert req is not None
        assert req.name == "requests"


class TestExtras:
    """Tests for package extras."""

    def test_single_extra(self, parser: RequirementsParser):
        """Test parsing package with single extra."""
        req = parser.parse_line("requests[security]==2.28.0", 1)

        assert req is not None
        assert req.name == "requests"
        assert "security" in req.extras
        assert req.specs == [("==", "2.28.0")]

    def test_multiple_extras(self, parser: RequirementsParser):
        """Test parsing package with multiple extras."""
        req = parser.parse_line("django[argon2,bcrypt]>=3.2", 1)

        assert req is not None
        assert req.name == "django"
        assert "argon2" in req.extras
        assert "bcrypt" in req.extras

    def test_extras_no_version(self, parser: RequirementsParser):
        """Test parsing package with extras but no version."""
        req = parser.parse_line("celery[redis]", 1)

        assert req is not None
        assert req.name == "celery"
        assert "redis" in req.extras
        assert req.specs == []


class TestEnvironmentMarkers:
    """Tests for PEP 508 environment markers."""

    def test_python_version_marker(self, parser: RequirementsParser):
        """Test parsing with python_version marker."""
        req = parser.parse_line('typing-extensions>=4.0; python_version<"3.10"', 1)

        assert req is not None
        assert req.name == "typing-extensions"
        assert req.markers is not None
        assert "python_version" in req.markers

    def test_platform_marker(self, parser: RequirementsParser):
        """Test parsing with platform marker."""
        req = parser.parse_line('pywin32>=300; sys_platform=="win32"', 1)

        assert req is not None
        assert req.name == "pywin32"
        assert req.markers is not None
        assert "sys_platform" in req.markers

    def test_complex_marker(self, parser: RequirementsParser):
        """Test parsing with complex marker expression."""
        req = parser.parse_line(
            'backports.zoneinfo>=0.2.1; python_version<"3.9" and platform_system=="Linux"',
            1,
        )

        assert req is not None
        assert req.name == "backports-zoneinfo"
        assert req.markers is not None
        assert "python_version" in req.markers
        assert "platform_system" in req.markers

    def test_extra_marker(self, parser: RequirementsParser):
        """Test parsing with extra marker."""
        req = parser.parse_line('pytest-cov>=3.0; extra=="dev"', 1)

        assert req is not None
        assert req.name == "pytest-cov"
        assert req.markers is not None
        assert "extra" in req.markers


class TestURLDependencies:
    """Tests for direct URL dependencies (git, https, file)."""

    def test_git_https_url(self, parser: RequirementsParser):
        """Test parsing git+https URL."""
        req = parser.parse_line("git+https://github.com/user/repo.git#egg=package", 1)

        assert req is not None
        assert req.name == "package"
        assert req.url == "git+https://github.com/user/repo.git#egg=package"
        assert req.specs == []

    def test_git_ssh_url(self, parser: RequirementsParser):
        """Test parsing git+ssh URL."""
        req = parser.parse_line(
            "git+ssh://git@github.com/user/repo.git#egg=mypackage", 1
        )

        assert req is not None
        assert req.name == "mypackage"
        assert req.url.startswith("git+ssh://")

    def test_https_archive_url(self, parser: RequirementsParser):
        """Test parsing direct HTTPS archive URL."""
        req = parser.parse_line(
            "https://github.com/user/repo/archive/main.zip#egg=package", 1
        )

        assert req is not None
        assert req.name == "package"
        assert req.url.startswith("https://")

    def test_file_url(self, parser: RequirementsParser):
        """Test parsing file:// URL."""
        req = parser.parse_line("file:///path/to/package.tar.gz#egg=localpackage", 1)

        assert req is not None
        assert req.name == "localpackage"
        assert req.url.startswith("file://")

    def test_url_without_egg(self, parser: RequirementsParser):
        """Test URL without #egg= should raise ParseError."""
        with pytest.raises(ParseError) as exc_info:
            parser.parse_line("https://example.com/package.tar.gz", 1)

        assert "egg=" in str(exc_info.value).lower()

    def test_git_url_with_branch(self, parser: RequirementsParser):
        """Test git URL with branch specifier."""
        req = parser.parse_line(
            "git+https://github.com/user/repo.git@develop#egg=package", 1
        )

        assert req is not None
        assert req.name == "package"
        assert "@develop" in req.url

    def test_git_url_with_commit(self, parser: RequirementsParser):
        """Test git URL with commit hash."""
        req = parser.parse_line(
            "git+https://github.com/user/repo.git@abc123def456#egg=package", 1
        )

        assert req is not None
        assert req.name == "package"
        assert "@abc123" in req.url
