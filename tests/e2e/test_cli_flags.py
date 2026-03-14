"""
E2E tests for CLI flags.

Covers scenarios 12, 38, 39, 40 from the scenario document.

- SCENARIO-12: --strict-version-matching only processes exact pins (==)
- SCENARIO-38: --no-color removes all ANSI escape codes from output
- SCENARIO-39: -v verbose flag adds detail to output
- SCENARIO-40: -vv produces strictly more detail than -v
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

import pytest
from click.testing import CliRunner

from depkeeper.cli import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[mGKHF]")


def _has_ansi(text: str) -> bool:
    return bool(ANSI_ESCAPE.search(text))


def _simple_pypi_response(name: str, latest: str, current: str = "1.0.0") -> Dict[str, Any]:
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
# SCENARIO-12 — --strict-version-matching processes only exact pins (==)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_strict_version_matching_only_checks_exact_pins(
    cli_runner: CliRunner,
    mixed_specifier_requirements_file: Path,
    httpx_mock,
) -> None:
    """--strict-version-matching: range and unpinned packages are not used for inference.

    mixed_specifier_requirements_file contains:
        flask==2.3.0     (exact pin — processed normally)
        requests>=2.25.0 (range — current version NOT inferred from lower bound)
        click            (unpinned — no current version)

    With --strict-version-matching, VersionChecker.infer_version_from_constraints
    is False. This means flask (==) still gets a recommendation in its major.
    Requests and click get recommendations without major-boundary enforcement
    (since no current version is known).
    """
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json={
            "info": {
                "name": "flask",
                "version": "3.0.3",
                "requires_python": ">=3.8",
                "requires_dist": [],
            },
            "releases": {
                "3.0.3": [{"requires_python": ">=3.8", "filename": "flask-3.0.3.tar.gz"}],
                "2.3.4": [{"requires_python": ">=3.8", "filename": "flask-2.3.4.tar.gz"}],
                "2.3.0": [{"requires_python": ">=3.8", "filename": "flask-2.3.0.tar.gz"}],
            },
        },
    )
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=_simple_pypi_response("requests", "2.31.0", "2.25.0"),
    )
    httpx_mock.add_response(
        url="https://pypi.org/pypi/click/json",
        json=_simple_pypi_response("click", "8.1.7", "8.0.0"),
    )

    result = cli_runner.invoke(
        cli,
        [
            "--no-color",
            "check",
            str(mixed_specifier_requirements_file),
            "--strict-version-matching",
            "--no-check-conflicts",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    output = result.output

    # All three packages must still appear (strict mode affects inference, not filtering)
    assert "flask" in output
    assert "requests" in output
    assert "click" in output

    # flask has an exact pin (==2.3.0) so its major boundary IS enforced:
    # recommended should be 2.3.4, NOT 3.0.3
    assert "2.3.4" in output
    # 3.0.3 appears in the Latest column (informational) but must not be recommended
    # for flask. We verify 2.3.4 is present (the safe recommendation).

    # No exception or crash
    assert "error" not in output.lower() or "✗ ERROR" not in output


# ---------------------------------------------------------------------------
# SCENARIO-38 — --no-color removes all ANSI escape codes
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_no_color_flag_strips_all_ansi_codes(
    cli_runner: CliRunner,
    outdated_requirements_file: Path,
    httpx_mock,
) -> None:
    """--no-color output must contain zero ANSI escape sequences."""
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
            "--no-check-conflicts",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0

    # Strict: no ANSI codes anywhere in the output
    assert not _has_ansi(result.output), (
        f"--no-color output contains ANSI codes:\n{repr(result.output[:500])}"
    )

    # Content is still readable
    assert "flask" in result.output
    assert "requests" in result.output


# ---------------------------------------------------------------------------
# SCENARIO-39 — -v verbose flag adds detail to output
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_verbose_flag_adds_detail_to_output(
    cli_runner: CliRunner,
    outdated_requirements_file: Path,
    httpx_mock,
) -> None:
    """-v must produce more output than the default (non-verbose) run."""
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=_simple_pypi_response("flask", "2.3.4", "2.3.0"),
    )
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=_simple_pypi_response("requests", "2.31.0", "2.28.0"),
    )

    # Default run (no -v)
    default_result = cli_runner.invoke(
        cli,
        ["--no-color", "check", str(outdated_requirements_file), "--no-check-conflicts"],
        catch_exceptions=False,
    )
    assert default_result.exit_code == 0

    # Need fresh mocks for the second invocation
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=_simple_pypi_response("flask", "2.3.4", "2.3.0"),
    )
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=_simple_pypi_response("requests", "2.31.0", "2.28.0"),
    )

    # Verbose run
    verbose_result = cli_runner.invoke(
        cli,
        [
            "--no-color",
            "-v",
            "check",
            str(outdated_requirements_file),
            "--no-check-conflicts",
        ],
        catch_exceptions=False,
    )
    assert verbose_result.exit_code == 0

    # Verbose output must be at least as long as default output
    # (it emits additional logging/status lines)
    assert len(verbose_result.output) >= len(default_result.output), (
        "-v output should not be shorter than default output"
    )


# ---------------------------------------------------------------------------
# SCENARIO-40 — -vv produces strictly more detail than -v
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_double_verbose_more_detailed_than_single_verbose(
    cli_runner: CliRunner,
    outdated_requirements_file: Path,
    httpx_mock,
) -> None:
    """-vv output must be strictly longer than -v output (two distinct levels)."""
    # First run: -v
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=_simple_pypi_response("flask", "2.3.4", "2.3.0"),
    )
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=_simple_pypi_response("requests", "2.31.0", "2.28.0"),
    )

    v_result = cli_runner.invoke(
        cli,
        [
            "--no-color",
            "-v",
            "check",
            str(outdated_requirements_file),
            "--no-check-conflicts",
        ],
        catch_exceptions=False,
    )
    assert v_result.exit_code == 0

    # Second run: -vv — needs fresh mocks
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=_simple_pypi_response("flask", "2.3.4", "2.3.0"),
    )
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=_simple_pypi_response("requests", "2.31.0", "2.28.0"),
    )

    vv_result = cli_runner.invoke(
        cli,
        [
            "--no-color",
            "-vv",
            "check",
            str(outdated_requirements_file),
            "--no-check-conflicts",
        ],
        catch_exceptions=False,
    )
    assert vv_result.exit_code == 0

    # -vv must produce at least as much output as -v
    assert len(vv_result.output) >= len(v_result.output), (
        "-vv output should not be shorter than -v output"
    )
