from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from packaging.markers import Marker
from packaging.version import Version
from packaging.specifiers import SpecifierSet


@dataclass
class Requirement:
    """
    Represents a single requirement line from a requirements file.

    Attributes:
        name: Normalized package name.
        specs: List of (operator, version) tuples.
        extras: Optional extras, e.g. ["security", "speed"].
        markers: Environment marker string, e.g. "python_version < '3.11'".
        url: Direct URL or VCS source.
        editable: Whether "-e" is used.
        hashes: "--hash=" values attached to this requirement.
        comment: Inline comment for this line.
        line_number: Line number in original file.
        raw_line: Raw unmodified line for round-trip safety.
    """

    name: str
    specs: List[Tuple[str, str]] = field(default_factory=list)
    extras: List[str] = field(default_factory=list)
    markers: Optional[str] = None
    url: Optional[str] = None
    editable: bool = False
    hashes: List[str] = field(default_factory=list)
    comment: Optional[str] = None
    line_number: int = 0
    raw_line: Optional[str] = None

    # ------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------
    def __post_init__(self) -> None:
        """Normalize the package name according to PEP 503 rules."""
        self.name = self._normalize_name(self.name)

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize package name per PEP 503."""
        return name.lower().replace("_", "-")

    # ------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------
    def to_string(
        self,
        include_hashes: bool = True,
        include_comment: bool = True,
    ) -> str:
        """
        Convert the requirement to a canonical string suitable for writing
        back into a requirements.txt file.
        """
        parts: List[str] = []

        # Editable flag
        if self.editable:
            parts.append("-e")

        # Package or URL
        if self.url:
            pkg = self.url
        else:
            pkg = self.name
            if self.extras:
                pkg += f"[{','.join(self.extras)}]"

            if self.specs:
                spec_str = ",".join(f"{op}{ver}" for op, ver in self.specs)
                pkg += spec_str

        parts.append(pkg)

        # Markers
        if self.markers:
            parts.append(f"; {self.markers}")

        req = " ".join(parts)

        # Hashes
        if include_hashes and self.hashes:
            for h in self.hashes:
                req += f" --hash={h}"

        # Comment
        if include_comment and self.comment:
            req += f"  # {self.comment}"

        return req

    # ------------------------------------------------------------
    # Requirements logic
    # ------------------------------------------------------------
    def is_pinned(self) -> bool:
        """
        Return True if all specifiers use '==' (exact version).
        """
        if not self.specs:
            return False

        return all(op == "==" for op, _ in self.specs)

    def matches_version(self, version: str) -> bool:
        """
        Check if a specific version satisfies the requirement's specifiers.
        """
        if not self.specs:
            return True

        try:
            spec_set = self.get_specifier_set()
            if spec_set is None:
                return False
            return Version(version) in spec_set
        except Exception:
            return False

    def get_specifier_set(self) -> Optional[SpecifierSet]:
        """
        Build a SpecifierSet from the specifier tuples.
        """
        if not self.specs:
            return None

        try:
            spec_str = ",".join(f"{op}{ver}" for op, ver in self.specs)
            return SpecifierSet(spec_str)
        except Exception:
            return None

    def get_marker(self) -> Optional[Marker]:
        """
        Convert marker string into a Marker object.
        """
        if not self.markers:
            return None

        try:
            return Marker(self.markers)
        except Exception:
            return None

    # ------------------------------------------------------------
    # Source type detection
    # ------------------------------------------------------------
    def is_vcs(self) -> bool:
        """
        Return True if the requirement is a VCS dependency.
        """
        if not self.url:
            return False

        return self.url.startswith(("git+", "hg+", "svn+", "bzr+"))

    def is_local(self) -> bool:
        """
        Return True if this is a local file or directory requirement.
        """
        if not self.url:
            return False

        return self.url.startswith("file://") or self.url.startswith(".")

    # ------------------------------------------------------------
    # Representations
    # ------------------------------------------------------------
    def __str__(self) -> str:
        return self.to_string()

    def __repr__(self) -> str:
        return (
            f"Requirement(name={self.name!r}, specs={self.specs!r}, "
            f"extras={self.extras!r}, editable={self.editable}, "
            f"line_number={self.line_number})"
        )
