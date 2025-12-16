"""
Check command implementation.

Checks requirements file for available updates and displays results.
"""

from __future__ import annotations

import sys
import json
import click
import asyncio
from typing import List, Dict, Any, Optional
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

    # Count packages needing action (updates or incompatibilities)
    packages_needing_action = sum(
        1 for p in packages if p.has_update() or _needs_action(p)
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
            current_version = checker.extract_current_version(req)
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
            current_version = checker.extract_current_version(req)
            packages.append(checker.create_error_package(req.name, current_version))

        tracker.update(task, advance=1)

    tracker.update(task, description=f"Checked {len(requirements)} package(s)")
    tracker.stop()

    for result in results_log:
        logger.debug(result)

    return packages


# ============================================================================
# Helper Functions
# ============================================================================


def _needs_action(pkg: Package) -> bool:
    """Check if package needs action (incompatible or needs downgrade).

    Parameters
    ----------
    pkg : Package
        Package to check.

    Returns
    -------
    bool
        True if package is incompatible with current Python or needs downgrade.
    """
    # Check if there's a compatible version and current is greater (needs downgrade)
    if pkg.has_compatible_version() and pkg.current_version:
        try:
            from packaging.version import parse

            return parse(pkg.current_version) > parse(pkg.compatible_version)
        except Exception:
            pass

    # Check if latest is incompatible and no compatible version found
    if not pkg.is_python_compatible() and not pkg.has_compatible_version():
        return True

    return False


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
    python_reqs = _get_detailed_python_reqs(pkg)

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
    # Compatible version now shows max version within same major version
    target_version = None
    compatible_display = "[dim]-[/dim]"
    needs_downgrade = False

    if pkg.has_compatible_version():
        # There's a max compatible version within same major version
        target_version = pkg.compatible_version

        # Only show compatible version if it's different from current
        # (i.e., there's actually an upgrade available)
        if pkg.current_version and pkg.compatible_version != pkg.current_version:
            compatible_display = f"[bright_cyan]{pkg.compatible_version}[/bright_cyan]"
        else:
            # Current == compatible, so no upgrade available - show as "-"
            compatible_display = "[dim]-[/dim]"

        # Check if current version is newer than max compatible (needs downgrade)
        if pkg.current_version:
            try:
                from packaging.version import parse

                needs_downgrade = parse(pkg.current_version) > parse(target_version)
            except Exception:
                pass
    else:
        # No compatible version found within same major, use latest
        target_version = pkg.latest_version
        compatible_display = f"[green]{pkg.latest_version}[/green]"

    # Check if update is available based on target version
    has_update = False
    if target_version and pkg.current_version:
        try:
            from packaging.version import parse

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
            "Safe Upgrade": compatible_display,
            "Update": "[red]downgrade[/red]",
            "Python Requires": python_reqs,
        }

    if has_update:
        # Update available to target version
        update_type = _get_update_type_between(pkg.current_version, target_version)
        colored_type = _colorize_update_type(update_type)

        return {
            "Status": "[yellow]↑ UPDATE[/yellow]",
            "Package": pkg.name,
            "Current": pkg.current_version or "[dim]-[/dim]",
            "Latest": pkg.latest_version,
            "Safe Upgrade": compatible_display,
            "Update": colored_type,
            "Python Requires": python_reqs,
        }

    # Up to date - current >= target version
    return {
        "Status": "[green]✓ OK[/green]",
        "Package": pkg.name,
        "Current": pkg.current_version or "[dim]-[/dim]",
        "Latest": pkg.latest_version or "[dim]-[/dim]",
        "Safe Upgrade": compatible_display,
        "Update": "[dim]-[/dim]",
        "Python Requires": python_reqs,
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


def _get_detailed_python_reqs(pkg: Package) -> str:
    """Get detailed Python requirements for current, available, and suggested versions.

    Parameters
    ----------
    pkg : Package
        Package to get requirements for.

    Returns
    -------
    str
        Formatted string with Python requirements for all versions.
    """
    parts = []

    # Current version requirement
    current_req = pkg.get_version_python_req("current")
    if current_req:
        parts.append(f"Installed: {current_req}")

    # Available (latest) version requirement
    latest_req = pkg.get_version_python_req("latest") or pkg.get_requires_python()
    if latest_req:
        is_compatible = pkg.is_python_compatible()
        if is_compatible:
            parts.append(f"[green]Latest: {latest_req}[/green]")
        else:
            parts.append(f"[red]Latest: {latest_req}[/red]")

    # Compatible version requirement (if different from latest)
    if pkg.has_compatible_version():
        compatible_req = pkg.get_version_python_req("compatible")
        if compatible_req:
            parts.append(f"[bright_cyan]Safe Upgrade: {compatible_req}[/bright_cyan]")
        else:
            parts.append(f"[bright_cyan]Safe Upgrade: any[/bright_cyan]")
    elif not pkg.is_python_compatible() and pkg.latest_version:
        # Latest incompatible but no suggestion found
        import sys

        current_py = f"{sys.version_info.major}.{sys.version_info.minor}"
        parts.append(f"[dim]No Py{current_py} version[/dim]")

    return "\n".join(parts) if parts else "[dim]-[/dim]"


def _display_simple(packages: List[Package]) -> None:
    """Display packages in simple text format."""
    from depkeeper.utils.console import get_raw_console

    console = get_raw_console()

    for pkg in packages:
        status, installed, latest, compatible = _get_simple_status(pkg)

        # Show status with versions
        if compatible and compatible != latest:
            console.print(
                f"[{status}] {pkg.name:20} {installed:10} → {latest:10} (safe: {compatible})"
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
            if pkg.has_compatible_version():
                safe_req = pkg.get_version_python_req("compatible")
                if safe_req:
                    req_parts.append(f"safe: {safe_req}")
            if req_parts:
                console.print(f"       Python: {', '.join(req_parts)}")


def _get_simple_status(pkg: Package) -> tuple[str, str, str, str | None]:
    """Get simple status tuple for package.

    Parameters
    ----------
    pkg : Package
        Package to get status for.

    Returns
    -------
    tuple[str, str, str, str | None]
        (status, installed_version, latest_version, compatible_version) tuple.
    """
    installed = pkg.current_version or "none"
    latest = pkg.latest_version or "error"
    compatible = pkg.compatible_version if pkg.has_compatible_version() else None

    if not pkg.latest_version:
        return "✗", installed, "error", None

    if pkg.has_update():
        return "↑", installed, latest, compatible

    return "✓", installed, latest, compatible


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
    # Determine status
    if not pkg.latest_version:
        status = "error"
    elif pkg.has_update():
        status = "update_available"
    else:
        status = "up_to_date"

    entry = {
        "name": pkg.name,
        "status": status,
    }

    # Add version information
    versions = {}
    if pkg.current_version:
        versions["current"] = pkg.current_version
    if pkg.latest_version:
        versions["latest"] = pkg.latest_version
    if pkg.compatible_version:
        versions["safe_upgrade"] = pkg.compatible_version

    if versions:
        entry["versions"] = versions

    # Add update type if available
    if pkg.has_update():
        update_type = _get_update_type(pkg)
        if update_type and update_type != "-":
            entry["update_type"] = update_type

    # Build python_requirements only with non-null values
    python_reqs = {}
    installed_req = pkg.get_version_python_req("current")
    if installed_req:
        python_reqs["current"] = installed_req

    latest_req = pkg.get_requires_python()
    if latest_req:
        python_reqs["latest"] = latest_req

    if pkg.has_compatible_version():
        safe_req = pkg.get_version_python_req("compatible")
        if safe_req:
            python_reqs["safe_upgrade"] = safe_req

    if python_reqs:
        entry["python_requires"] = python_reqs

    # Add error field if package fetch failed
    if not pkg.latest_version:
        entry["error"] = "Failed to fetch package information from PyPI"

    return entry


def _get_update_type(pkg: Package) -> str:
    """Determine update type (major, minor, patch, etc.) between current and latest.

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

    return _get_update_type_between(pkg.current_version, pkg.latest_version)


def _get_update_type_between(
    from_version: Optional[str], to_version: Optional[str]
) -> str:
    """Determine update type between two specific versions.

    Parameters
    ----------
    from_version : str or None
        Starting version
    to_version : str or None
        Target version

    Returns
    -------
    str
        Update type: 'major', 'minor', 'patch', 'update', or 'unknown'
    """
    if not from_version or not to_version:
        return "unknown"

    try:
        from packaging.version import parse

        current = parse(from_version)
        target = parse(to_version)

        # Check if versions have release segments
        if hasattr(current, "release") and hasattr(target, "release"):
            c_parts = current.release
            t_parts = target.release

            if len(c_parts) >= 1 and len(t_parts) >= 1:
                if c_parts[0] != t_parts[0]:
                    return "major"
                elif (
                    len(c_parts) >= 2 and len(t_parts) >= 2 and c_parts[1] != t_parts[1]
                ):
                    return "minor"
                elif (
                    len(c_parts) >= 3 and len(t_parts) >= 3 and c_parts[2] != t_parts[2]
                ):
                    return "patch"
                else:
                    return "update"

        return "update"

    except Exception:
        return "unknown"
