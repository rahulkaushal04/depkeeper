"""Tests for deterministic, source-faithful specifier ordering.

``packaging`` stores specifiers in an unordered ``frozenset``, so iteration
order varies between processes under PEP 456 string hash randomisation. Since
M5 made the update writer preserve multiple specifiers per line, an unstable
order would produce spurious, non-reproducible diffs in requirements files.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from depkeeper.core.parser import RequirementsParser, _ordered_specs
from packaging.requirements import Requirement as PkgRequirement


@pytest.mark.unit
class TestOrderedSpecs:
    """Unit tests for the ordering helper."""

    def test_source_order_is_preserved(self) -> None:
        spec = "flask>=2.0,<3,!=2.1"
        parsed = PkgRequirement(spec)
        assert _ordered_specs(parsed.specifier, spec) == [
            (">=", "2.0"),
            ("<", "3"),
            ("!=", "2.1"),
        ]

    def test_spaced_specifiers_sort_deterministically(self) -> None:
        """Specifiers not found verbatim still get a stable total order."""
        spec = "flask >= 2.0, < 3"
        parsed = PkgRequirement(spec)
        assert _ordered_specs(parsed.specifier, spec) == [
            ("<", "3"),
            (">=", "2.0"),
        ]

    def test_single_specifier(self) -> None:
        spec = "flask==2.0"
        parsed = PkgRequirement(spec)
        assert _ordered_specs(parsed.specifier, spec) == [("==", "2.0")]


@pytest.mark.unit
class TestParserSpecOrder:
    """End-to-end ordering through the parser."""

    def test_parsed_specs_follow_the_line(self) -> None:
        req = RequirementsParser().parse_string("celery>=5.0,<6.0,!=5.2.0")[0]
        assert req.specs == [(">=", "5.0"), ("<", "6.0"), ("!=", "5.2.0")]

    def test_order_is_stable_across_processes(self) -> None:
        """Separate interpreters (fresh hash seeds) must agree on the order."""
        code = (
            "from depkeeper.core.parser import RequirementsParser;"
            "print(RequirementsParser()"
            ".parse_string('celery>=5.0,<6.0,!=5.2.0')[0].specs)"
        )
        results = {
            subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            for _ in range(5)
        }
        assert len(results) == 1
