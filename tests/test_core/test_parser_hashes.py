"""Regression tests for ``--hash`` directive parsing (M2).

pip accepts both ``--hash=sha256:...`` and the space-separated
``--hash sha256:...`` form.  Historically only the ``=`` form parsed; the
space form leaked the bare digest token into the PEP 508 spec and raised a
``ParseError``.  These tests lock in support for both forms and the
combinations pip permits.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from depkeeper.core.parser import RequirementsParser


@pytest.mark.parametrize(
    "line, expected_hashes",
    [
        # Single hash, both separator forms
        ("flask==2.0 --hash=sha256:abc123", ["sha256:abc123"]),
        ("flask==2.0 --hash sha256:abc123", ["sha256:abc123"]),
        # Multiple hashes, each separator form
        (
            "django==4.0 --hash=sha256:111 --hash=sha256:222",
            ["sha256:111", "sha256:222"],
        ),
        (
            "django==4.0 --hash sha256:111 --hash sha256:222",
            ["sha256:111", "sha256:222"],
        ),
        # Mixed separators on one line
        (
            "pkg==1.0 --hash=sha256:a --hash sha256:b",
            ["sha256:a", "sha256:b"],
        ),
    ],
)
def test_parse_line_extracts_hashes_both_forms(
    line: str, expected_hashes: list[str]
) -> None:
    """Both ``--hash=`` and ``--hash `` forms are parsed and extracted."""
    parser = RequirementsParser()

    req = parser.parse_line(line, line_number=1, source_file_path="req.txt")

    assert req is not None
    assert req.hashes == expected_hashes


def test_parse_line_space_form_does_not_leak_digest_into_spec() -> None:
    """M2 regression: the space form must not raise ParseError.

    Previously the digest token survived removal and broke PEP 508 parsing.
    """
    parser = RequirementsParser()

    req = parser.parse_line("flask==2.0 --hash sha256:abc", 1, "req.txt")

    assert req is not None
    assert req.name == "flask"
    assert req.specs == [("==", "2.0")]
    assert req.hashes == ["sha256:abc"]


def test_parse_line_hash_preserves_trailing_marker() -> None:
    """A hash followed by an environment marker keeps the marker intact."""
    parser = RequirementsParser()

    req = parser.parse_line(
        "requests>=2.0 --hash sha256:xyz ; python_version<'3.9'", 1, "req.txt"
    )

    assert req is not None
    assert req.name == "requests"
    assert req.specs == [(">=", "2.0")]
    assert req.hashes == ["sha256:xyz"]
    assert req.markers is not None
    assert "python_version" in req.markers


def test_parse_file_with_mixed_hash_forms(tmp_path: Path) -> None:
    """A file mixing both hash forms parses fully without errors."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text(
        "\n".join(
            [
                "# Requirements with hashes",
                "requests==2.28.0 --hash=sha256:abc123def456",
                "django==4.0 --hash sha256:111111 --hash sha256:222222",
                "flask==2.0.1 --hash=sha256:333333",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    requirements = parser_parse(req_file)

    by_name = {req.name: req for req in requirements}
    assert by_name["requests"].hashes == ["sha256:abc123def456"]
    assert by_name["django"].hashes == ["sha256:111111", "sha256:222222"]
    assert by_name["flask"].hashes == ["sha256:333333"]


def parser_parse(path: Path) -> list:
    """Helper: parse a file with a fresh parser and return the requirements."""
    return RequirementsParser().parse_file(path)
