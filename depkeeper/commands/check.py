"""
Check command implementation.

Checks requirements file for available updates and displays results.
"""

from __future__ import annotations

import sys
import json
import click
import asyncio
from typing import List, Dict, Any
from pathlib import Path

from depkeeper.models.package import Package
from depkeeper.utils.logger import get_logger
from depkeeper.exceptions import DepKeeperError
from depkeeper.core.checker import VersionChecker
from depkeeper.utils.progress import ProgressTracker
from depkeeper.core.parser import RequirementsParser
from depkeeper.context import pass_context, DepKeeperContext
from depkeeper.utils.console import (
    print_success,
    print_error,
    print_warning,
    print_info,
    print_table,
)

logger = get_logger("commands.check")


# ============================================================================
# Check Command
# ============================================================================


@click.command()
@click.argument(
    "file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default="requirements.txt",
)
@click.option(
    "--outdated-only",
    is_flag=True,
    help="Show only packages with available updates.",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["table", "simple", "json"], case_sensitive=False),
    default="table",
    help="Output format.",
)
@click.option(
    "--no-extract-ranges",
    is_flag=True,
    help="Disable extracting baseline versions from range constraints (>=, >, ~=).",
)
@pass_context
def check(
    ctx: DepKeeperContext,
    file: Path,
    outdated_only: bool,
    format: str,
    no_extract_ranges: bool,
) -> None:
    """
    Check requirements file for available updates.

    Scans the requirements file, queries PyPI for each package,
    and displays current vs. latest versions.

    Examples:

        # Check default requirements.txt
        depkeeper check

        # Check specific file
        depkeeper check requirements-dev.txt

        # Show only outdated packages
        depkeeper check --outdated-only

    Exit codes:
        0 - No updates available
        1 - Updates available or error occurred
    """
    try:
        # Run async check
        has_updates = asyncio.run(
            _check_async(ctx, file, outdated_only, format, not no_extract_ranges)
        )

        # Exit with appropriate code
        sys.exit(1 if has_updates else 0)

    except DepKeeperError as e:
        print_error(f"{e}")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        logger.exception("Error in check command")
        sys.exit(1)


# ============================================================================
# Async Implementation
# ============================================================================


async def _check_async(
    ctx: DepKeeperContext,
    file: Path,
    outdated_only: bool,
    format: str,
    extract_from_ranges: bool,
) -> bool:
    """
    Async implementation of check command.

    Parameters
    ----------
    ctx : DepKeeperContext
        CLI context.
    file : Path
        Requirements file path.
    outdated_only : bool
        Whether to show only outdated packages.
    format : str
        Output format.
    extract_from_ranges : bool
        Whether to extract baseline versions from range constraints.

    Returns
    -------
    bool
        True if updates are available, False otherwise.
    """
    print_info(f"Checking {file}...")

    # Parse requirements file
    parser = RequirementsParser()
    try:
        requirements = parser.parse_file(file)
    except Exception as e:
        raise DepKeeperError(f"Failed to parse {file}: {e}") from e

    # Early return if no requirements found
    if not requirements:
        print_warning("No packages found in requirements file")
        return False

    print_info(f"Found {len(requirements)} package(s)")

    # Check versions with progress tracking
    packages = await _check_packages_with_progress(
        requirements, ctx.verbose > 0, extract_from_ranges
    )

    # Filter outdated if requested
    if outdated_only:
        packages = [p for p in packages if p.has_update()]

    # Display results
    if not packages:
        if outdated_only:
            print_success("All packages are up to date!")
        else:
            print_warning("No packages to display")
        return False

    # Count updates
    outdated_count = sum(1 for p in packages if p.has_update())

    # Display based on format
    if format == "table":
        _display_table(packages)
    elif format == "simple":
        _display_simple(packages)
    elif format == "json":
        _display_json(packages)

    # Summary
    if outdated_count > 0:
        print_warning(f"\n{outdated_count} package(s) have updates available")
    else:
        print_success("\nAll packages are up to date!")

    return outdated_count > 0


async def _check_packages_with_progress(
    requirements: list,
    show_progress: bool,
    extract_from_ranges: bool,
) -> List[Package]:
    """Check packages with optional progress display.

    Parameters
    ----------
    requirements : list
        List of requirements to check.
    show_progress : bool
        Whether to show progress bar.
    extract_from_ranges : bool
        Whether to extract baseline versions from range constraints.

    Returns
    -------
    List[Package]
        List of checked packages.
    """
    async with VersionChecker(extract_from_ranges=extract_from_ranges) as checker:
        if show_progress:
            return await _check_with_progress(checker, requirements)
        else:
            return await checker.check_multiple(requirements)


async def _check_with_progress(
    checker: VersionChecker,
    requirements: list,
) -> List[Package]:
    """Check packages with progress tracking."""
    tracker = ProgressTracker(transient=False)
    tracker.start()
    task = tracker.add_task(
        "Checking packages...",
        total=len(requirements),
    )

    packages = []
    results_log = []

    for i, req in enumerate(requirements):
        try:
            current_version = checker._extract_current_version(req)
            tracker.update(task, description=f"Checking {req.name}...", completed=i)

            package = await checker.check_package(
                req.name,
                current_version=current_version,
            )

            if package.has_update():
                results_log.append(
                    f"[{i+1}/{len(requirements)}] {req.name}: {package.current_version} -> {package.latest_version}"
                )
            else:
                results_log.append(
                    f"[{i+1}/{len(requirements)}] {req.name}: {package.current_version} (up-to-date)"
                )

            packages.append(package)
        except Exception as e:
            results_log.append(f"[{i+1}/{len(requirements)}] {req.name}: ERROR - {e}")
            current_version = checker._extract_current_version(req)
            packages.append(Package(name=req.name, current_version=current_version))

        tracker.update(task, advance=1)

    tracker.update(task, description=f"Checked {len(requirements)} package(s)")
    tracker.stop()

    for result in results_log:
        logger.debug(result)

    return packages


# ============================================================================
# Display Functions
# ============================================================================


def _display_table(packages: List[Package]) -> None:
    """Display packages as a formatted table with color-coded status."""
    # Prepare data with Rich markup for styling
    data = [_create_table_row(pkg) for pkg in packages]

    # Define column styles
    column_styles = {
        "Status": {"justify": "center", "no_wrap": True, "width": 8},
        "Package": {"style": "cyan", "no_wrap": True},
        "Current": {"justify": "center"},
        "Latest": {"justify": "center"},
        "Type": {"justify": "center"},
    }

    # Use enhanced print_table utility
    print_table(data, title="Package Status", column_styles=column_styles)


def _create_table_row(pkg: Package) -> Dict[str, str]:
    """Create a table row dict for a package with Rich markup.

    Parameters
    ----------
    pkg : Package
        Package to create row for.

    Returns
    -------
    Dict[str, str]
        Dictionary with Status, Package, Current, Latest, and Type keys.
    """
    if not pkg.latest_version:
        # Error case - package not found or failed to fetch
        return {
            "Status": "[red]ERROR[/red]",
            "Package": pkg.name,
            "Current": pkg.current_version or "[dim]-[/dim]",
            "Latest": "[red]error[/red]",
            "Type": "[dim]-[/dim]",
        }

    if pkg.has_update():
        # Outdated - needs update
        update_type = _get_update_type(pkg)
        colored_type = _colorize_update_type(update_type)

        return {
            "Status": "[yellow]UPDATE[/yellow]",
            "Package": pkg.name,
            "Current": pkg.current_version or "[dim]-[/dim]",
            "Latest": pkg.latest_version,
            "Type": colored_type,
        }

    # Up to date
    return {
        "Status": "[green]OK[/green]",
        "Package": pkg.name,
        "Current": pkg.current_version or "[dim]-[/dim]",
        "Latest": pkg.latest_version or "[dim]-[/dim]",
        "Type": "[dim]-[/dim]",
    }


def _colorize_update_type(update_type: str) -> str:
    """Apply color coding to update type.

    Parameters
    ----------
    update_type : str
        Update type (major, minor, patch, etc.).

    Returns
    -------
    str
        Color-coded update type with Rich markup.
    """
    color_map = {
        "major": "red",
        "minor": "yellow",
        "patch": "green",
    }

    color = color_map.get(update_type)
    if color:
        return f"[{color}]{update_type}[/{color}]"
    return update_type


def _display_simple(packages: List[Package]) -> None:
    """Display packages in simple text format."""
    from depkeeper.utils.console import get_raw_console

    console = get_raw_console()

    for pkg in packages:
        status, current, latest = _get_simple_status(pkg)
        console.print(f"[{status}] {pkg.name}: {current} -> {latest}")


def _get_simple_status(pkg: Package) -> tuple[str, str, str]:
    """Get simple status tuple for package.

    Parameters
    ----------
    pkg : Package
        Package to get status for.

    Returns
    -------
    tuple[str, str, str]
        (status, current_version, latest_version) tuple.
    """
    if not pkg.latest_version:
        return "ERROR", pkg.current_version or "unknown", "not found"

    if pkg.has_update():
        return "UPDATE", pkg.current_version or "unknown", pkg.latest_version

    return "OK", pkg.current_version or "unknown", pkg.latest_version or "unknown"


def _display_json(packages: List[Package]) -> None:
    """Display packages as JSON."""
    data = [_create_json_entry(pkg) for pkg in packages]
    print(json.dumps(data, indent=2))


def _create_json_entry(pkg: Package) -> Dict[str, Any]:
    """Create JSON entry for a package.

    Parameters
    ----------
    pkg : Package
        Package to create entry for.

    Returns
    -------
    Dict[str, Any]
        JSON-serializable dictionary with package information.
    """
    entry = {
        "name": pkg.name,
        "current_version": pkg.current_version,
        "latest_version": pkg.latest_version,
        "has_update": pkg.has_update(),
        "update_type": _get_update_type(pkg),
    }

    # Add error field if package fetch failed
    if not pkg.latest_version:
        entry["error"] = "Package not found or failed to fetch from PyPI"

    return entry


def _get_update_type(pkg: Package) -> str:
    """
    Determine update type (major, minor, patch, etc.).

    Parameters
    ----------
    pkg : Package
        Package to analyze.

    Returns
    -------
    str
        Update type description.
    """
    if not pkg.has_update:
        return "-"

    if not pkg.current_version or not pkg.latest_version:
        return "unknown"

    try:
        from packaging.version import parse

        current = parse(pkg.current_version)
        latest = parse(pkg.latest_version)

        # Check if versions have release segments
        if hasattr(current, "release") and hasattr(latest, "release"):
            c_parts = current.release
            l_parts = latest.release

            if len(c_parts) >= 1 and len(l_parts) >= 1:
                if c_parts[0] != l_parts[0]:
                    return "major"
                elif (
                    len(c_parts) >= 2 and len(l_parts) >= 2 and c_parts[1] != l_parts[1]
                ):
                    return "minor"
                elif (
                    len(c_parts) >= 3 and len(l_parts) >= 3 and c_parts[2] != l_parts[2]
                ):
                    return "patch"
                else:
                    return "update"

        return "update"

    except Exception:
        return "unknown"
