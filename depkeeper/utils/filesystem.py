from __future__ import annotations


import shutil
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional, List

from depkeeper.exceptions import FileOperationError
from depkeeper.constants import REQUIREMENT_FILE_PATTERNS, MAX_FILE_SIZE


# ============================================================================
# Internal Helpers
# ============================================================================


def _validated_file(path: Path, *, must_exist: bool = True) -> Path:
    """Validate and normalize file path with clear error formatting."""
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
    """
    Atomically write content to a file.

    Creates the file via a temporary file in the same directory, then moves it.
    """
    target.parent.mkdir(parents=True, exist_ok=True)

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
            temp_path = Path(tmp.name)

        shutil.move(str(temp_path), str(target))

    except Exception as exc:
        # Attempt cleanup of temp file if present
        try:
            if "temp_path" in locals() and temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass

        raise FileOperationError(
            f"Atomic write failed: {exc}",
            file_path=str(target),
            operation="write",
            original_error=exc,
        ) from exc


def _create_backup_internal(path: Path) -> Path:
    """Create a timestamped backup file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
    """Restore file from backup."""
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
    file_path: str | Path,
    *,
    max_size: Optional[int] = MAX_FILE_SIZE,
    encoding: str = "utf-8",
) -> str:
    """
    Safely read a file with size checks and clear error messages.

    Raises:
        FileOperationError if:
          - The file is missing
          - The file is not a regular file
          - The file exceeds MAX_FILE_SIZE
          - Cannot be read due to IO errors
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
    file_path: str | Path,
    content: str,
    *,
    create_backup: bool = True,
) -> Optional[Path]:
    """
    Safely write content to a file using atomic operations.

    If `create_backup=True`, a timestamped backup is created before writing.

    Returns:
        Optional[Path]: Path to the backup file if created, otherwise None.

    Raises:
        FileOperationError on any IO failure.
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


def create_backup(file_path: str | Path) -> Path:
    """
    Manually create a timestamped backup of a file.
    """
    return _create_backup_internal(_validated_file(Path(file_path)))


def restore_backup(
    backup_path: str | Path,
    target_path: Optional[str | Path] = None,
) -> None:
    """
    Restore a file from a given backup.

    If target_path is None:
      - Removes the trailing '.backup*' suffix to infer the original path.
    """
    backup = Path(backup_path)

    if not backup.exists():
        raise FileOperationError(
            f"Backup file not found: {backup}",
            file_path=str(backup),
            operation="restore",
        )

    if target_path:
        target = Path(target_path)
    else:
        name = str(backup)
        if ".backup" not in name:
            raise FileOperationError(
                f"Cannot infer target path from backup: {backup}",
                file_path=str(backup),
                operation="restore",
            )
        name_without_backup = name[: name.rfind(".backup")]
        parts = name_without_backup.rsplit(".", 1)
        if len(parts) == 2 and len(parts[1]) == 15 and "_" in parts[1]:
            target = Path(parts[0])
        else:
            target = Path(name_without_backup)

    _restore_backup_internal(backup, target)


def find_requirements_files(
    directory: str | Path = ".",
    *,
    recursive: bool = True,
) -> List[Path]:
    """
    Discover requirement files within a directory tree.

    Patterns come from FILE_PATTERNS["requirements"] and
    include variants such as:

      - requirements.txt
      - requirements/*.txt
      - requirements-*.txt

    Returns:
        Sorted list of unique Path objects.
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


def validate_path(
    path: str | Path,
    base_dir: Optional[str | Path] = None,
) -> Path:
    """
    Validate and canonicalize a path.

    Prevents:
      • Invalid filesystem paths
      • Path traversal when base_dir is provided

    Returns:
        Canonical, absolute path.

    Raises:
        FileOperationError if invalid or outside base_dir.
    """
    try:
        resolved = Path(path).expanduser().resolve()
    except Exception as exc:
        raise FileOperationError(
            f"Invalid path: {path}",
            file_path=str(path),
            operation="validate",
            original_error=exc,
        ) from exc

    if base_dir:
        base = Path(base_dir).resolve()
        try:
            resolved.relative_to(base)
        except Exception as exc:
            raise FileOperationError(
                f"Path outside allowed base directory: {resolved}",
                file_path=str(path),
                operation="validate",
                original_error=exc,
            ) from exc

    return resolved
