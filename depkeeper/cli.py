"""
CLI entry point for depkeeper.

Provides the main command-line interface using Click, with global options,
configuration loading, and command routing.
"""

from __future__ import annotations

import sys
import logging
from pathlib import Path
from typing import Optional

import click

from depkeeper.__version__ import __version__
from depkeeper.utils.logger import get_logger, setup_logging
from depkeeper.utils.console import print_error, print_info
from depkeeper.exceptions import DepKeeperError

logger = get_logger("cli")


# ============================================================================
# Global Options Context
# ============================================================================


class DepKeeperContext:
    """
    Global context for CLI commands.

    Stores global options and configuration that should be available
    to all commands.

    Attributes
    ----------
    config_path : Path, optional
        Path to configuration file.
    verbose : int
        Verbosity level (0=normal, 1=verbose, 2=debug).
    no_cache : bool
        Whether to disable caching.
    color : bool
        Whether to enable colored output.
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
    """
    depkeeper - Modern Python dependency management for requirements.txt files.

    Automatically check for updates, apply version constraints, and keep your
    dependencies secure and up-to-date.

    Examples:

        # Check for updates
        depkeeper check

        # Update all packages
        depkeeper update

        # Update with specific strategy
        depkeeper update --strategy semver-minor

    For more information, visit: https://github.com/rahulkaushal04/depkeeper
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
    """
    Configure logging based on verbosity level.

    Parameters
    ----------
    verbose : int
        Verbosity level:
        - 0: WARNING (default)
        - 1: INFO (-v)
        - 2+: DEBUG (-vv or more)
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
    """
    Main entry point for the CLI.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for errors).
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
