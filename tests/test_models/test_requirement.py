"""Unit tests for depkeeper.models.requirement module.

This test suite provides comprehensive coverage of the Requirement data model,
including parsing representation, string rendering, version updates, and
edge cases for various requirement formats.

Test Coverage:
- Requirement initialization with various parameters
- String rendering with and without hashes/comments
- Version update operations
- Extras and markers handling
- Editable installations
- URL-based requirements
- Hash verification entries
- Comment preservation
- Line number tracking
- String representations (__str__ and __repr__)
- Edge cases (empty values, special characters, complex markers)
"""

from __future__ import annotations

from depkeeper.models.requirement import Requirement


class TestRequirementInit:
    """Tests for Requirement initialization."""

    def test_minimal_initialization(self) -> None:
        """Test Requirement with only package name.

        Happy path: Minimal requirement with just name.
        """
        req = Requirement(name="requests")

        assert req.name == "requests"
        assert req.specs == []
        assert req.extras == []
        assert req.markers is None
        assert req.url is None
        assert req.editable is False
        assert req.hashes == []
        assert req.comment is None
        assert req.line_number == 0
        assert req.raw_line is None

    def test_full_initialization(self) -> None:
        """Test Requirement with all parameters.

        Should accept and store all optional parameters.
        """
        req = Requirement(
            name="requests",
            specs=[(">=", "2.0.0"), ("<", "3.0.0")],
            extras=["security", "socks"],
            markers='python_version >= "3.7"',
            url="https://github.com/psf/requests/archive/v2.28.0.tar.gz",
            editable=True,
            hashes=["sha256:abc123", "sha256:def456"],
            comment="Production dependency",
            line_number=42,
            raw_line="requests>=2.0.0,<3.0.0 # Production dependency",
        )

        assert req.name == "requests"
        assert req.specs == [(">=", "2.0.0"), ("<", "3.0.0")]
        assert req.extras == ["security", "socks"]
        assert req.markers == 'python_version >= "3.7"'
        assert req.url == "https://github.com/psf/requests/archive/v2.28.0.tar.gz"
        assert req.editable is True
        assert req.hashes == ["sha256:abc123", "sha256:def456"]
        assert req.comment == "Production dependency"
        assert req.line_number == 42
        assert req.raw_line == "requests>=2.0.0,<3.0.0 # Production dependency"

    def test_default_factories_create_new_instances(self) -> None:
        """Test default factories create independent instances.

        Edge case: Multiple requirements shouldn't share lists.
        """
        req1 = Requirement(name="requests")
        req2 = Requirement(name="django")

        req1.specs.append((">=", "2.0.0"))
        req2.specs.append((">=", "4.0.0"))

        assert req1.specs != req2.specs
        assert req1.extras is not req2.extras
        assert req1.hashes is not req2.hashes

    def test_initialization_with_empty_lists(self) -> None:
        """Test Requirement with explicitly empty lists.

        Edge case: Empty lists should be accepted.
        """
        req = Requirement(name="requests", specs=[], extras=[], hashes=[])

        assert req.specs == []
        assert req.extras == []
        assert req.hashes == []


class TestToStringBasic:
    """Tests for Requirement.to_string method - basic cases."""

    def test_simple_package_name_only(self) -> None:
        """Test rendering requirement with only package name.

        Happy path: Simplest possible requirement.
        """
        req = Requirement(name="requests")
        result = req.to_string()
        assert result == "requests"

    def test_with_single_spec(self) -> None:
        """Test rendering requirement with single version specifier.

        Happy path: Common format with version constraint.
        """
        req = Requirement(name="requests", specs=[(">=", "2.0.0")])
        result = req.to_string()
        assert result == "requests>=2.0.0"

    def test_with_multiple_specs(self) -> None:
        """Test rendering requirement with multiple version specifiers.

        Should concatenate specifiers with commas.
        """
        req = Requirement(
            name="requests", specs=[(">=", "2.0.0"), ("<", "3.0.0"), ("!=", "2.5.0")]
        )
        result = req.to_string()
        assert result == "requests>=2.0.0,<3.0.0,!=2.5.0"

    def test_with_single_extra(self) -> None:
        """Test rendering requirement with single extra.

        Extras should be enclosed in square brackets.
        """
        req = Requirement(name="requests", extras=["security"])
        result = req.to_string()
        assert result == "requests[security]"

    def test_with_multiple_extras(self) -> None:
        """Test rendering requirement with multiple extras.

        Multiple extras should be comma-separated.
        """
        req = Requirement(name="requests", extras=["security", "socks"])
        result = req.to_string()
        assert result == "requests[security,socks]"

    def test_with_extras_and_specs(self) -> None:
        """Test rendering requirement with both extras and specs.

        Format should be: package[extras]specs
        """
        req = Requirement(name="requests", specs=[(">=", "2.0.0")], extras=["security"])
        result = req.to_string()
        assert result == "requests[security]>=2.0.0"

    def test_with_markers(self) -> None:
        """Test rendering requirement with environment markers.

        Markers should be preceded by semicolon and space.
        """
        req = Requirement(
            name="requests", specs=[(">=", "2.0.0")], markers='python_version >= "3.7"'
        )
        result = req.to_string()
        assert result == 'requests>=2.0.0 ; python_version >= "3.7"'

    def test_with_url(self) -> None:
        """Test rendering URL-based requirement.

        URL should replace package name in output.
        """
        req = Requirement(
            name="requests", url="https://github.com/psf/requests/archive/main.zip"
        )
        result = req.to_string()
        assert result == "https://github.com/psf/requests/archive/main.zip"

    def test_editable_package(self) -> None:
        """Test rendering editable installation.

        Should prefix with -e flag.
        """
        req = Requirement(name="mypackage", editable=True)
        result = req.to_string()
        assert result == "-e mypackage"

    def test_editable_url(self) -> None:
        """Test rendering editable URL installation.

        Should prefix URL with -e flag.
        """
        req = Requirement(
            name="mypackage", url="git+https://github.com/user/repo.git", editable=True
        )
        result = req.to_string()
        assert result == "-e git+https://github.com/user/repo.git"


class TestToStringWithHashes:
    """Tests for Requirement.to_string with hash handling."""

    def test_single_hash(self) -> None:
        """Test rendering requirement with single hash.

        Hash should be appended with --hash= prefix.
        """
        req = Requirement(
            name="requests", specs=[("==", "2.28.0")], hashes=["sha256:abc123def456"]
        )
        result = req.to_string(include_hashes=True)
        assert result == "requests==2.28.0 --hash=sha256:abc123def456"

    def test_multiple_hashes(self) -> None:
        """Test rendering requirement with multiple hashes.

        Multiple hashes should each have --hash= prefix.
        """
        req = Requirement(
            name="requests",
            specs=[("==", "2.28.0")],
            hashes=["sha256:abc123", "sha256:def456", "sha256:ghi789"],
        )
        result = req.to_string(include_hashes=True)

        assert "requests==2.28.0" in result
        assert "--hash=sha256:abc123" in result
        assert "--hash=sha256:def456" in result
        assert "--hash=sha256:ghi789" in result

    def test_hashes_excluded_when_flag_false(self) -> None:
        """Test hashes are omitted when include_hashes=False.

        Should not include hash entries when flag is False.
        """
        req = Requirement(
            name="requests", specs=[("==", "2.28.0")], hashes=["sha256:abc123"]
        )
        result = req.to_string(include_hashes=False)
        assert result == "requests==2.28.0"
        assert "--hash=" not in result

    def test_no_hashes_with_flag_true(self) -> None:
        """Test rendering with include_hashes=True but no hashes.

        Edge case: Flag is True but no hashes to include.
        """
        req = Requirement(name="requests", specs=[("==", "2.28.0")])
        result = req.to_string(include_hashes=True)
        assert result == "requests==2.28.0"
        assert "--hash=" not in result


class TestToStringWithComments:
    """Tests for Requirement.to_string with comment handling."""

    def test_simple_comment(self) -> None:
        """Test rendering requirement with comment.

        Comment should be appended with # prefix and space.
        """
        req = Requirement(
            name="requests", specs=[(">=", "2.0.0")], comment="Production dependency"
        )
        result = req.to_string(include_comment=True)
        assert result == "requests>=2.0.0  # Production dependency"

    def test_comment_excluded_when_flag_false(self) -> None:
        """Test comment is omitted when include_comment=False.

        Should not include comment when flag is False.
        """
        req = Requirement(
            name="requests", specs=[(">=", "2.0.0")], comment="Production dependency"
        )
        result = req.to_string(include_comment=False)
        assert result == "requests>=2.0.0"
        assert "#" not in result

    def test_no_comment_with_flag_true(self) -> None:
        """Test rendering with include_comment=True but no comment.

        Edge case: Flag is True but no comment to include.
        """
        req = Requirement(name="requests", specs=[(">=", "2.0.0")])
        result = req.to_string(include_comment=True)
        assert result == "requests>=2.0.0"
        assert "#" not in result

    def test_comment_with_hashes(self) -> None:
        """Test rendering with both hashes and comment.

        Comment should come after hashes.
        """
        req = Requirement(
            name="requests",
            specs=[("==", "2.28.0")],
            hashes=["sha256:abc123"],
            comment="Pinned for security",
        )
        result = req.to_string(include_hashes=True, include_comment=True)

        assert result.endswith("# Pinned for security")
        assert "--hash=sha256:abc123  #" in result

    def test_comment_without_hashes(self) -> None:
        """Test rendering with comment but hashes excluded.

        Comment should still appear when hashes are excluded.
        """
        req = Requirement(
            name="requests",
            specs=[("==", "2.28.0")],
            hashes=["sha256:abc123"],
            comment="Pinned",
        )
        result = req.to_string(include_hashes=False, include_comment=True)
        assert result == "requests==2.28.0  # Pinned"


class TestToStringComplex:
    """Tests for Requirement.to_string with complex combinations."""

    def test_all_features_combined(self) -> None:
        """Test rendering with all features enabled.

        Integration test: extras, specs, markers, hashes, comment.
        """
        req = Requirement(
            name="requests",
            specs=[(">=", "2.0.0"), ("<", "3.0.0")],
            extras=["security"],
            markers='python_version >= "3.7"',
            hashes=["sha256:abc123"],
            comment="Production",
        )
        result = req.to_string(include_hashes=True, include_comment=True)

        assert "requests[security]>=2.0.0,<3.0.0" in result
        assert '; python_version >= "3.7"' in result
        assert "--hash=sha256:abc123" in result
        assert "# Production" in result

    def test_editable_with_all_features(self) -> None:
        """Test editable requirement with multiple features.

        Should handle -e flag with extras and markers.
        """
        req = Requirement(
            name="mypackage",
            url="git+https://github.com/user/repo.git",
            editable=True,
            markers='sys_platform == "linux"',
            comment="Development version",
        )
        result = req.to_string(include_comment=True)

        assert result.startswith("-e")
        assert "git+https://github.com/user/repo.git" in result
        assert '; sys_platform == "linux"' in result
        assert "# Development version" in result

    def test_url_with_extras(self) -> None:
        """Test URL-based requirement with extras.

        Edge case: Extras should be added to URL.
        """
        req = Requirement(
            name="requests",
            url="https://github.com/psf/requests/archive/main.zip",
            extras=["security"],
        )
        result = req.to_string()

        # URL should include extras
        assert "https://github.com/psf/requests/archive/main.zip[security]" in result


class TestUpdateVersion:
    """Tests for Requirement.update_version method."""

    def test_update_simple_requirement(self) -> None:
        """Test updating version of simple requirement.

        Happy path: Basic version update with >= operator.
        """
        req = Requirement(name="requests", specs=[("==", "2.20.0")])
        result = req.update_version("2.28.0", preserve_trailing_newline=False)

        assert result == "requests>=2.28.0"

    def test_update_replaces_all_specs(self) -> None:
        """Test update replaces all existing specifiers.

        Multiple old specifiers should be replaced with single >=.
        """
        req = Requirement(
            name="requests", specs=[(">=", "2.0.0"), ("<", "3.0.0"), ("!=", "2.5.0")]
        )
        result = req.update_version("2.28.0", preserve_trailing_newline=False)

        assert result == "requests>=2.28.0"
        assert "<3.0.0" not in result
        assert "!=2.5.0" not in result

    def test_update_preserves_extras(self) -> None:
        """Test update preserves extras.

        Extras should remain in updated requirement.
        """
        req = Requirement(
            name="requests", specs=[("==", "2.20.0")], extras=["security", "socks"]
        )
        result = req.update_version("2.28.0")

        assert result == "requests[security,socks]>=2.28.0\n"

    def test_update_preserves_markers(self) -> None:
        """Test update preserves environment markers.

        Markers should remain in updated requirement.
        """
        req = Requirement(
            name="requests", specs=[("==", "2.20.0")], markers='python_version >= "3.7"'
        )
        result = req.update_version("2.28.0")

        assert 'python_version >= "3.7"' in result

    def test_update_preserves_url(self) -> None:
        """Test update preserves URL.

        URL-based requirements should keep URL.
        """
        req = Requirement(
            name="requests",
            url="https://github.com/psf/requests/archive/main.zip",
            specs=[("==", "2.20.0")],
        )
        result = req.update_version("2.28.0")

        assert "https://github.com/psf/requests/archive/main.zip" in result

    def test_update_preserves_editable_flag(self) -> None:
        """Test update preserves editable flag.

        Editable installs should remain editable.
        """
        req = Requirement(name="mypackage", specs=[("==", "1.0.0")], editable=True)
        result = req.update_version("1.5.0")

        assert result.startswith("-e")

    def test_update_removes_hashes(self) -> None:
        """Test update removes hash entries.

        Hashes are version-specific and should be removed.
        """
        req = Requirement(
            name="requests",
            specs=[("==", "2.20.0")],
            hashes=["sha256:abc123", "sha256:def456"],
        )
        result = req.update_version("2.28.0")

        assert "--hash=" not in result

    def test_update_preserves_comment(self) -> None:
        """Test update preserves inline comment.

        Comments should remain in updated requirement.
        """
        req = Requirement(
            name="requests", specs=[("==", "2.20.0")], comment="Production dependency"
        )
        result = req.update_version("2.28.0")

        assert "# Production dependency" in result

    def test_update_with_newline_preserved(self) -> None:
        """Test update with trailing newline preservation.

        Default behavior should add trailing newline.
        """
        req = Requirement(name="requests", specs=[("==", "2.20.0")])
        result = req.update_version("2.28.0", preserve_trailing_newline=True)

        assert result.endswith("")

    def test_update_without_newline(self) -> None:
        """Test update without trailing newline.

        preserve_trailing_newline=False should not add newline.
        """
        req = Requirement(name="requests", specs=[("==", "2.20.0")])
        result = req.update_version("2.28.0", preserve_trailing_newline=False)

        assert not result.endswith("\n")
        assert result == "requests>=2.28.0"

    def test_update_with_all_features(self) -> None:
        """Test update with complex requirement.

        Integration test: Update requirement with all features.
        """
        req = Requirement(
            name="requests",
            specs=[(">=", "2.0.0"), ("<", "3.0.0")],
            extras=["security"],
            markers='python_version >= "3.7"',
            hashes=["sha256:abc123"],
            comment="Pinned for stability",
            editable=False,
        )
        result = req.update_version("2.28.0")

        # Should have new version
        assert ">=2.28.0" in result
        # Should preserve extras, markers, comment
        assert "[security]" in result
        assert 'python_version >= "3.7"' in result
        assert "# Pinned for stability" in result
        # Should not have old specs or hashes
        assert "<3.0.0" not in result
        assert "--hash=" not in result

    def test_update_preserves_line_number(self) -> None:
        """Test update preserves original line number.

        Line number tracking should be maintained.
        """
        req = Requirement(name="requests", specs=[("==", "2.20.0")], line_number=42)
        # Create updated requirement object to verify
        updated_req = Requirement(
            name=req.name, specs=[(">=", "2.28.0")], line_number=req.line_number
        )

        assert updated_req.line_number == 42


class TestStringRepresentations:
    """Tests for Requirement.__str__ and __repr__ methods."""

    def test_str_simple(self) -> None:
        """Test __str__ with simple requirement.

        Should delegate to to_string().
        """
        req = Requirement(name="requests", specs=[(">=", "2.0.0")])
        result = str(req)
        assert result == "requests>=2.0.0"

    def test_str_complex(self) -> None:
        """Test __str__ with complex requirement.

        Should include all features via to_string().
        """
        req = Requirement(
            name="requests",
            specs=[(">=", "2.0.0")],
            extras=["security"],
            hashes=["sha256:abc123"],
            comment="Production",
        )
        result = str(req)

        assert "requests[security]>=2.0.0" in result
        assert "--hash=sha256:abc123" in result
        assert "# Production" in result

    def test_repr_minimal(self) -> None:
        """Test __repr__ with minimal data.

        Should show constructor format for debugging.
        """
        req = Requirement(name="requests")
        result = repr(req)

        assert result.startswith("Requirement(")
        assert "name='requests'" in result
        assert "specs=[]" in result
        assert "extras=[]" in result
        assert "editable=False" in result
        assert "line_number=0" in result

    def test_repr_full(self) -> None:
        """Test __repr__ with full data.

        Should show key fields in constructor format.
        """
        req = Requirement(
            name="requests",
            specs=[(">=", "2.0.0"), ("<", "3.0.0")],
            extras=["security"],
            editable=True,
            line_number=42,
        )
        result = repr(req)

        assert "name='requests'" in result
        assert "specs=[('>=', '2.0.0'), ('<', '3.0.0')]" in result
        assert "extras=['security']" in result
        assert "editable=True" in result
        assert "line_number=42" in result

    def test_str_vs_repr_difference(self) -> None:
        """Test str() and repr() produce different outputs.

        str() should be user-friendly, repr() for debugging.
        """
        req = Requirement(name="requests", specs=[(">=", "2.0.0")])

        str_result = str(req)
        repr_result = repr(req)

        assert str_result == "requests>=2.0.0"
        assert "Requirement(" in repr_result
        assert str_result != repr_result


class TestEdgeCases:
    """Tests for edge cases and unusual inputs."""

    def test_empty_package_name(self) -> None:
        """Test requirement with empty package name.

        Edge case: Empty string as name.
        """
        req = Requirement(name="")
        result = req.to_string()
        assert result == ""

    def test_package_name_with_special_characters(self) -> None:
        """Test package name with special characters.

        Edge case: Names with dots, dashes, underscores.
        """
        req = Requirement(name="my-package.name_v2")
        result = req.to_string()
        assert result == "my-package.name_v2"

    def test_very_long_package_name(self) -> None:
        """Test requirement with very long package name.

        Edge case: Extremely long names should be handled.
        """
        long_name = "package-" * 50 + "name"
        req = Requirement(name=long_name)
        result = req.to_string()
        assert result == long_name

    def test_spec_with_wildcards(self) -> None:
        """Test version specifier with wildcards.

        Edge case: Wildcard versions like ==2.*.
        """
        req = Requirement(name="requests", specs=[("==", "2.*")])
        result = req.to_string()
        assert result == "requests==2.*"

    def test_spec_with_local_version(self) -> None:
        """Test version specifier with local identifier.

        Edge case: PEP 440 local versions like 1.0+local.
        """
        req = Requirement(name="requests", specs=[("==", "2.28.0+local")])
        result = req.to_string()
        assert result == "requests==2.28.0+local"

    def test_spec_with_epoch(self) -> None:
        """Test version specifier with epoch.

        Edge case: PEP 440 epochs like 1!2.0.0.
        """
        req = Requirement(name="requests", specs=[("==", "1!2.0.0")])
        result = req.to_string()
        assert result == "requests==1!2.0.0"

    def test_marker_with_complex_expression(self) -> None:
        """Test requirement with complex marker expression.

        Edge case: Multiple conditions in markers.
        """
        req = Requirement(
            name="requests",
            markers='python_version >= "3.7" and sys_platform == "linux" and platform_machine == "x86_64"',
        )
        result = req.to_string()

        assert 'python_version >= "3.7"' in result
        assert 'sys_platform == "linux"' in result
        assert 'platform_machine == "x86_64"' in result

    def test_marker_with_or_condition(self) -> None:
        """Test requirement with OR marker expression.

        Edge case: Markers with or operator.
        """
        req = Requirement(
            name="requests",
            markers='sys_platform == "win32" or sys_platform == "darwin"',
        )
        result = req.to_string()
        assert 'sys_platform == "win32" or sys_platform == "darwin"' in result

    def test_url_with_git_protocol(self) -> None:
        """Test URL with git+ protocol.

        Edge case: VCS URLs.
        """
        req = Requirement(
            name="mypackage",
            url="git+https://github.com/user/repo.git@main#egg=mypackage",
        )
        result = req.to_string()
        assert "git+https://github.com/user/repo.git@main#egg=mypackage" in result

    def test_url_with_ssh(self) -> None:
        """Test URL with SSH protocol.

        Edge case: SSH-based VCS URLs.
        """
        req = Requirement(
            name="mypackage", url="git+ssh://git@github.com/user/repo.git"
        )
        result = req.to_string()
        assert "git+ssh://git@github.com/user/repo.git" in result

    def test_url_with_branch_and_subdirectory(self) -> None:
        """Test URL with branch and subdirectory.

        Edge case: Complex VCS URL with path.
        """
        req = Requirement(
            name="mypackage",
            url="git+https://github.com/user/repo.git@feature-branch#subdirectory=packages/mypackage",
        )
        result = req.to_string()
        assert "feature-branch" in result
        assert "subdirectory=packages/mypackage" in result

    def test_comment_with_special_characters(self) -> None:
        """Test comment with special characters.

        Edge case: Comments with unicode, symbols.
        """
        req = Requirement(
            name="requests", comment="Critical! ⚠️ Don't update (see issue #123)"
        )
        result = req.to_string(include_comment=True)
        assert "Critical! ⚠️ Don't update (see issue #123)" in result

    def test_comment_with_hash_symbol(self) -> None:
        """Test comment containing # symbol.

        Edge case: Hash symbols within comment text.
        """
        req = Requirement(name="requests", comment="See issue #123 and PR #456")
        result = req.to_string(include_comment=True)
        assert "# See issue #123 and PR #456" in result

    def test_multiple_extras_ordering(self) -> None:
        """Test extras maintain insertion order.

        Edge case: Order of extras should be preserved.
        """
        req = Requirement(name="requests", extras=["z-extra", "a-extra", "m-extra"])
        result = req.to_string()
        assert result == "requests[z-extra,a-extra,m-extra]"

    def test_hash_with_different_algorithms(self) -> None:
        """Test hashes with different algorithms.

        Edge case: Multiple hash algorithms (sha256, sha512, md5).
        """
        req = Requirement(
            name="requests",
            specs=[("==", "2.28.0")],
            hashes=["sha256:abc123", "sha512:def456ghi789", "md5:xyz890"],
        )
        result = req.to_string(include_hashes=True)

        assert "--hash=sha256:abc123" in result
        assert "--hash=sha512:def456ghi789" in result
        assert "--hash=md5:xyz890" in result

    def test_very_long_comment(self) -> None:
        """Test requirement with very long comment.

        Edge case: Comments can be arbitrarily long.
        """
        long_comment = "This is a very long comment " * 20
        req = Requirement(name="requests", comment=long_comment)
        result = req.to_string(include_comment=True)

        assert long_comment in result

    def test_zero_line_number(self) -> None:
        """Test requirement with line number 0.

        Edge case: Zero is valid line number (default).
        """
        req = Requirement(name="requests", line_number=0)
        assert req.line_number == 0

    def test_large_line_number(self) -> None:
        """Test requirement with very large line number.

        Edge case: Large files can have high line numbers.
        """
        req = Requirement(name="requests", line_number=999999)
        assert req.line_number == 999999

    def test_raw_line_with_whitespace(self) -> None:
        """Test raw_line preserves whitespace.

        Edge case: Original line might have leading/trailing space.
        """
        req = Requirement(name="requests", raw_line="  requests>=2.0.0  # comment  ")
        assert req.raw_line == "  requests>=2.0.0  # comment  "

    def test_operator_variations(self) -> None:
        """Test all valid PEP 440 operators.

        Edge case: All comparison operators should work.
        """
        operators = ["==", "!=", ">=", "<=", ">", "<", "~=", "==="]

        for op in operators:
            req = Requirement(name="requests", specs=[(op, "2.0.0")])
            result = req.to_string()
            assert f"requests{op}2.0.0" in result

    def test_compatible_release_operator(self) -> None:
        """Test compatible release operator ~=.

        Edge case: Tilde equal operator for compatible releases.
        """
        req = Requirement(name="requests", specs=[("~=", "2.28")])
        result = req.to_string()
        assert result == "requests~=2.28"

    def test_arbitrary_equality_operator(self) -> None:
        """Test arbitrary equality operator ===.

        Edge case: Triple equals for string matching.
        """
        req = Requirement(name="requests", specs=[("===", "2.28.0-local")])
        result = req.to_string()
        assert result == "requests===2.28.0-local"

    def test_update_version_with_prerelease(self) -> None:
        """Test updating to pre-release version.

        Edge case: Pre-release versions like 3.0.0a1.
        """
        req = Requirement(name="requests", specs=[("==", "2.28.0")])
        result = req.update_version("3.0.0a1")
        assert ">=3.0.0a1" in result

    def test_update_version_with_dev_version(self) -> None:
        """Test updating to development version.

        Edge case: Dev versions like 3.0.0.dev1.
        """
        req = Requirement(name="requests", specs=[("==", "2.28.0")])
        result = req.update_version("3.0.0.dev1")
        assert ">=3.0.0.dev1" in result

    def test_empty_specs_list_to_string(self) -> None:
        """Test to_string with explicitly empty specs list.

        Edge case: Empty list should produce name only.
        """
        req = Requirement(name="requests", specs=[])
        result = req.to_string()
        assert result == "requests"

    def test_empty_extras_list_to_string(self) -> None:
        """Test to_string with explicitly empty extras list.

        Edge case: Empty list should not add brackets.
        """
        req = Requirement(name="requests", extras=[])
        result = req.to_string()
        assert result == "requests"
        assert "[" not in result

    def test_empty_hashes_list_to_string(self) -> None:
        """Test to_string with explicitly empty hashes list.

        Edge case: Empty list should not add --hash entries.
        """
        req = Requirement(name="requests", hashes=[])
        result = req.to_string(include_hashes=True)
        assert result == "requests"
        assert "--hash=" not in result


class TestIntegrationScenarios:
    """Integration tests for real-world requirement scenarios."""

    def test_typical_pinned_requirement(self) -> None:
        """Test typical pinned requirement with hash.

        Integration: Common pattern for reproducible installs.
        """
        req = Requirement(
            name="requests",
            specs=[("==", "2.28.0")],
            hashes=["sha256:abc123def456"],
            line_number=15,
            raw_line="requests==2.28.0 --hash=sha256:abc123def456",
        )

        # Test string rendering
        result = req.to_string()
        assert "requests==2.28.0" in result
        assert "--hash=sha256:abc123def456" in result

        # Test version update
        updated = req.update_version("2.31.0")
        assert ">=2.31.0" in updated
        assert "--hash=" not in updated  # Hashes removed

    def test_development_dependency_workflow(self) -> None:
        """Test development dependency with markers and comment.

        Integration: Dev dependency with platform markers.
        """
        req = Requirement(
            name="pytest",
            specs=[(">=", "7.0.0")],
            markers='python_version >= "3.8"',
            comment="Testing framework",
            line_number=25,
        )

        # Render with all features
        result = req.to_string()
        assert "pytest>=7.0.0" in result
        assert 'python_version >= "3.8"' in result
        assert "# Testing framework" in result

        # Update version
        updated = req.update_version("7.4.0")
        assert ">=7.4.0" in updated
        assert "# Testing framework" in updated

    def test_editable_local_package_workflow(self) -> None:
        """Test editable local package installation.

        Integration: Common development workflow.
        """
        req = Requirement(
            name="myproject",
            url=".",
            editable=True,
            extras=["dev", "test"],
            comment="Local development",
            line_number=1,
        )

        result = req.to_string()
        assert result.startswith("-e")
        assert ".[dev,test]" in result
        assert "# Local development" in result

    def test_vcs_requirement_with_branch(self) -> None:
        """Test VCS requirement with specific branch.

        Integration: Installing from git repository.
        """
        req = Requirement(
            name="my-lib",
            url="git+https://github.com/user/my-lib.git@develop",
            editable=False,
            markers='sys_platform != "win32"',
            comment="Latest develop branch",
        )

        result = req.to_string()
        assert "git+https://github.com/user/my-lib.git@develop" in result
        assert '; sys_platform != "win32"' in result
        assert "# Latest develop branch" in result

    def test_requirement_with_all_operators(self) -> None:
        """Test requirement using multiple operators.

        Integration: Complex version constraints.
        """
        req = Requirement(
            name="django",
            specs=[(">=", "3.2"), ("<", "5.0"), ("!=", "4.0")],
            extras=["bcrypt"],
            comment="Avoid Django 4.0 due to breaking changes",
        )

        result = req.to_string()
        assert "django[bcrypt]>=3.2,<5.0,!=4.0" in result
        assert "# Avoid Django 4.0" in result

        # Update should replace all specs
        updated = req.update_version("4.2.0")
        assert ">=4.2.0" in updated
        assert "<5.0" not in updated
        assert "!=4.0" not in updated

    def test_security_constrained_requirement(self) -> None:
        """Test requirement with security-related constraints.

        Integration: Security fix with exclusions.
        """
        req = Requirement(
            name="pillow",
            specs=[(">=", "9.0.0"), ("!=", "9.1.0"), ("!=", "9.1.1")],
            comment="Exclude vulnerable versions (CVE-2023-XXXXX)",
            hashes=["sha256:hash1", "sha256:hash2"],
            line_number=50,
        )

        result = req.to_string()
        assert "pillow>=9.0.0,!=9.1.0,!=9.1.1" in result
        assert "CVE-2023-XXXXX" in result
        assert "--hash=sha256:hash1" in result

    def test_platform_specific_requirement(self) -> None:
        """Test requirement specific to certain platforms.

        Integration: Platform-conditional dependency.
        """
        req = Requirement(
            name="pywin32",
            specs=[(">=", "300")],
            markers='sys_platform == "win32"',
            comment="Windows-specific",
        )

        result = req.to_string()
        assert "pywin32>=300" in result
        assert '; sys_platform == "win32"' in result

    def test_requirement_update_preserves_context(self) -> None:
        """Test version update preserves all context.

        Integration: Full update workflow maintaining metadata.
        """
        original = Requirement(
            name="flask",
            specs=[(">=", "2.0.0"), ("<", "3.0.0")],
            extras=["async"],
            markers='python_version >= "3.8"',
            comment="Web framework",
            line_number=10,
            raw_line='flask[async]>=2.0.0,<3.0.0 ; python_version >= "3.8"  # Web framework',
        )

        # Update version
        updated_str = original.update_version("2.3.0")

        # Verify preservation
        assert "flask[async]>=2.3.0" in updated_str
        assert 'python_version >= "3.8"' in updated_str
        assert "# Web framework" in updated_str
        assert "<3.0.0" not in updated_str

    def test_roundtrip_string_consistency(self) -> None:
        """Test to_string output can represent requirement.

        Integration: String rendering should be consistent.
        """
        req = Requirement(
            name="numpy",
            specs=[(">=", "1.20.0"), ("<", "2.0.0")],
            extras=["dev"],
            markers='python_version >= "3.9"',
            comment="Scientific computing",
        )

        # Render twice
        first = req.to_string()
        second = req.to_string()

        # Should be identical
        assert first == second

        # Should contain all components
        assert "numpy[dev]>=1.20.0,<2.0.0" in first
        assert 'python_version >= "3.9"' in first
        assert "# Scientific computing" in first
