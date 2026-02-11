"""
Command-line interface for depkeeper.

This module provides the main CLI entry point and handles global options,
configuration loading, and command registration.
"""

from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from typing import Optional

import click

from depkeeper.config import load_config
from depkeeper.__version__ import __version__
from depkeeper.context import DepKeeperContext
from depkeeper.exceptions import ConfigError, DepKeeperError
from depkeeper.utils.logger import get_logger, setup_logging
from depkeeper.utils.console import print_error, print_warning

logger = get_logger("cli")


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
    "--color/--no-color",
    default=True,
    help="Enable or disable colored output.",
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
    color: bool,
) -> None:
    """depkeeper — modern dependency management for requirements.txt files.

    \b
    Available commands:
      depkeeper check              Check for available updates
      depkeeper update             Update packages to newer versions

    \b
    Examples:
      depkeeper check
      depkeeper update
      depkeeper -v check

    Use ``depkeeper COMMAND --help`` for command-specific options.
    """
    _configure_logging(verbose)

    try:
        loaded_config = load_config(config)
    except ConfigError as exc:
        print_error(str(exc))
        raise SystemExit(1) from exc

    depkeeper_ctx = DepKeeperContext()
    depkeeper_ctx.config_path = config or (
        loaded_config.source_path if loaded_config.source_path else None
    )
    depkeeper_ctx.color = color
    depkeeper_ctx.verbose = verbose
    depkeeper_ctx.config = loaded_config
    ctx.obj = depkeeper_ctx

    # Respect NO_COLOR for downstream libraries
    if color:
        os.environ.pop("NO_COLOR", None)
    else:
        os.environ["NO_COLOR"] = "1"

    logger.debug("depkeeper v%s", __version__)
    logger.debug("Config path: %s", depkeeper_ctx.config_path)
    if loaded_config.source_path:
        logger.debug("Loaded configuration: %s", loaded_config.to_log_dict())
    logger.debug("Verbosity: %s | Color: %s", verbose, color)


def _configure_logging(verbose: int) -> None:
    """Configure logging level based on verbosity flags."""
    if verbose <= 0:
        level = logging.WARNING
    elif verbose == 1:
        level = logging.INFO
    else:
        level = logging.DEBUG

    setup_logging(level=level)
    logger.debug("Logging initialized at %s level", logging.getLevelName(level))


# Register CLI subcommands
try:
    from depkeeper.commands.check import check
    from depkeeper.commands.update import update

    cli.add_command(check)
    cli.add_command(update)

except ImportError as exc:
    sys.stderr.write(f"FATAL: Failed to import CLI commands: {exc}\n")
    sys.exit(1)


def main() -> int:
    """Main entry point for the depkeeper CLI.

    Returns:
        Exit code:
            0   Success
            1   Unhandled or application error
            2   Usage error (Click)
            130 Interrupted by user (Ctrl+C)
    """
    try:
        cli(standalone_mode=False)
        return 0

    except click.ClickException as exc:
        exc.show()
        return exc.exit_code

    except DepKeeperError as exc:
        print_error(str(exc))
        logger.debug(
            "DepKeeperError details: %s",
            exc.details or "<none>",
            exc_info=True,
        )
        return 1

    except KeyboardInterrupt:
        print_warning("\nOperation cancelled by user")
        return 130

    except Exception as exc:
        print_error(f"Unexpected error: {exc}")
        logger.exception("Unhandled exception in CLI")
        return 1


if __name__ == "__main__":
    sys.exit(main())
