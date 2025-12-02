"""
Utility modules for depkeeper.

This module provides convenient access to utility functions and classes for
logging, filesystem operations, and other common tasks. Importing from here
keeps user-facing imports clean and stable:

    from depkeeper.utils import get_logger, safe_read_file

As additional utility modules are added (cache, config, http, etc.),
they should be re-exported here to maintain a consistent public API.
"""

from __future__ import annotations

from depkeeper.utils.filesystem import (
    create_backup,
    find_requirements_files,
    restore_backup,
    safe_read_file,
    safe_write_file,
    validate_path,
)
from depkeeper.utils.logger import (
    get_console,
    get_logger,
    setup_logging,
    LoggerContext,
)

__all__ = [
    # Logging
    "setup_logging",
    "get_logger",
    "get_console",
    "LoggerContext",
    # Filesystem
    "safe_read_file",
    "safe_write_file",
    "create_backup",
    "restore_backup",
    "find_requirements_files",
    "validate_path",
]
