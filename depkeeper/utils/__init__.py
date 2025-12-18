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
    get_logger,
    setup_logging,
    disable_logging,
    is_logging_configured,
)
from depkeeper.utils.console import (
    confirm,
    get_raw_console,
    print_dim,
    print_error,
    print_highlight,
    print_info,
    print_success,
    print_table,
    print_warning,
    reconfigure_console,
)
from depkeeper.utils.progress import (
    ProgressTracker,
    create_spinner,
    create_progress,
)
from depkeeper.utils.http import (
    HTTPClient,
)

__all__ = [
    # Console
    "confirm",
    "print_info",
    "print_error",
    "print_table",
    "print_success",
    "print_warning",
    "get_raw_console",
    "create_progress_bar",
    "reconfigure_console",
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
    # HTTP
    "HTTPClient",
    # Progress
    "ProgressTracker",
    "create_spinner",
    "create_progress",
]
