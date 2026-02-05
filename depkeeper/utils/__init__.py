"""
Utility helpers for depkeeper.

This package provides reusable utilities used across depkeeper, including:

- Console output helpers (Rich-based)
- Logging configuration and retrieval
- Filesystem safety helpers
- Async HTTP client utilities
- Version comparison helpers

Only symbols listed in ``__all__`` are considered part of the public API.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Filesystem utilities
# ---------------------------------------------------------------------------

from depkeeper.utils.filesystem import (
    create_backup,
    create_timestamped_backup,
    find_requirements_files,
    restore_backup,
    safe_read_file,
    safe_write_file,
    validate_path,
)

# ---------------------------------------------------------------------------
# Logging utilities
# ---------------------------------------------------------------------------

from depkeeper.utils.logger import (
    disable_logging,
    get_logger,
    is_logging_configured,
    setup_logging,
)

# ---------------------------------------------------------------------------
# Console utilities
# ---------------------------------------------------------------------------

from depkeeper.utils.console import (
    colorize_update_type,
    confirm,
    get_raw_console,
    print_error,
    print_success,
    print_table,
    print_warning,
    reconfigure_console,
)

# ---------------------------------------------------------------------------
# HTTP utilities
# ---------------------------------------------------------------------------

from depkeeper.utils.http import HTTPClient

# ---------------------------------------------------------------------------
# Version utilities
# ---------------------------------------------------------------------------

from depkeeper.utils.version_utils import get_update_type

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # Console
    "confirm",
    "print_error",
    "print_table",
    "print_success",
    "print_warning",
    "get_raw_console",
    "reconfigure_console",
    "colorize_update_type",
    # Logging
    "get_logger",
    "setup_logging",
    "disable_logging",
    "is_logging_configured",
    # Filesystem
    "safe_read_file",
    "safe_write_file",
    "create_backup",
    "restore_backup",
    "find_requirements_files",
    "validate_path",
    "create_timestamped_backup",
    # HTTP
    "HTTPClient",
    # Version utilities
    "get_update_type",
]
