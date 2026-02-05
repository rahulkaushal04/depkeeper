"""
Update command implementation.

Updates packages in requirements file to safe upgrade versions.
"""

from __future__ import annotations

import sys
import shutil
import asyncio
from pathlib import Path
from typing import List, Tuple

import click

from depkeeper.models.package import Package
from depkeeper.models.requirement import Requirement
from depkeeper.utils.logger import get_logger
from depkeeper.exceptions import DepKeeperError
from depkeeper.core.checker import VersionChecker
from depkeeper.core.parser import RequirementsParser
from depkeeper.utils.version_utils import get_update_type
from depkeeper.context import pass_context, DepKeeperContext
from depkeeper.utils.filesystem import create_timestamped_backup
from depkeeper.utils.console import (
    print_success,
    print_error,
    print_warning,
    print_table,
    colorize_update_type,
)

logger = get_logger("commands.update")


# ============================================================================
# Update Command
# ============================================================================


@click.command()
@click.argument(
    "file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default="requirements.txt",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview changes without applying them.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt.",
)
@click.option(
    "--backup",
    is_flag=True,
    help="Create backup file before updating.",
)
@click.option(
    "--packages",
    "-p",
    multiple=True,
    help="Update only specific packages (can be repeated).",
)
@pass_context
def update(
    ctx: DepKeeperContext,
    file: Path,
    dry_run: bool,
    yes: bool,
    backup: bool,
    packages: Tuple[str, ...],
) -> None:
    """
    Update packages to safe upgrade versions.

    Updates packages to their "safe upgrade" versions - the maximum version
    within the same major version that is compatible with your Python version.
    This avoids breaking changes from major version upgrades.

    Examples:

        # Update all packages
        depkeeper update

        # Preview changes without applying
        depkeeper update --dry-run

        # Update specific packages only
        depkeeper update -p click -p httpx

        # Skip confirmation
        depkeeper update -y

    Exit codes:
        0 - Updates applied successfully or no updates needed
        1 - Error occurred
    """
    try:
        # Run async update
        asyncio.run(_update_async(ctx, file, dry_run, yes, backup, list(packages)))
        sys.exit(0)

    except DepKeeperError as e:
        print_error(f"{e}")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        logger.exception("Error in update command")
        sys.exit(1)


# ============================================================================
# Async Implementation
# ============================================================================


async def _update_async(
    ctx: DepKeeperContext,
    file: Path,
    dry_run: bool,
    skip_confirm: bool,
    backup: bool,
    package_filter: List[str],
) -> None:
    """
    Async implementation of update command.

    Parameters
    ----------
    ctx : DepKeeperContext
        CLI context.
    file : Path
        Requirements file path.
    dry_run : bool
        Whether to preview changes without applying.
    skip_confirm : bool
        Whether to skip confirmation prompt.
    backup : bool
        Whether to create backup before updating.
    package_filter : List[str]
        List of package names to update (empty = all).
    """
    logger.info("Checking %s for updates...", file)

    # Parse requirements file
    parser = RequirementsParser()
    try:
        requirements = parser.parse_file(file)
    except Exception as e:
        raise DepKeeperError(f"Failed to parse {file}: {e}") from e

    if not requirements:
        print_warning("No packages found in requirements file")
        return

    logger.info("Found %d package(s)", len(requirements))

    # Check versions
    async with VersionChecker(infer_version_from_constraints=True) as checker:
        packages = await checker.check_packages(requirements)

    # Filter packages if requested
    if package_filter:
        package_filter_lower = [p.lower() for p in package_filter]
        packages = [p for p in packages if p.name.lower() in package_filter_lower]
        requirements = [
            r for r in requirements if r.name.lower() in package_filter_lower
        ]

        if not packages:
            print_warning(f"No matching packages found: {', '.join(package_filter)}")
            return

    # Find packages that need updates
    updates = _find_updates(packages, requirements)

    if not updates:
        print_success("All packages are up to date!")
        return

    # Display update plan
    _display_update_plan(updates, dry_run)

    if dry_run:
        print_warning("\nDry run mode - no changes applied")
        return

    # Confirm before updating (unless -y flag)
    if not skip_confirm:
        if not _confirm_update(len(updates)):
            logger.info("Update cancelled by user")
            return

    # Create backup if requested
    backup_path = None
    if backup:
        backup_path = create_timestamped_backup(file)
        logger.info("Created backup: %s", backup_path)

    # Apply updates
    try:
        _apply_updates(file, requirements, updates)
        print_success(f"\n✓ Successfully updated {len(updates)} package(s)")

        # Log individual updates at debug level
        for req, pkg, new_version in updates:
            old_version = pkg.current_version or "not specified"
            logger.debug("  %s: %s → %s", req.name, old_version, new_version)

    except Exception as e:
        # Restore from backup on error
        if backup_path and backup_path.exists():
            print_error(f"Error during update: {e}")
            logger.info("Restoring from backup...")
            shutil.copy2(backup_path, file)
            print_success("Restored original file from backup")
        raise DepKeeperError(f"Failed to apply updates: {e}") from e


# ============================================================================
# Helper Functions
# ============================================================================


def _find_updates(
    packages: List[Package],
    requirements: List[Requirement],
) -> List[Tuple[Requirement, Package, str]]:
    """Find packages that have safe upgrades available.

    Parameters
    ----------
    packages : List[Package]
        List of checked packages.
    requirements : List[Requirement]
        Original requirements.

    Returns
    -------
    List[Tuple[Requirement, Package, str]]
        List of (requirement, package, new_version) tuples for packages
        that have safe upgrades available.
    """
    updates = []

    # Create mapping from package name to requirement
    req_map = {r.name.lower(): r for r in requirements}

    for pkg in packages:
        req = req_map.get(pkg.name.lower())
        if not req:
            continue

        # Determine target version (recommended or latest)
        target_version = pkg.recommended_version

        if not target_version:
            logger.debug(f"No target version for {pkg.name}")
            continue

        # Check if update is needed using Package model methods
        if not pkg.current_version:
            # No current version specified, add version pin
            updates.append((req, pkg, target_version))
        elif pkg.has_update():
            # Package has a newer version available
            updates.append((req, pkg, target_version))
        elif pkg.requires_downgrade:
            # Downgrade needed (incompatible current version)
            logger.info(
                f"Downgrade needed for {pkg.name}: {pkg.current_version} → {target_version}"
            )
            updates.append((req, pkg, target_version))

    return updates


def _display_update_plan(
    updates: List[Tuple[Requirement, Package, str]],
    dry_run: bool,
) -> None:
    """Display planned updates as a table.

    Parameters
    ----------
    updates : List[Tuple[Requirement, Package, str]]
        List of planned updates.
    dry_run : bool
        Whether this is a dry run.
    """
    title = "Update Plan (Dry Run)" if dry_run else "Update Plan"

    data = []
    for req, pkg, new_version in updates:
        old_version = pkg.current_version or "not specified"

        # Determine update type
        update_type = get_update_type(pkg.current_version, new_version)
        colored_type = colorize_update_type(update_type)

        # Python requirements
        python_req = (
            pkg.get_version_python_req("recommended")
            or pkg.get_requires_python()
            or "-"
        )

        data.append(
            {
                "Package": pkg.name,
                "Current": old_version,
                "New Version": f"[bold green]{new_version}[/bold green]",
                "Change": colored_type,
                "Python Requires": python_req,
            }
        )

    column_styles = {
        "Package": {"style": "bold cyan", "no_wrap": True},
        "Current": {"justify": "center", "style": "dim"},
        "New Version": {"justify": "center"},
        "Change": {"justify": "center"},
        "Python Requires": {"justify": "left"},
    }

    print_table(data, title=title, column_styles=column_styles)


def _confirm_update(count: int) -> bool:
    """Prompt user to confirm update.

    Parameters
    ----------
    count : int
        Number of packages to update.

    Returns
    -------
    bool
        True if user confirms, False otherwise.
    """
    plural = "package" if count == 1 else "packages"
    response = click.prompt(
        f"\nUpdate {count} {plural}?",
        type=click.Choice(["y", "n"], case_sensitive=False),
        default="y",
        show_choices=True,
    )
    return response.lower() == "y"


def _apply_updates(
    file: Path,
    requirements: List[Requirement],
    updates: List[Tuple[Requirement, Package, str]],
) -> None:
    """Apply updates to requirements file.

    Parameters
    ----------
    file : Path
        Requirements file path.
    requirements : List[Requirement]
        All requirements.
    updates : List[Tuple[Requirement, Package, str]]
        Updates to apply.
    """
    # Create update map
    update_map = {req.name.lower(): new_version for req, _, new_version in updates}

    # Read original file content
    with open(file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Create requirement line map
    req_line_map = {req.line_number: req for req in requirements}

    # Update lines
    updated_lines = []
    for i, line in enumerate(lines, start=1):
        req = req_line_map.get(i)

        if req and req.name.lower() in update_map:
            # Update this line
            new_version = update_map[req.name.lower()]
            updated_line = req.update_version(
                new_version, preserve_trailing_newline=line.endswith("\n")
            )
            updated_lines.append(updated_line)
            logger.debug(f"Updated line {i}: {line.strip()} → {updated_line.strip()}")
        else:
            # Keep original line
            updated_lines.append(line)

    # Write updated content
    with open(file, "w", encoding="utf-8") as f:
        f.writelines(updated_lines)
