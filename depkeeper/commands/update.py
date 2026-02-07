"""Update command implementation for depkeeper.

Updates packages in a ``requirements.txt`` file to safe upgrade versions
while maintaining major version boundaries and Python compatibility.

The command uses the same core components as the check command:

1. **RequirementsParser** — parses the requirements file
2. **PyPIDataStore** — shared cache for PyPI metadata (one fetch per package)
3. **VersionChecker** — computes recommended versions with strict major
   version boundaries

Recommended versions **never** cross major version boundaries, ensuring
that updates avoid breaking changes from major version upgrades.

Typical usage::

    # Update all packages to safe versions
    $ depkeeper update requirements.txt

    # Preview changes without applying
    $ depkeeper update --dry-run

    # Update only specific packages
    $ depkeeper update -p flask -p click

    # Create backup and skip confirmation
    $ depkeeper update --backup -y
"""

from __future__ import annotations

import sys
import shutil
import asyncio
from pathlib import Path
from typing import List, Tuple

import click

from depkeeper.models import Package, Requirement
from depkeeper.exceptions import DepKeeperError, ParseError
from depkeeper.context import pass_context, DepKeeperContext
from depkeeper.core import (
    PyPIDataStore,
    VersionChecker,
    RequirementsParser,
)
from depkeeper.utils import (
    HTTPClient,
    get_logger,
    print_success,
    print_error,
    print_warning,
    print_table,
    colorize_update_type,
    get_update_type,
    create_timestamped_backup,
)

logger = get_logger("commands.update")


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
@click.option(
    "--strict-version-matching",
    is_flag=True,
    help="Only use exact version pins, don't infer from constraints.",
)
@pass_context
def update(
    ctx: DepKeeperContext,
    file: Path,
    dry_run: bool,
    yes: bool,
    backup: bool,
    packages: Tuple[str, ...],
    strict_version_matching: bool,
) -> None:
    """Update packages to safe upgrade versions.

    Updates packages to their recommended versions — the maximum version
    within the same major version that is compatible with your Python
    version. This avoids breaking changes from major version upgrades.

    When ``--strict-version-matching`` is disabled (default), the command
    can infer the current version from range constraints like ``>=2.0``.
    When enabled, only exact pins (``==``) are treated as current versions.

    Args:
        ctx: Depkeeper context with configuration and verbosity settings.
        file: Path to the requirements file (default: ``requirements.txt``).
        dry_run: Preview changes without modifying the file.
        yes: Skip confirmation prompt before applying updates.
        backup: Create a timestamped backup before modifying the file.
        packages: Only update these packages (empty = update all).
        strict_version_matching: Don't infer current versions from
            constraints; only use exact pins (``==``).

    Exits:
        0 if updates were applied successfully or no updates needed,
        1 if an error occurred.

    Example::

        >>> # CLI invocation
        $ depkeeper update requirements.txt --dry-run
        $ depkeeper update -p flask -p click --backup -y
    """
    try:
        asyncio.run(
            _update_async(
                ctx,
                file,
                dry_run,
                yes,
                backup,
                list(packages),
                infer_version_from_constraints=not strict_version_matching,
            )
        )
        sys.exit(0)

    except DepKeeperError as e:
        print_error(f"{e}")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        logger.exception("Error in update command")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Async orchestration
# ---------------------------------------------------------------------------


async def _update_async(
    ctx: DepKeeperContext,
    file: Path,
    dry_run: bool,
    skip_confirm: bool,
    backup: bool,
    package_filter: List[str],
    infer_version_from_constraints: bool,
) -> None:
    """Async implementation of the update command.

    Core logic:

    1. Parse the requirements file.
    2. Create a shared :class:`PyPIDataStore` (ensures each package is
       fetched once).
    3. Run :class:`VersionChecker` to compute recommended versions.
    4. Filter packages if ``--packages`` is specified.
    5. Identify packages needing updates.
    6. Display update plan.
    7. Optionally create backup, apply updates, and report results.

    Args:
        ctx: Depkeeper context.
        file: Path to the requirements file.
        dry_run: Whether to preview changes without applying.
        skip_confirm: Whether to skip confirmation prompt.
        backup: Whether to create a backup before updating.
        package_filter: List of package names to update (empty = all).
        infer_version_from_constraints: Infer current version from
            constraints (e.g., ``>=2.0`` → current is ``2.0``).

    Raises:
        DepKeeperError: Requirements file cannot be parsed or updates
            cannot be applied.
    """
    logger.info("Checking %s for updates...", file)

    # ── Step 1: Parse requirements ────────────────────────────────────
    parser = RequirementsParser()
    try:
        requirements = parser.parse_file(file)
    except ParseError as e:
        raise DepKeeperError(f"Failed to parse {file}: {e}") from e

    if not requirements:
        print_warning("No packages found in requirements file")
        return

    logger.info("Found %d package(s)", len(requirements))

    # ── Step 2: Fetch versions from PyPI (shared data store) ──────────
    async with HTTPClient() as http:
        data_store = PyPIDataStore(http)

        # Warm the cache with all packages in one concurrent burst
        await data_store.prefetch_packages([req.name for req in requirements])

        # Use the same data store for version checking
        checker = VersionChecker(
            data_store=data_store,
            infer_version_from_constraints=infer_version_from_constraints,
        )
        packages = await checker.check_packages(requirements)

    # ── Step 3: Filter packages if requested ──────────────────────────
    if package_filter:
        package_filter_lower = [p.lower() for p in package_filter]
        packages = [p for p in packages if p.name.lower() in package_filter_lower]
        requirements = [
            r for r in requirements if r.name.lower() in package_filter_lower
        ]

        if not packages:
            print_warning(f"No matching packages found: {', '.join(package_filter)}")
            return

    # ── Step 4: Find packages that need updates ───────────────────────
    updates = _find_updates(packages, requirements)

    if not updates:
        print_success("All packages are up to date!")
        return

    # ── Step 5: Display update plan ───────────────────────────────────
    _display_update_plan(updates, dry_run)

    if dry_run:
        print_warning("\nDry run mode - no changes applied")
        return

    # ── Step 6: Confirm before updating (unless -y flag) ──────────────
    if not skip_confirm:
        if not _confirm_update(len(updates)):
            logger.info("Update cancelled by user")
            return

    # ── Step 7: Create backup if requested ────────────────────────────
    backup_path = None
    if backup:
        backup_path = create_timestamped_backup(file)
        logger.info("Created backup: %s", backup_path)

    # ── Step 8: Apply updates ─────────────────────────────────────────
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


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _find_updates(
    packages: List[Package],
    requirements: List[Requirement],
) -> List[Tuple[Requirement, Package, str]]:
    """Find packages that have safe upgrades available.

    Identifies packages where the recommended version differs from the
    current version, including cases where:

    - A newer version is available within the current major version
    - No current version is specified (adds a version pin)
    - A downgrade is needed (incompatible current version)

    Args:
        packages: List of checked packages with version metadata.
        requirements: Original parsed requirements.

    Returns:
        List of ``(requirement, package, new_version)`` tuples for packages
        that have safe upgrades or changes available.

    Example::

        >>> updates = _find_updates(packages, requirements)
        >>> len(updates)
        3
        >>> updates[0]
        (Requirement('flask', ...), Package('flask', ...), '2.3.3')
    """
    updates = []

    # Create mapping from package name to requirement
    req_map = {r.name.lower(): r for r in requirements}

    for pkg in packages:
        req = req_map.get(pkg.name.lower())
        if not req:
            continue

        # Determine target version (recommended)
        target_version = pkg.recommended_version

        if not target_version:
            logger.debug("No target version for %s", pkg.name)
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
                "Downgrade needed for %s: %s → %s",
                pkg.name,
                pkg.current_version,
                target_version,
            )
            updates.append((req, pkg, target_version))

    return updates


def _display_update_plan(
    updates: List[Tuple[Requirement, Package, str]],
    dry_run: bool,
) -> None:
    """Display planned updates as a Rich-formatted table.

    Creates a visual summary of all pending updates showing:

    - Package name
    - Current version (or "not specified")
    - New version (color-coded green)
    - Change type (major/minor/patch, color-coded)
    - Python version requirements for the new version

    Args:
        updates: List of planned updates.
        dry_run: Whether this is a dry run (affects table title).

    Example output::

        ┏━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
        ┃ Package  ┃ Current    ┃ New Version┃ Change  ┃ Python Requires ┃
        ┡━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
        │ flask    │ 2.0.0      │ 2.3.3      │ minor   │ >=3.8           │
        │ click    │ 8.0.0      │ 8.1.7      │ minor   │ >=3.7           │
        └──────────┴────────────┴────────────┴─────────┴─────────────────┘
    """
    title = "Update Plan (Dry Run)" if dry_run else "Update Plan"

    data = []
    for req, pkg, new_version in updates:
        old_version = pkg.current_version or "not specified"

        # Determine update type
        update_type = get_update_type(pkg.current_version, new_version)
        colored_type = colorize_update_type(update_type)

        # Python requirements for the new version
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
    """Prompt user to confirm update operation.

    Displays an interactive prompt asking the user to confirm whether they
    want to proceed with the planned updates. Defaults to 'yes'.

    Args:
        count: Number of packages to update.

    Returns:
        ``True`` if the user confirms (responds with 'y'), ``False``
        otherwise.

    Example::

        >>> _confirm_update(3)
        Update 3 packages? [y/n] (y): y
        True
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
    """Apply updates to the requirements file.

    Reads the original file, updates the relevant lines to the new versions,
    and writes the modified content back atomically. Preserves comments,
    blank lines, and formatting of non-updated lines.

    The update process:

    1. Creates a map of package names to new versions
    2. Creates a map of line numbers to requirements
    3. Reads all lines from the original file
    4. For each line:
       - If it corresponds to an updated requirement, replace the version
       - Otherwise, keep the original line unchanged
    5. Writes all updated lines back to the file

    Args:
        file: Path to the requirements file.
        requirements: All parsed requirements.
        updates: Updates to apply (from :func:`_find_updates`).

    Raises:
        DepKeeperError: File cannot be read or written.

    Example (internal)::

        >>> _apply_updates(
        ...     Path("requirements.txt"),
        ...     requirements,
        ...     [(req1, pkg1, "2.3.3"), (req2, pkg2, "8.1.7")]
        ... )
        # requirements.txt is now updated in place
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
            logger.debug(
                "Updated line %d: %s → %s", i, line.strip(), updated_line.strip()
            )
        else:
            # Keep original line
            updated_lines.append(line)

    # Write updated content
    with open(file, "w", encoding="utf-8") as f:
        f.writelines(updated_lines)
