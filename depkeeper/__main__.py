"""
Module entry point for depkeeper.

This file enables execution via ``python -m depkeeper`` and delegates
control to the main CLI implementation.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Entry point for ``python -m depkeeper``.

    Returns:
        Exit code:
            0   Success
            1   Import or runtime error
            130 Interrupted by user
    """
    try:
        from depkeeper.cli import main as cli_main
    except ImportError as exc:
        _print_startup_error(exc)
        return 1

    return cli_main()


def _print_startup_error(exc: ImportError) -> None:
    """Print a helpful error message if the CLI cannot be imported."""
    try:
        from depkeeper.__version__ import __version__

        sys.stderr.write(f"depkeeper version: {__version__}\n")
    except Exception:
        sys.stderr.write("depkeeper version: <unknown>\n")

    sys.stderr.write("\n")
    sys.stderr.write(f"ImportError: {exc}\n")


if __name__ == "__main__":
    sys.exit(main())
