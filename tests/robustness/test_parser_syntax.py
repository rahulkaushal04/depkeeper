"""Requirements-file syntax edge cases: continuations, includes, options, URLs, secrets."""

from __future__ import annotations

import importlib.util
import logging
import random
from pathlib import Path
from typing import List

import pytest

from depkeeper.core.parser import RequirementsParser
from depkeeper.core.sources.requirements_txt import RequirementsTxtAdapter
from depkeeper.exceptions import FileOperationError, ParseError
from depkeeper.models.requirement import Requirement


def _parse(text: str) -> List[Requirement]:
    return RequirementsParser().parse_string(text)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


class TestLineHandling:
    @pytest.mark.parametrize(
        "separator", ["\n", "\r\n", "\r"], ids=["lf", "crlf", "cr"]
    )
    def test_line_numbers_per_terminator(self, separator: str) -> None:
        reqs = _parse(separator.join(["a==1", "", "# c", "b==2", "c==3"]))
        assert [(r.name, r.line_number) for r in reqs] == [("a", 1), ("b", 4), ("c", 5)]

    @pytest.mark.parametrize(
        "odd", ["\x0c", "\x0b", "\x1c", "\x85", "\u2028", "\u2029"]
    )
    def test_exotic_separators_are_not_line_breaks(self, odd: str) -> None:
        """Only \\n, \\r\\n and \\r end a line, matching pip and the update writer."""
        reqs = _parse(f"a==1\n# note{odd}b==2\nc==3\n")
        assert [(r.name, r.line_number) for r in reqs] == [("a", 1), ("c", 3)]

    def test_form_feed_page_break_line_numbers(self) -> None:
        reqs = _parse("a==1\n\x0c\nb==2\n")
        assert [(r.name, r.line_number) for r in reqs] == [("a", 1), ("b", 3)]

    def test_line_numbers_after_continuations(self) -> None:
        text = "a==1 \\\n  --hash=sha256:aa \\\n  --hash=sha256:bb\nb==2\n\nc==3\n"
        reqs = _parse(text)
        assert [(r.name, r.line_number) for r in reqs] == [("a", 1), ("b", 4), ("c", 6)]
        assert reqs[0].hashes == ["sha256:aa", "sha256:bb"]

    def test_error_line_number_after_continuation(self) -> None:
        text = "a==1 \\\n  --hash=sha256:aa\nb==2\nthis is not valid\n"
        with pytest.raises(ParseError) as caught:
            _parse(text)
        assert caught.value.line_number == 4

    def test_comment_line_never_continues(self) -> None:
        reqs = _parse("# trailing backslash \\\nb==2\n")
        assert [(r.name, r.line_number) for r in reqs] == [("b", 2)]

    def test_comment_inside_continuation_ends_it(self) -> None:
        """pip yields the comment as the last piece, so the next line stands alone."""
        reqs = _parse("a==1 \\\n  # why \\\nb==2\n")
        assert [(r.name, r.line_number) for r in reqs] == [("a", 1), ("b", 3)]

    def test_trailing_backslash_at_eof(self) -> None:
        assert [r.name for r in _parse("a==1 \\")] == ["a"]

    def test_bom_and_whitespace(self) -> None:
        reqs = _parse("\ufeff  a==1\t\n\t\n  \tb==2")
        assert [r.name for r in reqs] == ["a", "b"]

    def test_nul_byte_is_a_parse_error_not_a_crash(self) -> None:
        with pytest.raises(ParseError):
            _parse("a\x00==1\n")

    def test_binary_file_is_a_clean_error(self, tmp_path: Path) -> None:
        path = tmp_path / "requirements.txt"
        path.write_bytes(b"\xff\xfe\x00\x01garbage\x80\x81")
        with pytest.raises((FileOperationError, ParseError)):
            RequirementsParser().parse_file(path)

    def test_huge_line(self) -> None:
        name = "a" * 300_000
        assert _parse(f"{name}==1")[0].name == name


class TestComments:
    @pytest.mark.parametrize(
        "line,spec,comment",
        [
            ("a==1 # c", "a", "c"),
            ("a==1\t#c", "a", "c"),
            ("a==1 # c # d", "a", "c # d"),
            ("a @ https://h/p.zip#sha256=ab # c", "a", "c"),
            ("git+https://h/r.git#egg=a # c", "a", "c"),
            ("a==1; extra == 'x#y'", "a", None),
        ],
    )
    def test_comment_split(self, line: str, spec: str, comment: object) -> None:
        req = _parse(line)[0]
        assert req.name == spec
        assert req.comment == comment

    def test_hash_inside_token_is_not_a_comment(self) -> None:
        with pytest.raises(ParseError):
            _parse("a==1#c")

    def test_url_fragment_hash_kept(self) -> None:
        req = _parse("https://h/p.zip#sha256=ab#egg=pkg")[0]
        assert req.url == "https://h/p.zip#sha256=ab#egg=pkg"


class TestDirectives:
    @pytest.mark.parametrize(
        "spelling",
        [
            "-r {p}",
            "-r{p}",
            "-r={p}",
            "--requirement {p}",
            "--requirement={p}",
            '-r "{p}"',
            "-r '{p}'",
            "-r   {p}   # c",
        ],
    )
    def test_include_spellings(self, tmp_path: Path, spelling: str) -> None:
        _write(tmp_path / "base.txt", "a==1\n")
        top = _write(tmp_path / "top.txt", spelling.format(p="base.txt") + "\nb==2\n")
        names = [r.name for r in RequirementsParser().parse_file(top)]
        assert names == ["a", "b"]

    @pytest.mark.parametrize(
        "spelling",
        [
            "-c {p}",
            "-c{p}",
            "-c={p}",
            "--constraint {p}",
            "--constraint={p}",
            '-c "{p}"',
        ],
    )
    def test_constraint_spellings(self, tmp_path: Path, spelling: str) -> None:
        _write(tmp_path / "c.txt", "a<2\n")
        top = _write(tmp_path / "top.txt", spelling.format(p="c.txt") + "\na==1\n")
        parser = RequirementsParser()
        (req,) = parser.parse_file(top)
        assert req.constraint_specs == [("<", "2")]
        assert req.specs == [("==", "1")]

    def test_relative_paths_resolve_against_including_file(
        self, tmp_path: Path
    ) -> None:
        _write(tmp_path / "base.txt", "a==1\n")
        _write(tmp_path / "sub" / "mid.txt", "-r ../base.txt\nb==2\n")
        top = _write(tmp_path / "top.txt", "-r sub/mid.txt\n-r sub/../base.txt\n")
        reqs = RequirementsParser().parse_file(top)
        assert [(r.name, Path(r.source_file or "").name) for r in reqs] == [
            ("a", "base.txt"),
            ("b", "mid.txt"),
            ("a", "base.txt"),
        ]

    def test_nested_include_relative_to_nested_file(self, tmp_path: Path) -> None:
        _write(tmp_path / "a" / "b" / "deep.txt", "d==1\n")
        _write(tmp_path / "a" / "mid.txt", "-r b/deep.txt\n")
        top = _write(tmp_path / "top.txt", "-r a/mid.txt\n")
        assert [r.name for r in RequirementsParser().parse_file(top)] == ["d"]

    def test_circular_include(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.txt", "-r b.txt\n")
        _write(tmp_path / "b.txt", "-r a.txt\n")
        with pytest.raises(ParseError, match="Circular"):
            RequirementsParser().parse_file(tmp_path / "a.txt")

    def test_self_include(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "s.txt", "-r s.txt\n")
        with pytest.raises(ParseError, match="Circular"):
            RequirementsParser().parse_file(path)

    def test_diamond_include_is_not_circular(self, tmp_path: Path) -> None:
        _write(tmp_path / "base.txt", "a==1\n")
        _write(tmp_path / "l.txt", "-r base.txt\n")
        _write(tmp_path / "r.txt", "-r base.txt\n")
        top = _write(tmp_path / "top.txt", "-r l.txt\n-r r.txt\n")
        assert len(RequirementsParser().parse_file(top)) == 2

    def test_parser_state_survives_a_failed_parse(self, tmp_path: Path) -> None:
        bad = _write(tmp_path / "bad.txt", "-r missing.txt\n")
        good = _write(tmp_path / "good.txt", "a==1\n")
        parser = RequirementsParser()
        with pytest.raises(ParseError):
            parser.parse_file(bad)
        assert [r.name for r in parser.parse_file(good)] == ["a"]

    def test_missing_include_reports_line(self, tmp_path: Path) -> None:
        top = _write(tmp_path / "top.txt", "a==1\n-r nope.txt\n")
        with pytest.raises(ParseError) as caught:
            RequirementsParser().parse_file(top)
        assert caught.value.line_number == 2

    def test_missing_top_level_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileOperationError):
            RequirementsParser().parse_file(tmp_path / "nope.txt")

    def test_include_with_no_path_is_ignored(self) -> None:
        assert _parse("-r\n--requirement\n-c\n") == []

    @pytest.mark.parametrize(
        "spelling,editable",
        [
            ("-e .", True),
            ("-e.", True),
            ("-e=.", True),
            ("--editable .", True),
            ("--editable=.", True),
            ('-e "."', True),
        ],
    )
    def test_editable_spellings(self, spelling: str, editable: bool) -> None:
        (req,) = _parse(spelling)
        assert req.editable is editable
        assert req.url is not None and req.url.startswith("file://")

    @pytest.mark.parametrize("line", ["-e", "--editable", "-e   "])
    def test_editable_without_target_is_a_clear_error(self, line: str) -> None:
        with pytest.raises(ParseError, match="[Ee]ditable"):
            _parse(line)

    @pytest.mark.parametrize(
        "line",
        [
            "--index-url https://u:p@host/simple",
            "--index-url=https://host/simple",
            "-i https://host/simple",
            "--extra-index-url https://host/simple",
            "--find-links ./wheels",
            "--find-links=./wheels",
            "-f ./wheels",
            "--no-index",
            "--pre",
            "--trusted-host host",
            "--prefer-binary",
            "--no-binary :all:",
            "--only-binary=:all:",
            "--require-hashes",
            "--use-feature=fast-deps",
        ],
    )
    def test_global_options_are_skipped(self, line: str) -> None:
        assert _parse(f"a==1\n{line}\nb==2\n") != []
        assert [r.name for r in _parse(f"a==1\n{line}\nb==2\n")] == ["a", "b"]

    def test_per_requirement_options_are_dropped(self) -> None:
        (req,) = _parse(
            'a==1 --global-option="--x y" --config-settings=k=v --hash=sha256:aa'
        )
        assert (req.name, req.specs, req.hashes) == ("a", [("==", "1")], ["sha256:aa"])

    def test_unknown_option_is_an_error(self) -> None:
        with pytest.raises(ParseError):
            _parse("--definitely-not-an-option\n")


class TestUrlsAndPaths:
    @pytest.mark.parametrize(
        "line",
        [
            "git+https://h/r.git#egg=pkg",
            "git+ssh://git@h/r.git@v1.0#egg=pkg",
            "git+file:///srv/r.git#egg=pkg",
            "svn+svn://h/r#egg=pkg",
            "ftp://h/p.tar.gz#egg=pkg",
            "HTTPS://h/p.zip#egg=pkg",
            "https://h/p.zip#egg=pkg&subdirectory=sub",
            "file:///tmp/p.whl#egg=pkg",
        ],
    )
    def test_url_schemes(self, line: str) -> None:
        (req,) = _parse(line)
        assert req.name == "pkg"
        assert req.url == line

    def test_url_with_marker(self) -> None:
        (req,) = _parse("https://h/p.zip#egg=pkg ; python_version < '3.9'")
        assert req.url == "https://h/p.zip#egg=pkg"
        assert req.markers == 'python_version < "3.9"'
        assert req.to_string() == 'https://h/p.zip#egg=pkg ; python_version < "3.9"'

    @pytest.mark.parametrize("egg", ["a/b", "../x", "-bad", "a;b"])
    def test_bad_egg_names(self, egg: str) -> None:
        with pytest.raises(ParseError):
            _parse(f"./local#egg={egg}")

    def test_empty_egg_infers_name(self) -> None:
        (req,) = _parse("https://h/pkgname.git#egg=")
        assert req.name == "pkgname"

    def test_local_path_relative_to_requirements_file(self, tmp_path: Path) -> None:
        (tmp_path / "sub" / "proj").mkdir(parents=True)
        top = _write(tmp_path / "sub" / "r.txt", "./proj\n")
        (req,) = RequirementsParser().parse_file(top)
        assert req.url == (tmp_path / "sub" / "proj").resolve().as_uri()

    def test_direct_reference_keeps_name_and_form(self) -> None:
        (req,) = _parse("Foo_Bar[extra] @ https://h/p.zip")
        assert req.direct_reference
        assert req.to_string() == "foo-bar[extra] @ https://h/p.zip"


class TestSpecifiers:
    @pytest.mark.parametrize(
        "line,specs",
        [
            ("a==1.*", [("==", "1.*")]),
            ("a~=1.4.2", [("~=", "1.4.2")]),
            ("a===weird-version", [("===", "weird-version")]),
            ("a==1!2.0.post1.dev3+local.1", [("==", "1!2.0.post1.dev3+local.1")]),
            ("a >= 1 , < 2 ,", [(">=", "1"), ("<", "2")]),
            ("a (>=1.0)", [(">=", "1.0")]),
            ("a<2,>=1,!=1.5", [("<", "2"), (">=", "1"), ("!=", "1.5")]),
        ],
    )
    def test_accepted(self, line: str, specs: List[tuple]) -> None:
        assert _parse(line)[0].specs == specs

    @pytest.mark.parametrize(
        "line",
        ["a==", "a>=1.*", "a~=1", "a<=1.0.*", "a==1..0", "a>=>1", "a=1", "a ! 1"],
    )
    def test_rejected(self, line: str) -> None:
        with pytest.raises(ParseError):
            _parse(line)

    def test_name_normalisation(self) -> None:
        reqs = _parse("Foo_Bar==1\nfoo-bar==2\nFOO.BAR==3\n")
        assert {r.name for r in reqs} == {"foo-bar"}
        assert len(reqs) == 3  # duplicates are kept, as pip would see them

    def test_extras_spacing_and_case(self) -> None:
        (req,) = _parse("a[ B , a_b ]==1")
        assert req.extras == ["B", "a_b"]


class TestSecrets:
    SECRET = "s3cr3t-pass"

    def _error(self, text: str) -> ParseError:
        with pytest.raises(ParseError) as caught:
            _parse(text)
        return caught.value

    @pytest.mark.parametrize(
        "line",
        [
            "git+https://bob:{s}@host/r.git ; bad marker (",
            "pkg @ https://bob:{s}@host/p.zip ; python_version <",
            "pkg @ https://bob:{s}@host/p.zip >= 1",
            "https://bob:{s}@host/p.zip#egg=a/b",
            "https://bob:p@{s}@host/p.zip#egg=a/b",
            "-e https://bob:{s}@host/p.zip#egg=../x",
            "https://bob:{s}@host/p.zip#egg=ok ; bad (",
        ],
    )
    def test_parse_error_never_leaks_credentials(self, line: str) -> None:
        error = self._error(line.format(s=self.SECRET))
        for rendered in (
            str(error),
            repr(error),
            error.line_content or "",
            error.args[0] if error.args else "",
            str(getattr(error, "details", "")),
        ):
            assert self.SECRET not in rendered
            assert "bob" not in rendered

    def test_include_error_does_not_leak(self, tmp_path: Path) -> None:
        top = _write(
            tmp_path / "t.txt", f"-r https://bob:{self.SECRET}@host/base.txt\n"
        )
        with pytest.raises(ParseError) as caught:
            RequirementsParser().parse_file(top)
        assert self.SECRET not in str(caught.value)
        assert self.SECRET not in (caught.value.line_content or "")

    def test_debug_log_does_not_leak(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG)
        _parse(f"--index-url https://bob:{self.SECRET}@host/simple\n")
        assert self.SECRET not in caplog.text


class TestAdapterLineMapping:
    """Parser line numbers must address the same physical lines the writer edits."""

    @pytest.mark.parametrize(
        "terminator", ["\n", "\r\n", "\r"], ids=["lf", "crlf", "cr"]
    )
    def test_update_hits_the_right_line(self, terminator: str) -> None:
        text = terminator.join(
            ["# head\x0c", "a==1.0", "\x0c", "b==2.0  # keep", "c>=3.0,<4"]
        )
        adapter = RequirementsTxtAdapter()
        reqs = _parse(text)
        by_name = {r.name: r for r in reqs}
        out = adapter.apply_updates(
            text, [(by_name["b"], "2.5.0"), (by_name["c"], "3.9.0")]
        )
        expected = text.replace("b==2.0", "b==2.5.0").replace("c>=3.0", "c>=3.9.0")
        assert out == expected

    def test_update_preserves_name_spelling_markers_and_quotes(self) -> None:
        text = "Foo_Bar[Extra] >= 1.0 ; python_version<'3.9' # c\r\n"
        (req,) = _parse(text)
        out = RequirementsTxtAdapter().apply_updates(text, [(req, "2.0")])
        assert out == "Foo_Bar[Extra] >= 2.0 ; python_version<'3.9' # c\r\n"


@pytest.mark.skipif(importlib.util.find_spec("pip") is None, reason="pip not installed")
class TestPipLineJoiningParity:
    """Compare logical line numbers with pip's own preprocessing."""

    def test_random_files(self) -> None:
        from pip._internal.req.req_file import preprocess  # type: ignore[import-not-found]

        from depkeeper.core.parser import _join_continuations

        rng = random.Random(11)
        pieces = [
            "a==1",
            "b>=2 \\",
            "  --hash=sha256:aa \\",
            "",
            "# c",
            "# c \\",
            "  # x",
            "c<3",
        ]
        for _ in range(200):
            lines = [rng.choice(pieces) for _ in range(rng.randint(1, 12))]
            text = "\n".join(lines) + "\n"
            try:
                expected = [n for n, _ in preprocess(text)]
            except Exception:
                continue
            ours = [
                n
                for n, line in _join_continuations(text)
                if line.strip() and not line.strip().startswith("#")
            ]
            # depkeeper drops comment-only lines; compare those pip also keeps
            assert [n for n in expected if n in ours] == ours, text


class TestSpecifierHelpers:
    def test_implied_major_bound_keeps_epoch(self) -> None:
        from packaging.specifiers import SpecifierSet

        from depkeeper.utils.version_utils import implied_major_bounds

        (bound,) = implied_major_bounds([("~=", "1!2.4")])
        assert SpecifierSet(f"{bound[0]}{bound[1]}").contains("1!2.9")
        assert not SpecifierSet(f"{bound[0]}{bound[1]}").contains("1!3.0")
        assert implied_major_bounds([("~=", "7.0")]) == [("<", "8")]
