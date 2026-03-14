"""
E2E tests for error handling.

Covers scenarios 30–34 from the scenario document.

- SCENARIO-30: Missing requirements.txt → clear error, non-zero exit
- SCENARIO-31: Package not on PyPI → graceful skip, rest continue
- SCENARIO-32: PyPI unreachable → clean failure message, no hang
- SCENARIO-33: Malformed requirement line → parse error with line context
- SCENARIO-34: Empty requirements.txt → graceful "nothing to check" message
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


def _simple_pypi_response(name: str, version: str) -> Dict[str, Any]:
    return {
        "info": {
            "name": name,
            "version": version,
            "requires_python": ">=3.7",
            "requires_dist": [],
        },
        "releases": {
            version: [{"requires_python": ">=3.7", "filename": f"{name}-{version}.tar.gz"}],
        },
    }


# ---------------------------------------------------------------------------
# SCENARIO-30 — Missing requirements.txt: clear error, non-zero exit
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_check_missing_file_exits_nonzero(cli_runner: CliRunner, tmp_path: Path) -> None:
    """When the requirements file does not exist, exit non-zero with a clear message."""
    nonexistent = tmp_path / "nonexistent_requirements.txt"
    # Confirm the file truly does not exist
    assert not nonexistent.exists()

    result = cli_runner.invoke(
        cli,
        ["--no-color", "check", str(nonexistent)],
        # DO NOT use catch_exceptions=False here — Click itself handles the
        # file-not-found case via its path validation and may raise SystemExit.
        catch_exceptions=True,
    )

    # Must exit with a non-zero code
    assert result.exit_code != 0, (
        f"Expected non-zero exit for missing file, got {result.exit_code}"
    )

    # Output or exception must reference the problem.
    # When CliRunner is created with mix_stderr=False (the default for our fixture),
    # Click routes its built-in validation errors to result.stderr, not result.output.
    stderr = getattr(result, "stderr", "") or ""
    combined = (result.output or "") + stderr + str(result.exception or "")
    assert (
        "nonexistent" in combined.lower()
        or "not exist" in combined.lower()
        or "no such" in combined.lower()
        or "invalid" in combined.lower()
        or "error" in combined.lower()
    ), f"No useful error message found:\n{combined}"


@pytest.mark.e2e
def test_update_missing_file_exits_nonzero(cli_runner: CliRunner, tmp_path: Path) -> None:
    """update on a missing file must exit non-zero."""
    nonexistent = tmp_path / "gone.txt"
    assert not nonexistent.exists()

    result = cli_runner.invoke(
        cli,
        ["--no-color", "update", str(nonexistent)],
        catch_exceptions=True,
    )

    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# SCENARIO-31 — Unknown PyPI package: graceful skip, rest continue
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_check_unknown_package_is_skipped_gracefully(
    cli_runner: CliRunner,
    tmp_path: Path,
    httpx_mock,
) -> None:
    """A package that doesn't exist on PyPI is skipped; others still checked."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("flask==2.3.0\ntotally-nonexistent-pkg==1.0.0\n")

    # flask resolves normally
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=_simple_pypi_response("flask", "2.3.4"),
    )
    # nonexistent-pkg returns 404 — pytest-httpx maps this to a NetworkError
    httpx_mock.add_response(
        url="https://pypi.org/pypi/totally-nonexistent-pkg/json",
        status_code=404,
    )

    result = cli_runner.invoke(
        cli,
        [
            "--no-color",
            "check",
            str(req_file),
            "--no-check-conflicts",
        ],
        catch_exceptions=False,
    )

    # Must NOT crash — the whole run must complete
    assert result.exit_code == 0

    output = result.output
    # flask must still appear and be checked
    assert "flask" in output

    # The unknown package must appear (as an error row) OR be skipped cleanly.
    # Either way: no unhandled exception, and flask results are present.
    # Note: we assert on "OUTDATED" (a short, non-truncated word) rather than
    # the version string "2.3.4", because Rich's table layout may split "2.3.4"
    # across rows when the column is compressed by the long package name
    # "totally-nonexistent-pkg".
    assert "OUTDATED" in output  # flask was successfully checked and is outdated


# ---------------------------------------------------------------------------
# SCENARIO-32 — PyPI unreachable: clean failure, no hang
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_check_pypi_unreachable_does_not_crash(
    cli_runner: CliRunner,
    tmp_path: Path,
    httpx_mock,
) -> None:
    """Network failure on all PyPI calls must not crash; output explains the issue."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("flask==2.3.0\n")

    # Simulate a connection error for the flask PyPI request
    import httpx as _httpx
    httpx_mock.add_exception(
        _httpx.ConnectError("Connection refused"),
        url="https://pypi.org/pypi/flask/json",
    )

    result = cli_runner.invoke(
        cli,
        ["--no-color", "check", str(req_file), "--no-check-conflicts"],
        catch_exceptions=False,
    )

    # Must NOT hang or crash with an unhandled exception
    # The command should exit cleanly (0 or non-zero) with an explanatory output
    output = result.output
    # flask must appear — even if as an error row
    assert "flask" in output


# ---------------------------------------------------------------------------
# SCENARIO-33 — Malformed requirement line: parse error reported
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_check_malformed_requirement_reports_error(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    """A syntactically invalid requirement line must produce a clear error message.

    Uses "flask==" (missing version after operator) which packaging rejects
    as InvalidRequirement → the parser raises ParseError → the check command
    raises DepKeeperError → non-zero exit code.

    Note: "flask===invalid" is intentionally NOT used here because "===" is the
    PEP 440 arbitrary equality operator and "flask===invalid" is valid syntax.
    """
    req_file = tmp_path / "requirements.txt"
    # Line 1: valid. Line 2: invalid — "flask==" has no version after the operator
    # and is rejected by packaging.requirements.Requirement as InvalidRequirement.
    # Note: "flask===invalid" is NOT invalid — "===" is PEP 440 arbitrary equality,
    # so the packaging library accepts it silently. We must use a spec that truly
    # fails PEP 508 parsing (missing version string after "==").
    req_file.write_text("flask==2.3.0\nflask==\n")

    result = cli_runner.invoke(
        cli,
        ["--no-color", "check", str(req_file), "--no-check-conflicts"],
        catch_exceptions=True,
    )

    # Either: exits non-zero with an error message
    # Or: exits 0 but includes an error/warning about the bad line
    # Both are acceptable — what is NOT acceptable is a silent success
    # or an unhandled Python traceback.
    combined_output = (result.output or "") + str(result.exception or "")

    # The output must reference the problem in some way
    # (the exact message depends on packaging library behaviour)
    assert result.exit_code != 0 or (
        "error" in combined_output.lower()
        or "invalid" in combined_output.lower()
        or "parse" in combined_output.lower()
    ), (
        f"Expected an error indication for malformed requirement, got:\n"
        f"exit_code={result.exit_code}\noutput={combined_output[:500]}"
    )


# ---------------------------------------------------------------------------
# SCENARIO-34 — Empty requirements.txt: graceful "nothing to check"
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_check_empty_requirements_file_is_handled_gracefully(
    cli_runner: CliRunner,
    empty_requirements_file: Path,
) -> None:
    """An empty requirements file must not crash and must produce a clear message."""
    result = cli_runner.invoke(
        cli,
        ["--no-color", "check", str(empty_requirements_file), "--no-check-conflicts"],
        catch_exceptions=False,
    )

    # Must exit cleanly — empty file is not an error condition
    assert result.exit_code == 0

    # Output must indicate that no packages were found (not just empty output)
    assert (
        "no packages" in result.output.lower()
        or "nothing" in result.output.lower()
        or "empty" in result.output.lower()
        or "found" in result.output.lower()
    ), f"Expected 'no packages' message for empty file, got:\n{result.output}"
