"""Command-line interface for depkeeper.

This module provides the main CLI entry point using the Click framework.
It defines the command structure, global options, context management, and
command routing for all depkeeper operations.

The CLI is organized as a Click group with multiple subcommands (check, update,
audit, etc.) that share common global options like verbosity, caching, and
color output preferences.

Architecture
------------
The CLI follows a hierarchical structure:

- **cli**: Main command group with global options
- **DepKeeperContext**: Shared context object for all commands
- **Subcommands**: Individual commands (check, update, audit, etc.)
- **Helper functions**: Logging setup and utilities

Global Options
--------------
All commands inherit these global options:

- **--config, -c**: Path to configuration file (or DEPKEEPER_CONFIG env var)
- **--verbose, -v**: Increase verbosity (-v for INFO, -vv for DEBUG)
- **--no-cache**: Disable PyPI response caching (or DEPKEEPER_NO_CACHE env var)
- **--color/--no-color**: Enable/disable colored output (or DEPKEEPER_COLOR env var)
- **--version**: Show version and exit
- **--help, -h**: Show help message and exit

Examples
--------
Basic command usage:

    $ depkeeper check
    $ depkeeper update --strategy minor
    $ depkeeper audit --severity critical

With global options:

    $ depkeeper -v check
    $ depkeeper -vv --no-cache update
    $ depkeeper --config /path/to/config.toml check

Environment variables:

    $ export DEPKEEPER_CONFIG=/path/to/config.toml
    $ export DEPKEEPER_NO_CACHE=1
    $ depkeeper check

Notes
-----
The CLI uses Click's context system to pass global configuration to
subcommands. Each command receives a DepKeeperContext object through the
@pass_context decorator.

Logging is configured based on verbosity level before command execution.
The NO_COLOR environment variable is respected for color output.

See Also
--------
Click documentation: https://click.palletsprojects.com/
depkeeper.commands : Individual command implementations
"""

from __future__ import annotations

import sys
import logging
from pathlib import Path
from typing import Optional

import click

from depkeeper.__version__ import __version__
from depkeeper.exceptions import DepKeeperError
from depkeeper.utils.logger import get_logger, setup_logging
from depkeeper.utils.console import print_error, print_info

logger = get_logger("cli")


# ============================================================================
# Global Options Context
# ============================================================================


class DepKeeperContext:
    """Global context object for CLI commands.

    This context object is created by the main CLI group and passed to all
    subcommands via Click's context system. It stores global configuration
    options that affect all commands, such as verbosity, caching preferences,
    and output styling.

    The context is accessible in subcommands through the @pass_context
    decorator, allowing commands to adapt their behavior based on global
    settings.

    Attributes
    ----------
    config_path : Path, optional
        Path to the configuration file (depkeeper.toml or pyproject.toml).
        If None, default configuration locations will be checked.
    verbose : int
        Verbosity level controlling log output:
        - 0: WARNING level (default, minimal output)
        - 1: INFO level (shows progress and status)
        - 2+: DEBUG level (detailed diagnostic information)
    no_cache : bool
        Whether to disable caching of PyPI API responses. When True, all
        package information is fetched fresh from PyPI, which is slower but
        ensures the most up-to-date data.
    color : bool
        Whether to enable colored terminal output. When False, NO_COLOR
        environment variable is set and Rich library outputs plain text.

    Examples
    --------
    Access context in a command:

        >>> @click.command()
        ... @pass_context
        ... def my_command(ctx: DepKeeperContext) -> None:
        ...     if ctx.verbose > 0:
        ...         print(f"Config: {ctx.config_path}")
        ...     if ctx.no_cache:
        ...         print("Cache disabled")

    Check verbosity level:

        >>> ctx = DepKeeperContext()
        >>> ctx.verbose = 2
        >>> if ctx.verbose >= 2:
        ...     print("Debug mode enabled")
        Debug mode enabled

    Notes
    -----
    This class is instantiated once per CLI invocation by the main cli()
    function. It is stored in Click's context.obj and retrieved by commands
    using the @pass_context decorator.

    The context is read-only by convention; commands should not modify it.
    Any command-specific state should be stored separately.

    See Also
    --------
    pass_context : Decorator to access context in commands
    cli : Main CLI function that creates the context
    """

    def __init__(self) -> None:
        self.config_path: Optional[Path] = None
        self.verbose: int = 0
        self.no_cache: bool = False
        self.color: bool = True


pass_context = click.make_pass_decorator(DepKeeperContext, ensure=True)


# ============================================================================
# Main CLI Group
# ============================================================================


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to configuration file.",
    envvar="DEPKEEPER_CONFIG",
)
@click.option(
    "--verbose",
    "-v",
    count=True,
    help="Increase verbosity (can be repeated: -v, -vv).",
)
@click.option(
    "--no-cache",
    is_flag=True,
    help="Disable caching of PyPI responses.",
    envvar="DEPKEEPER_NO_CACHE",
)
@click.option(
    "--color/--no-color",
    default=True,
    help="Enable/disable colored output.",
    envvar="DEPKEEPER_COLOR",
)
@click.version_option(
    version=__version__,
    prog_name="depkeeper",
    message="%(prog)s %(version)s",
)
@click.pass_context
def cli(
    ctx: click.Context,
    config: Optional[Path],
    verbose: int,
    no_cache: bool,
    color: bool,
) -> None:
    """depkeeper - Modern Python dependency management for requirements.txt

    Automatically check for updates, apply version constraints, and keep your
    dependencies secure and up-to-date with intelligent updates, security
    scanning, and dependency resolution.

    \b
    Common Commands:
      depkeeper check              Check for available updates
      depkeeper update             Update packages to newer versions
      depkeeper audit              Scan for security vulnerabilities
      depkeeper lock               Generate a lock file

    \b
    Examples:
      depkeeper check                          # Check for updates
      depkeeper update --strategy minor        # Safe updates
      depkeeper -v check                       # Verbose output
      depkeeper --no-cache update              # Fresh PyPI data

    For detailed help on any command, use: depkeeper COMMAND --help
    Documentation: https://docs.depkeeper.dev
    """
    # Create context object
    depkeeper_ctx = DepKeeperContext()
    depkeeper_ctx.config_path = config
    depkeeper_ctx.verbose = verbose
    depkeeper_ctx.no_cache = no_cache
    depkeeper_ctx.color = color

    # Store in Click context
    ctx.obj = depkeeper_ctx

    # Configure logging based on verbosity
    _setup_logging(verbose)

    # Set NO_COLOR environment variable if needed
    if not color:
        import os

        os.environ["NO_COLOR"] = "1"

    logger.debug(f"depkeeper v{__version__}")
    logger.debug(f"Config: {config}")
    logger.debug(f"Verbose: {verbose}, No-cache: {no_cache}, Color: {color}")


# ============================================================================
# Helper Functions
# ============================================================================


def _setup_logging(verbose: int) -> None:
    """Configure logging based on verbosity level.

    Internal helper function that maps the CLI verbosity count to appropriate
    Python logging levels and configures the depkeeper logger hierarchy.
    Called automatically by the main cli() function before command execution.

    The logging configuration affects all depkeeper modules, providing
    consistent logging behavior across the entire application. Higher
    verbosity levels include all messages from lower levels.

    Parameters
    ----------
    verbose : int
        Verbosity level from the --verbose flag:
        - 0: WARNING level (default) - Only warnings and errors
        - 1: INFO level (-v flag) - Progress and status messages
        - 2+: DEBUG level (-vv or more) - Detailed diagnostic information

    Returns
    -------
    None

    Examples
    --------
    Called internally by CLI (not for direct use):

        >>> # User runs: depkeeper -vv check
        >>> _setup_logging(2)  # Sets DEBUG level
        >>> logger.debug("This message is shown")

        >>> # User runs: depkeeper check
        >>> _setup_logging(0)  # Sets WARNING level
        >>> logger.info("This message is hidden")
        >>> logger.warning("This message is shown")

    Notes
    -----
    This is an internal function and should not be called directly by user
    code or plugins. It is automatically invoked by the CLI framework.

    The function delegates to depkeeper.utils.logger.setup_logging() which
    handles the actual logger configuration, including handler setup,
    formatting, and color support.

    See Also
    --------
    depkeeper.utils.logger.setup_logging : Actual logging configuration
    depkeeper.utils.logger.get_logger : Get logger instances
    """
    if verbose == 0:
        level = logging.WARNING
    elif verbose == 1:
        level = logging.INFO
    else:
        level = logging.DEBUG

    setup_logging(level=level)
    logger.debug(f"Logging configured at {logging.getLevelName(level)} level")


# ============================================================================
# Commands Import
# ============================================================================

# Import commands to register them with the CLI group
# This must be done after the cli group is defined
try:
    from depkeeper.commands.check import check
    from depkeeper.commands.update import update

    cli.add_command(check)
    cli.add_command(update)
except ImportError as e:
    # During development, commands might not be implemented yet
    logger.warning(f"Failed to import commands: {e}")


# ============================================================================
# Main Entry Point
# ============================================================================


def main() -> int:
    """Main entry point for the depkeeper CLI with exception handling.

    This function serves as the primary entry point when depkeeper is invoked
    as a console script. It wraps the Click CLI with comprehensive exception
    handling to provide user-friendly error messages and appropriate exit codes.

    The function catches various exception types and handles them appropriately:

    - Click exceptions: Already formatted, just display them
    - DepKeeperError: Custom application errors with detailed context
    - KeyboardInterrupt: User cancellation (Ctrl+C)
    - Unexpected exceptions: Log with traceback for debugging

    Returns
    -------
    int
        Exit code following POSIX conventions:
        - 0: Success, operation completed without errors
        - 1: General error (DepKeeperError, unexpected exceptions)
        - 2: Command line usage error (Click exceptions)
        - 130: Interrupted by user (SIGINT/Ctrl+C)

    Examples
    --------
    This function is called automatically by the console script:

        $ depkeeper check
        # Internally calls main(), which invokes cli()

    Exit code examples:

        $ depkeeper check
        $ echo $?  # 0 (success)

        $ depkeeper invalid-command
        $ echo $?  # 2 (usage error)

        $ depkeeper check
        # Press Ctrl+C
        $ echo $?  # 130 (interrupted)

    Use in scripts:

        >>> from depkeeper.cli import main
        >>> exit_code = main()
        >>> if exit_code == 0:
        ...     print("Success")

    Use in Python code (with sys.exit):

        >>> import sys
        >>> from depkeeper.cli import main
        >>> sys.exit(main())

    Notes
    -----
    This function disables Click's standalone mode to gain control over
    exception handling and exit codes. This allows for consistent error
    reporting across all error types.

    The function logs detailed error information at DEBUG level, which is
    useful for troubleshooting. Users can enable debug logging with -vv:

        $ depkeeper -vv check  # See detailed error information

    Custom DepKeeperError exceptions should include a 'details' attribute
    with additional context for debugging. This is logged but not shown to
    users unless debug mode is enabled.

    See Also
    --------
    cli : The main Click command group
    depkeeper.exceptions.DepKeeperError : Base exception class
    depkeeper.__main__.main : Alternative entry point for python -m
    """
    try:
        cli(standalone_mode=False)
        return 0
    except click.ClickException as e:
        # Click exceptions are already formatted nicely
        e.show()
        return e.exit_code
    except DepKeeperError as e:
        # Our custom exceptions
        print_error(f"{e}")
        logger.debug(f"DepKeeperError details: {e.details}", exc_info=True)
        return 1
    except KeyboardInterrupt:
        print_info("\nOperation cancelled by user")
        return 130  # Standard exit code for SIGINT
    except Exception as e:
        # Unexpected errors
        print_error(f"Unexpected error: {e}")
        logger.exception("Unexpected error in CLI")
        return 1


if __name__ == "__main__":
    sys.exit(main())
