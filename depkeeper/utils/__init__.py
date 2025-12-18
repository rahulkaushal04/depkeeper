from __future__ import annotations

from depkeeper.utils.filesystem import (
    create_backup,
    find_requirements_files,
    restore_backup,
    safe_read_file,
    safe_write_file,
    validate_path,
    create_timestamped_backup,
)
from depkeeper.utils.logger import (
    get_logger,
    setup_logging,
    disable_logging,
    is_logging_configured,
)
from depkeeper.utils.console import (
    confirm,
    get_raw_console,
    print_error,
    print_info,
    print_success,
    print_table,
    print_warning,
    reconfigure_console,
    colorize_update_type,
)
from depkeeper.utils.progress import (
    ProgressTracker,
    create_spinner,
    create_progress,
)
from depkeeper.utils.http import (
    HTTPClient,
)
from depkeeper.utils.version_utils import get_update_type

__all__ = [
    # Console
    "confirm",
    "print_info",
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
    # Progress
    "ProgressTracker",
    "create_spinner",
    "create_progress",
    # Version utilities
    "get_update_type",
]
