"""
Dependency conflict data models for depkeeper.

This module defines structured representations for dependency conflicts
and utilities to reason about compatible versions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

from packaging.version import InvalidVersion, Version, parse
from packaging.specifiers import InvalidSpecifier, SpecifierSet


def _normalize_name(name: str) -> str:
    """Normalize a package name according to PEP 503."""
    return name.lower().replace("_", "-")


@dataclass(frozen=True)
class Conflict:
    """Represents a dependency conflict between two packages.

    Args:
        source_package: Package declaring the dependency.
        target_package: Package being constrained.
        required_spec: Version specifier required by the source package.
        conflicting_version: Version that violates the requirement.
        source_version: Version of the source package, if known.
    """

    source_package: str
    target_package: str
    required_spec: str
    conflicting_version: str
    source_version: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_package", _normalize_name(self.source_package))
        object.__setattr__(self, "target_package", _normalize_name(self.target_package))

    def to_display_string(self) -> str:
        """Return a human-readable description of the conflict."""
        source = (
            f"{self.source_package}=={self.source_version}"
            if self.source_version
            else self.source_package
        )
        return f"{source} requires {self.target_package}{self.required_spec}"

    def to_short_string(self) -> str:
        """Return a compact conflict summary."""
        return f"{self.source_package} needs {self.required_spec}"

    def to_json(self) -> Dict[str, Optional[str]]:
        """Return a JSON-serializable representation."""
        return {
            "source_package": self.source_package,
            "source_version": self.source_version,
            "target_package": self.target_package,
            "required_spec": self.required_spec,
            "conflicting_version": self.conflicting_version,
        }

    def __str__(self) -> str:
        return self.to_display_string()

    def __repr__(self) -> str:
        return (
            "Conflict("
            f"source_package={self.source_package!r}, "
            f"target_package={self.target_package!r}, "
            f"required_spec={self.required_spec!r}, "
            f"conflicting_version={self.conflicting_version!r}"
            ")"
        )


@dataclass
class ConflictSet:
    """Collection of conflicts affecting a single package.

    Args:
        package_name: Name of the affected package.
        conflicts: Conflicts associated with this package.
    """

    package_name: str
    conflicts: List[Conflict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.package_name = _normalize_name(self.package_name)

    def add_conflict(self, conflict: Conflict) -> None:
        """Add a conflict to the set."""
        self.conflicts.append(conflict)

    def has_conflicts(self) -> bool:
        """Return True if any conflicts exist."""
        return bool(self.conflicts)

    def get_max_compatible_version(
        self,
        available_versions: List[str],
    ) -> Optional[str]:
        """Return the highest version compatible with all conflicts.

        Pre-release versions are ignored.

        Args:
            available_versions: List of available version strings.

        Returns:
            Highest compatible version string, or None if no compatible
            version exists.
        """
        if not self.conflicts:
            return None

        try:
            combined_spec = SpecifierSet(
                ",".join(conflict.required_spec for conflict in self.conflicts)
            )
        except InvalidSpecifier:
            return None

        compatible: List[Tuple[str, Version]] = []

        for version_str in available_versions:
            try:
                parsed = parse(version_str)
                if not isinstance(parsed, Version) or parsed.is_prerelease:
                    continue
                if parsed in combined_spec:
                    compatible.append((version_str, parsed))
            except InvalidVersion:
                continue

        if not compatible:
            return None

        compatible.sort(key=lambda item: item[1], reverse=True)
        return compatible[0][0]

    def __len__(self) -> int:
        return len(self.conflicts)

    def __iter__(self) -> Iterator[Conflict]:
        return iter(self.conflicts)
