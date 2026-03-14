"""
Integration tests: RequirementsParser → VersionChecker pipeline.

Covers SCENARIO-51 from the scenario document.

These tests exercise the handoff between the parser and the version checker,
verifying that Requirement objects produced by RequirementsParser are consumed
correctly by VersionChecker to produce accurate Package results.

No real network calls are made: the PyPIDataStore is pre-seeded with
PyPIPackageData from the conftest fixtures.
"""

from __future__ import annotations

from typing import List

import pytest

from depkeeper.core.checker import VersionChecker
from depkeeper.core.data_store import PyPIDataStore, PyPIPackageData
from depkeeper.core.parser import RequirementsParser
from depkeeper.models.package import Package
from depkeeper.models.requirement import Requirement


# ---------------------------------------------------------------------------
# SCENARIO-51 — Parser output feeds directly into VersionChecker
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_parser_output_feeds_into_checker(
    version_checker_with_infer: VersionChecker,
    parser: RequirementsParser,
) -> None:
    """Parser → VersionChecker pipeline produces correct Package objects.

    Steps:
    1. Parse 'flask==2.3.0\\nrequests==2.28.0\\n' via RequirementsParser.
    2. Feed the parsed Requirement list into VersionChecker.check_packages.
    3. Verify each Package has correct name, current_version, recommended_version.

    The data store is pre-seeded (no HTTP) with:
      - flask: latest=3.0.3, latest in major 2 = 2.3.4
      - requests: latest=2.31.0 (single major)
    """
    requirements = parser.parse_string("flask==2.3.0\nrequests==2.28.0\n")

    # Sanity: parser must produce 2 requirements with correct names
    assert len(requirements) == 2
    req_names = {r.name for r in requirements}
    assert req_names == {"flask", "requests"}

    packages: List[Package] = await version_checker_with_infer.check_packages(requirements)

    assert len(packages) == 2
    by_name = {p.name: p for p in packages}

    # --- flask ---
    flask = by_name["flask"]
    assert flask.current_version == "2.3.0"
    assert flask.latest_version == "3.0.3"
    # Major boundary enforced: recommended stays in major 2
    assert flask.recommended_version == "2.3.4"
    assert flask.has_update()  # 2.3.4 > 2.3.0

    # --- requests ---
    requests = by_name["requests"]
    assert requests.current_version == "2.28.0"
    assert requests.latest_version == "2.31.0"
    assert requests.recommended_version == "2.31.0"
    assert requests.has_update()  # 2.31.0 > 2.28.0


@pytest.mark.integration
async def test_parser_extracts_current_version_from_exact_pin(
    version_checker_with_infer: VersionChecker,
    parser: RequirementsParser,
) -> None:
    """VersionChecker receives exact-pin current version from parser.

    An '==' specifier must yield current_version equal to the pinned value.
    VersionChecker.extract_current_version() handles this in the '==' branch.
    """
    requirements = parser.parse_string("flask==2.3.0\n")
    assert len(requirements) == 1
    req = requirements[0]
    assert req.specs == [("==", "2.3.0")]

    # extract_current_version uses the == specifier directly
    inferred = version_checker_with_infer.extract_current_version(req)
    assert inferred == "2.3.0"


@pytest.mark.integration
async def test_parser_extracts_current_version_from_range_specifier(
    version_checker_with_infer: VersionChecker,
    parser: RequirementsParser,
) -> None:
    """With infer=True, '>=' specifier is used to infer current version.

    'flask>=2.0' → current version inferred as '2.0', major boundary = 2.
    """
    requirements = parser.parse_string("flask>=2.0\n")
    assert len(requirements) == 1
    req = requirements[0]

    inferred = version_checker_with_infer.extract_current_version(req)
    assert inferred == "2.0"


@pytest.mark.integration
async def test_strict_mode_does_not_infer_from_range(
    version_checker_no_infer: VersionChecker,
    parser: RequirementsParser,
) -> None:
    """With infer=False (strict mode), range specifiers yield no current version.

    'flask>=2.0' → current version is None; no major boundary enforcement.
    """
    requirements = parser.parse_string("flask>=2.0\n")
    req = requirements[0]

    inferred = version_checker_no_infer.extract_current_version(req)
    assert inferred is None


@pytest.mark.integration
async def test_unavailable_package_returns_stub(
    version_checker_with_infer: VersionChecker,
    parser: RequirementsParser,
) -> None:
    """A package not in the data store returns an unavailable stub Package.

    VersionChecker.check_packages catches PyPIError from missing packages
    and substitutes an unavailable stub (latest=None, recommended=None).

    The 'totally-missing' package is not seeded in data_store_with_flask_and_requests,
    so get_package_data raises PyPIError.  The stub is returned instead.
    """
    requirements = parser.parse_string("totally-missing==1.0.0\n")
    packages = await version_checker_with_infer.check_packages(requirements)

    assert len(packages) == 1
    stub = packages[0]
    assert stub.name == "totally-missing"
    assert stub.current_version == "1.0.0"
    assert stub.latest_version is None
    assert stub.recommended_version is None
    assert not stub.has_update()


@pytest.mark.integration
async def test_all_packages_up_to_date_returns_no_update(
    version_checker_with_infer: VersionChecker,
    parser: RequirementsParser,
) -> None:
    """Packages already at their latest version have has_update() == False.

    flask==2.3.4 is the highest in major 2 (the data store has no 2.x > 2.3.4),
    so the checker recommends 2.3.4, which equals current → no update available.
    """
    requirements = parser.parse_string("flask==2.3.4\nrequests==2.31.0\n")
    packages = await version_checker_with_infer.check_packages(requirements)

    by_name = {p.name: p for p in packages}
    assert not by_name["flask"].has_update()
    assert not by_name["requests"].has_update()


@pytest.mark.integration
async def test_comments_and_blank_lines_stripped_before_checker(
    version_checker_with_infer: VersionChecker,
    parser: RequirementsParser,
) -> None:
    """Comments and blank lines are stripped by the parser before checker sees them.

    The checker must only receive real package requirements, never comment lines.
    """
    content = (
        "# This is a header comment\n"
        "flask==2.3.0  # inline comment\n"
        "\n"
        "# Another comment\n"
        "requests==2.28.0\n"
    )
    requirements = parser.parse_string(content)

    # Exactly 2 real packages, no comment noise
    assert len(requirements) == 2
    assert {r.name for r in requirements} == {"flask", "requests"}

    # Checker sees only real packages
    packages = await version_checker_with_infer.check_packages(requirements)
    assert len(packages) == 2
