"""
Package data model.

Represents package information fetched from PyPI, including current/latest
versions, available versions, metadata, and update detection utilities.
"""

from __future__ import annotations

import sys
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from packaging.specifiers import SpecifierSet
from packaging.version import Version, InvalidVersion, parse


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
        compatible_version: Maximum version compatible with current Python.
        available_versions: All published versions for the package.
        metadata: Optional metadata (summary, authors, requires_dist, etc.)
        last_updated: Timestamp of last fetch.
    """

    name: str
    current_version: Optional[str] = None
    latest_version: Optional[str] = None
    compatible_version: Optional[str] = None
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

    # ----------------------------------------------------------------------
    # Python version compatibility
    # ----------------------------------------------------------------------
    def get_requires_python(self) -> Optional[str]:
        """Get the requires_python specifier from metadata.

        Returns:
            The requires_python string (e.g., '>=3.8') or None.
        """
        return self.metadata.get("requires_python")

    def is_python_compatible(self, python_version: Optional[str] = None) -> bool:
        """Check if package is compatible with specified Python version.

        Parameters:
            python_version: Python version string to check (e.g., '3.9.0').
                          If None, uses current Python version.

        Returns:
            True if compatible, False if incompatible, True if no requirement specified.
        """
        requires_python = self.get_requires_python()
        if not requires_python:
            # No requirement specified, assume compatible
            return True

        if python_version is None:
            # Use current Python version
            python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        try:
            spec = SpecifierSet(requires_python)
            return python_version in spec
        except Exception:
            # If we can't parse, assume compatible
            return True

    def get_version_python_req(self, version_key: str) -> Optional[str]:
        """Get Python requirement for a specific version (current/latest/compatible).

        Parameters:
            version_key: One of 'current', 'latest', or 'compatible'

        Returns:
            Python requirement string or None
        """
        version_metadata = self.metadata.get(f"{version_key}_metadata", {})
        return version_metadata.get("requires_python")

    def has_compatible_version(self) -> bool:
        """Check if a compatible version is available (different from latest)."""
        return (
            self.compatible_version is not None
            and self.compatible_version != self.latest_version
        )

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
