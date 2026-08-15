"""Logging utilities for depkeeper.

Centralizes logger configuration, formatting, and retrieval for the depkeeper
package. It is safe for both library and CLI usage: handlers are never
duplicated, and colorized output is optional.
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
    """Logging formatter that colorizes the level name when the TTY allows it.

    Args:
        fmt: Standard :mod:`logging` format string.
        datefmt: Timestamp format passed to :class:`logging.Formatter`.
        use_color: Master switch. Even when ``True``, color is applied only
            if the destination stream also passes :meth:`_should_use_color`.
    """

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
        """Render *record*, wrapping its level name in an ANSI color code."""
        if self.use_color and self._should_use_color():
            color = self.COLORS.get(record.levelname)
            if color:
                record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)

    @staticmethod
    def _should_use_color() -> bool:
        """Return whether ANSI colors are appropriate for ``sys.stderr``.

        ``NO_COLOR`` is honored per the no-color.org convention, and ``CI``
        is treated as a non-interactive environment because build log viewers
        render raw escape sequences.
        """
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
    """Configure logging for the ``depkeeper`` logger hierarchy.

    Safe to call multiple times: existing handlers are replaced under a
    process-wide lock rather than accumulated.

    Side effects:
        Reconfigures the shared ``depkeeper`` logger for the whole process and
        sets ``propagate = False`` on it, so records no longer reach the root
        logger. Test suites that capture log output must snapshot and restore
        that logger's handlers, level and ``propagate`` flag.

    Args:
        level: Logging level (e.g., ``logging.INFO``, ``logging.DEBUG``).
        verbose: Enable verbose formatting with timestamps and logger names.
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
    """Return a logger within the ``depkeeper`` namespace.

    Bare names are prefixed with ``depkeeper.`` so every logger inherits the
    configuration applied by :func:`setup_logging`.

    Args:
        name: Logger name, e.g. ``"parser"`` or ``__name__``.

    Returns:
        A logger under the ``depkeeper`` hierarchy. When logging has not been
        configured, a :class:`logging.NullHandler` is attached so importing
        depkeeper as a library never emits "no handlers" warnings.
    """
    if not name or name == "depkeeper":
        logger = logging.getLogger("depkeeper")
    elif name.startswith("depkeeper."):
        logger = logging.getLogger(name)
    else:
        logger = logging.getLogger(f"depkeeper.{name}")

    if not logger.handlers and (not logger.parent or not logger.parent.handlers):
        logger.addHandler(logging.NullHandler())

    return logger


def is_logging_configured() -> bool:
    """Return whether :func:`setup_logging` has run since the last reset."""
    return _logging_configured


def disable_logging() -> None:
    """Silence all depkeeper logging output and reset the configured flag."""
    global _logging_configured

    with _lock:
        root_logger = logging.getLogger("depkeeper")
        root_logger.handlers.clear()
        root_logger.addHandler(logging.NullHandler())
        root_logger.setLevel(logging.NOTSET)
        _logging_configured = False
