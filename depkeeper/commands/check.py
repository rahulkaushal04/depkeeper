"""Check command implementation for depkeeper.

This module provides the 'check' subcommand which scans Python requirements
files to identify available package updates. It queries PyPI asynchronously,
compares current versions with available versions, and displays results in
multiple output formats with rich formatting and color-coded status indicators.

Architecture
------------
The check command follows an async workflow:

1. **Parse**: Read and parse requirements.txt using RequirementsParser
2. **Extract**: Extract current versions from requirement specifiers
3. **Query**: Asynchronously fetch package metadata from PyPI
4. **Analyze**: Compare versions and determine update types
5. **Display**: Format and present results based on output format

The command supports multiple output formats (table, simple, json) and can
filter results to show only outdated packages. It provides detailed information
about Python version compatibility and safe upgrade paths.

Features
--------
- **Async PyPI queries**: Concurrent package checking for speed
- **Progress tracking**: Real-time progress bar during checks
- **Multiple formats**: Table, simple text, or JSON output
- **Version analysis**: Identifies major, minor, and patch updates
- **Python compatibility**: Shows Python version requirements
- **Safe upgrades**: Suggests max compatible version within same major version
- **Error resilience**: Continues checking even if individual packages fail
- **Color coding**: Visual status indicators (✓ OK, ↑ UPDATE, ⚠ INCOMP, ✗ ERROR)

Output Formats
--------------
**Table Format** (default):
    Rich formatted table with columns for Status, Package, Current, Latest,
    Safe Upgrade, Update Type, and Python Requirements. Color-coded for
    easy visual scanning.

**Simple Format**:
    Plain text output suitable for scripting and parsing. Shows package name,
    current version, latest version, and safe upgrade suggestion.

**JSON Format**:
    Machine-readable JSON array of package objects with all metadata. Ideal
    for integration with other tools and automated processing.

Exit Codes
----------
The command returns standard POSIX exit codes:

- **0**: All packages up-to-date, no errors
- **1**: Updates available or error occurred during checking

Examples
--------
Check default requirements.txt:

    $ depkeeper check
    Checking requirements.txt...
    Found 15 package(s)
    [Table with status of all packages]

Check specific file and show only outdated:

    $ depkeeper check requirements-dev.txt --outdated-only
    Checking requirements-dev.txt...
    Found 8 package(s)
    [Only packages with updates shown]

Get JSON output for scripting:

    $ depkeeper check --format json > updates.json
    $ cat updates.json | jq '.[] | select(.has_update == true)'

Notes
-----
The check command is read-only and never modifies requirements files.
Use 'depkeeper update' to apply version changes.

Version extraction supports both exact pins (package==1.0.0) and range
constraints (package>=1.0.0). The --no-extract-ranges flag disables
extracting baseline versions from range constraints.

Safe upgrade versions are calculated as the maximum compatible version
within the same major version as the current version. This helps avoid
breaking changes while getting security and bug fixes.

See Also
--------
depkeeper.commands.update : Apply updates to requirements files
depkeeper.core.checker : Version checking implementation
depkeeper.core.parser : Requirements file parsing
depkeeper.utils.console : Console output utilities
"""

from __future__ import annotations

import sys
import json
import click
import asyncio
from pathlib import Path
from typing import List, Dict
from packaging.version import parse

from depkeeper.models.package import Package
from depkeeper.utils.logger import get_logger
from depkeeper.exceptions import DepKeeperError
from depkeeper.core.checker import VersionChecker
from depkeeper.models.requirement import Requirement
from depkeeper.utils.progress import ProgressTracker
from depkeeper.core.parser import RequirementsParser
from depkeeper.utils.version_utils import get_update_type
from depkeeper.context import pass_context, DepKeeperContext
from depkeeper.utils.console import (
    print_success,
    print_error,
    print_warning,
    print_info,
    print_table,
    colorize_update_type,
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
    """Check requirements file for available updates.

    Scans the specified requirements file, asynchronously queries PyPI for
    each package's metadata, compares current versions with available versions,
    and displays results in the requested format with color-coded status
    indicators.

    This is a read-only operation that never modifies the requirements file.
    Use 'depkeeper update' to apply version changes.

    Parameters
    ----------
    ctx : DepKeeperContext
        CLI context object containing global configuration (verbosity, color
        settings, config path). Automatically injected by Click framework.
    file : Path
        Path to requirements.txt file to check. Defaults to "requirements.txt"
        in the current directory if not specified.
    outdated_only : bool
        If True, only display packages that have updates available. Filters
        out packages that are already at the latest version.
    format : str
        Output format for results. Must be one of:
        - "table": Rich formatted table (default)
        - "simple": Plain text output
        - "json": Machine-readable JSON
    no_extract_ranges : bool
        If True, disables extracting baseline versions from range constraints
        like >=1.0.0. When False (default), treats "package>=1.0.0" as having
        current version 1.0.0 for comparison purposes.

    Returns
    -------
    None
        The function exits the process with appropriate exit code:
        - 0: All packages up-to-date
        - 1: Updates available or error occurred

    Raises
    ------
    DepKeeperError
        If requirements file cannot be parsed or other application errors occur.
    SystemExit
        Always exits with appropriate code (0 or 1).

    Examples
    --------
    Check default requirements.txt with table output:

        $ depkeeper check
        Checking requirements.txt...
        Found 15 package(s)
        ┌────────┬─────────────┬─────────┬────────┬──────────────┬────────┬─────────────────┐
        │ Status │ Package     │ Current │ Latest │ Safe Upgrade │ Update │ Python Requires │
        ├────────┼─────────────┼─────────┼────────┼──────────────┼────────┼─────────────────┤
        │ ✓ OK   │ requests    │ 2.31.0  │ 2.31.0 │      -       │   -    │      >=3.7      │
        └────────┴─────────────┴─────────┴────────┴──────────────┴────────┴─────────────────┘

    Check specific file and show only outdated packages:

        $ depkeeper check requirements-dev.txt --outdated-only
        Checking requirements-dev.txt...
        Found 8 package(s)
        [Only packages with updates displayed]

    Get JSON output for automation:

        $ depkeeper check --format json > updates.json
        $ cat updates.json | jq '.[] | select(.has_update == true) | .name'

    Simple text format for scripting:

        $ depkeeper check --format simple
        [✓] requests           2.31.0     → 2.31.0
        [↑] flask              2.0.0      → 3.0.0 (safe: 2.3.5)

    Disable range extraction:

        $ depkeeper check --no-extract-ranges
        # Treats "package>=1.0.0" as having no current version

    Notes
    -----
    The command performs async I/O for efficiency, checking multiple packages
    concurrently. Progress is displayed in real-time during the check process.

    Version extraction from range constraints (e.g., package>=1.0.0) treats
    the lower bound as the current version. This behavior can be disabled
    with --no-extract-ranges.

    Safe upgrade versions show the maximum compatible version within the same
    major version as the current version, helping avoid breaking changes while
    getting security fixes and improvements.

    Exit codes follow POSIX conventions. Scripts can check $? to determine if
    updates are available:

        $ depkeeper check
        $ if [ $? -eq 1 ]; then echo "Updates available"; fi

    See Also
    --------
    depkeeper.commands.update : Apply updates to requirements
    depkeeper.core.checker.VersionChecker : Version checking implementation
    depkeeper.core.parser.RequirementsParser : Requirements parsing
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
    """Async implementation of the check command workflow.

    This is the core async implementation that orchestrates the entire check
    workflow: parsing requirements, querying PyPI, analyzing versions, and
    displaying results. It runs asynchronously to enable concurrent package
    checks for better performance.

    The function follows a clear pipeline:
    1. Parse requirements file
    2. Check versions with progress tracking
    3. Filter results if outdated_only is True
    4. Display in requested format
    5. Return status

    Parameters
    ----------
    ctx : DepKeeperContext
        CLI context object containing global configuration such as verbosity
        level, color preferences, and config file path. The verbosity level
        affects message output: informational messages and progress bars are
        shown for table format or when verbose > 0.
    file : Path
        Absolute or relative path to the requirements.txt file to check.
        Must exist and be readable (enforced by Click validation).
    outdated_only : bool
        If True, filters the display to show only packages with available
        updates or compatibility issues. If False, shows all packages
        regardless of update status.
    format : str
        Output format specifier. One of "table", "simple", or "json".
        Determines how results are formatted and displayed to the user.
    extract_from_ranges : bool
        If True, extracts baseline versions from range constraints. For
        example, "package>=1.0.0" is treated as having current version
        "1.0.0". If False, range constraints are treated as having no
        current version.

    Returns
    -------
    bool
        True if any packages have updates available or need action (e.g.,
        incompatibility issues), False if all packages are up-to-date or
        no packages were found.

    Raises
    ------
    DepKeeperError
        If requirements file cannot be parsed. The error message includes
        the original parsing exception details for troubleshooting.

    Examples
    --------
    Internal usage (not called directly by users):

        >>> ctx = DepKeeperContext()
        >>> has_updates = await _check_async(
        ...     ctx,
        ...     Path("requirements.txt"),
        ...     outdated_only=False,
        ...     format="table",
        ...     extract_from_ranges=True
        ... )
        >>> print("Updates available" if has_updates else "Up to date")

    Notes
    -----
    This function is the async counterpart to the synchronous check()
    command. It's wrapped by check() which uses asyncio.run() to execute
    the async workflow.

    The function uses async context managers for proper resource cleanup,
    particularly for the VersionChecker which manages HTTP connections.

    Progress tracking and informational messages are displayed based on
    output format and verbosity:
    - **table format**: Always shows progress and messages
    - **json/simple format**: Clean output by default, but shows progress
      and messages when verbose mode is enabled (ctx.verbose > 0)

    Empty requirements files result in a warning but are not treated as
    errors. The function returns False to indicate no updates available.

    See Also
    --------
    check : The synchronous wrapper command
    _check_with_progress : Async package checking with progress tracking
    depkeeper.core.checker.VersionChecker : PyPI version checking
    """
    # Show messages and progress for table format OR when verbose mode is enabled
    show_messages = format == "table" or ctx.verbose > 0

    if show_messages:
        print_info(f"Checking {file}...")

    # Parse requirements file
    parser = RequirementsParser()
    try:
        requirements = parser.parse_file(file)
    except Exception as e:
        raise DepKeeperError(f"Failed to parse {file}: {e}") from e

    # Early return if no requirements found
    if not requirements:
        if show_messages:
            print_warning("No packages found in requirements file")
        return False

    if show_messages:
        print_info(f"Found {len(requirements)} package(s)")

    # Check versions with progress tracking
    async with VersionChecker(extract_from_ranges=extract_from_ranges) as checker:
        packages = await _check_with_progress(ctx, checker, requirements, format)

    # Filter outdated if requested
    if outdated_only:
        packages = [p for p in packages if p.has_update()]

    # Display results
    if not packages:
        if show_messages:
            msg = (
                "All packages are up to date!"
                if outdated_only
                else "No packages to display"
            )
            (print_success if outdated_only else print_warning)(msg)
        return False

    # Count packages needing action (updates or incompatibilities)
    packages_needing_action = sum(
        1 for p in packages if p.has_update() or p.needs_action()
    )

    # Display based on format
    if format == "table":
        _display_table(packages)
    elif format == "simple":
        _display_simple(packages)
    else:  # json
        _display_json(packages)

    if show_messages:
        if packages_needing_action > 0:
            print_warning(
                f"\n{packages_needing_action} package(s) have updates available"
            )
        else:
            print_success("\nAll packages are up to date!")

    return packages_needing_action > 0


async def _check_with_progress(
    ctx: DepKeeperContext,
    checker: VersionChecker,
    requirements: List[Requirement],
    format: str = "table",
) -> List[Package]:
    """Check package versions with real-time progress tracking and error resilience.

    This function queries PyPI for each package's metadata, extracts version
    information, and builds Package objects with all relevant data. It displays
    a progress bar during execution and continues checking even if individual
    packages fail, ensuring maximum information is gathered.

    The function processes packages sequentially but the VersionChecker may
    perform async I/O operations, allowing for efficient network usage. Each
    package check is independent, and errors are isolated to individual
    packages without stopping the entire check process.

    Parameters
    ----------
    ctx : DepKeeperContext
        CLI context object containing verbosity level. Used to determine
        whether to show progress bars for json/simple output formats.
    checker : VersionChecker
        Configured VersionChecker instance with active async HTTP session.
        Should be created within an async context manager to ensure proper
        session lifecycle management.
    requirements : List[Requirement]
        List of parsed Requirement objects from the requirements file. Each
        contains package name, version specifiers, extras, markers, etc.
    format : str, optional
        Output format ("table", "simple", or "json"). Affects progress bar
        visibility: table format always shows progress, json/simple formats
        only show progress when verbose mode is enabled. Default is "table".

    Returns
    -------
    List[Package]
        List of Package objects in the same order as input requirements.
        Packages that failed to check are represented with error Package
        objects (has_error=True) rather than being omitted, ensuring the
        output list matches the input list length and order.

    Examples
    --------
    Internal usage within async context:

        >>> ctx = DepKeeperContext()
        >>> async with VersionChecker() as checker:
        ...     requirements = parser.parse_file("requirements.txt")
        ...     packages = await _check_with_progress(ctx, checker, requirements)
        ...     for pkg in packages:
        ...         if pkg.has_error:
        ...             print(f"Failed to check {pkg.name}")
        ...         elif pkg.has_update():
        ...             print(f"{pkg.name}: {pkg.current_version} -> {pkg.latest_version}")

    Notes
    -----
    The function uses a ProgressTracker with transient=False to ensure the
    progress bar remains visible after completion, providing a persistent
    record of the operation in the terminal.

    Progress bar visibility is controlled by output format and verbosity:
    - **table format**: Always displays progress bar
    - **json/simple formats**: Progress bar disabled by default for clean
      output, but enabled when verbose mode is active (ctx.verbose > 0)

    Progress updates occur before each package check, showing the current
    package being processed. The final progress message shows the total
    count of packages checked.

    Error handling is resilient: if a package fails to check (network error,
    package not found, malformed data), an error Package object is created
    and the check continues with the next package. This ensures partial
    results are always available even if some packages fail.

    All check results are logged at DEBUG level for troubleshooting,
    including both successful checks and errors. This debug log includes
    the package index, name, and version information or error message.

    See Also
    --------
    depkeeper.core.checker.VersionChecker : Handles PyPI queries and version extraction
    depkeeper.utils.progress.ProgressTracker : Progress bar implementation
    depkeeper.models.package.Package : Package data model
    """
    # Disable progress for JSON/simple formats unless verbose mode is enabled
    disable_progress = format in ["json", "simple"] and ctx.verbose == 0
    tracker = ProgressTracker(transient=False, disable=disable_progress)
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

            package = await checker.get_package_info(
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
# Display Functions
# ============================================================================


def _display_table(packages: List[Package]) -> None:
    """Display packages as a Rich-formatted table with color-coded status indicators.

    Creates and displays a comprehensive table showing package status, versions,
    update information, and Python compatibility. The table uses Rich markup
    for colors and styling, providing visual cues for different package states.

    The table includes these columns:
    - **Status**: Visual indicator (✓ OK, ↑ UPDATE, ⚠ INCOMP, ✗ ERROR)
    - **Package**: Package name (bold cyan)
    - **Current**: Currently installed/specified version
    - **Latest**: Latest version available on PyPI
    - **Safe Upgrade**: Maximum compatible version within same major version
    - **Update**: Type of update (major/minor/patch) with color coding
    - **Python Requires**: Python version requirements for different versions

    Parameters
    ----------
    packages : List[Package]
        List of Package objects to display. Each package should have version
        information populated from PyPI queries. Empty list is handled gracefully.

    Returns
    -------
    None
        Outputs directly to console via Rich print_table utility.

    Examples
    --------
    Display packages after checking:

        >>> packages = await checker.check_packages(requirements)
        >>> _display_table(packages)
        ┌────────┬──────────┬─────────┬────────┬──────────────┬────────┬─────────────────┐
        │ Status │ Package  │ Current │ Latest │ Safe Upgrade │ Update │ Python Requires │
        ├────────┼──────────┼─────────┼────────┼──────────────┼────────┼─────────────────┤
        │ ✓ OK   │ requests │ 2.31.0  │ 2.31.0 │      -       │   -    │      >=3.7      │
        │ ↑ UPD  │ flask    │ 2.0.0   │ 3.0.0  │    2.3.5     │ major  │ >=3.8, 3.8+     │
        └────────┴──────────┴─────────┴────────┴──────────────┴────────┴─────────────────┘

    Notes
    -----
    The table uses Rich markup syntax for styling:
    - [green]: Success/up-to-date status
    - [yellow]: Updates available
    - [red]: Errors or incompatibilities
    - [bright_cyan]: Safe upgrade versions
    - [dim]: Not applicable/no value

    Column widths and styles are configured via column_styles dictionary,
    which is passed to print_table utility for consistent formatting.

    Each package is converted to a table row via _create_table_row(), which
    handles the complex logic of determining status, colors, and values.

    The table title "Dependency Status" provides context for the displayed
    information and is centered above the table.

    See Also
    --------
    _create_table_row : Creates individual table row from Package
    depkeeper.utils.console.print_table : Rich table rendering utility
    depkeeper.models.package.Package : Package data model
    """
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
    """Create a table row dictionary for a package with Rich markup styling.

    Analyzes a Package object and generates a formatted table row dictionary
    with appropriate status indicators, version information, and color coding.
    This function implements the complex logic for determining package status,
    update types, and safe upgrade recommendations.

    The function handles four main package states:
    1. **ERROR**: Package not found or failed to fetch from PyPI
    2. **INCOMP** (Incompatible): Current version exceeds max compatible version
    3. **UPDATE**: Updates available to a newer version
    4. **OK**: Package is up-to-date

    Safe upgrade version logic:
    - Shows the maximum compatible version within the same major version
    - Only displayed if different from current version
    - Helps avoid breaking changes while getting security fixes
    - Falls back to latest version if no same-major upgrade exists

    Parameters
    ----------
    pkg : Package
        Package object containing version information, Python requirements,
        and metadata from PyPI. Must have at minimum a name; other fields
        may be None for error cases.

    Returns
    -------
    Dict[str, str]
        Dictionary with these keys (all values include Rich markup):
        - "Status": Status indicator with icon and color
        - "Package": Package name (plain text)
        - "Current": Current version or "-" if unknown
        - "Latest": Latest version from PyPI or "error" if failed
        - "Safe Upgrade": Max safe version or "-" if not applicable
        - "Update": Update type (major/minor/patch/downgrade) or "-"
        - "Python Requires": Python version requirements, formatted

    Examples
    --------
    Create row for up-to-date package:

        >>> pkg = Package(name="requests", current_version="2.31.0", latest_version="2.31.0")
        >>> row = _create_table_row(pkg)
        >>> print(row["Status"])
        '[green]✓ OK[/green]'

    Create row for package with update:

        >>> pkg = Package(name="flask", current_version="2.0.0", latest_version="3.0.0")
        >>> row = _create_table_row(pkg)
        >>> print(row["Status"])
        '[yellow]↑ UPDATE[/yellow]'
        >>> print(row["Update"])
        '[red]major[/red]'

    Error case:

        >>> pkg = Package(name="unknown-pkg", current_version="1.0.0", latest_version=None)
        >>> row = _create_table_row(pkg)
        >>> print(row["Status"])
        '[red]✗ ERROR[/red]'

    Notes
    -----
    The function uses Rich markup syntax for styling:
    - Status indicators: [green]✓[/green], [yellow]↑[/yellow], [red]⚠[/red], [red]✗[/red]
    - Update types: [green]patch[/green], [yellow]minor[/yellow], [red]major[/red]
    - Safe upgrades: [bright_cyan]version[/bright_cyan]
    - Not applicable: [dim]-[/dim]

    Version comparison uses packaging.version.parse() for robust semantic
    version handling. Comparison failures (e.g., invalid versions) fall back
    to string comparison.

    Python requirements are formatted by pkg.format_python_requirements(),
    which shows requirements for current, latest, and safe upgrade versions
    in a compact format.

    The "needs downgrade" case occurs when the current version is newer than
    the maximum Python-compatible version, indicating a compatibility issue
    that requires downgrading to a compatible version.

    See Also
    --------
    depkeeper.utils.version_utils.get_update_type : Determines update type
    depkeeper.utils.console.colorize_update_type : Applies color to update types
    depkeeper.models.package.Package : Package data model
    """
    # Get Python requirements for all versions
    python_reqs = pkg.format_python_requirements()

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
    # Safe upgrade version now shows max version within same major version
    target_version = None
    safe_upgrade_display = "[dim]-[/dim]"
    needs_downgrade = False

    if pkg.has_safe_upgrade_version():
        # There's a max safe upgrade version within same major version
        target_version = pkg.safe_upgrade_version

        # Only show safe upgrade version if it's different from current
        # (i.e., there's actually an upgrade available)
        if pkg.current_version and pkg.safe_upgrade_version != pkg.current_version:
            safe_upgrade_display = (
                f"[bright_cyan]{pkg.safe_upgrade_version}[/bright_cyan]"
            )
        else:
            # Current == safe upgrade, so no upgrade available - show as "-"
            safe_upgrade_display = "[dim]-[/dim]"

        # Check if current version is newer than max compatible (needs downgrade)
        if pkg.current_version:
            try:
                needs_downgrade = parse(pkg.current_version) > parse(target_version)
            except Exception:
                pass
    else:
        # No safe upgrade version found within same major, use latest
        target_version = pkg.latest_version
        # Only show latest as safe upgrade if it's different from current
        if pkg.current_version and pkg.latest_version != pkg.current_version:
            safe_upgrade_display = f"[green]{pkg.latest_version}[/green]"
        else:
            safe_upgrade_display = "[dim]-[/dim]"

    # Check if update is available based on target version
    has_update = False
    if target_version and pkg.current_version:
        try:
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
            "Safe Upgrade": safe_upgrade_display,
            "Update": "[red]downgrade[/red]",
            "Python Requires": python_reqs,
        }

    if has_update:
        # Update available to target version
        update_type = get_update_type(pkg.current_version, target_version)
        colored_type = colorize_update_type(update_type)

        return {
            "Status": "[yellow]↑ UPDATE[/yellow]",
            "Package": pkg.name,
            "Current": pkg.current_version or "[dim]-[/dim]",
            "Latest": pkg.latest_version,
            "Safe Upgrade": safe_upgrade_display,
            "Update": colored_type,
            "Python Requires": python_reqs,
        }

    # Up to date - current >= target version
    return {
        "Status": "[green]✓ OK[/green]",
        "Package": pkg.name,
        "Current": pkg.current_version or "[dim]-[/dim]",
        "Latest": pkg.latest_version or "[dim]-[/dim]",
        "Safe Upgrade": safe_upgrade_display,
        "Update": "[dim]-[/dim]",
        "Python Requires": python_reqs,
    }


def _display_simple(packages: List[Package]) -> None:
    """Display packages in simple text format suitable for parsing and scripting.

    Outputs package information in a compact, line-based format that's easy to
    parse with standard Unix tools like grep, awk, and sed. Each package is
    shown on one or two lines with status indicator, name, and versions.

    Format:
        [STATUS] package_name    current_version → latest_version (safe: safe_version)
               Python: current: requirement, latest: requirement, safe: requirement

    The second line (Python requirements) is only shown if any version has
    Python requirements specified.

    Parameters
    ----------
    packages : List[Package]
        List of Package objects to display. Each package's simple status is
        generated via Package.get_simple_status() method.

    Returns
    -------
    None
        Outputs directly to console via Rich console print.

    Examples
    --------
    Display packages in simple format:

        >>> _display_simple(packages)
        [✓] requests           2.31.0     → 2.31.0
               Python: latest: >=3.7
        [↑] flask              2.0.0      → 3.0.0 (safe: 2.3.5)
               Python: current: >=3.6, latest: >=3.8, safe: >=3.6
        [✗] unknown-pkg        1.0.0      → error

    Parse output with grep:

        $ depkeeper check --format simple | grep '[↑]'
        [↑] flask              2.0.0      → 3.0.0 (safe: 2.3.5)

    Notes
    -----
    This format is designed to be human-readable while remaining parseable
    by scripts. Field widths are fixed for alignment (package name: 20 chars,
    versions: 10 chars each).

    Status indicators match the table format:
    - [✓]: Up-to-date
    - [↑]: Update available
    - [⚠]: Incompatibility issue
    - [✗]: Error

    Safe upgrade version is only shown if it differs from the latest version,
    indicating a safer upgrade path that avoids major version changes.

    Python requirements are shown on a separate indented line to maintain
    clean alignment while providing important compatibility information.

    The function uses Rich console for output, which respects color settings
    and NO_COLOR environment variable.

    See Also
    --------
    depkeeper.models.package.Package.get_simple_status : Generates simple status
    _display_table : Rich table format
    _display_json : JSON format
    """
    from depkeeper.utils.console import get_raw_console

    console = get_raw_console()

    for pkg in packages:
        status, installed, latest, safe_upgrade = pkg.get_simple_status()

        # Show status with versions
        if safe_upgrade and safe_upgrade != latest:
            console.print(
                f"[{status}] {pkg.name:20} {installed:10} → {latest:10} (safe: {safe_upgrade})"
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
            if pkg.has_safe_upgrade_version():
                safe_req = pkg.get_version_python_req("safe_upgrade")
                if safe_req:
                    req_parts.append(f"safe: {safe_req}")
            if req_parts:
                console.print(f"       Python: {', '.join(req_parts)}")


def _display_json(packages: List[Package]) -> None:
    """Display packages as machine-readable JSON for automation and scripting.

    Serializes package information to JSON format and outputs to stdout.
    The output is a JSON array where each element represents a package with
    all available metadata including versions, Python requirements, and status.

    This format is ideal for:
    - Integration with other tools and pipelines
    - Automated processing and analysis
    - Storing results for later comparison
    - Generating reports and dashboards

    Parameters
    ----------
    packages : List[Package]
        List of Package objects to serialize. Each package is converted to
        a dictionary via Package.to_json() method.

    Returns
    -------
    None
        Outputs JSON to stdout. No return value.

    Examples
    --------
    Display packages as JSON:

        >>> _display_json(packages)
        [
          {
            "name": "requests",
            "current_version": "2.31.0",
            "latest_version": "2.31.0",
            "safe_upgrade_version": null,
            "has_update": false,
            "update_type": null,
            "requires_python": ">=3.7",
            "has_error": false
          },
          {
            "name": "flask",
            "current_version": "2.0.0",
            "latest_version": "3.0.0",
            "safe_upgrade_version": "2.3.5",
            "has_update": true,
            "update_type": "major",
            "requires_python": ">=3.8",
            "has_error": false
          }
        ]

    Use with jq for filtering:

        $ depkeeper check --format json | jq '.[] | select(.has_update == true)'
        $ depkeeper check --format json | jq '.[] | select(.update_type == "major")'
        $ depkeeper check --format json | jq 'map(select(.has_update)) | length'

    Process with Python:

        >>> import json
        >>> import subprocess
        >>> result = subprocess.run(
        ...     ["depkeeper", "check", "--format", "json"],
        ...     capture_output=True,
        ...     text=True
        ... )
        >>> packages = json.loads(result.stdout)
        >>> outdated = [p for p in packages if p["has_update"]]
        >>> print(f"{len(outdated)} packages need updates")

    Notes
    -----
    The JSON output uses 2-space indentation for readability while remaining
    compact enough for efficient processing.

    All package metadata is included in the JSON output, making it a complete
    representation of the check results. The schema is defined by the
    Package.to_json() method.

    String values may be null if information is not available (e.g.,
    safe_upgrade_version when no safe upgrade exists).

    The output is valid JSON that can be parsed by any JSON-compliant tool
    or library. No additional processing is needed.

    See Also
    --------
    depkeeper.models.package.Package.to_json : Package JSON serialization
    _display_table : Rich table format
    _display_simple : Simple text format
    """
    data = [pkg.to_json() for pkg in packages]
    print(json.dumps(data, indent=2))
