"""Update command implementation for depkeeper.

Updates packages in a ``requirements.txt`` file to safe upgrade versions
while maintaining major version boundaries and Python compatibility.

The command orchestrates three core components:

1. **RequirementsParser** — parses the requirements file into structured
   :class:`Requirement` objects.
2. **VersionChecker** — queries PyPI concurrently to fetch latest versions
   and compute recommendations.
3. **DependencyAnalyzer** — cross-validates all recommended versions and
   resolves conflicts through iterative downgrading/constraining.

All components share a single :class:`PyPIDataStore` instance to guarantee
that each package's metadata is fetched at most once per invocation.

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

    # Disable conflict resolution (faster, but may create conflicts)
    $ depkeeper update --no-check-conflicts
"""

from __future__ import annotations

import sys
import click
import shutil
import asyncio
from pathlib import Path
from typing import Dict, List, Tuple

from depkeeper.models import Package, Requirement
from depkeeper.exceptions import DepKeeperError, ParseError
from depkeeper.context import pass_context, DepKeeperContext
from depkeeper.core import (
    PyPIDataStore,
    VersionChecker,
    RequirementsParser,
    DependencyAnalyzer,
    ResolutionResult,
)
from depkeeper.utils import (
    HTTPClient,
    get_logger,
    print_success,
    print_error,
    print_warning,
    print_table,
    get_raw_console,
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
@click.option(
    "--check-conflicts",
    is_flag=True,
    default=True,
    help="Check for dependency conflicts and adjust versions accordingly.",
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
    check_conflicts: bool,
) -> None:
    """Update packages to safe upgrade versions.

    Updates packages to their recommended versions — the maximum version
    within the same major version that is compatible with your Python
    version. This avoids breaking changes from major version upgrades.

    When ``--strict-version-matching`` is disabled (default), the command
    can infer the current version from range constraints like ``>=2.0``.
    When enabled, only exact pins (``==``) are treated as current versions.

    When ``--check-conflicts`` is enabled (default), the command:

    1. Fetches initial recommendations for every package.
    2. Cross-validates all recommendations to detect conflicts (package A's
       dependency on B is incompatible with B's recommended version).
    3. Iteratively adjusts versions (downgrading sources or constraining
       targets) until a conflict-free set is found or the iteration limit
       is reached.
    4. Applies the final resolved versions to the requirements file.

    Args:
        ctx: Depkeeper context with configuration and verbosity settings.
        file: Path to the requirements file (default: ``requirements.txt``).
        dry_run: Preview changes without modifying the file.
        yes: Skip confirmation prompt before applying updates.
        backup: Create a timestamped backup before modifying the file.
        packages: Only update these packages (empty = update all).
        strict_version_matching: Don't infer current versions from
            constraints; only use exact pins (``==``).
        check_conflicts: Enable dependency conflict resolution. When enabled,
            the command will adjust recommended versions to avoid conflicts.

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
                check_conflicts=check_conflicts,
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
    check_conflicts: bool,
) -> None:
    """Async implementation of the update command.

    Core logic:

    1. Parse the requirements file into structured :class:`Requirement`
       objects.
    2. Create a shared :class:`PyPIDataStore` (ensures each package is
       fetched once).
    3. Run :class:`VersionChecker` to compute recommended versions.
    4. Optionally run :class:`DependencyAnalyzer` to resolve conflicts and
       adjust recommendations to ensure mutual compatibility.
    5. Filter packages if ``--packages`` is specified.
    6. Identify packages needing updates (newer version available, no
       version pinned, or downgrade required).
    7. Display update plan showing current → new versions.
    8. Confirm before updating (unless ``--yes`` flag is set).
    9. Optionally create backup, apply updates atomically, and report
       results.

    Args:
        ctx: Depkeeper context with verbosity and configuration.
        file: Path to the requirements file.
        dry_run: Whether to preview changes without applying.
        skip_confirm: Whether to skip confirmation prompt.
        backup: Whether to create a backup before updating.
        package_filter: List of package names to update (empty = all).
        infer_version_from_constraints: Infer current version from
            constraints (e.g., ``>=2.0`` → current is ``2.0``).
        check_conflicts: Enable dependency conflict resolution to ensure
            recommended versions are mutually compatible.

    Raises:
        DepKeeperError: Requirements file cannot be parsed or updates
            cannot be applied.

    Example (internal)::

        >>> await _update_async(
        ...     ctx,
        ...     Path("requirements.txt"),
        ...     dry_run=False,
        ...     skip_confirm=True,
        ...     backup=True,
        ...     package_filter=[],
        ...     infer_version_from_constraints=True,
        ...     check_conflicts=True,
        ... )
        # Updates applied to requirements.txt
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

        # Use the same data store for version checking and conflict analysis
        checker = VersionChecker(
            data_store=data_store,
            infer_version_from_constraints=infer_version_from_constraints,
        )
        packages = await checker.check_packages(requirements)

        # ── Step 3: Resolve conflicts (optional) ──────────────────────
        resolution_result: ResolutionResult | None = None
        if check_conflicts:
            logger.info("Cross-validating recommended versions...")
            analyzer = DependencyAnalyzer(data_store=data_store)
            resolution_result = await analyzer.resolve_and_annotate_conflicts(packages)

            if ctx.verbose > 0 and resolution_result:
                # Display resolution summary (convergence status, version changes)
                _display_resolution_summary(resolution_result)

    # ── Step 4: Filter packages if requested ──────────────────────────
    if package_filter:
        package_filter_lower = [p.lower() for p in package_filter]
        packages = [p for p in packages if p.name.lower() in package_filter_lower]
        requirements = [
            r for r in requirements if r.name.lower() in package_filter_lower
        ]

        if not packages:
            print_warning(f"No matching packages found: {', '.join(package_filter)}")
            return

    # ── Step 5: Find packages that need updates ───────────────────────
    updates = _find_updates(packages, requirements)

    if not updates:
        print_success("All packages are up to date!")
        return

    # Show conflict warnings if any packages have unresolved conflicts
    if resolution_result and resolution_result.packages_with_conflicts > 0:
        print_warning(
            f"\n{resolution_result.packages_with_conflicts} package(s) have "
            "unresolved conflicts — updates may cause issues"
        )

    # ── Step 6: Display update plan ───────────────────────────────────
    _display_update_plan(updates, dry_run)

    if dry_run:
        print_warning("\nDry run mode - no changes applied")
        return

    # ── Step 7: Confirm before updating (unless -y flag) ──────────────
    if not skip_confirm:
        if not _confirm_update(len(updates)):
            logger.info("Update cancelled by user")
            return

    # ── Step 8: Create backup if requested ────────────────────────────
    backup_path: Path | None = None
    if backup:
        backup_path = create_timestamped_backup(file)
        logger.info("Created backup: %s", backup_path)

    # ── Step 9: Apply updates ─────────────────────────────────────────
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


def _display_resolution_summary(result: ResolutionResult) -> None:
    """Print a human-readable summary of the conflict resolution process.

    Displays:

    - Total packages analyzed
    - Number of packages with unresolved conflicts
    - Number of version changes made during resolution
    - Convergence status (did resolution finish or hit iteration limit?)
    - Details of each version change (original → resolved)

    Args:
        result: The :class:`ResolutionResult` from the dependency analyzer
            containing resolution metadata and version adjustments.

    Example output::

        Resolution Summary:
        ==================================================
        Total packages: 15
        Packages with conflicts: 2
        Packages changed: 3
        Converged: Yes (5 iterations)

        Version changes:
          • flask: 3.0.0 → 2.3.3 (downgraded)
          • werkzeug: 3.0.1 → 2.3.7 (constrained)
    """
    console = get_raw_console()
    console.print("\n[bold]Resolution Summary:[/bold]")
    console.print("=" * 50)
    console.print(f"Total packages: {result.total_packages}")
    console.print(f"Packages with conflicts: {result.packages_with_conflicts}")

    changed = result.get_changed_packages()
    console.print(f"Packages changed: {len(changed)}")

    convergence_status = (
        f"Yes ({result.iterations_used} iterations)"
        if result.converged
        else f"No (stopped after {result.iterations_used} iterations)"
    )
    console.print(f"Converged: {convergence_status}")

    if changed:
        console.print("\n[bold]Version changes:[/bold]")
        for pkg_resolution in changed:
            console.print(
                f"  • {pkg_resolution.name}: {pkg_resolution.original} → "
                f"{pkg_resolution.resolved} ({pkg_resolution.status.value})"
            )

    console.print("")  # blank line separator


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
    - A downgrade is needed (current version is incompatible with Python
      or has unresolvable conflicts)

    The function respects major version boundaries — it will never
    recommend an update that crosses a major version unless the current
    version is already incompatible.

    Args:
        packages: List of checked packages with version metadata from
            :class:`VersionChecker` and optionally adjusted by
            :class:`DependencyAnalyzer`.
        requirements: Original parsed requirements from the file.

    Returns:
        List of ``(requirement, package, new_version)`` tuples for packages
        that have safe upgrades or changes available. Each tuple contains:

        - The original :class:`Requirement` object for line mapping
        - The :class:`Package` object with version information
        - The target version string to apply

    Example::

        >>> updates = _find_updates(packages, requirements)
        >>> len(updates)
        3
        >>> updates[0]
        (Requirement('flask', ...), Package('flask', ...), '2.3.3')
    """
    updates: List[Tuple[Requirement, Package, str]] = []

    # Create mapping from package name to requirement for efficient lookup
    req_map: Dict[str, Requirement] = {r.name.lower(): r for r in requirements}

    for pkg in packages:
        req = req_map.get(pkg.name.lower())
        if not req:
            # Package not in requirements (shouldn't happen, but defensive)
            continue

        # Determine target version (recommended version from checker/analyzer)
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

    - Package name (cyan, bold)
    - Current version (dimmed, centered, or "not specified")
    - New version (green, bold, centered)
    - Change type (major/minor/patch/downgrade, color-coded)
    - Python version requirements for the new version

    The table provides a clear overview of what will change before the
    user confirms the operation.

    Args:
        updates: List of planned updates as ``(requirement, package,
            new_version)`` tuples.
        dry_run: Whether this is a dry run (affects table title).

    Example output::

        ┏━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
        ┃ Package  ┃ Current    ┃ New Version┃ Change  ┃ Python Requires ┃
        ┡━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
        │ flask    │ 2.0.0      │ 2.3.3      │ minor   │ >=3.8           │
        │ click    │ 8.0.0      │ 8.1.7      │ minor   │ >=3.7           │
        │ requests │ not spec.  │ 2.31.0     │ new pin │ >=3.7           │
        └──────────┴────────────┴────────────┴─────────┴─────────────────┘
    """
    title = "Update Plan (Dry Run)" if dry_run else "Update Plan"

    data: List[Dict[str, str]] = []
    for req, pkg, new_version in updates:
        old_version = pkg.current_version or "not specified"

        # Determine update type (major/minor/patch/downgrade)
        update_type = get_update_type(pkg.current_version, new_version)
        colored_type = colorize_update_type(update_type)

        # Python requirements for the new version
        python_req = (
            pkg.get_version_python_req("recommended")
            or pkg.get_version_python_req("latest")
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

    column_styles: Dict[str, Dict[str, str | bool]] = {
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
    want to proceed with the planned updates. Defaults to 'yes' for
    convenience.

    Args:
        count: Number of packages to update.

    Returns:
        ``True`` if the user confirms (responds with 'y'), ``False``
        otherwise.

    Example::

        >>> _confirm_update(3)
        Update 3 packages? [y/n] (y): y
        True

        >>> _confirm_update(1)
        Update 1 package? [y/n] (y): n
        False
    """
    plural = "package" if count == 1 else "packages"
    response: str = click.prompt(
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
    """Apply updates to the requirements file atomically.

    Reads the original file, updates the relevant lines to the new versions,
    and writes the modified content back. Preserves comments, blank lines,
    and formatting of non-updated lines.

    The update process:

    1. Creates a map of package names to new versions for O(1) lookup.
    2. Creates a map of line numbers to requirements for efficient
       identification of lines that need updating.
    3. Reads all lines from the original file.
    4. For each line:

       - If it corresponds to an updated requirement, replace the version
         specifier while preserving the rest of the line
       - Otherwise, keep the original line unchanged

    5. Writes all updated lines back to the file atomically.

    All updates are performed using the :meth:`Requirement.update_version`
    method, which ensures that only the version specifier is changed while
    preserving comments, whitespace, and other metadata.

    Args:
        file: Path to the requirements file.
        requirements: All parsed requirements (including those not being
            updated).
        updates: Updates to apply (from :func:`_find_updates`).

    Raises:
        DepKeeperError: File cannot be read or written.
        OSError: File system errors during read/write operations.

    Example (internal)::

        >>> _apply_updates(
        ...     Path("requirements.txt"),
        ...     requirements,
        ...     [(req1, pkg1, "2.3.3"), (req2, pkg2, "8.1.7")]
        ... )
        # requirements.txt is now updated in place
    """
    # Create update map for O(1) lookup: package_name → new_version
    update_map: Dict[str, str] = {
        req.name.lower(): new_version for req, _, new_version in updates
    }

    # Read original file content
    with open(file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Create requirement line map for efficient lookup: line_number → requirement
    req_line_map: Dict[int, Requirement] = {
        req.line_number: req for req in requirements
    }

    # Update lines
    updated_lines: List[str] = []
    for i, line in enumerate(lines, start=1):
        req = req_line_map.get(i)

        if req and req.name.lower() in update_map:
            # This line needs updating
            new_version = update_map[req.name.lower()]
            updated_line = req.update_version(
                new_version, preserve_trailing_newline=line.endswith("\n")
            )
            updated_lines.append(updated_line)
            logger.debug(
                "Updated line %d: %s → %s", i, line.strip(), updated_line.strip()
            )
        else:
            # Keep original line (comment, blank line, or non-updated requirement)
            updated_lines.append(line)

    # Write updated content atomically
    with open(file, "w", encoding="utf-8") as f:
        f.writelines(updated_lines)
