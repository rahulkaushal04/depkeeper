"""
Version information wrapper.

Provides a typed wrapper around packaging.version.Version with additional
utilities for semantic versioning, calendar versioning, comparison,
and version bumping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering
from packaging.version import InvalidVersion, Version, parse

from depkeeper.constants import CALVER_PATTERNS, SEMVER_PATTERN


# Precompile regex for efficiency
SEMVER_REGEX = re.compile(SEMVER_PATTERN)
CALVER_REGEXES = [re.compile(p) for p in CALVER_PATTERNS]


@total_ordering
@dataclass(frozen=True)
class VersionInfo:
    """
    A wrapper around packaging.version.Version.

    Provides:
        - Semantic version detection
        - Calendar version detection
        - Comparison utilities
        - Major/minor/patch bumping
        - Stability classification (pre/dev/post)
    """

    version_string: str
    _parsed: Version

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------
    def __init__(self, version_string: str) -> None:
        object.__setattr__(self, "version_string", version_string)
        try:
            parsed = parse(version_string)
        except InvalidVersion as e:
            raise ValueError(f"Invalid version string: {version_string}") from e

        object.__setattr__(self, "_parsed", parsed)

    @classmethod
    def from_version(cls, version: Version) -> VersionInfo:
        """Create VersionInfo from a Version object."""
        return cls(str(version))

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def version(self) -> Version:
        """The underlying packaging.version.Version object."""
        return self._parsed

    @property
    def major(self) -> int:
        return self.version.major

    @property
    def minor(self) -> int:
        return self.version.minor

    @property
    def micro(self) -> int:
        return self.version.micro

    @property
    def patch(self) -> int:
        """Alias for micro (patch)."""
        return self.micro

    # Release type
    @property
    def is_prerelease(self) -> bool:
        return self.version.is_prerelease

    @property
    def is_devrelease(self) -> bool:
        return self.version.is_devrelease

    @property
    def is_postrelease(self) -> bool:
        return self.version.is_postrelease

    @property
    def is_stable(self) -> bool:
        """True if not pre/dev/post release."""
        return not (self.is_prerelease or self.is_devrelease or self.is_postrelease)

    # ------------------------------------------------------------------
    # Version type detection
    # ------------------------------------------------------------------
    def is_semver(self) -> bool:
        """Check if version matches X.Y.Z semantic versioning."""
        return SEMVER_REGEX.match(self.version_string) is not None

    def is_calver(self) -> bool:
        """Check if version matches any supported calendar version patterns."""
        return any(regex.match(self.version_string) for regex in CALVER_REGEXES)

    # ------------------------------------------------------------------
    # Bumping logic
    # ------------------------------------------------------------------
    def bump_major(self) -> VersionInfo:
        return VersionInfo(f"{self.major + 1}.0.0")

    def bump_minor(self) -> VersionInfo:
        return VersionInfo(f"{self.major}.{self.minor + 1}.0")

    def bump_patch(self) -> VersionInfo:
        return VersionInfo(f"{self.major}.{self.minor}.{self.patch + 1}")

    # ------------------------------------------------------------------
    # Comparison helpers
    # ------------------------------------------------------------------
    def compare_to(self, other: VersionInfo) -> int:
        """Return -1, 0, 1 based on comparison with another version."""
        if self.version < other.version:
            return -1
        if self.version > other.version:
            return 1
        return 0

    def __eq__(self, other: object) -> bool:
        if isinstance(other, VersionInfo):
            return self.version == other.version
        if isinstance(other, str):
            try:
                return self.version == parse(other)
            except InvalidVersion:
                return False
        return False

    def __lt__(self, other: VersionInfo) -> bool:
        return self.version < other.version

    # ------------------------------------------------------------------
    # Representations
    # ------------------------------------------------------------------
    def __str__(self) -> str:
        return self.version_string

    def __repr__(self) -> str:
        return f"VersionInfo(version_string={self.version_string!r})"

    def __hash__(self) -> int:
        return hash(self.version)
