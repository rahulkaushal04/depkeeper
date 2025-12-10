"""Console output utilities for depkeeper.

This module provides a centralized console interface using the Rich library
for styled terminal output. It supports colored messages, formatted tables,
progress bars, and respects the NO_COLOR environment variable standard.

All console output is lazy-initialized and respects user preferences for
color output, making it suitable for both interactive CLI usage and CI/CD
environments.

Examples
--------
Basic message printing:

    >>> from depkeeper.utils.console import print_success, print_error
    >>> print_success("Package updated successfully")
    ✓ Package updated successfully
    >>> print_error("Failed to connect to PyPI")
    ✗ Failed to connect to PyPI

Display data in tables:

    >>> from depkeeper.utils.console import print_table
    >>> data = [
    ...     {"Package": "requests", "Current": "2.28.0", "Latest": "2.31.0"},
    ...     {"Package": "click", "Current": "8.0.0", "Latest": "8.1.7"},
    ... ]
    >>> print_table(data, title="Outdated Packages")

User confirmation prompts:

    >>> from depkeeper.utils.console import confirm
    >>> if confirm("Update all packages?", default=True):
    ...     print("Updating...")

Progress tracking:

    >>> from depkeeper.utils.progress import ProgressTracker
    >>> with ProgressTracker() as tracker:
    ...     task = tracker.add_task("Processing...", total=100)
    ...     for i in range(100):
    ...         # Do work
    ...         tracker.update(task, advance=1)

Notes
-----
The console respects the NO_COLOR environment variable (https://no-color.org/)
and automatically disables color output in CI environments or when output is
not directed to a terminal.

To force reconfiguration (e.g., after changing NO_COLOR at runtime):

    >>> from depkeeper.utils.console import reconfigure_console
    >>> import os
    >>> os.environ["NO_COLOR"] = "1"
    >>> reconfigure_console()  # Apply changes
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Any, Optional, List, Dict, Literal, Callable

from rich.theme import Theme
from rich.table import Table
from rich.console import Console


from depkeeper.utils.logger import get_logger

logger = get_logger("console")


# Color Theme
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


def _should_use_color() -> bool:
    """Check if color output should be used.

    This function respects multiple environment indicators to determine
    whether colored output is appropriate. It checks for the NO_COLOR
    environment variable, CI environment detection, and whether stdout
    is connected to a terminal.

    Returns
    -------
    bool
        True if color output should be enabled, False otherwise.

    Notes
    -----
    Color output is disabled when:

    - NO_COLOR environment variable is set (any value)
    - CI environment variable is set (running in CI/CD)
    - stdout is not a TTY (output redirected to file/pipe)
    - stdout.isatty() raises an exception (broken terminal)

    This follows the NO_COLOR standard: https://no-color.org/
    """
    # NO_COLOR environment variable disables color
    if os.environ.get("NO_COLOR"):
        return False

    # Check if running in CI or non-interactive environment
    if os.environ.get("CI"):
        return False

    # Check if stdout is a terminal
    try:
        if not sys.stdout.isatty():
            return False
    except (AttributeError, OSError):
        return False

    return True


# Global console instance (lazy-initialized)
_console: Optional[Console] = None
_console_lock = threading.Lock()


def _get_console() -> Console:
    """Get or create the global console instance.

    This function implements lazy initialization for the Rich Console
    instance. The console is created on first access and reused for
    all subsequent calls, ensuring consistent output styling and
    performance.

    Returns
    -------
    Console
        The global Rich Console instance configured with depkeeper's
        theme and color settings.

    Notes
    -----
    The console is initialized with:

    - Custom depkeeper theme (success/error/warning/info colors)
    - Color output based on environment detection
    - Syntax highlighting enabled when colors are available

    Call `reconfigure_console()` to force re-initialization if
    environment settings change at runtime.

    See Also
    --------
    reconfigure_console : Force console re-initialization
    """
    global _console
    if _console is None:
        with _console_lock:  # Thread-safe initialization
            # Double-check after acquiring lock
            if _console is None:
                use_color = _should_use_color()
                _console = Console(
                    theme=DEPKEEPER_THEME,
                    no_color=not use_color,
                    highlight=use_color,
                )
    return _console


def reconfigure_console() -> None:
    """Reconfigure the console instance.

    Forces recreation of the console instance on next use. This is useful
    when environment variables (like NO_COLOR or CI) have been modified at
    runtime and you want the console to reflect the new settings.

    Returns
    -------
    None

    Examples
    --------
    Change color settings at runtime:

    >>> import os
    >>> from depkeeper.utils.console import reconfigure_console, print_info
    >>> print_info("This has color")  # Color enabled
    >>> os.environ["NO_COLOR"] = "1"
    >>> reconfigure_console()  # Apply change
    >>> print_info("This has no color")  # Color disabled

    Re-enable colors:

    >>> del os.environ["NO_COLOR"]
    >>> reconfigure_console()
    >>> print_info("Color is back")  # Color enabled again

    Notes
    -----
    This function only resets the console instance. The actual
    reconfiguration happens lazily on the next console access.

    See Also
    --------
    _get_console : Internal function that creates the console
    """
    global _console
    with _console_lock:
        _console = None


def print_success(message: str, prefix: str = "✓") -> None:
    """Print a success message in green.

    Displays a styled success message with a checkmark prefix. The message
    is rendered in bold green when color output is enabled.

    Parameters
    ----------
    message : str
        The success message to display.
    prefix : str, optional
        Prefix symbol to prepend to the message. Default is "✓" (checkmark).
        Can be customized or set to empty string for no prefix.

    Returns
    -------
    None

    Examples
    --------
    Standard success message:

    >>> from depkeeper.utils.console import print_success
    >>> print_success("Package updated successfully")
    ✓ Package updated successfully

    Custom prefix:

    >>> print_success("All tests passed", prefix="[OK]")
    [OK] All tests passed

    Notes
    -----
    The message uses the 'success' style from the depkeeper theme, which
    renders as bold green text when color output is enabled.

    See Also
    --------
    print_error : Print error messages in red
    print_warning : Print warning messages in yellow
    print_info : Print informational messages in cyan
    """
    _get_console().print(f"{prefix} {message}", style="success")


def print_error(message: str, prefix: str = "✗") -> None:
    """Print an error message in red.

    Displays a styled error message with an X mark prefix. The message
    is rendered in bold red when color output is enabled.

    Parameters
    ----------
    message : str
        The error message to display.
    prefix : str, optional
        Prefix symbol to prepend to the message. Default is "✗" (X mark).

    Returns
    -------
    None

    Examples
    --------
    >>> from depkeeper.utils.console import print_error
    >>> print_error("Failed to parse requirements file")
    ✗ Failed to parse requirements file

    >>> errors = ["Package not found", "Invalid version"]
    >>> for error in errors:
    ...     print_error(error)

    See Also
    --------
    print_success : Print success messages in green
    print_warning : Print warning messages in yellow
    """
    _get_console().print(f"{prefix} {message}", style="error")


def print_warning(message: str, prefix: str = "⚠") -> None:
    """Print a warning message in yellow.

    Displays a styled warning message with a warning symbol prefix. The
    message is rendered in bold yellow when color output is enabled.

    Parameters
    ----------
    message : str
        The warning message to display.
    prefix : str, optional
        Prefix symbol to prepend to the message. Default is "⚠" (warning sign).

    Returns
    -------
    None

    Examples
    --------
    >>> from depkeeper.utils.console import print_warning
    >>> print_warning("Package not found on PyPI")
    ⚠ Package not found on PyPI

    See Also
    --------
    print_error : Print error messages in red
    print_info : Print informational messages
    """
    _get_console().print(f"{prefix} {message}", style="warning")


def print_info(message: str, prefix: str = "ℹ") -> None:
    """Print an informational message in cyan.

    Displays a styled informational message with an info symbol prefix.
    The message is rendered in bold cyan when color output is enabled.

    Parameters
    ----------
    message : str
        The informational message to display.
    prefix : str, optional
        Prefix symbol to prepend to the message. Default is "ℹ" (info symbol).

    Returns
    -------
    None

    Examples
    --------
    >>> from depkeeper.utils.console import print_info
    >>> print_info("Checking 5 packages...")
    ℹ Checking 5 packages...

    See Also
    --------
    print_success : Print success messages
    print_warning : Print warning messages
    """
    _get_console().print(f"{prefix} {message}", style="info")


def print_dim(message: str) -> None:
    """Print a dimmed message with reduced emphasis.

    Displays a message in dimmed style, useful for supplementary information
    that should be visible but not prominent.

    Parameters
    ----------
    message : str
        The message to display in dimmed style.

    Returns
    -------
    None

    Examples
    --------
    >>> from depkeeper.utils.console import print_dim
    >>> print_dim("Using cache from /tmp/cache")
    Using cache from /tmp/cache

    Notes
    -----
    Dimmed text appears in a lighter/grayed color when color output is
    enabled, making it visually distinct from primary messages.
    """
    _get_console().print(message, style="dim")


def print_highlight(message: str) -> None:
    """Print a highlighted message with strong emphasis.

    Displays a message in bold magenta style, useful for drawing attention
    to important information that requires immediate notice.

    Parameters
    ----------
    message : str
        The message to display with highlighting.

    Returns
    -------
    None

    Examples
    --------
    >>> from depkeeper.utils.console import print_highlight
    >>> print_highlight("5 packages need updates")
    5 packages need updates

    Notes
    -----
    Highlighted text appears in bold magenta when color output is enabled,
    making it stand out significantly from other message types.
    """
    _get_console().print(message, style="highlight")


def print_table(
    data: List[Dict[str, Any]],
    headers: Optional[List[str]] = None,
    title: Optional[str] = None,
    caption: Optional[str] = None,
    column_styles: Optional[Dict[str, Dict[str, Any]]] = None,
    row_styler: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
) -> None:
    """Print data as a formatted Rich table with advanced styling support.

    Displays tabular data with automatic column width adjustment, optional
    title and caption, and consistent styling. Supports Rich markup in cell
    values and dynamic row styling via callbacks. Empty data lists are handled
    gracefully with a debug log message.

    Parameters
    ----------
    data : list[dict[str, Any]]
        List of dictionaries where each dictionary represents a row. Keys
        are column names and values are cell contents. Values can include
        Rich markup (e.g., "[red]error[/red]") for inline styling.
    headers : list[str], optional
        Column headers to display. If None, uses the keys from the first
        data row. Allows customizing column order or display names.
    title : str, optional
        Table title displayed above the table with styling.
    caption : str, optional
        Table caption displayed below the table.
    column_styles : dict[str, dict[str, Any]], optional
        Dictionary mapping column names to style configurations. Each config
        can include 'style', 'justify', 'no_wrap', 'width', etc.
        Example: {"Status": {"justify": "center", "width": 8}}
    row_styler : callable, optional
        Function that takes a row dict and returns a style string or None.
        Applied to entire row for conditional formatting.

    Returns
    -------
    None

    Examples
    --------
    Basic table:

    >>> from depkeeper.utils.console import print_table
    >>> data = [
    ...     {"Package": "requests", "Current": "2.28.0", "Latest": "2.31.0"},
    ...     {"Package": "click", "Current": "8.0.0", "Latest": "8.1.7"},
    ... ]
    >>> print_table(data, title="Outdated Packages")

    Table with Rich markup and custom column styles:

    >>> data = [
    ...     {"Status": "[green]✓[/green]", "Package": "requests"},
    ...     {"Status": "[red]✗[/red]", "Package": "click"},
    ... ]
    >>> column_styles = {"Status": {"justify": "center", "width": 8}}
    >>> print_table(data, column_styles=column_styles)

    Notes
    -----
    - Empty data lists are silently skipped
    - Missing dictionary keys result in empty cells
    - Values can include Rich markup for inline styling
    - Column styles allow fine-grained control over appearance
    - Row styler enables conditional row highlighting

    See Also
    --------
    depkeeper.utils.progress.ProgressTracker : For progress tracking
    """
    if not data:
        logger.debug("No data to display in table")
        return

    # Determine headers
    if headers is None:
        headers = list(data[0].keys())

    # Create table
    table = Table(title=title, caption=caption, show_header=True, header_style="bold")

    # Add columns with custom styles
    column_styles = column_styles or {}
    for header in headers:
        col_config = column_styles.get(header, {})

        # Extract justify with proper type - default to "default" if not specified
        justify_value = col_config.get("justify", "default")

        table.add_column(
            header,
            style=col_config.get("style"),
            justify=justify_value,
            no_wrap=col_config.get("no_wrap", False),
            width=col_config.get("width"),
            overflow=col_config.get("overflow", "fold"),
        )

    # Add rows
    for row in data:
        values = [str(row.get(h, "")) for h in headers]
        # Apply row styling if provided
        row_style = row_styler(row) if row_styler else None
        table.add_row(*values, style=row_style)

    # Print table
    _get_console().print(table)


def confirm(message: str, default: bool = False) -> bool:
    """Prompt user for yes/no confirmation.

    Displays an interactive prompt asking the user to confirm an action.
    Accepts 'y', 'yes', 'n', 'no' (case-insensitive). Empty input uses
    the default value. Handles interrupts gracefully.

    Parameters
    ----------
    message : str
        The confirmation question to display to the user.
    default : bool, optional
        Default response if user presses Enter without input. If True,
        shows [Y/n] prompt. If False, shows [y/N] prompt. Default is False.

    Returns
    -------
    bool
        True if user confirmed (answered yes), False if user declined
        or interrupted the prompt.

    Examples
    --------
    >>> from depkeeper.utils.console import confirm
    >>> if confirm("Update requirements.txt?"):
    ...     print("Updating...")

    >>> if confirm("Continue?", default=True):
    ...     print("Proceeding...")

    Notes
    -----
    Accepted responses: 'y', 'yes', 'n', 'no' (case-insensitive)
    Empty response uses the default value
    Keyboard interrupt (Ctrl+C) returns False

    See Also
    --------
    print_warning : Warn before destructive operations
    """
    console = _get_console()
    suffix = " [Y/n]: " if default else " [y/N]: "
    console.print(f"{message}{suffix}", end="", style="info")

    try:
        response = input().strip().lower()
    except (KeyboardInterrupt, EOFError):
        console.print()  # New line
        return False

    if not response:
        return default

    return response in ("y", "yes")


def get_raw_console() -> Console:
    """Get the underlying Rich Console instance for advanced usage.

    Provides direct access to the global Rich Console instance for advanced
    use cases not covered by the high-level printing functions.

    Returns
    -------
    Console
        The global Rich Console instance configured with depkeeper's theme.

    Examples
    --------
    Use Rich's advanced features:

    >>> from depkeeper.utils.console import get_raw_console
    >>> console = get_raw_console()
    >>> console.print("[bold red]Custom[/] [green]styled[/] text")

    Access console properties:

    >>> console = get_raw_console()
    >>> width = console.width
    >>> is_terminal = console.is_terminal

    Notes
    -----
    For most use cases, the high-level functions (print_success, print_error)
    are recommended. Use this only when you need Rich's advanced features.

    See Also
    --------
    reconfigure_console : Force console reconfiguration
    print_table : High-level table printing
    """
    return _get_console()
