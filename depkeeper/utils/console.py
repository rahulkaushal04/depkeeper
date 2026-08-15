"""
Console output utilities for depkeeper using Rich.

This module provides user-facing output helpers for CLI commands.
For diagnostic or debug output, use :mod:`depkeeper.utils.logger`.

Guidelines:
- print_* functions: user-facing status messages
- print_table / confirm: structured or interactive CLI output
- Logging should never go through this module

Stream separation
-----------------
Every helper accepts a ``stderr`` keyword that selects the target stream.
Commands that emit machine-readable payloads (``--format json`` /
``--format simple``) must keep **stdout** reserved for the payload and send
all human-facing status output to **stderr**, otherwise the payload is
corrupted for downstream consumers such as ``jq``.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import IO, Any, Callable, Dict, List, Optional

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

# Keyed by ``stderr`` flag: False -> stdout console, True -> stderr console.
_consoles: Dict[bool, Console] = {}
_console_lock = threading.Lock()


def _target_stream(stderr: bool) -> IO[str]:
    """Return the stream a console with the given ``stderr`` flag writes to."""
    return sys.stderr if stderr else sys.stdout


def _should_use_color(*, stderr: bool = False) -> bool:
    """Return True if colored output should be enabled for the given stream.

    Args:
        stderr: Check ``sys.stderr`` instead of ``sys.stdout``. Each stream is
            evaluated independently because one may be a TTY while the other
            is redirected (e.g. ``depkeeper check --format json | jq``).
    """
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return _target_stream(stderr).isatty()
    except (AttributeError, OSError):
        return False


def _get_console(*, stderr: bool = False) -> Console:
    """Return the singleton Rich Console for the requested stream.

    Args:
        stderr: Return the stderr-bound console instead of the stdout one.
    """
    console = _consoles.get(stderr)

    if console is None:
        with _console_lock:
            console = _consoles.get(stderr)
            if console is None:
                use_color = _should_use_color(stderr=stderr)
                console = Console(
                    theme=DEPKEEPER_THEME,
                    stderr=stderr,
                    no_color=not use_color,
                    highlight=use_color,
                )
                _consoles[stderr] = console
    return console


def reconfigure_console() -> None:
    """Discard the memoized stdout and stderr consoles.

    Color support is probed once per stream when a console is first built, so
    call this after changing ``NO_COLOR`` or redirecting a stream at runtime
    (tests rely on it for isolation).
    """
    with _console_lock:
        _consoles.clear()


# ---------------------------------------------------------------------------
# Status message helpers
# ---------------------------------------------------------------------------


def print_success(
    message: str, *, prefix: str = "[OK]", stderr: bool = False
) -> None:
    """Print a success message.

    Args:
        message: Message body.
        prefix: Label rendered before the message.
        stderr: Write to stderr instead of stdout. Use this whenever stdout
            carries machine-readable output.
    """
    _get_console(stderr=stderr).print(f"{prefix} {message}", style="success")


def print_error(message: str, *, prefix: str = "[ERROR]", stderr: bool = True) -> None:
    """Print an error message.

    Errors default to stderr so they never corrupt machine-readable stdout.

    Args:
        message: Message body.
        prefix: Label rendered before the message.
        stderr: Write to stderr (default) or stdout.
    """
    _get_console(stderr=stderr).print(f"{prefix} {message}", style="error")


def print_warning(
    message: str, *, prefix: str = "[WARNING]", stderr: bool = False
) -> None:
    """Print a warning message.

    Args:
        message: Message body.
        prefix: Label rendered before the message.
        stderr: Write to stderr instead of stdout. Use this whenever stdout
            carries machine-readable output.
    """
    _get_console(stderr=stderr).print(f"{prefix} {message}", style="warning")


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
    stderr: bool = False,
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
        stderr: Render to stderr instead of stdout.
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

    _get_console(stderr=stderr).print(table)


# ---------------------------------------------------------------------------
# User interaction
# ---------------------------------------------------------------------------


def confirm(message: str, *, default: bool = False) -> bool:
    """Prompt the user for a yes/no confirmation on stdout.

    Input handling:

    - ``y`` / ``yes`` -> ``True``
    - ``n`` / ``no`` -> ``False``
    - empty or unrecognized input -> *default*
    - ``Ctrl+C`` / EOF -> ``False``

    Unrecognized input falls back to *default* rather than re-prompting, so a
    non-interactive caller can never be trapped in a loop.

    Args:
        message: Prompt message shown to the user.
        default: Choice used when the user presses Enter or types something
            unrecognized.

    Returns:
        ``True`` if confirmed, ``False`` otherwise.
    """
    console = _get_console()
    suffix = " [Y/n]: " if default else " [y/N]: "
    console.print(f"{message}{suffix}", end="", style="info", markup=False)

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

    return default


# ---------------------------------------------------------------------------
# Advanced / internal helpers
# ---------------------------------------------------------------------------


def get_raw_console(*, stderr: bool = False) -> Console:
    """Return the underlying Rich Console instance.

    Args:
        stderr: Return the stderr-bound console instead of the stdout one.
    """
    return _get_console(stderr=stderr)


def colorize_update_type(update_type: str) -> str:
    """Wrap an update-type label in Rich markup colored by severity.

    Args:
        update_type: Update classification, e.g. ``"major"`` (see
            `get_update_type`).

    Returns:
        Rich markup string, or *update_type* unchanged when the label has no
        assigned color.
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
