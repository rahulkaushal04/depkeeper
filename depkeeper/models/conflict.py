"""Dependency conflict data models for depkeeper.

Defines structured representations for dependency conflicts and the utilities
used to reason about versions that satisfy every recorded constraint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

from packaging.version import InvalidVersion, Version, parse
from packaging.specifiers import InvalidSpecifier, SpecifierSet

from depkeeper.utils.naming import normalize_package_name


def _normalize_name(name: str) -> str:
    """Normalize a package name according to PEP 503.

    Thin alias for :func:`depkeeper.utils.naming.normalize_package_name`,
    so conflict endpoints stay comparable to ``Package.name`` keys.
    """
    return normalize_package_name(name)


@dataclass(frozen=True)
class Conflict:
    """A dependency conflict between two packages.

    Frozen so a conflict can be hashed and deduplicated while the resolution
    loop accumulates findings across iterations.

    Attributes:
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
        """Normalize both endpoints so they match ``Package.name`` keys."""
        # object.__setattr__ is required: the dataclass is frozen.
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

    Attributes:
        package_name: Name of the affected package.
        conflicts: Conflicts associated with this package.
    """

    package_name: str
    conflicts: List[Conflict] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Normalize the package name so it matches ``Package.name`` keys."""
        self.package_name = _normalize_name(self.package_name)

    def add_conflict(self, conflict: Conflict) -> None:
        """Append a conflict to the set."""
        self.conflicts.append(conflict)

    def has_conflicts(self) -> bool:
        """Return ``True`` when the set holds at least one conflict."""
        return bool(self.conflicts)

    def get_max_compatible_version(
        self,
        available_versions: List[str],
    ) -> Optional[str]:
        """Return the highest version satisfying *every* recorded conflict.

        All ``required_spec`` values are intersected into a single specifier
        set, so the answer is compatible with all conflicting dependents at
        once. Pre-releases are never returned.

        Args:
            available_versions: Candidate version strings, in any order.

        Returns:
            The highest compatible version, or ``None`` when the set is empty,
            a specifier is unparseable, or no candidate satisfies them all.
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
