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
        sys.stderr.write("depkeeper CLI is not available yet.")
        sys.stderr.write("This is expected during early development (Phase 0).")
        sys.stderr.write()
        sys.stderr.write(f"Python version : {sys.version}")
        try:
            from depkeeper.__version__ import __version__

            sys.stderr.write(f"depkeeper version: {__version__}")
        except Exception:
            sys.stderr.write("depkeeper version: <unknown>")
        sys.stderr.write()
        sys.stderr.write(f"ImportError: {exc}")
        return 0

    # Execute the CLI handler
    return cli_main()


if __name__ == "__main__":
    sys.exit(main())
