"""Logging utilities for depkeeper.

This module provides a centralized logging interface with consistent naming
and configuration across all depkeeper modules. It follows library logging
best practices by using NullHandler by default and allowing applications to
configure logging as needed.

The logging hierarchy is organized under the 'depkeeper' namespace to avoid
conflicts with other libraries.

Examples
--------
As a library (no output by default):
    >>> from depkeeper.utils.logger import get_logger
    >>> logger = get_logger("parser")
    >>> logger.info("This will not show (NullHandler)")

As an application (configure logging first):
    >>> from depkeeper.utils.logger import setup_logging, get_logger
    >>> import logging
    >>> setup_logging(level=logging.INFO)
    >>> logger = get_logger("parser")
    >>> logger.info("This will show")

For testing (disable all output):
    >>> from depkeeper.utils.logger import disable_logging
    >>> disable_logging()
"""

from __future__ import annotations

import os
import sys
import logging
import threading
from typing import IO, Optional, Any

# Module Constants
DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
DEFAULT_FORMAT: str = "%(levelname)s: %(message)s"
VERBOSE_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Module state - tracks if logging has been configured
_logging_configured: bool = False
_lock = threading.Lock()


class ColoredFormatter(logging.Formatter):
    """Formatter that adds colors to log levels if supported.

    Respects NO_COLOR environment variable and terminal capabilities.
    Colors are only applied when:
    - NO_COLOR is not set
    - Output is to a TTY
    - Not running in CI environment
    """

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def __init__(self, *args: Any, use_color: bool = True, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record with optional color."""
        if self.use_color and self._should_use_color():
            levelname = record.levelname
            if levelname in self.COLORS:
                record.levelname = f"{self.COLORS[levelname]}{levelname}{self.RESET}"
        return super().format(record)

    def _should_use_color(self) -> bool:
        """Check if color output should be used."""
        # NO_COLOR environment variable disables color
        if os.environ.get("NO_COLOR"):
            return False

        # Check if running in CI
        if os.environ.get("CI"):
            return False

        # Check if stderr is a terminal
        try:
            return sys.stderr.isatty()
        except (AttributeError, OSError):
            return False


def setup_logging(
    level: int = logging.INFO,
    verbose: bool = False,
    stream: Optional[IO[str]] = None,
) -> None:
    """Configure logging for depkeeper CLI and applications.

    This sets up the root 'depkeeper' logger with appropriate handlers and
    formatters. Should be called once at application startup, typically from
    the CLI entry point. Safe to call multiple times (will reconfigure if
    called again).

    For library usage, this is optional. By default, depkeeper uses NullHandler
    and will not produce any log output unless explicitly configured by the
    consuming application.

    Parameters
    ----------
    level : int, optional
        Logging level constant from the logging module. Common values:
        - logging.DEBUG (10): Detailed information for diagnosing problems
        - logging.INFO (20): Confirmation that things are working as expected
        - logging.WARNING (30): Indication of potential issues (default)
        - logging.ERROR (40): Serious problems
        Default is logging.INFO.
    verbose : bool, optional
        Whether to use verbose output format. When True, includes timestamps
        and module names. When False, uses simple level and message format.
        Default is False.
    stream : IO[str], optional
        Output stream for log messages. If None, defaults to sys.stderr.
        Can be any file-like object that accepts text (e.g., open file,
        io.StringIO).

    Returns
    -------
    None

    Examples
    --------
    Basic setup for CLI with INFO level:

    >>> import logging
    >>> from depkeeper.utils.logger import setup_logging, get_logger
    >>> setup_logging(level=logging.INFO)
    >>> logger = get_logger("parser")
    >>> logger.info("Starting parse operation")
    INFO: Starting parse operation

    Debug mode with verbose output:

    >>> setup_logging(level=logging.DEBUG, verbose=True)
    >>> logger = get_logger("checker")
    >>> logger.debug("Checking package versions")
    2025-12-08 10:30:45 - depkeeper.checker - DEBUG - Checking package versions

    Custom stream for log file output:

    >>> with open("depkeeper.log", "w") as f:
    ...     setup_logging(level=logging.INFO, stream=f)
    ...     logger = get_logger()
    ...     logger.info("Logged to file")

    Notes
    -----
    This function modifies the global logging configuration for the 'depkeeper'
    namespace. When using depkeeper as a library, you have three options:

    1. Don't call this function - depkeeper will use NullHandler (no output).
       This is the recommended approach for libraries.
    2. Call this function to enable depkeeper's internal logging in your
       application.
    3. Configure Python's logging yourself using standard logging.config -
       depkeeper loggers will respect your configuration.

    The function prevents propagation to the root logger to avoid interference
    with other libraries' logging configurations.

    See Also
    --------
    get_logger : Get a logger instance for a specific module
    disable_logging : Disable all depkeeper logging output
    is_logging_configured : Check if logging has been configured
    """
    global _logging_configured

    with _lock:  # Thread-safe configuration
        root_logger = logging.getLogger("depkeeper")

        # Remove existing handlers to avoid duplicates
        root_logger.handlers.clear()

        # Set level
        root_logger.setLevel(level)

        # Create console handler
        handler = logging.StreamHandler(stream or sys.stderr)
        handler.setLevel(level)

        # Set format with color support
        fmt = VERBOSE_FORMAT if verbose else DEFAULT_FORMAT
        use_color = not os.environ.get("NO_COLOR") and hasattr(sys.stderr, "isatty")
        formatter = ColoredFormatter(fmt, datefmt=DATE_FORMAT, use_color=use_color)
        handler.setFormatter(formatter)

        # Add handler
        root_logger.addHandler(handler)

        # Prevent propagation to root logger
        root_logger.propagate = False

        _logging_configured = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get a logger from the depkeeper hierarchy.

    This is the primary interface for obtaining loggers throughout the
    depkeeper codebase. All loggers are namespaced under 'depkeeper' to
    avoid conflicts with other libraries and to provide a consistent logging
    hierarchy.

    By default, if no logging configuration has been set up, the logger will
    use a NullHandler to prevent "No handlers could be found" warnings. This
    follows the Python logging best practice for libraries documented in the
    Python Logging Cookbook.

    Parameters
    ----------
    name : str, optional
        Submodule or component name for the logger. Best practice is to pass
        __name__ to get proper module hierarchy. Common patterns:
        - get_logger(__name__): Automatic module path (recommended)
        - get_logger("parser"): Custom component name
        - get_logger(): Root depkeeper logger

        For module 'depkeeper.core.parser', using __name__ creates logger
        'depkeeper.core.parser' automatically.

        If None or "depkeeper", returns the root depkeeper logger.

    Returns
    -------
    logging.Logger
        A configured Logger instance within the depkeeper namespace. The
        logger will have a NullHandler if no other handlers are configured,
        ensuring library-friendly behavior.

    Examples
    --------
    Recommended: Use __name__ for automatic module path:

    >>> # In depkeeper/core/parser.py
    >>> from depkeeper.utils.logger import get_logger
    >>> logger = get_logger(__name__)  # Creates 'depkeeper.core.parser'
    >>> logger.info("Parsing requirements.txt")

    Custom component name:

    >>> logger = get_logger("parser")  # Creates 'depkeeper.parser'
    >>> logger.info("Parsing requirements.txt")

    Get the root depkeeper logger:

    >>> root_logger = get_logger()  # Same as get_logger("depkeeper")
    >>> root_logger.warning("Configuration file not found")

    Use in a module (best practice):

    >>> # In depkeeper/core/checker.py
    >>> from depkeeper.utils.logger import get_logger
    >>> logger = get_logger(__name__)  # Recommended
    >>>
    >>> def check_version(package: str) -> None:
    ...     logger.debug(f"Checking version for {package}")
    ...     # ... implementation ...

    Notes
    -----
    The logger hierarchy is organized as follows:

    - depkeeper (root)
      - depkeeper.parser
      - depkeeper.checker
      - depkeeper.updater
      - depkeeper.cli
      - etc.

    Each logger inherits from its parent, allowing for hierarchical
    configuration and filtering.

    If the logger has no handlers configured and no parent handlers exist,
    a NullHandler is automatically added. This prevents the "No handlers
    could be found for logger" warning while allowing consuming applications
    to configure logging as needed.

    See Also
    --------
    setup_logging : Configure logging for depkeeper
    is_logging_configured : Check if logging has been configured
    """
    if not name or name == "depkeeper":
        logger = logging.getLogger("depkeeper")
    else:
        # If name already starts with 'depkeeper', use it as-is (for __name__ usage)
        # Otherwise, prepend 'depkeeper.' (for custom names)
        if name.startswith("depkeeper."):
            logger = logging.getLogger(name)
        else:
            logger = logging.getLogger(f"depkeeper.{name}")

    # Add NullHandler if no handlers configured (library best practice)
    if not logger.handlers and (not logger.parent or not logger.parent.handlers):
        logger.addHandler(logging.NullHandler())

    return logger


def is_logging_configured() -> bool:
    """Check if depkeeper logging has been configured.

    This function queries the internal module state to determine if
    `setup_logging()` has been called. Useful for conditional logging
    setup or for testing.

    Returns
    -------
    bool
        True if `setup_logging()` has been called at least once, False
        otherwise. Note that calling `disable_logging()` resets this to
        False.

    Examples
    --------
    Check initial state (no configuration):

    >>> from depkeeper.utils.logger import is_logging_configured
    >>> is_logging_configured()
    False

    After configuration:

    >>> from depkeeper.utils.logger import setup_logging, is_logging_configured
    >>> import logging
    >>> setup_logging(level=logging.INFO)
    >>> is_logging_configured()
    True

    Conditional setup in applications:

    >>> if not is_logging_configured():
    ...     setup_logging(level=logging.WARNING)

    See Also
    --------
    setup_logging : Configure depkeeper logging
    disable_logging : Disable and reset logging configuration
    """
    return _logging_configured


def disable_logging() -> None:
    """Disable all depkeeper logging output.

    This function removes all handlers from the depkeeper logger and replaces
    them with a NullHandler, effectively silencing all log output. This is
    primarily useful for testing or when you need to suppress depkeeper's
    internal logging in your application.

    The function also resets the module's configuration state, so
    `is_logging_configured()` will return False after calling this function.

    Returns
    -------
    None

    Examples
    --------
    Disable logging after it has been set up:

    >>> from depkeeper.utils.logger import setup_logging, disable_logging, get_logger
    >>> import logging
    >>> setup_logging(level=logging.DEBUG)
    >>> logger = get_logger()
    >>> logger.info("This will be shown")
    INFO: This will be shown
    >>> disable_logging()
    >>> logger.info("This will not be shown")

    Use in test fixtures to suppress output:

    >>> import pytest
    >>> from depkeeper.utils.logger import disable_logging
    >>>
    >>> @pytest.fixture(autouse=True)
    ... def suppress_logging():
    ...     disable_logging()
    ...     yield
    ...     # Cleanup after test

    Temporarily disable logging:

    >>> from depkeeper.utils.logger import setup_logging, disable_logging
    >>> import logging
    >>> setup_logging(level=logging.INFO)
    >>> # ... do some work with logging ...
    >>> disable_logging()
    >>> # ... do work without logging ...
    >>> setup_logging(level=logging.INFO)
    >>> # ... logging re-enabled ...

    Notes
    -----
    This function modifies the global state of the 'depkeeper' logger. After
    calling this function:

    - All existing handlers are removed
    - A NullHandler is added (suppresses all output)
    - The logger level is reset to NOTSET
    - The `_logging_configured` flag is set to False

    To re-enable logging, call `setup_logging()` again.

    See Also
    --------
    setup_logging : Configure depkeeper logging
    is_logging_configured : Check if logging has been configured
    get_logger : Get a logger instance
    """
    global _logging_configured

    with _lock:
        root_logger = logging.getLogger("depkeeper")
        root_logger.handlers.clear()
        root_logger.addHandler(logging.NullHandler())
        root_logger.setLevel(logging.NOTSET)

        _logging_configured = False
