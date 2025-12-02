"""
Centralized logging utilities for depkeeper.

This module provides:

  • Configurable logging setup (console + optional file log)
  • Support for Rich-enhanced output
  • A consistent logger hierarchy under the "depkeeper" namespace
  • A thread-safe, idempotent setup function
  • Helper utilities for fetching loggers and consoles
  • Temporary log-level overrides via LoggerContext

Design principles:
  - Avoid global mutable logging state when possible
  - Handlers should not be duplicated across repeated calls
  - Output must be clean, colorful (Rich), and test-safe
  - All loggers should be retrieved through get_logger()
"""

from __future__ import annotations

import sys
import logging
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler

from depkeeper.constants import DEFAULT_LOG_LEVEL, LOG_DATE_FORMAT, LOG_FORMAT


# ============================================================================
# Internal Singleton State
# ============================================================================

# Thread-safe lazy initialization of the root depkeeper logger
_LOGGER_SINGLETON: Optional[logging.Logger] = None

# Shared Rich console instance
_CONSOLE_SINGLETON: Optional[Console] = None


# ============================================================================
# Logger Setup
# ============================================================================


def setup_logging(
    level: str = DEFAULT_LOG_LEVEL,
    *,
    log_file: Optional[str | Path] = None,
    use_rich: bool = True,
) -> logging.Logger:
    """
    Initialize the depkeeper logging system.

    This function is idempotent — repeated calls will update the configuration
    but will not add duplicate handlers.

    Parameters
    ----------
    level:
        Logging level ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL").
    log_file:
        Optional path for file logging.
    use_rich:
        Whether to enable Rich-enhanced console logging.

    Returns
    -------
    logging.Logger
        The configured root depkeeper logger.
    """
    global _LOGGER_SINGLETON, _CONSOLE_SINGLETON

    level_val = getattr(logging, level.upper(), logging.INFO)

    # Create or fetch root logger
    logger = logging.getLogger("depkeeper")
    logger.setLevel(level_val)

    # Remove all previous handlers to avoid duplicates
    for h in list(logger.handlers):
        logger.removeHandler(h)

    # Configure console handler
    if use_rich:
        _CONSOLE_SINGLETON = _CONSOLE_SINGLETON or Console(stderr=True)
        console_handler: logging.Handler = RichHandler(
            console=_CONSOLE_SINGLETON,
            show_time=True,
            show_path=False,
            markup=True,
            rich_tracebacks=True,
        )
    else:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(
            logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
        )

    console_handler.setLevel(logging.DEBUG)
    logger.addHandler(console_handler)

    # Optional file logging
    if log_file:
        file_path = Path(log_file)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
        )
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)

    _LOGGER_SINGLETON = logger
    return logger


# ============================================================================
# Logger Access Helpers
# ============================================================================


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Retrieve a logger from the depkeeper hierarchy.

    Parameters
    ----------
    name:
        Optional submodule logger name: e.g. "resolver", "parser".

    Returns
    -------
    logging.Logger
    """
    global _LOGGER_SINGLETON

    if _LOGGER_SINGLETON is None:
        setup_logging()  # lazy initialization

    if not name or name == "depkeeper":
        return _LOGGER_SINGLETON  # type: ignore

    return logging.getLogger(f"depkeeper.{name}")


def get_console() -> Console:
    """
    Fetch the shared Rich console instance.

    Returns
    -------
    rich.console.Console
    """
    global _CONSOLE_SINGLETON

    if _CONSOLE_SINGLETON is None:
        _CONSOLE_SINGLETON = Console(stderr=True)

    return _CONSOLE_SINGLETON


# ============================================================================
# Context Manager
# ============================================================================


class LoggerContext:
    """
    Temporarily override the log level for a logger.

    Usage:
        with LoggerContext("DEBUG"):
            logger.info("Inside context")
    """

    def __init__(
        self,
        level: str,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        level_val = getattr(logging, level.upper(), logging.INFO)
        self.logger = logger or get_logger()
        self.old_level = self.logger.level
        self.new_level = level_val

    def __enter__(self) -> logging.Logger:
        self.logger.setLevel(self.new_level)
        return self.logger

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore
        self.logger.setLevel(self.old_level)
        # No suppression of exceptions
