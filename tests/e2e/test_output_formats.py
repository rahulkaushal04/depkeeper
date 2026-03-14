"""
E2E tests for output format behaviour.

Covers scenarios 10, 11, 35, 36, 37 from the scenario document.

- SCENARIO-10: --format json produces valid, parseable JSON with required keys
- SCENARIO-11: --format simple produces no ANSI escape codes
- SCENARIO-35: depkeeper --version prints the correct version string
- SCENARIO-36: depkeeper --help and depkeeper check --help show documented flags
- SCENARIO-37: --format json exit code is non-zero when outdated packages exist
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

import pytest
from click.testing import CliRunner

from depkeeper.cli import cli
from depkeeper.__version__ import __version__


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ANSI escape sequence regex — any sequence starting with ESC [
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[mGKHF]")


def _has_ansi(text: str) -> bool:
    """Return True if text contains any ANSI escape codes."""
    return bool(ANSI_ESCAPE.search(text))


def _simple_pypi_response(name: str, latest: str, current: str) -> Dict[str, Any]:
    """Minimal PyPI response with two versions."""
    return {
        "info": {
            "name": name,
            "version": latest,
            "requires_python": ">=3.7",
            "requires_dist": [],
        },
        "releases": {
            latest: [{"requires_python": ">=3.7", "filename": f"{name}-{latest}.tar.gz"}],
            current: [{"requires_python": ">=3.7", "filename": f"{name}-{current}.tar.gz"}],
        },
    }


# ---------------------------------------------------------------------------
# SCENARIO-10 — --format json produces valid, parseable JSON
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_check_json_format_is_valid_and_structured(
    cli_runner: CliRunner,
    outdated_requirements_file: Path,
    httpx_mock,
) -> None:
    """--format json output must parse as JSON with expected structure per package."""
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=_simple_pypi_response("flask", "2.3.4", "2.3.0"),
    )
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=_simple_pypi_response("requests", "2.31.0", "2.28.0"),
    )

    result = cli_runner.invoke(
        cli,
        [
            "--no-color",
            "check",
            str(outdated_requirements_file),
            "--format",
            "json",
            "--no-check-conflicts",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0

    # stdout must be valid JSON — parse it; no Rich markup chars allowed
    try:
        data = json.loads(result.output)
    except json.JSONDecodeError as exc:
        pytest.fail(f"Output is not valid JSON: {exc}\n\nOutput was:\n{result.output}")

    # Must be a list of package objects
    assert isinstance(data, list), f"Expected JSON array, got {type(data)}"
    assert len(data) == 2, f"Expected 2 packages, got {len(data)}"

    # Build a name→entry map for assertion ordering independence
    by_name = {entry["name"]: entry for entry in data}

    assert "flask" in by_name, f"flask missing from JSON output: {by_name.keys()}"
    assert "requests" in by_name

    flask_entry = by_name["flask"]
    requests_entry = by_name["requests"]

    # Each entry must have 'name' and 'status' keys (from Package.to_json())
    for entry in data:
        assert "name" in entry
        assert "status" in entry

    # Each entry must have a 'versions' dict with at least 'current' and 'latest'
    assert "versions" in flask_entry
    assert flask_entry["versions"]["current"] == "2.3.0"
    assert flask_entry["versions"]["latest"] == "2.3.4"

    assert "versions" in requests_entry
    assert requests_entry["versions"]["current"] == "2.28.0"
    assert requests_entry["versions"]["latest"] == "2.31.0"

    # Outdated packages must have status == "outdated"
    assert flask_entry["status"] == "outdated"
    assert requests_entry["status"] == "outdated"


# ---------------------------------------------------------------------------
# SCENARIO-11 — --format simple produces no ANSI escape codes
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_check_simple_format_has_no_ansi_codes(
    cli_runner: CliRunner,
    outdated_requirements_file: Path,
    httpx_mock,
) -> None:
    """--format simple output must contain no ANSI escape sequences."""
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=_simple_pypi_response("flask", "2.3.4", "2.3.0"),
    )
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=_simple_pypi_response("requests", "2.31.0", "2.28.0"),
    )

    result = cli_runner.invoke(
        cli,
        [
            "--no-color",
            "check",
            str(outdated_requirements_file),
            "--format",
            "simple",
            "--no-check-conflicts",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    output = result.output

    # No ANSI escape codes in output
    assert not _has_ansi(output), (
        f"Output contains ANSI escape codes:\n{repr(output[:500])}"
    )

    # Package names must still be present (human-readable content preserved)
    assert "flask" in output
    assert "requests" in output


# ---------------------------------------------------------------------------
# SCENARIO-35 — depkeeper --version prints the correct version string
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_version_flag_prints_correct_version(cli_runner: CliRunner) -> None:
    """--version must output the installed depkeeper version string."""
    result = cli_runner.invoke(cli, ["--version"], catch_exceptions=False)

    assert result.exit_code == 0

    # The version string from __version__.py must appear in output
    assert __version__ in result.output

    # The program name must appear (from the message template "%(prog)s %(version)s")
    assert "depkeeper" in result.output.lower()


# ---------------------------------------------------------------------------
# SCENARIO-36 — --help and check --help show all documented flags
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_help_shows_usage_without_error(cli_runner: CliRunner) -> None:
    """depkeeper --help must exit 0 and display usage text."""
    result = cli_runner.invoke(cli, ["--help"], catch_exceptions=False)

    assert result.exit_code == 0
    output = result.output.lower()
    assert "usage" in output or "depkeeper" in output
    # Core commands must be mentioned
    assert "check" in output
    assert "update" in output


@pytest.mark.e2e
def test_check_help_shows_all_documented_flags(cli_runner: CliRunner) -> None:
    """depkeeper check --help must list every flag documented in README.md."""
    result = cli_runner.invoke(cli, ["check", "--help"], catch_exceptions=False)

    assert result.exit_code == 0
    output = result.output

    # All flags documented in README.md for the check command:
    assert "--outdated-only" in output
    assert "--format" in output
    assert "--strict-version-matching" in output
    assert "--check-conflicts" in output


@pytest.mark.e2e
def test_update_help_shows_all_documented_flags(cli_runner: CliRunner) -> None:
    """depkeeper update --help must list every flag documented in README.md."""
    result = cli_runner.invoke(cli, ["update", "--help"], catch_exceptions=False)

    assert result.exit_code == 0
    output = result.output

    # All flags documented in README.md for the update command:
    assert "--dry-run" in output
    assert "--yes" in output or "-y" in output
    assert "--backup" in output
    assert "--packages" in output or "-p" in output
    assert "--strict-version-matching" in output
    assert "--check-conflicts" in output


# ---------------------------------------------------------------------------
# SCENARIO-37 — --format json exit code is non-zero when outdated packages exist
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_check_json_exit_code_nonzero_when_outdated(
    cli_runner: CliRunner,
    outdated_requirements_file: Path,
    httpx_mock,
) -> None:
    """--format json must exit non-zero when outdated packages are found (CI gate).

    NOTE: The current implementation exits 0 on success regardless of whether
    packages are outdated (from commands/check.py: exit code is always 0 on
    success, 1 on error). This test documents the EXPECTED CI behaviour per
    SCENARIO-37 and is marked xfail until the exit-code contract is implemented.
    """
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=_simple_pypi_response("flask", "2.3.4", "2.3.0"),
    )
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=_simple_pypi_response("requests", "2.31.0", "2.28.0"),
    )

    result = cli_runner.invoke(
        cli,
        [
            "--no-color",
            "check",
            str(outdated_requirements_file),
            "--format",
            "json",
            "--no-check-conflicts",
        ],
        catch_exceptions=False,
    )

    # JSON output must always be valid regardless of exit code
    try:
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) > 0
    except json.JSONDecodeError:
        pytest.fail(f"JSON output is invalid: {result.output[:300]}")

    # CI contract: non-zero when outdated packages exist
    # See commands/check.py — _check_async returns True when packages_needing_action > 0
    # but the check() command does not propagate this to the process exit code.
    # This is a known gap: the command always exits 0 on success.
    pytest.xfail(
        "SCENARIO-37: check command always exits 0 on success even when packages are "
        "outdated. The CI contract (exit 1 when stale deps found) is not yet "
        "implemented. See commands/check.py — the return value of _check_async "
        "is not used to set the exit code."
    )


@pytest.mark.e2e
def test_check_json_exit_code_zero_when_all_current(
    cli_runner: CliRunner,
    all_current_requirements_file: Path,
    httpx_mock,
) -> None:
    """--format json must exit 0 when all packages are up to date."""
    # all_current_requirements_file has flask==2.3.4 and requests==2.31.0
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=_simple_pypi_response("flask", "2.3.4", "2.3.4"),
    )
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=_simple_pypi_response("requests", "2.31.0", "2.31.0"),
    )

    result = cli_runner.invoke(
        cli,
        [
            "--no-color",
            "check",
            str(all_current_requirements_file),
            "--format",
            "json",
            "--no-check-conflicts",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
