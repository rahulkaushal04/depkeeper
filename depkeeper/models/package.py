"""
Package data model.

Represents package information fetched from PyPI, including current/latest
versions, available versions, metadata, and update detection utilities.
"""

from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from packaging.specifiers import SpecifierSet
from packaging.version import Version, InvalidVersion, parse

from depkeeper.models.version import VersionInfo


def _parse(version: Optional[str]) -> Optional[Version]:
    """Safely parse version strings into packaging.version.Version."""
    if version is None:
        return None
    try:
        return parse(version)
    except InvalidVersion:
        return None


@dataclass
class Package:
    """
    Represents a Python package along with version information from PyPI.

    Attributes:
        name: Normalized package name.
        current_version: Installed or specified version.
        latest_version: Latest available version.
        available_versions: All published versions for the package.
        metadata: Optional metadata (summary, authors, requires_dist, etc.)
        last_updated: Timestamp of last fetch.
    """

    name: str
    current_version: Optional[str] = None
    latest_version: Optional[str] = None
    available_versions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    last_updated: datetime = field(default_factory=datetime.now)

    # ----------------------------------------------------------------------
    # Initialization
    # ----------------------------------------------------------------------
    def __post_init__(self) -> None:
        """Normalize package name following PEP 503."""
        self.name = self.name.lower().replace("_", "-")

    # ----------------------------------------------------------------------
    # Version helpers
    # ----------------------------------------------------------------------
    @property
    def current(self) -> Optional[Version]:
        return _parse(self.current_version)

    @property
    def latest(self) -> Optional[Version]:
        return _parse(self.latest_version)

    @property
    def version_info_current(self) -> Optional[VersionInfo]:
        return VersionInfo(self.current_version) if self.current_version else None

    @property
    def version_info_latest(self) -> Optional[VersionInfo]:
        return VersionInfo(self.latest_version) if self.latest_version else None

    # ----------------------------------------------------------------------
    # Update detection
    # ----------------------------------------------------------------------
    def has_update(self) -> bool:
        """
        True if a newer version is available.
        """
        if self.current is None or self.latest is None:
            return False
        return self.latest > self.current

    def is_outdated(self) -> bool:
        """Alias for has_update()."""
        return self.has_update()

    def get_update_type(self) -> Optional[str]:
        """
        Determine update type: major, minor, patch, or None.

        Uses VersionInfo for correctness and simplicity.
        """
        if not self.has_update():
            return None

        curr = self.version_info_current
        latest = self.version_info_latest

        if curr is None or latest is None:
            return None

        if latest.major > curr.major:
            return "major"
        if latest.minor > curr.minor:
            return "minor"
        if latest.patch > curr.patch:
            return "patch"
        return "other"

    # ----------------------------------------------------------------------
    # Version filtering
    # ----------------------------------------------------------------------
    def get_newer_versions(
        self,
        include_pre_release: bool = False,
    ) -> List[str]:
        """
        List versions newer than the current installed version.

        Sorted from newest → oldest.
        """
        if self.current is None:
            return []

        newer: List[str] = []
        for v in self.available_versions:
            parsed = _parse(v)
            if parsed is None:
                continue

            if not include_pre_release and parsed.is_prerelease:
                continue

            if parsed > self.current:
                newer.append(v)

        newer.sort(key=lambda v: _parse(v) or Version("0"), reverse=True)
        return newer

    def get_compatible_versions(self, specifier_set: SpecifierSet) -> List[str]:
        """
        Return versions matching the provided SpecifierSet.

        Sorted from newest → oldest.
        """
        compatible: List[str] = []
        for v in self.available_versions:
            parsed = _parse(v)
            if parsed is None:
                continue
            if parsed in specifier_set:
                compatible.append(v)

        compatible.sort(key=lambda v: _parse(v) or Version("0"), reverse=True)
        return compatible

    # ----------------------------------------------------------------------
    # Metadata helpers
    # ----------------------------------------------------------------------
    def get_metadata_field(self, field: str, default: Any = None) -> Any:
        """Retrieve metadata value with fallback."""
        return self.metadata.get(field, default)

    def is_pre_release(self, version: Optional[str] = None) -> bool:
        """
        Check if a version (or current version) is a pre-release.
        """
        parsed = _parse(version or self.current_version)
        if parsed is None:
            return False
        return parsed.is_prerelease

    # ----------------------------------------------------------------------
    # Representations
    # ----------------------------------------------------------------------
    def __str__(self) -> str:
        if self.current_version and self.latest_version:
            status = "outdated" if self.has_update() else "up-to-date"
            return (
                f"{self.name} {self.current_version} → "
                f"{self.latest_version} ({status})"
            )
        if self.latest_version:
            return f"{self.name} (latest: {self.latest_version})"
        return self.name

    def __repr__(self) -> str:
        return (
            f"Package(name={self.name!r}, current_version={self.current_version!r}, "
            f"latest_version={self.latest_version!r}, outdated={self.has_update()})"
        )
