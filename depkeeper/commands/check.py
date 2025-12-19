"""
Check command implementation.

Checks requirements file for available updates and displays results.
"""

from __future__ import annotations

import sys
import json
import click
import asyncio
from pathlib import Path
from typing import List, Dict
from packaging.version import parse

from depkeeper.models.package import Package
from depkeeper.utils.logger import get_logger
from depkeeper.exceptions import DepKeeperError
from depkeeper.core.checker import VersionChecker
from depkeeper.models.requirement import Requirement
from depkeeper.utils.progress import ProgressTracker
from depkeeper.core.parser import RequirementsParser
from depkeeper.utils.version_utils import get_update_type
from depkeeper.context import pass_context, DepKeeperContext
from depkeeper.utils.console import (
    print_success,
    print_error,
    print_warning,
    print_info,
    print_table,
    colorize_update_type,
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
    async with VersionChecker(extract_from_ranges=extract_from_ranges) as checker:
        packages = await _check_with_progress(checker, requirements)

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

    # Count packages needing action (updates or incompatibilities)
    packages_needing_action = sum(
        1 for p in packages if p.has_update() or p.needs_action()
    )

    # Display based on format
    if format == "table":
        _display_table(packages)
    elif format == "simple":
        _display_simple(packages)
    elif format == "json":
        _display_json(packages)

    # Summary
    if packages_needing_action > 0:
        print_warning(f"\n{packages_needing_action} package(s) have updates available")
    else:
        print_success("\nAll packages are up to date!")

    return packages_needing_action > 0


async def _check_with_progress(
    checker: VersionChecker,
    requirements: List[Requirement],
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
            current_version = checker.extract_current_version(req)
            tracker.update(task, description=f"Checking {req.name}...", completed=i)

            package = await checker.get_package_info(
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
            current_version = checker.extract_current_version(req)
            packages.append(checker.create_error_package(req.name, current_version))

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
        "Status": {"justify": "center", "no_wrap": True, "width": 10},
        "Package": {"style": "bold cyan", "no_wrap": True},
        "Current": {"justify": "center", "style": "dim"},
        "Latest": {"justify": "center", "style": "bold green"},
        "Safe Upgrade": {"justify": "center", "style": "bright_cyan"},
        "Update": {"justify": "center"},
        "Python Requires": {"justify": "left", "no_wrap": False},
    }

    # Use enhanced print_table utility
    print_table(data, title="Dependency Status", column_styles=column_styles)


def _create_table_row(pkg: Package) -> Dict[str, str]:
    """Create a table row dict for a package with Rich markup.

    Parameters
    ----------
    pkg : Package
        Package to create row for.

    Returns
    -------
    Dict[str, str]
        Dictionary with Status, Package Name, Current, Available, Suggested, Update Type, and Python Req.
    """
    # Get Python requirements for all versions
    python_reqs = pkg.format_python_requirements()

    if not pkg.latest_version:
        # Error case - package not found or failed to fetch
        return {
            "Status": "[red]✗ ERROR[/red]",
            "Package": pkg.name,
            "Current": pkg.current_version or "[dim]-[/dim]",
            "Latest": "[red]error[/red]",
            "Safe Upgrade": "[dim]-[/dim]",
            "Update": "[dim]-[/dim]",
            "Python Requires": "[dim]-[/dim]",
        }

    # Determine the target version for comparison and display
    # Safe upgrade version now shows max version within same major version
    target_version = None
    safe_upgrade_display = "[dim]-[/dim]"
    needs_downgrade = False

    if pkg.has_safe_upgrade_version():
        # There's a max safe upgrade version within same major version
        target_version = pkg.safe_upgrade_version

        # Only show safe upgrade version if it's different from current
        # (i.e., there's actually an upgrade available)
        if pkg.current_version and pkg.safe_upgrade_version != pkg.current_version:
            safe_upgrade_display = (
                f"[bright_cyan]{pkg.safe_upgrade_version}[/bright_cyan]"
            )
        else:
            # Current == safe upgrade, so no upgrade available - show as "-"
            safe_upgrade_display = "[dim]-[/dim]"

        # Check if current version is newer than max compatible (needs downgrade)
        if pkg.current_version:
            try:
                needs_downgrade = parse(pkg.current_version) > parse(target_version)
            except Exception:
                pass
    else:
        # No safe upgrade version found within same major, use latest
        target_version = pkg.latest_version
        # Only show latest as safe upgrade if it's different from current
        if pkg.current_version and pkg.latest_version != pkg.current_version:
            safe_upgrade_display = f"[green]{pkg.latest_version}[/green]"
        else:
            safe_upgrade_display = "[dim]-[/dim]"

    # Check if update is available based on target version
    has_update = False
    if target_version and pkg.current_version:
        try:
            has_update = parse(target_version) > parse(pkg.current_version)
        except Exception:
            has_update = target_version != pkg.current_version
    elif target_version and not pkg.current_version:
        has_update = True

    if needs_downgrade:
        # Current version is incompatible, needs downgrade to compatible version
        return {
            "Status": "[red]⚠ INCOMP[/red]",
            "Package": pkg.name,
            "Current": pkg.current_version or "[dim]-[/dim]",
            "Latest": pkg.latest_version,
            "Safe Upgrade": safe_upgrade_display,
            "Update": "[red]downgrade[/red]",
            "Python Requires": python_reqs,
        }

    if has_update:
        # Update available to target version
        update_type = get_update_type(pkg.current_version, target_version)
        colored_type = colorize_update_type(update_type)

        return {
            "Status": "[yellow]↑ UPDATE[/yellow]",
            "Package": pkg.name,
            "Current": pkg.current_version or "[dim]-[/dim]",
            "Latest": pkg.latest_version,
            "Safe Upgrade": safe_upgrade_display,
            "Update": colored_type,
            "Python Requires": python_reqs,
        }

    # Up to date - current >= target version
    return {
        "Status": "[green]✓ OK[/green]",
        "Package": pkg.name,
        "Current": pkg.current_version or "[dim]-[/dim]",
        "Latest": pkg.latest_version or "[dim]-[/dim]",
        "Safe Upgrade": safe_upgrade_display,
        "Update": "[dim]-[/dim]",
        "Python Requires": python_reqs,
    }


def _display_simple(packages: List[Package]) -> None:
    """Display packages in simple text format."""
    from depkeeper.utils.console import get_raw_console

    console = get_raw_console()

    for pkg in packages:
        status, installed, latest, safe_upgrade = pkg.get_simple_status(pkg)

        # Show status with versions
        if safe_upgrade and safe_upgrade != latest:
            console.print(
                f"[{status}] {pkg.name:20} {installed:10} → {latest:10} (safe: {safe_upgrade})"
            )
        else:
            console.print(f"[{status}] {pkg.name:20} {installed:10} → {latest:10}")

        # Add Python compatibility information
        current_req = pkg.get_version_python_req("current")
        latest_req = pkg.get_requires_python()
        if current_req or latest_req:
            req_parts = []
            if current_req:
                req_parts.append(f"current: {current_req}")
            if latest_req:
                req_parts.append(f"latest: {latest_req}")
            if pkg.has_safe_upgrade_version():
                safe_req = pkg.get_version_python_req("safe_upgrade")
                if safe_req:
                    req_parts.append(f"safe: {safe_req}")
            if req_parts:
                console.print(f"       Python: {', '.join(req_parts)}")


def _display_json(packages: List[Package]) -> None:
    """Display packages as JSON."""
    data = [pkg.to_json(pkg) for pkg in packages]
    print(json.dumps(data, indent=2))
