"""Filesystem utilities for depkeeper.

Provides safe helpers for reading, writing, backing up, restoring, and
discovering requirement-related files. Writes are atomic and all filesystem
errors are normalized to :class:`~depkeeper.exceptions.FileOperationError`.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from uuid import uuid4
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Union

from depkeeper.utils.logger import get_logger
from depkeeper.exceptions import FileOperationError
from depkeeper.constants import (
    DEFAULT_READ_ENCODING,
    DEFAULT_WRITE_ENCODING,
    MAX_FILE_SIZE,
    REQUIREMENT_FILE_PATTERNS,
)


logger = get_logger("filesystem")

PathLike = Union[str, Path]


def _validated_file(path: Path, *, must_exist: bool = True) -> Path:
    """Resolve *path*, optionally asserting that it is an existing file.

    Raises:
        FileOperationError: *must_exist* is set and the path is missing or is
            not a regular file.
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


def _replace_with_retry(source: Path, target: Path, *, attempts: int = 5) -> None:
    """Rename *source* over *target*, retrying transient lock errors.

    On Windows ``os.replace`` raises ``PermissionError`` while another process
    (typically an antivirus scanner or the search indexer) briefly holds a
    handle on the freshly created temporary file or on the destination. The
    condition clears in milliseconds, so a short bounded backoff turns a
    spurious failure into a successful write. Any other error, and a lock that
    outlives every attempt, propagates unchanged.

    Args:
        source: Temporary file to move.
        target: Destination path.
        attempts: Maximum number of attempts.
    """
    delay = 0.05

    for attempt in range(1, attempts + 1):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt == attempts:
                raise
            logger.debug(
                "Replace of %s blocked (attempt %d/%d); retrying",
                target,
                attempt,
                attempts,
            )
            time.sleep(delay)
            delay *= 2


def _fsync_directory(directory: Path) -> None:
    """Best-effort ``fsync`` of a directory so a rename survives a crash."""
    # Directories cannot be opened for reading on Windows.
    if os.name != "posix":
        return

    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError as exc:
        logger.debug("Could not open %s for fsync: %s", directory, exc)
        return

    try:
        os.fsync(fd)
    except OSError as exc:
        logger.debug("Directory fsync failed for %s: %s", directory, exc)
    finally:
        os.close(fd)


def _atomic_write(
    target: Path,
    content: str,
    *,
    encoding: str = DEFAULT_WRITE_ENCODING,
) -> None:
    """Atomically write text to a file using a temporary file + replace.

    The content is written to a temporary file in the destination directory,
    flushed and ``fsync``-ed, then moved over the target with
    :meth:`Path.replace` (``os.replace``), which is atomic on POSIX and
    Windows. A reader therefore never observes a truncated file, and an
    interrupted write leaves the original file untouched.

    Args:
        target: Destination path.
        content: Text to write. Line endings are written verbatim.
        encoding: Text encoding. Pass ``utf-8-sig`` to emit a byte order mark.
    """
    # Replace the file a symlink points at, rather than the symlink itself.
    if target.is_symlink():
        target = Path(os.path.realpath(target))

    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Optional[Path] = None

    try:
        # ``newline=""`` disables newline translation, so CRLF/LF endings in
        # *content* reach the disk byte-for-byte on every platform.
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            newline="",
            dir=str(target.parent),
            delete=False,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        # Bind the path before the first write so cleanup can always reach it.
        temp_path = Path(tmp.name)

        with tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())

        if target.exists():
            # NamedTemporaryFile creates 0600; keep the original file's mode.
            shutil.copymode(target, temp_path)

        _replace_with_retry(temp_path, target)
        _fsync_directory(target.parent)
    except Exception as exc:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
                logger.debug("Cleaned up temporary file: %s", temp_path)
            except Exception as cleanup_exc:
                logger.warning(
                    "Failed to clean up temporary file %s: %s",
                    temp_path,
                    cleanup_exc,
                )

        raise FileOperationError(
            f"Atomic write failed: {exc}",
            file_path=str(target),
            operation="write",
            original_error=exc,
        ) from exc


def _create_backup_internal(path: Path) -> Path:
    """Copy *path* to a sibling ``<name><suffix>.<timestamp>_<uuid>.backup``.

    The random suffix makes concurrent backups of the same file collision-free
    even within the same microsecond.

    Raises:
        FileOperationError: The copy failed.
    """
    unique = uuid4().hex[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = path.with_suffix(f"{path.suffix}.{timestamp}_{unique}.backup")

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
    """Copy *backup* over *target*, preserving metadata.

    Raises:
        FileOperationError: The copy failed.
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


def safe_read_file(
    file_path: PathLike,
    *,
    max_size: Optional[int] = MAX_FILE_SIZE,
    encoding: str = DEFAULT_READ_ENCODING,
) -> str:
    """Safely read a text file with optional size limits.

    The default encoding is ``utf-8-sig``, which decodes plain UTF-8 exactly
    like ``utf-8`` but also strips a leading byte order mark. Without this,
    the BOM survives as a ``\\ufeff`` character at the start of the first line
    (``str.strip()`` does not remove it) and corrupts the first token of the
    file. Pass ``encoding="utf-8"`` explicitly to retain the BOM.

    Args:
        file_path: Path to the file.
        max_size: Maximum allowed file size in bytes (None disables limit).
            Measured in bytes on disk, so a BOM counts toward the limit.
        encoding: Text encoding.

    Returns:
        File contents as a string, without a leading byte order mark.

    Raises:
        FileOperationError: The file is missing, is not a regular file,
            exceeds *max_size*, or cannot be decoded.
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
        return path.read_text(encoding=encoding)
    except Exception as exc:
        raise FileOperationError(
            f"Failed to read file: {exc}",
            file_path=str(path),
            operation="read",
            original_error=exc,
        ) from exc


def safe_write_file(
    file_path: PathLike,
    content: str,
    *,
    create_backup: bool = True,
    encoding: str = DEFAULT_WRITE_ENCODING,
) -> Optional[Path]:
    """Safely write text to a file using atomic replacement.

    The write is atomic: the content lands in a temporary file that is
    ``fsync``-ed and then renamed over the destination, so the destination is
    never left truncated or half-written. Line endings in *content* are
    preserved exactly.

    Args:
        file_path: Destination path.
        content: Text content to write.
        create_backup: Whether to create a backup before writing.
        encoding: Text encoding. Use ``utf-8-sig`` to re-emit a byte order
            mark for files that originally carried one.

    Returns:
        Path to the created backup, if any.

    Raises:
        FileOperationError: The write failed. Any backup taken beforehand is
            restored over the destination on a best-effort basis first.
    """
    path = Path(file_path)
    backup: Optional[Path] = None

    if create_backup and path.exists() and path.is_file():
        backup = _create_backup_internal(path)

    try:
        _atomic_write(path, content, encoding=encoding)
    except Exception:
        if backup and backup.exists():
            try:
                _restore_backup_internal(backup, path)
            except Exception:
                pass
        raise

    return backup


def create_backup(file_path: PathLike) -> Path:
    """Create a timestamped backup of an existing file.

    Args:
        file_path: File to copy.

    Returns:
        Path to the new backup file.

    Raises:
        FileOperationError: The source does not exist, is not a regular file,
            or the copy failed.
    """
    return _create_backup_internal(_validated_file(Path(file_path)))


def restore_backup(
    backup_path: PathLike,
    target_path: Optional[PathLike] = None,
) -> None:
    """Restore a file from a backup created by :func:`create_backup`.

    When *target_path* is omitted the original name is recovered from the
    backup name by dropping the ``.backup`` extension and the trailing
    ``.<timestamp>_<uuid>`` segment.

    Args:
        backup_path: Backup file to restore from.
        target_path: Explicit destination. Required for backups whose name
            does not follow the generated convention.

    Raises:
        FileOperationError: The backup is missing, the destination cannot be
            inferred, or the copy failed.
    """
    backup = Path(backup_path)

    if not backup.exists():
        raise FileOperationError(
            f"Backup file not found: {backup}",
            file_path=str(backup),
            operation="restore",
        )

    if target_path is None:
        if not backup.name.endswith(".backup"):
            raise FileOperationError(
                f"Cannot infer restore target from backup: {backup}",
                file_path=str(backup),
                operation="restore",
            )

        base_name = backup.name[:-7]
        target = backup.parent / base_name.rsplit(".", 1)[0]
    else:
        target = Path(target_path)

    logger.debug("Restoring %s from backup %s", target, backup)
    _restore_backup_internal(backup, target)


def find_requirements_files(
    directory: PathLike = ".",
    *,
    recursive: bool = True,
) -> List[Path]:
    """Discover requirement files under a directory.

    Args:
        directory: Root to search. A non-directory yields an empty list.
        recursive: Search subdirectories as well. When ``False``, patterns
            containing a path separator are dropped.

    Returns:
        Sorted, de-duplicated list of matching paths.
    """
    root = Path(directory).resolve()
    if not root.is_dir():
        return []

    patterns = REQUIREMENT_FILE_PATTERNS["requirements"]

    if not recursive:
        patterns = [p for p in patterns if "/" not in p]

    matches: List[Path] = []

    for pattern in patterns:
        iterator = root.rglob(pattern) if recursive else root.glob(pattern)
        matches.extend(iterator)

    return sorted(set(matches))


def validate_path(
    path: PathLike,
    *,
    base_dir: Optional[PathLike] = None,
) -> Path:
    """Resolve a path and optionally confine it to a base directory.

    Resolution is non-strict, so paths that do not exist yet are accepted.
    Passing *base_dir* turns this into a path-traversal guard for values that
    originate outside the process.

    Args:
        path: Path to resolve. ``~`` is expanded; relative paths are taken
            against the current working directory.
        base_dir: When given, the resolved path must sit inside it.

    Returns:
        The absolute, resolved path.

    Raises:
        FileOperationError: The resolved path escapes *base_dir*.
    """
    p = Path(path).expanduser()

    if not p.is_absolute():
        p = Path.cwd() / p

    resolved = p.resolve(strict=False)

    if base_dir is not None:
        base = Path(base_dir).expanduser()

        if not base.is_absolute():
            base = Path.cwd() / base

        base = base.resolve(strict=False)

        try:
            resolved.relative_to(base)
        except ValueError as exc:
            raise FileOperationError(
                f"Path outside allowed base directory: {resolved}",
                file_path=str(path),
                operation="validate",
                original_error=exc,
            ) from exc

    return resolved


def create_timestamped_backup(file_path: PathLike) -> Path:
    """Create a backup named ``<stem>.<timestamp>_<uuid>.backup<suffix>``.

    Unlike :func:`create_backup`, the original suffix is kept last so the
    backup remains recognizable by extension (``requirements.txt`` backs up to
    ``requirements.<timestamp>_<uuid>.backup.txt``).

    Args:
        file_path: File to copy.

    Returns:
        Path to the new backup file.

    Raises:
        FileOperationError: The source is missing or not a regular file, or
            the copy failed.
    """
    path = Path(file_path)

    if not path.exists() or not path.is_file():
        raise FileOperationError(
            f"Cannot backup invalid file: {path}",
            file_path=str(path),
            operation="backup",
        )

    unique = uuid4().hex[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_name = f"{path.stem}.{timestamp}_{unique}.backup{path.suffix}"
    backup_path = path.with_name(backup_name)

    try:
        shutil.copy2(path, backup_path)
        logger.debug("Created timestamped backup: %s", backup_path)
        return backup_path
    except Exception as exc:
        raise FileOperationError(
            f"Failed to create backup: {exc}",
            file_path=str(path),
            operation="backup",
            original_error=exc,
        ) from exc
