"""Tests for requirement source-file provenance in the parser.

These tests guard against regression C1: requirements pulled in through
``-r`` includes must retain the *included* file's path (and line numbers),
so the update writer can rewrite the correct file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from depkeeper.core.parser import RequirementsParser


@pytest.fixture
def parser() -> RequirementsParser:
    return RequirementsParser()


def test_source_file_set_for_flat_file(tmp_path: Path, parser: RequirementsParser) -> None:
    """Every requirement records the file it was parsed from."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("click==8.0.0\nrich==13.0.0\n", encoding="utf-8")

    reqs = parser.parse_file(req_file)

    assert {r.name for r in reqs} == {"click", "rich"}
    for r in reqs:
        assert r.source_file == str(req_file.resolve())


def test_included_requirements_retain_included_file_provenance(
    tmp_path: Path, parser: RequirementsParser
) -> None:
    """Requirements from ``-r base.txt`` point at base.txt, not the parent."""
    base = tmp_path / "base.txt"
    base.write_text("click==8.0.0\n", encoding="utf-8")

    root = tmp_path / "requirements.txt"
    root.write_text("-r base.txt\n# comment line\nrich==13.0.0\n", encoding="utf-8")

    reqs = parser.parse_file(root)
    by_name = {r.name: r for r in reqs}

    # click comes from base.txt at line 1
    assert by_name["click"].source_file == str(base.resolve())
    assert by_name["click"].line_number == 1

    # rich comes from the parent at line 3
    assert by_name["rich"].source_file == str(root.resolve())
    assert by_name["rich"].line_number == 3


def test_parse_string_without_source_leaves_provenance_none(
    parser: RequirementsParser,
) -> None:
    """Direct string parsing without a path leaves source_file unset."""
    reqs = parser.parse_string("flask>=2.0\nrequests>=2.25.0\n")

    assert [r.name for r in reqs] == ["flask", "requests"]
    for r in reqs:
        assert r.source_file is None


def test_source_file_excluded_from_equality() -> None:
    """Provenance must not change requirement equality semantics."""
    from depkeeper.models.requirement import Requirement

    a = Requirement(name="click", specs=[("==", "8.0.0")], source_file="a.txt")
    b = Requirement(name="click", specs=[("==", "8.0.0")], source_file="b.txt")

    assert a == b
