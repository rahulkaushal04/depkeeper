"""Package data model for depkeeper.

Defines the core representation of a Python package, including version state,
update recommendations, conflict tracking, and Python compatibility
evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from packaging.version import InvalidVersion, Version, parse

from depkeeper.models.conflict import Conflict
from depkeeper.utils.naming import normalize_package_name
from depkeeper.utils.version_utils import get_update_type


def _normalize_name(name: str) -> str:
    """Normalize a package name according to PEP 503.

    Thin alias for :func:`depkeeper.utils.naming.normalize_package_name`,
    so ``Package.name`` is always comparable to the keys used by the
    parser, data store and dependency analyzer.

    Args:
        name: Original package name.

    Returns:
        Normalized package name.
    """
    return normalize_package_name(name)


@dataclass
class Package:
    """A Python package with version and compatibility state.

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
        """Normalize the name so lookups match the parser and data store keys."""
        self.name = _normalize_name(self.name)

    # ------------------------------------------------------------------
    # Version parsing & accessors
    # ------------------------------------------------------------------

    def _parse_version(self, version: Optional[str]) -> Optional[Version]:
        """Parse and cache a version string.

        Args:
            version: Version string to parse.

        Returns:
            Parsed :class:`~packaging.version.Version`, or ``None`` when the
            input is ``None`` or not PEP 440 compliant.
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
        """Whether the recommended version is lower than the current one.

        True when conflict resolution or Python incompatibility forced the
        recommendation below the version declared in the requirements file.
        """
        return (
            self.current is not None
            and self.recommended is not None
            and self.current > self.recommended
        )

    def has_conflicts(self) -> bool:
        """Return ``True`` when dependency conflicts were recorded."""
        return bool(self.conflicts)

    def set_conflicts(
        self,
        conflicts: List[Conflict],
        *,
        resolved_version: Optional[str] = None,
    ) -> None:
        """Record dependency conflicts and optionally override the recommendation.

        Args:
            conflicts: Detected conflicts affecting this package.
            resolved_version: Version that resolves the conflicts. When given,
                it replaces :attr:`recommended_version`.
        """
        self.conflicts = conflicts
        if resolved_version:
            self.recommended_version = resolved_version

    def get_conflict_summary(self) -> List[str]:
        """Return one short conflict summary per recorded conflict."""
        return [conflict.to_short_string() for conflict in self.conflicts]

    def get_conflict_details(self) -> List[str]:
        """Return one detailed description per recorded conflict."""
        return [conflict.to_display_string() for conflict in self.conflicts]

    # ------------------------------------------------------------------
    # Update & compatibility logic
    # ------------------------------------------------------------------

    def has_update(self) -> bool:
        """Return ``True`` when the recommended version is newer than current."""
        return (
            self.current is not None
            and self.recommended is not None
            and self.recommended > self.current
        )

    def get_version_python_req(self, version_key: str) -> Optional[str]:
        """Return the ``requires_python`` specifier for one version slot.

        Args:
            version_key: One of ``"current"``, ``"latest"`` or
                ``"recommended"``.

        Returns:
            The specifier string, or ``None`` when the upload omitted it or
            the slot has no metadata.
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
        """Compute the high-level status used by line-based output.

        The status ladder is ordered by severity: a missing recommendation
        means PyPI data was unavailable, and a required downgrade outranks a
        plain "outdated" because it signals an incompatible pin.

        Returns:
            Tuple of ``(status, installed, latest, recommended)``, where
            *status* is one of ``no-update``, ``install``, ``downgrade``,
            ``outdated`` or ``latest``.
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
        """Serialize package state to a JSON-compatible dictionary.

        Optional sections (``versions``, ``update_type``,
        ``python_requirements``, ``conflicts``) are omitted when empty, so
        consumers must treat every key except ``name`` and ``status`` as
        optional.

        Returns:
            JSON-safe package representation.
        """
        # Mirrors the status ladder in get_status_summary(); keep both in sync.
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
        """Render Python compatibility as a multi-line cell for the table view.

        Returns:
            Newline-separated requirement lines, or a dimmed placeholder when
            no ``requires_python`` metadata is known.
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
        """Compute the derived values required for UI rendering.

        Centralizing this keeps the renderers free of status logic, so table
        and simple output can never disagree about a package's state.

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
