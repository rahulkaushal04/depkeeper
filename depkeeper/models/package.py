"""
Package data model for depkeeper.

This module defines the core representation of a Python package, including
version state, update recommendations, conflict tracking, and Python
compatibility evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from packaging.version import InvalidVersion, Version, parse

from depkeeper.models.conflict import Conflict
from depkeeper.utils.version_utils import get_update_type


def _normalize_name(name: str) -> str:
    """
    Normalize a package name according to PEP 503.

    Args:
        name: Original package name.

    Returns:
        Normalized package name.
    """
    return name.lower().replace("_", "-")


@dataclass
class Package:
    """
    Represents a Python package with version and compatibility state.

    Attributes:
        name: Normalized package name.
        current_version: Installed or specified version.
        latest_version: Latest known upstream version (informational only).
        recommended_version: Best version considering constraints.
        metadata: Arbitrary metadata (typically from PyPI).
        conflicts: Dependency conflicts affecting this package.
    """

    name: str
    current_version: Optional[str] = None
    latest_version: Optional[str] = None
    recommended_version: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    conflicts: List[Conflict] = field(default_factory=list)

    _parsed_versions: Dict[str, Optional[Version]] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        """Normalize package name after initialization."""
        self.name = _normalize_name(self.name)

    # ------------------------------------------------------------------
    # Version parsing & accessors
    # ------------------------------------------------------------------

    def _parse_version(self, version: Optional[str]) -> Optional[Version]:
        """
        Parse and cache a version string.

        Args:
            version: Version string to parse.

        Returns:
            Parsed Version object, or None if invalid.
        """
        if version is None:
            return None

        if version not in self._parsed_versions:
            try:
                parsed = parse(version)
                self._parsed_versions[version] = (
                    parsed if isinstance(parsed, Version) else None
                )
            except InvalidVersion:
                self._parsed_versions[version] = None

        return self._parsed_versions[version]

    @property
    def current(self) -> Optional[Version]:
        """Parsed current version."""
        return self._parse_version(self.current_version)

    @property
    def latest(self) -> Optional[Version]:
        """Parsed latest version (informational only)."""
        return self._parse_version(self.latest_version)

    @property
    def recommended(self) -> Optional[Version]:
        """Parsed recommended version."""
        return self._parse_version(self.recommended_version)

    # ------------------------------------------------------------------
    # State & conflict handling
    # ------------------------------------------------------------------

    @property
    def requires_downgrade(self) -> bool:
        """
        Determine whether the recommended version is lower than current.

        Returns:
            True if a downgrade is required.
        """
        return (
            self.current is not None
            and self.recommended is not None
            and self.current > self.recommended
        )

    def has_conflicts(self) -> bool:
        """
        Check whether dependency conflicts exist.

        Returns:
            True if conflicts are present.
        """
        return bool(self.conflicts)

    def set_conflicts(
        self,
        conflicts: List[Conflict],
        *,
        resolved_version: Optional[str] = None,
    ) -> None:
        """
        Set dependency conflicts and optionally update recommended version.

        Args:
            conflicts: List of detected conflicts.
            resolved_version: Version resolving the conflicts, if known.
        """
        self.conflicts = conflicts
        if resolved_version:
            self.recommended_version = resolved_version

    def get_conflict_summary(self) -> List[str]:
        """
        Return short, user-friendly conflict summaries.

        Returns:
            List of summary strings.
        """
        return [conflict.to_short_string() for conflict in self.conflicts]

    def get_conflict_details(self) -> List[str]:
        """
        Return detailed conflict descriptions.

        Returns:
            List of detailed conflict strings.
        """
        return [conflict.to_display_string() for conflict in self.conflicts]

    # ------------------------------------------------------------------
    # Update & compatibility logic
    # ------------------------------------------------------------------

    def has_update(self) -> bool:
        """
        Determine whether an update is available.

        Returns:
            True if recommended version is newer than current.
        """
        return (
            self.current is not None
            and self.recommended is not None
            and self.recommended > self.current
        )

    def get_version_python_req(self, version_key: str) -> Optional[str]:
        """
        Retrieve Python version requirements for a specific version entry.

        Args:
            version_key: One of 'current', 'latest', or 'recommended'.

        Returns:
            Python requirement specifier if available.
        """
        meta = self.metadata.get(f"{version_key}_metadata")
        if isinstance(meta, dict):
            value = meta.get("requires_python")
            return value if isinstance(value, str) else None
        return None

    # ------------------------------------------------------------------
    # Reporting & serialization
    # ------------------------------------------------------------------

    def get_status_summary(self) -> Tuple[str, str, str, Optional[str]]:
        """
        Compute a high-level status summary.

        Returns:
            Tuple of (status, installed, latest, recommended).
        """
        installed = self.current_version or "none"
        latest = self.latest_version or "error"
        recommended = self.recommended_version

        if not self.recommended_version:
            status = "no-update"
        elif not self.current_version:
            status = "install"
        elif self.requires_downgrade:
            status = "downgrade"
        elif self.has_update():
            status = "outdated"
        else:
            status = "latest"

        return status, installed, latest, recommended

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize package state to a JSON-compatible dictionary.

        Returns:
            JSON-safe package representation.
        """
        if not self.recommended_version:
            status = "no-update"
        elif not self.current_version:
            status = "install"
        elif self.requires_downgrade:
            status = "downgrade"
        elif self.has_update():
            status = "outdated"
        else:
            status = "latest"

        entry: Dict[str, Any] = {
            "name": self.name,
            "status": status,
        }

        versions: Dict[str, str] = {}
        if self.current_version:
            versions["current"] = self.current_version
        if self.latest_version:
            versions["latest"] = self.latest_version
        if self.recommended_version:
            versions["recommended"] = self.recommended_version

        if versions:
            entry["versions"] = versions

        if status in ("outdated", "downgrade"):
            entry["update_type"] = get_update_type(
                self.current_version,
                self.recommended_version,
            )

        python_reqs: Dict[str, str] = {}
        for key in ("current", "latest", "recommended"):
            req = self.get_version_python_req(key)
            if req:
                python_reqs[key] = req

        if python_reqs:
            entry["python_requirements"] = python_reqs

        if self.has_conflicts():
            entry["conflicts"] = [c.to_json() for c in self.conflicts]

        if status == "no-update":
            entry["error"] = "Package information unavailable"

        return entry

    # ------------------------------------------------------------------
    # Presentation helpers
    # ------------------------------------------------------------------

    def render_python_compatibility(self) -> str:
        """
        Render Python compatibility information for display.

        Returns:
            Formatted compatibility string.
        """
        parts: List[str] = []

        current_req = self.get_version_python_req("current")
        if current_req:
            parts.append(f"Current: {current_req}")

        latest_req = self.get_version_python_req("latest")
        if latest_req:
            parts.append(f"Latest: {latest_req}")

        if self.has_update():
            rec_req = self.get_version_python_req("recommended")
            if rec_req:
                parts.append(f"Recommended:{rec_req}")

        return "\n".join(parts) if parts else "[dim]-[/dim]"

    def get_display_data(self) -> Dict[str, Any]:
        """
        Compute all values required for UI rendering.

        Returns:
            Dictionary of derived display properties.
        """
        update_available = self.has_update()
        downgrade_required = self.requires_downgrade

        return {
            "update_available": update_available,
            "requires_downgrade": downgrade_required,
            "update_target": self.recommended_version,
            "update_type": (
                get_update_type(self.current_version, self.recommended_version)
                if update_available or downgrade_required
                else None
            ),
            "has_conflicts": self.has_conflicts(),
            "conflict_summary": (
                self.get_conflict_summary() if self.has_conflicts() else []
            ),
        }

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __str__(self) -> str:
        """Return a human-readable package summary."""
        if self.current_version and self.latest_version:
            status = "outdated" if self.has_update() else "up-to-date"
            text = (
                f"{self.name} {self.current_version} → "
                f"{self.latest_version} ({status})"
            )
            if self.has_update():
                text += f" [recommended: {self.recommended_version}]"
            return text

        if self.latest_version:
            return f"{self.name} (latest: {self.latest_version})"

        return self.name

    def __repr__(self) -> str:
        """Return a debug-friendly representation."""
        return (
            "Package("
            f"name={self.name!r}, "
            f"current_version={self.current_version!r}, "
            f"latest_version={self.latest_version!r}, "
            f"recommended_version={self.recommended_version!r}, "
            f"outdated={self.has_update()}"
            ")"
        )
