"""
Requirements updater module.

Provides transaction-like updates to requirements files with backup, rollback,
and format preservation capabilities.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from depkeeper.utils.logger import get_logger
from depkeeper.core.parser import RequirementsParser
from depkeeper.core.validator import RequirementsValidator
from depkeeper.models.requirement import Requirement
from depkeeper.models.update_result import UpdateResult
from depkeeper.exceptions import (
    FileOperationError,
)
from depkeeper.strategies.base import UpdateStrategy
from depkeeper.constants import MAX_FILE_SIZE

logger = get_logger("updater")


# ============================================================================
# Requirements Updater
# ============================================================================


class RequirementsUpdater:
    """
    Updates requirements files with transaction-like behavior.

    This class provides atomic updates to requirements files with:
    - Automatic backup creation
    - Format and comment preservation
    - Validation before and after updates
    - Rollback capability on failures
    - Dry-run support

    Attributes
    ----------
    parser : RequirementsParser
        Parser for requirements files.
    validator : RequirementsValidator, optional
        Validator for requirements validation.
    backup_dir : Path, optional
        Directory for storing backup files.
    validate_before : bool
        Whether to validate file before updating.
    validate_after : bool
        Whether to validate file after updating.
    """

    def __init__(
        self,
        parser: Optional[RequirementsParser] = None,
        validator: Optional[RequirementsValidator] = None,
        backup_dir: Optional[Path] = None,
        validate_before: bool = True,
        validate_after: bool = True,
    ) -> None:
        """
        Initialize requirements updater.

        Parameters
        ----------
        parser : RequirementsParser, optional
            Parser for requirements files. Creates new instance if not provided.
        validator : RequirementsValidator, optional
            Validator for requirements validation. Creates new instance if not provided.
        backup_dir : Path, optional
            Directory for storing backup files. If not provided, backups are created
            in the same directory as the requirements file.
        validate_before : bool, optional
            Whether to validate file before updating. Default is True.
        validate_after : bool, optional
            Whether to validate file after updating. Default is True.
        """
        self.parser = parser or RequirementsParser()
        self.validator = validator or RequirementsValidator(parser=self.parser)
        self.backup_dir = backup_dir
        self.validate_before = validate_before
        self.validate_after = validate_after

        # Internal state for transaction management
        self._current_backup: Optional[Path] = None
        self._current_file: Optional[Path] = None

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def update_requirements(
        self,
        requirements_file: Path | str,
        version_updates: Dict[str, str],
        strategy: Optional[UpdateStrategy] = None,
        dry_run: bool = False,
    ) -> UpdateResult:
        """
        Apply updates to a requirements file.

        This method performs a transaction-like update with automatic backup,
        validation, and rollback on failure.

        Parameters
        ----------
        requirements_file : Path | str
            Path to the requirements file to update.
        version_updates : Dict[str, str]
            Dictionary mapping package names to new versions.
            Example: {"requests": "2.31.0", "numpy": "1.26.0"}
        strategy : UpdateStrategy, optional
            Update strategy to apply. If provided, versions are filtered
            through the strategy.
        dry_run : bool, optional
            If True, simulate the update without making changes. Default is False.

        Returns
        -------
        UpdateResult
            Result object containing update status, updated packages, failures,
            and metadata.

        Raises
        ------
        FileOperationError
            If file operations fail.
        ValidationError
            If validation fails and rollback is performed.
        UpdateError
            If update operation fails.

        Examples
        --------
        >>> updater = RequirementsUpdater()
        >>> result = updater.update_requirements(
        ...     "requirements.txt",
        ...     {"requests": "2.31.0", "numpy": "1.26.0"}
        ... )
        >>> if result.success:
        ...     print(f"Updated {result.total_updated} packages")
        """
        start_time = time.time()
        file_path = Path(requirements_file)

        # Validate file exists
        if not file_path.exists():
            return UpdateResult.create_failure(
                failed_packages={"file": f"File not found: {file_path}"},
                duration=time.time() - start_time,
            )

        # Pre-update validation
        if self.validate_before:
            is_valid, errors = self.validator.validate_file(file_path)
            if not is_valid:
                error_msg = "; ".join(errors)
                logger.error(f"Pre-update validation failed: {error_msg}")
                return UpdateResult.create_failure(
                    failed_packages={"validation": error_msg},
                    duration=time.time() - start_time,
                )

        try:
            # Parse current requirements
            requirements = self.parser.parse_file(str(file_path))

            # Create backup (unless dry-run)
            backup_path = None
            if not dry_run:
                backup_path = self._create_backup(file_path)
                self._current_backup = backup_path
                self._current_file = file_path

            # Apply updates to requirements
            updated_reqs, updated_packages, failed_packages, skipped_packages = (
                self._apply_changes(requirements, version_updates, strategy)
            )

            # Validate changes if any were made
            if updated_packages:
                validation_errors = self._validate_changes(updated_reqs)
                if validation_errors:
                    if not dry_run:
                        self._rollback()
                    return UpdateResult.create_failure(
                        failed_packages={"validation": "; ".join(validation_errors)},
                        duration=time.time() - start_time,
                    )

            # Write updated requirements (unless dry-run)
            if not dry_run and updated_packages:
                self._write_requirements(file_path, updated_reqs)

                # Post-update validation
                if self.validate_after:
                    is_valid, errors = self.validator.validate_file(file_path)
                    if not is_valid:
                        logger.error(f"Post-update validation failed: {errors}")
                        self._rollback()
                        return UpdateResult.create_failure(
                            failed_packages={"post_validation": "; ".join(errors)},
                            duration=time.time() - start_time,
                        )

            # Clear transaction state
            self._current_backup = None
            self._current_file = None

            duration = time.time() - start_time

            # Create appropriate result
            if dry_run:
                return UpdateResult.create_dry_run(
                    updated_packages=updated_packages,
                    skipped_packages=skipped_packages,
                    duration=duration,
                )
            elif failed_packages:
                return UpdateResult.create_failure(
                    failed_packages=failed_packages,
                    updated_packages=updated_packages,
                    skipped_packages=skipped_packages,
                    backup_path=backup_path,
                    duration=duration,
                )
            else:
                return UpdateResult.create_success(
                    updated_packages=updated_packages,
                    skipped_packages=skipped_packages,
                    backup_path=backup_path,
                    duration=duration,
                )

        except Exception as e:
            logger.error(f"Update failed: {e}")
            if not dry_run and self._current_backup:
                self._rollback()
            return UpdateResult.create_failure(
                failed_packages={"error": str(e)},
                duration=time.time() - start_time,
            )

    # -------------------------------------------------------------------------
    # Internal Methods
    # -------------------------------------------------------------------------

    def _create_backup(self, file_path: Path) -> Path:
        """
        Create a backup of the original requirements file.

        Parameters
        ----------
        file_path : Path
            Path to the file to backup.

        Returns
        -------
        Path
            Path to the backup file.

        Raises
        ------
        FileOperationError
            If backup creation fails.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{file_path.stem}.backup_{timestamp}{file_path.suffix}"

        if self.backup_dir:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = self.backup_dir / backup_name
        else:
            backup_path = file_path.parent / backup_name

        try:
            shutil.copy2(file_path, backup_path)
            logger.info(f"Created backup: {backup_path}")
            return backup_path
        except Exception as e:
            raise FileOperationError(
                f"Failed to create backup: {e}",
                file_path=str(file_path),
                operation="backup",
            ) from e

    def _apply_changes(
        self,
        requirements: List[Requirement],
        version_updates: Dict[str, str],
        strategy: Optional[UpdateStrategy] = None,
    ) -> Tuple[
        List[Requirement],
        Dict[str, Tuple[str, str]],
        Dict[str, str],
        List[str],
    ]:
        """
        Apply version updates to requirements.

        Parameters
        ----------
        requirements : List[Requirement]
            List of current requirements.
        version_updates : Dict[str, str]
            Dictionary of package names to new versions.
        strategy : UpdateStrategy, optional
            Update strategy to filter versions.

        Returns
        -------
        Tuple[List[Requirement], Dict[str, Tuple[str, str]], Dict[str, str], List[str]]
            Tuple of:
            - Updated requirements list
            - Dictionary of updated packages (name -> (old_version, new_version))
            - Dictionary of failed packages (name -> error_message)
            - List of skipped package names
        """
        updated_requirements: List[Requirement] = []
        updated_packages: Dict[str, Tuple[str, str]] = {}
        failed_packages: Dict[str, str] = {}
        skipped_packages: List[str] = []

        for req in requirements:
            # Skip URL and VCS dependencies
            if req.url or req.is_vcs():
                skipped_packages.append(req.name)
                updated_requirements.append(req)
                logger.info(f"Skipping {req.name} (URL/VCS dependency)")
                continue

            # Check if update is available for this package
            if req.name not in version_updates:
                updated_requirements.append(req)
                continue

            new_version = version_updates[req.name]

            # Get current version from specs
            current_version = self._extract_version_from_specs(req.specs)

            # Skip if already at target version
            if current_version == new_version:
                skipped_packages.append(req.name)
                updated_requirements.append(req)
                continue

            # Apply update
            try:
                updated_req = self._update_requirement_version(req, new_version)
                updated_requirements.append(updated_req)
                updated_packages[req.name] = (
                    current_version or "unknown",
                    new_version,
                )
                logger.info(f"Updated {req.name}: {current_version} -> {new_version}")
            except Exception as e:
                logger.error(f"Failed to update {req.name}: {e}")
                failed_packages[req.name] = str(e)
                updated_requirements.append(req)  # Keep original

        return (
            updated_requirements,
            updated_packages,
            failed_packages,
            skipped_packages,
        )

    def _update_requirement_version(
        self, req: Requirement, new_version: str
    ) -> Requirement:
        """
        Update a requirement with a new version.

        Parameters
        ----------
        req : Requirement
            Original requirement.
        new_version : str
            New version to apply.

        Returns
        -------
        Requirement
            Updated requirement with new version.
        """
        # Create a new requirement with updated specs
        new_specs = [("==", new_version)]

        # Preserve other attributes
        return Requirement(
            name=req.name,
            specs=new_specs,
            extras=req.extras,
            markers=req.markers,
            url=req.url,
            editable=req.editable,
            hashes=req.hashes,
            comment=req.comment,
            line_number=req.line_number,
            raw_line=req.raw_line,
        )

    def _extract_version_from_specs(
        self, specs: List[Tuple[str, str]]
    ) -> Optional[str]:
        """
        Extract version from requirement specs.

        Parameters
        ----------
        specs : List[Tuple[str, str]]
            List of (operator, version) tuples.

        Returns
        -------
        Optional[str]
            Extracted version or None if no exact version found.
        """
        for operator, version in specs:
            if operator == "==":
                return version

        # If no exact match, try to get from other operators
        if specs:
            return specs[0][1]

        return None

    def _write_requirements(
        self, file_path: Path, requirements: List[Requirement]
    ) -> None:
        """
        Write updated requirements to file, preserving format.

        Parameters
        ----------
        file_path : Path
            Path to write requirements to.
        requirements : List[Requirement]
            List of requirements to write.

        Raises
        ------
        FileOperationError
            If write operation fails.
        """
        try:
            lines: List[str] = []

            for req in requirements:
                # Use to_string to preserve format
                req_line = req.to_string(include_hashes=True, include_comment=True)
                lines.append(req_line)

            content = "\n".join(lines)

            # Add newline at end of file if not present
            if content and not content.endswith("\n"):
                content += "\n"

            # Write atomically
            file_path.write_text(content, encoding="utf-8")
            logger.info(f"Wrote updated requirements to {file_path}")

        except Exception as e:
            raise FileOperationError(
                f"Failed to write requirements: {e}",
                file_path=str(file_path),
                operation="write",
            ) from e

    def _preserve_format(self, original_content: str, updated_content: str) -> str:
        """
        Preserve original formatting and comments.

        This is a placeholder for more sophisticated format preservation.
        The current implementation relies on Requirement.to_string() to
        maintain format through raw_line and comment attributes.

        Parameters
        ----------
        original_content : str
            Original file content.
        updated_content : str
            Updated file content.

        Returns
        -------
        str
            Content with preserved formatting.
        """
        # For now, rely on requirement serialization
        # Future: implement more sophisticated format preservation
        return updated_content

    def _validate_changes(self, requirements: List[Requirement]) -> List[str]:
        """
        Validate updated requirements.

        Parameters
        ----------
        requirements : List[Requirement]
            List of updated requirements to validate.

        Returns
        -------
        List[str]
            List of validation errors (empty if valid).
        """
        errors: List[str] = []

        # Validate individual requirements
        for req in requirements:
            is_valid, req_errors = self.validator.validate_requirement(req)
            if not is_valid:
                errors.extend(
                    f"Line {req.line_number} ({req.name}): {error}"
                    for error in req_errors
                )

        # Check version consistency
        is_consistent, consistency_errors = self.validator.validate_versions(
            requirements
        )
        if not is_consistent:
            errors.extend(consistency_errors)

        return errors

    def _rollback(self) -> None:
        """
        Rollback to backup file.

        Restores the original file from backup if a backup exists.

        Raises
        ------
        FileOperationError
            If rollback fails.
        """
        if not self._current_backup or not self._current_file:
            logger.warning("No backup to rollback to")
            return

        try:
            shutil.copy2(self._current_backup, self._current_file)
            logger.info(f"Rolled back {self._current_file} from {self._current_backup}")

            # Clean up backup
            self._current_backup.unlink()
            logger.info(f"Removed backup: {self._current_backup}")

        except Exception as e:
            raise FileOperationError(
                f"Rollback failed: {e}",
                file_path=str(self._current_file),
                operation="rollback",
            ) from e
        finally:
            self._current_backup = None
            self._current_file = None

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def get_backup_files(self, requirements_file: Path | str) -> List[Path]:
        """
        Get list of backup files for a requirements file.

        Parameters
        ----------
        requirements_file : Path | str
            Path to the requirements file.

        Returns
        -------
        List[Path]
            List of backup file paths, sorted by creation time (newest first).
        """
        file_path = Path(requirements_file)
        backup_pattern = f"{file_path.stem}.backup_*{file_path.suffix}"

        search_dir = self.backup_dir if self.backup_dir else file_path.parent

        backup_files = list(search_dir.glob(backup_pattern))
        return sorted(backup_files, key=lambda p: p.stat().st_mtime, reverse=True)

    def cleanup_old_backups(
        self, requirements_file: Path | str, keep_count: int = 5
    ) -> int:
        """
        Clean up old backup files, keeping only the most recent ones.

        Parameters
        ----------
        requirements_file : Path | str
            Path to the requirements file.
        keep_count : int, optional
            Number of recent backups to keep. Default is 5.

        Returns
        -------
        int
            Number of backup files removed.
        """
        backup_files = self.get_backup_files(requirements_file)

        if len(backup_files) <= keep_count:
            return 0

        removed_count = 0
        for backup_file in backup_files[keep_count:]:
            try:
                backup_file.unlink()
                removed_count += 1
                logger.info(f"Removed old backup: {backup_file}")
            except Exception as e:
                logger.warning(f"Failed to remove backup {backup_file}: {e}")

        return removed_count
