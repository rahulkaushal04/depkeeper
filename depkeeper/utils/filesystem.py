"""
Filesystem utilities for depkeeper.

This module provides safe helpers for reading, writing, backing up,
restoring, and discovering requirement-related files. All filesystem
errors are normalized to ``FileOperationError``.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from uuid import uuid4
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Union

from depkeeper.utils.logger import get_logger
from depkeeper.exceptions import FileOperationError
from depkeeper.constants import MAX_FILE_SIZE, REQUIREMENT_FILE_PATTERNS


logger = get_logger("filesystem")

PathLike = Union[str, Path]


def _validated_file(path: Path, *, must_exist: bool = True) -> Path:
    """Validate and resolve a file path."""
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
    """Atomically write text to a file using a temporary file + replace."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Optional[Path] = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=str(target.parent),
            delete=False,
            prefix=f".{target.name}.",
            suffix=".tmp",
        ) as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
            temp_path = Path(tmp.name)

        temp_path.replace(target)

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
    """Create a timestamped backup of a file."""
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
    """Restore a file from a backup."""
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
    encoding: str = "utf-8",
) -> str:
    """Safely read a text file with optional size limits.

    Args:
        file_path: Path to the file.
        max_size: Maximum allowed file size in bytes (None disables limit).
        encoding: Text encoding.

    Returns:
        File contents as a string.
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
) -> Optional[Path]:
    """Safely write text to a file using atomic replacement.

    Args:
        file_path: Destination path.
        content: Text content to write.
        create_backup: Whether to create a backup before writing.

    Returns:
        Path to the created backup, if any.
    """
    path = Path(file_path)
    backup: Optional[Path] = None

    if create_backup and path.exists() and path.is_file():
        backup = _create_backup_internal(path)

    try:
        _atomic_write(path, content)
    except Exception:
        if backup and backup.exists():
            try:
                _restore_backup_internal(backup, path)
            except Exception:
                pass
        raise

    return backup


def create_backup(file_path: PathLike) -> Path:
    """Create a timestamped backup of a file."""
    return _create_backup_internal(_validated_file(Path(file_path)))


def restore_backup(
    backup_path: PathLike,
    target_path: Optional[PathLike] = None,
) -> None:
    """Restore a file from a backup.

    If ``target_path`` is not provided, the original filename is inferred
    from the backup name.
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
    """Find requirement files within a directory."""
    root = Path(directory).resolve()
    if not root.is_dir():
        return []

    patterns = REQUIREMENT_FILE_PATTERNS["requirements"]

    if not recursive:
        # Only root-level patterns (no directory components)
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
    """
    Resolve and validate a filesystem path in a cross-platform safe way.

    If ``base_dir`` is provided, the resolved path must be located within
    the resolved base directory. Otherwise, a ``FileOperationError`` is raised.
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
    """Create a timestamped backup with format:
    ``{stem}.{timestamp}.backup{suffix}``.
    """
    path = Path(file_path)

    if not path.exists() or not path.is_file():
        raise FileOperationError(
            f"Cannot backup invalid file: {path}",
            file_path=str(path),
            operation="backup",
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = path.parent / f"{path.stem}.{timestamp}.backup{path.suffix}"

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
