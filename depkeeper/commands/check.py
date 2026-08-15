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
from typing import Any, Dict, List, Optional

from depkeeper.models import Package
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
)

logger = get_logger("commands.check")

#: Output format whose payload is meant to be read by a human at a terminal.
#: Every other format writes a machine-consumable payload to stdout, so all
#: human-facing status output must be diverted to stderr.
HUMAN_READABLE_FORMAT = "table"


def _status_stream_is_stderr(format: str) -> bool:
    """Return True when status output must not share stdout with the payload.

    ``--format json`` and ``--format simple`` write a machine-consumable
    document to stdout. Warnings, success messages and the resolution summary
    are diagnostics, so they go to stderr to keep stdout parseable.

    Args:
        format: The requested output format.

    Returns:
        ``True`` for machine-readable formats, ``False`` for ``table``.
    """
    return format.lower() != HUMAN_READABLE_FORMAT


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
    "--strict-version-matching",
    is_flag=True,
    default=None,
    help="Only use exact version pins, don't infer from constraints.",
)
@click.option(
    "--check-conflicts/--no-check-conflicts",
    default=None,
    help="Check for dependency conflicts between packages.",
)
@pass_context
def check(
    ctx: DepKeeperContext,
    file: Path,
    outdated_only: bool,
    format: str,
    strict_version_matching: Optional[bool],
    check_conflicts: Optional[bool],
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
    Output streams:
      table            report on stdout, status messages on stdout
      simple / json    payload on stdout only; every status message,
                       warning, error and resolution summary goes to
                       stderr, so `depkeeper -v check -f json | jq` works
    \f

    Args:
        ctx: Depkeeper context with configuration and verbosity settings.
        file: Path to the requirements file (default: ``requirements.txt``).
        outdated_only: Only display packages with updates or conflicts.
        format: Output format (``table``, ``simple``, or ``json``).
        strict_version_matching: Don't infer current versions from
            constraints like ``>=2.0``; only use exact pins (``==``).
            Falls back to the ``strict_version_matching`` config option.
        check_conflicts: Enable cross-package conflict resolution. Falls
            back to the ``check_conflicts`` config option.

    Exits:
        0 if the command completed successfully (whether or not updates
        are available), 1 if an error occurred.
    """
    cfg = ctx.config
    if strict_version_matching is None:
        strict_version_matching = cfg.strict_version_matching if cfg else False
    if check_conflicts is None:
        check_conflicts = cfg.check_conflicts if cfg else True

    try:
        asyncio.run(
            _check_async(
                ctx,
                file,
                outdated_only,
                format,
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
        logger.exception("Error in check command")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Async orchestration
# ---------------------------------------------------------------------------


async def _check_async(
    ctx: DepKeeperContext,
    file: Path,
    outdated_only: bool,
    format: str,
    infer_version_from_constraints: bool,
    check_conflicts: bool,
) -> bool:
    """Async implementation of the check command.

    Core logic:

    1. Parse the requirements file.
    2. Create a shared :class:`PyPIDataStore` (guarantees each package is
       fetched once).
    3. Run :class:`VersionChecker` to compute initial recommendations.
    4. Optionally run :class:`DependencyAnalyzer` to resolve conflicts.
    5. Filter packages if ``--outdated-only`` is set.
    6. Display results in the requested format.

    Args:
        ctx: Depkeeper context.
        file: Path to the requirements file.
        outdated_only: Filter to show only packages needing updates.
        format: Output format (``table``, ``simple``, ``json``).
        infer_version_from_constraints: Infer current version from
            constraints (e.g., ``>=2.0`` → current is ``2.0``).
        check_conflicts: Enable dependency conflict resolution.

    Returns:
        ``True`` if any package has updates or unresolved conflicts,
        ``False`` if everything is up-to-date.  The return value is
        used only for informational logging; it does not affect the
        exit code (which is always 0 on success).

    Raises:
        DepKeeperError: Requirements file cannot be parsed or is malformed.
    """
    # Only show progress/status for human-readable formats
    show_progress: bool = format == "table" or ctx.verbose > 0

    # For json/simple, stdout belongs to the payload; status goes to stderr.
    status_to_stderr: bool = _status_stream_is_stderr(format)
    emits_json: bool = format.lower() == "json"

    logger.info("Checking %s...", file)

    # ── Step 1: Parse requirements ────────────────────────────────────
    parser = RequirementsParser()
    try:
        requirements = parser.parse_file(file)
    except ParseError as e:
        raise DepKeeperError(f"Failed to parse {file}: {e}") from e

    if not requirements:
        if show_progress:
            print_warning(
                "No packages found in requirements file", stderr=status_to_stderr
            )
        if emits_json:
            _display_json([])
        return False

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
        resolution_result = None
        if check_conflicts:
            logger.info("Cross-validating recommended versions...")
            analyzer = DependencyAnalyzer(data_store=data_store)
            resolution_result = await analyzer.resolve_and_annotate_conflicts(packages)

            if show_progress and resolution_result:
                _display_resolution_summary(
                    resolution_result, stderr=status_to_stderr
                )

    # ── Step 4: Filter and display ────────────────────────────────────
    if outdated_only:
        packages = [p for p in packages if p.has_update() or p.has_conflicts()]

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
        if emits_json:
            _display_json([])
        return False

    packages_needing_action = sum(1 for p in packages if p.has_update())

    if format == "table":
        _display_table(packages)
    elif format == "simple":
        _display_simple(packages)
    else:  # json
        _display_json(packages)

    # ── Final summary ──────────────────────────────────────────────────
    if show_progress:
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
            print_success(
                "\nAll packages are up to date!", stderr=status_to_stderr
            )

    return packages_needing_action > 0


def _display_resolution_summary(
    result: ResolutionResult, *, stderr: bool = False
) -> None:
    """Print a human-readable summary of the conflict resolution process.

    Displays:

    - Total packages analyzed
    - Number of packages with conflicts
    - Number of version changes made during resolution
    - Convergence status (did resolution finish or hit iteration limit?)
    - Details of each version change (original → resolved)

    Args:
        result: The :class:`ResolutionResult` from the dependency analyzer.
        stderr: Render to stderr instead of stdout. Required for the
            ``json``/``simple`` formats, whose payload owns stdout.

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
    console = get_raw_console(stderr=stderr)
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
# Display renderers
# ---------------------------------------------------------------------------


def _display_table(packages: List[Package]) -> None:
    """Render packages as a Rich table on stdout.

    Status indicators:

    - ``✓ OK`` (green): up to date.
    - ``⬆ OUTDATED`` (yellow): a safe upgrade is available.
    - ``⚠ CONFLICT`` (red): conflicts block every candidate version.
    - ``⚠ INCOMP`` (red): the declared version is unusable and the
      recommendation is lower than it.
    - ``✗ ERROR`` (red): PyPI metadata could not be retrieved.

    Args:
        packages: List of :class:`Package` objects to display.
    """
    data = [_create_table_row(pkg) for pkg in packages]

    column_styles: Dict[str, Dict[str, Any]] = {
        "Status": {"justify": "center", "no_wrap": True, "width": 10},
        "Package": {"style": "bold cyan", "no_wrap": True},
        "Current": {"justify": "center", "style": "dim"},
        "Latest": {"justify": "center", "style": "bold green"},
        "Recommended": {"justify": "center", "style": "bright_cyan"},
        "Update Type": {"justify": "center"},
        "Conflicts": {"justify": "left", "no_wrap": False},
        "Python Support": {"justify": "left", "no_wrap": False},
    }

    print_table(
        data,
        title="Dependency Status",
        column_styles=column_styles,
        show_row_lines=True,
    )


def _create_table_row(pkg: Package) -> Dict[str, str]:
    """Build a Rich-formatted table row for a single package.

    Status determination is delegated to :meth:`Package.get_display_data`, so
    this function only maps a known state to markup.

    Args:
        pkg: The :class:`Package` to render.

    Returns:
        A dictionary mapping column names to Rich markup strings.
    """
    python_support = pkg.render_python_compatibility()

    # A missing latest_version means the PyPI lookup failed (unavailable
    # stub), which is a different state from "no update available".
    if not pkg.latest_version:
        return {
            "Status": "[red]✗ ERROR[/red]",
            "Package": pkg.name,
            "Current": pkg.current_version or "[dim]-[/dim]",
            "Latest": "[red]error[/red]",
            "Recommended": "[dim]-[/dim]",
            "Update Type": "[dim]-[/dim]",
            "Conflicts": "[dim]-[/dim]",
            "Python Support": "[dim]-[/dim]",
        }

    display = pkg.get_display_data()

    # Repeating the current version in the Recommended column is noise, so it
    # is shown only when it actually differs.
    recommended_display = "[dim]-[/dim]"
    if pkg.recommended_version:
        if pkg.current_version and pkg.recommended_version != pkg.current_version:
            recommended_display = (
                f"[bright_cyan]{pkg.recommended_version}[/bright_cyan]"
            )

    conflicts_display = "[dim]-[/dim]"
    if display["has_conflicts"]:
        conflict_lines = [
            f"[red]⚠[/red] {c.source_package} needs {c.required_spec}"
            for c in pkg.conflicts
        ]
        conflicts_display = "\n".join(conflict_lines)

    # A required downgrade outranks a conflict: it means the declared version
    # itself is unusable, which the user must see first.
    if display["requires_downgrade"]:
        return {
            "Status": "[red]⚠ INCOMP[/red]",
            "Package": pkg.name,
            "Current": pkg.current_version or "[dim]-[/dim]",
            "Latest": pkg.latest_version,
            "Recommended": recommended_display,
            "Update Type": "[red]downgrade[/red]",
            "Conflicts": conflicts_display,
            "Python Support": python_support,
        }

    # ── Conflict case ──────────────────────────────────────────────────
    if display["has_conflicts"]:
        if not pkg.has_update():
            # Conflicts blocked every candidate version.
            return {
                "Status": "[red]⚠ CONFLICT[/red]",
                "Package": pkg.name,
                "Current": pkg.current_version or "[dim]-[/dim]",
                "Latest": pkg.latest_version,
                "Recommended": recommended_display,
                "Update Type": "[red]blocked[/red]",
                "Conflicts": conflicts_display,
                "Python Support": python_support,
            }
        else:
            # Conflicts exist, but resolution still found a safe target.
            colored_type = colorize_update_type(display["update_type"] or "update")
            return {
                "Status": "[yellow]⬆ OUTDATED[/yellow]",
                "Package": pkg.name,
                "Current": pkg.current_version or "[dim]-[/dim]",
                "Latest": pkg.latest_version,
                "Recommended": recommended_display,
                "Update Type": colored_type,
                "Conflicts": conflicts_display,
                "Python Support": python_support,
            }

    # ── Update available case ──────────────────────────────────────────
    if display["update_available"]:
        colored_type = colorize_update_type(display["update_type"] or "update")
        return {
            "Status": "[yellow]⬆ OUTDATED[/yellow]",
            "Package": pkg.name,
            "Current": pkg.current_version or "[dim]-[/dim]",
            "Latest": pkg.latest_version,
            "Recommended": recommended_display,
            "Update Type": colored_type,
            "Conflicts": conflicts_display,
            "Python Support": python_support,
        }

    # ── Up-to-date case ────────────────────────────────────────────────
    return {
        "Status": "[green]✓ OK[/green]",
        "Package": pkg.name,
        "Current": pkg.current_version or "[dim]-[/dim]",
        "Latest": pkg.latest_version or "[dim]-[/dim]",
        "Recommended": recommended_display,
        "Update Type": "[dim]-[/dim]",
        "Conflicts": conflicts_display,
        "Python Support": python_support,
    }


def _display_simple(packages: List[Package]) -> None:
    """Render packages as one status line each, with indented detail lines.

    Rich markup is disabled for every line: a status label such as
    ``[OUTDATED]`` is otherwise parsed as a style tag and swallowed.

    Args:
        packages: List of :class:`Package` objects to display.

    Example::

        [OUTDATED]   requests             2.28.0     → 2.32.0
               Python: installed: >=3.7, latest: >=3.8
        [OUTDATED]   flask                2.0.0      → 3.0.1     (recommended: 2.3.3)
               Python: installed: >=3.7, latest: >=3.8, recommended: >=3.7
    """
    console = get_raw_console()

    for pkg in packages:
        status, installed, latest, recommended = pkg.get_status_summary()
        status_label = f"[{status.upper()}]"

        if recommended and recommended != latest:
            # A recommendation below latest means conflict resolution or a
            # major boundary capped the upgrade.
            console.print(
                f"{status_label:12} {pkg.name:20} {installed:10} → {latest:10} "
                f"(recommended: {recommended})",
                markup=False,
            )
        else:
            console.print(
                f"{status_label:12} {pkg.name:20} {installed:10} → {latest:10}",
                markup=False,
            )

        # Indented conflict details
        if pkg.has_conflicts():
            for conflict in pkg.conflicts:
                console.print(
                    f"       ⚠ Conflict: {conflict.to_display_string()}",
                    style="red",
                    markup=False,
                )

        # Indented Python version requirements
        current_req = pkg.get_version_python_req("current")
        latest_req = pkg.get_version_python_req("latest")
        if current_req or latest_req:
            req_parts = []
            if current_req:
                req_parts.append(f"installed: {current_req}")
            if latest_req:
                req_parts.append(f"latest: {latest_req}")
            if pkg.has_update():
                recommended_req = pkg.get_version_python_req("recommended")
                if recommended_req:
                    req_parts.append(f"recommended: {recommended_req}")
            if req_parts:
                console.print(f"       Python: {', '.join(req_parts)}", markup=False)


def _display_json(packages: List[Package]) -> None:
    """Render packages as a JSON array on stdout.

    Always emits a document (``[]`` when there is nothing to report) so
    consumers such as ``jq`` never receive empty input. Uses the builtin
    :func:`print` rather than Rich so no markup or wrapping is applied.

    Args:
        packages: List of :class:`Package` objects to serialize.

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
    data = [pkg.to_json() for pkg in packages]
    print(json.dumps(data, indent=2))
