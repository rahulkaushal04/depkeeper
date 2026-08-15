"""Centralized constants for depkeeper.

Defines the immutable configuration values used across depkeeper, including
network settings, file patterns, pip directives, encodings, and logging
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

#: Upper bound (in seconds) on how long a ``429`` response's ``Retry-After``
#: value may delay the client, regardless of what the server sends.
MAX_RETRY_AFTER_SECONDS: Final[int] = 120

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

#: Pip global options allowed in requirements files (long and short forms).
#: These apply to pip invocation and are not package requirements.
PIP_GLOBAL_OPTIONS_WITH_VALUES: Final[Sequence[str]] = (
    "--index-url",
    "--extra-index-url",
    "--find-links",
    "--trusted-host",
    "--no-binary",
    "--only-binary",
    "--use-feature",
    "-i",
    "-f",
)

#: Pip global option flags that do not take values.
PIP_GLOBAL_OPTIONS_NO_VALUES: Final[Sequence[str]] = (
    "--pre",
    "--prefer-binary",
)

# ---------------------------------------------------------------------------
# Security constraints
# ---------------------------------------------------------------------------

#: Maximum allowed file size (in bytes) when reading requirement files.
MAX_FILE_SIZE: Final[int] = 10 * 1024 * 1024  # 10 MB

# ---------------------------------------------------------------------------
# File encoding
# ---------------------------------------------------------------------------

#: Encoding used when reading text files. ``utf-8-sig`` decodes plain UTF-8
#: identically to ``utf-8`` but additionally removes a leading byte order mark,
#: which Windows editors (Notepad, PowerShell ``Set-Content``) prepend.
DEFAULT_READ_ENCODING: Final[str] = "utf-8-sig"

#: Encoding used when writing text files. Never emits a byte order mark.
DEFAULT_WRITE_ENCODING: Final[str] = "utf-8"

#: Encoding used to rewrite a file that originally carried a UTF-8 BOM, so the
#: byte order mark is preserved rather than silently dropped.
BOM_WRITE_ENCODING: Final[str] = "utf-8-sig"

#: The Unicode byte order mark character, as produced by decoding a UTF-8 BOM
#: with a non-BOM-aware codec.
BOM_CHARACTER: Final[str] = "\ufeff"

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

#: Timestamp format for verbose logging.
LOG_DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"

#: Default log format (non-verbose).
LOG_DEFAULT_FORMAT: Final[str] = "%(levelname)s: %(message)s"

#: Verbose log format including timestamp and logger name.
LOG_VERBOSE_FORMAT: Final[str] = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------

#: Default setting for dependency conflict checking.
DEFAULT_CHECK_CONFLICTS: Final[bool] = True

#: Default setting for strict version matching (only exact pins).
DEFAULT_STRICT_VERSION_MATCHING: Final[bool] = False
