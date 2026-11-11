"""``--python-version`` accepts ASCII digits only."""

from __future__ import annotations

from typing import Any

import click
import pytest

from depkeeper.commands._report import minimum_python, python_version_option
from depkeeper.core.verify import verify_plan

_NO_CTX: Any = None


@pytest.mark.parametrize("value", ["３.９", "٣.٩", "3.９", "3.9.1a"])
def test_cli_rejects_non_ascii_digits(value: str) -> None:
    with pytest.raises(click.BadParameter):
        python_version_option(_NO_CTX, _NO_CTX, value)


def test_cli_accepts_plain_and_padded_versions() -> None:
    assert python_version_option(_NO_CTX, _NO_CTX, " 3.9 ") == "3.9"


def test_minimum_python_ignores_non_ascii_digits() -> None:
    assert minimum_python("３.９") is None


def test_verify_skips_non_ascii_target() -> None:
    result = verify_plan(["packaging==24.0"], python_version="３.９")
    assert result.skipped


def test_source_has_no_unicode_digit_patterns() -> None:
    """``\\d`` matches non-ASCII digits that ``int()`` or pip then rejects."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "depkeeper"
    offenders = [
        f"{path.relative_to(root.parent)}:{number}"
        for path in root.rglob("*.py")
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if "\\d" in line and not line.lstrip().startswith("#")
    ]
    assert offenders == []


def test_source_files_have_no_literal_invisible_characters() -> None:
    """Zero-width, bidi, BOM and line/paragraph separators must be written as escapes."""
    import unicodedata
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    offenders = [
        f"{path.relative_to(root)}:{number}"
        for folder in ("depkeeper", "tests")
        for path in (root / folder).rglob("*.py")
        for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1)
        if any(unicodedata.category(ch) in ("Cf", "Zl", "Zp") for ch in line)
    ]
    assert offenders == []
