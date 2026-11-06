"""Update command implementation for depkeeper.

Rewrites requirements files to safe upgrade versions while respecting major
version boundaries, Python compatibility, and the version ranges the author
declared. All writes are atomic and multi-file updates roll back as a unit.
"""

from __future__ import annotations

import re
import sys
import click
import asyncio
from pathlib import Path
from datetime import timedelta
from dataclasses import replace
from functools import partial
from collections import defaultdict
from typing import (
    TYPE_CHECKING,
    Callable,
    Dict,
    List,
    NamedTuple,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from depkeeper.models import Package, Requirement
from depkeeper.config import DepKeeperConfig
from depkeeper.commands import _report
from depkeeper.exceptions import DepKeeperError, FileOperationError
from depkeeper.context import pass_context, DepKeeperContext
from depkeeper.constants import (
    BOM_CHARACTER,
    BOM_WRITE_ENCODING,
    DEFAULT_WRITE_ENCODING,
)
from depkeeper.core import (
    PyPIDataStore,
    VersionChecker,
    DependencyAnalyzer,
    ResolutionResult,
)
from depkeeper.core.parser import RequirementsParser
from depkeeper.core.sources import default_target, get_adapter, parse_targets
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
    safe_read_file,
    safe_write_file,
    normalize_package_name,
)
from depkeeper.utils.version_utils import (
    UPDATE_RANK,
    gating_type,
    parse_version_lenient,
    retained_specs,
    rewrite_version_specs,
    specs_allow_version,
    specs_to_string,
)

if TYPE_CHECKING:
    from depkeeper.core.verify import VerifyResult

logger = get_logger("commands.update")


@click.command()
@click.argument(
    "file",
    type=click.Path(exists=True, dir_okay=True, path_type=Path),
    required=False,
    default=None,
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
    "--refresh-hashes",
    is_flag=True,
    help=(
        "When a hashed requirement is updated, regenerate its --hash=sha256 "
        "lines for the new version from PyPI instead of refusing. Refuses a "
        "package whose digests cannot be fetched. Conflicts with "
        "--allow-hash-removal."
    ),
)
@click.option(
    "--verify",
    is_flag=True,
    help=(
        "Before writing, ask pip's resolver whether the proposed requirement "
        "set resolves; abort (exit 1, nothing written) on a conflict. "
        "Skipped with a warning when pip is unavailable."
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
    "--ignore",
    "ignore",
    multiple=True,
    help="Never update this package (can be repeated).",
)
@click.option(
    "--max-update",
    type=click.Choice(["patch", "minor", "major"]),
    default=None,
    help="Skip updates larger than this level (e.g. 'minor' skips major bumps).",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "markdown"], case_sensitive=False),
    default="table",
    help="table (default) or markdown: a PR-body of what changed (or would "
    "change with --dry-run) on stdout. markdown needs --yes or --dry-run.",
)
@click.option(
    "--python-version",
    metavar="X.Y",
    callback=_report.python_version_option,
    default=None,
    help="Python version candidates must support. Default: config "
    "python_version, else the file's requires-python / conda python pin "
    "(lowest supported minor), else the running interpreter.",
)
@click.option(
    "--min-age",
    metavar="DURATION",
    callback=_report.min_age_option,
    default=None,
    help="Don't update to versions released more recently than this "
    "(e.g. 7d, 12h, 2w). Default: config min_age.",
)
@click.option(
    "--allow-major",
    "allow_major",
    multiple=True,
    metavar="PKG",
    help="Allow this package to cross its current major (repeatable; '*' = all). "
    "Your declared upper bounds and --max-update still apply.",
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
    file: Optional[Path],
    dry_run: bool,
    yes: bool,
    backup: bool,
    allow_hash_removal: bool,
    refresh_hashes: bool,
    verify: bool,
    pin: bool,
    packages: Tuple[str, ...],
    ignore: Tuple[str, ...],
    max_update: Optional[str],
    output_format: str,
    python_version: Optional[str],
    min_age: Optional[timedelta],
    allow_major: Tuple[str, ...],
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
        file: A dependency file or a directory to scan (default:
            ``requirements.txt``, else discovery in the current directory).
        dry_run: Preview changes without modifying the file.
        yes: Skip confirmation prompt before applying updates.
        backup: Create a timestamped backup before modifying the file.
        allow_hash_removal: Allow updates that remove ``--hash`` entries.
        refresh_hashes: Regenerate ``--hash`` entries for the new version.
        verify: Check the proposed set with pip's resolver before writing.
        pin: Replace all specifiers with an exact ``==`` pin instead of
            preserving the declared range.
        packages: Only update these packages (empty = update all).
        ignore: Packages that must never be updated (merged with the
            ``ignore`` config).
        max_update: Largest update level to apply (``patch``/``minor``/``major``).
            Calver ``month`` counts as minor, ``year`` as minor too (not breaking).
        output_format: ``table`` or ``markdown`` (PR body on stdout).
        python_version: Target Python (``X.Y``); beats config and the file's
            own ``requires-python``.
        min_age: Release cooldown; beats config ``min_age``.
        strict_version_matching: Don't infer current versions from
            constraints; only use exact pins (``==``). Falls back to the
            ``strict_version_matching`` config option.
        check_conflicts: Enable dependency conflict resolution. Falls
            back to the ``check_conflicts`` config option.

    Exits:
        0 if updates were applied successfully or no updates needed,
        1 if an error occurred or the update was declined,
        4 if some packages could not be looked up on PyPI.
    """
    file = default_target(file)
    if not file.exists():
        raise click.UsageError(f"File '{file}' does not exist.")
    if refresh_hashes and allow_hash_removal:
        raise click.UsageError(
            "--refresh-hashes and --allow-hash-removal are mutually exclusive: "
            "the first regenerates hashes, the second deletes them."
        )
    cfg = ctx.config
    if strict_version_matching is None:
        strict_version_matching = cfg.strict_version_matching if cfg else False
    if check_conflicts is None:
        check_conflicts = cfg.check_conflicts if cfg else True
    output_format = output_format.lower()
    if output_format == "markdown" and not (yes or dry_run):
        raise click.UsageError(
            "--format markdown needs --yes or --dry-run (no prompt)."
        )
    python = _report.resolve_target_python(python_version, cfg, file)
    logger.info(
        "Target Python: %s (from %s)", python[0] or "running interpreter", python[1]
    )

    try:
        code = asyncio.run(
            _update_async(
                ctx,
                file,
                dry_run,
                yes,
                backup,
                allow_hash_removal,
                pin,
                list(packages),
                refresh_hashes=refresh_hashes,
                verify=verify,
                infer_version_from_constraints=not strict_version_matching,
                check_conflicts=check_conflicts,
                ignore={
                    normalize_package_name(i)
                    for i in list(cfg.ignore if cfg else []) + list(ignore)
                },
                max_update=max_update,
                output_format=output_format,
                python=python,
                min_age=min_age,
                allow_major=_report.allow_major_names(allow_major),
            )
        )
        sys.exit(code)

    except DepKeeperError as e:
        print_error(e.message)
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {type(e).__name__}: {e}")
        logger.debug("Error in update command", exc_info=True)
        sys.exit(1)


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
    ignore: Optional[Set[str]] = None,
    max_update: Optional[str] = None,
    output_format: str = "table",
    python: Tuple[Optional[str], str] = (None, "running interpreter"),
    min_age: Optional[timedelta] = None,
    allow_major: Sequence[str] = (),
    refresh_hashes: bool = False,
    verify: bool = False,
) -> int:
    """Run the update pipeline and return the process exit code.

    Parses the target, fetches PyPI data through one shared `PyPIDataStore`,
    computes recommendations with `VersionChecker`, optionally resolves
    conflicts with `DependencyAnalyzer`, filters to ``--packages``, shows the
    plan, confirms, optionally backs up, and applies the updates atomically.

    Args:
        ctx: Depkeeper context with verbosity and configuration.
        file: A dependency file or a directory to scan.
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
        refresh_hashes: Regenerate ``--hash`` lines of updated hashed
            requirements from PyPI file digests.
        verify: Run pip's resolver over the proposed set before writing.
        ignore: Normalized package names that must never be updated.
        max_update: Skip updates larger than this level.
        output_format: ``table`` or ``markdown``.
        python: ``(target Python or None, who decided)``.
        min_age: Release cooldown.
        allow_major: Normalised ``--allow-major`` names.

    Returns:
        0 on success, 1 when the user declined or ``--verify`` found a
        conflict, 4 when some packages could not be looked up.

    Raises:
        DepKeeperError: The target cannot be parsed or updates cannot be
            applied.
    """
    markdown = output_format == "markdown"
    # Markdown owns stdout; every status line goes to stderr.
    warn = partial(print_warning, stderr=markdown)
    ok = partial(print_success, stderr=markdown)
    logger.info("Checking %s for updates...", file)

    requirements = parse_targets(file)
    all_requirements = requirements  # --verify checks the whole final plan

    if not requirements:
        warn("No packages found in requirements file")
        return 0

    logger.info("Found %d package(s)", len(requirements))

    async with HTTPClient() as http:
        data_store = PyPIDataStore(http, target_python=python[0])

        # Failed lookups are remembered by HTTPClient, so later checks do not
        # re-wait the retry backoff for them.
        await data_store.prefetch_packages(
            [req.name for req in requirements if not (req.url or req.editable)]
        )

        checker = VersionChecker.from_config(
            data_store,
            ctx.config or DepKeeperConfig(),
            infer_version_from_constraints=infer_version_from_constraints,
            target_python=python[0],
            min_age=min_age,
            allow_major=allow_major or None,
            max_update=max_update,
        )
        packages = await checker.check_packages(requirements)
        links = _report.collect_links(data_store, packages) if markdown else {}

        resolution_result: Optional[ResolutionResult] = None
        if check_conflicts:
            logger.info("Cross-validating recommended versions...")
            analyzer = DependencyAnalyzer(
                data_store=data_store, target_python=python[0], checker=checker
            )
            resolution_result = await resolve_conflicts_by_name(analyzer, packages)

            if ctx.verbose > 0 and resolution_result:
                _report.display_resolution_summary(resolution_result, stderr=markdown)

    if package_filter:
        # Canonicalize so `--packages my_pkg`, `My.Pkg` and `my-pkg` all match
        # the parser's PEP 503 name for the same distribution.
        wanted = {normalize_package_name(p) for p in package_filter}
        packages = [p for p in packages if normalize_package_name(p.name) in wanted]
        requirements = [
            r for r in requirements if normalize_package_name(r.name) in wanted
        ]

        if not packages:
            warn(f"No matching packages found: {', '.join(package_filter)}")
            return 1

    capped: List[str] = []
    updates = _find_updates(
        packages,
        requirements,
        pin=pin,
        ignore=ignore or set(),
        max_update=max_update,
        capped=capped,
        stderr=markdown,
    )
    rows = _report.make_rows(requirements, packages, links if markdown else None)

    # A failed PyPI lookup is not "up to date": report it and exit non-zero.
    unavailable = sorted(
        {
            pkg.name
            for req, pkg in zip(requirements, packages)
            if pkg.latest_version is None
            and not (req.url or req.editable)
            and not req.approximate
            and normalize_package_name(req.name) not in (ignore or set())
        }
    )
    # Conda names may not exist on PyPI: warn, never fail the run.
    unmatched = sorted(
        {
            pkg.name
            for req, pkg in zip(requirements, packages)
            if pkg.latest_version is None and req.approximate
        }
    )
    if unmatched:
        warn(
            f"{len(unmatched)} conda package(s) not found on PyPI (may be "
            f"conda-only; left unchanged): {', '.join(unmatched)}"
        )
    if unavailable:
        warn(
            f"{len(unavailable)} package(s) could not be checked on PyPI: "
            f"{', '.join(unavailable)}"
        )
    exit_code = 4 if unavailable else 0

    # Hashes are version-specific integrity pins: never strip them silently.
    hashed_updates = _find_hashed_updates(updates)
    hash_digests: Dict[Tuple[str, str], List[str]] = {}
    if hashed_updates and refresh_hashes:
        hash_digests = await _fetch_hash_digests(hashed_updates)
        missing = sorted(
            {
                f"{req.name}=={ver}"
                for req, _pkg, ver in hashed_updates
                if (normalize_package_name(req.name), ver) not in hash_digests
            }
        )
        if missing and not dry_run:
            raise DepKeeperError(
                "Cannot refresh hashes: no PyPI file digests available for "
                f"{', '.join(missing)}. Nothing was written."
            )
        if missing:
            warn(
                "Hashes could not be fetched (would be refused): " + ", ".join(missing)
            )
        other = sorted(
            {
                r.name
                for r, _p, _v in hashed_updates
                if any(not h.lower().startswith("sha256:") for h in r.hashes)
            }
        )
        if other:
            warn(
                "--refresh-hashes writes sha256 only; existing non-sha256 hashes "
                "will be replaced for: " + ", ".join(other)
            )
        for req, _pkg, ver in hashed_updates:
            found = hash_digests.get((normalize_package_name(req.name), ver))
            if found:
                warn(
                    f"Hashes {'would be ' if dry_run else 'will be '}refreshed for "
                    f"{req.name}=={ver} ({len(found)} file hash(es))"
                )
    elif hashed_updates and not allow_hash_removal and dry_run:
        warn(
            "Hashed requirement(s) would be refused without --allow-hash-removal "
            "(or use --refresh-hashes): "
            + ", ".join(sorted({req.name for req, _pkg, _ver in hashed_updates}))
        )
    elif hashed_updates and not allow_hash_removal:
        package_names = ", ".join(
            sorted({req.name for req, _pkg, _ver in hashed_updates})
        )
        raise DepKeeperError(
            "Refusing to update requirement(s) with --hash entries: "
            f"{package_names}. Hashes are version-specific and cannot be "
            "silently removed. Re-run with --refresh-hashes to regenerate "
            "them, or --allow-hash-removal to proceed without hashes."
        )

    if hashed_updates and allow_hash_removal:
        package_names = ", ".join(
            sorted({req.name for req, _pkg, _ver in hashed_updates})
        )
        warn(
            "Proceeding with --allow-hash-removal: hashes will be removed for "
            f"{package_names}"
        )
        logger.warning(
            "Removing hashes for %d requirement(s): %s",
            len(hashed_updates),
            package_names,
        )

    for note in (
        _report.policy_note(packages),
        _report.cooldown_note(packages),
        _report.major_note(packages),
        _report.unknown_allow_major_note(allow_major, requirements),
    ):
        if note:
            warn(note)

    def emit_markdown() -> None:
        change_rows = [
            _report.Row(p, r, links.get(p.name, {}), v) for r, p, v in updates
        ]
        skipped = [
            f"`{n}`: update exceeds --max-update {max_update}"
            for n in sorted(set(capped))
        ]
        title = "depkeeper updates (dry run)" if dry_run else "depkeeper updates"
        print(
            _report.render_markdown(
                rows,
                title=title,
                python=python,
                change_rows=change_rows,
                skipped=skipped,
            ),
            end="",
        )

    if not updates:
        # An already-conflicting set must not pass as "up to date" under --verify.
        if verify and not _verify_ok(all_requirements, updates, warn, ok, python[0]):
            return 1
        if markdown:
            emit_markdown()
        if capped:
            warn(
                f"{len(capped)} update(s) skipped by --max-update {max_update}: "
                f"{', '.join(sorted(set(capped)))}"
            )
        elif not unavailable:
            ok("All packages are up to date!")
        return exit_code

    if resolution_result and resolution_result.packages_with_conflicts > 0:
        warn(
            f"\n{resolution_result.packages_with_conflicts} package(s) have "
            "unresolved conflicts — updates may cause issues"
        )

    if not markdown:
        _display_update_plan(updates, dry_run)

    majors = sorted(
        {
            pkg.name
            for _req, pkg, ver in updates
            if get_update_type(pkg.current_version, ver, pkg.versioning) == "major"
        }
    )
    if majors:
        verb = "would be applied" if dry_run else "applied"
        warn(
            f"{len(majors)} major upgrade(s) {verb}: {', '.join(majors)}. "
            "Run --verify and your tests."
        )

    if verify and not _verify_ok(all_requirements, updates, warn, ok, python[0]):
        return 1

    if dry_run:
        warn("\nDry run mode - no changes applied")
        if markdown:
            emit_markdown()
        return exit_code

    if not skip_confirm:
        if not _confirm_update(len(updates)):
            warn("Aborted. No changes were made.")
            return 1

    # An update may touch multiple files (the primary file plus any files it
    # pulls in via -r includes), so back up every file that will change.
    backups: Dict[Path, Path] = {}
    if backup:
        for affected_file in _resolve_affected_files(file, updates):
            backup_path = create_timestamped_backup(affected_file)
            backups[affected_file] = backup_path
            ok(f"Backup saved: {backup_path}")

    if file.is_symlink():
        warn(f"{file} is a symlink; updating its target {file.resolve()}")

    try:
        _apply_updates(
            file,
            requirements,
            updates,
            allow_hash_removal=allow_hash_removal,
            refresh_hashes=refresh_hashes,
            hash_digests=hash_digests,
            pin=pin,
        )
    except BaseException:
        # _apply_updates already rolled back its own writes; never overwrite
        # files from backups here, that could clobber an external edit.
        if backups:
            warn(
                "Original file(s) are saved at: "
                + ", ".join(str(b) for b in backups.values())
            )
        raise

    ok(f"Successfully updated {len(updates)} package(s)")
    if markdown:
        emit_markdown()
    for req, pkg, new_version in updates:
        old_version = pkg.current_version or "not specified"
        logger.debug("  %s: %s -> %s", req.name, old_version, new_version)
    return exit_code


async def resolve_conflicts_by_name(
    analyzer: DependencyAnalyzer, packages: List[Package]
) -> ResolutionResult:
    """Cross-validate *packages* with one entry per distinct name.

    The analyzer keys everything by name, so a package declared in several
    places (directory mode, ``-r`` includes) is validated through its
    highest-proposal declaration only. Other declarations keep their own,
    major-bounded recommendation, and only adopt the analyzer's outcome (and
    its conflicts) when their proposal was identical to the validated one.
    """
    best: Dict[str, Package] = {}
    for pkg in packages:
        proposal = parse_version_lenient(pkg.recommended_version or pkg.current_version)
        held = best.get(pkg.name)
        held_v = held and parse_version_lenient(
            held.recommended_version or held.current_version
        )
        if held is None or (
            proposal is not None and (held_v is None or proposal > held_v)
        ):
            best[pkg.name] = pkg
    if len(best) == len(packages):
        return await analyzer.resolve_and_annotate_conflicts(packages)

    seeds = {name: pkg.recommended_version for name, pkg in best.items()}
    result = await analyzer.resolve_and_annotate_conflicts(list(best.values()))
    for pkg in packages:
        rep = best[pkg.name]
        if pkg is rep or pkg.recommended_version != seeds[pkg.name]:
            continue
        pkg.recommended_version = rep.recommended_version
        pkg.set_conflicts(rep.conflicts)
        pkg.conflict_held = rep.conflict_held
        pkg.recommended_released = rep.recommended_released
        pkg.cooldown_skipped = rep.cooldown_skipped
        if "recommended_metadata" in rep.metadata:
            pkg.metadata["recommended_metadata"] = rep.metadata["recommended_metadata"]
    return result


def _find_updates(
    packages: List[Package],
    requirements: List[Requirement],
    *,
    pin: bool = False,
    ignore: Optional[Set[str]] = None,
    max_update: Optional[str] = None,
    capped: Optional[List[str]] = None,
    stderr: bool = False,
) -> List[Tuple[Requirement, Package, str]]:
    """Find packages that have safe upgrades available.

    Selects packages whose recommended version should be written: a newer
    version, a first pin for an unversioned requirement, or a downgrade when
    the current version is unusable.

    Skipped: direct references (URL/VCS/editable, which have no PyPI version
    to rewrite); ignored packages; updates above *max_update*; and, unless
    *pin* is set, targets excluded by a declared upper bound or exclusion
    (the conflict resolver can propose one) and targets that would leave the
    line byte-identical, so repeated runs converge.

    Args:
        packages: List of checked packages with version metadata from
            `VersionChecker` and optionally adjusted by
            `DependencyAnalyzer`. Paired positionally with
            *requirements* (same length, same order), so duplicate
            declarations of the same package are each handled independently.
        requirements: Original parsed requirements from the file, one per
            entry in *packages*.
        pin: Whether the writer will replace all specifiers with an exact
            ``==`` pin. When ``True``, no declared constraint survives, so
            the constraint compatibility check is skipped.
        ignore: Normalized package names that must never be updated.
        max_update: Skip updates whose level (patch/minor/major) exceeds this;
            compared through `gating_type`, so calver month/year rank as minor.
        capped: When given, receives the names whose update was capped by
            *max_update*.
        stderr: Send skip warnings to stderr (machine-readable output mode).

    Returns:
        List of ``(requirement, package, new_version)`` tuples for packages
        that have safe upgrades or changes available. Each tuple contains:

        - The original `Requirement` object for line mapping
        - The `Package` object with version information
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
        # Never pair a requirement with an unrelated package.
        if normalize_package_name(req.name) != normalize_package_name(pkg.name):
            logger.warning(
                "Requirement/package name mismatch at this position "
                "(%s vs %s); skipping",
                req.name,
                pkg.name,
            )
            continue

        # A version specifier appended to a direct reference would produce an
        # uninstallable line such as "-e git+https://...#egg=pkg==9.9.9".
        if req.url or req.editable:
            logger.debug("Skipping direct reference (url/editable) for %s", req.name)
            continue

        if ignore and normalize_package_name(req.name) in ignore:
            logger.debug("Ignoring %s (--ignore)", req.name)
            continue

        target_version = pkg.recommended_version
        if not target_version:
            logger.debug("No target version for %s", pkg.name)
            continue

        if (
            max_update
            and UPDATE_RANK.get(
                gating_type(
                    get_update_type(pkg.current_version, target_version, pkg.versioning)
                ),
                -1,
            )
            > UPDATE_RANK[max_update]
        ):
            logger.debug("Skipping %s: exceeds --max-update %s", req.name, max_update)
            # A capped major stays visible as an opt-in the user declined.
            if (
                get_update_type(pkg.current_version, target_version, pkg.versioning)
                == "major"
            ):
                pkg.major_available = pkg.major_available or target_version
                pkg.major_capped = True
            if capped is not None:
                capped.append(req.name)
            continue

        if not pin:
            preserved = retained_specs(req.specs)
            if not specs_allow_version(preserved, target_version):
                print_warning(
                    f"Skipping {req.name}: {target_version} is excluded by the "
                    f"declared constraint '{specs_to_string(preserved)}' "
                    "(use --pin to replace the constraint)",
                    stderr=stderr,
                )
                logger.warning(
                    "Skipping %s: target %s violates declared constraint '%s'",
                    req.name,
                    target_version,
                    specs_to_string(preserved),
                )
                continue

            # Rewriting only moves the declared floor, so a target the floor
            # already covers yields a byte-identical line; reporting it would
            # never converge (e.g. `~=2.3` keeps selecting 2.3.3).
            if _fuzzy_noop(req, target_version) or rewrite_version_specs(
                req.specs, target_version
            ) == list(req.specs):
                logger.debug(
                    "Skipping %s: %s is already covered by '%s'",
                    req.name,
                    target_version,
                    specs_to_string(req.specs),
                )
                continue

        if pin and pkg.current_version and _is_exact_pin(req, target_version):
            continue

        if pin and pkg.current_version and not pkg.requires_downgrade:
            # --pin rewrites the specifier even when the version stays put;
            # a lower target would be a downgrade nobody asked for.
            cur, tgt = (
                parse_version_lenient(pkg.current_version),
                parse_version_lenient(target_version),
            )
            if cur is not None and tgt is not None and tgt < cur:
                continue
            updates.append((req, pkg, target_version))
            continue

        if not pkg.current_version:
            # Bare names outside requirements files keep "only version bytes
            # change": a pin is added there only on request (--pin).
            if req.source_format in ("pyproject", "conda") and not pin:
                continue
            updates.append((req, pkg, target_version))
        elif pkg.has_update():
            updates.append((req, pkg, target_version))
        elif pkg.requires_downgrade:
            logger.info(
                "Downgrade needed for %s: %s → %s",
                pkg.name,
                pkg.current_version,
                target_version,
            )
            updates.append((req, pkg, target_version))

    return updates


async def _fetch_hash_digests(
    hashed_updates: List[Tuple[Requirement, Package, str]],
) -> Dict[Tuple[str, str], List[str]]:
    """Return sha256 digests for each ``(normalized name, new version)``; failures omitted."""
    wanted = sorted(
        {(normalize_package_name(r.name), v) for r, _p, v in hashed_updates}
    )
    async with HTTPClient() as http:
        store = PyPIDataStore(http)
        found = await asyncio.gather(
            *(store.get_version_digests(n, v) for n, v in wanted)
        )
    return {key: d for key, d in zip(wanted, found) if d}


def _plan_requirement_strings(
    requirements: List[Requirement],
    updates: List[Tuple[Requirement, Package, str]],
) -> List[str]:
    """Requirement strings of the file after the plan: updated ones pinned."""
    new_versions = {id(r): v for r, _p, v in updates}
    out: List[str] = []
    for req in requirements:
        if req.url or req.editable:
            continue
        version = new_versions.get(id(req))
        if version:
            req = replace(req, specs=[("==", version)])
        out.append(req.to_string(include_hashes=False, include_comment=False))
    return out


def _plan_constraints(requirements: List[Requirement]) -> List[str]:
    """Every ``-c`` constraint of the files, including ones for unlisted packages."""
    specs = {
        normalize_package_name(r.name): (r.name, r.constraint_specs)
        for r in requirements
        if r.constraint_specs
    }
    for f in {
        r.source_file
        for r in requirements
        if r.source_file and (r.source_format or "").startswith("requirements")
    }:
        try:
            parser = RequirementsParser()
            parser.parse_file(Path(f))
            consts = parser.get_constraints()
        except Exception:  # noqa: BLE001 -- verification is best-effort
            continue
        for name, c in consts.items():
            if c.specs:
                specs.setdefault(normalize_package_name(name), (c.name, c.specs))
    return [f"{n}{specs_to_string(sp)}" for n, sp in specs.values()]


def _verify_ok(
    requirements: List[Requirement],
    updates: List[Tuple[Requirement, Package, str]],
    warn: Callable[[str], None],
    ok: Callable[[str], None],
    python_version: Optional[str] = None,
) -> bool:
    """Run ``--verify`` on the plan for the run's target Python.

    Args:
        requirements: Parsed requirements of the file(s).
        updates: Planned ``(requirement, package, new_version)`` changes.
        warn: Warning printer (used when verification is skipped).
        ok: Success printer; receives the "what was verified" line.
        python_version: Target Python resolved for the run, or ``None`` for
            the running interpreter.

    Returns:
        ``False`` (after printing the conflicts) when pip rejects the plan.
    """
    constraints = _plan_constraints(requirements)
    plan = _plan_requirement_strings(requirements, updates)
    # Optional arguments are only passed when set so narrow stand-ins still work.
    kwargs: Dict[str, str] = (
        {"python_version": python_version} if python_version else {}
    )
    if constraints:
        result = _run_verify(plan, constraints, **kwargs)
    else:
        result = _run_verify(plan, **kwargs)
    if result.skipped:
        warn(f"--verify skipped: {result.message}")
    elif not result.ok:
        print_error("Proposed updates do not resolve (pip):", stderr=True)
        for conflict in result.conflicts or [result.message]:
            print_error(f"  {conflict}", stderr=True)
        print_error("Aborting: no changes were made.", stderr=True)
        return False
    else:
        from depkeeper.core.verify import VerifyResult

        excluded = sum(1 for r in requirements if r.url or r.editable)
        line = (
            result.summary(excluded=excluded)
            if isinstance(result, VerifyResult)
            else "pip resolved the proposed set"
        )
        ok(f"--verify: {line}")
    return True


def _run_verify(
    requirements: List[str],
    constraints: Sequence[str] = (),
    python_version: Optional[str] = None,
) -> "VerifyResult":
    """Call `depkeeper.core.verify.verify_plan` (imported lazily; tests patch this)."""
    from depkeeper.core.verify import verify_plan

    return verify_plan(
        requirements, constraints=constraints, python_version=python_version
    )


def _is_exact_pin(req: Requirement, target: str) -> bool:
    """Return whether *req* already is exactly ``==<target>`` (conda ``=`` is a series, not a pin)."""
    if len(req.specs) != 1 or req.specs[0][0] != "==":
        return False
    if req.approximate and "==" not in (req.raw_line or ""):
        return False
    have, want = parse_version_lenient(req.specs[0][1]), parse_version_lenient(target)
    return have is not None and have == want


def _fuzzy_noop(req: Requirement, target: str) -> bool:
    """Return whether *req* is a conda prefix spec (``numpy=1.24``) that already covers *target*.

    The conda writer keeps the spec's precision, so ``=1.24`` -> 1.24.5 is
    rewritten to ``=1.24``: nothing would change on disk.
    """
    raw = req.raw_line or ""
    if not (req.approximate and len(req.specs) == 1 and req.specs[0][0] == "=="):
        return False
    if not (re.search(r"[^=!<>~]=\s*\d", raw) or raw.rstrip().endswith(".*")):
        return False
    prefix = req.specs[0][1]
    lead = re.match(r"\d+(\.\d+)*", target)
    if lead is None:
        return False
    return ".".join(lead.group(0).split(".")[: len(prefix.split("."))]) == prefix


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

    Shown before confirmation, so it lists every change that will be written.

    Args:
        updates: Planned updates as ``(requirement, package, new_version)``
            tuples.
        dry_run: Marks the table title as a preview.
    """
    title = "Update Plan (Dry Run)" if dry_run else "Update Plan"

    data: List[Dict[str, str]] = []
    for req, pkg, new_version in updates:
        old_version = pkg.current_version or "not specified"

        update_type = get_update_type(pkg.current_version, new_version, pkg.versioning)
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
                "New Version": f"[bold green]{new_version}[/bold green]"
                + (
                    f"\n[dim]{_report.age_short(pkg)} old[/dim]"
                    if new_version == pkg.recommended_version
                    and pkg.recommended_released
                    else ""
                ),
                "Change": colored_type,
                "Python Requires": python_req,
            }
        )
    if _report.multi_file([_report.Row(p, r) for r, p, _ in updates]):
        for row, (req, pkg, _) in zip(data, updates):
            fmt = f"\n[dim]({req.source_format})[/dim]" if req.source_format else ""
            row["Source"] = f"{_report.source_cell(_report.Row(pkg, req))}{fmt}"

    column_styles: Dict[str, Dict[str, Union[str, bool]]] = {
        "Package": {"style": "bold cyan", "no_wrap": True},
        "Current": {"justify": "center", "style": "dim"},
        "New Version": {"justify": "center"},
        "Change": {"justify": "center"},
        "Python Requires": {"justify": "left"},
        "Source": {"justify": "left"},
    }

    print_table(data, title=title, column_styles=column_styles)


def _confirm_update(count: int) -> bool:
    """Prompt the user to confirm the planned updates.

    Defaults to yes: the plan has been shown and the user invoked ``update``.

    Args:
        count: Number of packages to update.

    Returns:
        ``True`` when the user confirms.

    Raises:
        DepKeeperError: No terminal is available to ask on.

    Example::

        Update 3 packages? (y, n) [y]: y
    """
    plural = "package" if count == 1 else "packages"
    try:
        response: str = click.prompt(
            f"\nUpdate {count} {plural}?",
            type=click.Choice(["y", "n"], case_sensitive=False),
            default="y",
            show_choices=True,
        )
    except click.Abort:
        if sys.stdin.isatty():
            raise  # Ctrl-C / Ctrl-D at a real prompt
        raise DepKeeperError(
            "Cannot ask for confirmation without a terminal. Re-run with "
            "--yes to apply or --dry-run to preview."
        ) from None
    return response.lower() == "y"


def _update_target_path(req: Requirement, default_file: Path) -> Path:
    """Return the file that a requirement should be written back to.

    Requirements from ``-r`` includes carry the included file in
    `Requirement.source_file`; without provenance, *default_file* is used.
    """
    # Both spellings are resolved so one file is never written twice under
    # two names.
    source = Path(req.source_file) if req.source_file else default_file
    return source.resolve()


def _resolve_affected_files(
    file: Path,
    updates: List[Tuple[Requirement, Package, str]],
) -> Set[Path]:
    """Return every file *updates* will modify (``-r`` includes may add more)."""
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


def _brief(exc: Exception) -> str:
    """Return a one-line, user-facing reason for *exc* (no nested details)."""
    cause = getattr(exc, "original_error", None) or exc
    if isinstance(cause, OSError) and cause.strerror:
        return cause.strerror
    return str(getattr(cause, "message", cause))


def _read_exact(path: Path) -> str:
    """Read *path* byte-faithfully (no newline translation, BOM stripped)."""
    text = safe_read_file(path, encoding="utf-8", newline="")
    return text[len(BOM_CHARACTER) :] if text.startswith(BOM_CHARACTER) else text


def _rollback_writes(committed: List[_PendingWrite]) -> List[Path]:
    """Restore already-written files to their original content.

    Restore failures are reported but do not mask the triggering error.

    Args:
        committed: Writes that were successfully applied, in commit order.

    Returns:
        Paths that could *not* be restored.
    """
    failed: List[Path] = []
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
            failed.append(write.path)
            logger.error("Failed to roll back %s: %s", write.path, exc)
            print_error(f"Could not restore {write.path}: {_brief(exc)}")
    return failed


def _commit_pending_writes(pending: List[_PendingWrite]) -> None:
    """Write every rendered file atomically, rolling back on failure.

    Each replace is atomic (`safe_write_file`), so a crash leaves the old or
    the new file, never a truncated one. A file changed on disk since it was
    read aborts the batch. ``Ctrl-C`` between files rolls back and re-raises.

    Args:
        pending: Rendered writes produced by `_apply_updates`.

    Raises:
        DepKeeperError: A file could not be written; files already written in
            this batch have been restored.
    """
    committed: List[_PendingWrite] = []

    for write in pending:
        try:
            try:
                changed = _read_exact(write.path) != write.original
            except FileOperationError:
                changed = True
            if changed:
                raise DepKeeperError(
                    f"{write.path} was modified while depkeeper was running; "
                    "nothing was written to it. Re-run the command."
                )
            safe_write_file(
                write.path,
                write.updated,
                create_backup=False,
                encoding=write.encoding,
            )
        except BaseException as exc:
            # An interrupt can land after the rename but before this file is
            # recorded as committed; it must be rolled back with the others.
            try:
                if _read_exact(write.path) == write.updated != write.original:
                    committed.append(write)
            except Exception:  # noqa: BLE001 -- best effort; the file is unreadable
                pass
            if committed:
                logger.error(
                    "Write failed for %s; rolling back %d file(s)",
                    write.path,
                    len(committed),
                )
                failed = _rollback_writes(committed)
                if not failed and not isinstance(exc, Exception):
                    print_warning("Interrupted; restored original file(s).")
            if isinstance(exc, FileOperationError):
                raise DepKeeperError(
                    f"Failed to write {write.path}: {_brief(exc)}"
                ) from exc
            raise

        committed.append(write)


def _apply_updates(
    file: Path,
    requirements: List[Requirement],
    updates: List[Tuple[Requirement, Package, str]],
    *,
    allow_hash_removal: bool = False,
    pin: bool = False,
    refresh_hashes: bool = False,
    hash_digests: Optional[Dict[Tuple[str, str], List[str]]] = None,
) -> None:
    """Apply updates to the dependency file(s), one file at a time.

    Updates are grouped by source file (`Requirement.source_file`), so
    requirements from ``-r`` includes are written to the included file, and
    each file is edited by its source adapter, which changes only the version
    text. Every file is rendered in memory first and committed only once all
    of them render, so a rejected requirement never leaves a partially
    updated set; if a later write fails, earlier ones are rolled back. A
    UTF-8 byte order mark is re-emitted for files that carried one.

    Args:
        file: The primary file; fallback for requirements without provenance.
        requirements: All parsed requirements.
        updates: Updates to apply (from `_find_updates`).
        allow_hash_removal: Allow updates that remove ``--hash`` entries.
        pin: Replace every specifier with an exact ``==`` pin.
        refresh_hashes: Regenerate ``--hash`` lines (requirements files only).
        hash_digests: ``(normalized name, version)`` -> sha256 digests.

    Raises:
        DepKeeperError: A file cannot be read or written, or an update cannot
            be rendered.
    """
    file_updates: Dict[str, List[Tuple[Requirement, str]]] = defaultdict(list)
    for update_req, _pkg, target_version in updates:
        target = str(_update_target_path(update_req, file))
        file_updates[target].append((update_req, target_version))

    pending: List[_PendingWrite] = []

    for target_str in sorted(file_updates):
        target_path = Path(target_str)

        try:
            # newline="" preserves CRLF/mixed endings; plain utf-8 (not
            # utf-8-sig) keeps a BOM visible so it can be detected below.
            content = safe_read_file(target_path, encoding="utf-8", newline="")
        except FileOperationError as exc:
            raise DepKeeperError(
                f"Failed to read {target_path}: {_brief(exc)}"
            ) from exc

        # The parser sees BOM-free content, so adapters must too.
        has_bom = content.startswith(BOM_CHARACTER)
        if has_bom:
            content = content[len(BOM_CHARACTER) :]

        adapter = get_adapter(target_path)
        # Only requirements.txt carries --hash lines.
        extra = (
            {"refresh_hashes": True, "hash_digests": hash_digests}
            if refresh_hashes and adapter.name == "requirements.txt"
            else {}
        )
        updated = adapter.apply_updates(
            content,
            file_updates[target_str],
            pin=pin,
            allow_hash_removal=allow_hash_removal,
            path=target_path,
            **extra,
        )

        # utf-8-sig re-emits the BOM on write.
        pending.append(
            _PendingWrite(
                path=target_path,
                original=content,
                updated=updated,
                encoding=BOM_WRITE_ENCODING if has_bom else DEFAULT_WRITE_ENCODING,
            )
        )

    _commit_pending_writes(pending)
