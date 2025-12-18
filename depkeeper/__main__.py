"""Main entry point for running depkeeper as a module.

This module provides the entry point when depkeeper is invoked as:

    $ python -m depkeeper [args]

It handles the initialization of the CLI interface and provides graceful
error handling for development phases when the CLI is not yet fully
implemented.

The module uses lazy imports to avoid loading heavy dependencies until
actually needed, improving startup time and reducing import overhead for
scripts that only need to check the version or perform lightweight
operations.

Examples
--------
Run depkeeper as a module:

    $ python -m depkeeper check
    $ python -m depkeeper update
    $ python -m depkeeper --version

Notes
-----
This module is automatically invoked by Python when using the -m flag.
It should not be imported directly in user code. Instead, use:

    >>> from depkeeper.cli import main
    >>> main()

Or use the installed console script:

    $ depkeeper [args]

See Also
--------
depkeeper.cli : The main CLI implementation
"""

from __future__ import annotations

import sys


def main() -> int:
    """Main entry point for python -m depkeeper.

    This function serves as the entry point when depkeeper is invoked as a
    module (python -m depkeeper). It lazily imports the CLI to avoid loading
    heavy dependencies until needed, then delegates to the actual CLI
    implementation.

    Returns
    -------
    int
        Exit code returned by the CLI. Standard exit codes:
        - 0: Success
        - 1: General error
        - 2: Command line usage error
        - 130: Interrupted by user (Ctrl+C)

    Examples
    --------
    This function is called automatically when using python -m:

        $ python -m depkeeper check
        # Calls main() which delegates to depkeeper.cli.main()

    Direct invocation (not recommended):

        >>> from depkeeper.__main__ import main
        >>> exit_code = main()
        >>> print(exit_code)
        0

    Notes
    -----
    The function uses lazy imports to improve performance. The CLI module
    and its dependencies (click, rich, httpx, etc.) are only loaded when
    actually executing a command, not during module imports.

    See Also
    --------
    depkeeper.cli.main : The actual CLI implementation
    """
    try:
        from depkeeper.cli import main as cli_main
    except ImportError as exc:
        try:
            from depkeeper.__version__ import __version__

            sys.stderr.write(f"depkeeper version: {__version__}\n")
        except Exception:
            sys.stderr.write("depkeeper version: <unknown>\n")
        sys.stderr.write("\n")
        sys.stderr.write(f"ImportError: {exc}\n")
        return 0

    return cli_main()


if __name__ == "__main__":
    sys.exit(main())
