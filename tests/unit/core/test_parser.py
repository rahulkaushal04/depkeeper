import pytest
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

    def test_git_http_url(self, parser: RequirementsParser):
        """Test parsing git+http URL."""
        req = parser.parse_line("git+http://example.com/repo.git#egg=package", 1)

        assert req is not None
        assert req.name == "package"
        assert req.url.startswith("git+http://")

    def test_git_git_url(self, parser: RequirementsParser):
        """Test parsing git+git URL."""
        req = parser.parse_line("git+git://example.com/repo.git#egg=package", 1)

        assert req is not None
        assert req.name == "package"
        assert req.url.startswith("git+git://")

    def test_bzr_url(self, parser: RequirementsParser):
        """Test parsing bzr URL."""
        req = parser.parse_line("bzr+https://example.com/repo#egg=package", 1)

        assert req is not None
        assert req.name == "package"
        assert req.url.startswith("bzr+https://")

    def test_hg_url(self, parser: RequirementsParser):
        """Test parsing hg (mercurial) URL."""
        req = parser.parse_line("hg+https://example.com/repo#egg=package", 1)

        assert req is not None
        assert req.name == "package"
        assert req.url.startswith("hg+https://")

    def test_svn_url(self, parser: RequirementsParser):
        """Test parsing svn URL."""
        req = parser.parse_line("svn+https://example.com/repo#egg=package", 1)

        assert req is not None
        assert req.name == "package"
        assert req.url.startswith("svn+https://")

    def test_url_without_egg_generates_warning(
        self, parser: RequirementsParser, caplog: pytest.LogCaptureFixture
    ):
        """Test URL without #egg parameter generates warning but works."""
        req = parser.parse_line("git+https://github.com/user/repo.git", 1)

        assert req is not None
        assert req.name == "repo"
        assert len(caplog.records) == 1
        assert "egg=" in caplog.records[0].message.lower()

    def test_http_url(self, parser: RequirementsParser):
        """Test parsing http archive URL."""
        req = parser.parse_line("http://example.com/package-1.0.tar.gz#egg=package", 1)

        assert req is not None
        assert req.name == "package"
        assert req.url.startswith("http://")


class TestEditableInstalls:
    """Tests for editable install syntax (-e / --editable)."""

    def test_editable_short_form(self, parser: RequirementsParser):
        """Test editable install with -e flag."""
        req = parser.parse_line(
            "-e git+https://github.com/user/repo.git#egg=package", 1
        )

        assert req is not None
        assert req.name == "package"
        assert req.editable is True

    def test_editable_long_form(self, parser: RequirementsParser):
        """Test editable install with --editable flag."""
        req = parser.parse_line(
            "--editable git+https://github.com/user/repo.git#egg=package", 1
        )

        assert req is not None
        assert req.name == "package"
        assert req.editable is True

    def test_editable_local_path(self, parser: RequirementsParser, tmp_path: Path):
        """Test editable install with local path."""
        local_dir = tmp_path / "mypackage"
        local_dir.mkdir()

        req = parser.parse_line(
            f"-e {local_dir}#egg=mypackage", 1, _current_directory_path=tmp_path
        )

        assert req is not None
        assert req.name == "mypackage"
        assert req.editable is True

    def test_editable_dot_path(self, parser: RequirementsParser):
        """Test editable install with current directory."""
        req = parser.parse_line(
            "-e .#egg=mypackage", 1, _current_directory_path=Path.cwd()
        )

        assert req is not None
        assert req.name == "mypackage"
        assert req.editable is True


class TestHashSupport:
    """Tests for --hash directive support."""

    def test_single_hash(self, parser: RequirementsParser):
        """Test parsing requirement with single hash."""
        req = parser.parse_line("requests==2.28.0 --hash=sha256:abc123", 1)

        assert req is not None
        assert req.name == "requests"
        assert len(req.hashes) == 1
        assert "sha256:abc123" in req.hashes

    def test_multiple_hashes(self, parser: RequirementsParser):
        """Test parsing requirement with multiple hashes."""
        req = parser.parse_line(
            "requests==2.28.0 --hash=sha256:abc123 --hash=sha256:def456", 1
        )

        assert req is not None
        assert req.name == "requests"
        assert len(req.hashes) == 2
        assert "sha256:abc123" in req.hashes
        assert "sha256:def456" in req.hashes

    def test_hash_with_equals(self, parser: RequirementsParser):
        """Test hash directive with equals separator."""
        req = parser.parse_line("django==4.0 --hash=sha256:12345", 1)

        assert req is not None
        assert "sha256:12345" in req.hashes

    def test_hash_with_space(self, parser: RequirementsParser):
        """Test hash directive with space separator raises ParseError."""
        with pytest.raises(ParseError) as exc_info:
            parser.parse_line("django==4.0 --hash sha256:12345", 1)


class TestInlineComments:
    """Tests for inline comment handling."""

    def test_simple_inline_comment(self, parser: RequirementsParser):
        """Test requirement with inline comment."""
        req = parser.parse_line("requests==2.28.0  # Used for HTTP requests", 1)

        assert req is not None
        assert req.name == "requests"
        assert req.comment == "Used for HTTP requests"

    def test_comment_with_url(self, parser: RequirementsParser):
        """Test that # in URLs is not treated as comment."""
        req = parser.parse_line("git+https://github.com/user/repo.git#egg=package", 1)

        assert req is not None
        assert req.name == "package"
        assert req.comment is None

    def test_comment_after_url(self, parser: RequirementsParser):
        """Test comment after URL with #egg."""
        req = parser.parse_line(
            "git+https://github.com/user/repo.git#egg=package # My package", 1
        )

        assert req is not None
        assert req.name == "package"
        assert req.comment == "My package"

    def test_empty_comment(self, parser: RequirementsParser):
        """Test requirement with empty comment."""
        req = parser.parse_line("requests==2.28.0 #", 1)

        assert req is not None
        assert req.comment == ""


class TestQuotedRequirements:
    """Tests for quoted requirement strings."""

    def test_double_quoted_requirement(self, parser: RequirementsParser):
        """Test requirement wrapped in double quotes."""
        req = parser.parse_line('"requests==2.28.0"', 1)

        assert req is not None
        assert req.name == "requests"
        assert req.specs == [("==", "2.28.0")]

    def test_single_quoted_requirement(self, parser: RequirementsParser):
        """Test requirement wrapped in single quotes."""
        req = parser.parse_line("'django>=3.2'", 1)

        assert req is not None
        assert req.name == "django"
        assert (">=", "3.2") in req.specs

    def test_quoted_url(self, parser: RequirementsParser):
        """Test quoted URL requirement."""
        req = parser.parse_line('"git+https://github.com/user/repo.git#egg=package"', 1)

        assert req is not None
        assert req.name == "package"


class TestEmptyAndCommentLines:
    """Tests for empty lines and comment-only lines."""

    def test_empty_line(self, parser: RequirementsParser):
        """Test that empty lines return None."""
        result = parser.parse_line("", 1)
        assert result is None

    def test_whitespace_only_line(self, parser: RequirementsParser):
        """Test that whitespace-only lines return None."""
        result = parser.parse_line("   \t  ", 1)
        assert result is None

    def test_comment_only_line(self, parser: RequirementsParser):
        """Test that comment-only lines return None."""
        result = parser.parse_line("# This is a comment", 1)
        assert result is None

    def test_comment_with_leading_whitespace(self, parser: RequirementsParser):
        """Test comment with leading whitespace."""
        result = parser.parse_line("   # Comment with spaces", 1)
        assert result is None


class TestLocalPaths:
    """Tests for local file path requirements."""

    def test_relative_path_dot(self, parser: RequirementsParser, tmp_path: Path):
        """Test relative path starting with ./"""
        local_dir = tmp_path / "package"
        local_dir.mkdir()

        req = parser.parse_line(
            "./package#egg=mypackage", 1, _current_directory_path=tmp_path
        )

        assert req is not None
        assert req.name == "mypackage"
        assert req.url.startswith("file://")

    def test_relative_path_parent(self, parser: RequirementsParser, tmp_path: Path):
        """Test relative path starting with ../"""
        req = parser.parse_line(
            "../package#egg=mypackage", 1, _current_directory_path=tmp_path
        )

        assert req is not None
        assert req.name == "mypackage"

    def test_absolute_path_unix(self, parser: RequirementsParser):
        """Test absolute Unix-style path."""
        req = parser.parse_line("/home/user/package#egg=mypackage", 1)

        assert req is not None
        assert req.name == "mypackage"

    def test_local_path_without_egg(self, parser: RequirementsParser, tmp_path: Path):
        """Test local path without #egg infers name from path."""
        local_dir = tmp_path / "mypackage"
        local_dir.mkdir()

        req = parser.parse_line(
            f"./{local_dir.name}", 1, _current_directory_path=tmp_path
        )

        assert req is not None
        assert req.name == "mypackage"


class TestDirectives:
    """Tests for include and constraint directives."""

    def test_include_directive_short(self, parser: RequirementsParser, tmp_path: Path):
        """Test -r include directive."""
        # Create a file to include
        include_file = tmp_path / "base.txt"
        include_file.write_text("requests==2.28.0\n")

        result = parser.parse_line(
            f"-r {include_file.name}",
            1,
            source_file_path=str(tmp_path / "requirements.txt"),
            _current_directory_path=tmp_path / "requirements.txt",
        )

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].name == "requests"

    def test_include_directive_long(self, parser: RequirementsParser, tmp_path: Path):
        """Test --requirement include directive."""
        include_file = tmp_path / "base.txt"
        include_file.write_text("django>=3.2\n")

        result = parser.parse_line(
            f"--requirement {include_file.name}",
            1,
            source_file_path=str(tmp_path / "requirements.txt"),
            _current_directory_path=tmp_path / "requirements.txt",
        )

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].name == "django"

    def test_constraint_directive_short(
        self, parser: RequirementsParser, tmp_path: Path
    ):
        """Test -c constraint directive."""
        constraint_file = tmp_path / "constraints.txt"
        constraint_file.write_text("requests==2.28.0\n")

        result = parser.parse_line(
            f"-c {constraint_file.name}",
            1,
            source_file_path=str(tmp_path / "requirements.txt"),
            _current_directory_path=tmp_path / "requirements.txt",
        )

        assert result is None  # Constraints don't return requirements

    def test_constraint_directive_long(
        self, parser: RequirementsParser, tmp_path: Path
    ):
        """Test --constraint directive."""
        constraint_file = tmp_path / "constraints.txt"
        constraint_file.write_text("django==4.0\n")

        result = parser.parse_line(
            f"--constraint {constraint_file.name}",
            1,
            source_file_path=str(tmp_path / "requirements.txt"),
            _current_directory_path=tmp_path / "requirements.txt",
        )

        assert result is None

    def test_include_directive_missing_path(
        self, parser: RequirementsParser, caplog: pytest.LogCaptureFixture
    ):
        """Test include directive without file path."""
        result = parser.parse_line("-r", 1)

        assert result is None
        assert len(caplog.records) > 0

    def test_constraint_directive_missing_path(
        self, parser: RequirementsParser, caplog: pytest.LogCaptureFixture
    ):
        """Test constraint directive without file path."""
        result = parser.parse_line("-c", 1)

        assert result is None
        assert len(caplog.records) > 0


class TestErrorHandling:
    """Tests for error handling and invalid input."""

    def test_invalid_syntax(self, parser: RequirementsParser):
        """Test parsing invalid requirement syntax."""
        with pytest.raises(ParseError):
            parser.parse_line("invalid package name with spaces", 1)

    def test_invalid_version_specifier(self, parser: RequirementsParser):
        """Test invalid version specifier."""
        with pytest.raises(ParseError):
            parser.parse_line("package===", 1)

    def test_malformed_extras(self, parser: RequirementsParser):
        """Test malformed extras syntax."""
        with pytest.raises(ParseError):
            parser.parse_line("package[extra", 1)

    def test_malformed_marker(self, parser: RequirementsParser):
        """Test malformed environment marker."""
        with pytest.raises(ParseError):
            parser.parse_line("package; python_version", 1)


class TestConstraintApplication:
    """Tests for constraint application to requirements."""

    def test_apply_constraint_to_unpinned_requirement(self, parser: RequirementsParser):
        """Test that constraints apply to unpinned requirements."""
        # First parse constraint
        parser._constraint_requirements["requests"] = Requirement(
            name="requests",
            specs=[("==", "2.28.0")],
            extras=[],
            markers=None,
            url=None,
            editable=False,
            hashes=[],
            comment=None,
            line_number=1,
            raw_line="requests==2.28.0",
        )

        # Parse unpinned requirement
        req = parser.parse_line("requests", 2)

        assert req is not None
        assert req.name == "requests"
        assert req.specs == [("==", "2.28.0")]

    def test_constraint_does_not_override_pinned(self, parser: RequirementsParser):
        """Test that constraints don't override existing specs."""
        # Set constraint
        parser._constraint_requirements["requests"] = Requirement(
            name="requests",
            specs=[("==", "2.28.0")],
            extras=[],
            markers=None,
            url=None,
            editable=False,
            hashes=[],
            comment=None,
            line_number=1,
            raw_line="requests==2.28.0",
        )

        # Parse pinned requirement
        req = parser.parse_line("requests>=2.25.0", 2)

        assert req is not None
        assert req.name == "requests"
        assert req.specs == [(">=", "2.25.0")]


class TestComplexSpecifications:
    """Tests for complex version specifications and combinations."""

    def test_multiple_operators_with_spaces(self, parser: RequirementsParser):
        """Test multiple operators with various spacing."""
        req = parser.parse_line("package >= 1.0 , < 2.0", 1)

        assert req is not None
        assert req.name == "package"
        assert len(req.specs) == 2

    def test_extras_with_markers(self, parser: RequirementsParser):
        """Test package with both extras and markers."""
        req = parser.parse_line('celery[redis,msgpack]>=5.0; python_version>="3.8"', 1)

        assert req is not None
        assert req.name == "celery"
        assert "redis" in req.extras
        assert "msgpack" in req.extras
        assert req.markers is not None
        assert "python_version" in req.markers

    def test_extras_with_version_and_hash(self, parser: RequirementsParser):
        """Test package with extras, version, and hash."""
        req = parser.parse_line("package[extra1,extra2]==1.0 --hash=sha256:abc123", 1)

        assert req is not None
        assert req.name == "package"
        assert len(req.extras) == 2
        assert req.specs == [("==", "1.0")]
        assert len(req.hashes) == 1

    def test_editable_url_with_hash_and_comment(self, parser: RequirementsParser):
        """Test editable URL with hash and comment."""
        req = parser.parse_line(
            "-e git+https://github.com/user/repo.git#egg=package --hash=sha256:abc # Dev version",
            1,
        )

        assert req is not None
        assert req.name == "package"
        assert req.editable is True
        assert len(req.hashes) == 1
        assert req.comment == "Dev version"


class TestRawLinePreservation:
    """Tests for raw line preservation."""

    def test_raw_line_preserved(self, parser: RequirementsParser):
        """Test that original line is preserved."""
        original = "requests==2.28.0  # HTTP library"
        req = parser.parse_line(original, 1)

        assert req is not None
        assert req.raw_line == original

    def test_line_number_preserved(self, parser: RequirementsParser):
        """Test that line number is preserved."""
        req = parser.parse_line("django>=3.2", 42)

        assert req is not None
        assert req.line_number == 42


class TestParseFile:
    """Tests for parse_file method."""

    @pytest.fixture
    def fixtures_dir(self) -> Path:
        """Get the fixtures directory path."""
        return Path(__file__).parent.parent.parent / "fixtures"

    def test_parse_simple_requirements(
        self, parser: RequirementsParser, fixtures_dir: Path
    ):
        """Test parsing a simple requirements file."""
        requirements = parser.parse_file(fixtures_dir / "simple_requirements.txt")

        assert len(requirements) == 4
        assert requirements[0].name == "requests"
        assert requirements[1].name == "django"
        assert requirements[2].name == "flask"
        assert requirements[3].name == "numpy"

    def test_parse_requirements_with_extras(
        self, parser: RequirementsParser, fixtures_dir: Path
    ):
        """Test parsing requirements with extras."""
        requirements = parser.parse_file(fixtures_dir / "requirements_with_extras.txt")

        assert len(requirements) == 3
        assert "redis" in requirements[0].extras
        assert "msgpack" in requirements[0].extras
        assert "security" in requirements[1].extras
        assert "argon2" in requirements[2].extras
        assert "bcrypt" in requirements[2].extras

    def test_parse_requirements_with_markers(
        self, parser: RequirementsParser, fixtures_dir: Path
    ):
        """Test parsing requirements with environment markers."""
        requirements = parser.parse_file(fixtures_dir / "requirements_with_markers.txt")

        assert len(requirements) == 3
        assert requirements[0].markers is not None
        assert "python_version" in requirements[0].markers
        assert requirements[1].markers is not None
        assert "sys_platform" in requirements[1].markers
        assert requirements[2].markers is not None

    def test_parse_requirements_with_urls(
        self, parser: RequirementsParser, fixtures_dir: Path
    ):
        """Test parsing requirements with direct URLs."""
        requirements = parser.parse_file(fixtures_dir / "requirements_with_urls.txt")

        assert len(requirements) == 3
        assert requirements[0].name == "mypackage"
        assert requirements[0].url.startswith("git+https://")
        assert requirements[1].name == "devpackage"
        assert "@develop" in requirements[1].url
        assert requirements[2].name == "zippackage"

    def test_parse_requirements_with_hashes(
        self, parser: RequirementsParser, fixtures_dir: Path
    ):
        """Test parsing requirements with hash values."""
        requirements = parser.parse_file(fixtures_dir / "requirements_with_hashes.txt")

        assert len(requirements) == 3
        assert len(requirements[0].hashes) == 1
        assert "sha256:abc123def456" in requirements[0].hashes
        assert len(requirements[1].hashes) == 2
        assert len(requirements[2].hashes) == 1

    def test_parse_requirements_with_comments(
        self, parser: RequirementsParser, fixtures_dir: Path
    ):
        """Test parsing requirements with comments."""
        requirements = parser.parse_file(
            fixtures_dir / "requirements_with_comments.txt"
        )

        assert len(requirements) == 3
        assert requirements[0].comment == "Latest LTS version"
        assert requirements[1].comment == "Pinned for stability"
        assert requirements[2].comment == "Test runner"

    def test_parse_empty_requirements(
        self, parser: RequirementsParser, fixtures_dir: Path
    ):
        """Test parsing empty requirements file."""
        requirements = parser.parse_file(fixtures_dir / "empty_requirements.txt")

        assert len(requirements) == 0

    def test_parse_file_not_found(self, parser: RequirementsParser):
        """Test parsing non-existent file raises FileOperationError."""
        with pytest.raises(FileOperationError) as exc_info:
            parser.parse_file("nonexistent_file.txt")

        assert "not found" in str(exc_info.value).lower()

    def test_parse_file_with_string_path(
        self, parser: RequirementsParser, fixtures_dir: Path
    ):
        """Test parsing file with string path instead of Path object."""
        requirements = parser.parse_file(str(fixtures_dir / "simple_requirements.txt"))

        assert len(requirements) == 4

    def test_parse_mixed_requirements(
        self, parser: RequirementsParser, fixtures_dir: Path
    ):
        """Test parsing file with mixed requirement types."""
        requirements = parser.parse_file(fixtures_dir / "mixed_requirements.txt")

        # Should have multiple different types
        has_standard = any(req.specs and not req.url for req in requirements)
        has_extras = any(req.extras for req in requirements)
        has_markers = any(req.markers for req in requirements)
        has_urls = any(req.url for req in requirements)
        has_hashes = any(req.hashes for req in requirements)
        has_editable = any(req.editable for req in requirements)

        assert has_standard
        assert has_extras
        assert has_markers
        assert has_urls
        assert has_hashes
        assert has_editable


class TestParseFileWithIncludes:
    """Tests for parse_file with -r include directives."""

    @pytest.fixture
    def fixtures_dir(self) -> Path:
        """Get the fixtures directory path."""
        return Path(__file__).parent.parent.parent / "fixtures"

    def test_parse_with_single_include(
        self, parser: RequirementsParser, fixtures_dir: Path
    ):
        """Test parsing file with single include directive."""
        requirements = parser.parse_file(fixtures_dir / "requirements_with_include.txt")

        # Should have base requirements plus additional ones
        req_names = [req.name for req in requirements]
        assert "requests" in req_names  # From base
        assert "django" in req_names  # From base
        assert "flask" in req_names  # From main
        assert "celery" in req_names  # From main

    def test_parse_nested_includes(
        self, parser: RequirementsParser, fixtures_dir: Path
    ):
        """Test parsing file with nested include directives."""
        requirements = parser.parse_file(fixtures_dir / "nested_top.txt")

        req_names = [req.name for req in requirements]
        assert "requests" in req_names  # From nested_base
        assert "django" in req_names  # From nested_middle
        assert "flask" in req_names  # From nested_top

    def test_circular_dependency_detection(
        self, parser: RequirementsParser, fixtures_dir: Path
    ):
        """Test that circular dependencies are detected."""
        with pytest.raises(ParseError) as exc_info:
            parser.parse_file(fixtures_dir / "circular_a.txt")

        assert "circular" in str(exc_info.value).lower()


class TestParseFileWithConstraints:
    """Tests for parse_file with -c constraint directives."""

    @pytest.fixture
    def fixtures_dir(self) -> Path:
        """Get the fixtures directory path."""
        return Path(__file__).parent.parent.parent / "fixtures"

    def test_parse_with_constraints(
        self, parser: RequirementsParser, fixtures_dir: Path
    ):
        """Test parsing file with constraint directive."""
        requirements = parser.parse_file(
            fixtures_dir / "requirements_with_constraints.txt"
        )

        # Find requirements by name
        requests_req = next(r for r in requirements if r.name == "requests")
        django_req = next(r for r in requirements if r.name == "django")
        flask_req = next(r for r in requirements if r.name == "flask")

        # Constraints should be applied to unpinned requirements
        assert requests_req.specs == [("==", "2.28.0")]
        assert django_req.specs == [("==", "4.0")]
        # Flask already has specs, so constraint shouldn't override
        assert flask_req.specs == [("==", "2.0.1")]

    def test_constraint_file_parsing(
        self, parser: RequirementsParser, fixtures_dir: Path
    ):
        """Test parsing a constraint file directly."""
        requirements = parser.parse_file(
            fixtures_dir / "constraints.txt", is_constraint_file=True
        )

        # Constraint files should return empty list
        assert len(requirements) == 0
        # But constraints should be stored internally
        assert len(parser.get_constraints()) == 3
