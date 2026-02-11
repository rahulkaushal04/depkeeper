from __future__ import annotations

import os
import sys
import pytest
from pathlib import Path
from typing import Generator
from unittest.mock import patch

from depkeeper.utils.filesystem import (
    _validated_file,
    _atomic_write,
    _create_backup_internal,
    _restore_backup_internal,
    safe_read_file,
    safe_write_file,
    create_backup,
    restore_backup,
    find_requirements_files,
    validate_path,
    create_timestamped_backup,
)
from depkeeper.exceptions import FileOperationError


def _can_create_symlinks() -> bool:
    """Check if the current environment supports symlink creation.

    On Windows, symlinks require admin privileges or developer mode.
    Returns False if symlink creation fails.
    """
    import tempfile

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target.txt"
            link = Path(tmpdir) / "link.txt"
            target.write_text("test")
            link.symlink_to(target)
            return True
    except (OSError, NotImplementedError):
        return False


SYMLINKS_SUPPORTED = _can_create_symlinks()


@pytest.fixture
def temp_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary directory for testing.

    Yields:
        Path: Temporary directory that's automatically cleaned up.
    """
    yield tmp_path


@pytest.fixture
def temp_file(temp_dir: Path) -> Path:
    """Create a temporary file with sample content.

    Returns:
        Path: Temporary file with "test content" written to it.
    """
    file_path = temp_dir / "test.txt"
    file_path.write_text("test content")
    return file_path


@pytest.fixture
def requirements_structure(temp_dir: Path) -> Path:
    """Create a directory structure with various requirements files.

    Creates a realistic project structure with:
    - requirements.txt in root
    - requirements-dev.txt in root
    - requirements/base.txt
    - requirements/test.txt
    - other non-requirements files

    Returns:
        Path: Root directory of the structure.
    """
    # Root level requirements
    (temp_dir / "requirements.txt").write_text("requests==2.28.0\n")
    (temp_dir / "requirements-dev.txt").write_text("pytest==7.0.0\n")
    (temp_dir / "requirements-test.txt").write_text("coverage==6.0\n")

    # Subdirectory requirements
    req_dir = temp_dir / "requirements"
    req_dir.mkdir()
    (req_dir / "base.txt").write_text("django==4.0\n")
    (req_dir / "test.txt").write_text("factory-boy==3.0\n")

    # Non-requirements files (should be ignored)
    (temp_dir / "README.md").write_text("# Project\n")
    (temp_dir / "setup.py").write_text("# setup\n")

    return temp_dir


@pytest.mark.unit
class TestValidatedFile:
    """Tests for _validated_file internal helper."""

    def test_validates_existing_file(self, temp_file: Path) -> None:
        """Test _validated_file accepts existing files.

        Happy path: Valid file should be returned as resolved path.
        """
        result = _validated_file(temp_file, must_exist=True)

        assert result.exists()
        assert result.is_file()
        assert result.is_absolute()

    def test_rejects_nonexistent_file(self, temp_dir: Path) -> None:
        """Test _validated_file rejects non-existent files.

        Should raise FileOperationError when file doesn't exist.
        """
        nonexistent = temp_dir / "does_not_exist.txt"

        with pytest.raises(FileOperationError) as exc_info:
            _validated_file(nonexistent, must_exist=True)

        assert "not found" in str(exc_info.value).lower()
        assert exc_info.value.file_path == str(nonexistent)
        assert exc_info.value.operation == "read"

    def test_rejects_directory(self, temp_dir: Path) -> None:
        """Test _validated_file rejects directories.

        Edge case: Directory paths should be rejected even if they exist.
        """
        with pytest.raises(FileOperationError) as exc_info:
            _validated_file(temp_dir, must_exist=True)

        assert "not a file" in str(exc_info.value).lower()

    def test_accepts_nonexistent_when_allowed(self, temp_dir: Path) -> None:
        """Test _validated_file accepts non-existent files when must_exist=False.

        Edge case: Should not raise when must_exist=False.
        """
        nonexistent = temp_dir / "future_file.txt"

        result = _validated_file(nonexistent, must_exist=False)

        assert result.is_absolute()

    @pytest.mark.skipif(not SYMLINKS_SUPPORTED, reason="Symlinks not supported")
    def test_resolves_symlink(self, temp_file: Path, temp_dir: Path) -> None:
        """Test _validated_file resolves symlinks.

        Edge case: Symlinks should be resolved to their target.
        """
        symlink = temp_dir / "link.txt"
        symlink.symlink_to(temp_file)

        result = _validated_file(symlink, must_exist=True)

        assert result.exists()
        assert result.is_file()

    def test_resolves_relative_path(self, temp_file: Path) -> None:
        """Test _validated_file converts relative to absolute paths.

        Should return absolute path even for relative input.
        """
        # Change to temp directory
        original_cwd = Path.cwd()
        try:
            os.chdir(temp_file.parent)
            relative_path = Path(temp_file.name)

            result = _validated_file(relative_path, must_exist=True)

            assert result.is_absolute()
            assert result.name == temp_file.name
        finally:
            os.chdir(original_cwd)


@pytest.mark.unit
class TestAtomicWrite:
    """Tests for _atomic_write internal helper."""

    def test_writes_content_atomically(self, temp_dir: Path) -> None:
        """Test _atomic_write creates file with correct content.

        Happy path: File should be created with exact content.
        """
        target = temp_dir / "output.txt"
        content = "Hello, World!"

        _atomic_write(target, content)

        assert target.exists()
        assert target.read_text(encoding="utf-8") == content

    def test_creates_parent_directories(self, temp_dir: Path) -> None:
        """Test _atomic_write creates missing parent directories.

        Should automatically create directory structure.
        """
        target = temp_dir / "subdir" / "nested" / "file.txt"

        _atomic_write(target, "content")

        assert target.exists()
        assert target.parent.exists()

    def test_overwrites_existing_file(self, temp_file: Path) -> None:
        """Test _atomic_write replaces existing file content.

        Should completely replace existing content.
        """
        original_content = temp_file.read_text()
        new_content = "New content"

        _atomic_write(temp_file, new_content)

        assert temp_file.read_text(encoding="utf-8") == new_content
        assert temp_file.read_text() != original_content

    def test_cleans_up_temp_file_on_success(self, temp_dir: Path) -> None:
        """Test _atomic_write removes temporary file after success.

        No .tmp files should remain after successful write.
        """
        target = temp_dir / "file.txt"

        _atomic_write(target, "content")

        # Check no .tmp files remain
        tmp_files = list(temp_dir.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_cleans_up_temp_file_on_failure(self, temp_dir: Path) -> None:
        """Test _atomic_write cleans up temp file on error.

        Edge case: Failed writes should not leave temp files behind.
        """
        target = temp_dir / "file.txt"

        # Make write fail by mocking replace to raise error
        with patch.object(Path, "replace", side_effect=OSError("Mock error")):
            with pytest.raises(FileOperationError):
                _atomic_write(target, "content")

        # Temp file should be cleaned up
        tmp_files = list(temp_dir.glob("*.tmp"))
        tmp_files.extend(temp_dir.glob(".*.tmp"))
        assert len(tmp_files) == 0

    def test_handles_write_permission_error(self, temp_dir: Path) -> None:
        """Test _atomic_write handles permission errors gracefully.

        Edge case: Should raise FileOperationError with details.
        """
        target = temp_dir / "readonly_dir" / "file.txt"
        target.parent.mkdir()

        # Make directory read-only (skip on Windows)
        if sys.platform != "win32":
            target.parent.chmod(0o444)

            try:
                with pytest.raises(FileOperationError) as exc_info:
                    _atomic_write(target, "content")

                assert exc_info.value.operation == "write"
                assert exc_info.value.file_path == str(target)
            finally:
                # Restore permissions for cleanup
                target.parent.chmod(0o755)

    def test_fsync_called(self, temp_dir: Path) -> None:
        """Test _atomic_write calls fsync to ensure data persistence.

        Should call os.fsync to flush data to disk.
        """
        target = temp_dir / "file.txt"

        with patch("os.fsync") as mock_fsync:
            _atomic_write(target, "content")

            # fsync should be called
            assert mock_fsync.call_count >= 1

    def test_unicode_content(self, tmp_path: Path) -> None:
        target = tmp_path / "unicode.txt"
        content = "Unicode test: ✓ α β γ ��"

        safe_write_file(target, content)

        assert target.exists()
        assert target.read_text(encoding="utf-8") == content

    def test_large_content(self, temp_dir: Path) -> None:
        """Test _atomic_write handles large content.

        Edge case: Should handle files with substantial content.
        """
        target = temp_dir / "large.txt"
        content = "x" * 1_000_000  # 1MB of data

        _atomic_write(target, content)

        assert target.read_text(encoding="utf-8") == content

    def test_cleanup_failure_logged(self, temp_dir: Path) -> None:
        """Test _atomic_write logs warning when temp file cleanup fails.

        Edge case: If atomic write fails AND cleanup fails, should log warning.
        """
        target = temp_dir / "file.txt"

        # Create a scenario where both replace and unlink fail
        with patch.object(Path, "replace", side_effect=OSError("Replace failed")):
            with patch.object(Path, "unlink", side_effect=OSError("Unlink failed")):
                with pytest.raises(FileOperationError) as exc_info:
                    _atomic_write(target, "content")

                assert "atomic write failed" in str(exc_info.value).lower()


@pytest.mark.unit
class TestCreateBackupInternal:
    """Tests for _create_backup_internal helper."""

    def test_creates_backup_with_timestamp(self, temp_file: Path) -> None:
        """Test _create_backup_internal creates timestamped backup.

        Happy path: Backup should be created with timestamp in name.
        """
        backup = _create_backup_internal(temp_file)

        assert backup.exists()
        assert "backup" in backup.name
        assert backup.suffix == ".backup"

    def test_backup_preserves_content(self, temp_file: Path) -> None:
        """Test backup contains identical content to original.

        Backup should be exact copy of original file.
        """
        original_content = temp_file.read_text()

        backup = _create_backup_internal(temp_file)

        assert backup.read_text(encoding="utf-8") == original_content

    def test_backup_preserves_metadata(self, temp_file: Path) -> None:
        """Test backup preserves file metadata (timestamps, permissions).

        Uses shutil.copy2 which should preserve metadata.
        """
        original_stat = temp_file.stat()

        backup = _create_backup_internal(temp_file)
        backup_stat = backup.stat()

        # Modification time should be preserved (with some tolerance)
        assert abs(original_stat.st_mtime - backup_stat.st_mtime) < 1.0

    def test_multiple_backups_unique_names(self, temp_file: Path) -> None:
        """Test multiple backups get unique timestamped names.

        Edge case: Rapid successive backups should have different names.
        """
        backup1 = _create_backup_internal(temp_file)
        backup2 = _create_backup_internal(temp_file)

        assert backup1.name != backup2.name
        assert backup1.exists()
        assert backup2.exists()

    def test_raises_on_nonexistent_file(self, temp_dir: Path) -> None:
        """Test _create_backup_internal fails for non-existent file.

        Edge case: Should raise FileOperationError.
        """
        nonexistent = temp_dir / "missing.txt"

        with pytest.raises(FileOperationError) as exc_info:
            _create_backup_internal(nonexistent)

        assert exc_info.value.operation == "backup"


@pytest.mark.unit
class TestRestoreBackupInternal:
    """Tests for _restore_backup_internal helper."""

    def test_restores_backup_content(self, temp_file: Path, temp_dir: Path) -> None:
        """Test _restore_backup_internal restores content correctly.

        Happy path: Target should have backup's content after restore.
        """
        # Create backup
        backup = _create_backup_internal(temp_file)

        # Modify original
        temp_file.write_text("modified content")

        # Restore
        _restore_backup_internal(backup, temp_file)

        assert temp_file.read_text(encoding="utf-8") == "test content"

    def test_restores_to_new_location(self, temp_file: Path, temp_dir: Path) -> None:
        """Test restore can write to different target path.

        Should allow restoring backup to arbitrary location.
        """
        backup = _create_backup_internal(temp_file)
        new_target = temp_dir / "restored.txt"

        _restore_backup_internal(backup, new_target)

        assert new_target.exists()
        assert new_target.read_text(encoding="utf-8") == "test content"

    def test_raises_on_missing_backup(self, temp_dir: Path) -> None:
        """Test _restore_backup_internal fails for missing backup.

        Edge case: Should raise FileOperationError.
        """
        missing_backup = temp_dir / "missing.backup"
        target = temp_dir / "target.txt"

        with pytest.raises(FileOperationError) as exc_info:
            _restore_backup_internal(missing_backup, target)

        assert exc_info.value.operation == "restore"


@pytest.mark.unit
class TestSafeReadFile:
    """Tests for safe_read_file public API."""

    def test_reads_file_content(self, temp_file: Path) -> None:
        """Test safe_read_file returns file content.

        Happy path: Should return exact file content.
        """
        content = safe_read_file(temp_file)

        assert content == "test content"

    def test_accepts_string_path(self, temp_file: Path) -> None:
        """Test safe_read_file accepts string paths.

        Should work with both Path and str inputs.
        """
        content = safe_read_file(str(temp_file))

        assert content == "test content"

    def test_enforces_size_limit(self, temp_dir: Path) -> None:
        """Test safe_read_file respects max_size parameter.

        Should raise FileOperationError when file exceeds limit.
        """
        large_file = temp_dir / "large.txt"
        large_file.write_text("x" * 1000)

        with pytest.raises(FileOperationError) as exc_info:
            safe_read_file(large_file, max_size=100)

        assert "too large" in str(exc_info.value).lower()
        assert exc_info.value.operation == "read"

    def test_no_size_limit_when_none(self, temp_dir: Path) -> None:
        """Test safe_read_file allows unlimited size when max_size=None.

        Edge case: max_size=None should disable size checking.
        """
        large_file = temp_dir / "large.txt"
        content = "x" * 10_000
        large_file.write_text(content)

        result = safe_read_file(large_file, max_size=None)

        assert result == content

    def test_custom_encoding(self, temp_dir: Path) -> None:
        """Test safe_read_file respects encoding parameter.

        Should use specified encoding for reading.
        """
        file_path = temp_dir / "encoded.txt"
        content = "Café ☕"
        file_path.write_text(content, encoding="utf-8")

        result = safe_read_file(file_path, encoding="utf-8")

        assert result == content

    def test_raises_on_nonexistent_file(self, temp_dir: Path) -> None:
        """Test safe_read_file raises for non-existent files.

        Should raise FileOperationError with appropriate message.
        """
        nonexistent = temp_dir / "missing.txt"

        with pytest.raises(FileOperationError) as exc_info:
            safe_read_file(nonexistent)

        assert "not found" in str(exc_info.value).lower()

    def test_raises_on_directory(self, temp_dir: Path) -> None:
        """Test safe_read_file rejects directory paths.

        Edge case: Should fail for directories even if they exist.
        """
        with pytest.raises(FileOperationError) as exc_info:
            safe_read_file(temp_dir)

        assert "not a file" in str(exc_info.value).lower()

    def test_handles_unicode_content(self, temp_dir: Path) -> None:
        """Test safe_read_file handles Unicode content.

        Edge case: Should handle emoji and international text.
        """
        file_path = temp_dir / "unicode.txt"
        content = "Hello 世界 ��"
        file_path.write_text(content, encoding="utf-8")

        result = safe_read_file(file_path)

        assert result == content

    def test_handles_empty_file(self, temp_dir: Path) -> None:
        """Test safe_read_file handles empty files.

        Edge case: Empty files should return empty string.
        """
        empty_file = temp_dir / "empty.txt"
        empty_file.write_text("")

        result = safe_read_file(empty_file)

        assert result == ""

    def test_handles_binary_decode_error(self, temp_dir: Path) -> None:
        """Test safe_read_file handles encoding errors.

        Edge case: Invalid UTF-8 should raise FileOperationError.
        """
        binary_file = temp_dir / "binary.txt"
        binary_file.write_bytes(b"\xff\xfe Invalid UTF-8")

        with pytest.raises(FileOperationError) as exc_info:
            safe_read_file(binary_file, encoding="utf-8")

        assert exc_info.value.operation == "read"


@pytest.mark.unit
class TestSafeWriteFile:
    """Tests for safe_write_file public API."""

    def test_writes_content_to_new_file(self, temp_dir: Path) -> None:
        """Test safe_write_file creates new file with content.

        Happy path: Should create file with exact content.
        """
        target = temp_dir / "new.txt"
        content = "new content"

        safe_write_file(target, content, create_backup=False)

        assert target.exists()
        assert target.read_text(encoding="utf-8") == content

    def test_creates_backup_by_default(self, temp_file: Path) -> None:
        """Test safe_write_file creates backup by default.

        Should create backup when overwriting existing file.
        """
        original_content = temp_file.read_text()

        backup = safe_write_file(temp_file, "new content")

        assert backup is not None
        assert backup.exists()
        assert backup.read_text(encoding="utf-8") == original_content

    def test_skips_backup_when_disabled(self, temp_file: Path) -> None:
        """Test safe_write_file skips backup when create_backup=False.

        Should return None when backup is disabled.
        """
        backup = safe_write_file(temp_file, "new content", create_backup=False)

        assert backup is None

    def test_no_backup_for_new_file(self, temp_dir: Path) -> None:
        """Test safe_write_file doesn't create backup for new files.

        Edge case: No backup needed when file doesn't exist yet.
        """
        target = temp_dir / "new.txt"

        backup = safe_write_file(target, "content", create_backup=True)

        assert backup is None

    def test_restores_backup_on_write_failure(self, temp_file: Path) -> None:
        """Test safe_write_file restores backup if write fails.

        Edge case: Original file should be restored on error.
        """
        original_content = temp_file.read_text()

        # Mock atomic write to fail
        with patch(
            "depkeeper.utils.filesystem._atomic_write",
            side_effect=FileOperationError(
                "Mock error", file_path=str(temp_file), operation="write"
            ),
        ):
            with pytest.raises(FileOperationError):
                safe_write_file(temp_file, "new content")

        # Original content should be restored
        assert temp_file.read_text(encoding="utf-8") == original_content

    def test_accepts_string_path(self, temp_dir: Path) -> None:
        """Test safe_write_file accepts string paths.

        Should work with both Path and str inputs.
        """
        target = str(temp_dir / "file.txt")

        safe_write_file(target, "content", create_backup=False)

        assert Path(target).exists()

    def test_unicode_content(self, temp_dir: Path) -> None:
        """Test safe_write_file handles Unicode content.

        Edge case: Should write emoji and international text correctly.
        """
        target = temp_dir / "unicode.txt"
        content = "Hello 世界 ��"

        safe_write_file(target, content, create_backup=False)

        assert target.read_text(encoding="utf-8") == content

    def test_overwrites_existing_content(self, temp_file: Path) -> None:
        """Test safe_write_file completely replaces existing content.

        Should not append, should replace entirely.
        """
        safe_write_file(temp_file, "replacement", create_backup=False)

        assert temp_file.read_text(encoding="utf-8") == "replacement"

    def test_restore_failure_silently_handled(self, temp_file: Path) -> None:
        """Test safe_write_file silently handles restore failures.

        Edge case: If write fails and restore also fails, should raise original error.
        """
        # Make write fail and restore also fail
        with patch(
            "depkeeper.utils.filesystem._atomic_write",
            side_effect=FileOperationError(
                "Write failed", file_path=str(temp_file), operation="write"
            ),
        ):
            with patch(
                "depkeeper.utils.filesystem._restore_backup_internal",
                side_effect=OSError("Restore failed"),
            ):
                with pytest.raises(FileOperationError) as exc_info:
                    safe_write_file(temp_file, "new content")

                assert "write failed" in str(exc_info.value).lower()

        # Original file should still exist
        assert temp_file.exists()

    def test_creates_parent_directories(self, temp_dir: Path) -> None:
        """Test safe_write_file creates missing parent directories.

        Should automatically create directory structure.
        """
        target = temp_dir / "subdir" / "nested" / "file.txt"

        safe_write_file(target, "content", create_backup=False)

        assert target.exists()
        assert target.parent.exists()


@pytest.mark.unit
class TestCreateBackup:
    """Tests for create_backup public API."""

    def test_creates_backup(self, temp_file: Path) -> None:
        """Test create_backup creates a backup file.

        Happy path: Should create timestamped backup.
        """
        backup = create_backup(temp_file)

        assert backup.exists()
        assert backup != temp_file
        assert "backup" in backup.name

    def test_backup_has_original_content(self, temp_file: Path) -> None:
        """Test backup contains original file content.

        Backup should be exact copy.
        """
        original = temp_file.read_text()

        backup = create_backup(temp_file)

        assert backup.read_text(encoding="utf-8") == original

    def test_raises_on_nonexistent_file(self, temp_dir: Path) -> None:
        """Test create_backup fails for non-existent files.

        Should raise FileOperationError.
        """
        nonexistent = temp_dir / "missing.txt"

        with pytest.raises(FileOperationError):
            create_backup(nonexistent)

    def test_accepts_string_path(self, temp_file: Path) -> None:
        """Test create_backup accepts string paths.

        Should work with both Path and str inputs.
        """
        backup = create_backup(str(temp_file))

        assert backup.exists()


@pytest.mark.unit
class TestRestoreBackup:
    """Tests for restore_backup public API."""

    def test_restores_backup_with_explicit_target(
        self, temp_file: Path, temp_dir: Path
    ) -> None:
        """Test restore_backup with explicit target path.

        Happy path: Should restore backup to specified location.
        """
        backup = create_backup(temp_file)
        temp_file.write_text("modified")

        restore_backup(backup, temp_file)

        assert temp_file.read_text(encoding="utf-8") == "test content"

    def test_infers_target_from_backup_name(self, temp_file: Path) -> None:
        """Test restore_backup infers target from backup filename.

        Should extract original filename from .backup suffix.
        """
        backup = create_backup(temp_file)
        temp_file.unlink()  # Remove original

        restore_backup(backup)

        # Should restore to original location
        assert temp_file.exists()
        assert temp_file.read_text(encoding="utf-8") == "test content"

    def test_raises_on_missing_backup(self, temp_dir: Path) -> None:
        """Test restore_backup fails for non-existent backup.

        Should raise FileOperationError.
        """
        missing = temp_dir / "missing.backup"

        with pytest.raises(FileOperationError) as exc_info:
            restore_backup(missing)

        assert "not found" in str(exc_info.value).lower()

    def test_raises_on_invalid_backup_name(self, temp_dir: Path) -> None:
        """Test restore_backup fails when cannot infer target.

        Edge case: Backup without .backup suffix and no explicit target.
        """
        invalid_backup = temp_dir / "somefile.txt"
        invalid_backup.write_text("content")

        with pytest.raises(FileOperationError) as exc_info:
            restore_backup(invalid_backup)

        assert "cannot infer" in str(exc_info.value).lower()

    def test_accepts_string_paths(self, temp_file: Path) -> None:
        """Test restore_backup accepts string paths.

        Should work with both Path and str inputs.
        """
        backup = create_backup(temp_file)
        temp_file.write_text("modified")

        restore_backup(str(backup), str(temp_file))

        assert temp_file.read_text(encoding="utf-8") == "test content"


@pytest.mark.unit
class TestFindRequirementsFiles:
    """Tests for find_requirements_files discovery."""

    def test_finds_requirements_txt(self, requirements_structure: Path) -> None:
        """Test finds standard requirements.txt file.

        Happy path: Should find requirements.txt in root.
        """
        files = find_requirements_files(requirements_structure)

        names = [f.name for f in files]
        assert "requirements.txt" in names

    def test_finds_requirements_dev_txt(self, requirements_structure: Path) -> None:
        """Test finds requirements-dev.txt variant.

        Should find files matching requirements-*.txt pattern.
        """
        files = find_requirements_files(requirements_structure)

        names = [f.name for f in files]
        assert "requirements-dev.txt" in names
        assert "requirements-test.txt" in names

    def test_finds_nested_requirements(self, requirements_structure: Path) -> None:
        """Test finds requirements files in subdirectories.

        Should recursively search subdirectories by default.
        """
        files = find_requirements_files(requirements_structure, recursive=True)

        # Should find files in requirements/ subdirectory
        paths = [f.as_posix() for f in files]
        assert any("requirements/base.txt" in p for p in paths)
        assert any("requirements/test.txt" in p for p in paths)

    def test_non_recursive_search(self, requirements_structure: Path) -> None:
        """Test non-recursive search only finds root level files.

        With recursive=False, should only find files in root directory.
        """
        files = find_requirements_files(requirements_structure, recursive=False)

        # Should find root level files
        names = [f.name for f in files]
        assert "requirements.txt" in names

        # Should NOT find nested files
        assert "base.txt" not in names
        assert "test.txt" not in names

    def test_excludes_non_requirements_files(
        self, requirements_structure: Path
    ) -> None:
        """Test ignores files that don't match requirements patterns.

        Should not find README.md, setup.py, etc.
        """
        files = find_requirements_files(requirements_structure)

        names = [f.name for f in files]
        assert "README.md" not in names
        assert "setup.py" not in names

    def test_empty_directory(self, temp_dir: Path) -> None:
        """Test returns empty list for directory without requirements.

        Edge case: No requirements files should return empty list.
        """
        files = find_requirements_files(temp_dir)

        assert files == []

    def test_returns_empty_for_nonexistent_directory(self, temp_dir: Path) -> None:
        """Test returns empty list for non-existent directory.

        Edge case: Should handle missing directories gracefully.
        """
        nonexistent = temp_dir / "does_not_exist"

        files = find_requirements_files(nonexistent)

        assert files == []

    def test_returns_empty_for_file_path(self, temp_file: Path) -> None:
        """Test returns empty list when given a file path.

        Edge case: Should only work with directories.
        """
        files = find_requirements_files(temp_file)

        assert files == []

    def test_returns_sorted_unique_results(self, requirements_structure: Path) -> None:
        """Test results are sorted and contain no duplicates.

        Should return consistent, sorted list of unique paths.
        """
        files = find_requirements_files(requirements_structure)

        # Should be sorted
        assert files == sorted(files)

        # Should be unique
        assert len(files) == len(set(files))

    def test_accepts_string_path(self, requirements_structure: Path) -> None:
        """Test find_requirements_files accepts string paths.

        Should work with both Path and str inputs.
        """
        files = find_requirements_files(str(requirements_structure))

        assert len(files) > 0


@pytest.mark.unit
class TestValidatePath:
    """Tests for validate_path security and validation."""

    def test_resolves_absolute_path(self, temp_file: Path) -> None:
        """Test validate_path returns absolute path.

        Happy path: Should resolve to absolute path.
        """
        result = validate_path(temp_file)

        assert result.is_absolute()

    def test_expands_tilde(self) -> None:
        """Test validate_path expands ~ to home directory.

        Should expand user home directory shorthand.
        """
        result = validate_path("~/test.txt")

        assert "~" not in str(result)
        assert result.is_absolute()

    def test_resolves_relative_path(self, temp_dir: Path) -> None:
        """Test validate_path resolves relative paths.

        Should convert relative to absolute paths.
        """
        # Change to temp directory
        original_cwd = Path.cwd()
        try:
            os.chdir(temp_dir)

            result = validate_path("test.txt")

            assert result.is_absolute()
            assert temp_dir in result.parents or result.parent == temp_dir
        finally:
            os.chdir(original_cwd)

    def test_allows_path_within_base_dir(self, temp_dir: Path) -> None:
        """Test validate_path accepts paths within base_dir.

        Happy path: Paths inside base_dir should be allowed.
        """
        subfile = temp_dir / "subdir" / "file.txt"

        result = validate_path(subfile, base_dir=temp_dir)

        assert result.is_absolute()

    def test_rejects_path_outside_base_dir(self, temp_dir: Path) -> None:
        """Test validate_path rejects paths outside base_dir.

        Security: Should prevent path traversal attacks.
        """
        outside_path = temp_dir.parent / "outside.txt"

        with pytest.raises(FileOperationError) as exc_info:
            validate_path(outside_path, base_dir=temp_dir)

        assert "outside allowed base" in str(exc_info.value).lower()
        assert exc_info.value.operation == "validate"

    def test_prevents_path_traversal(self, temp_dir: Path) -> None:
        """Test validate_path prevents .. traversal attacks.

        Security: Should resolve .. and check final path.
        """
        traversal_path = temp_dir / "subdir" / ".." / ".." / "outside.txt"

        with pytest.raises(FileOperationError):
            validate_path(traversal_path, base_dir=temp_dir)

    def test_accepts_string_path(self, temp_file: Path) -> None:
        """Test validate_path accepts string paths.

        Should work with both Path and str inputs.
        """
        result = validate_path(str(temp_file))

        assert result.is_absolute()

    def test_relative_base_dir(self, temp_dir: Path) -> None:
        """Test validate_path handles relative base_dir.

        Should resolve relative base_dir to absolute path.
        """
        original_cwd = Path.cwd()
        try:
            # Change to temp directory
            import os

            os.chdir(temp_dir)

            # Create a file in temp dir
            test_file = temp_dir / "test.txt"
            test_file.write_text("test")

            # Use relative base_dir
            result = validate_path(test_file, base_dir=".")

            assert result.is_absolute()
            assert result == test_file.resolve()
        finally:
            import os

            os.chdir(original_cwd)

    def test_handles_nonexistent_paths(self, temp_dir: Path) -> None:
        """Test validate_path works with non-existent paths.

        Edge case: Should validate paths that don't exist yet.
        """
        nonexistent = temp_dir / "future" / "file.txt"

        result = validate_path(nonexistent, base_dir=temp_dir)

        assert result.is_absolute()

    @pytest.mark.skipif(not SYMLINKS_SUPPORTED, reason="Symlinks not supported")
    def test_symlink_resolution(self, temp_file: Path, temp_dir: Path) -> None:
        """Test validate_path resolves symlinks.

        Edge case: Should follow symlinks to real path.
        """
        symlink = temp_dir / "link.txt"
        symlink.symlink_to(temp_file)

        result = validate_path(symlink)

        assert result.is_absolute()


@pytest.mark.unit
class TestCreateTimestampedBackup:
    """Tests for create_timestamped_backup public API."""

    def test_creates_timestamped_backup(self, temp_file: Path) -> None:
        """Test creates backup with timestamp in name.

        Happy path: Backup should have timestamp format.
        """
        backup = create_timestamped_backup(temp_file)

        assert backup.exists()
        assert backup != temp_file
        assert "backup" in backup.name

    def test_backup_name_format(self, temp_file: Path) -> None:
        """Test backup follows naming convention.

        Format should be: {stem}.{timestamp}.backup{suffix}
        """
        backup = create_timestamped_backup(temp_file)

        # Should contain stem
        assert temp_file.stem in backup.name

        # Should have .backup in name
        assert ".backup" in backup.name

        # Should end with original suffix
        assert backup.suffix == temp_file.suffix

    def test_backup_preserves_content(self, temp_file: Path) -> None:
        """Test backup contains original content.

        Should be exact copy of original.
        """
        original = temp_file.read_text()

        backup = create_timestamped_backup(temp_file)

        assert backup.read_text(encoding="utf-8") == original

    def test_multiple_backups_unique(self, temp_file: Path) -> None:
        """Test multiple backups have unique names.

        Edge case: Rapid backups should have different timestamps.
        """
        backup1 = create_timestamped_backup(temp_file)
        backup2 = create_timestamped_backup(temp_file)

        assert backup1 != backup2
        assert backup1.exists()
        assert backup2.exists()

    def test_raises_on_nonexistent_file(self, temp_dir: Path) -> None:
        """Test fails for non-existent files.

        Should raise FileOperationError.
        """
        nonexistent = temp_dir / "missing.txt"

        with pytest.raises(FileOperationError) as exc_info:
            create_timestamped_backup(nonexistent)

        assert "cannot backup invalid file" in str(exc_info.value).lower()

    def test_raises_on_directory(self, temp_dir: Path) -> None:
        """Test fails for directory paths.

        Edge case: Should only work with files, not directories.
        """
        with pytest.raises(FileOperationError) as exc_info:
            create_timestamped_backup(temp_dir)

        assert "cannot backup invalid file" in str(exc_info.value).lower()

    def test_copy_failure_raises_error(self, temp_file: Path) -> None:
        """Test create_timestamped_backup raises error when copy fails.

        Edge case: Should raise FileOperationError when shutil.copy2 fails.
        """
        with patch("shutil.copy2", side_effect=OSError("Copy failed")):
            with pytest.raises(FileOperationError) as exc_info:
                create_timestamped_backup(temp_file)

            assert exc_info.value.operation == "backup"
            assert "failed to create backup" in str(exc_info.value).lower()

    def test_accepts_string_path(self, temp_file: Path) -> None:
        """Test accepts string paths.

        Should work with both Path and str inputs.
        """
        backup = create_timestamped_backup(str(temp_file))

        assert backup.exists()


@pytest.mark.integration
class TestEdgeCases:
    """Additional edge cases and integration tests."""

    def test_concurrent_backups(self, temp_file: Path) -> None:
        """Test multiple simultaneous backups don't conflict.

        Edge case: Concurrent backups should all succeed with unique names.
        """
        import concurrent.futures

        def create_backup_wrapper():
            return create_backup(temp_file)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(create_backup_wrapper) for _ in range(5)]
            backups = [f.result() for f in futures]

        # All should succeed
        assert len(backups) == 5
        assert all(b.exists() for b in backups)

        # All should be unique
        assert len(set(backups)) == 5

    def test_write_read_cycle(self, temp_dir: Path) -> None:
        """Test write then read returns same content.

        Integration test: Full write/read cycle.
        """
        file_path = temp_dir / "cycle.txt"
        content = "Test content with �� unicode"

        safe_write_file(file_path, content, create_backup=False)
        result = safe_read_file(file_path)

        assert result == content

    def test_cross_platform_path_handling(self, temp_dir: Path) -> None:
        """Test path handling works across different platforms.

        Cross-platform: Paths should work on Windows, Linux, macOS.
        """
        # Test with nested directories
        nested = temp_dir / "a" / "b" / "c" / "file.txt"

        safe_write_file(nested, "content", create_backup=False)

        assert nested.exists()
        assert safe_read_file(nested) == "content"

    def test_special_characters_in_content(self, temp_dir: Path) -> None:
        """Test files with special characters and unicode.

        Cross-platform: Unicode should work on all platforms.
        """
        file_path = temp_dir / "unicode.txt"
        content = "Hello 世界 �� Привет مرحبا"

        safe_write_file(file_path, content, create_backup=False)
        result = safe_read_file(file_path)

        assert result == content

    def test_line_ending_preservation(self, temp_dir: Path) -> None:
        """Test line endings are consistent across platforms.

        Uses newline='\\n' in atomic_write to ensure LF line endings.
        """
        file_path = temp_dir / "lines.txt"
        content = "line1\\nline2\\nline3\\n"

        safe_write_file(file_path, content, create_backup=False)
        result = safe_read_file(file_path)

        assert result == content
        assert "\\r\\n" not in result  # Should use LF, not CRLF

    def test_backup_restore_cycle(self, temp_file: Path) -> None:
        """Test backup then restore preserves content.

        Integration test: Full backup/restore cycle.
        """
        original = temp_file.read_text()

        # Create backup, modify, restore
        backup = create_backup(temp_file)
        temp_file.write_text("modified")
        restore_backup(backup, temp_file)

        assert temp_file.read_text(encoding="utf-8") == original

    def test_special_characters_in_filename(self, temp_dir: Path) -> None:
        """Test handles special characters in filenames.

        Edge case: Some special chars should work.
        """
        # Avoid truly invalid chars like / \ : * ? " < > |
        special_name = "file-with_special.chars (1) [test].txt"
        file_path = temp_dir / special_name

        safe_write_file(file_path, "content", create_backup=False)

        assert file_path.exists()

    def test_empty_file_operations(self, temp_dir: Path) -> None:
        """Test operations on empty files.

        Edge case: Empty files should be handled correctly.
        """
        empty_file = temp_dir / "empty.txt"
        empty_file.write_text("")

        # Read empty file
        content = safe_read_file(empty_file)
        assert content == ""

        # Backup empty file
        backup = create_backup(empty_file)
        assert backup.exists()
        assert backup.read_text(encoding="utf-8") == ""

    def test_whitespace_only_content(self, temp_dir: Path) -> None:
        """Test files with only whitespace.

        Edge case: Whitespace-only content should be preserved.
        """
        file_path = temp_dir / "whitespace.txt"
        content = "   \n\n\t  \n"

        safe_write_file(file_path, content, create_backup=False)
        result = safe_read_file(file_path)

        assert result == content
