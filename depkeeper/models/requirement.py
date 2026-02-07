"""
Requirement data model for depkeeper.

This module defines a structured representation of a single requirement
entry as parsed from a ``requirements.txt`` file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Requirement:
    """
    Represents a single requirement line from a requirements file.

    Attributes:
        name: Canonical package name.
        specs: List of (operator, version) specifiers.
        extras: Optional extras to install.
        markers: Environment marker expression (PEP 508).
        url: Direct URL or VCS source.
        editable: Whether this is an editable install (``-e``).
        hashes: Hash values used for verification.
        comment: Inline comment without the ``#`` prefix.
        line_number: Original line number in the source file.
        raw_line: Original unmodified line text.
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

    def to_string(
        self,
        *,
        include_hashes: bool = True,
        include_comment: bool = True,
    ) -> str:
        """
        Render the canonical ``requirements.txt`` representation.

        Args:
            include_hashes: Whether to include ``--hash=`` entries.
            include_comment: Whether to include inline comments.

        Returns:
            Formatted requirement string.
        """
        parts: List[str] = []

        if self.editable:
            parts.append("-e")

        if self.url:
            requirement = self.url
        else:
            requirement = self.name

        if self.extras:
            requirement += f"[{','.join(self.extras)}]"

        if self.specs:
            requirement += ",".join(
                f"{operator}{version}" for operator, version in self.specs
            )

        parts.append(requirement)

        if self.markers:
            parts.append(f"; {self.markers}")

        result = " ".join(parts)

        if include_hashes:
            for hash_value in self.hashes:
                result += f" --hash={hash_value}"

        if include_comment and self.comment:
            result += f"  # {self.comment}"

        return result

    def update_version(
        self,
        new_version: str,
        *,
        preserve_trailing_newline: bool = True,
    ) -> str:
        """
        Return a requirement string updated to the given version.

        All existing version specifiers are replaced with ``>=new_version``.
        Hashes are omitted in the updated output.

        Args:
            new_version: Version string to apply.
            preserve_trailing_newline: Ensure output ends with ``\\n``.

        Returns:
            Updated requirement string.
        """
        updated = Requirement(
            name=self.name,
            specs=[(">=", new_version)],
            extras=list(self.extras),
            markers=self.markers,
            url=self.url,
            editable=self.editable,
            hashes=[],
            comment=self.comment,
            line_number=self.line_number,
        )

        result = updated.to_string(
            include_hashes=False,
            include_comment=True,
        )

        if preserve_trailing_newline and not result.endswith("\n"):
            result += "\n"

        return result

    def __str__(self) -> str:
        """Return the rendered requirement string."""
        return self.to_string()

    def __repr__(self) -> str:
        """Return a debug-friendly representation."""
        return (
            "Requirement("
            f"name={self.name!r}, "
            f"specs={self.specs!r}, "
            f"extras={self.extras!r}, "
            f"editable={self.editable!r}, "
            f"line_number={self.line_number!r}"
            ")"
        )
