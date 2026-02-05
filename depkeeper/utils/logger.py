"""
Logging utilities for depkeeper.

This module centralizes logger configuration, formatting, and retrieval
for the depkeeper package. It is designed to be safe for libraries and
CLI usage, avoiding duplicate handlers and supporting optional colorized
output.
"""

from __future__ import annotations

import os
import sys
import logging
import threading
from typing import IO, Optional

from depkeeper.constants import (
    LOG_DATE_FORMAT,
    LOG_DEFAULT_FORMAT,
    LOG_VERBOSE_FORMAT,
)

_logging_configured: bool = False
_lock = threading.Lock()


class ColoredFormatter(logging.Formatter):
    """Logging formatter with optional ANSI color support."""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def __init__(
        self,
        fmt: str,
        *,
        datefmt: Optional[str] = None,
        use_color: bool = True,
    ) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        if self.use_color and self._should_use_color():
            color = self.COLORS.get(record.levelname)
            if color:
                record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)

    @staticmethod
    def _should_use_color() -> bool:
        """Determine whether ANSI colors should be emitted."""
        if os.environ.get("NO_COLOR"):
            return False
        if os.environ.get("CI"):
            return False
        try:
            return sys.stderr.isatty()
        except (AttributeError, OSError):
            return False


def setup_logging(
    *,
    level: int = logging.INFO,
    verbose: bool = False,
    stream: Optional[IO[str]] = None,
) -> None:
    """Configure logging for depkeeper.

    This function is safe to call multiple times; configuration is
    protected by a process-wide lock.

    Args:
        level: Logging level (e.g., ``logging.INFO``, ``logging.DEBUG``).
        verbose: Enable verbose formatting with timestamps.
        stream: Output stream; defaults to ``sys.stderr``.
    """
    global _logging_configured

    with _lock:
        root_logger = logging.getLogger("depkeeper")
        root_logger.handlers.clear()
        root_logger.setLevel(level)

        handler = logging.StreamHandler(stream or sys.stderr)
        handler.setLevel(level)

        fmt = LOG_VERBOSE_FORMAT if verbose else LOG_DEFAULT_FORMAT
        formatter = ColoredFormatter(
            fmt,
            datefmt=LOG_DATE_FORMAT,
            use_color=not os.environ.get("NO_COLOR"),
        )
        handler.setFormatter(formatter)

        root_logger.addHandler(handler)
        root_logger.propagate = False
        _logging_configured = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a logger within the depkeeper namespace.

    Args:
        name: Logger name. Use ``__name__`` for module-relative naming.

    Returns:
        A logger instance under the ``depkeeper`` hierarchy.
    """
    if not name or name == "depkeeper":
        logger = logging.getLogger("depkeeper")
    elif name.startswith("depkeeper."):
        logger = logging.getLogger(name)
    else:
        logger = logging.getLogger(f"depkeeper.{name}")

    # Ensure library-safe behavior if logging is not configured
    if not logger.handlers and (not logger.parent or not logger.parent.handlers):
        logger.addHandler(logging.NullHandler())

    return logger


def is_logging_configured() -> bool:
    """Return True if depkeeper logging has been configured."""
    return _logging_configured


def disable_logging() -> None:
    """Disable all depkeeper logging output."""
    global _logging_configured

    with _lock:
        root_logger = logging.getLogger("depkeeper")
        root_logger.handlers.clear()
        root_logger.addHandler(logging.NullHandler())
        root_logger.setLevel(logging.NOTSET)
        _logging_configured = False
