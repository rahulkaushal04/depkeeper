"""
Update result model.

Represents the result of a requirements file update operation, including
success status, updated packages, failures, and change tracking.
"""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class UpdateResult:
    """
    Represents the result of a requirements file update operation.

    This class provides comprehensive tracking of update operations, including
    successful updates, failures, skipped packages, and metadata about the
    operation.

    Attributes
    ----------
    success : bool
        Overall success status of the update operation.
        True if all packages were updated successfully or no updates were needed.
        False if any package failed to update or validation failed.
    updated_packages : Dict[str, Tuple[str, str]]
        Dictionary mapping package names to (old_version, new_version) tuples.
        Example: {"requests": ("2.28.0", "2.31.0"), "numpy": ("1.24.0", "1.26.0")}
    failed_packages : Dict[str, str]
        Dictionary mapping package names to error messages for failed updates.
        Example: {"pandas": "Version conflict with numpy>=1.20", "scipy": "Network timeout"}
    skipped_packages : List[str]
        List of package names that were skipped during the update.
        Packages may be skipped due to pinned versions, URL dependencies, or
        strategy constraints.
    backup_path : Optional[Path]
        Path to the backup file created before applying changes.
        None if no backup was created (e.g., dry-run mode).
    duration : float
        Time taken for the update operation in seconds.
    changes_summary : str
        Human-readable summary of changes made during the update.
        Example: "Updated 5 packages, failed 1, skipped 2"
    """

    success: bool
    updated_packages: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    failed_packages: Dict[str, str] = field(default_factory=dict)
    skipped_packages: List[str] = field(default_factory=list)
    backup_path: Optional[Path] = None
    duration: float = 0.0
    changes_summary: str = ""

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

    @property
    def total_updated(self) -> int:
        """Number of packages successfully updated."""
        return len(self.updated_packages)

    @property
    def total_failed(self) -> int:
        """Number of packages that failed to update."""
        return len(self.failed_packages)

    @property
    def total_skipped(self) -> int:
        """Number of packages skipped during update."""
        return len(self.skipped_packages)

    @property
    def has_updates(self) -> bool:
        """True if any packages were updated."""
        return self.total_updated > 0

    @property
    def has_failures(self) -> bool:
        """True if any packages failed to update."""
        return self.total_failed > 0

    @property
    def has_backup(self) -> bool:
        """True if a backup file was created."""
        return self.backup_path is not None

    # -------------------------------------------------------------------------
    # Summary Methods
    # -------------------------------------------------------------------------

    def generate_summary(self) -> str:
        """
        Generate a human-readable summary of the update operation.

        Returns
        -------
        str
            Multi-line summary including counts of updated, failed, and
            skipped packages, along with duration.

        Examples
        --------
        >>> result = UpdateResult(success=True, updated_packages={"requests": ("2.28.0", "2.31.0")})
        >>> print(result.generate_summary())
        Update completed successfully in 1.23s
        Updated: 1 package(s)
        Failed: 0 package(s)
        Skipped: 0 package(s)
        """
        status = "successfully" if self.success else "with errors"
        summary_lines = [
            f"Update completed {status} in {self.duration:.2f}s",
            f"Updated: {self.total_updated} package(s)",
        ]

        if self.has_failures:
            summary_lines.append(f"Failed: {self.total_failed} package(s)")

        if self.total_skipped > 0:
            summary_lines.append(f"Skipped: {self.total_skipped} package(s)")

        if self.has_backup:
            summary_lines.append(f"Backup saved to: {self.backup_path}")

        return "\n".join(summary_lines)

    def get_updated_packages_list(self) -> List[str]:
        """
        Get a formatted list of updated packages with version changes.

        Returns
        -------
        List[str]
            List of strings in format "package_name: old_version -> new_version"

        Examples
        --------
        >>> result.get_updated_packages_list()
        ['requests: 2.28.0 -> 2.31.0', 'numpy: 1.24.0 -> 1.26.0']
        """
        return [
            f"{name}: {old} -> {new}"
            for name, (old, new) in sorted(self.updated_packages.items())
        ]

    def get_failed_packages_list(self) -> List[str]:
        """
        Get a formatted list of failed packages with error messages.

        Returns
        -------
        List[str]
            List of strings in format "package_name: error_message"

        Examples
        --------
        >>> result.get_failed_packages_list()
        ['pandas: Version conflict with numpy>=1.20', 'scipy: Network timeout']
        """
        return [
            f"{name}: {error}" for name, error in sorted(self.failed_packages.items())
        ]

    # -------------------------------------------------------------------------
    # Representations
    # -------------------------------------------------------------------------

    def __str__(self) -> str:
        """Return the changes summary or generate it if not set."""
        if self.changes_summary:
            return self.changes_summary
        return self.generate_summary()

    def __repr__(self) -> str:
        """Return detailed representation of the update result."""
        return (
            f"UpdateResult(success={self.success}, "
            f"updated={self.total_updated}, "
            f"failed={self.total_failed}, "
            f"skipped={self.total_skipped}, "
            f"duration={self.duration:.2f}s)"
        )

    # -------------------------------------------------------------------------
    # Builder Methods
    # -------------------------------------------------------------------------

    @classmethod
    def create_success(
        cls,
        updated_packages: Dict[str, Tuple[str, str]],
        skipped_packages: Optional[List[str]] = None,
        backup_path: Optional[Path] = None,
        duration: float = 0.0,
    ) -> UpdateResult:
        """
        Create a successful update result.

        Parameters
        ----------
        updated_packages : Dict[str, Tuple[str, str]]
            Dictionary of successfully updated packages.
        skipped_packages : List[str], optional
            List of skipped package names.
        backup_path : Path, optional
            Path to the backup file.
        duration : float, optional
            Duration of the update operation in seconds.

        Returns
        -------
        UpdateResult
            Update result instance with success=True.
        """
        result = cls(
            success=True,
            updated_packages=updated_packages,
            skipped_packages=skipped_packages or [],
            backup_path=backup_path,
            duration=duration,
        )
        result.changes_summary = result.generate_summary()
        return result

    @classmethod
    def create_failure(
        cls,
        failed_packages: Dict[str, str],
        updated_packages: Optional[Dict[str, Tuple[str, str]]] = None,
        skipped_packages: Optional[List[str]] = None,
        backup_path: Optional[Path] = None,
        duration: float = 0.0,
    ) -> UpdateResult:
        """
        Create a failed update result.

        Parameters
        ----------
        failed_packages : Dict[str, str]
            Dictionary of failed packages with error messages.
        updated_packages : Dict[str, Tuple[str, str]], optional
            Dictionary of packages that were updated before failure.
        skipped_packages : List[str], optional
            List of skipped package names.
        backup_path : Path, optional
            Path to the backup file (for rollback).
        duration : float, optional
            Duration of the update operation in seconds.

        Returns
        -------
        UpdateResult
            Update result instance with success=False.
        """
        result = cls(
            success=False,
            updated_packages=updated_packages or {},
            failed_packages=failed_packages,
            skipped_packages=skipped_packages or [],
            backup_path=backup_path,
            duration=duration,
        )
        result.changes_summary = result.generate_summary()
        return result

    @classmethod
    def create_dry_run(
        cls,
        updated_packages: Dict[str, Tuple[str, str]],
        skipped_packages: Optional[List[str]] = None,
        duration: float = 0.0,
    ) -> UpdateResult:
        """
        Create a dry-run result (no actual changes made).

        Parameters
        ----------
        updated_packages : Dict[str, Tuple[str, str]]
            Dictionary of packages that would be updated.
        skipped_packages : List[str], optional
            List of packages that would be skipped.
        duration : float, optional
            Duration of the dry-run operation in seconds.

        Returns
        -------
        UpdateResult
            Update result instance for dry-run with no backup_path.
        """
        result = cls(
            success=True,
            updated_packages=updated_packages,
            skipped_packages=skipped_packages or [],
            backup_path=None,  # No backup in dry-run mode
            duration=duration,
        )
        result.changes_summary = f"[DRY RUN] {result.generate_summary()}"
        return result
