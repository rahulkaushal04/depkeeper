"""
Console output utilities for depkeeper using Rich.

This module provides user-facing output helpers for CLI commands.
For diagnostic or debug output, use :mod:`depkeeper.utils.logger`.

Guidelines:
- print_* functions: user-facing status messages
- print_table / confirm: structured or interactive CLI output
- Logging should never go through this module
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Any, Callable, Dict, List, Optional

from rich.table import Table
from rich.theme import Theme
from rich.console import Console

# ---------------------------------------------------------------------------
# Theme configuration
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Console lifecycle management
# ---------------------------------------------------------------------------

_console: Optional[Console] = None
_console_lock = threading.Lock()


def _should_use_color() -> bool:
    """Return True if colored output should be enabled."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("CI"):
        return False
    try:
        return sys.stdout.isatty()
    except (AttributeError, OSError):
        return False


def _get_console() -> Console:
    """Return a singleton Rich Console instance."""
    global _console

    if _console is None:
        with _console_lock:
            if _console is None:
                use_color = _should_use_color()
                _console = Console(
                    theme=DEPKEEPER_THEME,
                    no_color=not use_color,
                    highlight=use_color,
                )
    return _console


def reconfigure_console() -> None:
    """Reset the global console instance.

    Useful if environment variables (e.g. NO_COLOR) change at runtime.
    """
    global _console
    with _console_lock:
        _console = None


# ---------------------------------------------------------------------------
# Status message helpers
# ---------------------------------------------------------------------------


def print_success(message: str, *, prefix: str = "[OK]") -> None:
    """Print a success message."""
    _get_console().print(f"{prefix} {message}", style="success")


def print_error(message: str, *, prefix: str = "[ERROR]") -> None:
    """Print an error message."""
    _get_console().print(f"{prefix} {message}", style="error")


def print_warning(message: str, *, prefix: str = "[WARNING]") -> None:
    """Print a warning message."""
    _get_console().print(f"{prefix} {message}", style="warning")


# ---------------------------------------------------------------------------
# Structured output
# ---------------------------------------------------------------------------


def print_table(
    data: List[Dict[str, Any]],
    *,
    headers: Optional[List[str]] = None,
    title: Optional[str] = None,
    caption: Optional[str] = None,
    column_styles: Optional[Dict[str, Dict[str, Any]]] = None,
    row_styler: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
    show_row_lines: bool = False,
) -> None:
    """Render structured data as a Rich table.

    Args:
        data: List of row dictionaries.
        headers: Column order. Defaults to keys of the first row.
        title: Optional table title.
        caption: Optional table caption.
        column_styles: Per-column style configuration.
        row_styler: Optional callback returning a row style.
        show_row_lines: Whether to draw horizontal lines between rows.
    """
    if not data:
        return

    if headers is None:
        headers = list(data[0].keys())

    table = Table(
        title=title,
        caption=caption,
        show_header=True,
        header_style="bold",
        show_lines=show_row_lines,
    )

    column_styles = column_styles or {}
    for header in headers:
        config = column_styles.get(header, {})
        table.add_column(
            header,
            style=config.get("style"),
            justify=config.get("justify", "default"),
            no_wrap=config.get("no_wrap", False),
            width=config.get("width"),
            overflow=config.get("overflow", "fold"),
        )

    for row in data:
        values = [str(row.get(h, "")) for h in headers]
        style = row_styler(row) if row_styler else None
        table.add_row(*values, style=style)

    _get_console().print(table)


# ---------------------------------------------------------------------------
# User interaction
# ---------------------------------------------------------------------------


def confirm(message: str, *, default: bool = False) -> bool:
    """Prompt the user for a yes/no confirmation.

    The prompt accepts common yes/no inputs. Behavior is as follows:

    - "y", "yes"   → return True
    - "n", "no"    → return False
    - empty input  → return `default`
    - any other input (invalid) → return `default`
    - Ctrl+C / EOF → return False

    Args:
        message: Prompt message shown to the user.
        default: Default choice used when the user presses Enter or
            provides an unrecognized response.

    Returns:
        True if confirmed, False otherwise.
    """
    console = _get_console()
    suffix = " [Y/n]: " if default else " [y/N]: "
    console.print(f"{message}{suffix}", end="", style="info")

    try:
        response = input().strip().lower()
    except (KeyboardInterrupt, EOFError):
        console.print()
        return False

    if not response:
        return default

    if response in ("y", "yes"):
        return True
    if response in ("n", "no"):
        return False

    # Invalid input → fall back to default
    return default


# ---------------------------------------------------------------------------
# Advanced / internal helpers
# ---------------------------------------------------------------------------


def get_raw_console() -> Console:
    """Return the underlying Rich Console instance."""
    return _get_console()


def colorize_update_type(update_type: str) -> str:
    """Return a Rich-markup colored update type label.

    Args:
        update_type: Update classification string.

    Returns:
        Rich markup string.
    """
    color_map = {
        "major": "red",
        "minor": "yellow",
        "patch": "green",
        "new": "cyan",
        "downgrade": "red",
        "update": "yellow",
    }

    color = color_map.get(update_type.lower())
    return f"[{color}]{update_type}[/{color}]" if color else update_type
