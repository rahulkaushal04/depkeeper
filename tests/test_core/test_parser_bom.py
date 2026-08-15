"""Tests for UTF-8 BOM handling in the requirements parser.

Regression guard for audit finding M3: a leading byte order mark survived
``utf-8`` decoding as ``\\ufeff`` (``str.strip()`` does not remove it), so the
first line of any file written by Notepad or PowerShell ``Set-Content``
failed to parse and aborted the whole command.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from depkeeper.core.parser import RequirementsParser


def _write_bom(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8-sig"))


@pytest.mark.unit
class TestParserBomHandling:
    """BOM-prefixed requirement files must parse identically to plain UTF-8."""

    def test_requirement_on_first_line(self, tmp_path: Path) -> None:
        """M3 regression: a pinned requirement on line 1 parses."""
        req_file = tmp_path / "requirements.txt"
        _write_bom(req_file, "flask==2.0.0\nrequests>=2.25.0\n")

        reqs = RequirementsParser().parse_file(req_file)

        assert [r.name for r in reqs] == ["flask", "requests"]
        assert reqs[0].specs == [("==", "2.0.0")]
        assert reqs[0].line_number == 1
        assert reqs[0].raw_line == "flask==2.0.0"

    def test_comment_on_first_line(self, tmp_path: Path) -> None:
        """A BOM followed by a comment must still be treated as a comment."""
        req_file = tmp_path / "requirements.txt"
        _write_bom(req_file, "# header comment\nflask==2.0.0\n")

        reqs = RequirementsParser().parse_file(req_file)

        assert [r.name for r in reqs] == ["flask"]
        assert reqs[0].line_number == 2

    def test_include_directive_on_first_line(self, tmp_path: Path) -> None:
        """A BOM must not hide an ``-r`` directive on line 1."""
        base = tmp_path / "base.txt"
        base.write_text("click==8.0.0\n", encoding="utf-8")

        root = tmp_path / "requirements.txt"
        _write_bom(root, "-r base.txt\nflask==2.0.0\n")

        reqs = RequirementsParser().parse_file(root)

        assert sorted(r.name for r in reqs) == ["click", "flask"]

    def test_bom_in_included_file(self, tmp_path: Path) -> None:
        """Included files are read through the same BOM-aware path."""
        base = tmp_path / "base.txt"
        _write_bom(base, "click==8.0.0\n")

        root = tmp_path / "requirements.txt"
        root.write_text("-r base.txt\n", encoding="utf-8")

        reqs = RequirementsParser().parse_file(root)

        assert [r.name for r in reqs] == ["click"]

    def test_bom_in_constraint_file(self, tmp_path: Path) -> None:
        """Constraint files loaded via ``-c`` are equally BOM-tolerant."""
        constraints = tmp_path / "constraints.txt"
        _write_bom(constraints, "django<4.0\n")

        root = tmp_path / "requirements.txt"
        root.write_text("-c constraints.txt\ndjango==3.2\n", encoding="utf-8")

        parser = RequirementsParser()
        reqs = parser.parse_file(root)

        assert [r.name for r in reqs] == ["django"]
        assert "django" in parser.get_constraints()

    def test_parse_string_strips_bom(self) -> None:
        """``parse_string`` protects callers that decode content themselves."""
        content = "\ufeffflask==2.0.0\n"

        reqs = RequirementsParser().parse_string(content)

        assert [r.name for r in reqs] == ["flask"]
        assert reqs[0].line_number == 1

    def test_bom_does_not_shift_line_numbers(self, tmp_path: Path) -> None:
        """Line numbering must match the file without a BOM."""
        text = "flask==2.0.0\n# comment\nrequests==2.25.0\n"

        plain = tmp_path / "plain.txt"
        plain.write_text(text, encoding="utf-8")
        bom = tmp_path / "bom.txt"
        _write_bom(bom, text)

        plain_reqs = RequirementsParser().parse_file(plain)
        bom_reqs = RequirementsParser().parse_file(bom)

        assert [(r.name, r.line_number) for r in plain_reqs] == [
            (r.name, r.line_number) for r in bom_reqs
        ]

    def test_plain_utf8_still_parses(self, tmp_path: Path) -> None:
        """Non-ASCII content without a BOM is unaffected by the change."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("flask==2.0.0  # café ☕\n", encoding="utf-8")

        reqs = RequirementsParser().parse_file(req_file)

        assert [r.name for r in reqs] == ["flask"]
