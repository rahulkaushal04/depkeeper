"""
Executable module for depkeeper.

Running:
    python -m depkeeper

is equivalent to:
    depkeeper

This module simply forwards execution to the CLI entrypoint defined in
`depkeeper.cli`.
"""

from __future__ import annotations

import sys


def main() -> int:
    """
    Main entrypoint when executing `python -m depkeeper`.

    Returns:
        Exit code returned by the CLI.
    """
    try:
        # Import lazily so dependencies are only loaded during CLI use
        from depkeeper.cli import main as cli_main
    except ImportError as exc:
        # CLI not implemented yet (Phase 0) or import error during development
        print("depkeeper CLI is not available yet.")
        print("This is expected during early development (Phase 0).")
        print()
        print(f"Python version : {sys.version}")
        try:
            from depkeeper.__version__ import __version__

            print(f"depkeeper version: {__version__}")
        except Exception:
            print("depkeeper version: <unknown>")
        print()
        print(f"ImportError: {exc}")
        return 0

    # Execute the CLI handler
    return cli_main()


if __name__ == "__main__":
    sys.exit(main())
