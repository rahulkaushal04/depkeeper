"""
Centralized constants for depkeeper.

This module defines immutable configuration defaults, API endpoints,
environment limits, regex patterns, file conventions, and enums used
across the depkeeper codebase.

All values here MUST remain pure constants — no imports from internal
modules (to avoid circular imports).
"""

from enum import Enum
from typing import Final, Tuple, Dict, List

# =============================================================================
# Project Metadata
# =============================================================================

# Populated dynamically at runtime using depkeeper.__version__
USER_AGENT_TEMPLATE: Final[str] = (
    "depkeeper/{version} (https://github.com/rahulkaushal04/depkeeper)"
)

# =============================================================================
# PyPI Endpoints
# =============================================================================

PYPI_JSON_API: Final[str] = "https://pypi.org/pypi/{package}/json"
PYPI_SIMPLE_API: Final[str] = "https://pypi.org/simple/{package}/"
PYPI_BASE_URL: Final[str] = "https://pypi.org"

# =============================================================================
# Cache Configuration
# =============================================================================

DEFAULT_CACHE_TTL: Final[int] = 3600  # 1 hour
DEFAULT_CACHE_DIR: Final[str] = "~/.cache/depkeeper"
CACHE_DB_NAME: Final[str] = "cache.db"

# =============================================================================
# HTTP Configuration
# =============================================================================

DEFAULT_CONCURRENT_REQUESTS: Final[int] = 10
DEFAULT_TIMEOUT: Final[int] = 30  # seconds
DEFAULT_MAX_RETRIES: Final[int] = 3
DEFAULT_RETRY_DELAY: Final[int] = 1  # seconds

# User agent is dynamically formatted by clients when sending requests
HTTP_USER_AGENT: Final[str] = USER_AGENT_TEMPLATE

# =============================================================================
# Supported Python Versions
# =============================================================================

SUPPORTED_PYTHON_VERSIONS: Final[Tuple[str, ...]] = (
    "3.8",
    "3.9",
    "3.10",
    "3.11",
    "3.12",
    "3.13",
)

# =============================================================================
# File Patterns & Directives
# =============================================================================

REQUIREMENT_FILE_PATTERNS: Final[Dict[str, List[str]]] = {
    "requirements": [
        "requirements.txt",
        "requirements-*.txt",
        "requirements/*.txt",
    ],
    "constraints": [
        "constraints.txt",
        "constraints-*.txt",
    ],
    "backup": ["*.backup"],
}

# PEP 508 Directives (short and long forms)
INCLUDE_DIRECTIVE: Final[str] = "-r"
INCLUDE_DIRECTIVE_LONG: Final[str] = "--requirement"
CONSTRAINT_DIRECTIVE: Final[str] = "-c"
CONSTRAINT_DIRECTIVE_LONG: Final[str] = "--constraint"
EDITABLE_DIRECTIVE: Final[str] = "-e"
EDITABLE_DIRECTIVE_LONG: Final[str] = "--editable"
HASH_DIRECTIVE: Final[str] = "--hash"

# =============================================================================
# Update Strategies
# =============================================================================


class UpdateStrategy(str, Enum):
    """Package update strategy."""

    CONSERVATIVE = "conservative"  # Patch only
    MODERATE = "moderate"  # Minor updates
    AGGRESSIVE = "aggressive"  # Major updates
    CUSTOM = "custom"  # Per-package rules

    def __str__(self) -> str:
        return self.value


# =============================================================================
# Version Operators (PEP 440)
# =============================================================================


class VersionOperator(str, Enum):
    """PEP 440 version comparison operators."""

    EQUAL = "=="
    NOT_EQUAL = "!="
    LESS_THAN = "<"
    LESS_THAN_EQUAL = "<="
    GREATER_THAN = ">"
    GREATER_THAN_EQUAL = ">="
    COMPATIBLE = "~="
    ARBITRARY_EQUAL = "==="

    def __str__(self) -> str:
        return self.value


# =============================================================================
# Exit Codes
# =============================================================================


class ExitCode(int, Enum):
    """Standard CLI exit codes."""

    SUCCESS = 0
    GENERAL_ERROR = 1
    PARSE_ERROR = 2
    NETWORK_ERROR = 3
    VALIDATION_ERROR = 4
    CONFLICT_ERROR = 5
    FILE_ERROR = 6
    SECURITY_VULNERABILITY = 10

    def __int__(self) -> int:
        return self.value


# =============================================================================
# Logging Defaults
# =============================================================================

LOG_FORMAT: Final[str] = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"
DEFAULT_LOG_LEVEL: Final[str] = "INFO"

# =============================================================================
# Versioning Patterns
# =============================================================================

# Semantic Versioning (SemVer)
SEMVER_PATTERN: Final[str] = (
    r"^(\d+)\.(\d+)\.(\d+)(?:-([a-zA-Z0-9.]+))?(?:\+([a-zA-Z0-9.]+))?$"
)

# Calendar Versioning (CalVer)
CALVER_PATTERNS: Final[List[str]] = [
    r"^\d{4}\.\d{1,2}\.\d{1,2}",  # YYYY.MM.DD
    r"^\d{2}\.\d{1,2}",  # YY.MM
]

# =============================================================================
# Security Constraints
# =============================================================================

MAX_FILE_SIZE: Final[int] = 10 * 1024 * 1024  # 10 MB

ALLOWED_URL_SCHEMES: Final[Tuple[str, ...]] = (
    "http",
    "https",
    "git+https",
    "git+ssh",
)

# =============================================================================
# Progress Display
# =============================================================================

PROGRESS_UPDATE_INTERVAL: Final[float] = 0.1  # seconds
PROGRESS_BAR_WIDTH: Final[int] = 40

# =============================================================================
# PEP 503 Package Normalization
# =============================================================================

PACKAGE_NAME_NORMALIZE_PATTERN: Final[str] = r"[-_.]+"
PACKAGE_NAME_NORMALIZE_REPLACEMENT: Final[str] = "-"
