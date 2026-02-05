"""
Shared context object for depkeeper CLI commands.

This module defines the global Click context used to share configuration
and runtime options across CLI subcommands.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click


class DepKeeperContext:
    """Global context object for depkeeper CLI commands.

    An instance of this class is created once per CLI invocation and
    passed to commands using Click's context mechanism.

    Attributes:
        config_path: Path to the depkeeper configuration file, if provided.
        verbose: Verbosity level (0=WARNING, 1=INFO, 2+=DEBUG).
        color: Whether colored terminal output is enabled.
    """

    __slots__ = ("config_path", "verbose", "color")

    def __init__(self) -> None:
        self.config_path: Optional[Path] = None
        self.verbose: int = 0
        self.color: bool = True


#: Click decorator for injecting :class:`DepKeeperContext` into commands.
pass_context = click.make_pass_decorator(DepKeeperContext, ensure=True)
