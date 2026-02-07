"""Check command implementation for depkeeper.

Analyzes a ``requirements.txt`` file to identify packages with available
updates, dependency conflicts, and Python version compatibility issues.

The command orchestrates three core components:

1. **RequirementsParser** — parses the requirements file into structured
   :class:`Requirement` objects.
2. **VersionChecker** — queries PyPI concurrently to fetch latest versions
   and compute recommendations.
3. **DependencyAnalyzer** — cross-validates all recommended versions and
   resolves conflicts through iterative downgrading/constraining.

All components share a single :class:`PyPIDataStore` instance to guarantee
that each package's metadata is fetched at most once per invocation.

Typical usage::

    # Show all packages with available updates
    $ depkeeper check requirements.txt --outdated-only

    # Machine-readable JSON output
    $ depkeeper check --format json > report.json

    # Enable conflict resolution (adjusts recommendations to be mutually compatible)
    $ depkeeper check --check-conflicts

    # Strict mode: only use pinned versions, don't infer from constraints
    $ depkeeper check --strict-version-matching
"""

from __future__ import annotations

import sys
import json
import click
import asyncio
from pathlib import Path
from typing import Any, Dict, List

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
    help="Only use exact version pins, don't infer from constraints.",
)
@click.option(
    "--check-conflicts",
    is_flag=True,
    default=True,
    help="Check for dependency conflicts between packages.",
)
@pass_context
def check(
    ctx: DepKeeperContext,
    file: Path,
    outdated_only: bool,
    format: str,
    strict_version_matching: bool,
    check_conflicts: bool,
) -> None:
    """Check requirements file for available updates.

    Parses the specified requirements file, queries PyPI for the latest
    versions, and displays a report of packages that can be updated.
    Optionally performs dependency conflict analysis to ensure recommended
    updates are compatible with each other.

    When ``--check-conflicts`` is enabled, the command:

    1. Fetches initial recommendations for every package.
    2. Cross-validates all recommendations to detect conflicts (package A's
       dependency on B is incompatible with B's recommended version).
    3. Iteratively adjusts versions (downgrading sources or constraining
       targets) until a conflict-free set is found or the iteration limit
       is reached.
    4. Displays the final resolved versions along with any unresolved
       conflicts.

    Args:
        ctx: Depkeeper context with configuration and verbosity settings.
        file: Path to the requirements file (default: ``requirements.txt``).
        outdated_only: Only display packages with updates or conflicts.
        format: Output format (``table``, ``simple``, or ``json``).
        strict_version_matching: Don't infer current versions from
            constraints like ``>=2.0``; only use exact pins (``==``).
        check_conflicts: Enable cross-package conflict resolution.

    Exits:
        0 if all packages are up-to-date, 1 if updates are available or an
        error occurred.

    Example::

        >>> # CLI invocation
        $ depkeeper check requirements.txt --check-conflicts --format table
    """
    try:
        has_updates = asyncio.run(
            _check_async(
                ctx,
                file,
                outdated_only,
                format,
                infer_version_from_constraints=not strict_version_matching,
                check_conflicts=check_conflicts,
            )
        )
        sys.exit(1 if has_updates else 0)

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
        ``False`` if everything is up-to-date.

    Raises:
        DepKeeperError: Requirements file cannot be parsed or is malformed.
    """
    # Only show progress/status for human-readable formats
    show_progress: bool = format == "table" or ctx.verbose > 0

    logger.info("Checking %s...", file)

    # ── Step 1: Parse requirements ────────────────────────────────────
    parser = RequirementsParser()
    try:
        requirements = parser.parse_file(file)
    except ParseError as e:
        raise DepKeeperError(f"Failed to parse {file}: {e}") from e

    if not requirements:
        if show_progress:
            print_warning("No packages found in requirements file")
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
                # Display resolution summary (convergence status, version changes)
                _display_resolution_summary(resolution_result)

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
            (print_success if outdated_only else print_warning)(msg)
        return False

    packages_needing_action = sum(1 for p in packages if p.has_update())

    # Dispatch to the appropriate renderer
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
                f"\n{packages_needing_action} package(s) have updates available"
            )
            if resolution_result and resolution_result.packages_with_conflicts > 0:
                print_warning(
                    f"{resolution_result.packages_with_conflicts} package(s) have "
                    "unresolved conflicts — see 'Conflicts' column"
                )
        else:
            print_success("\nAll packages are up to date!")

    return packages_needing_action > 0


def _display_resolution_summary(result: ResolutionResult) -> None:
    """Print a human-readable summary of the conflict resolution process.

    Displays:

    - Total packages analyzed
    - Number of packages with conflicts
    - Number of version changes made during resolution
    - Convergence status (did resolution finish or hit iteration limit?)
    - Details of each version change (original → resolved)

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

    console.print("")  # blank line separator


# ---------------------------------------------------------------------------
# Display renderers
# ---------------------------------------------------------------------------


def _display_table(packages: List[Package]) -> None:
    """Render packages as a Rich-formatted table.

    Creates a visually appealing table with color-coded status indicators,
    version columns, update types, conflict details, and Python
    compatibility information.

    Status indicators:

    - ``✓ OK`` (green): Package is up-to-date.
    - ``⬆ OUTDATED`` (yellow): Updates are available.
    - ``⚠ CONFLICT`` (red): Dependency conflicts exist; no safe upgrade.
    - ``⚠ INCOMP`` (red): Recommended version is lower than current
      (would require a downgrade).
    - ``✗ ERROR`` (red): PyPI query failed or package not found.

    Args:
        packages: List of :class:`Package` objects to display.

    Example::

        ┏━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
        ┃ Status     ┃ Package     ┃ Current   ┃ Latest    ┃ Update Type  ┃
        ┡━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
        │ ✓ OK       │ requests    │ 2.31.0    │ 2.31.0    │ -            │
        │ ⬆ OUTDATED │ flask       │ 2.0.0     │ 3.0.0     │ major        │
        └────────────┴─────────────┴───────────┴───────────┴──────────────┘
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
    """Build a Rich-formatted table row dictionary for a single package.

    Determines the appropriate status indicator, version displays, and
    conflict information based on the package's state.  All logic for
    status determination is delegated to :meth:`Package.get_display_data`.

    Args:
        pkg: The :class:`Package` to render.

    Returns:
        A dictionary mapping column names to Rich markup strings.

    Example::

        {
            "Status": "[yellow]⬆ OUTDATED[/yellow]",
            "Package": "flask",
            "Current": "2.0.0",
            "Latest": "3.0.0",
            "Recommended": "[bright_cyan]2.3.3[/bright_cyan]",
            "Update Type": "[bold yellow]minor[/bold yellow]",
            "Conflicts": "[dim]-[/dim]",
            "Python Support": ">=3.8",
        }
    """
    python_support = pkg.render_python_compatibility()

    # ── Error case (PyPI query failed) ────────────────────────────────
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

    # ── Fetch pre-computed display metadata ───────────────────────────
    display = pkg.get_display_data()

    # Recommended version: only show if it differs from current
    recommended_display = "[dim]-[/dim]"
    if pkg.recommended_version:
        if pkg.current_version and pkg.recommended_version != pkg.current_version:
            recommended_display = (
                f"[bright_cyan]{pkg.recommended_version}[/bright_cyan]"
            )

    # Conflicts: format as multi-line list of requirements
    conflicts_display = "[dim]-[/dim]"
    if display["has_conflicts"]:
        conflict_lines = [
            f"[red]⚠[/red] {c.source_package} needs {c.required_spec}"
            for c in pkg.conflicts
        ]
        conflicts_display = "\n".join(conflict_lines)

    # ── Downgrade/incompatible case ───────────────────────────────────
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
            # True conflict: no safe upgrade exists
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
            # Conflicts exist but a safe upgrade is available
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
    """Render packages in simple, line-based text format.

    Outputs one line per package showing status, name, current version,
    and latest version.  Conflict and Python compatibility details are
    shown on indented lines below each package.

    Suitable for piping to other tools or for minimal terminal output.

    Args:
        packages: List of :class:`Package` objects to display.

    Example::

        [OUTDATED] flask              2.0.0      → 3.0.0
               ⚠ Conflict: werkzeug requires >=2.0,<3
               Python: installed: >=3.7, latest: >=3.8
        [OK] requests             2.31.0     → 2.31.0
    """
    console = get_raw_console()

    for pkg in packages:
        # Main line: [STATUS] package_name    current → latest
        status, installed, latest, recommended = pkg.get_status_summary()

        if recommended and recommended != latest:
            # Show recommended version when it differs (conflict resolution)
            console.print(
                f"[{status}] {pkg.name:20} {installed:10} → {latest:10} "
                f"(recommended: {recommended})"
            )
        else:
            console.print(f"[{status}] {pkg.name:20} {installed:10} → {latest:10}")

        # Indented conflict details
        if pkg.has_conflicts():
            for conflict in pkg.conflicts:
                console.print(
                    f"       [red]⚠ Conflict:[/red] {conflict.to_display_string()}"
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
                console.print(f"       Python: {', '.join(req_parts)}")


def _display_json(packages: List[Package]) -> None:
    """Render packages as formatted JSON for machine consumption.

    Outputs a JSON array where each element contains complete package
    information: versions, conflicts, metadata, and Python compatibility.
    Suitable for piping to ``jq`` or parsing in scripts.

    Args:
        packages: List of :class:`Package` objects to serialize.

    Example::

        [
          {
            "name": "flask",
            "current_version": "2.0.0",
            "latest_version": "3.0.0",
            "recommended_version": "2.3.3",
            "conflicts": [...],
            "metadata": {...}
          },
          ...
        ]
    """
    data = [pkg.to_json() for pkg in packages]
    print(json.dumps(data, indent=2))
