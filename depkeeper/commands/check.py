"""Check command implementation for depkeeper.

Analyzes requirements files to report available updates, dependency
conflicts, and Python version compatibility. This command is read-only; it
never modifies the requirements file.
"""

from __future__ import annotations

import sys
import json
import click
import asyncio
from pathlib import Path
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from packaging.utils import canonicalize_name

from depkeeper.models import Package
from depkeeper.exceptions import DepKeeperError
from depkeeper.context import pass_context, DepKeeperContext
from depkeeper.core import (
    PyPIDataStore,
    VersionChecker,
    DependencyAnalyzer,
)
from depkeeper.core.sources import default_target, parse_targets
from depkeeper.config import DepKeeperConfig
from depkeeper.utils.version_utils import gating_type
from depkeeper.commands import _report
from depkeeper.commands._report import Row
from depkeeper.utils import (
    HTTPClient,
    get_logger,
    print_success,
    print_error,
    print_warning,
    print_table,
    get_raw_console,
    colorize_update_type,
    safe_text,
)

logger = get_logger("commands.check")

#: Output format whose payload is meant to be read by a human at a terminal.
#: Every other format writes a machine-consumable payload to stdout, so all
#: human-facing status output must be diverted to stderr.
HUMAN_READABLE_FORMAT = "table"

#: Exit codes: 0 ok, 1 error, 2 usage (Click), 3 updates found per
#: ``--fail-on``, 4 at least one PyPI lookup failed (takes precedence over 3).
EXIT_UPDATES_FOUND = 3
EXIT_LOOKUP_FAILED = 4

#: ``--fail-on`` threshold -> update types that trip it.
#: Compared via `gating_type`, so calver ``year``/``month`` count as ``minor``.
_FAIL_ON_TYPES = {"minor": ("minor", "major"), "major": ("major",)}

FORMATS = ["table", "simple", "json", "json-v2", "markdown"]


def _status_stream_is_stderr(format: str) -> bool:
    """Return True when status output must not share stdout with the payload.

    Every format except ``table`` writes a machine-consumable document to
    stdout, so diagnostics go to stderr to keep it parseable.
    """
    return format.lower() != HUMAN_READABLE_FORMAT


@click.command()
@click.argument(
    "file",
    type=click.Path(exists=True, dir_okay=True, path_type=Path),
    required=False,
    default=None,
)
@click.option(
    "--outdated-only",
    is_flag=True,
    help="Show only packages with available updates.",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(FORMATS, case_sensitive=False),
    default="table",
    help="Output format. json is a bare array (stable); json-v2 is the "
    "versioned envelope; markdown is a PR-body / CI-summary report.",
)
@click.option(
    "--strict-version-matching/--no-strict-version-matching",
    default=None,
    help="Only use exact version pins, don't infer from constraints.",
)
@click.option(
    "--fail-on",
    type=click.Choice(["none", "updates", "minor", "major"], case_sensitive=False),
    default=None,
    help="Exit 3 when updates of this level are found "
    "(updates = any, minor = minor or major, major = major only). "
    "Default: none (config: fail_on).",
)
@click.option(
    "--ignore",
    "ignore",
    multiple=True,
    metavar="PKG",
    help="Skip this package (repeatable; adds to config 'ignore').",
)
@click.option(
    "--check-conflicts/--no-check-conflicts",
    default=None,
    help="Check for dependency conflicts between packages.",
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
    help="Don't recommend versions released more recently than this "
    "(e.g. 7d, 12h, 2w). Default: config min_age.",
)
@click.option(
    "--allow-major",
    "allow_major",
    multiple=True,
    metavar="PKG",
    help="Allow this package to cross its current major (repeatable; '*' = all). "
    "Your declared upper bounds still apply.",
)
@pass_context
def check(
    ctx: DepKeeperContext,
    file: Optional[Path],
    outdated_only: bool,
    format: str,
    strict_version_matching: Optional[bool],
    fail_on: Optional[str],
    ignore: Tuple[str, ...],
    check_conflicts: Optional[bool],
    python_version: Optional[str],
    min_age: Optional[timedelta],
    allow_major: Tuple[str, ...],
) -> None:
    """Check requirements file for available updates.

    Parses the specified requirements file, queries PyPI for the latest
    versions, and displays a report of packages that can be updated.
    Optionally performs dependency conflict analysis to ensure recommended
    updates are compatible with each other.

    \b
    When --check-conflicts is enabled (the default), the command:
      1. Fetches initial recommendations for every package.
      2. Cross-validates all recommendations to detect conflicts.
      3. Iteratively adjusts versions until a conflict-free set is found.
      4. Displays the final resolved versions along with any unresolved
         conflicts.

    Options not explicitly provided on the command line fall back to values
    from the configuration file (depkeeper.toml or pyproject.toml), then
    to built-in defaults.

    \b
    Exit codes:
      0  success (updates may exist unless --fail-on says otherwise)
      1  error (unreadable/invalid file, unexpected failure)
      2  usage error
      3  updates found at or above the --fail-on level
      4  at least one package could not be looked up on PyPI
         (a lookup failure is never reported as "up to date")

    \b
    Output streams:
      table            report on stdout, status messages on stdout
      simple / json /  payload on stdout only;
    json-v2 / markdown every status message,
                       warning, error and resolution summary goes to
                       stderr, so `depkeeper -v check -f json | jq` works
    \f

    Args:
        ctx: Depkeeper context with configuration and verbosity settings.
        file: A dependency file or a directory to scan (default:
            ``requirements.txt``, else discovery in the current directory).
        outdated_only: Only display packages with updates or conflicts.
        format: Output format (``table``, ``simple``, or ``json``).
        strict_version_matching: Don't infer current versions from
            constraints like ``>=2.0``; only use exact pins (``==``).
            Falls back to the ``strict_version_matching`` config option.
        fail_on: Gate level for exit code 3. Falls back to ``fail_on``.
        ignore: Package names to skip, merged with the ``ignore`` config.
        check_conflicts: Enable cross-package conflict resolution. Falls
            back to the ``check_conflicts`` config option.
        python_version: Target Python (``X.Y``); beats config and the file's
            own ``requires-python``.
        min_age: Release cooldown; beats config ``min_age``.
        allow_major: Package names (or ``*``) allowed to cross their major.

    Exits:
        See "Exit codes" above.
    """
    file = default_target(file)
    if not file.exists():
        raise click.UsageError(f"File '{file}' does not exist.")
    cfg = ctx.config
    if strict_version_matching is None:
        strict_version_matching = cfg.strict_version_matching if cfg else False
    if check_conflicts is None:
        check_conflicts = cfg.check_conflicts if cfg else True
    if fail_on is None:
        fail_on = cfg.fail_on if cfg else "none"
    ignored = list(cfg.ignore if cfg else []) + list(ignore)
    python = _report.resolve_target_python(python_version, cfg, file)
    logger.info(
        "Target Python: %s (from %s)", python[0] or "running interpreter", python[1]
    )

    try:
        code = asyncio.run(
            _check_async(
                ctx,
                file,
                outdated_only,
                format,
                infer_version_from_constraints=not strict_version_matching,
                check_conflicts=check_conflicts,
                fail_on=fail_on.lower(),
                ignore=ignored,
                python=python,
                min_age=min_age,
                allow_major=_report.allow_major_names(allow_major),
            )
        )
        sys.exit(code)

    except DepKeeperError as e:
        print_error(e.message)
        sys.exit(1)
    except (BrokenPipeError, click.Abort):
        raise  # handled once, in cli.main()
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        logger.exception("Error in check command")
        sys.exit(1)


async def _check_async(
    ctx: DepKeeperContext,
    file: Path,
    outdated_only: bool,
    format: str,
    infer_version_from_constraints: bool,
    check_conflicts: bool,
    fail_on: str = "none",
    ignore: Sequence[str] = (),
    python: Tuple[Optional[str], str] = (None, "running interpreter"),
    min_age: Optional[timedelta] = None,
    allow_major: Sequence[str] = (),
) -> int:
    """Run the check pipeline and return the process exit code.

    Parses the target, fetches PyPI data through one shared `PyPIDataStore`,
    computes recommendations with `VersionChecker`, optionally resolves
    conflicts with `DependencyAnalyzer`, then renders the requested format.

    Args:
        ctx: Depkeeper context.
        file: A dependency file or a directory to scan.
        outdated_only: Show only packages needing attention.
        format: Output format.
        infer_version_from_constraints: Infer the current version from
            constraints (``>=2.0`` -> ``2.0``).
        check_conflicts: Enable dependency conflict resolution.
        fail_on: Gate level for `EXIT_UPDATES_FOUND`.
        ignore: Package names to skip.
        python: ``(target Python or None, who decided)``.
        min_age: Release cooldown.
        allow_major: Normalised ``--allow-major`` names.

    Returns:
        The process exit code: ``0``, `EXIT_UPDATES_FOUND` or
        `EXIT_LOOKUP_FAILED`.

    Raises:
        DepKeeperError: The target cannot be parsed or is malformed.
    """
    format = format.lower()
    show_progress: bool = format == "table" or ctx.verbose > 0

    # Machine formats own stdout; status output goes to stderr.
    status_to_stderr: bool = _status_stream_is_stderr(format)

    logger.info("Checking %s...", file)

    requirements = parse_targets(file)

    if ignore:
        skip = {canonicalize_name(n) for n in ignore}
        requirements = [
            r for r in requirements if canonicalize_name(r.name) not in skip
        ]

    if not requirements:
        if show_progress:
            print_warning(
                "No packages found in requirements file", stderr=status_to_stderr
            )
        _emit_empty(format, python)
        return 0

    logger.info("Found %d package(s)", len(requirements))

    async with HTTPClient() as http:
        data_store = PyPIDataStore(http, target_python=python[0])

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
        )
        packages = await checker.check_packages(requirements)
        links = _report.collect_links(data_store, packages)

        resolution_result = None
        if check_conflicts:
            logger.info("Cross-validating recommended versions...")
            analyzer = DependencyAnalyzer(
                data_store=data_store, target_python=python[0], checker=checker
            )
            resolution_result = await analyzer.resolve_and_annotate_conflicts(packages)
            _report.warn_conflict_check_incomplete(resolution_result)

            # The summary is noise unless something changed or conflicted.
            if (
                show_progress
                and resolution_result
                and (
                    ctx.verbose > 0
                    or resolution_result.get_changed_packages()
                    or resolution_result.packages_with_conflicts
                )
            ):
                _report.display_resolution_summary(
                    resolution_result, stderr=status_to_stderr
                )

    # Computed before filtering so --outdated-only cannot hide a failure.
    # Direct references (URL/VCS/editable) are never on PyPI: not a failure.
    rows = _report.make_rows(requirements, packages, links)
    direct = {id(p) for r, p in zip(requirements, packages) if r.url or r.editable}
    # Conda-sourced names may be absent from PyPI: warn, don't fail (exit 4).
    approx = {id(p) for r, p in zip(requirements, packages) if r.approximate}
    failed = [
        p.name
        for p in packages
        if not p.latest_version and id(p) not in direct and id(p) not in approx
    ]
    unmatched = [p.name for p in packages if not p.latest_version and id(p) in approx]
    updates_found = _gate_tripped(packages, fail_on)
    if outdated_only:
        packages = [
            p
            for p in packages
            if p.has_update()
            or p.has_conflicts()
            or p.conflict_held
            or (not p.latest_version and id(p) not in direct)
        ]
        shown = {id(p) for p in packages}
        rows = [r for r in rows if id(r.pkg) in shown]
    exit_code = (
        EXIT_LOOKUP_FAILED if failed else EXIT_UPDATES_FOUND if updates_found else 0
    )

    if not packages:
        if show_progress:
            msg = (
                "All packages are up to date!"
                if outdated_only
                else "No packages to display"
            )
            (print_success if outdated_only else print_warning)(
                msg, stderr=status_to_stderr
            )
        _emit_empty(format, python)
        return exit_code

    packages_needing_action = sum(1 for p in packages if p.has_update())

    if format == "table":
        _display_table(packages, rows)
    elif format == "simple":
        _display_simple(packages, rows)
    elif format == "json-v2":
        print(
            json.dumps(
                _report.build_envelope(
                    rows,
                    python,
                    conflict_check_complete=(
                        resolution_result.conflict_check_complete
                        if resolution_result
                        else True
                    ),
                ),
                indent=2,
            )
        )
    elif format == "markdown":
        print(
            _report.render_markdown(rows, title="Dependency report", python=python),
            end="",
        )
    else:  # json
        _display_json(packages, rows)

    # Always shown (on stderr for machine formats): a typo'd name silently
    # applies nothing otherwise.
    unknown_note = _report.unknown_allow_major_note(allow_major, requirements)
    if unknown_note:
        print_warning(unknown_note, stderr=status_to_stderr)

    if show_progress:
        for note in (
            _report.policy_note(packages),
            _report.cooldown_note(packages),
            _report.major_note(packages),
        ):
            if note:
                print_warning(note, stderr=status_to_stderr)
        if packages_needing_action > 0:
            print_warning(
                f"\n{packages_needing_action} package(s) have updates available",
                stderr=status_to_stderr,
            )
            if resolution_result and resolution_result.packages_with_conflicts > 0:
                print_warning(
                    f"{resolution_result.packages_with_conflicts} package(s) have "
                    "unresolved conflicts — see 'Conflicts' column",
                    stderr=status_to_stderr,
                )
        else:
            remaining = _report.attention_note(packages, failed)
            if remaining:
                print_warning(f"\n{remaining}", stderr=status_to_stderr)
            else:
                print_success("\nAll packages are up to date!", stderr=status_to_stderr)

    # Failures are reported regardless of format or verbosity: a CI log must
    # never look clean when PyPI could not be queried.
    if failed:
        print_error(
            f"{len(failed)} package(s) could not be checked "
            f"(not found on PyPI or network error): {', '.join(failed)}",
            stderr=True,
        )
    for p in packages:
        if not p.latest_version and p.metadata.get("lookup_error"):
            print_error(p.metadata["lookup_error"], stderr=True)
    if unmatched:
        print_warning(
            f"{len(unmatched)} conda package(s) not found on PyPI (may be "
            f"conda-only): {', '.join(unmatched)}",
            stderr=True,
        )

    return exit_code


def _gate_tripped(packages: Sequence[Package], fail_on: str) -> bool:
    """Return True when any package meets the ``--fail-on`` threshold."""
    if fail_on == "none":
        return False
    if fail_on == "updates":
        return any(
            p.has_update() or p.has_conflicts() or p.requires_downgrade
            for p in packages
            if p.latest_version
        )
    types = _FAIL_ON_TYPES[fail_on]
    return any(p.has_update() and gating_type(p.update_type) in types for p in packages)


def _emit_empty(format: str, python: Tuple[Optional[str], str]) -> None:
    """Print the empty document for machine formats (never empty stdout)."""
    if format == "json":
        _display_json([])
    elif format == "json-v2":
        print(json.dumps(_report.build_envelope([], python), indent=2))
    elif format == "markdown":
        print(
            _report.render_markdown([], title="Dependency report", python=python),
            end="",
        )


def _display_table(
    packages: List[Package], rows: Optional[Sequence[Row]] = None
) -> None:
    """Render packages as a Rich table on stdout.

    Status indicators:

    - ``[OK]`` (green): up to date.
    - ``[OUTDATED]`` (yellow): a safe upgrade is available.
    - ``[CONFLICT]`` (red): conflicts block every candidate version.
    - ``[INCOMP]`` (red): the declared version is unusable and the
      recommendation is lower than it.
    - ``[ERROR]`` (red): PyPI metadata could not be retrieved.
    - ``[HELD]`` / ``[IGNORED]`` (cyan): policy froze the package.

    The Recommended cell shows the release age (``12d old``) and any
    cooldown-withheld version; a "Source" column appears when the packages
    come from more than one file. Labels are bracketed text rather than
    symbols so they render in any font and match ``--format simple``.

    Args:
        packages: Packages to display.
        rows: Matching `Row` objects, used for the Source column.
    """
    data = [_create_table_row(pkg) for pkg in packages]
    by_id = {id(r.pkg): r for r in rows or []}
    for pkg, row in zip(packages, data):
        # Age rides in the Recommended cell: a new column would overflow 80 cols.
        if pkg.has_update() and pkg.recommended_released:
            row["Recommended"] += f"\n[dim]{_report.age_short(pkg)} old[/dim]"
    if rows and _report.multi_file(rows):
        for pkg, row in zip(packages, data):
            r = by_id.get(id(pkg))
            if r and r.req:
                fmt = (
                    f"\n[dim]({safe_text(r.req.source_format)})[/dim]"
                    if r.req.source_format
                    else ""
                )
                row["Source"] = f"{safe_text(_report.source_cell(r))}{fmt}"
            else:
                row["Source"] = "[dim]-[/dim]"

    column_styles: Dict[str, Dict[str, Any]] = {
        "Status": {"justify": "center", "no_wrap": True, "width": 10},
        "Package": {"style": "bold cyan", "no_wrap": True, "overflow": "ellipsis"},
        "Current": {"justify": "center", "style": "dim", "min_width": 7},
        "Latest": {"justify": "center", "style": "bold green", "min_width": 6},
        "Recommended": {
            "justify": "center",
            "style": "bright_cyan",
            "min_width": 11,
        },
        "Update Type": {"justify": "center", "no_wrap": True},
        "Conflicts": {"justify": "left", "no_wrap": False},
        "Python Support": {"justify": "left", "no_wrap": False},
        "Source": {"justify": "left", "no_wrap": False},
    }

    print_table(
        data,
        title="Dependency Status",
        column_styles=column_styles,
        show_row_lines=True,
    )


def _python_cell(pkg: Package) -> str:
    """One short value: the Python requirement of the version being targeted."""
    req = pkg.get_version_python_req(
        "recommended" if pkg.has_update() else "current"
    ) or pkg.get_version_python_req("latest")
    if not req:
        return "[dim]-[/dim]"
    return safe_text(_report.python_bounds(req))


def _create_table_row(pkg: Package) -> Dict[str, str]:
    """Table row, with the policy marker applied for held/ignored packages."""
    row = _base_table_row(pkg)
    marker = "HELD" if pkg.held else "IGNORED" if pkg.ignored else None
    if marker and pkg.latest_version:
        row["Status"] = f"[cyan][{marker}][/cyan]"
        row["Update Type"] = f"[cyan]{marker.lower()} by policy[/cyan]"
    if pkg.cooldown_skipped:
        row["Recommended"] += (
            f"\n[dim]{safe_text(pkg.cooldown_skipped)} held (age)[/dim]"
        )
    return row


def _base_table_row(pkg: Package) -> Dict[str, str]:
    """Map *pkg* (state from `Package.get_display_data`) to Rich-markup cells."""
    python_support = _python_cell(pkg)
    dash = "[dim]-[/dim]"

    if pkg.direct:
        return {
            "Status": "[dim][DIRECT][/dim]",
            "Package": safe_text(pkg.name),
            "Current": dash,
            "Latest": dash,
            "Recommended": "[dim]direct reference, not checked[/dim]",
            "Update Type": dash,
            "Conflicts": dash,
            "Python Support": dash,
        }

    if pkg.not_applicable:
        return {
            "Status": "[dim][N/A][/dim]",
            "Package": safe_text(pkg.name),
            "Current": safe_text(pkg.current_version) if pkg.current_version else dash,
            "Latest": safe_text(pkg.latest_version) if pkg.latest_version else dash,
            "Recommended": (
                f"[dim]not applicable for target Python "
                f"{safe_text(pkg.not_applicable)}[/dim]"
            ),
            "Update Type": dash,
            "Conflicts": dash,
            "Python Support": dash,
        }

    # A missing latest_version means the PyPI lookup failed, which is a
    # different state from "no update available".
    if not pkg.latest_version:
        return {
            "Status": "[red][ERROR][/red]",
            "Package": safe_text(pkg.name),
            "Current": safe_text(pkg.current_version) if pkg.current_version else dash,
            "Latest": "[red]error[/red]",
            "Recommended": dash,
            "Update Type": dash,
            "Conflicts": dash,
            "Python Support": dash,
        }

    display = pkg.get_display_data()

    # The current version repeated in the Recommended column is noise.
    recommended_display = dash
    if pkg.recommended_version:
        if pkg.current_version and pkg.recommended_version != pkg.current_version:
            recommended_display = (
                f"[bright_cyan]{safe_text(pkg.recommended_version)}[/bright_cyan]"
            )

    conflicts_display = dash
    if display["has_conflicts"]:
        conflicts_display = "\n".join(
            f"[red]⚠[/red] {safe_text(c.source_package)} needs {safe_text(c.required_spec)}"
            for c in pkg.conflicts
        )

    def build(status: str, update_type: str) -> Dict[str, str]:
        return {
            "Status": status,
            "Package": safe_text(pkg.name),
            "Current": safe_text(pkg.current_version) if pkg.current_version else dash,
            "Latest": safe_text(pkg.latest_version) if pkg.latest_version else dash,
            "Recommended": recommended_display,
            "Update Type": update_type,
            "Conflicts": conflicts_display,
            "Python Support": python_support,
        }

    # A required downgrade outranks a conflict: the declared version itself is
    # unusable, which the user must see first.
    if display["requires_downgrade"]:
        return build("[red][INCOMP][/red]", "[red]downgrade[/red]")
    if display["has_conflicts"] and not pkg.has_update():
        # Conflicts blocked every candidate version.
        return build("[red][CONFLICT][/red]", "[red]blocked[/red]")
    if display["has_conflicts"] or display["update_available"]:
        colored_type = colorize_update_type(display["update_type"] or "update")
        return build("[yellow][OUTDATED][/yellow]", colored_type)
    return build("[green][OK][/green]", dash)


def _display_simple(
    packages: List[Package], rows: Optional[Sequence[Row]] = None
) -> None:
    """Render packages as one status line each, with indented detail lines.

    Rich markup is disabled for every line: a status label such as
    ``[OUTDATED]`` is otherwise parsed as a style tag and swallowed.

    Args:
        packages: Packages to display.
        rows: Matching `Row` objects, used for the Source line.

    Example::

        [OUTDATED]   requests             2.28.0     → 2.32.0
               Python: installed: >=3.7, latest: >=3.8
        [OUTDATED]   flask                2.0.0      → 3.0.1     (recommended: 2.3.3)
               Python: installed: >=3.7, latest: >=3.8, recommended: >=3.7
    """
    console = get_raw_console()
    by_id = {id(r.pkg): r for r in rows or []}
    show_source = bool(rows) and _report.multi_file(rows or [])

    for pkg in packages:
        status, installed, latest, recommended = pkg.get_status_summary()
        if pkg.latest_version and (pkg.held or pkg.ignored):
            status = "held" if pkg.held else "ignored"
        status_label = f"[{status.upper()}]"

        if pkg.direct:
            console.print(
                f"{status_label:12} {pkg.name:20} direct reference, not checked",
                markup=False,
                soft_wrap=True,
            )
            continue

        if pkg.not_applicable:
            console.print(
                f"{status_label:12} {pkg.name:20} {installed:10} "
                f"not applicable for target Python {pkg.not_applicable}",
                markup=False,
                soft_wrap=True,
            )
            continue

        if recommended and recommended != latest:
            # A recommendation below latest means conflict resolution or a
            # major boundary capped the upgrade.
            console.print(
                f"{status_label:12} {pkg.name:20} {installed:10} → {latest:10} "
                f"(recommended: {recommended})",
                markup=False,
                soft_wrap=True,
            )
        else:
            console.print(
                f"{status_label:12} {pkg.name:20} {installed:10} → {latest:10}",
                markup=False,
                soft_wrap=True,
            )

        age = _report.age_text(pkg) if pkg.has_update() else None
        if age:
            console.print(f"       {age}", markup=False, soft_wrap=True)
        if pkg.cooldown_skipped:
            console.print(
                f"       cooldown: {pkg.cooldown_skipped} withheld (min_age)",
                markup=False,
                soft_wrap=True,
            )
        row = by_id.get(id(pkg))
        if show_source and row and row.req:
            fmt = f" ({row.req.source_format})" if row.req.source_format else ""
            console.print(
                f"       Source: {_report.source_cell(row)}{fmt}",
                markup=False,
                soft_wrap=True,
            )

        if pkg.has_conflicts():
            for conflict in pkg.conflicts:
                console.print(
                    f"       ⚠ Conflict: {conflict.to_display_string()}",
                    style="red",
                    markup=False,
                    soft_wrap=True,
                )

        current_req = _report.clean_specifier(pkg.get_version_python_req("current"))
        latest_req = _report.clean_specifier(pkg.get_version_python_req("latest"))
        if current_req or latest_req:
            req_parts = []
            if current_req:
                req_parts.append(f"installed: {current_req}")
            if latest_req:
                req_parts.append(f"latest: {latest_req}")
            if pkg.has_update():
                recommended_req = _report.clean_specifier(
                    pkg.get_version_python_req("recommended")
                )
                if recommended_req:
                    req_parts.append(f"recommended: {recommended_req}")
            if req_parts:
                console.print(
                    f"       Python: {', '.join(req_parts)}",
                    markup=False,
                    soft_wrap=True,
                )


def _display_json(
    packages: List[Package], rows: Optional[Sequence[Row]] = None
) -> None:
    """Render packages as a JSON array on stdout.

    Always emits a document (``[]`` when there is nothing to report) so
    consumers such as ``jq`` never receive empty input. Uses the builtin
    `print` rather than Rich so no markup or wrapping is applied.

    Args:
        packages: Packages to serialize.
        rows: Matching `Row` objects, used for links and ignored flags.

    Example::

        [
          {
            "name": "requests",
            "status": "outdated",
            "versions": {
              "current": "2.28.0",
              "latest": "2.32.0",
              "recommended": "2.32.0"
            },
            "update_type": "minor",
            "python_requirements": {
              "current": ">=3.7",
              "latest": ">=3.8",
              "recommended": ">=3.8"
            }
          }
        ]
    """
    by_id = {id(r.pkg): r for r in rows or []}
    data = [
        _report.package_json(by_id[id(p)]) if id(p) in by_id else p.to_json()
        for p in packages
    ]
    print(json.dumps(data, indent=2))
