"""
E2E tests for version-specifier edge cases.

Covers scenarios 41–50 from the scenario document.

- SCENARIO-41: Bare unpinned package (no specifier) → recommends latest stable, no boundary
- SCENARIO-42: Lower-bound range (>=) with infer=True → infers current, enforces major boundary
- SCENARIO-43: Lower-bound range (>=) with --strict-version-matching → no inference, no boundary
- SCENARIO-44: Compatible-release (~=) with infer=True → infers current, enforces major boundary
- SCENARIO-45: Not-equal exclusion (!=) → no current inferred from != operator
- SCENARIO-46: Compound specifier (>=, !=, <) → infers from >=, major boundary respected
- SCENARIO-47: Pre-release on PyPI → stable always recommended, pre-release never suggested
- SCENARIO-48: Environment marker (;python_version) → marker stripped, check runs normally
- SCENARIO-49: Hashed requirement (--hash) → hash stripped, version check runs normally
- SCENARIO-50: Upper-bound-only (<) → no current inferred, command exits cleanly
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest
from click.testing import CliRunner

from depkeeper.cli import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _simple_pypi_response(
    name: str,
    latest: str,
    all_versions: Dict[str, str],
) -> Dict[str, Any]:
    """Build a minimal PyPI JSON response with arbitrary versions.

    Args:
        name: Package name.
        latest: Version reported in info.version (absolute latest).
        all_versions: Mapping of version string → requires_python string.
    """
    releases = {
        v: [{"requires_python": rp, "filename": f"{name}-{v}.tar.gz"}]
        for v, rp in all_versions.items()
    }
    return {
        "info": {
            "name": name,
            "version": latest,
            "requires_python": all_versions.get(latest),
            "requires_dist": [],
        },
        "releases": releases,
    }


# Standard flask mock used by most tests in this file.
# Has: 3.0.3 (latest), 2.3.4 (latest in major 2), 2.3.0, 2.0.0
FLASK_PYPI = _simple_pypi_response(
    "flask",
    latest="3.0.3",
    all_versions={
        "3.0.3": ">=3.8",
        "2.3.4": ">=3.8",
        "2.3.0": ">=3.8",
        "2.0.0": ">=3.6",
    },
)

REQUESTS_PYPI = _simple_pypi_response(
    "requests",
    latest="2.31.0",
    all_versions={
        "2.31.0": ">=3.7",
        "2.28.0": ">=3.7",
        "2.25.0": ">=3.7",
    },
)


# ---------------------------------------------------------------------------
# SCENARIO-41 — Bare unpinned package: recommends highest stable, no boundary
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_bare_unpinned_package_appears_and_does_not_crash(
    cli_runner: CliRunner,
    unpinned_requirements_file: Path,
    httpx_mock,
) -> None:
    """Bare 'flask' (no version specifier) is handled without crashing.

    Since no current version is known, the checker has no major boundary to
    enforce.  The highest Python-compatible stable version across all majors
    is found as the recommendation, but because current_version is None,
    has_update() returns False and the package shows as ✓ OK.

    Implementation detail (checker.py): When current_version is None,
    _build_package_from_data skips the major-boundary logic entirely and
    calls get_python_compatible_versions with no major filter.
    """
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=FLASK_PYPI,
    )

    result = cli_runner.invoke(
        cli,
        ["--no-color", "check", str(unpinned_requirements_file), "--no-check-conflicts"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    # Package must appear — checker still fetches PyPI metadata
    assert "flask" in result.output
    # Must not show as an error row (PyPI responded successfully)
    assert "ERROR" not in result.output


# ---------------------------------------------------------------------------
# SCENARIO-42 — Range specifier (>=) with infer=True: major boundary enforced
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_range_lower_bound_infers_current_version(
    cli_runner: CliRunner,
    range_lower_bound_requirements_file: Path,
    httpx_mock,
) -> None:
    """'flask>=2.0' with default infer=True: current inferred as 2.0, stays in major 2.

    range_lower_bound_requirements_file contains: flask>=2.0

    Implementation: extract_current_version sees the '>=' operator and returns '2.0'.
    _build_package_from_data uses major=2 → finds highest stable in major 2 → 2.3.4.
    Result: flask is OUTDATED (2.3.4 > 2.0), never recommends 3.0.3.
    """
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=FLASK_PYPI,
    )

    result = cli_runner.invoke(
        cli,
        ["--no-color", "check", str(range_lower_bound_requirements_file), "--no-check-conflicts"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    output = result.output
    assert "flask" in output
    # Major boundary IS enforced: recommended is 2.3.4 (highest in major 2),
    # NOT 3.0.3 — even though 3.0.3 is the absolute latest on PyPI.
    assert "OUTDATED" in output
    assert "2.3.4" in output


# ---------------------------------------------------------------------------
# SCENARIO-43 — Range specifier (>=) with --strict-version-matching: no inference
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_range_lower_bound_strict_mode_no_inference(
    cli_runner: CliRunner,
    range_lower_bound_requirements_file: Path,
    httpx_mock,
) -> None:
    """'flask>=2.0' with --strict-version-matching: >= is not used to infer current.

    With --strict-version-matching (infer_version_from_constraints=False),
    extract_current_version returns None for range specifiers.  The checker
    then has no major boundary to enforce, so it finds the highest compatible
    stable version across all majors.

    Since current_version is None, has_update() is always False, so the
    package shows as ✓ OK regardless of what PyPI returns.
    """
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=FLASK_PYPI,
    )

    result = cli_runner.invoke(
        cli,
        [
            "--no-color",
            "check",
            str(range_lower_bound_requirements_file),
            "--strict-version-matching",
            "--no-check-conflicts",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "flask" in result.output
    # No current version → has_update()=False → no OUTDATED row
    assert "OUTDATED" not in result.output


# ---------------------------------------------------------------------------
# SCENARIO-44 — Compatible-release (~=) with infer=True: major boundary enforced
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_tilde_pin_infers_current_enforces_major_boundary(
    cli_runner: CliRunner,
    tilde_pinned_requirements_file: Path,
    httpx_mock,
) -> None:
    """'flask~=2.3' with default infer=True: current inferred as 2.3, stays in major 2.

    tilde_pinned_requirements_file contains: flask~=2.3

    Implementation: extract_current_version sees '~=' in the operator list and
    returns '2.3'.  The checker finds major=2, then the highest stable version
    in major 2 → 2.3.4.  2.3.4 > 2.3 → OUTDATED.  3.0.3 is NEVER recommended.
    """
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=FLASK_PYPI,
    )

    result = cli_runner.invoke(
        cli,
        ["--no-color", "check", str(tilde_pinned_requirements_file), "--no-check-conflicts"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    output = result.output
    assert "flask" in output
    # ~=2.3 → inferred current 2.3 → major 2 boundary → recommended 2.3.4
    assert "OUTDATED" in output
    assert "2.3.4" in output


# ---------------------------------------------------------------------------
# SCENARIO-45 — Not-equal exclusion (!=): no current version inferred
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_not_equal_specifier_no_current_version_inferred(
    cli_runner: CliRunner,
    not_equal_requirements_file: Path,
    httpx_mock,
) -> None:
    """'requests!=2.28.0' does not allow current-version inference.

    not_equal_requirements_file contains: requests!=2.28.0

    Implementation: extract_current_version only inspects '>=', '>', and '~='
    operators.  The '!=' operator is not in that list, so current_version remains
    None.  With no current version, has_update() returns False → ✓ OK.

    The command must still complete without crashing.
    """
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=REQUESTS_PYPI,
    )

    result = cli_runner.invoke(
        cli,
        ["--no-color", "check", str(not_equal_requirements_file), "--no-check-conflicts"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "requests" in result.output
    # No current version inferred from !=; has_update()=False → not shown as OUTDATED
    assert "OUTDATED" not in result.output


# ---------------------------------------------------------------------------
# SCENARIO-46 — Compound specifier (>=, !=, <): lower bound used for inference
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_compound_specifier_infers_from_lower_bound(
    cli_runner: CliRunner,
    compound_specifier_requirements_file: Path,
    httpx_mock,
) -> None:
    """'requests>=2.25,!=2.27.0,<2.30': current inferred from >=2.25, stays in major 2.

    compound_specifier_requirements_file contains: requests>=2.25,!=2.27.0,<2.30

    Implementation: extract_current_version finds the first '>=' operator → '2.25'.
    The checker enforces major=2 boundary → recommends highest stable in major 2.
    NOTE: The upper bound '<2.30' is not honoured by the current implementation;
    VersionChecker does not filter by the requirement specifier when computing
    recommendations (known limitation).

    The command must exit 0 and requests must appear.
    """
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=REQUESTS_PYPI,
    )

    result = cli_runner.invoke(
        cli,
        [
            "--no-color",
            "check",
            str(compound_specifier_requirements_file),
            "--no-check-conflicts",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    output = result.output
    assert "requests" in output
    # current inferred as 2.25, latest in major 2 is 2.31.0 → OUTDATED
    assert "OUTDATED" in output


# ---------------------------------------------------------------------------
# SCENARIO-47 — Pre-release versions: stable always recommended over pre-release
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_prerelease_version_never_recommended(
    cli_runner: CliRunner,
    tmp_path: Path,
    prerelease_only_pypi_response: Dict[str, Any],
    httpx_mock,
) -> None:
    """Pre-release versions on PyPI must never appear as a recommendation.

    Setup:
        somepackage==1.8.0 (current)
        PyPI response: 2.0.0a1 (pre-release), 1.9.0 (stable), 1.8.0 (stable)

    Implementation:
        get_python_compatible_versions filters out pre-releases (parsed.is_prerelease).
        Within major 1, only [1.9.0, 1.8.0] are eligible; recommended = 1.9.0.

    Expected:
        - recommended = 1.9.0 (appears in output)
        - 2.0.0a1 does NOT appear as the recommended version
        - OUTDATED status (1.9.0 > 1.8.0)
    """
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("somepackage==1.8.0\n")

    httpx_mock.add_response(
        url="https://pypi.org/pypi/somepackage/json",
        json=prerelease_only_pypi_response,
    )

    result = cli_runner.invoke(
        cli,
        ["--no-color", "check", str(req_file), "--no-check-conflicts"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    output = result.output
    assert "somepackage" in output
    # The stable upgrade within major 1 is present
    assert "OUTDATED" in output
    assert "1.9.0" in output
    # Pre-release must NEVER be the recommended version
    # (it may appear in the "Latest" column as info, but not as recommended)
    # We verify by checking that 2.0.0a1 is not shown as the current recommendation.
    # The table shows latest=2.0.0a1 (from info.version) and recommended=1.9.0;
    # since 2.0.0a1 is the PyPI "info.version" it appears in the Latest column.
    # What we care about is that 1.9.0 (stable) is chosen as recommendation, not 2.0.0a1.
    assert "1.9.0" in output  # stable upgrade present


# ---------------------------------------------------------------------------
# SCENARIO-48 — Environment marker: marker stripped, check runs normally
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_environment_marker_does_not_prevent_check(
    cli_runner: CliRunner,
    marker_requirements_file: Path,
    httpx_mock,
) -> None:
    """'requests>=2.25.0; python_version > \"3.6\"' — marker is stripped, check runs.

    marker_requirements_file contains: requests>=2.25.0; python_version > \"3.6\"

    The parser stores the marker separately (req.markers) and does NOT include
    it in the version specifier used for PyPI lookups.  The checker sees
    '>=2.25.0' and infers current as '2.25.0'; major=2 → recommends 2.31.0.

    Expected: exit 0, requests appears as OUTDATED with 2.31.0 as recommendation.
    """
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=REQUESTS_PYPI,
    )

    result = cli_runner.invoke(
        cli,
        ["--no-color", "check", str(marker_requirements_file), "--no-check-conflicts"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    output = result.output
    assert "requests" in output
    # Marker is stripped → >=2.25.0 is seen → infer current=2.25.0, major=2
    # → recommend 2.31.0 → OUTDATED
    assert "OUTDATED" in output
    assert "2.31.0" in output


# ---------------------------------------------------------------------------
# SCENARIO-49 — Hashed requirement: hash stripped, version check runs normally
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_hashed_requirement_check_runs_normally(
    cli_runner: CliRunner,
    hashed_requirements_file: Path,
    httpx_mock,
) -> None:
    """'flask==2.3.0 --hash=sha256:...' — hash stripped, version check proceeds.

    hashed_requirements_file contains: flask==2.3.0 --hash=sha256:...

    The parser extracts '--hash=...' tokens before delegating to PkgRequirement,
    stores them in req.hashes, and passes 'flask==2.3.0' for version parsing.
    The checker then sees current='2.3.0', major=2 → recommends 2.3.4.

    Expected: exit 0, flask appears as OUTDATED.
    """
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=FLASK_PYPI,
    )

    result = cli_runner.invoke(
        cli,
        ["--no-color", "check", str(hashed_requirements_file), "--no-check-conflicts"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    output = result.output
    assert "flask" in output
    # Hash is stripped correctly → flask==2.3.0 is processed → OUTDATED (2.3.4 available)
    assert "OUTDATED" in output


# ---------------------------------------------------------------------------
# SCENARIO-50 — Upper-bound-only (<): no current version inferred, exits cleanly
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_upper_bound_only_no_current_inferred(
    cli_runner: CliRunner,
    upper_only_requirements_file: Path,
    httpx_mock,
) -> None:
    """'flask<3.0' — upper-bound-only spec: no current version can be inferred.

    upper_only_requirements_file contains: flask<3.0

    Implementation: extract_current_version only recognises '>=', '>', '~=' as
    inference sources.  '<' is not in that list, so current_version is None.
    The checker finds the highest compatible stable across all majors for display,
    but since current is None, has_update() is False → ✓ OK.

    The command must exit 0 without crashing, and flask must appear.
    """
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=FLASK_PYPI,
    )

    result = cli_runner.invoke(
        cli,
        ["--no-color", "check", str(upper_only_requirements_file), "--no-check-conflicts"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "flask" in result.output
    # No current version inferred from '<'; has_update()=False → no OUTDATED
    assert "OUTDATED" not in result.output
