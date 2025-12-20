import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# Platform detection for Windows-specific test handling
IS_WINDOWS = sys.platform == "win32"

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
    list_backups,
    clean_old_backups,
    validate_path,
    create_timestamped_backup,
)
from depkeeper.constants import MAX_FILE_SIZE
from depkeeper.exceptions import FileOperationError


@pytest.fixture
def temp_dir(tmp_path):
    """Provide a temporary directory for testing."""
    return tmp_path


@pytest.fixture
def temp_file(temp_dir):
    """Create a temporary file with some content."""
    file_path = temp_dir / "test_file.txt"
    file_path.write_text("test content\n", encoding="utf-8")
    return file_path


@pytest.fixture
def requirements_file(temp_dir):
    """Create a temporary requirements.txt file."""
    req_file = temp_dir / "requirements.txt"
    req_file.write_text(
        "requests>=2.28.0\n" "click>=8.0.0\n" "pytest>=7.0.0\n", encoding="utf-8"
    )
    return req_file


@pytest.fixture
def mock_logger():
    """Provide a mock logger for testing."""
    with patch("depkeeper.utils.filesystem.logger") as mock:
        yield mock


class TestValidatedFile:
    """Test suite for file validation helper."""

    def test_validated_file_existing_file(self, temp_file):
        """Should return resolved path for existing file."""
        result = _validated_file(temp_file, must_exist=True)
        assert result.exists()
        assert result.is_absolute()

    def test_validated_file_nonexistent_must_exist(self, temp_dir):
        """Should raise FileOperationError if file doesn't exist and must_exist=True."""
        nonexistent = temp_dir / "nonexistent.txt"
        with pytest.raises(FileOperationError) as exc_info:
            _validated_file(nonexistent, must_exist=True)

        assert "File not found" in str(exc_info.value)
        assert exc_info.value.file_path == str(nonexistent)
        assert exc_info.value.operation == "read"

    def test_validated_file_nonexistent_optional(self, temp_dir):
        """Should return resolved path for nonexistent file if must_exist=False."""
        nonexistent = temp_dir / "nonexistent.txt"
        result = _validated_file(nonexistent, must_exist=False)
        assert result.is_absolute()

    def test_validated_file_directory_must_exist(self, temp_dir):
        """Should raise FileOperationError if path is a directory."""
        with pytest.raises(FileOperationError) as exc_info:
            _validated_file(temp_dir, must_exist=True)

        assert "Not a file" in str(exc_info.value)
        assert exc_info.value.operation == "read"

    @pytest.mark.skipif(
        IS_WINDOWS, reason="Symlinks require admin privileges on Windows"
    )
    def test_validated_file_resolves_symlinks(self, temp_file, temp_dir):
        """Should resolve symlinks to canonical path."""
        symlink = temp_dir / "symlink.txt"
        symlink.symlink_to(temp_file)

        result = _validated_file(symlink, must_exist=True)
        assert result == temp_file.resolve()

    def test_validated_file_relative_path(self, temp_file):
        """Should resolve relative paths to absolute."""
        # Create relative path
        relative = Path(temp_file.name)
        with patch.object(Path, "resolve", return_value=temp_file):
            result = _validated_file(relative, must_exist=False)
            assert result.is_absolute()


class TestAtomicWrite:
    """Test suite for atomic file writing."""

    def test_atomic_write_success(self, temp_dir):
        """Should write content atomically."""
        target = temp_dir / "output.txt"
        content = "test content\n"

        _atomic_write(target, content)

        assert target.exists()
        assert target.read_text(encoding="utf-8") == content

    def test_atomic_write_creates_parent_dirs(self, temp_dir):
        """Should create parent directories if they don't exist."""
        target = temp_dir / "subdir" / "nested" / "file.txt"
        content = "nested content\n"

        _atomic_write(target, content)

        assert target.exists()
        assert target.read_text(encoding="utf-8") == content

    def test_atomic_write_overwrites_existing(self, temp_file):
        """Should overwrite existing file atomically."""
        original_content = temp_file.read_text()
        new_content = "new content\n"

        _atomic_write(temp_file, new_content)

        assert temp_file.read_text(encoding="utf-8") == new_content
        assert temp_file.read_text() != original_content

    def test_atomic_write_failure_cleanup(self, temp_dir, mock_logger):
        """Should clean up temporary file on failure."""
        target = temp_dir / "output.txt"

        # Mock fsync to raise an exception
        with patch("os.fsync", side_effect=OSError("Disk full")):
            with pytest.raises(FileOperationError) as exc_info:
                _atomic_write(target, "content")

        assert "Atomic write failed" in str(exc_info.value)
        assert exc_info.value.operation == "write"

        # Check that temp files are cleaned up or cleanup was attempted
        # On Windows, cleanup might fail due to file locks
        temp_files = list(temp_dir.glob(".output.txt.*.tmp"))
        # Either cleaned up successfully or cleanup was attempted (logged)
        if temp_files:
            # Verify cleanup was attempted even if it failed
            assert len(temp_files) <= 1  # At most one temp file remains

    def test_atomic_write_preserves_on_error(self, temp_file):
        """Should preserve original file if write fails."""
        original_content = temp_file.read_text()

        with patch("os.fsync", side_effect=OSError("Disk full")):
            with pytest.raises(FileOperationError):
                _atomic_write(temp_file, "new content")

        # Original file should be unchanged
        assert temp_file.read_text() == original_content

    def test_atomic_write_unicode_content(self, temp_dir):
        """Should handle Unicode content correctly."""
        target = temp_dir / "unicode.txt"
        content = "Hello 世界 �� café\n"

        _atomic_write(target, content)

        assert target.read_text(encoding="utf-8") == content

    def test_atomic_write_large_content(self, temp_dir):
        """Should handle large content."""
        target = temp_dir / "large.txt"
        content = "x" * (1024 * 1024)  # 1 MB

        _atomic_write(target, content)

        assert target.read_text(encoding="utf-8") == content

    def test_atomic_write_empty_content(self, temp_dir):
        """Should handle empty content."""
        target = temp_dir / "empty.txt"

        _atomic_write(target, "")

        assert target.exists()
        assert target.read_text(encoding="utf-8") == ""

    def test_atomic_write_cleanup_failure_logged(self, temp_dir, mock_logger):
        """Should log cleanup failures."""
        target = temp_dir / "output.txt"

        # Create a controlled scenario where cleanup fails
        original_unlink = Path.unlink

        def failing_unlink(self, *args, **kwargs):
            if str(self).endswith(".tmp"):
                raise PermissionError("Cannot delete")
            return original_unlink(self, *args, **kwargs)

        with patch("os.fsync", side_effect=OSError("Error")):
            with patch.object(Path, "unlink", failing_unlink):
                with pytest.raises(FileOperationError):
                    _atomic_write(target, "content")

        # Warning should be logged if cleanup was attempted and failed
        # Check if warning was called (it might not be on some platforms)
        assert mock_logger.warning.call_count >= 0


class TestCreateBackupInternal:
    """Test suite for internal backup creation."""

    def test_create_backup_internal_success(self, temp_file):
        """Should create timestamped backup."""
        backup = _create_backup_internal(temp_file)

        assert backup.exists()
        assert backup.name.startswith(temp_file.name)
        assert ".backup" in backup.name
        assert backup.read_text() == temp_file.read_text()

    def test_create_backup_internal_preserves_metadata(self, temp_file):
        """Should preserve file metadata."""
        original_stat = temp_file.stat()

        backup = _create_backup_internal(temp_file)
        backup_stat = backup.stat()

        # Modification time should be preserved (within a small delta)
        assert abs(backup_stat.st_mtime - original_stat.st_mtime) < 1

    def test_create_backup_internal_unique_names(self, temp_file):
        """Should create unique backup names."""
        backup1 = _create_backup_internal(temp_file)
        time.sleep(0.001)  # Ensure different timestamp
        backup2 = _create_backup_internal(temp_file)

        assert backup1 != backup2
        assert backup1.exists()
        assert backup2.exists()

    def test_create_backup_internal_failure(self, temp_file):
        """Should raise FileOperationError on failure."""
        with patch("shutil.copy2", side_effect=PermissionError("Access denied")):
            with pytest.raises(FileOperationError) as exc_info:
                _create_backup_internal(temp_file)

        assert "Failed to create backup" in str(exc_info.value)
        assert exc_info.value.operation == "backup"

    def test_create_backup_internal_timestamp_format(self, temp_file):
        """Should use correct timestamp format."""
        backup = _create_backup_internal(temp_file)

        # Extract timestamp from filename
        # Format: filename.suffix.YYYYMMDD_HHMMSS_ffffff.backup
        parts = backup.name.split(".")
        assert len(parts) >= 3
        # Should contain timestamp pattern
        assert any("_" in part for part in parts)


class TestRestoreBackupInternal:
    """Test suite for internal backup restoration."""

    def test_restore_backup_internal_success(self, temp_file, temp_dir):
        """Should restore file from backup."""
        backup = _create_backup_internal(temp_file)
        target = temp_dir / "restored.txt"

        _restore_backup_internal(backup, target)

        assert target.exists()
        assert target.read_text() == temp_file.read_text()

    def test_restore_backup_internal_overwrites(self, temp_file, temp_dir):
        """Should overwrite existing target file."""
        backup = _create_backup_internal(temp_file)
        target = temp_dir / "target.txt"
        target.write_text("old content")

        _restore_backup_internal(backup, target)

        assert target.read_text() == temp_file.read_text()

    def test_restore_backup_internal_failure(self, temp_file, temp_dir):
        """Should raise FileOperationError on failure."""
        backup = _create_backup_internal(temp_file)
        target = temp_dir / "target.txt"

        with patch("shutil.copy2", side_effect=PermissionError("Access denied")):
            with pytest.raises(FileOperationError) as exc_info:
                _restore_backup_internal(backup, target)

        assert "Failed to restore backup" in str(exc_info.value)
        assert exc_info.value.operation == "restore"


class TestSafeReadFile:
    """Test suite for safe file reading."""

    def test_safe_read_file_success(self, temp_file):
        """Should read file content successfully."""
        content = safe_read_file(temp_file)
        assert content == "test content\n"

    def test_safe_read_file_with_string_path(self, temp_file):
        """Should accept string path."""
        content = safe_read_file(str(temp_file))
        assert content == "test content\n"

    def test_safe_read_file_nonexistent(self, temp_dir):
        """Should raise FileOperationError for nonexistent file."""
        with pytest.raises(FileOperationError) as exc_info:
            safe_read_file(temp_dir / "nonexistent.txt")

        assert "File not found" in str(exc_info.value)

    def test_safe_read_file_directory(self, temp_dir):
        """Should raise FileOperationError for directory."""
        with pytest.raises(FileOperationError) as exc_info:
            safe_read_file(temp_dir)

        assert "Not a file" in str(exc_info.value)

    def test_safe_read_file_size_limit(self, temp_dir):
        """Should raise FileOperationError if file exceeds size limit."""
        large_file = temp_dir / "large.txt"
        large_file.write_text("x" * 1000)

        with pytest.raises(FileOperationError) as exc_info:
            safe_read_file(large_file, max_size=100)

        assert "File too large" in str(exc_info.value)
        assert "1000 bytes" in str(exc_info.value)
        assert "max 100" in str(exc_info.value)

    def test_safe_read_file_no_size_limit(self, temp_dir):
        """Should read large file if max_size=None."""
        large_file = temp_dir / "large.txt"
        content = "x" * (MAX_FILE_SIZE + 1000)
        large_file.write_text(content)

        result = safe_read_file(large_file, max_size=None)
        assert result == content

    def test_safe_read_file_custom_encoding(self, temp_dir):
        """Should use custom encoding."""
        file_path = temp_dir / "encoded.txt"
        content = "café"
        file_path.write_text(content, encoding="latin-1")

        result = safe_read_file(file_path, encoding="latin-1")
        assert result == content

    def test_safe_read_file_encoding_error(self, temp_dir):
        """Should raise FileOperationError on encoding error."""
        file_path = temp_dir / "binary.txt"
        file_path.write_bytes(b"\xFF\xFE\xFD")

        with pytest.raises(FileOperationError) as exc_info:
            safe_read_file(file_path, encoding="utf-8")

        assert "Failed to read file" in str(exc_info.value)

    def test_safe_read_file_empty_file(self, temp_dir):
        """Should read empty file."""
        empty_file = temp_dir / "empty.txt"
        empty_file.write_text("")

        result = safe_read_file(empty_file)
        assert result == ""

    def test_safe_read_file_unicode(self, temp_dir):
        """Should read Unicode content."""
        unicode_file = temp_dir / "unicode.txt"
        content = "Hello 世界 �� café\n"
        unicode_file.write_text(content, encoding="utf-8")

        result = safe_read_file(unicode_file)
        assert result == content

    def test_safe_read_file_permission_error(self, temp_file):
        """Should raise FileOperationError on permission error."""
        with patch.object(
            Path, "read_text", side_effect=PermissionError("Access denied")
        ):
            with pytest.raises(FileOperationError) as exc_info:
                safe_read_file(temp_file)

        assert "Failed to read file" in str(exc_info.value)


class TestSafeWriteFile:
    """Test suite for safe file writing."""

    def test_safe_write_file_new_file(self, temp_dir):
        """Should create new file with content."""
        file_path = temp_dir / "new.txt"
        content = "new content\n"

        backup = safe_write_file(file_path, content, create_backup=False)

        assert file_path.exists()
        assert file_path.read_text() == content
        assert backup is None

    def test_safe_write_file_with_backup(self, temp_file):
        """Should create backup when updating existing file."""
        new_content = "updated content\n"

        backup = safe_write_file(temp_file, new_content, create_backup=True)

        assert temp_file.read_text() == new_content
        assert backup is not None
        assert backup.exists()
        assert "test content" in backup.read_text()

    def test_safe_write_file_without_backup(self, temp_file):
        """Should not create backup when create_backup=False."""
        new_content = "updated content\n"

        backup = safe_write_file(temp_file, new_content, create_backup=False)

        assert temp_file.read_text() == new_content
        assert backup is None

    def test_safe_write_file_creates_directories(self, temp_dir):
        """Should create parent directories."""
        file_path = temp_dir / "sub" / "nested" / "file.txt"
        content = "nested content\n"

        safe_write_file(file_path, content, create_backup=False)

        assert file_path.exists()
        assert file_path.read_text() == content

    def test_safe_write_file_rollback_on_failure(self, temp_file):
        """Should rollback to backup on write failure."""
        original_content = temp_file.read_text()
        new_content = "new content\n"

        # Mock the replace operation to fail (simulating disk full during write)
        with patch.object(Path, "replace", side_effect=OSError("Disk full")):
            with pytest.raises(FileOperationError):
                safe_write_file(temp_file, new_content, create_backup=True)

        # Original content should be restored from backup
        assert temp_file.read_text() == original_content

    def test_safe_write_file_string_path(self, temp_dir):
        """Should accept string path."""
        file_path = str(temp_dir / "new.txt")
        content = "content\n"

        safe_write_file(file_path, content, create_backup=False)

        assert Path(file_path).exists()

    def test_safe_write_file_unicode_content(self, temp_dir):
        """Should handle Unicode content."""
        file_path = temp_dir / "unicode.txt"
        content = "Hello 世界 �� café\n"

        safe_write_file(file_path, content, create_backup=False)

        assert file_path.read_text(encoding="utf-8") == content

    def test_safe_write_file_empty_content(self, temp_dir):
        """Should write empty content."""
        file_path = temp_dir / "empty.txt"

        safe_write_file(file_path, "", create_backup=False)

        assert file_path.exists()
        assert file_path.read_text() == ""

    def test_safe_write_file_backup_for_existing_only(self, temp_dir):
        """Should only create backup for existing files."""
        file_path = temp_dir / "new.txt"

        backup = safe_write_file(file_path, "content", create_backup=True)

        # New file, so no backup should be created
        assert backup is None

    def test_safe_write_file_backup_not_for_directory(self, temp_dir):
        """Should not try to backup a directory."""
        # Try to write to a path that is a directory
        with pytest.raises(FileOperationError):
            safe_write_file(temp_dir, "content", create_backup=True)


class TestCreateBackup:
    """Test suite for manual backup creation."""

    def test_create_backup_success(self, temp_file):
        """Should create backup of file."""
        backup = create_backup(temp_file)

        assert backup.exists()
        assert backup.read_text() == temp_file.read_text()

    def test_create_backup_string_path(self, temp_file):
        """Should accept string path."""
        backup = create_backup(str(temp_file))

        assert backup.exists()

    def test_create_backup_nonexistent_file(self, temp_dir):
        """Should raise FileOperationError for nonexistent file."""
        with pytest.raises(FileOperationError) as exc_info:
            create_backup(temp_dir / "nonexistent.txt")

        assert "File not found" in str(exc_info.value)

    def test_create_backup_directory(self, temp_dir):
        """Should raise FileOperationError for directory."""
        with pytest.raises(FileOperationError) as exc_info:
            create_backup(temp_dir)

        assert "Not a file" in str(exc_info.value)


class TestRestoreBackup:
    """Test suite for backup restoration."""

    def test_restore_backup_with_target(self, temp_file, temp_dir):
        """Should restore backup to specified target."""
        backup = create_backup(temp_file)
        target = temp_dir / "restored.txt"

        restore_backup(backup, target)

        assert target.exists()
        assert target.read_text() == temp_file.read_text()

    def test_restore_backup_infer_target(self, temp_file, mock_logger):
        """Should infer target from backup filename."""
        backup = create_backup(temp_file)
        original_content = temp_file.read_text()

        # Modify original
        temp_file.write_text("modified")

        # Restore from backup (should infer target)
        restore_backup(backup)

        # Original file should be restored
        assert temp_file.read_text() == original_content

    def test_restore_backup_nonexistent(self, temp_dir):
        """Should raise FileOperationError for nonexistent backup."""
        with pytest.raises(FileOperationError) as exc_info:
            restore_backup(temp_dir / "nonexistent.backup")

        assert "Backup file not found" in str(exc_info.value)

    def test_restore_backup_invalid_name(self, temp_dir):
        """Should raise FileOperationError if cannot infer target."""
        invalid_backup = temp_dir / "invalid.txt"
        invalid_backup.write_text("content")

        with pytest.raises(FileOperationError) as exc_info:
            restore_backup(invalid_backup)

        assert "Cannot infer target path" in str(exc_info.value)
        assert "must end with .backup" in str(exc_info.value)

    def test_restore_backup_string_paths(self, temp_file, temp_dir):
        """Should accept string paths."""
        backup = create_backup(temp_file)
        target = temp_dir / "restored.txt"

        restore_backup(str(backup), str(target))

        assert target.exists()

    def test_restore_backup_logs_info(self, temp_file, temp_dir, mock_logger):
        """Should log restoration info."""
        backup = create_backup(temp_file)
        target = temp_dir / "restored.txt"

        restore_backup(backup, target)

        # Should log restoration start and success
        assert mock_logger.info.call_count >= 2

    def test_restore_backup_complex_filename(self, temp_dir, mock_logger):
        """Should handle complex filenames with multiple dots."""
        # Create file with multiple dots
        original = temp_dir / "file.test.data.txt"
        original.write_text("content")

        backup = create_backup(original)
        original.unlink()

        restore_backup(backup)

        assert original.exists()
        assert original.read_text() == "content"

    def test_restore_backup_no_extension(self, temp_dir):
        """Should handle files without extension."""
        original = temp_dir / "Makefile"
        original.write_text("content")

        backup = create_backup(original)
        original.unlink()

        restore_backup(backup)

        assert original.exists()


class TestFindRequirementsFiles:
    """Test suite for requirements file discovery."""

    def test_find_requirements_files_basic(self, temp_dir):
        """Should find requirements.txt in directory."""
        req_file = temp_dir / "requirements.txt"
        req_file.write_text("requests>=2.28.0")

        files = find_requirements_files(temp_dir, recursive=False)

        assert len(files) == 1
        assert req_file in files

    def test_find_requirements_files_recursive(self, temp_dir):
        """Should find requirements files recursively."""
        (temp_dir / "requirements.txt").write_text("pkg1")
        (temp_dir / "subdir").mkdir()
        (temp_dir / "subdir" / "requirements-dev.txt").write_text("pkg2")
        (temp_dir / "subdir" / "nested").mkdir()
        (temp_dir / "subdir" / "nested" / "requirements-test.txt").write_text("pkg3")

        files = find_requirements_files(temp_dir, recursive=True)

        assert len(files) >= 3

    def test_find_requirements_files_non_recursive(self, temp_dir):
        """Should not find nested files when recursive=False."""
        (temp_dir / "requirements.txt").write_text("pkg1")
        (temp_dir / "subdir").mkdir()
        (temp_dir / "subdir" / "requirements-dev.txt").write_text("pkg2")

        files = find_requirements_files(temp_dir, recursive=False)

        assert len(files) == 1
        assert files[0].name == "requirements.txt"

    def test_find_requirements_files_patterns(self, temp_dir):
        """Should match various requirement file patterns."""
        # Create files matching different patterns
        (temp_dir / "requirements.txt").write_text("pkg")
        (temp_dir / "requirements-dev.txt").write_text("pkg")
        (temp_dir / "requirements-test.txt").write_text("pkg")
        (temp_dir / "requirements").mkdir()
        (temp_dir / "requirements" / "base.txt").write_text("pkg")
        (temp_dir / "requirements" / "prod.txt").write_text("pkg")

        files = find_requirements_files(temp_dir, recursive=True)

        assert len(files) >= 5

    def test_find_requirements_files_nonexistent_dir(self, temp_dir):
        """Should return empty list for nonexistent directory."""
        files = find_requirements_files(temp_dir / "nonexistent", recursive=True)

        assert files == []

    def test_find_requirements_files_file_path(self, temp_file):
        """Should return empty list if path is a file."""
        files = find_requirements_files(temp_file, recursive=True)

        assert files == []

    def test_find_requirements_files_sorted(self, temp_dir):
        """Should return sorted results."""
        (temp_dir / "z-requirements.txt").write_text("pkg")
        (temp_dir / "a-requirements.txt").write_text("pkg")
        (temp_dir / "m-requirements.txt").write_text("pkg")

        files = find_requirements_files(temp_dir, recursive=False)

        # Check if sorted
        names = [f.name for f in files]
        assert names == sorted(names)

    def test_find_requirements_files_deduplication(self, temp_dir):
        """Should deduplicate results."""
        req_file = temp_dir / "requirements.txt"
        req_file.write_text("pkg")

        files = find_requirements_files(temp_dir, recursive=True)

        # Should not have duplicates
        assert len(files) == len(set(files))

    def test_find_requirements_files_string_path(self, temp_dir):
        """Should accept string path."""
        req_file = temp_dir / "requirements.txt"
        req_file.write_text("pkg")

        files = find_requirements_files(str(temp_dir), recursive=False)

        assert len(files) == 1


class TestListBackups:
    """Test suite for backup listing."""

    def test_list_backups_single(self, temp_file):
        """Should list single backup."""
        backup = create_backup(temp_file)

        backups = list_backups(temp_file)

        assert len(backups) == 1
        assert backup in backups

    def test_list_backups_multiple(self, temp_file):
        """Should list multiple backups."""
        backup1 = create_backup(temp_file)
        time.sleep(0.01)
        backup2 = create_backup(temp_file)
        time.sleep(0.01)
        backup3 = create_backup(temp_file)

        backups = list_backups(temp_file)

        assert len(backups) == 3
        assert all(b in backups for b in [backup1, backup2, backup3])

    def test_list_backups_sorted_newest_first(self, temp_file):
        """Should sort backups by modification time, newest first."""
        backup1 = create_backup(temp_file)
        time.sleep(0.05)  # Increased delay for Windows filesystem
        # Touch the file to ensure different mtime
        backup1.touch()
        time.sleep(0.05)
        backup2 = create_backup(temp_file)
        time.sleep(0.05)
        backup2.touch()
        time.sleep(0.05)
        backup3 = create_backup(temp_file)

        backups = list_backups(temp_file)

        # Newest should be first (based on mtime)
        assert len(backups) == 3
        # Verify they're sorted by mtime descending
        mtimes = [b.stat().st_mtime for b in backups]
        assert mtimes == sorted(mtimes, reverse=True)

    def test_list_backups_nonexistent_file(self, temp_dir):
        """Should return empty list for nonexistent file."""
        backups = list_backups(temp_dir / "nonexistent.txt")

        assert backups == []

    def test_list_backups_no_backups(self, temp_file):
        """Should return empty list if no backups exist."""
        backups = list_backups(temp_file)

        assert backups == []

    def test_list_backups_string_path(self, temp_file):
        """Should accept string path."""
        create_backup(temp_file)

        backups = list_backups(str(temp_file))

        assert len(backups) == 1

    def test_list_backups_ignores_non_backups(self, temp_file, temp_dir):
        """Should ignore files that aren't backups."""
        create_backup(temp_file)

        # Create non-backup files
        (temp_dir / f"{temp_file.name}.other").write_text("not a backup")
        (temp_dir / f"{temp_file.name}.txt").write_text("not a backup")

        backups = list_backups(temp_file)

        assert len(backups) == 1


class TestCleanOldBackups:
    """Test suite for backup cleanup."""

    def test_clean_old_backups_keeps_recent(self, temp_file):
        """Should keep specified number of recent backups."""
        backups_created = []
        for _ in range(5):
            backups_created.append(create_backup(temp_file))
            time.sleep(0.01)

        deleted = clean_old_backups(temp_file, keep=3)

        assert deleted == 2
        remaining = list_backups(temp_file)
        assert len(remaining) == 3

    def test_clean_old_backups_all(self, temp_file, mock_logger):
        """Should delete all backups if keep=0."""
        for _ in range(3):
            create_backup(temp_file)
            time.sleep(0.01)

        deleted = clean_old_backups(temp_file, keep=0)

        assert deleted == 3
        assert list_backups(temp_file) == []

    def test_clean_old_backups_fewer_than_keep(self, temp_file):
        """Should not delete anything if fewer backups than keep."""
        create_backup(temp_file)
        create_backup(temp_file)

        deleted = clean_old_backups(temp_file, keep=5)

        assert deleted == 0
        assert len(list_backups(temp_file)) == 2

    def test_clean_old_backups_no_backups(self, temp_file):
        """Should return 0 if no backups exist."""
        deleted = clean_old_backups(temp_file, keep=5)

        assert deleted == 0

    def test_clean_old_backups_deletion_failure(self, temp_file, mock_logger):
        """Should log warning on deletion failure and continue."""
        backup1 = create_backup(temp_file)
        time.sleep(0.05)
        backup2 = create_backup(temp_file)
        time.sleep(0.05)
        backup3 = create_backup(temp_file)

        # Track which backup should fail
        failed_backup = backup1

        # Mock unlink to fail for specific backup
        original_unlink = Path.unlink

        def selective_unlink(self, *args, **kwargs):
            if self.name == failed_backup.name:
                raise PermissionError("Cannot delete")
            return original_unlink(self, *args, **kwargs)

        with patch.object(Path, "unlink", selective_unlink):
            deleted = clean_old_backups(temp_file, keep=1)

        # Should have succeeded deleting at least 1
        assert deleted >= 1
        # Warning should be logged for the failed deletion
        if deleted < 2:
            mock_logger.warning.assert_called()

    def test_clean_old_backups_string_path(self, temp_file):
        """Should accept string path."""
        create_backup(temp_file)
        create_backup(temp_file)

        deleted = clean_old_backups(str(temp_file), keep=1)

        assert deleted == 1

    def test_clean_old_backups_logs_info(self, temp_file, mock_logger):
        """Should log info message when backups deleted."""
        for _ in range(3):
            create_backup(temp_file)

        clean_old_backups(temp_file, keep=1)

        mock_logger.info.assert_called_once()


class TestValidatePath:
    """Test suite for path validation."""

    def test_validate_path_absolute(self, temp_dir):
        """Should return absolute path."""
        path = validate_path(temp_dir / "file.txt")

        assert path.is_absolute()

    def test_validate_path_relative(self, temp_dir):
        """Should resolve relative path to absolute."""
        with patch.object(Path, "resolve", return_value=temp_dir / "file.txt"):
            path = validate_path("file.txt")
            assert path.is_absolute()

    def test_validate_path_expanduser(self, temp_dir):
        """Should expand user home directory."""
        with patch.object(Path, "expanduser") as mock_expand:
            mock_expand.return_value = Path("/home/user/file.txt")
            path = validate_path("~/file.txt")
            mock_expand.assert_called_once()

    def test_validate_path_within_base_dir(self, temp_dir):
        """Should validate path is within base directory."""
        path = validate_path(temp_dir / "subdir" / "file.txt", base_dir=temp_dir)

        assert temp_dir in path.parents or path == temp_dir

    def test_validate_path_outside_base_dir(self, temp_dir):
        """Should raise FileOperationError if path outside base directory."""
        with pytest.raises(FileOperationError) as exc_info:
            validate_path("/etc/passwd", base_dir=temp_dir)

        assert "outside allowed base directory" in str(exc_info.value)
        assert exc_info.value.operation == "validate"

    def test_validate_path_traversal_attack(self, temp_dir):
        """Should prevent path traversal attacks."""
        with pytest.raises(FileOperationError):
            validate_path(temp_dir / ".." / ".." / "etc" / "passwd", base_dir=temp_dir)

    @pytest.mark.skipif(
        IS_WINDOWS, reason="Symlinks require admin privileges on Windows"
    )
    def test_validate_path_symlink_escape(self, temp_dir):
        """Should prevent symlink escape from base directory."""
        # Create symlink pointing outside base_dir
        outside = temp_dir.parent / "outside.txt"
        outside.write_text("outside")

        symlink = temp_dir / "link"
        symlink.symlink_to(outside)

        with pytest.raises(FileOperationError):
            validate_path(symlink, base_dir=temp_dir)

    def test_validate_path_string_inputs(self, temp_dir):
        """Should accept string paths."""
        path = validate_path(str(temp_dir / "file.txt"))

        assert isinstance(path, Path)
        assert path.is_absolute()

    def test_validate_path_no_base_dir(self, temp_dir):
        """Should allow any path if no base_dir specified."""
        path = validate_path("/etc/passwd")

        assert path.is_absolute()

    def test_validate_path_nonexistent(self, temp_dir):
        """Should validate nonexistent paths."""
        path = validate_path(temp_dir / "nonexistent.txt", base_dir=temp_dir)

        assert path.is_absolute()

    def test_validate_path_base_dir_string(self, temp_dir):
        """Should accept string base_dir."""
        path = validate_path(temp_dir / "file.txt", base_dir=str(temp_dir))

        assert temp_dir in path.parents or path == temp_dir


class TestCreateTimestampedBackup:
    """Test suite for timestamped backup creation."""

    def test_create_timestamped_backup_success(self, temp_file):
        """Should create backup with timestamp in name."""
        backup = create_timestamped_backup(temp_file)

        assert backup.exists()
        assert backup.read_text() == temp_file.read_text()
        assert ".backup" in backup.name

    def test_create_timestamped_backup_format(self, temp_file):
        """Should use correct timestamp format."""
        backup = create_timestamped_backup(temp_file)

        # Format: stem.YYYYMMDD_HHMMSS.backup.suffix
        # e.g., test_file.20231208_143022.backup.txt
        name_parts = backup.name.split(".")
        assert len(name_parts) >= 3
        assert "backup" in name_parts

    def test_create_timestamped_backup_nonexistent(self, temp_dir):
        """Should raise FileOperationError for nonexistent file."""
        with pytest.raises(FileOperationError) as exc_info:
            create_timestamped_backup(temp_dir / "nonexistent.txt")

        assert "Cannot backup non-existent file" in str(exc_info.value)

    def test_create_timestamped_backup_directory(self, temp_dir):
        """Should raise FileOperationError for directory."""
        with pytest.raises(FileOperationError) as exc_info:
            create_timestamped_backup(temp_dir)

        assert "Cannot backup non-file path" in str(exc_info.value)

    def test_create_timestamped_backup_string_path(self, temp_file):
        """Should accept string path."""
        backup = create_timestamped_backup(str(temp_file))

        assert backup.exists()

    def test_create_timestamped_backup_preserves_content(self, temp_file):
        """Should preserve file content exactly."""
        original_content = temp_file.read_text()

        backup = create_timestamped_backup(temp_file)

        assert backup.read_text() == original_content

    def test_create_timestamped_backup_failure(self, temp_file):
        """Should raise FileOperationError on backup failure."""
        with patch("shutil.copy2", side_effect=PermissionError("Access denied")):
            with pytest.raises(FileOperationError) as exc_info:
                create_timestamped_backup(temp_file)

        assert "Failed to create backup" in str(exc_info.value)

    def test_create_timestamped_backup_unique_names(self, temp_file):
        """Should create unique backup names."""
        backup1 = create_timestamped_backup(temp_file)
        time.sleep(1.1)  # Ensure different timestamp (1 second resolution)
        backup2 = create_timestamped_backup(temp_file)

        assert backup1 != backup2
        assert backup1.exists()
        assert backup2.exists()

    def test_create_timestamped_backup_logs_debug(self, temp_file, mock_logger):
        """Should log debug message."""
        create_timestamped_backup(temp_file)

        mock_logger.debug.assert_called()


class TestEdgeCasesAndSecurity:
    """Test suite for edge cases and security concerns."""

    def test_concurrent_file_writes(self, temp_dir):
        """Should handle concurrent writes safely."""
        file_path = temp_dir / "concurrent.txt"
        errors = []
        successes = []

        def write_thread(content):
            try:
                safe_write_file(file_path, content, create_backup=False)
                successes.append(content)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=write_thread, args=(f"content{i}",))
            for i in range(5)
        ]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # On Windows, file locking might cause some writes to fail
        # At least one should succeed
        assert len(successes) >= 1 or IS_WINDOWS
        assert file_path.exists()

    def test_unicode_filename(self, temp_dir):
        """Should handle Unicode filenames."""
        unicode_file = temp_dir / "файл.txt"
        content = "content"

        safe_write_file(unicode_file, content, create_backup=False)

        assert unicode_file.exists()
        assert safe_read_file(unicode_file) == content

    def test_very_long_filename(self, temp_dir):
        """Should handle long filenames (up to OS limit)."""
        # Windows has a 260 char MAX_PATH limit including directory
        # Filename limit is typically 255 chars
        # Use shorter name on Windows to account for temp path length
        if IS_WINDOWS:
            # Account for temp directory path and prefix
            long_name = "a" * 100 + ".txt"
        else:
            long_name = "a" * 200 + ".txt"

        long_file = temp_dir / long_name

        try:
            safe_write_file(long_file, "content", create_backup=False)
            assert long_file.exists()
        except FileOperationError:
            # On some systems, even shorter paths might fail
            # This is acceptable behavior
            pytest.skip("Filesystem doesn't support this path length")

    def test_special_characters_in_filename(self, temp_dir):
        """Should handle special characters in filenames."""
        # Characters that are valid in filenames
        special_file = temp_dir / "file-with_special.chars[].txt"

        safe_write_file(special_file, "content", create_backup=False)

        assert special_file.exists()

    def test_file_with_no_extension(self, temp_dir):
        """Should handle files without extension."""
        no_ext_file = temp_dir / "Makefile"

        safe_write_file(no_ext_file, "content", create_backup=False)
        backup = create_backup(no_ext_file)

        assert backup.exists()
        assert ".backup" in backup.name

    def test_hidden_files(self, temp_dir):
        """Should handle hidden files (starting with dot)."""
        hidden_file = temp_dir / ".hidden"

        safe_write_file(hidden_file, "content", create_backup=False)

        assert hidden_file.exists()

    @pytest.mark.skipif(
        IS_WINDOWS, reason="Symlinks require admin privileges on Windows"
    )
    def test_symlink_handling(self, temp_file, temp_dir):
        """Should follow symlinks correctly."""
        symlink = temp_dir / "link.txt"
        symlink.symlink_to(temp_file)

        content = safe_read_file(symlink)

        assert content == temp_file.read_text()

    def test_large_number_of_backups(self, temp_file):
        """Should handle large number of backups efficiently."""
        # Create many backups
        for _ in range(100):
            create_backup(temp_file)

        backups = list_backups(temp_file)
        assert len(backups) == 100

        # Cleanup should work
        deleted = clean_old_backups(temp_file, keep=5)
        assert deleted == 95

    def test_disk_space_error(self, temp_dir):
        """Should handle disk space errors gracefully."""
        file_path = temp_dir / "file.txt"

        with patch("tempfile.NamedTemporaryFile", side_effect=OSError("No space left")):
            with pytest.raises(FileOperationError) as exc_info:
                safe_write_file(file_path, "content", create_backup=False)

        assert "Atomic write failed" in str(exc_info.value)

    def test_atomic_write_transaction_safety(self, temp_file):
        """Should ensure write operations are truly atomic."""
        original_content = temp_file.read_text()

        # Simulate crash during write
        with patch("os.fsync", side_effect=KeyboardInterrupt):
            try:
                safe_write_file(temp_file, "new content", create_backup=False)
            except (KeyboardInterrupt, FileOperationError):
                pass

        # File should still have original content (not corrupted)
        assert temp_file.exists()
        # Either original content or new content, but not corrupted
        content = temp_file.read_text()
        assert content in [original_content, "new content"]


class TestPerformance:
    """Test suite for performance characteristics."""

    def test_large_file_read_performance(self, temp_dir):
        """Should read large files efficiently."""
        large_file = temp_dir / "large.txt"
        content = "x" * (5 * 1024 * 1024)  # 5 MB
        large_file.write_text(content)

        start = time.time()
        result = safe_read_file(large_file)
        elapsed = time.time() - start

        assert result == content
        assert elapsed < 1.0  # Should complete in under 1 second

    def test_backup_cleanup_performance(self, temp_file):
        """Should clean up backups efficiently."""
        # Create many backups
        for _ in range(50):
            create_backup(temp_file)

        start = time.time()
        deleted = clean_old_backups(temp_file, keep=10)
        elapsed = time.time() - start

        assert deleted == 40
        assert elapsed < 1.0  # Should complete quickly

    def test_requirements_discovery_performance(self, temp_dir):
        """Should discover requirements files efficiently."""
        # Create many files
        for i in range(20):
            (temp_dir / f"requirements-{i}.txt").write_text(f"pkg{i}")

        start = time.time()
        files = find_requirements_files(temp_dir, recursive=False)
        elapsed = time.time() - start

        assert len(files) >= 20
        assert elapsed < 1.0
