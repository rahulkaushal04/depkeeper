"""Requirement data model for depkeeper.

Defines a structured representation of a single requirement entry as parsed
from a ``requirements.txt`` file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from depkeeper.utils.version_utils import (
    rewrite_version_specs,
    specs_allow_version,
    specs_to_string,
)


@dataclass
class Requirement:
    """A single requirement line from a requirements file.

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
        source_file: Absolute path of the file this requirement was parsed
            from. Requirements pulled in via ``-r``/``--requirement`` includes
            retain the path of the *included* file, not the parent. Used by the
            update writer to rewrite the correct file. Excluded from equality
            comparison as it is provenance metadata, not part of the
            requirement's semantic identity.
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
    source_file: Optional[str] = field(default=None, compare=False)

    def to_string(
        self,
        *,
        include_hashes: bool = True,
        include_comment: bool = True,
    ) -> str:
        """Render the canonical ``requirements.txt`` representation.

        Version specifiers are omitted when :attr:`url` is set, because a
        direct URL/VCS/local-path reference cannot carry a version specifier
        (doing so yields an uninstallable line).

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

        if self.specs and not self.url:
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
        pin: bool = False,
        preserve_trailing_newline: bool = True,
        allow_hash_removal: bool = False,
    ) -> str:
        """Return a requirement string updated to the given version.

        By default only the specifiers that describe the *currently selected*
        version are rewritten. Upper bounds (``<``, ``<=``), exclusions
        (``!=``) and wildcard bands (``==2.*``) are deliberate compatibility
        statements authored by the user and are preserved verbatim, so
        ``celery[redis]>=5.0,<6.0`` updated to ``5.5.3`` becomes
        ``celery[redis]>=5.5.3,<6.0`` rather than a hard ``==`` pin. Pass
        ``pin=True`` to opt into replacing every specifier with
        ``==new_version``.

        Hashes are version-specific. Updating the version while silently
        removing ``--hash`` entries degrades integrity guarantees and can break
        hash-pinned installs (pip ``--require-hashes`` mode). To prevent silent
        security regressions, hashed requirements are rejected by default unless
        ``allow_hash_removal=True`` is explicitly provided by the caller.

        Args:
            new_version: Version string to apply.
            pin: Replace all specifiers with an exact ``==new_version`` pin,
                discarding any declared range. Defaults to ``False``.
            preserve_trailing_newline: Ensure output ends with ``\\n``.
            allow_hash_removal: Allow updating requirements that include
                ``--hash`` entries by removing those hashes in the output.
                Defaults to ``False``.

        Returns:
            Updated requirement string.

        Raises:
            ValueError: The requirement has one or more ``--hash`` entries and
                ``allow_hash_removal`` is ``False``; or the requirement's own
                preserved constraints exclude *new_version* (which would
                produce an unsatisfiable line).
        """
        if self.hashes and not allow_hash_removal:
            raise ValueError(
                f"Cannot update hashed requirement '{self.name}' without explicit "
                "hash-removal opt-in"
            )

        if pin:
            new_specs: List[Tuple[str, str]] = [("==", new_version)]
        else:
            new_specs = rewrite_version_specs(self.specs, new_version)

        # Specifiers are not rendered for direct references, so an unsatisfiable
        # combination cannot reach the file in that case.
        if not self.url and not specs_allow_version(new_specs, new_version):
            raise ValueError(
                f"Cannot update '{self.name}' to {new_version}: the declared "
                f"constraint '{specs_to_string(self.specs)}' excludes that "
                "version. Relax the constraint, or pass pin=True to replace it"
            )

        updated = Requirement(
            name=self.name,
            specs=new_specs,
            extras=list(self.extras),
            markers=self.markers,
            url=self.url,
            editable=self.editable,
            hashes=[],
            comment=self.comment,
            line_number=self.line_number,
            source_file=self.source_file,
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
