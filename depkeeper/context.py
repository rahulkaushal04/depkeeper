"""Context object for CLI commands.

This module provides the shared context object that is passed to all CLI
commands via Click's context system. It stores global configuration options
that affect command execution.

By separating the context into its own module, we avoid circular import
dependencies between cli.py and command modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click


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
    depkeeper.cli.cli : Main CLI function that creates the context
    """

    def __init__(self) -> None:
        """Initialize context with default values."""
        self.config_path: Optional[Path] = None
        self.verbose: int = 0
        self.color: bool = True


# Create the pass_context decorator for use in commands
pass_context = click.make_pass_decorator(DepKeeperContext, ensure=True)
