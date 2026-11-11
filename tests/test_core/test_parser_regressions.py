"""Regression tests for requirements-file parsing edge cases."""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from depkeeper.core.parser import RequirementsParser
from depkeeper.exceptions import ParseError
from depkeeper.models.requirement import Requirement


def _names(reqs: List[Requirement]) -> List[str]:
    return [r.name for r in reqs]


@pytest.mark.unit
class TestAttachedDirectiveForms:
    @pytest.mark.parametrize(
        "directive", ["-rb.txt", "--requirement=b.txt", "-r=b.txt", "-r  b.txt"]
    )
    def test_include_forms(self, tmp_path: Path, directive: str) -> None:
        (tmp_path / "b.txt").write_text("flask\n", encoding="utf-8")
        a = tmp_path / "a.txt"
        a.write_text(f"{directive}\nrequests\n", encoding="utf-8")
        assert _names(RequirementsParser().parse_file(a)) == ["flask", "requests"]

    @pytest.mark.parametrize("directive", ["-cc.txt", "--constraint=c.txt", "-c=c.txt"])
    def test_constraint_forms(self, tmp_path: Path, directive: str) -> None:
        (tmp_path / "c.txt").write_text("flask<2\n", encoding="utf-8")
        a = tmp_path / "a.txt"
        a.write_text(f"{directive}\nflask\n", encoding="utf-8")
        parser = RequirementsParser()
        parser.parse_file(a)
        assert "flask" in parser.get_constraints()

    def test_missing_file_after_attached_form_is_an_error(self, tmp_path: Path) -> None:
        a = tmp_path / "a.txt"
        a.write_text("--requirement=nope.txt\n", encoding="utf-8")
        with pytest.raises(ParseError):
            RequirementsParser().parse_file(a)


@pytest.mark.unit
class TestLineContinuation:
    def test_hash_continuations_are_joined(self) -> None:
        text = (
            "requests==2.0 \\\n"
            "    --hash=sha256:aa \\\n"
            "    --hash=sha256:bb\n"
            "flask==2.0\n"
        )
        reqs = RequirementsParser().parse_string(text)
        assert _names(reqs) == ["requests", "flask"]
        assert reqs[0].hashes == ["sha256:aa", "sha256:bb"]
        assert reqs[1].line_number == 4


@pytest.mark.unit
class TestConstraints:
    def test_multiple_constraint_lines_merge(self, tmp_path: Path) -> None:
        (tmp_path / "c.txt").write_text("pkg>=1.5\npkg<2\n", encoding="utf-8")
        a = tmp_path / "a.txt"
        a.write_text("-c c.txt\npkg\n", encoding="utf-8")
        parser = RequirementsParser()
        parser.parse_file(a)
        assert sorted(parser.get_constraints()["pkg"].specs) == [
            ("<", "2"),
            (">=", "1.5"),
        ]

    def test_constraints_do_not_leak_into_rendered_requirement(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "c.txt").write_text("pkg==1.3\n", encoding="utf-8")
        a = tmp_path / "a.txt"
        a.write_text("-c c.txt\npkg\n", encoding="utf-8")
        (req,) = RequirementsParser().parse_file(a)
        assert req.specs == []
        assert req.to_string() == "pkg"
        assert req.constraint_specs == [("==", "1.3")]

    def test_constraint_after_requirement_still_applies(self, tmp_path: Path) -> None:
        (tmp_path / "c.txt").write_text("pkg<2\n", encoding="utf-8")
        a = tmp_path / "a.txt"
        a.write_text("pkg\n-c c.txt\n", encoding="utf-8")
        (req,) = RequirementsParser().parse_file(a)
        assert req.constraint_specs == [("<", "2")]


@pytest.mark.unit
class TestMinors:
    def test_extras_sorted(self) -> None:
        (req,) = RequirementsParser().parse_string("pkg[zeta,alpha,mid,beta]")
        assert req.extras == ["alpha", "beta", "mid", "zeta"]

    def test_pep508_direct_reference_keeps_name(self) -> None:
        (req,) = RequirementsParser().parse_string("pkg[b,a] @ https://x.org/p.whl")
        assert req.to_string() == "pkg[a,b] @ https://x.org/p.whl"
        assert req.update_version("1.0") == "pkg[a,b] @ https://x.org/p.whl\n"

    def test_credentials_redacted_in_parse_error(self) -> None:
        with pytest.raises(ParseError) as exc:
            RequirementsParser().parse_string(
                "git+https://user:s3cret@host/repo.git#egg=a/b"
            )
        assert "s3cret" not in str(exc.value)
        assert "s3cret" not in exc.value.line_content

    def test_credentials_redacted_in_syntax_error(self) -> None:
        with pytest.raises(ParseError) as exc:
            RequirementsParser().parse_string("pkg>=1 @@ https://user:s3cret@host/p")
        assert "s3cret" not in str(exc.value)
        assert "s3cret" not in exc.value.line_content

    @pytest.mark.parametrize("egg", ["../evil", "a/b", "a\\b", ".."])
    def test_path_like_egg_rejected(self, egg: str) -> None:
        with pytest.raises(ParseError):
            RequirementsParser().parse_string(f"git+https://h/r.git#egg={egg}")

    def test_valid_egg_with_extras_accepted(self) -> None:
        (req,) = RequirementsParser().parse_string("git+https://h/r.git#egg=my_pkg")
        assert req.name == "my-pkg"


def test_comment_ending_in_backslash_does_not_swallow_next_line() -> None:
    from depkeeper.core.parser import RequirementsParser

    reqs = RequirementsParser().parse_string(
        "# path C:\\dir\\\nflask==2.0\nclick==8.0\n"
    )
    assert [r.name for r in reqs] == ["flask", "click"]
