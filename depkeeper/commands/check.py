"""
Check command implementation.

Checks requirements file for available updates and displays results.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import click

from depkeeper.cli import pass_context, DepKeeperContext
from depkeeper.core.parser import RequirementsParser
from depkeeper.core.checker import VersionChecker
from depkeeper.models.package import Package
from depkeeper.utils.console import (
    print_success,
    print_error,
    print_warning,
    print_info,
    print_table,
)
from depkeeper.utils.progress import ProgressTracker
from depkeeper.utils.logger import get_logger
from depkeeper.exceptions import DepKeeperError

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
@pass_context
def check(
    ctx: DepKeeperContext,
    file: Path,
    outdated_only: bool,
    format: str,
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
        has_updates = asyncio.run(_check_async(ctx, file, outdated_only, format))

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
        raise DepKeeperError(f"Failed to parse {file}: {e}")

    if not requirements:
        print_warning(f"No requirements found in {file}")
        return False

    print_info(f"Found {len(requirements)} package(s)")

    # Check versions with progress tracking
    packages = await _check_packages_with_progress(requirements, ctx.verbose > 0)

    # Filter outdated if requested
    if outdated_only:
        packages = [p for p in packages if p.has_update]

    # Display results
    if not packages:
        if outdated_only:
            print_success("All packages are up to date!")
        else:
            print_warning("No packages to display")
        return False

    # Count updates
    outdated_count = sum(1 for p in packages if p.has_update)

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
) -> List[Package]:
    """
    Check packages with optional progress display.

    Parameters
    ----------
    requirements : list
        List of requirements to check.
    show_progress : bool
        Whether to show progress bar.

    Returns
    -------
    List[Package]
        List of checked packages.
    """
    async with VersionChecker() as checker:
        if show_progress:
            # Use progress tracker
            tracker = ProgressTracker(transient=True)
            tracker.start()
            task = tracker.add_task(
                "Checking packages...",
                total=len(requirements),
            )

            packages = []
            for req in requirements:
                try:
                    package = await checker.check_package(
                        req.name,
                        current_version=str(req.specifier) if req.specifier else None,
                    )
                    packages.append(package)
                except Exception as e:
                    logger.error(f"Failed to check {req.name}: {e}")
                    # Create error package
                    from depkeeper.models.package import Package

                    packages.append(Package(name=req.name))

                tracker.update(task, advance=1)

            tracker.stop()
            return packages
        else:
            # No progress display
            return await checker.check_multiple(requirements)


# ============================================================================
# Display Functions
# ============================================================================


def _display_table(packages: List[Package]) -> None:
    """Display packages as a formatted table."""
    data = []
    for pkg in packages:
        status = "��" if pkg.has_update else "��"
        data.append(
            {
                "Status": status,
                "Package": pkg.name,
                "Current": pkg.current_version or "-",
                "Latest": pkg.latest_version or "-",
                "Type": _get_update_type(pkg),
            }
        )

    print_table(data, title="Package Status")


def _display_simple(packages: List[Package]) -> None:
    """Display packages in simple text format."""
    for pkg in packages:
        status = "UPDATE" if pkg.has_update else "OK"
        current = pkg.current_version or "unknown"
        latest = pkg.latest_version or "unknown"
        print(f"[{status}] {pkg.name}: {current} -> {latest}")


def _display_json(packages: List[Package]) -> None:
    """Display packages as JSON."""
    import json

    data = [
        {
            "name": pkg.name,
            "current_version": pkg.current_version,
            "latest_version": pkg.latest_version,
            "has_update": pkg.has_update,
            "update_type": _get_update_type(pkg),
        }
        for pkg in packages
    ]

    print(json.dumps(data, indent=2))


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
