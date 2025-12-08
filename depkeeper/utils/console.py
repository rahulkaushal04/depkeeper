"""
Console output helpers using rich library.

Provides consistent, styled console output with support for:
- Colored messages (success, error, warning, info)
- Tables with proper formatting
- Progress bars and spinners
- NO_COLOR environment variable support
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Union

from rich.console import Console
from rich.table import Table
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
)
from rich.theme import Theme

from depkeeper.utils.logger import get_logger

logger = get_logger("console")


# ============================================================================
# Color Theme
# ============================================================================

DEPKEEPER_THEME = Theme(
    {
        "success": "bold green",
        "error": "bold red",
        "warning": "bold yellow",
        "info": "bold cyan",
        "dim": "dim",
        "highlight": "bold magenta",
    }
)


# ============================================================================
# Console Instance
# ============================================================================


def _should_use_color() -> bool:
    """
    Check if color output should be used.

    Respects NO_COLOR environment variable (https://no-color.org/).

    Returns
    -------
    bool
        True if color should be used, False otherwise.
    """
    # NO_COLOR environment variable disables color
    if os.environ.get("NO_COLOR"):
        return False

    # Check if running in CI or non-interactive environment
    if os.environ.get("CI") or not os.isatty(1):
        return False

    return True


def get_console(force_terminal: Optional[bool] = None) -> Console:
    """
    Get configured console instance.

    Parameters
    ----------
    force_terminal : bool, optional
        Force terminal mode regardless of environment detection.

    Returns
    -------
    Console
        Configured rich Console instance.
    """
    use_color = _should_use_color()

    return Console(
        theme=DEPKEEPER_THEME,
        force_terminal=force_terminal,
        no_color=not use_color,
        highlight=use_color,
    )


# Global console instance
_console = get_console()


# ============================================================================
# Message Printing Functions
# ============================================================================


def print_success(message: str, prefix: str = "✓") -> None:
    """
    Print success message in green.

    Parameters
    ----------
    message : str
        The message to print.
    prefix : str, optional
        Prefix symbol. Default is "✓".

    Examples
    --------
    >>> print_success("Package updated successfully")
    ✓ Package updated successfully
    """
    _console.print(f"{prefix} {message}", style="success")


def print_error(message: str, prefix: str = "✗") -> None:
    """
    Print error message in red.

    Parameters
    ----------
    message : str
        The message to print.
    prefix : str, optional
        Prefix symbol. Default is "✗".

    Examples
    --------
    >>> print_error("Failed to parse requirements file")
    ✗ Failed to parse requirements file
    """
    _console.print(f"{prefix} {message}", style="error")


def print_warning(message: str, prefix: str = "⚠") -> None:
    """
    Print warning message in yellow.

    Parameters
    ----------
    message : str
        The message to print.
    prefix : str, optional
        Prefix symbol. Default is "⚠".

    Examples
    --------
    >>> print_warning("Package not found on PyPI")
    ⚠ Package not found on PyPI
    """
    _console.print(f"{prefix} {message}", style="warning")


def print_info(message: str, prefix: str = "ℹ") -> None:
    """
    Print info message in cyan.

    Parameters
    ----------
    message : str
        The message to print.
    prefix : str, optional
        Prefix symbol. Default is "ℹ".

    Examples
    --------
    >>> print_info("Checking 5 packages...")
    ℹ Checking 5 packages...
    """
    _console.print(f"{prefix} {message}", style="info")


def print_dim(message: str) -> None:
    """
    Print dimmed message (less emphasis).

    Parameters
    ----------
    message : str
        The message to print.

    Examples
    --------
    >>> print_dim("Using cache from /tmp/cache")
    Using cache from /tmp/cache
    """
    _console.print(message, style="dim")


def print_highlight(message: str) -> None:
    """
    Print highlighted message (strong emphasis).

    Parameters
    ----------
    message : str
        The message to print.

    Examples
    --------
    >>> print_highlight("5 packages need updates")
    5 packages need updates
    """
    _console.print(message, style="highlight")


# ============================================================================
# Table Printing
# ============================================================================


def print_table(
    data: List[Dict[str, Any]],
    headers: Optional[List[str]] = None,
    title: Optional[str] = None,
    caption: Optional[str] = None,
) -> None:
    """
    Print data as a formatted table.

    Parameters
    ----------
    data : List[Dict[str, Any]]
        List of dictionaries where keys are column names and values are cell values.
    headers : List[str], optional
        Column headers. If not provided, uses keys from first data row.
    title : str, optional
        Table title displayed above the table.
    caption : str, optional
        Table caption displayed below the table.

    Examples
    --------
    >>> data = [
    ...     {"Package": "requests", "Current": "2.28.0", "Latest": "2.31.0"},
    ...     {"Package": "click", "Current": "8.0.0", "Latest": "8.1.7"},
    ... ]
    >>> print_table(data, title="Outdated Packages")
    """
    if not data:
        logger.debug("No data to display in table")
        return

    # Determine headers
    if headers is None:
        headers = list(data[0].keys())

    # Create table
    table = Table(title=title, caption=caption, show_header=True, header_style="bold")

    # Add columns
    for header in headers:
        table.add_column(header, overflow="fold")

    # Add rows
    for row in data:
        values = [str(row.get(h, "")) for h in headers]
        table.add_row(*values)

    # Print table
    _console.print(table)


# ============================================================================
# Progress Bar
# ============================================================================


def create_progress_bar(transient: bool = True) -> Progress:
    """
    Create a rich progress bar for tracking operations.

    Parameters
    ----------
    transient : bool, optional
        If True, progress bar disappears when complete. Default is True.

    Returns
    -------
    Progress
        Rich Progress instance for tracking tasks.

    Examples
    --------
    >>> with create_progress_bar() as progress:
    ...     task = progress.add_task("Checking packages...", total=10)
    ...     for i in range(10):
    ...         # Do work
    ...         progress.update(task, advance=1)
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=_console,
        transient=transient,
    )


# ============================================================================
# Confirmation Prompts
# ============================================================================


def confirm(message: str, default: bool = False) -> bool:
    """
    Prompt user for yes/no confirmation.

    Parameters
    ----------
    message : str
        The confirmation message to display.
    default : bool, optional
        Default value if user just presses Enter. Default is False.

    Returns
    -------
    bool
        True if user confirmed, False otherwise.

    Examples
    --------
    >>> if confirm("Update requirements.txt?"):
    ...     print("Updating...")
    """
    suffix = " [Y/n]: " if default else " [y/N]: "
    _console.print(f"{message}{suffix}", end="", style="info")

    try:
        response = input().strip().lower()
    except (KeyboardInterrupt, EOFError):
        _console.print()  # New line
        return False

    if not response:
        return default

    return response in ("y", "yes")


# ============================================================================
# Console Direct Access
# ============================================================================


def get_raw_console() -> Console:
    """
    Get the underlying rich Console instance for advanced usage.

    Returns
    -------
    Console
        The global console instance.
    """
    return _console
