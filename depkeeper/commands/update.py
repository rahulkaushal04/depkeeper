"""
Update command implementation.

Updates packages in requirements file based on available versions and strategies.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Dict, Optional

import click

from depkeeper.cli import pass_context, DepKeeperContext
from depkeeper.core.parser import RequirementsParser
from depkeeper.core.checker import VersionChecker
from depkeeper.core.updater import RequirementsUpdater
from depkeeper.strategies import get_strategy
from depkeeper.constants import UpdateStrategy as UpdateStrategyEnum
from depkeeper.utils.console import (
    print_success,
    print_error,
    print_warning,
    print_info,
    print_table,
    confirm,
)
from depkeeper.utils.progress import create_spinner
from depkeeper.utils.logger import get_logger
from depkeeper.exceptions import DepKeeperError

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
    "--strategy",
    "-s",
    type=click.Choice(
        ["pin", "semver-major", "semver-minor", "semver-patch", "latest"],
        case_sensitive=False,
    ),
    default="semver-minor",
    help="Update strategy to apply.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be updated without making changes.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt.",
)
@pass_context
def update(
    ctx: DepKeeperContext,
    file: Path,
    strategy: str,
    dry_run: bool,
    yes: bool,
) -> None:
    """
    Update packages in requirements file.

    Checks PyPI for latest versions, applies the specified update strategy,
    and updates the requirements file with new versions. Creates a backup
    before making changes.

    Update strategies:

        pin          - No updates (pin current versions)
        semver-patch - Allow patch version updates (1.2.3 -> 1.2.4)
        semver-minor - Allow minor version updates (1.2.3 -> 1.3.0) [default]
        semver-major - Allow major version updates (1.2.3 -> 2.0.0)
        latest       - Always update to latest version

    Examples:

        # Update with default strategy (semver-minor)
        depkeeper update

        # Preview updates without applying them
        depkeeper update --dry-run

        # Update to latest versions
        depkeeper update --strategy latest

        # Skip confirmation prompt
        depkeeper update --yes

    Exit codes:
        0 - Updates applied successfully or no updates needed
        1 - Error occurred during update
    """
    try:
        # Run async update
        asyncio.run(_update_async(ctx, file, strategy, dry_run, yes))
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
    strategy_name: str,
    dry_run: bool,
    yes: bool,
) -> None:
    """
    Async implementation of update command.

    Parameters
    ----------
    ctx : DepKeeperContext
        CLI context.
    file : Path
        Requirements file path.
    strategy_name : str
        Update strategy name.
    dry_run : bool
        Whether to perform a dry run.
    yes : bool
        Whether to skip confirmation.
    """
    if dry_run:
        print_info(f"[DRY RUN] Checking updates for {file}...")
    else:
        print_info(f"Checking updates for {file}...")

    # Parse requirements file
    parser = RequirementsParser()
    try:
        requirements = parser.parse_file(file)
    except Exception as e:
        raise DepKeeperError(f"Failed to parse {file}: {e}")

    if not requirements:
        print_warning(f"No requirements found in {file}")
        return

    print_info(f"Found {len(requirements)} package(s)")

    # Check versions
    print_info("Checking PyPI for latest versions...")
    packages = await _check_packages(requirements)

    # Get update strategy
    strategy = _get_strategy(strategy_name)

    # Collect available updates
    version_updates: Dict[str, str] = {}
    update_info = []

    for pkg in packages:
        if not pkg.has_update or not pkg.latest_version:
            continue

        current = pkg.current_version or "unknown"
        latest = pkg.latest_version

        # Apply strategy filter
        if strategy:
            from depkeeper.models.version import VersionInfo

            try:
                current_ver = VersionInfo(current)
                latest_ver = VersionInfo(latest)

                if not strategy.should_update(current_ver, latest_ver):
                    logger.debug(
                        f"Strategy rejected update: {pkg.name} {current} -> {latest}"
                    )
                    continue
            except Exception as e:
                logger.warning(f"Failed to apply strategy for {pkg.name}: {e}")
                continue

        version_updates[pkg.name] = latest
        update_info.append(
            {
                "Package": pkg.name,
                "Current": current,
                "New": latest,
                "Type": _get_update_type(current, latest),
            }
        )

    # Display updates
    if not version_updates:
        print_success("All packages are up to date!")
        return

    print_table(update_info, title=f"Planned Updates ({strategy_name} strategy)")

    # Confirm with user (unless --yes or --dry-run)
    if not dry_run and not yes:
        if not confirm(f"\nUpdate {len(version_updates)} package(s)?", default=False):
            print_info("Update cancelled")
            return

    # Perform update
    if dry_run:
        print_success(f"\n[DRY RUN] Would update {len(version_updates)} package(s)")
    else:
        print_info("\nApplying updates...")
        _apply_updates(file, version_updates)


async def _check_packages(requirements: list) -> list:
    """
    Check packages for updates.

    Parameters
    ----------
    requirements : list
        List of requirements to check.

    Returns
    -------
    list
        List of checked packages.
    """
    with create_spinner("Fetching package information from PyPI..."):
        async with VersionChecker() as checker:
            packages = await checker.check_multiple(requirements)

    return packages


def _get_strategy(strategy_name: str):
    """
    Get update strategy by name.

    Parameters
    ----------
    strategy_name : str
        Strategy name.

    Returns
    -------
    UpdateStrategy
        Strategy instance.
    """
    # Map CLI strategy names to enum values
    strategy_map = {
        "pin": UpdateStrategyEnum.PIN,
        "semver-patch": UpdateStrategyEnum.SEMVER_PATCH,
        "semver-minor": UpdateStrategyEnum.SEMVER_MINOR,
        "semver-major": UpdateStrategyEnum.SEMVER_MAJOR,
        "latest": UpdateStrategyEnum.LATEST,
    }

    strategy_enum = strategy_map.get(strategy_name.lower())
    if not strategy_enum:
        raise DepKeeperError(f"Unknown strategy: {strategy_name}")

    return get_strategy(strategy_enum)


def _apply_updates(file: Path, version_updates: Dict[str, str]) -> None:
    """
    Apply updates to requirements file.

    Parameters
    ----------
    file : Path
        Requirements file path.
    version_updates : Dict[str, str]
        Package name to version mapping.
    """
    updater = RequirementsUpdater()

    try:
        result = updater.update_requirements(
            file,
            version_updates,
            dry_run=False,
        )

        if result.success:
            print_success(f"\n{result.changes_summary}")

            if result.backup_path:
                print_info(f"Backup created: {result.backup_path}")

            # Show update details
            if result.updated_packages:
                print_info(f"\nUpdated packages:")
                for name, (old, new) in result.updated_packages.items():
                    print_info(f"  • {name}: {old} → {new}")

            if result.failed_packages:
                print_warning(f"\nFailed packages:")
                for name, error in result.failed_packages.items():
                    print_warning(f"  • {name}: {error}")

            if result.skipped_packages:
                print_info(f"\nSkipped packages: {', '.join(result.skipped_packages)}")
        else:
            print_error("\nUpdate failed!")
            if result.failed_packages:
                for name, error in result.failed_packages.items():
                    print_error(f"  • {name}: {error}")
            raise DepKeeperError("Update operation failed")

    except Exception as e:
        raise DepKeeperError(f"Failed to update requirements: {e}")


def _get_update_type(current: str, latest: str) -> str:
    """
    Determine update type (major, minor, patch).

    Parameters
    ----------
    current : str
        Current version.
    latest : str
        Latest version.

    Returns
    -------
    str
        Update type.
    """
    try:
        from packaging.version import parse

        c = parse(current)
        l = parse(latest)

        if hasattr(c, "release") and hasattr(l, "release"):
            c_parts = c.release
            l_parts = l.release

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

        return "update"
    except Exception:
        return "unknown"
