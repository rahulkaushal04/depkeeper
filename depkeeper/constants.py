"""
Centralized constants for depkeeper.

This module defines immutable configuration values used across depkeeper,
including network settings, file patterns, CLI directives, and logging
formats. All values are intended to be treated as read-only.
"""

from typing import Final, Mapping, Sequence

# ---------------------------------------------------------------------------
# Project metadata
# ---------------------------------------------------------------------------

#: HTTP User-Agent template used for outbound requests.
USER_AGENT_TEMPLATE: Final[str] = (
    "depkeeper/{version} (https://github.com/rahulkaushal04/depkeeper)"
)

# ---------------------------------------------------------------------------
# PyPI endpoints
# ---------------------------------------------------------------------------

#: Base URL for the PyPI JSON API.
PYPI_JSON_API: Final[str] = "https://pypi.org/pypi/{package}/json"

# ---------------------------------------------------------------------------
# HTTP configuration
# ---------------------------------------------------------------------------

#: Default network timeout in seconds.
DEFAULT_TIMEOUT: Final[int] = 30

#: Maximum number of retries for failed HTTP requests.
DEFAULT_MAX_RETRIES: Final[int] = 3

# ---------------------------------------------------------------------------
# Requirement file patterns and directives
# ---------------------------------------------------------------------------

#: Glob patterns used to detect supported requirement-related files.
REQUIREMENT_FILE_PATTERNS: Final[Mapping[str, Sequence[str]]] = {
    "requirements": (
        "requirements.txt",
        "requirements-*.txt",
        "requirements/*.txt",
    ),
    "constraints": (
        "constraints.txt",
        "constraints-*.txt",
    ),
    "backup": ("*.backup",),
}

#: Short include directive for requirement files.
INCLUDE_DIRECTIVE: Final[str] = "-r"

#: Long include directive for requirement files.
INCLUDE_DIRECTIVE_LONG: Final[str] = "--requirement"

#: Short constraint directive.
CONSTRAINT_DIRECTIVE: Final[str] = "-c"

#: Long constraint directive.
CONSTRAINT_DIRECTIVE_LONG: Final[str] = "--constraint"

#: Short editable-install directive.
EDITABLE_DIRECTIVE: Final[str] = "-e"

#: Long editable-install directive.
EDITABLE_DIRECTIVE_LONG: Final[str] = "--editable"

#: Hash-checking directive.
HASH_DIRECTIVE: Final[str] = "--hash"

# ---------------------------------------------------------------------------
# Security constraints
# ---------------------------------------------------------------------------

#: Maximum allowed file size (in bytes) when reading requirement files.
MAX_FILE_SIZE: Final[int] = 10 * 1024 * 1024  # 10 MB

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

#: Timestamp format for verbose logging.
LOG_DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"

#: Default log format (non-verbose).
LOG_DEFAULT_FORMAT: Final[str] = "%(levelname)s: %(message)s"

#: Verbose log format including timestamp and logger name.
LOG_VERBOSE_FORMAT: Final[str] = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
