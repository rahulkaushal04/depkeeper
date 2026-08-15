"""End-to-end tests for :class:`~depkeeper.core.parser.RequirementsParser`.

The parser is the front door: every downstream decision is made on what it
produced, and anything it silently drops can never be checked or updated. This
module covers the parser's *whole* surface — line classification, PEP 508
attributes, direct references, include and constraint directives, and failure
modes.

Narrow regression areas live in their own modules so their intent stays legible
and this file does not become the dumping ground:

- ``--hash`` separator forms → ``test_parser_hashes.py``
- pip global options → ``test_parser_global_options.py``
- byte order marks → ``test_parser_bom.py``
- specifier ordering → ``test_parser_spec_order.py``
- ``source_file`` provenance → ``test_parser_provenance.py``

Corpora come from :mod:`tests.support.datasets` so the parser is exercised
against files shaped like the ones real projects check in, rather than
single-line probes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pytest

from depkeeper.core.parser import RequirementsParser
from depkeeper.exceptions import FileOperationError, ParseError
from depkeeper.models import Requirement
from tests.support import datasets


@pytest.fixture
def parser() -> RequirementsParser:
    """A parser with empty include-stack and constraint state."""
    return RequirementsParser()


def _by_name(requirements: List[Requirement]) -> Dict[str, Requirement]:
    """Index parsed requirements by their normalised name."""
    return {req.name: req for req in requirements}


# ---------------------------------------------------------------------------
# Line classification
# ---------------------------------------------------------------------------


class TestLineClassification:
    """Which lines produce a requirement, and which are structure or noise."""

    @pytest.mark.parametrize(
        "line",
        [
            "",
            "   ",
            "\t",
            "# pinned for CVE-2023-30861",
            "   # indented comment",
            "#",
        ],
        ids=["empty", "spaces", "tab", "comment", "indented-comment", "bare-hash"],
    )
    def test_blank_and_comment_lines_produce_nothing(
        self, parser: RequirementsParser, line: str
    ) -> None:
        assert parser.parse_line(line, 1) is None

    def test_line_numbers_are_one_indexed_and_track_the_source(
        self, parser: RequirementsParser
    ) -> None:
        """The update writer rewrites by line number; an off-by-one corrupts
        an unrelated line, which is regression C1's exact failure mode.
        """
        content = "# header\n\nrequests==2.31.0\n# gap\nurllib3==1.26.18\n"

        parsed = _by_name(parser.parse_string(content))

        assert parsed["requests"].line_number == 3
        assert parsed["urllib3"].line_number == 5

    def test_raw_line_is_preserved_verbatim(
        self, parser: RequirementsParser
    ) -> None:
        """Surrounding whitespace is retained so the writer can reproduce it."""
        req = parser.parse_line("   requests == 2.31.0   ", 1)

        assert req is not None
        assert req.raw_line == "   requests == 2.31.0   "

    def test_surrounding_quotes_are_stripped(
        self, parser: RequirementsParser
    ) -> None:
        """Shell-generated files routinely quote whole specs."""
        req = parser.parse_line('"requests>=2.31.0"', 1)

        assert req is not None
        assert req.name == "requests"


class TestInlineComments:
    """A ``#`` is a comment — except inside a URL fragment."""

    def test_inline_comment_is_split_from_the_specifier(
        self, parser: RequirementsParser
    ) -> None:
        req = parser.parse_line("urllib3<2.0  # 2.x drops the retry kwargs", 1)

        assert req is not None
        assert req.specs == [("<", "2.0")]
        assert req.comment == "2.x drops the retry kwargs"

    def test_egg_fragment_is_not_treated_as_a_comment(
        self, parser: RequirementsParser
    ) -> None:
        """``#egg=`` carries the package name; losing it makes the line
        unparseable and the requirement anonymous.
        """
        req = parser.parse_line(
            "git+https://github.com/pallets/flask.git@3.0.3#egg=flask", 1
        )

        assert req is not None
        assert req.name == "flask"
        assert req.comment is None

    def test_a_comment_after_an_egg_fragment_is_still_a_comment(
        self, parser: RequirementsParser
    ) -> None:
        req = parser.parse_line(
            "git+https://github.com/acme/sdk.git#egg=internal-sdk  # vendored", 1
        )

        assert req is not None
        assert req.name == "internal-sdk"
        assert req.comment == "vendored"


# ---------------------------------------------------------------------------
# PEP 508 attributes
# ---------------------------------------------------------------------------


class TestPep508Attributes:
    """Name, specifiers, extras and markers, on realistic lines."""

    def test_bare_name_has_no_constraints(self, parser: RequirementsParser) -> None:
        req = parser.parse_line("urllib3", 1)

        assert req is not None
        assert (req.name, req.specs, req.extras, req.markers) == (
            "urllib3",
            [],
            [],
            None,
        )

    @pytest.mark.parametrize(
        ("declared", "canonical"),
        [
            ("Django==4.2.11", "django"),
            ("zope.interface>=5.4.0", "zope-interface"),
            ("typing_extensions>=4.6.0", "typing-extensions"),
            ("ruamel.yaml.clib>=0.2.8", "ruamel-yaml-clib"),
        ],
        ids=["case", "dot", "underscore", "multi-dot"],
    )
    def test_names_are_normalised_to_pep503(
        self, parser: RequirementsParser, declared: str, canonical: str
    ) -> None:
        """Downstream lookups key on this name; a second spelling is invisible."""
        req = parser.parse_line(declared, 1)

        assert req is not None
        assert req.name == canonical

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("requests==2.31.0", [("==", "2.31.0")]),
            ("flask>=2.2,<3.0", [(">=", "2.2"), ("<", "3.0")]),
            (
                "django>=3.2,<5.0,!=4.0.*",
                [(">=", "3.2"), ("<", "5.0"), ("!=", "4.0.*")],
            ),
            ("sqlalchemy~=2.0", [("~=", "2.0")]),
            ("urllib3!=2.0.0", [("!=", "2.0.0")]),
            ("pandas>2.0.3", [(">", "2.0.3")]),
            ("certifi<=2024.7.4", [("<=", "2024.7.4")]),
        ],
        ids=["pin", "range", "range-exclusion", "compatible", "ne", "gt", "le"],
    )
    def test_specifiers_are_captured_in_declaration_order(
        self, parser: RequirementsParser, line: str, expected: List[tuple]
    ) -> None:
        req = parser.parse_line(line, 1)

        assert req is not None
        assert req.specs == expected

    @pytest.mark.parametrize(
        ("line", "extras"),
        [
            ("celery[redis]>=5.3.4", ["redis"]),
            ("django[argon2,bcrypt]>=4.2", ["argon2", "bcrypt"]),
            ("requests[socks]", ["socks"]),
        ],
        ids=["single", "multiple", "no-specifier"],
    )
    def test_extras_are_captured(
        self, parser: RequirementsParser, line: str, extras: List[str]
    ) -> None:
        req = parser.parse_line(line, 1)

        assert req is not None
        assert sorted(req.extras) == sorted(extras)

    @pytest.mark.parametrize(
        ("line", "marker_fragment"),
        [
            ('typing-extensions>=4.6.0 ; python_version < "3.11"', "python_version"),
            ('pywin32>=306 ; sys_platform == "win32"', "sys_platform"),
            (
                'greenlet>=3.0.3 ; platform_python_implementation == "CPython"',
                "platform_python_implementation",
            ),
            (
                'backports.zoneinfo>=0.2.1 ; python_version < "3.9" and '
                'platform_system == "Linux"',
                "and",
            ),
        ],
        ids=["python-version", "platform", "implementation", "compound"],
    )
    def test_environment_markers_are_captured(
        self, parser: RequirementsParser, line: str, marker_fragment: str
    ) -> None:
        """Markers decide whether a requirement applies at all; dropping one
        makes depkeeper propose updates for a package this environment never
        installs.
        """
        req = parser.parse_line(line, 1)

        assert req is not None
        assert req.markers is not None
        assert marker_fragment in req.markers

    def test_all_attributes_coexist_on_one_line(
        self, parser: RequirementsParser
    ) -> None:
        """The realistic worst case: extras, a range, a marker and a comment."""
        req = parser.parse_line(
            'celery[redis,msgpack]>=5.3.4,<6.0 ; python_version >= "3.8"'
            "  # broker client",
            17,
        )

        assert req is not None
        assert req.name == "celery"
        assert sorted(req.extras) == ["msgpack", "redis"]
        assert req.specs == [(">=", "5.3.4"), ("<", "6.0")]
        assert req.markers is not None and "python_version" in req.markers
        assert req.comment == "broker client"
        assert req.line_number == 17


# ---------------------------------------------------------------------------
# Direct references
# ---------------------------------------------------------------------------


class TestDirectReferences:
    """VCS URLs, archive URLs and local checkouts."""

    @pytest.mark.parametrize(
        ("line", "name"),
        [
            ("git+https://github.com/pallets/flask.git@3.0.3#egg=flask", "flask"),
            ("git+ssh://git@github.com/acme/sdk.git@main#egg=internal-sdk", "internal-sdk"),
            ("hg+https://hg.example.com/proj#egg=proj", "proj"),
            ("svn+https://svn.example.com/trunk#egg=legacy-lib", "legacy-lib"),
            (
                "https://files.pythonhosted.org/packages/x.zip#egg=zippkg",
                "zippkg",
            ),
        ],
        ids=["git-https", "git-ssh", "mercurial", "subversion", "archive"],
    )
    def test_egg_fragment_supplies_the_package_name(
        self, parser: RequirementsParser, line: str, name: str
    ) -> None:
        req = parser.parse_line(line, 1)

        assert req is not None
        assert req.name == name
        assert req.url == line
        assert req.specs == []

    def test_package_name_is_inferred_when_egg_is_missing(
        self, parser: RequirementsParser
    ) -> None:
        """pip dropped ``#egg=`` as a requirement, so real files omit it.

        Refusing the line would break otherwise-valid files; inferring from the
        repository name matches what pip itself displays.
        """
        req = parser.parse_line("git+https://github.com/pallets/flask.git", 1)

        assert req is not None
        assert req.name == "flask"

    def test_an_uninferable_url_is_rejected(self, parser: RequirementsParser) -> None:
        """Better a clear parse error than an anonymous requirement that can
        never be matched against PyPI metadata.
        """
        with pytest.raises(ParseError, match="#egg="):
            parser.parse_line("file://", 1)

    @pytest.mark.parametrize(
        ("line", "expected_name"),
        [
            ("https://example.com/pkg.tar.gz#egg=", "pkg-tar-gz"),
            ("git+https://github.com/org/repo.git#egg=", "repo"),
        ],
        ids=["archive", "git"],
    )
    def test_empty_egg_fragment_falls_back_to_inference_instead_of_crashing(
        self, parser: RequirementsParser, line: str, expected_name: str
    ) -> None:
        """A bare ``#egg=`` must fall back to URL inference, not crash."""
        req = parser.parse_line(line, 1)

        assert req is not None
        assert req.name == expected_name
        assert "egg" not in req.name

    def test_empty_egg_fragment_with_uninferable_url_still_raises_parse_error(
        self, parser: RequirementsParser
    ) -> None:
        with pytest.raises(ParseError, match="#egg="):
            parser.parse_line("file://#egg=", 1)

    def test_inference_from_an_archive_url_is_unreliable(
        self, parser: RequirementsParser, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Known limitation, pinned so it cannot regress further unnoticed.

        Inference takes the last path segment, so a wheel URL yields the
        *filename* rather than the distribution name. Nothing on PyPI matches
        it, so the requirement is reported as unavailable. A warning is emitted
        so the user can add ``#egg=`` — which is why archive URLs in the shared
        corpora always carry one.
        """
        import logging

        with caplog.at_level(logging.WARNING, logger="depkeeper.parser"):
            req = parser.parse_line(
                "https://files.pythonhosted.org/packages/rich-13.7.1-py3-none-any.whl",
                1,
            )

        assert req is not None
        assert req.name == "rich-13-7-1-py3-none-any-whl"
        assert "URL without '#egg='" in caplog.text

    @pytest.mark.parametrize(
        ("directive", "editable"),
        [("-e ", True), ("--editable ", True), ("", False)],
        ids=["short-flag", "long-flag", "no-flag"],
    )
    def test_editable_flag_is_recorded(
        self, parser: RequirementsParser, directive: str, editable: bool
    ) -> None:
        req = parser.parse_line(
            f"{directive}git+https://github.com/acme/sdk.git#egg=internal-sdk", 1
        )

        assert req is not None
        assert req.editable is editable

    def test_local_checkout_becomes_an_absolute_file_uri(
        self, tmp_path: Path, parser: RequirementsParser
    ) -> None:
        """Resolving to an absolute URI is what lets the writer recognise the
        same checkout referenced from two different requirements files.
        """
        checkout = tmp_path / "packages" / "internal-sdk"
        checkout.mkdir(parents=True)
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("-e ./packages/internal-sdk\n", encoding="utf-8")

        req = parser.parse_file(req_file)[0]

        assert req.editable is True
        assert req.name == "internal-sdk"
        assert req.url == checkout.resolve().as_uri()

    def test_local_path_egg_fragment_overrides_the_directory_name(
        self, tmp_path: Path, parser: RequirementsParser
    ) -> None:
        """A checkout directory is often named after the repo, not the dist."""
        checkout = tmp_path / "vendor" / "acme-sdk-python"
        checkout.mkdir(parents=True)
        req_file = tmp_path / "requirements.txt"
        req_file.write_text(
            "-e ./vendor/acme-sdk-python#egg=internal-sdk\n", encoding="utf-8"
        )

        req = parser.parse_file(req_file)[0]

        assert req.name == "internal-sdk"

    def test_local_path_empty_egg_fragment_falls_back_to_directory_name(
        self, tmp_path: Path, parser: RequirementsParser
    ) -> None:
        checkout = tmp_path / "vendor" / "acme-sdk-python"
        checkout.mkdir(parents=True)
        req_file = tmp_path / "requirements.txt"
        req_file.write_text(
            "-e ./vendor/acme-sdk-python#egg=\n", encoding="utf-8"
        )

        req = parser.parse_file(req_file)[0]

        assert req.name == "acme-sdk-python"


# ---------------------------------------------------------------------------
# Include directives
# ---------------------------------------------------------------------------


class TestIncludeDirectives:
    """``-r`` flattens another file into this one."""

    @pytest.mark.parametrize("directive", ["-r", "--requirement"])
    def test_included_requirements_are_flattened_into_the_result(
        self, tmp_path: Path, parser: RequirementsParser, directive: str
    ) -> None:
        (tmp_path / "base.txt").write_text("requests==2.31.0\n", encoding="utf-8")
        root = tmp_path / "requirements.txt"
        root.write_text(f"{directive} base.txt\nflask==2.3.3\n", encoding="utf-8")

        parsed = _by_name(parser.parse_file(root))

        assert set(parsed) == {"requests", "flask"}

    def test_includes_resolve_relative_to_the_including_file(
        self, tmp_path: Path, parser: RequirementsParser
    ) -> None:
        """The layered ``requirements/prod.txt`` -> ``-r base.txt`` layout only
        works if paths are resolved against the *including* file's directory,
        not the process working directory.
        """
        written = datasets.write_project(tmp_path, datasets.LAYERED_PROJECT)

        parsed = _by_name(parser.parse_file(written["requirements/prod.txt"]))

        # From base.txt via -r, plus prod.txt's own entries.
        assert {"requests", "urllib3", "gunicorn", "flask"} <= set(parsed)

    def test_transitive_includes_are_followed(
        self, tmp_path: Path, parser: RequirementsParser
    ) -> None:
        """dev.txt -> prod.txt -> base.txt is the standard three-layer stack."""
        written = datasets.write_project(tmp_path, datasets.LAYERED_PROJECT)

        parsed = _by_name(parser.parse_file(written["requirements/dev.txt"]))

        assert {"requests", "urllib3", "gunicorn", "flask", "pytest"} <= set(parsed)

    def test_included_requirements_keep_the_included_file_as_provenance(
        self, tmp_path: Path, parser: RequirementsParser
    ) -> None:
        """Regression C1: the writer rewrites ``source_file``, and an included
        requirement's line number is meaningless in the parent.
        """
        base = tmp_path / "base.txt"
        base.write_text("requests==2.31.0\n", encoding="utf-8")
        root = tmp_path / "requirements.txt"
        root.write_text("-r base.txt\nflask==2.3.3\n", encoding="utf-8")

        parsed = _by_name(parser.parse_file(root))

        assert parsed["requests"].source_file == str(base.resolve())
        assert parsed["flask"].source_file == str(root.resolve())

    def test_a_circular_include_is_rejected_rather_than_recursed(
        self, tmp_path: Path, parser: RequirementsParser
    ) -> None:
        """Without cycle detection this is an unbounded recursion that ends in
        a ``RecursionError`` the user cannot interpret.
        """
        written = datasets.write_project(tmp_path, datasets.CIRCULAR_PROJECT)

        with pytest.raises(ParseError, match="[Cc]ircular"):
            parser.parse_file(written["requirements.txt"])

    def test_a_missing_included_file_is_reported_with_context(
        self, tmp_path: Path, parser: RequirementsParser
    ) -> None:
        """The error must name the include, not just the absent path, or the
        user has to grep the whole tree to find the bad directive.
        """
        root = tmp_path / "requirements.txt"
        root.write_text("-r does-not-exist.txt\n", encoding="utf-8")

        with pytest.raises(ParseError) as exc_info:
            parser.parse_file(root)

        assert "include directive" in str(exc_info.value).lower()

    def test_a_directive_without_a_path_is_skipped_not_fatal(
        self, parser: RequirementsParser, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A malformed line should not abandon the other 200 requirements."""
        import logging

        with caplog.at_level(logging.WARNING, logger="depkeeper.parser"):
            assert parser.parse_line("-r", 1) is None

        assert "missing file path" in caplog.text.lower()

    def test_the_include_stack_is_unwound_after_parsing(
        self, tmp_path: Path, parser: RequirementsParser
    ) -> None:
        """A leaked stack entry makes the *second* parse of the same file look
        circular, which is exactly what a long-lived parser instance does.
        """
        (tmp_path / "base.txt").write_text("requests==2.31.0\n", encoding="utf-8")
        root = tmp_path / "requirements.txt"
        root.write_text("-r base.txt\n", encoding="utf-8")

        assert len(parser.parse_file(root)) == 1
        assert len(parser.parse_file(root)) == 1


# ---------------------------------------------------------------------------
# Constraint directives
# ---------------------------------------------------------------------------


class TestConstraintDirectives:
    """``-c`` caps versions without adding requirements."""

    @pytest.mark.parametrize("directive", ["-c", "--constraint"])
    def test_constraints_are_recorded_but_not_returned(
        self, tmp_path: Path, parser: RequirementsParser, directive: str
    ) -> None:
        """A constraints file caps transitive dependencies; installing its
        contents outright would turn every cap into a direct dependency.
        """
        (tmp_path / "constraints.txt").write_text(
            "jinja2<3.2\nwerkzeug<3.0\n", encoding="utf-8"
        )
        root = tmp_path / "requirements.txt"
        root.write_text(f"{directive} constraints.txt\nflask==2.3.3\n", encoding="utf-8")

        parsed = parser.parse_file(root)

        assert [req.name for req in parsed] == ["flask"]
        assert set(parser.get_constraints()) == {"jinja2", "werkzeug"}

    def test_get_constraints_returns_a_defensive_copy(
        self, tmp_path: Path, parser: RequirementsParser
    ) -> None:
        """Callers inspect this map; mutating it must not corrupt the parser."""
        (tmp_path / "constraints.txt").write_text("jinja2<3.2\n", encoding="utf-8")
        root = tmp_path / "requirements.txt"
        root.write_text("-c constraints.txt\n", encoding="utf-8")
        parser.parse_file(root)

        parser.get_constraints().clear()

        assert set(parser.get_constraints()) == {"jinja2"}

    def test_a_missing_constraint_file_is_reported_with_context(
        self, tmp_path: Path, parser: RequirementsParser
    ) -> None:
        root = tmp_path / "requirements.txt"
        root.write_text("-c missing-constraints.txt\n", encoding="utf-8")

        with pytest.raises(ParseError) as exc_info:
            parser.parse_file(root)

        assert "constraint directive" in str(exc_info.value).lower()


class TestParserState:
    """The parser is stateful and is reused across files."""

    def test_reset_clears_constraints(
        self, tmp_path: Path, parser: RequirementsParser
    ) -> None:
        """Reusing a parser across projects must not leak project A's caps
        into project B's resolution.
        """
        (tmp_path / "constraints.txt").write_text("jinja2<3.2\n", encoding="utf-8")
        root = tmp_path / "requirements.txt"
        root.write_text("-c constraints.txt\n", encoding="utf-8")
        parser.parse_file(root)

        parser.reset()

        assert parser.get_constraints() == {}


# ---------------------------------------------------------------------------
# Whole-file behaviour
# ---------------------------------------------------------------------------


class TestWholeFileParsing:
    def test_pinned_application_file(self, parser: RequirementsParser) -> None:
        """A pip-compile style file yields exactly its pinned distributions."""
        parsed = _by_name(parser.parse_string(datasets.PINNED_APPLICATION))

        assert set(parsed) == {"certifi", "charset-normalizer", "idna", "requests", "urllib3"}
        assert parsed["requests"].specs == [("==", "2.31.0")]

    def test_library_style_ranges_survive_intact(
        self, parser: RequirementsParser
    ) -> None:
        """Ranges are the whole point of a library file; collapsing any part of
        them would change what downstream consumers may install.
        """
        parsed = _by_name(parser.parse_string(datasets.LIBRARY_RANGES))

        assert parsed["flask"].specs == [(">=", "2.2"), ("<", "3.0")]
        assert parsed["celery"].extras == ["redis"]
        assert parsed["sqlalchemy"].specs == [("~=", "2.0")]
        assert parsed["django"].specs == [
            (">=", "3.2"),
            ("<", "5.0"),
            ("!=", "4.0.*"),
        ]
        assert parsed["django"].comment is not None

    def test_kitchen_sink_file_parses_every_supported_line_form(
        self, parser: RequirementsParser
    ) -> None:
        """One pass over every syntax depkeeper claims to support.

        Global options and comments contribute nothing; every other line must
        yield exactly one requirement.
        """
        parsed = _by_name(parser.parse_string(datasets.KITCHEN_SINK))

        assert set(parsed) == {
            "requests",
            "urllib3",
            "flask",
            "sqlalchemy",
            "celery",
            "django",
            "typing-extensions",
            "pywin32",
            "zope-interface",
            "rich",
            "internal-sdk",
            "click",
            "pandas",
        }
        assert parsed["internal-sdk"].editable is True
        assert parsed["click"].hashes == [
            "sha256:ae74fb96c20a0277a1d615f1e4d73c8414f5a98db8b799a7931d1582f3390c28"
        ]
        # The indented line proves leading whitespace does not hide a spec, and
        # its comment proves an inline '#' is still split off at that indent.
        assert parsed["pandas"].specs == [(">=", "2.2.2")]
        assert parsed["pandas"].comment is not None

    def test_a_comments_only_file_yields_no_requirements(
        self, parser: RequirementsParser
    ) -> None:
        """Legacy files kept alive for CI must not be reported as broken."""
        assert parser.parse_string(datasets.COMMENTS_ONLY) == []

    def test_an_empty_file_yields_no_requirements(
        self, parser: RequirementsParser
    ) -> None:
        assert parser.parse_string("") == []


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


class TestFailureModes:
    @pytest.mark.parametrize(
        "line",
        [
            "requests===",
            "requests>=",
            ">=2.31.0",
            "requests[unclosed>=2.0",
            "requests @ ",
        ],
        ids=["empty-triple-eq", "empty-version", "no-name", "unclosed-extras", "empty-url"],
    )
    def test_malformed_specifiers_raise_a_located_parse_error(
        self, parser: RequirementsParser, line: str
    ) -> None:
        """The error carries line number and content, because a requirements
        file can be thousands of lines long and the message is all the user has.
        """
        with pytest.raises(ParseError) as exc_info:
            parser.parse_line(line, 42, "requirements.txt")

        assert exc_info.value.line_number == 42

    def test_a_missing_file_raises_a_file_error_not_a_parse_error(
        self, tmp_path: Path, parser: RequirementsParser
    ) -> None:
        """The two need different remediation: fix the path vs fix the syntax."""
        with pytest.raises(FileOperationError):
            parser.parse_file(tmp_path / "absent.txt")

    def test_line_continuations_are_not_joined(
        self, parser: RequirementsParser
    ) -> None:
        """Known gap, pinned so it is visible rather than folklore.

        ``pip-compile --generate-hashes`` emits backslash continuations by
        default, so this is the *standard* lockfile layout. depkeeper parses
        line-by-line and rejects the trailing backslash, which means such a file
        cannot be checked at all. The failure is at least loud and located
        rather than silent, and the shared corpora use the single-line form.
        """
        with pytest.raises(ParseError):
            parser.parse_string(
                "certifi==2023.7.22 \\\n    --hash=sha256:539cc1d13202e33ca466e88b\n"
            )
