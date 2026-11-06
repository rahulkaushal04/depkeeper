"""Package data model for depkeeper.

Defines the core representation of a Python package, including version state,
update recommendations, conflict tracking, and Python compatibility
evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from packaging.version import Version

from depkeeper.models.conflict import Conflict
from depkeeper.utils.naming import normalize_package_name
from depkeeper.utils.version_utils import get_update_type, parse_version_lenient


def _normalize_name(name: str) -> str:
    """Normalize a package name according to PEP 503.

    Thin alias for `depkeeper.utils.naming.normalize_package_name`,
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
        versioning: Resolved scheme, ``"semver"`` or ``"calver"``; selects the
            update-type labels (calver: ``year``/``month``/``patch``).
        held: Package policy ``hold`` kept it on its current version.
        ignored: Package policy ``ignore`` excluded it from recommendations.
        recommended_released: Upload time of the recommended version, if known.
        current_released: Upload time of the current version, if known.
        latest_released: Upload time of the latest version, if known.
        cooldown_skipped: Newest version withheld by the ``min_age`` cooldown
            (the recommendation fell back to an older eligible one).
        retained_specs: The requirement's own upper bounds and exclusions.
        direct: URL, VCS, editable or local-path requirement; it is not on PyPI
            so it is reported as ``direct`` and never checked.
        major_available: Newest eligible version in a higher major than the
            recommendation that was *not* applied (no ``--allow-major`` opt-in,
            or capped by ``max_update``). Informational only.
        conflict_held: A conflict was resolved by holding or reverting a
            version, so ``conflicts`` may be empty.
    """

    name: str
    current_version: Optional[str] = None
    latest_version: Optional[str] = None
    recommended_version: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    conflicts: List[Conflict] = field(default_factory=list)
    # The requirement's own upper bounds / exclusions; resolver searches must
    # honour them so a chosen version never violates the declared range.
    retained_specs: List[Tuple[str, str]] = field(
        default_factory=list, compare=False, repr=False
    )

    versioning: str = field(default="semver", compare=False)
    held: bool = field(default=False, compare=False)
    ignored: bool = field(default=False, compare=False)
    recommended_released: Optional[datetime] = field(default=None, compare=False)
    current_released: Optional[datetime] = field(default=None, compare=False)
    latest_released: Optional[datetime] = field(default=None, compare=False)
    cooldown_skipped: Optional[str] = field(default=None, compare=False)
    # A conflict was recorded and resolved by holding/reverting a version, so
    # `conflicts` may be empty although the resolver still counts it.
    conflict_held: bool = field(default=False, compare=False)
    major_available: Optional[str] = field(default=None, compare=False)
    # The major is blocked by a max_update cap, not by lack of opt-in.
    major_capped: bool = field(default=False, compare=False)
    # URL/VCS/editable/path requirement: never looked up on PyPI.
    direct: bool = field(default=False, compare=False)

    _parsed_versions: Dict[str, Optional[Version]] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        """Normalize the name so lookups match the parser and data store keys."""
        self.name = _normalize_name(self.name)

    def _parse_version(self, version: Optional[str]) -> Optional[Version]:
        """Parse and cache a version string.

        Uses `parse_version_lenient`,
        which also resolves a PEP 440 wildcard band (``"2.*"``) to its
        release-prefix floor, so `has_update`/`requires_downgrade`
        stay meaningful for a wildcard exact pin instead of treating it as
        unparseable.

        Args:
            version: Version string to parse.

        Returns:
            Parsed `Version`, or ``None`` when the
            input is ``None`` or not PEP 440 compliant.
        """
        if version is None:
            return None

        if version not in self._parsed_versions:
            self._parsed_versions[version] = parse_version_lenient(version)

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

    @property
    def requires_downgrade(self) -> bool:
        """Return whether the recommended version is lower than the current one.

        This holds when conflict resolution or Python incompatibility forced the
        recommendation below the version declared in the requirements file.
        """
        return (
            self.current is not None
            and self.recommended is not None
            and self.current > self.recommended
        )

    @property
    def update_type(self) -> str:
        """Update label for current -> recommended under this package's scheme."""
        return get_update_type(
            self.current_version, self.recommended_version, self.versioning
        )

    def recommended_age_days(self, now: Optional[datetime] = None) -> Optional[int]:
        """Whole days since the recommended version was uploaded (``None`` if unknown)."""
        if self.recommended_released is None:
            return None
        now = now or datetime.now(timezone.utc)
        return max(0, (now - self.recommended_released).days)

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
                it replaces `recommended_version`.
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

    def get_status_summary(self) -> Tuple[str, str, str, Optional[str]]:
        """Compute the high-level status used by line-based output.

        The status ladder is ordered by severity: a missing recommendation
        means PyPI data was unavailable, and a required downgrade outranks a
        plain "outdated" because it signals an incompatible pin.

        Returns:
            Tuple of ``(status, installed, latest, recommended)``, where
            *status* is one of ``direct``, ``no-update``, ``install``, ``downgrade``,
            ``outdated`` or ``latest``.
        """
        installed = self.current_version or "none"
        latest = self.latest_version or "error"
        recommended = self.recommended_version

        if self.direct:
            status = "direct"
        elif not self.recommended_version:
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
        if self.direct:
            status = "direct"
        elif not self.recommended_version:
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
            entry["update_type"] = self.update_type

        if self.versioning != "semver":
            entry["versioning"] = self.versioning
        if self.held:
            entry["held"] = True
        if self.recommended_released is not None:
            entry["released"] = self.recommended_released.isoformat()
            entry["age_days"] = self.recommended_age_days()
        if self.cooldown_skipped:
            entry["cooldown_skipped"] = self.cooldown_skipped
        if self.conflict_held:
            entry["conflict_held"] = True
        if self.major_available:
            entry["major_available"] = self.major_available

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
            entry["error"] = self.metadata.get(
                "lookup_error", "Package information unavailable"
            )

        return entry

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
                parts.append(f"Recommended: {rec_req}")

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
                self.update_type if update_available or downgrade_required else None
            ),
            "has_conflicts": self.has_conflicts(),
            "conflict_summary": (
                self.get_conflict_summary() if self.has_conflicts() else []
            ),
        }

    def __str__(self) -> str:
        """Return a human-readable package summary."""
        if self.current_version and self.latest_version:
            status = "outdated" if self.has_update() else "up-to-date"
            text = (
                f"{self.name} {self.current_version} → {self.latest_version} ({status})"
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
