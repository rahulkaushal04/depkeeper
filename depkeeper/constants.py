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

# =============================================================================
# HTTP Configuration
# =============================================================================

DEFAULT_TIMEOUT: Final[int] = 30  # seconds
DEFAULT_MAX_RETRIES: Final[int] = 3


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


# =============================================================================
# Logging Configuration
# =============================================================================

LOG_DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"
LOG_DEFAULT_FORMAT: Final[str] = "%(levelname)s: %(message)s"
LOG_VERBOSE_FORMAT: Final[str] = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
