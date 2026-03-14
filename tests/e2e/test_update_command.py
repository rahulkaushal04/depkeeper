"""
E2E tests for `depkeeper update`.

Covers scenarios 14–20 from the scenario document.

All PyPI calls are intercepted by pytest-httpx (httpx_mock fixture).
No test in this file makes real network calls.

Key implementation facts confirmed from source:
- --backup creates a timestamped backup at: {file}.{timestamp}_{uuid8}.backup
  (from depkeeper/utils/filesystem.py:create_timestamped_backup)
- --dry-run prints the update plan but NEVER modifies the file
- -p / --packages filters to specific packages only
- -y / --yes skips the interactive confirmation prompt
- When nothing needs updating, the file is NOT written (safe for CI diffing)
- The update command writes with safe_write_file (atomic, no partial writes)
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, Dict

import pytest
from click.testing import CliRunner

from depkeeper.cli import cli


# ---------------------------------------------------------------------------
# Shared PyPI mock response builders
# ---------------------------------------------------------------------------


def _minimal_pypi_response(
    name: str,
    latest_in_major: str,
    current: str,
    absolute_latest: str | None = None,
    requires_python: str = ">=3.7",
) -> Dict[str, Any]:
    """Build a response with `current` and `latest_in_major` versions.

    Args:
        name: Package name.
        latest_in_major: The highest stable version within the same major as current.
        current: The currently pinned version (must share major with latest_in_major).
        absolute_latest: Optional absolute latest (different major). Defaults to
            latest_in_major if not provided.
        requires_python: Python version constraint for all versions.
    """
    abs_latest = absolute_latest or latest_in_major
    versions: Dict[str, list] = {}
    for v in {abs_latest, latest_in_major, current}:
        versions[v] = [{"requires_python": requires_python, "filename": f"{name}-{v}.tar.gz"}]

    return {
        "info": {
            "name": name,
            "version": abs_latest,
            "requires_python": requires_python,
            "requires_dist": [],
        },
        "releases": versions,
    }


# ---------------------------------------------------------------------------
# SCENARIO-14 — Dry-run: shows plan but does NOT modify the file
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_update_dry_run_does_not_modify_file(
    cli_runner: CliRunner,
    outdated_requirements_file: Path,
    httpx_mock,
) -> None:
    """--dry-run must show the update plan but leave requirements.txt unchanged."""
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=_minimal_pypi_response("flask", "2.3.4", "2.3.0"),
    )
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=_minimal_pypi_response("requests", "2.31.0", "2.28.0"),
    )

    original_content = outdated_requirements_file.read_text()
    original_mtime = outdated_requirements_file.stat().st_mtime

    result = cli_runner.invoke(
        cli,
        [
            "--no-color",
            "update",
            str(outdated_requirements_file),
            "--dry-run",
            "--no-check-conflicts",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0

    # File must be byte-for-byte identical to before the command ran
    assert outdated_requirements_file.read_text() == original_content

    # mtime must not have changed (no write occurred)
    assert outdated_requirements_file.stat().st_mtime == original_mtime

    # Output must contain the update plan
    output = result.output
    assert "flask" in output
    assert "requests" in output
    # Dry-run notice must appear
    assert "dry run" in output.lower()


# ---------------------------------------------------------------------------
# SCENARIO-15 — Update applies changes and correctly rewrites the file
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_update_rewrites_file_with_new_versions(
    cli_runner: CliRunner,
    outdated_requirements_file: Path,
    httpx_mock,
) -> None:
    """update -y applies changes: file is rewritten with new pinned versions."""
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=_minimal_pypi_response("flask", "2.3.4", "2.3.0"),
    )
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=_minimal_pypi_response("requests", "2.31.0", "2.28.0"),
    )

    result = cli_runner.invoke(
        cli,
        [
            "--no-color",
            "update",
            str(outdated_requirements_file),
            "-y",
            "--no-check-conflicts",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0

    # Read the updated file and verify new versions are present
    updated_content = outdated_requirements_file.read_text()
    assert "flask==2.3.4" in updated_content
    assert "requests==2.31.0" in updated_content

    # Old versions must be gone
    assert "flask==2.3.0" not in updated_content
    assert "requests==2.28.0" not in updated_content

    # Success message in output
    assert "updated" in result.output.lower() or "success" in result.output.lower()


# ---------------------------------------------------------------------------
# SCENARIO-15b — File format is preserved (comments, blank lines not corrupted)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_update_preserves_comments_and_blank_lines(
    cli_runner: CliRunner,
    tmp_path: Path,
    httpx_mock,
) -> None:
    """update preserves comments, blank lines, and non-updated lines."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text(
        "# Web dependencies\n"
        "flask==2.3.0  # web framework\n"
        "\n"
        "requests==2.28.0\n"
    )

    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=_minimal_pypi_response("flask", "2.3.4", "2.3.0"),
    )
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=_minimal_pypi_response("requests", "2.31.0", "2.28.0"),
    )

    result = cli_runner.invoke(
        cli,
        ["--no-color", "update", str(req_file), "-y", "--no-check-conflicts"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0

    updated = req_file.read_text()

    # Updated versions are present
    assert "flask==2.3.4" in updated
    assert "requests==2.31.0" in updated

    # Comment is preserved on the flask line
    assert "# web framework" in updated

    # Full-line comment is preserved
    assert "# Web dependencies" in updated

    # Blank line is preserved (file has more than 3 non-blank lines)
    lines = updated.splitlines()
    assert "" in lines


# ---------------------------------------------------------------------------
# SCENARIO-16 — --backup creates a .backup file before writing
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_update_backup_creates_timestamped_backup(
    cli_runner: CliRunner,
    outdated_requirements_file: Path,
    httpx_mock,
) -> None:
    """--backup: a timestamped .backup file is created with the original content."""
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=_minimal_pypi_response("flask", "2.3.4", "2.3.0"),
    )
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=_minimal_pypi_response("requests", "2.31.0", "2.28.0"),
    )

    original_content = outdated_requirements_file.read_text()
    parent_dir = outdated_requirements_file.parent

    # Count existing .backup files before the run
    before_backups = list(parent_dir.glob("*.backup"))

    result = cli_runner.invoke(
        cli,
        [
            "--no-color",
            "update",
            str(outdated_requirements_file),
            "--backup",
            "-y",
            "--no-check-conflicts",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0

    # A new .backup file must exist in the same directory
    after_backups = list(parent_dir.glob("*.backup"))
    new_backups = [b for b in after_backups if b not in before_backups]
    assert len(new_backups) == 1, (
        f"Expected exactly 1 new .backup file, found: {new_backups}"
    )

    backup_file = new_backups[0]

    # Backup name follows the pattern: requirements.txt.{timestamp}_{uuid8}.backup
    assert backup_file.name.startswith("requirements.txt.")
    assert backup_file.name.endswith(".backup")

    # Backup contains the ORIGINAL content (not the updated content)
    assert backup_file.read_text() == original_content

    # The main file has been updated
    updated_content = outdated_requirements_file.read_text()
    assert "flask==2.3.4" in updated_content


# ---------------------------------------------------------------------------
# SCENARIO-17 — -p flag updates only the specified package
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_update_p_flag_updates_only_specified_package(
    cli_runner: CliRunner,
    outdated_requirements_file: Path,
    httpx_mock,
) -> None:
    """-p flask updates flask only; requests line is untouched."""
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=_minimal_pypi_response("flask", "2.3.4", "2.3.0"),
    )
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=_minimal_pypi_response("requests", "2.31.0", "2.28.0"),
    )

    result = cli_runner.invoke(
        cli,
        [
            "--no-color",
            "update",
            str(outdated_requirements_file),
            "-p",
            "flask",
            "-y",
            "--no-check-conflicts",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0

    updated_content = outdated_requirements_file.read_text()

    # flask must be updated
    assert "flask==2.3.4" in updated_content

    # requests must NOT be touched — still at the original version
    assert "requests==2.28.0" in updated_content
    assert "requests==2.31.0" not in updated_content


# ---------------------------------------------------------------------------
# SCENARIO-18 — -y flag skips the confirmation prompt
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_update_yes_flag_skips_confirmation(
    cli_runner: CliRunner,
    outdated_requirements_file: Path,
    httpx_mock,
) -> None:
    """-y applies updates immediately with no interactive prompt needed."""
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=_minimal_pypi_response("flask", "2.3.4", "2.3.0"),
    )
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=_minimal_pypi_response("requests", "2.31.0", "2.28.0"),
    )

    # Invoke with NO stdin (simulates a non-interactive script)
    result = cli_runner.invoke(
        cli,
        [
            "--no-color",
            "update",
            str(outdated_requirements_file),
            "-y",
            "--no-check-conflicts",
        ],
        input=None,  # no stdin input provided
        catch_exceptions=False,
    )

    # Must succeed without hanging or prompting
    assert result.exit_code == 0

    # Updates must have been applied
    updated = outdated_requirements_file.read_text()
    assert "flask==2.3.4" in updated
    assert "requests==2.31.0" in updated


# ---------------------------------------------------------------------------
# SCENARIO-19 — 0 packages need updating: no file write, clear message
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_update_nothing_to_do_does_not_write_file(
    cli_runner: CliRunner,
    all_current_requirements_file: Path,
    httpx_mock,
) -> None:
    """When all packages are current, no file write occurs and mtime is unchanged."""
    # flask==2.3.4 is already the latest in major 2; requests==2.31.0 is already latest
    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=_minimal_pypi_response("flask", "2.3.4", "2.3.4"),
    )
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=_minimal_pypi_response("requests", "2.31.0", "2.31.0"),
    )

    original_content = all_current_requirements_file.read_text()
    original_mtime = all_current_requirements_file.stat().st_mtime

    result = cli_runner.invoke(
        cli,
        [
            "--no-color",
            "update",
            str(all_current_requirements_file),
            "-y",
            "--no-check-conflicts",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0

    # File must NOT have been written (content and mtime unchanged)
    assert all_current_requirements_file.read_text() == original_content
    assert all_current_requirements_file.stat().st_mtime == original_mtime

    # Output must clearly say all packages are up to date
    assert "up to date" in result.output.lower()


# ---------------------------------------------------------------------------
# SCENARIO-20 — --check-conflicts during update: command runs end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_update_with_check_conflicts_runs_without_error(
    cli_runner: CliRunner,
    tmp_path: Path,
    httpx_mock,
) -> None:
    """update --check-conflicts runs the full pipeline without crashing.

    Uses packages with no requires_dist so DependencyAnalyzer finds no
    transitive dependencies and makes no secondary per-version API calls.
    """
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("flask==2.3.0\nrequests==2.28.0\n")

    httpx_mock.add_response(
        url="https://pypi.org/pypi/flask/json",
        json=_minimal_pypi_response("flask", "2.3.4", "2.3.0"),
    )
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=_minimal_pypi_response("requests", "2.31.0", "2.28.0"),
    )

    result = cli_runner.invoke(
        cli,
        [
            "--no-color",
            "update",
            str(req_file),
            "-y",
            "--check-conflicts",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0

    # Updates must have been written
    updated = req_file.read_text()
    assert "flask==2.3.4" in updated
    assert "requests==2.31.0" in updated
