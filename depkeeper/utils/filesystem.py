"""Filesystem utilities for depkeeper.

This module provides safe, atomic file operations with comprehensive error
handling and backup management. All operations follow best practices for
file handling including atomic writes, automatic backups, and path validation
to prevent common filesystem errors and security issues.

The module is designed for managing requirements.txt files and related
configuration files, with built-in support for discovering requirement files
following common Python project conventions.

Examples
--------
Safe file reading with validation:

    >>> from depkeeper.utils.filesystem import safe_read_file
    >>> content = safe_read_file("requirements.txt")
    >>> print(content)

Atomic writes with automatic backup:

    >>> from depkeeper.utils.filesystem import safe_write_file
    >>> new_content = "requests>=2.28.0\\nclick>=8.0.0\\n"
    >>> backup = safe_write_file("requirements.txt", new_content)
    >>> print(f"Backup created at: {backup}")

Discover requirement files in a project:

    >>> from depkeeper.utils.filesystem import find_requirements_files
    >>> files = find_requirements_files(".", recursive=True)
    >>> for file in files:
    ...     print(file)
    requirements.txt
    requirements/dev.txt
    requirements/prod.txt

Backup management:

    >>> from depkeeper.utils.filesystem import list_backups, clean_old_backups
    >>> backups = list_backups("requirements.txt")
    >>> deleted = clean_old_backups("requirements.txt", keep=5)
    >>> print(f"Deleted {deleted} old backups")

Notes
-----
All file operations are designed to be atomic where possible, ensuring that
failures don't leave the filesystem in an inconsistent state. Temporary files
are used for writing and are automatically cleaned up on failure.

Path validation prevents directory traversal attacks and ensures paths stay
within expected boundaries when a base directory is specified.

See Also
--------
depkeeper.exceptions.FileOperationError : Custom exception for file errors
depkeeper.constants : Configuration constants including file size limits
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Union

from depkeeper.utils.logger import get_logger

from depkeeper.exceptions import FileOperationError
from depkeeper.constants import REQUIREMENT_FILE_PATTERNS, MAX_FILE_SIZE

logger = get_logger("filesystem")


def _validated_file(path: Path, *, must_exist: bool = True) -> Path:
    """Validate and normalize file path with clear error formatting.

    Internal helper function that validates a file path and returns its
    canonical form. Checks for file existence and type when required.

    Parameters
    ----------
    path : Path
        Path to validate and normalize.
    must_exist : bool, optional
        Whether the file must exist for validation to pass. If True,
        raises FileOperationError if file doesn't exist or isn't a
        regular file. Default is True.

    Returns
    -------
    Path
        Resolved, canonical path to the file.

    Raises
    ------
    FileOperationError
        If must_exist is True and the file doesn't exist or isn't a
        regular file.

    Notes
    -----
    This is an internal helper function not exposed in the public API.
    Uses Path.resolve() to get the canonical path, resolving all symlinks
    and relative path components.
    """
    if must_exist:
        if not path.exists():
            raise FileOperationError(
                f"File not found: {path}",
                file_path=str(path),
                operation="read",
            )

        if not path.is_file():
            raise FileOperationError(
                f"Not a file: {path}",
                file_path=str(path),
                operation="read",
            )

    return path.resolve()


def _atomic_write(target: Path, content: str) -> None:
    """Atomically write content to a file.

    Internal helper that implements atomic file writing using a temporary
    file followed by an atomic rename/replace operation. This ensures that
    the target file is never left in a partially written state, even if
    the process is interrupted.

    The temporary file is created in the same directory as the target to
    ensure it's on the same filesystem, which is required for atomic
    operations on most platforms.

    Parameters
    ----------
    target : Path
        Destination file path where content should be written.
    content : str
        Text content to write to the file.

    Returns
    -------
    None

    Raises
    ------
    FileOperationError
        If the write operation fails. The temporary file is automatically
        cleaned up on failure.

    Notes
    -----
    This is an internal helper function not exposed in the public API.

    The function:
    1. Creates parent directories if they don't exist
    2. Writes to a temporary file in the same directory
    3. Syncs the temporary file to disk (fsync)
    4. Atomically replaces the target file using Path.replace()
    5. Cleans up the temporary file on error

    The atomic replace operation (Path.replace()) works correctly on all
    platforms including Windows, where it uses the appropriate OS-level
    atomic file replacement mechanism.
    """
    target.parent.mkdir(parents=True, exist_ok=True)

    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(target.parent),
            delete=False,
            prefix=f".{target.name}.",
            suffix=".tmp",
        ) as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())  # Ensure data is written to disk
            temp_path = Path(tmp.name)

        temp_path.replace(target)

    except Exception as exc:
        # Attempt cleanup of temp file if present
        if temp_path is not None:
            try:
                if temp_path.exists():
                    temp_path.unlink()
                    logger.debug(f"Cleaned up temporary file: {temp_path}")
            except Exception as cleanup_exc:
                logger.warning(
                    f"Failed to clean up temporary file {temp_path}: {cleanup_exc}"
                )

        raise FileOperationError(
            f"Atomic write failed: {exc}",
            file_path=str(target),
            operation="write",
            original_error=exc,
        ) from exc


def _create_backup_internal(path: Path) -> Path:
    """Create a timestamped backup file.

    Internal helper that creates a backup copy of a file with a timestamp
    suffix. The backup preserves file metadata including modification times
    and permissions.

    Parameters
    ----------
    path : Path
        Path to the file to back up.

    Returns
    -------
    Path
        Path to the created backup file.

    Raises
    ------
    FileOperationError
        If the backup operation fails (e.g., permission denied, disk full).

    Notes
    -----
    This is an internal helper function not exposed in the public API.

    Backup filename format: {original}.{timestamp}.backup
    Example: requirements.txt.20231208_143022_123456.backup

    Uses shutil.copy2() to preserve file metadata during the copy operation.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = path.with_suffix(f"{path.suffix}.{timestamp}.backup")

    try:
        shutil.copy2(path, backup_path)
        return backup_path
    except Exception as exc:
        raise FileOperationError(
            f"Failed to create backup: {exc}",
            file_path=str(path),
            operation="backup",
            original_error=exc,
        ) from exc


def _restore_backup_internal(backup: Path, target: Path) -> None:
    """Restore file from backup.

    Internal helper that restores a file from a backup copy, preserving
    metadata.

    Parameters
    ----------
    backup : Path
        Path to the backup file.
    target : Path
        Path where the file should be restored.

    Returns
    -------
    None

    Raises
    ------
    FileOperationError
        If the restore operation fails.

    Notes
    -----
    This is an internal helper function not exposed in the public API.
    Uses shutil.copy2() to preserve file metadata during restoration.
    """
    try:
        shutil.copy2(backup, target)
    except Exception as exc:
        raise FileOperationError(
            f"Failed to restore backup: {exc}",
            file_path=str(target),
            operation="restore",
            original_error=exc,
        ) from exc


# ============================================================================
# Public API
# ============================================================================


def safe_read_file(
    file_path: Union[str, Path],
    *,
    max_size: Optional[int] = MAX_FILE_SIZE,
    encoding: str = "utf-8",
) -> str:
    """Safely read a file with size checks and clear error messages.

    Reads a file's contents with validation and safety checks. Prevents
    reading excessively large files that could cause memory issues, and
    provides clear error messages for common failure scenarios.

    Parameters
    ----------
    file_path : str or Path
        Path to the file to read. Can be absolute or relative.
    max_size : int, optional
        Maximum allowed file size in bytes. If the file exceeds this size,
        FileOperationError is raised. If None, no size check is performed.
        Default is MAX_FILE_SIZE from constants (typically 10 MB).
    encoding : str, optional
        Text encoding to use when reading the file. Default is "utf-8".
        Common alternatives: "latin-1", "ascii", "utf-16".

    Returns
    -------
    str
        The complete contents of the file as a string.

    Raises
    ------
    FileOperationError
        If any of the following conditions occur:
        - The file doesn't exist
        - The path points to a directory, not a file
        - The file size exceeds max_size
        - The file cannot be read (permission denied, encoding error, etc.)

    Examples
    --------
    Read a requirements file:

    >>> from depkeeper.utils.filesystem import safe_read_file
    >>> content = safe_read_file("requirements.txt")
    >>> print(content)
    requests>=2.28.0
    click>=8.0.0

    Read with custom size limit:

    >>> content = safe_read_file("large_file.txt", max_size=1_000_000)

    Read with different encoding:

    >>> content = safe_read_file("legacy.txt", encoding="latin-1")

    Handle errors gracefully:

    >>> from depkeeper.exceptions import FileOperationError
    >>> try:
    ...     content = safe_read_file("missing.txt")
    ... except FileOperationError as e:
    ...     print(f"Error: {e}")

    Notes
    -----
    The file is read entirely into memory as a string. For very large files,
    consider streaming approaches if the max_size check isn't sufficient.

    The function uses strict error handling for encoding issues, meaning
    any non-decodable bytes will raise an exception rather than being
    silently replaced.

    See Also
    --------
    safe_write_file : Safely write content to a file
    MAX_FILE_SIZE : Default maximum file size constant
    """
    path = _validated_file(Path(file_path))

    size = path.stat().st_size
    if max_size is not None and size > max_size:
        raise FileOperationError(
            f"File too large: {size} bytes (max {max_size})",
            file_path=str(path),
            operation="read",
        )

    try:
        return path.read_text(encoding=encoding, errors="strict")
    except Exception as exc:
        raise FileOperationError(
            f"Failed to read file: {exc}",
            file_path=str(path),
            operation="read",
            original_error=exc,
        ) from exc


def safe_write_file(
    file_path: Union[str, Path],
    content: str,
    *,
    create_backup: bool = True,
) -> Optional[Path]:
    """Safely write content to a file using atomic operations.

    Writes content to a file atomically, ensuring that the file is never
    left in a partially written state. Optionally creates a timestamped
    backup before writing, and automatically rolls back to the backup if
    the write operation fails.

    The atomic write is performed using a temporary file followed by an
    atomic rename operation, which is safe across process crashes and
    system failures on all supported platforms.

    Parameters
    ----------
    file_path : str or Path
        Path to the file to write. Can be absolute or relative. Parent
        directories are created automatically if they don't exist.
    content : str
        Text content to write to the file. Will be encoded as UTF-8.
    create_backup : bool, optional
        Whether to create a timestamped backup before writing. If True
        and the file already exists, a backup is created. If False or
        the file doesn't exist, no backup is created. Default is True.

    Returns
    -------
    Path or None
        Path to the backup file if a backup was created, None otherwise.
        The backup path includes a timestamp for unique identification.

    Raises
    ------
    FileOperationError
        If the write operation fails. If a backup exists, an automatic
        rollback is attempted before raising the exception.

    Examples
    --------
    Write with automatic backup:

    >>> from depkeeper.utils.filesystem import safe_write_file
    >>> content = "requests>=2.28.0\\nclick>=8.0.0\\n"
    >>> backup = safe_write_file("requirements.txt", content)
    >>> if backup:
    ...     print(f"Backup created: {backup}")
    Backup created: requirements.txt.20231208_143022_123456.backup

    Write without backup:

    >>> safe_write_file("new_file.txt", "content", create_backup=False)
    None

    Safe update with error handling:

    >>> from depkeeper.exceptions import FileOperationError
    >>> try:
    ...     backup = safe_write_file("requirements.txt", new_content)
    ...     print("Update successful")
    ... except FileOperationError as e:
    ...     print(f"Update failed: {e}")
    ...     # Original file is preserved or restored from backup

    Notes
    -----
    The function guarantees atomicity through the following process:

    1. If create_backup is True and file exists, create backup
    2. Write content to temporary file in same directory
    3. Sync temporary file to disk (fsync)
    4. Atomically replace target with temporary file
    5. On failure, attempt to restore from backup if it exists

    Parent directories are created automatically with mkdir(parents=True)
    if they don't exist.

    The backup filename format is: {original}.{timestamp}.backup
    Example: requirements.txt.20231208_143022_123456.backup

    See Also
    --------
    safe_read_file : Safely read a file
    create_backup : Manually create a backup
    restore_backup : Restore from a backup file
    """
    path = Path(file_path)
    backup: Optional[Path] = None

    if create_backup and path.exists() and path.is_file():
        backup = _create_backup_internal(path)

    try:
        _atomic_write(path, content)
    except Exception as exc:
        # Attempt rollback if backup exists
        if backup and backup.exists():
            try:
                _restore_backup_internal(backup, path)
            except Exception:
                pass
        raise

    return backup


def create_backup(file_path: Union[str, Path]) -> Path:
    """Manually create a timestamped backup of a file.

    Creates a backup copy of a file with a timestamp suffix. This is
    useful when you want to create a backup without immediately modifying
    the original file, or when you want explicit control over backup
    timing separate from write operations.

    Parameters
    ----------
    file_path : str or Path
        Path to the file to back up. The file must exist.

    Returns
    -------
    Path
        Path to the created backup file with timestamp suffix.

    Raises
    ------
    FileOperationError
        If the file doesn't exist, isn't a regular file, or the backup
        operation fails (e.g., permission denied, disk full).

    Examples
    --------
    Create a backup before manual modifications:

    >>> from depkeeper.utils.filesystem import create_backup
    >>> backup = create_backup("requirements.txt")
    >>> print(f"Backup created: {backup}")
    Backup created: requirements.txt.20231208_143022_123456.backup

    Create backups for multiple files:

    >>> files = ["requirements.txt", "setup.py", "pyproject.toml"]
    >>> backups = [create_backup(f) for f in files]

    Notes
    -----
    The backup preserves file metadata including modification times and
    permissions using shutil.copy2().

    Backup filename format: {original}.{timestamp}.backup
    The timestamp includes microseconds for uniqueness.

    See Also
    --------
    safe_write_file : Write file with automatic backup
    restore_backup : Restore from a backup
    list_backups : List all backups for a file
    """
    return _create_backup_internal(_validated_file(Path(file_path)))


def restore_backup(
    backup_path: Union[str, Path],
    target_path: Optional[Union[str, Path]] = None,
) -> None:
    """Restore a file from a backup.

    Restores a file from a backup copy. If target_path is not provided,
    the function attempts to infer the original file path from the backup
    filename by removing the timestamp and .backup suffix.

    Parameters
    ----------
    backup_path : str or Path
        Path to the backup file. The backup file must exist.
    target_path : str or Path, optional
        Path where the file should be restored. If None, the target is
        inferred from the backup filename by removing the timestamp and
        .backup suffix. For example:
        - requirements.txt.20231208_143022_123456.backup → requirements.txt
        Default is None.

    Returns
    -------
    None

    Raises
    ------
    FileOperationError
        If any of the following conditions occur:
        - The backup file doesn't exist
        - target_path is None and the target cannot be inferred (e.g.,
          backup filename doesn't end with .backup)
        - The restore operation fails (permission denied, disk full, etc.)

    Examples
    --------
    Restore to inferred original location:

    >>> from depkeeper.utils.filesystem import restore_backup
    >>> restore_backup("requirements.txt.20231208_143022_123456.backup")
    # Restores to requirements.txt

    Restore to custom location:

    >>> restore_backup(
    ...     "requirements.txt.20231208_143022_123456.backup",
    ...     "requirements_restored.txt"
    ... )

    Restore with string paths:

    >>> restore_backup("config.backup", "config.toml")

    Handle errors gracefully:

    >>> from depkeeper.exceptions import FileOperationError
    >>> try:
    ...     restore_backup("missing.backup")
    ... except FileOperationError as e:
    ...     print(f"Restore failed: {e}")

    Notes
    -----
    The function preserves file metadata including modification times
    and permissions using shutil.copy2().

    When inferring the target path, the function expects backup files
    to follow the format: {original}.{timestamp}.backup
    If the backup filename doesn't match this pattern, you must provide
    target_path explicitly.

    See Also
    --------
    create_backup : Create a backup of a file
    safe_write_file : Write file with automatic backup
    list_backups : List all backups for a file
    """
    backup = Path(backup_path)

    if not backup.exists():
        raise FileOperationError(
            f"Backup file not found: {backup}",
            file_path=str(backup),
            operation="restore",
        )

    # Infer target path if not provided
    if target_path is None:
        backup_name = backup.name
        if not backup_name.endswith(".backup"):
            raise FileOperationError(
                f"Cannot infer target path: backup filename must end with .backup: {backup}",
                file_path=str(backup),
                operation="restore",
            )

        # Remove .backup suffix
        without_backup_suffix = backup_name[:-7]  # Remove '.backup'

        # Remove timestamp (format: .YYYYMMDD_HHMMSS_ffffff)
        # Find the last occurrence of a pattern like .20231208_143022_123456
        parts = without_backup_suffix.rsplit(".", 1)
        if len(parts) == 2:
            # Check if the last part looks like a timestamp
            timestamp_part = parts[1]
            if len(timestamp_part) >= 15 and "_" in timestamp_part:
                # Looks like a timestamp, remove it
                target_name = parts[0]
            else:
                # Not a timestamp, keep as is
                target_name = without_backup_suffix
        else:
            # No extension before .backup
            target_name = without_backup_suffix

        target = backup.parent / target_name
    else:
        target = Path(target_path)

    logger.info(f"Restoring {target} from backup {backup}")
    _restore_backup_internal(backup, target)
    logger.info(f"Successfully restored {target}")


def find_requirements_files(
    directory: Union[str, Path] = ".",
    *,
    recursive: bool = True,
) -> List[Path]:
    """Discover requirement files within a directory tree.

    Searches for Python requirements files following common naming
    conventions and project structures. Uses predefined patterns from
    REQUIREMENT_FILE_PATTERNS to identify requirement files.

    Common patterns matched:
    - requirements.txt
    - requirements/*.txt
    - requirements-*.txt (e.g., requirements-dev.txt, requirements-test.txt)
    - *requirements.txt

    Parameters
    ----------
    directory : str or Path, optional
        Root directory to search for requirements files. Default is "."
        (current directory).
    recursive : bool, optional
        Whether to search recursively in subdirectories. If True, searches
        the entire directory tree. If False, only searches the specified
        directory. Default is True.

    Returns
    -------
    list[Path]
        Sorted list of unique Path objects pointing to discovered
        requirements files. Returns empty list if directory doesn't exist
        or no files are found.

    Examples
    --------
    Find all requirements files in current directory and subdirectories:

    >>> from depkeeper.utils.filesystem import find_requirements_files
    >>> files = find_requirements_files()
    >>> for file in files:
    ...     print(file)
    requirements.txt
    requirements/dev.txt
    requirements/prod.txt
    tests/requirements-test.txt

    Search only in specific directory without recursion:

    >>> files = find_requirements_files("requirements", recursive=False)
    >>> print(files)
    [Path('requirements/dev.txt'), Path('requirements/prod.txt')]

    Search in project root:

    >>> from pathlib import Path
    >>> project_root = Path.home() / "projects" / "myapp"
    >>> files = find_requirements_files(project_root)

    Notes
    -----
    The function returns an empty list if the specified directory doesn't
    exist or isn't a directory, rather than raising an exception.

    Duplicate paths are automatically removed, and results are sorted for
    consistent output.

    File patterns are defined in REQUIREMENT_FILE_PATTERNS constant and
    can be customized there if needed.

    See Also
    --------
    safe_read_file : Read discovered requirement files
    REQUIREMENT_FILE_PATTERNS : Pattern definitions in constants module
    """
    root = Path(directory).resolve()

    if not root.exists() or not root.is_dir():
        return []

    patterns = REQUIREMENT_FILE_PATTERNS["requirements"]
    discovered: List[Path] = []

    for pattern in patterns:
        matches = root.rglob(pattern) if recursive else root.glob(pattern)
        discovered.extend(matches)

    return sorted(set(discovered))


def list_backups(file_path: Union[str, Path]) -> List[Path]:
    """List all backup files for a given file.

    Finds and returns all backup files associated with a specific file,
    sorted by modification time (newest first). Backup files are identified
    by the naming pattern: {filename}.*.backup in the same directory.

    Parameters
    ----------
    file_path : str or Path
        Original file path to find backups for. The file itself doesn't
        need to exist; backups are identified by naming pattern in the
        same directory.

    Returns
    -------
    list[Path]
        Sorted list of backup file paths, ordered by modification time
        with newest backups first. Returns empty list if no backups found.

    Examples
    --------
    List all backups for a file:

    >>> from depkeeper.utils.filesystem import list_backups
    >>> backups = list_backups("requirements.txt")
    >>> for backup in backups:
    ...     print(backup)
    requirements.txt.20231208_143022_123456.backup
    requirements.txt.20231207_120000_654321.backup

    Check if any backups exist:

    >>> backups = list_backups("config.toml")
    >>> if backups:
    ...     print(f"Found {len(backups)} backup(s)")
    ...     print(f"Most recent: {backups[0]}")

    List backups for non-existent file:

    >>> backups = list_backups("deleted_file.txt")
    >>> print(backups)  # Returns empty list
    []

    Notes
    -----
    The function searches for files matching the pattern:
    {filename}.*.backup in the parent directory of the specified file.

    Backups are sorted by file modification time (st_mtime), not by the
    timestamp in the filename. This ensures accuracy even if file times
    are modified.

    The original file doesn't need to exist; backups are found based on
    the naming pattern alone.

    See Also
    --------
    create_backup : Create a new backup
    clean_old_backups : Remove old backup files
    restore_backup : Restore from a backup
    """
    path = Path(file_path)
    # Check in same directory even if file doesn't exist
    search_pattern = f"{path.name}.*.backup"

    backups = sorted(
        path.parent.glob(search_pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,  # Newest first
    )
    return backups


def clean_old_backups(
    file_path: Union[str, Path],
    keep: int = 5,
) -> int:
    """Remove old backup files, keeping only the most recent N backups.

    Automatically cleans up old backup files to prevent unlimited backup
    accumulation. Keeps the specified number of most recent backups and
    deletes older ones based on file modification time.

    Parameters
    ----------
    file_path : str or Path
        Original file path to clean backups for. The file itself doesn't
        need to exist; backups are identified by naming pattern.
    keep : int, optional
        Number of most recent backups to keep. Backups older than this
        count are deleted. Must be non-negative. Default is 5.

    Returns
    -------
    int
        Number of backup files successfully deleted.

    Examples
    --------
    Keep only 3 most recent backups:

    >>> from depkeeper.utils.filesystem import clean_old_backups
    >>> deleted = clean_old_backups("requirements.txt", keep=3)
    >>> print(f"Deleted {deleted} old backups")
    Deleted 2 old backups

    Clean all backups (keep=0):

    >>> deleted = clean_old_backups("requirements.txt", keep=0)
    >>> print(f"Deleted all {deleted} backups")

    Clean with default retention:

    >>> deleted = clean_old_backups("requirements.txt")  # Keeps 5

    Automated cleanup after operations:

    >>> from depkeeper.utils.filesystem import safe_write_file, clean_old_backups
    >>> # Create backup and write
    >>> safe_write_file("requirements.txt", new_content)
    >>> # Clean up old backups
    >>> clean_old_backups("requirements.txt", keep=3)

    Notes
    -----
    Backups are identified by the pattern: {filename}.*.backup in the
    same directory as the original file.

    Backups are sorted by modification time (newest first) before cleanup.
    If deletion of a backup fails (e.g., permission denied), a warning is
    logged but the function continues with remaining backups.

    The function logs an info message if any backups were deleted, and
    debug messages for individual deletions.

    The keep parameter can be 0 to delete all backups, which is useful
    for cleanup operations or when disk space is critical.

    See Also
    --------
    list_backups : List all backups for a file
    create_backup : Create a new backup
    safe_write_file : Write file with automatic backup creation
    """
    backups = list_backups(file_path)
    to_delete = backups[keep:]

    deleted = 0
    for backup in to_delete:
        try:
            backup.unlink()
            logger.debug(f"Deleted old backup: {backup}")
            deleted += 1
        except Exception as exc:
            logger.warning(f"Failed to delete backup {backup}: {exc}")

    if deleted > 0:
        logger.info(f"Cleaned up {deleted} old backup(s) for {file_path}")

    return deleted


def validate_path(
    path: Union[str, Path],
    base_dir: Optional[Union[str, Path]] = None,
) -> Path:
    """Validate and canonicalize a path.

    Validates and normalizes a filesystem path, optionally ensuring it
    stays within a specified base directory. This is crucial for security
    to prevent path traversal attacks and for ensuring paths are in
    expected locations.

    The function expands user home directories (~), resolves relative
    paths to absolute paths, and resolves symlinks to canonical paths.

    Parameters
    ----------
    path : str or Path
        Path to validate and canonicalize. Can be absolute, relative,
        or use ~ for user home directory.
    base_dir : str or Path, optional
        If provided, the path must be within this base directory (or a
        subdirectory). Used to prevent path traversal attacks. If None,
        no directory constraint is enforced. Default is None.

    Returns
    -------
    Path
        Canonical, absolute path that has been validated.

    Raises
    ------
    FileOperationError
        If base_dir is specified and the resolved path is outside the
        base directory.

    Examples
    --------
    Basic path validation:

    >>> from depkeeper.utils.filesystem import validate_path
    >>> path = validate_path("requirements.txt")
    >>> print(path)
    /home/user/project/requirements.txt

    Expand user home directory:

    >>> path = validate_path("~/projects/app/requirements.txt")
    >>> print(path)
    /home/user/projects/app/requirements.txt

    Prevent path traversal:

    >>> from depkeeper.exceptions import FileOperationError
    >>> try:
    ...     path = validate_path("../../../etc/passwd", base_dir="/home/user")
    ... except FileOperationError as e:
    ...     print(f"Blocked: {e}")
    Blocked: Path outside allowed base directory

    Validate paths within project directory:

    >>> project_dir = Path.cwd()
    >>> safe_path = validate_path("data/input.txt", base_dir=project_dir)

    Notes
    -----
    The function uses Path.resolve(strict=False), which means it doesn't
    require the path to exist. This allows validation of paths before
    file creation.

    When base_dir is provided, the function uses Path.relative_to() to
    verify the resolved path is within the base directory. This check
    occurs after full path resolution, so symlinks and .. components
    cannot be used to escape the base directory.

    Security implications: Always use base_dir when accepting user-provided
    paths that should be constrained to a specific directory tree.

    See Also
    --------
    safe_read_file : Read files with validation
    safe_write_file : Write files with validation
    """
    resolved = Path(path).expanduser().resolve(strict=False)

    if base_dir:
        base = Path(base_dir).resolve(strict=False)
        try:
            resolved.relative_to(base)
        except ValueError:
            raise FileOperationError(
                f"Path outside allowed base directory: {resolved}",
                file_path=str(path),
                operation="validate",
            )

    return resolved
