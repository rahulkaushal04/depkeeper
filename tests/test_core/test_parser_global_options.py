"""Regression tests for pip global option parsing in requirements files."""

from __future__ import annotations

from pathlib import Path

import pytest

from depkeeper.core.parser import RequirementsParser
from depkeeper.exceptions import ParseError


@pytest.mark.parametrize(
    "line",
    [
        "--index-url https://my.index/simple",
        "--extra-index-url https://x/simple",
        "--find-links https://files.example/simple",
        "--trusted-host pypi.example.com",
        "--no-binary :all:",
        "--only-binary :all:",
        "--use-feature truststore",
        "--pre",
        "--prefer-binary",
        "--index-url=https://my.index/simple",
        "--extra-index-url=https://x/simple",
        "-i https://my.index/simple",
        "-f https://files.example/simple",
    ],
)
def test_parse_line_skips_supported_global_options(line: str) -> None:
    """Supported pip global option lines are ignored, not treated as requirements."""
    parser = RequirementsParser()

    result = parser.parse_line(line, line_number=1, source_file_path="req.txt")

    assert result is None


def test_parse_line_unknown_option_still_raises_parse_error() -> None:
    """Unknown option-like lines should still fail fast as invalid syntax."""
    parser = RequirementsParser()

    with pytest.raises(ParseError):
        parser.parse_line("--definitely-not-a-pip-option value", 1, "req.txt")


def test_parse_file_with_global_options_returns_only_requirements(tmp_path: Path) -> None:
    """Global options should not abort parsing of otherwise valid files."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text(
        "\n".join(
            [
                "--index-url https://my.index/simple",
                "--extra-index-url https://x/simple",
                "--find-links https://files.example/simple",
                "requests==2.31.0",
                "flask>=2.0",
                "--prefer-binary",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    parser = RequirementsParser()
    requirements = parser.parse_file(req_file)

    assert [req.name for req in requirements] == ["requests", "flask"]
