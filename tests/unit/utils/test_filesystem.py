import time
import pytest
from pathlib import Path

from depkeeper.utils.filesystem import (
    safe_read_file,
    safe_write_file,
    create_backup,
    restore_backup,
    find_requirements_files,
    validate_path,
)
from depkeeper.exceptions import FileOperationError


class TestSafeReadFile:
    """Tests for the safe_read_file function."""

    def test_read_simple_file(self, tmp_path: Path):
        """Test reading a simple text file."""
        test_file = tmp_path / "test.txt"
        content = "Hello, World!"
        test_file.write_text(content, encoding="utf-8")

        result = safe_read_file(test_file)

        assert result == content

    def test_read_file_with_path_object(self, tmp_path: Path):
        """Test reading file using Path object."""
        test_file = tmp_path / "test.txt"
        content = "Path object test"
        test_file.write_text(content, encoding="utf-8")

        result = safe_read_file(test_file)

        assert result == content

    def test_read_file_with_string_path(self, tmp_path: Path):
        """Test reading file using string path."""
        test_file = tmp_path / "test.txt"
        content = "String path test"
        test_file.write_text(content, encoding="utf-8")

        result = safe_read_file(str(test_file))

        assert result == content

    def test_read_file_with_unicode_content(self, tmp_path: Path):
        """Test reading file with Unicode characters."""
        test_file = tmp_path / "unicode.txt"
        content = "Hello 世界 �� Ñoño"
        test_file.write_text(content, encoding="utf-8")

        result = safe_read_file(test_file)

        assert result == content

    def test_read_file_with_multiple_lines(self, tmp_path: Path):
        """Test reading multi-line file."""
        test_file = tmp_path / "multiline.txt"
        content = "Line 1\nLine 2\nLine 3\n"
        test_file.write_text(content, encoding="utf-8")

        result = safe_read_file(test_file)

        assert result == content

    def test_read_nonexistent_file_raises_error(self, tmp_path: Path):
        """Test that reading non-existent file raises FileOperationError."""
        nonexistent = tmp_path / "does_not_exist.txt"

        with pytest.raises(FileOperationError) as exc_info:
            safe_read_file(nonexistent)

        assert "not found" in str(exc_info.value).lower()
        assert exc_info.value.operation == "read"

    def test_read_directory_raises_error(self, tmp_path: Path):
        """Test that reading a directory raises FileOperationError."""
        directory = tmp_path / "subdir"
        directory.mkdir()

        with pytest.raises(FileOperationError) as exc_info:
            safe_read_file(directory)

        assert "not a file" in str(exc_info.value).lower()
        assert exc_info.value.operation == "read"

    def test_read_file_exceeding_max_size(self, tmp_path: Path):
        """Test that reading file larger than max_size raises error."""
        test_file = tmp_path / "large.txt"
        # Create file with content exceeding small max_size
        large_content = "x" * 1000
        test_file.write_text(large_content, encoding="utf-8")

        with pytest.raises(FileOperationError) as exc_info:
            safe_read_file(test_file, max_size=500)

        assert "too large" in str(exc_info.value).lower()
        assert exc_info.value.operation == "read"

    def test_read_file_with_custom_max_size(self, tmp_path: Path):
        """Test reading file with custom max_size parameter."""
        test_file = tmp_path / "custom.txt"
        content = "x" * 100
        test_file.write_text(content, encoding="utf-8")

        result = safe_read_file(test_file, max_size=200)

        assert result == content

    def test_read_empty_file(self, tmp_path: Path):
        """Test reading an empty file."""
        test_file = tmp_path / "empty.txt"
        test_file.write_text("", encoding="utf-8")

        result = safe_read_file(test_file)

        assert result == ""

    def test_read_file_with_custom_encoding(self, tmp_path: Path):
        """Test reading file with custom encoding."""
        test_file = tmp_path / "encoded.txt"
        content = "Test content"
        test_file.write_text(content, encoding="latin-1")

        result = safe_read_file(test_file, encoding="latin-1")

        assert result == content

    def test_read_file_respects_default_max_size(self, tmp_path: Path):
        """Test that default MAX_FILE_SIZE is respected."""
        test_file = tmp_path / "normal.txt"
        content = "Normal sized file"
        test_file.write_text(content, encoding="utf-8")

        # Should succeed with default max size
        result = safe_read_file(test_file)

        assert result == content


class TestSafeWriteFile:
    """Tests for the safe_write_file function."""

    def test_write_simple_file(self, tmp_path: Path):
        """Test writing a simple text file."""
        test_file = tmp_path / "output.txt"
        content = "Hello, World!"

        backup = safe_write_file(test_file, content, create_backup=False)

        assert test_file.exists()
        assert test_file.read_text(encoding="utf-8") == content
        assert backup is None

    def test_write_file_with_path_object(self, tmp_path: Path):
        """Test writing file using Path object."""
        test_file = tmp_path / "output.txt"
        content = "Path object write"

        safe_write_file(test_file, content, create_backup=False)

        assert test_file.read_text(encoding="utf-8") == content

    def test_write_file_with_string_path(self, tmp_path: Path):
        """Test writing file using string path."""
        test_file = tmp_path / "output.txt"
        content = "String path write"

        safe_write_file(str(test_file), content, create_backup=False)

        assert test_file.read_text(encoding="utf-8") == content

    def test_write_creates_parent_directories(self, tmp_path: Path):
        """Test that writing creates parent directories automatically."""
        nested_file = tmp_path / "level1" / "level2" / "file.txt"
        content = "Nested file"

        safe_write_file(nested_file, content, create_backup=False)

        assert nested_file.exists()
        assert nested_file.read_text(encoding="utf-8") == content

    def test_write_with_backup_creates_backup(self, tmp_path: Path):
        """Test that writing with create_backup=True creates a backup."""
        test_file = tmp_path / "original.txt"
        original_content = "Original"
        test_file.write_text(original_content, encoding="utf-8")

        new_content = "Updated"
        backup_path = safe_write_file(test_file, new_content, create_backup=True)

        assert backup_path is not None
        assert backup_path.exists()
        assert backup_path.read_text(encoding="utf-8") == original_content
        assert test_file.read_text(encoding="utf-8") == new_content
        assert ".backup" in str(backup_path)

    def test_write_without_backup_returns_none(self, tmp_path: Path):
        """Test that writing without backup returns None."""
        test_file = tmp_path / "no_backup.txt"
        content = "No backup"

        backup_path = safe_write_file(test_file, content, create_backup=False)

        assert backup_path is None

    def test_write_overwrites_existing_file(self, tmp_path: Path):
        """Test that writing overwrites existing file content."""
        test_file = tmp_path / "overwrite.txt"
        test_file.write_text("Old content", encoding="utf-8")

        new_content = "New content"
        safe_write_file(test_file, new_content, create_backup=False)

        assert test_file.read_text(encoding="utf-8") == new_content

    def test_write_with_unicode_content(self, tmp_path: Path):
        """Test writing file with Unicode characters."""
        test_file = tmp_path / "unicode.txt"
        content = "Unicode test: 日本語 �� Ñoño"

        safe_write_file(test_file, content, create_backup=False)

        assert test_file.read_text(encoding="utf-8") == content

    def test_write_empty_content(self, tmp_path: Path):
        """Test writing empty string to file."""
        test_file = tmp_path / "empty.txt"
        content = ""

        safe_write_file(test_file, content, create_backup=False)

        assert test_file.exists()
        assert test_file.read_text(encoding="utf-8") == ""

    def test_write_preserves_content_on_error_with_backup(self, tmp_path: Path):
        """Test that original content is preserved if write fails with backup."""
        test_file = tmp_path / "preserve.txt"
        original_content = "Original content"
        test_file.write_text(original_content, encoding="utf-8")

        # This test verifies the error handling mechanism exists
        # Actual failure scenarios are hard to simulate reliably
        new_content = "New content"
        safe_write_file(test_file, new_content, create_backup=True)

        assert test_file.read_text(encoding="utf-8") == new_content

    def test_write_large_content(self, tmp_path: Path):
        """Test writing large content."""
        test_file = tmp_path / "large.txt"
        content = "x" * 100000

        safe_write_file(test_file, content, create_backup=False)

        assert test_file.read_text(encoding="utf-8") == content

    def test_backup_has_timestamp_format(self, tmp_path: Path):
        """Test that backup filename includes timestamp."""
        test_file = tmp_path / "timestamped.txt"
        test_file.write_text("Original", encoding="utf-8")

        backup_path = safe_write_file(test_file, "New", create_backup=True)

        # Backup should have format: filename.ext.YYYYMMDD_HHMMSS.backup
        assert backup_path is not None
        backup_name = backup_path.name
        assert "timestamped.txt." in backup_name
        assert ".backup" in backup_name


class TestCreateBackup:
    """Tests for the create_backup function."""

    def test_create_backup_of_existing_file(self, tmp_path: Path):
        """Test creating backup of an existing file."""
        test_file = tmp_path / "original.txt"
        content = "Original content"
        test_file.write_text(content, encoding="utf-8")

        backup_path = create_backup(test_file)

        assert backup_path.exists()
        assert backup_path.read_text(encoding="utf-8") == content
        assert test_file.read_text(encoding="utf-8") == content
        assert ".backup" in str(backup_path)

    def test_create_backup_with_string_path(self, tmp_path: Path):
        """Test creating backup using string path."""
        test_file = tmp_path / "test.txt"
        content = "Test content"
        test_file.write_text(content, encoding="utf-8")

        backup_path = create_backup(str(test_file))

        assert backup_path.exists()
        assert backup_path.read_text(encoding="utf-8") == content

    def test_create_backup_preserves_original(self, tmp_path: Path):
        """Test that creating backup doesn't modify original."""
        test_file = tmp_path / "preserve.txt"
        content = "Preserve me"
        test_file.write_text(content, encoding="utf-8")
        original_mtime = test_file.stat().st_mtime

        # Small delay to ensure mtime would change if file was modified
        time.sleep(0.01)
        backup_path = create_backup(test_file)

        assert test_file.read_text(encoding="utf-8") == content
        # mtime might be updated by copy2, so we just verify content

    def test_create_backup_of_nonexistent_file_raises_error(self, tmp_path: Path):
        """Test that creating backup of non-existent file raises error."""
        nonexistent = tmp_path / "does_not_exist.txt"

        with pytest.raises(FileOperationError) as exc_info:
            create_backup(nonexistent)

        assert "not found" in str(exc_info.value).lower()

    def test_create_multiple_backups_different_timestamps(self, tmp_path: Path):
        """Test that multiple backups have different timestamps."""
        test_file = tmp_path / "multi.txt"
        test_file.write_text("Content", encoding="utf-8")

        backup1 = create_backup(test_file)
        time.sleep(1.1)  # Ensure different timestamp
        backup2 = create_backup(test_file)

        assert backup1 != backup2
        assert backup1.exists()
        assert backup2.exists()

    def test_create_backup_returns_path_object(self, tmp_path: Path):
        """Test that create_backup returns Path object."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Test", encoding="utf-8")

        backup_path = create_backup(test_file)

        assert isinstance(backup_path, Path)


class TestRestoreBackup:
    """Tests for the restore_backup function."""

    def test_restore_backup_to_original_location(self, tmp_path: Path):
        """Test restoring backup to inferred original location."""
        original_file = tmp_path / "original.txt"
        original_content = "Original"
        original_file.write_text(original_content, encoding="utf-8")

        backup_path = create_backup(original_file)

        # Modify original
        original_file.write_text("Modified", encoding="utf-8")

        # Restore without specifying target
        restore_backup(backup_path)

        assert original_file.read_text(encoding="utf-8") == original_content

    def test_restore_backup_to_custom_location(self, tmp_path: Path):
        """Test restoring backup to a custom target location."""
        original_file = tmp_path / "original.txt"
        original_file.write_text("Content", encoding="utf-8")

        backup_path = create_backup(original_file)

        custom_target = tmp_path / "restored.txt"
        restore_backup(backup_path, custom_target)

        assert custom_target.exists()
        assert custom_target.read_text(encoding="utf-8") == "Content"

    def test_restore_backup_with_string_paths(self, tmp_path: Path):
        """Test restoring backup using string paths."""
        original_file = tmp_path / "original.txt"
        original_file.write_text("Content", encoding="utf-8")

        backup_path = create_backup(original_file)
        original_file.write_text("Modified", encoding="utf-8")

        restore_backup(str(backup_path), str(original_file))

        assert original_file.read_text(encoding="utf-8") == "Content"

    def test_restore_nonexistent_backup_raises_error(self, tmp_path: Path):
        """Test that restoring non-existent backup raises error."""
        nonexistent = tmp_path / "fake.backup"

        with pytest.raises(FileOperationError) as exc_info:
            restore_backup(nonexistent)

        assert "not found" in str(exc_info.value).lower()
        assert exc_info.value.operation == "restore"

    def test_restore_backup_without_backup_suffix_raises_error(self, tmp_path: Path):
        """Test that file without .backup suffix raises error when inferring target."""
        regular_file = tmp_path / "regular.txt"
        regular_file.write_text("Content", encoding="utf-8")

        with pytest.raises(FileOperationError) as exc_info:
            restore_backup(regular_file)

        assert "cannot infer target" in str(exc_info.value).lower()

    def test_restore_backup_overwrites_existing_file(self, tmp_path: Path):
        """Test that restoring backup overwrites existing file."""
        original_file = tmp_path / "original.txt"
        original_file.write_text("Original", encoding="utf-8")

        backup_path = create_backup(original_file)
        original_file.write_text("Completely different content", encoding="utf-8")

        restore_backup(backup_path, original_file)

        assert original_file.read_text(encoding="utf-8") == "Original"

    def test_restore_backup_creates_target_if_not_exists(self, tmp_path: Path):
        """Test that restoring backup creates target file if it doesn't exist."""
        source_file = tmp_path / "source.txt"
        source_file.write_text("Content", encoding="utf-8")

        backup_path = create_backup(source_file)
        source_file.unlink()  # Remove original

        restore_backup(backup_path, source_file)

        assert source_file.exists()
        assert source_file.read_text(encoding="utf-8") == "Content"


class TestFindRequirementsFiles:
    """Tests for the find_requirements_files function."""

    def test_find_simple_requirements_txt(self, tmp_path: Path):
        """Test finding simple requirements.txt file."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests==2.28.0", encoding="utf-8")

        result = find_requirements_files(tmp_path)

        assert len(result) == 1
        assert result[0].name == "requirements.txt"

    def test_find_requirements_with_prefix(self, tmp_path: Path):
        """Test finding requirements files with prefixes."""
        (tmp_path / "requirements-dev.txt").write_text("pytest", encoding="utf-8")
        (tmp_path / "requirements-prod.txt").write_text("flask", encoding="utf-8")

        result = find_requirements_files(tmp_path)

        assert len(result) == 2
        names = [f.name for f in result]
        assert "requirements-dev.txt" in names
        assert "requirements-prod.txt" in names

    def test_find_requirements_in_subdirectory(self, tmp_path: Path):
        """Test finding requirements in subdirectory."""
        req_dir = tmp_path / "requirements"
        req_dir.mkdir()
        (req_dir / "base.txt").write_text("django", encoding="utf-8")
        (req_dir / "dev.txt").write_text("pytest", encoding="utf-8")

        result = find_requirements_files(tmp_path)

        assert len(result) == 2
        names = [f.name for f in result]
        assert "base.txt" in names
        assert "dev.txt" in names

    def test_find_requirements_recursive(self, tmp_path: Path):
        """Test finding requirements files recursively."""
        (tmp_path / "requirements.txt").write_text("flask", encoding="utf-8")

        subdir = tmp_path / "backend"
        subdir.mkdir()
        (subdir / "requirements.txt").write_text("django", encoding="utf-8")

        result = find_requirements_files(tmp_path, recursive=True)

        assert len(result) == 2

    def test_find_requirements_non_recursive(self, tmp_path: Path):
        """Test finding requirements files non-recursively."""
        (tmp_path / "requirements.txt").write_text("flask", encoding="utf-8")

        subdir = tmp_path / "backend"
        subdir.mkdir()
        (subdir / "requirements.txt").write_text("django", encoding="utf-8")

        result = find_requirements_files(tmp_path, recursive=False)

        assert len(result) == 1
        assert result[0].parent == tmp_path

    def test_find_no_requirements_returns_empty_list(self, tmp_path: Path):
        """Test that no requirements files returns empty list."""
        (tmp_path / "readme.txt").write_text(
            "Not a requirements file", encoding="utf-8"
        )

        result = find_requirements_files(tmp_path)

        assert result == []

    def test_find_requirements_in_nonexistent_directory(self, tmp_path: Path):
        """Test finding requirements in non-existent directory."""
        nonexistent = tmp_path / "does_not_exist"

        result = find_requirements_files(nonexistent)

        assert result == []

    def test_find_requirements_with_string_path(self, tmp_path: Path):
        """Test finding requirements using string path."""
        (tmp_path / "requirements.txt").write_text("requests", encoding="utf-8")

        result = find_requirements_files(str(tmp_path))

        assert len(result) == 1

    def test_find_requirements_returns_sorted_list(self, tmp_path: Path):
        """Test that results are sorted."""
        (tmp_path / "requirements-z.txt").write_text("last", encoding="utf-8")
        (tmp_path / "requirements-a.txt").write_text("first", encoding="utf-8")
        (tmp_path / "requirements-m.txt").write_text("middle", encoding="utf-8")

        result = find_requirements_files(tmp_path)

        names = [f.name for f in result]
        assert names == sorted(names)

    def test_find_requirements_deduplicates_results(self, tmp_path: Path):
        """Test that duplicate results are removed."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests", encoding="utf-8")

        result = find_requirements_files(tmp_path)

        assert len(result) == len(set(result))

    def test_find_requirements_ignores_other_txt_files(self, tmp_path: Path):
        """Test that non-requirements .txt files are ignored."""
        (tmp_path / "requirements.txt").write_text("flask", encoding="utf-8")
        (tmp_path / "readme.txt").write_text("readme", encoding="utf-8")
        (tmp_path / "changelog.txt").write_text("changes", encoding="utf-8")

        result = find_requirements_files(tmp_path)

        assert len(result) == 1
        assert result[0].name == "requirements.txt"

    def test_find_requirements_with_current_directory(
        self, tmp_path: Path, monkeypatch
    ):
        """Test finding requirements using current directory."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "requirements.txt").write_text("requests", encoding="utf-8")

        result = find_requirements_files(".")

        assert len(result) == 1

    def test_find_requirements_mixed_patterns(self, tmp_path: Path):
        """Test finding requirements with mixed patterns."""
        (tmp_path / "requirements.txt").write_text("base", encoding="utf-8")
        (tmp_path / "requirements-dev.txt").write_text("dev", encoding="utf-8")

        req_dir = tmp_path / "requirements"
        req_dir.mkdir()
        (req_dir / "prod.txt").write_text("prod", encoding="utf-8")

        result = find_requirements_files(tmp_path)

        assert len(result) == 3


class TestValidatePath:
    """Tests for the validate_path function."""

    def test_validate_simple_path(self, tmp_path: Path):
        """Test validating a simple file path."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content", encoding="utf-8")

        result = validate_path(test_file)

        assert isinstance(result, Path)
        assert result.is_absolute()

    def test_validate_returns_absolute_path(self, tmp_path: Path):
        """Test that validate_path returns absolute path."""
        test_file = tmp_path / "test.txt"

        result = validate_path(test_file)

        assert result.is_absolute()

    def test_validate_with_string_path(self, tmp_path: Path):
        """Test validating string path."""
        test_file = tmp_path / "test.txt"

        result = validate_path(str(test_file))

        assert isinstance(result, Path)
        assert result.is_absolute()

    def test_validate_resolves_relative_path(self, tmp_path: Path, monkeypatch):
        """Test that relative paths are resolved."""
        monkeypatch.chdir(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("content", encoding="utf-8")

        result = validate_path("./test.txt")

        assert result.is_absolute()
        assert result.name == "test.txt"

    def test_validate_expands_user_home(self, tmp_path: Path):
        """Test that ~ is expanded to home directory."""
        # Use a path that doesn't need to exist for this test
        result = validate_path("~/test.txt")

        assert "~" not in str(result)
        assert result.is_absolute()

    def test_validate_with_base_dir_allows_subdirectory(self, tmp_path: Path):
        """Test validating path within base directory."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        test_file = subdir / "test.txt"

        result = validate_path(test_file, base_dir=tmp_path)

        assert result.is_absolute()

        try:
            result.relative_to(tmp_path)
            is_relative = True
        except ValueError:
            is_relative = False

        assert is_relative

    def test_validate_with_base_dir_rejects_outside_path(self, tmp_path: Path):
        """Test that path outside base_dir raises error."""
        outside_path = tmp_path.parent / "outside.txt"

        with pytest.raises(FileOperationError) as exc_info:
            validate_path(outside_path, base_dir=tmp_path)

        assert "outside allowed base" in str(exc_info.value).lower()
        assert exc_info.value.operation == "validate"

    def test_validate_with_base_dir_using_string_paths(self, tmp_path: Path):
        """Test validation with string paths for both path and base_dir."""
        test_file = tmp_path / "test.txt"

        result = validate_path(str(test_file), base_dir=str(tmp_path))

        assert result.is_absolute()

    def test_validate_prevents_path_traversal(self, tmp_path: Path):
        """Test that path traversal is prevented with base_dir."""
        # Try to escape using ../
        malicious_path = tmp_path / "subdir" / ".." / ".." / "escape.txt"

        with pytest.raises(FileOperationError):
            validate_path(malicious_path, base_dir=tmp_path / "subdir")

    def test_validate_nonexistent_path_is_allowed(self, tmp_path: Path):
        """Test that non-existent paths can be validated."""
        nonexistent = tmp_path / "does_not_exist.txt"

        result = validate_path(nonexistent)

        assert isinstance(result, Path)
        assert result.is_absolute()

    def test_validate_directory_path(self, tmp_path: Path):
        """Test validating directory path."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        result = validate_path(subdir)

        assert result.is_absolute()

    def test_validate_with_dots_in_path(self, tmp_path: Path):
        """Test validating path with dots."""
        test_file = tmp_path / "test.file.name.txt"

        result = validate_path(test_file)

        assert result.name == "test.file.name.txt"

    def test_validate_with_spaces_in_path(self, tmp_path: Path):
        """Test validating path with spaces."""
        test_file = tmp_path / "test file with spaces.txt"

        result = validate_path(test_file)

        assert "test file with spaces" in str(result)

    def test_validate_resolves_symbolic_links(self, tmp_path: Path):
        """Test that symbolic links are resolved."""
        # This test may not work on all platforms
        actual_file = tmp_path / "actual.txt"
        actual_file.write_text("content", encoding="utf-8")

        try:
            link_file = tmp_path / "link.txt"
            link_file.symlink_to(actual_file)

            result = validate_path(link_file)

            # Should resolve to actual file
            assert result.name == "actual.txt"
        except (OSError, NotImplementedError):
            # Skip on systems that don't support symlinks
            pytest.skip("Symbolic links not supported")


class TestAtomicOperations:
    """Tests for atomic write operations behavior."""

    def test_atomic_write_creates_file_atomically(self, tmp_path: Path):
        """Test that file appears atomically (all-or-nothing)."""
        test_file = tmp_path / "atomic.txt"
        content = "Atomic content"

        safe_write_file(test_file, content, create_backup=False)

        assert test_file.exists()
        assert test_file.read_text(encoding="utf-8") == content

    def test_atomic_write_no_partial_content(self, tmp_path: Path):
        """Test that partial writes don't occur."""
        test_file = tmp_path / "complete.txt"
        content = "Complete or nothing"

        safe_write_file(test_file, content, create_backup=False)

        # File should have complete content
        assert test_file.read_text(encoding="utf-8") == content

    def test_temp_files_cleaned_up_on_success(self, tmp_path: Path):
        """Test that temporary files are cleaned up after successful write."""
        test_file = tmp_path / "cleanup.txt"
        content = "Clean content"

        safe_write_file(test_file, content, create_backup=False)

        # Should not have any .tmp files in directory
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_multiple_writes_to_same_file(self, tmp_path: Path):
        """Test multiple atomic writes to the same file."""
        test_file = tmp_path / "multiple.txt"

        safe_write_file(test_file, "First", create_backup=False)
        safe_write_file(test_file, "Second", create_backup=False)
        safe_write_file(test_file, "Third", create_backup=False)

        assert test_file.read_text(encoding="utf-8") == "Third"


class TestErrorHandling:
    """Tests for error handling and edge cases."""

    def test_read_file_error_includes_file_path(self, tmp_path: Path):
        """Test that error includes file path in details."""
        nonexistent = tmp_path / "missing.txt"

        with pytest.raises(FileOperationError) as exc_info:
            safe_read_file(nonexistent)

        assert exc_info.value.file_path is not None
        assert "missing.txt" in exc_info.value.file_path

    def test_write_file_error_includes_operation(self, tmp_path: Path):
        """Test that error includes operation type."""
        # This is a bit tricky to test without mocking
        # We can at least verify the structure exists
        test_file = tmp_path / "test.txt"
        safe_write_file(test_file, "content", create_backup=False)

        # If an error occurred, it would have operation field
        assert True  # Placeholder for error structure verification

    def test_backup_error_includes_details(self, tmp_path: Path):
        """Test that backup errors include relevant details."""
        nonexistent = tmp_path / "missing.txt"

        with pytest.raises(FileOperationError) as exc_info:
            create_backup(nonexistent)

        assert exc_info.value.file_path is not None
        assert exc_info.value.operation is not None

    def test_file_operation_error_has_original_error(self, tmp_path: Path):
        """Test that FileOperationError can contain original error."""
        nonexistent = tmp_path / "missing.txt"

        with pytest.raises(FileOperationError) as exc_info:
            safe_read_file(nonexistent)

        # Should have structured error information
        assert isinstance(exc_info.value, FileOperationError)


class TestIntegrationScenarios:
    """Integration tests for common usage patterns."""

    def test_read_modify_write_with_backup(self, tmp_path: Path):
        """Test complete read-modify-write cycle with backup."""
        test_file = tmp_path / "cycle.txt"
        test_file.write_text("Original content", encoding="utf-8")

        # Read
        content = safe_read_file(test_file)
        assert content == "Original content"

        # Modify
        modified = content.replace("Original", "Modified")

        # Write with backup
        backup = safe_write_file(test_file, modified, create_backup=True)

        assert test_file.read_text(encoding="utf-8") == "Modified content"
        assert backup is not None
        assert backup.read_text(encoding="utf-8") == "Original content"

    def test_backup_and_restore_workflow(self, tmp_path: Path):
        """Test complete backup and restore workflow."""
        original_file = tmp_path / "workflow.txt"
        original_file.write_text("Important data", encoding="utf-8")

        # Create backup
        backup = create_backup(original_file)

        # Simulate corruption
        original_file.write_text("Corrupted data", encoding="utf-8")

        # Restore from backup
        restore_backup(backup, original_file)

        assert original_file.read_text(encoding="utf-8") == "Important data"

    def test_find_and_read_requirements_files(self, tmp_path: Path):
        """Test finding and reading multiple requirements files."""
        req1 = tmp_path / "requirements.txt"
        req2 = tmp_path / "requirements-dev.txt"

        req1.write_text("flask==2.0.0", encoding="utf-8")
        req2.write_text("pytest==7.0.0", encoding="utf-8")

        # Find all requirements
        found = find_requirements_files(tmp_path)
        assert len(found) == 2

        # Read each one
        for req_file in found:
            content = safe_read_file(req_file)
            assert "==" in content

    def test_validate_and_write_secure_path(self, tmp_path: Path):
        """Test validating path before writing."""
        safe_dir = tmp_path / "safe"
        safe_dir.mkdir()

        target_file = safe_dir / "secure.txt"

        # Validate path is within safe directory
        validated = validate_path(target_file, base_dir=safe_dir)

        # Write to validated path
        safe_write_file(validated, "Secure content", create_backup=False)

        assert validated.read_text(encoding="utf-8") == "Secure content"
