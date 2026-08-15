"""Update command implementation for depkeeper.

Rewrites requirements files to safe upgrade versions while respecting major
version boundaries, Python compatibility, and the version ranges the author
declared. All writes are atomic and multi-file updates roll back as a unit.
"""

from __future__ import annotations

import sys
import click
import shutil
import asyncio
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, NamedTuple, Optional, Set, Tuple

from depkeeper.models import Package, Requirement
from depkeeper.exceptions import DepKeeperError, FileOperationError, ParseError
from depkeeper.context import pass_context, DepKeeperContext
from depkeeper.constants import (
    BOM_CHARACTER,
    BOM_WRITE_ENCODING,
    DEFAULT_WRITE_ENCODING,
)
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
    safe_write_file,
    normalize_package_name,
)
from depkeeper.utils.version_utils import (
    retained_specs,
    rewrite_version_specs,
    specs_allow_version,
    specs_to_string,
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
    "--allow-hash-removal",
    is_flag=True,
    help=(
        "Allow updates that remove --hash entries. By default, depkeeper "
        "refuses hashed updates to avoid silent integrity regressions."
    ),
)
@click.option(
    "--pin",
    is_flag=True,
    help=(
        "Replace every version specifier with an exact ==<version> pin. By "
        "default depkeeper only raises the lower bound and preserves declared "
        "upper bounds, exclusions and compatible-release ranges."
    ),
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
    default=None,
    help="Only use exact version pins, don't infer from constraints.",
)
@click.option(
    "--check-conflicts/--no-check-conflicts",
    default=None,
    help="Check for dependency conflicts and adjust versions accordingly.",
)
@pass_context
def update(
    ctx: DepKeeperContext,
    file: Path,
    dry_run: bool,
    yes: bool,
    backup: bool,
    allow_hash_removal: bool,
    pin: bool,
    packages: Tuple[str, ...],
    strict_version_matching: Optional[bool],
    check_conflicts: Optional[bool],
) -> None:
    """Update packages to safe upgrade versions.

    Updates packages to their recommended versions -- the maximum version
    within the same major version that is compatible with your Python
    version. This avoids breaking changes from major version upgrades.

    Declared version ranges are preserved: only the lower bound of a
    requirement is moved, so ``celery>=5.0,<6.0`` becomes ``celery>=5.5.3,<6.0``
    rather than a hard pin. Use ``--pin`` to convert requirements to exact
    ``==`` pins instead.

    \b
    When --check-conflicts is enabled (the default), the command:
      1. Fetches initial recommendations for every package.
      2. Cross-validates all recommendations to detect conflicts.
      3. Iteratively adjusts versions until a conflict-free set is found.
      4. Applies the final resolved versions to the requirements file.

    Options not explicitly provided on the command line fall back to values
    from the configuration file (depkeeper.toml or pyproject.toml), then
    to built-in defaults.
    \f

    Args:
        ctx: Depkeeper context with configuration and verbosity settings.
        file: Path to the requirements file (default: ``requirements.txt``).
        dry_run: Preview changes without modifying the file.
        yes: Skip confirmation prompt before applying updates.
        backup: Create a timestamped backup before modifying the file.
        allow_hash_removal: Allow updates that remove ``--hash`` entries.
        pin: Replace all specifiers with an exact ``==`` pin instead of
            preserving the declared range.
        packages: Only update these packages (empty = update all).
        strict_version_matching: Don't infer current versions from
            constraints; only use exact pins (``==``). Falls back to the
            ``strict_version_matching`` config option.
        check_conflicts: Enable dependency conflict resolution. Falls
            back to the ``check_conflicts`` config option.

    Exits:
        0 if updates were applied successfully or no updates needed,
        1 if an error occurred.
    """
    cfg = ctx.config
    if strict_version_matching is None:
        strict_version_matching = cfg.strict_version_matching if cfg else False
    if check_conflicts is None:
        check_conflicts = cfg.check_conflicts if cfg else True

    try:
        asyncio.run(
            _update_async(
                ctx,
                file,
                dry_run,
                yes,
                backup,
                allow_hash_removal,
                pin,
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
    allow_hash_removal: bool,
    pin: bool,
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
        allow_hash_removal: Whether hashed requirements may be updated by
            removing ``--hash`` entries.
        pin: Replace all specifiers with an exact ``==`` pin instead of
            preserving the declared range.
        package_filter: List of package names to update (empty = all).
        infer_version_from_constraints: Infer current version from
            constraints (e.g., ``>=2.0`` → current is ``2.0``).
        check_conflicts: Enable dependency conflict resolution to ensure
            recommended versions are mutually compatible.

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
                _display_resolution_summary(resolution_result)

    # ── Step 4: Filter packages if requested ──────────────────────────
    if package_filter:
        # Canonicalize so `--packages my_pkg`, `My.Pkg` and `my-pkg` all match
        # the parser's PEP 503 name for the same distribution.
        wanted = {normalize_package_name(p) for p in package_filter}
        packages = [p for p in packages if normalize_package_name(p.name) in wanted]
        requirements = [
            r for r in requirements if normalize_package_name(r.name) in wanted
        ]

        if not packages:
            print_warning(f"No matching packages found: {', '.join(package_filter)}")
            return

    # ── Step 5: Find packages that need updates ───────────────────────
    updates = _find_updates(packages, requirements, pin=pin)

    # Refuse hash-stripping updates by default. Hashes are version-specific
    # integrity pins and cannot be silently removed without weakening security.
    hashed_updates = _find_hashed_updates(updates)
    if hashed_updates and not allow_hash_removal:
        package_names = ", ".join(
            sorted({req.name for req, _pkg, _ver in hashed_updates})
        )
        raise DepKeeperError(
            "Refusing to update requirement(s) with --hash entries: "
            f"{package_names}. Hashes are version-specific and cannot be "
            "silently removed. Re-run with --allow-hash-removal to proceed "
            "without hashes."
        )

    if hashed_updates and allow_hash_removal:
        package_names = ", ".join(
            sorted({req.name for req, _pkg, _ver in hashed_updates})
        )
        print_warning(
            "Proceeding with --allow-hash-removal: hashes will be removed for "
            f"{package_names}"
        )
        logger.warning(
            "Removing hashes for %d requirement(s): %s",
            len(hashed_updates),
            package_names,
        )

    if not updates:
        print_success("All packages are up to date!")
        return

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

    # ── Step 8: Create backups if requested ───────────────────────────
    # An update may touch multiple files (the primary file plus any files it
    # pulls in via -r includes), so back up every file that will change.
    backups: Dict[Path, Path] = {}
    if backup:
        for affected_file in _resolve_affected_files(file, updates):
            backup_path = create_timestamped_backup(affected_file)
            backups[affected_file] = backup_path
            logger.info("Created backup: %s", backup_path)

    # ── Step 9: Apply updates ─────────────────────────────────────────
    try:
        _apply_updates(
            file,
            requirements,
            updates,
            allow_hash_removal=allow_hash_removal,
            pin=pin,
        )
        print_success(f"\n✓ Successfully updated {len(updates)} package(s)")

        for req, pkg, new_version in updates:
            old_version = pkg.current_version or "not specified"
            logger.debug("  %s: %s → %s", req.name, old_version, new_version)

    except Exception as e:
        # Backups are the last line of defence: _apply_updates already rolls
        # back its own committed writes, but a partially applied batch that
        # failed for another reason must still be restorable.
        if backups:
            print_error(f"Error during update: {e}")
            logger.info("Restoring from backup...")
            for target, backup_path in backups.items():
                if backup_path.exists():
                    shutil.copy2(backup_path, target)
            print_success("Restored original file(s) from backup")
        raise DepKeeperError(f"Failed to apply updates: {e}") from e


def _display_resolution_summary(result: ResolutionResult) -> None:
    """Print a human-readable summary of the conflict resolution process.

    Shown only under ``--verbose``; the update plan table is the primary
    output for this command.

    Args:
        result: The :class:`ResolutionResult` from the dependency analyzer.

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

    console.print("")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _find_updates(
    packages: List[Package],
    requirements: List[Requirement],
    *,
    pin: bool = False,
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

    Direct references (VCS/URL/local-path and editable installs) are always
    skipped: they are pinned to a source rather than a PyPI version, so a
    version specifier cannot be appended without producing an uninstallable
    line.

    Unless *pin* is set, upper bounds and exclusions declared in the file are
    preserved by the writer, so a target version they exclude is skipped
    rather than written as an unsatisfiable line such as ``flask>=2.3.3,<2.3``.
    The conflict resolver can propose such a version even though
    :class:`~depkeeper.core.checker.VersionChecker` already filters candidates.
    Targets that would leave the line byte-identical are skipped as well, so
    repeated runs converge.

    Args:
        packages: List of checked packages with version metadata from
            :class:`VersionChecker` and optionally adjusted by
            :class:`DependencyAnalyzer`. Paired positionally with
            *requirements* (same length, same order), so duplicate
            declarations of the same package are each handled independently.
        requirements: Original parsed requirements from the file, one per
            entry in *packages*.
        pin: Whether the writer will replace all specifiers with an exact
            ``==`` pin. When ``True``, no declared constraint survives, so
            the constraint compatibility check is skipped.

    Returns:
        List of ``(requirement, package, new_version)`` tuples for packages
        that have safe upgrades or changes available. Each tuple contains:

        - The original :class:`Requirement` object for line mapping
        - The :class:`Package` object with version information
        - The target version string to apply
    """
    updates: List[Tuple[Requirement, Package, str]] = []

    if len(packages) != len(requirements):
        logger.warning(
            "packages (%d) and requirements (%d) length mismatch; "
            "some requirements may not be checked for updates",
            len(packages),
            len(requirements),
        )

    for req, pkg in zip(requirements, packages):
        # A mismatch means the lists weren't paired as documented above —
        # skip rather than pairing a requirement with an unrelated package.
        if normalize_package_name(req.name) != normalize_package_name(pkg.name):
            logger.warning(
                "Requirement/package name mismatch at this position "
                "(%s vs %s); skipping",
                req.name,
                pkg.name,
            )
            continue

        # Skip direct references (VCS/URL/local-path/editable installs). These
        # are pinned to a source, not a PyPI version, so a version specifier
        # cannot be appended without producing an uninstallable line such as
        # "-e git+https://...#egg=pkg==9.9.9". They are not version-managed by
        # PyPI metadata, so there is nothing safe to update here.
        if req.url or req.editable:
            logger.debug(
                "Skipping direct reference (url/editable) for %s", req.name
            )
            continue

        # Determine target version (recommended version from checker/analyzer)
        target_version = pkg.recommended_version
        if not target_version:
            logger.debug("No target version for %s", pkg.name)
            continue

        if not pin:
            preserved = retained_specs(req.specs)
            if not specs_allow_version(preserved, target_version):
                print_warning(
                    f"Skipping {req.name}: {target_version} is excluded by the "
                    f"declared constraint '{specs_to_string(preserved)}' "
                    "(use --pin to replace the constraint)"
                )
                logger.warning(
                    "Skipping %s: target %s violates declared constraint '%s'",
                    req.name,
                    target_version,
                    specs_to_string(preserved),
                )
                continue

            # Rewriting only moves the declared floor, so a target already
            # covered by the existing floor produces a byte-identical line.
            # Reporting that as an update would never converge (e.g. `~=2.3`
            # keeps selecting 2.3.3 at the author's two-component precision).
            if rewrite_version_specs(req.specs, target_version) == list(req.specs):
                logger.debug(
                    "Skipping %s: %s is already covered by '%s'",
                    req.name,
                    target_version,
                    specs_to_string(req.specs),
                )
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
            logger.info(                "Downgrade needed for %s: %s → %s",
                pkg.name,
                pkg.current_version,
                target_version,
            )
            updates.append((req, pkg, target_version))

    return updates


def _find_hashed_updates(
    updates: List[Tuple[Requirement, Package, str]],
) -> List[Tuple[Requirement, Package, str]]:
    """Return updates targeting requirements that include ``--hash`` pins."""
    return [item for item in updates if item[0].hashes]


def _display_update_plan(
    updates: List[Tuple[Requirement, Package, str]],
    dry_run: bool,
) -> None:
    """Display the planned updates as a Rich table.

    This is the last thing the user sees before confirming, so it must show
    every change that will be written: package, current and target version,
    the change classification, and the Python requirement of the new version.

    Args:
        updates: Planned updates as ``(requirement, package, new_version)``
            tuples.
        dry_run: Marks the table title as a preview.
    """
    title = "Update Plan (Dry Run)" if dry_run else "Update Plan"

    data: List[Dict[str, str]] = []
    for req, pkg, new_version in updates:
        old_version = pkg.current_version or "not specified"

        update_type = get_update_type(pkg.current_version, new_version)
        colored_type = colorize_update_type(update_type)

        # Fall back to the latest release's requirement when the target
        # version's own metadata was never fetched.
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
    """Prompt the user to confirm the planned updates.

    Defaults to yes, because the plan table has already been shown and the
    user explicitly invoked ``update``. Click re-prompts on invalid input.

    Args:
        count: Number of packages to update.

    Returns:
        ``True`` when the user confirms.

    Example::

        Update 3 packages? (y, n) [y]: y
    """
    plural = "package" if count == 1 else "packages"
    response: str = click.prompt(
        f"\nUpdate {count} {plural}?",
        type=click.Choice(["y", "n"], case_sensitive=False),
        default="y",
        show_choices=True,
    )
    return response.lower() == "y"


def _update_target_path(req: Requirement, default_file: Path) -> Path:
    """Return the file that a requirement should be written back to.

    Requirements pulled in via ``-r``/``--requirement`` includes carry the
    path of the *included* file in :attr:`Requirement.source_file`. Standard
    requirements carry the path of the primary file. When provenance is
    missing (e.g. requirements built via ``parse_string`` without a source
    path), fall back to *default_file*.

    Args:
        req: The parsed requirement.
        default_file: The primary requirements file passed to the command.

    Returns:
        The :class:`Path` of the file the requirement lives in.
    """
    # The parser stores resolved paths; resolving the fallback too keeps both
    # kinds of provenance comparable, so one file is never written twice under
    # two spellings of the same path.
    source = Path(req.source_file) if req.source_file else default_file
    return source.resolve()


def _resolve_affected_files(
    file: Path,
    updates: List[Tuple[Requirement, Package, str]],
) -> Set[Path]:
    """Return the set of files that will be modified by *updates*.

    Because a requirements file may include others via ``-r``, a single
    ``update`` invocation can legitimately touch multiple files. This is used
    to back up every file that will change, not just the primary one.

    Args:
        file: The primary requirements file passed to the command.
        updates: Updates to apply (from :func:`_find_updates`).

    Returns:
        Set of :class:`Path` objects that :func:`_apply_updates` will write.
    """
    return {_update_target_path(req, file) for req, _pkg, _new_version in updates}


class _PendingWrite(NamedTuple):
    """A fully rendered file update waiting to be committed to disk.

    Attributes:
        path: File to replace.
        original: Content read from the file, without a byte order mark.
        updated: Content to write, without a byte order mark.
        encoding: Encoding to write with (``utf-8-sig`` re-emits a BOM).
    """

    path: Path
    original: str
    updated: str
    encoding: str


def _rollback_writes(committed: List[_PendingWrite]) -> None:
    """Restore already-written files to their original content.

    Used when a multi-file update fails part way through, so the ``-r``
    include graph is never left half-updated. Restore failures are reported
    but do not mask the error that triggered the rollback.

    Args:
        committed: Writes that were successfully applied, in commit order.
    """
    for write in reversed(committed):
        try:
            safe_write_file(
                write.path,
                write.original,
                create_backup=False,
                encoding=write.encoding,
            )
            logger.info("Rolled back %s", write.path)
        except FileOperationError as exc:
            logger.error("Failed to roll back %s: %s", write.path, exc)
            print_error(f"Could not restore {write.path}: {exc}")


def _commit_pending_writes(pending: List[_PendingWrite]) -> None:
    """Write every rendered file atomically, rolling back on failure.

    Each file is replaced through :func:`safe_write_file`, which writes to a
    temporary file in the same directory, ``fsync``s it and renames it over
    the target. A crash, ``Ctrl-C`` or a full disk therefore leaves either the
    complete old file or the complete new one -- never a truncated one.

    Args:
        pending: Rendered writes produced by :func:`_apply_updates`.

    Raises:
        DepKeeperError: A file could not be written; files already written in
            this batch have been restored.
    """
    committed: List[_PendingWrite] = []

    for write in pending:
        try:
            safe_write_file(
                write.path,
                write.updated,
                create_backup=False,
                encoding=write.encoding,
            )
        except FileOperationError as exc:
            if committed:
                logger.error(
                    "Write failed for %s; rolling back %d file(s)",
                    write.path,
                    len(committed),
                )
                _rollback_writes(committed)
            raise DepKeeperError(f"Failed to write {write.path}: {exc}") from exc

        committed.append(write)


def _apply_updates(
    file: Path,
    requirements: List[Requirement],
    updates: List[Tuple[Requirement, Package, str]],
    *,
    allow_hash_removal: bool = False,
    pin: bool = False,
) -> None:
    """Apply updates to the requirements file(s), one file at a time.

    Reads each affected file, updates only the lines that correspond to an
    updated requirement, and writes the modified content back. Comments,
    blank lines, and formatting of non-updated lines are preserved.

    Requirements pulled in through ``-r``/``--requirement`` includes retain
    the line numbers of the *included* file. Matching on line number alone
    would therefore rewrite unrelated lines in the parent file (destroying
    the ``-r`` directive and corrupting the dependency graph). To avoid this,
    updates are grouped by their source file (:attr:`Requirement.source_file`)
    and matched on the ``(source_file, line_number)`` pair, so every file is
    rewritten independently and correctly.

    The update process for each affected file:

    1. Collect the ``line_number → new_version`` updates that belong to it.
    2. Read all of its lines, preserving each line's original terminator.
    3. For each line, if a requirement on that exact line is being updated,
       replace the version specifier while preserving the rest of the line;
       otherwise keep the line unchanged.

    Every file is rendered in memory first and only committed once *all* of
    them render successfully, so a rejected requirement (hashed line, or a
    target excluded by the declared range) can never leave a partially
    updated set of files. Each commit is an atomic replace (temporary file →
    ``fsync`` → rename), and if a later file fails to write, the files
    already written are rolled back. A UTF-8 byte order mark is re-emitted
    for files that originally carried one.

    All updates are rendered via :meth:`Requirement.update_version`, which
    changes only the version specifier while preserving comments, whitespace,
    and other metadata. Declared upper bounds, exclusions and
    compatible-release ranges are preserved unless *pin* is set.

    Args:
        file: Path to the primary requirements file. Used as a fallback for
            requirements that lack source-file provenance.
        requirements: All parsed requirements (including those not being
            updated), used to locate the requirement on each updated line.
        updates: Updates to apply (from :func:`_find_updates`).
        allow_hash_removal: Whether updates that remove ``--hash`` entries
            are allowed.
        pin: Replace every specifier with an exact ``==`` pin instead of
            preserving the declared range.

    Raises:
        DepKeeperError: A file cannot be read or written, or an update cannot
            be rendered.
    """
    # Map (source_file, line_number) → Requirement so each updated line is
    # rendered by the exact requirement that produced it.
    req_by_location: Dict[Tuple[str, int], Requirement] = {}
    for parsed_req in requirements:
        location_key = (
            str(_update_target_path(parsed_req, file)),
            parsed_req.line_number,
        )
        req_by_location[location_key] = parsed_req

    # Group the target version for each update by the file it belongs to,
    # keyed by line number within that file.
    updates_by_file: Dict[str, Dict[int, str]] = defaultdict(dict)
    for update_req, _pkg, target_version in updates:
        target = str(_update_target_path(update_req, file))
        updates_by_file[target][update_req.line_number] = target_version

    # Render each affected file independently. Nothing is written yet.
    pending: List[_PendingWrite] = []

    for target_str in sorted(updates_by_file):
        line_updates = updates_by_file[target_str]
        target_path = Path(target_str)

        try:
            # ``newline=""`` keeps each line's original terminator, so a CRLF
            # or mixed-ending file is not silently rewritten to the platform
            # default. Reading as plain ``utf-8`` (not ``utf-8-sig``) keeps a
            # byte order mark visible so it can be detected below.
            with open(target_path, "r", encoding="utf-8", newline="") as f:
                lines = f.readlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise DepKeeperError(
                f"Failed to read {target_path}: {exc}"
            ) from exc

        # Strip the BOM: the parser sees BOM-free content, so line 1 must be
        # BOM-free here too for rendered replacements to match.
        has_bom = bool(lines) and lines[0].startswith(BOM_CHARACTER)
        if has_bom:
            lines[0] = lines[0][len(BOM_CHARACTER):]

        updated_lines: List[str] = []
        for line_number, line in enumerate(lines, start=1):
            new_version = line_updates.get(line_number)
            req = (
                req_by_location.get((target_str, line_number))
                if new_version is not None
                else None
            )

            if req is not None and new_version is not None:
                if req.hashes and not allow_hash_removal:
                    raise DepKeeperError(
                        f"Refusing to update hashed requirement at "
                        f"{target_path}:{line_number}. Re-run with "
                        "--allow-hash-removal to proceed without hashes."
                    )
                # Re-attach the line's own terminator so a single rewritten
                # line cannot change the file's line-ending style.
                line_ending = line[len(line.rstrip("\r\n")):]
                try:
                    updated_line = req.update_version(
                        new_version,
                        pin=pin,
                        preserve_trailing_newline=False,
                        allow_hash_removal=allow_hash_removal,
                    ) + line_ending
                except ValueError as exc:
                    raise DepKeeperError(
                        f"Cannot update requirement at "
                        f"{target_path}:{line_number}: {exc}"
                    ) from exc
                updated_lines.append(updated_line)
                logger.debug(
                    "Updated %s line %d: %s → %s",
                    target_path.name,
                    line_number,
                    line.strip(),
                    updated_line.strip(),
                )
            else:
                # Keep original line (comment, blank, or non-updated requirement)
                updated_lines.append(line)

        # ``utf-8-sig`` re-emits the byte order mark on write, so a
        # BOM-carrying file keeps its signature even when line 1 is rewritten.
        pending.append(
            _PendingWrite(
                path=target_path,
                original="".join(lines),
                updated="".join(updated_lines),
                encoding=BOM_WRITE_ENCODING if has_bom else DEFAULT_WRITE_ENCODING,
            )
        )

    # Commit only after every file rendered successfully.
    _commit_pending_writes(pending)
