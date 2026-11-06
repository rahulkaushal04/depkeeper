"""Source adapter interface: how depkeeper reads and edits a dependency file.

Extension guide
---------------
To support a new file format (e.g. ``pyproject.toml``, ``environment.yml``):

1. Create ``depkeeper/core/sources/<format>.py`` with a `SourceAdapter`
   subclass. Set ``name`` and ``patterns`` (glob file names used when a
   *directory* is given, e.g. ``("pyproject.toml",)``).
2. ``can_handle(path)``: cheap, side-effect free check, normally on the file
   name only (``discover`` also uses it to skip files with nothing to manage).
3. ``parse(path)``: return `Requirement` objects for every PyPI dependency.
   Raise `ParseError` for malformed input. Fill ``line_number`` and, when the
   format is not line oriented, ``span`` (start, end character offsets of the
   *version specifier text* in the file) so ``apply_updates`` can find it.
   ``source_file`` and ``source_format`` are filled in for you if left unset.
   Non-PyPI entries (conda channels, ``pip:`` sub-sections handled elsewhere)
   should simply be left out.
4. ``apply_updates(original_text, updates)``: return the new full file text.
   Edit **in place and minimally**: touch only the specifier characters of
   each updated requirement; comments, ordering, quoting, whitespace and
   line endings must survive byte for byte. Use
   `Requirement.update_version` / ``rewrite_version_specs`` for the version
   logic so ``--pin`` and upper-bound preservation behave identically across
   formats. Raise `DepKeeperError` (with ``path:line`` in the message) when an
   update cannot be rendered; never return partial results. The caller strips
   a UTF-8 BOM before calling and re-adds it, and owns atomic writing,
   backups and rollback -- adapters never touch the disk when updating.
5. Register an instance in ``registry._register_builtins`` (order matters:
   it is the order of ``discover`` results and of ``get_adapter`` matching).
6. Tests: parse -> apply_updates round trips under ``tests/test_sources/``,
   including a "no-op update leaves bytes identical" case.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

from depkeeper.models import Requirement

#: One edit: the requirement to change and the version to move it to.
SourceUpdate = Tuple[Requirement, str]


class SourceAdapter(ABC):
    """Reads requirements from, and applies version updates to, one file format."""

    #: Human-readable format name; stored in ``Requirement.source_format``.
    name: str = ""
    #: Glob file names looked up by ``discover(directory)``.
    patterns: Tuple[str, ...] = ()
    #: Whether this adapter takes files that no adapter claims (e.g. ``*.in``).
    fallback: bool = False

    @abstractmethod
    def can_handle(self, path: Path) -> bool:
        """Return True when this adapter understands *path*."""

    def has_dependencies(self, path: Path) -> bool:
        """Return whether directory discovery should pick *path* up."""
        return self.can_handle(path)

    @abstractmethod
    def parse(self, path: Path) -> List[Requirement]:
        """Parse *path* into requirements carrying provenance.

        Raises:
            ParseError: The file is malformed.
        """

    @abstractmethod
    def apply_updates(
        self,
        original_text: str,
        updates: Sequence[SourceUpdate],
        *,
        pin: bool = False,
        allow_hash_removal: bool = False,
        path: Optional[Union[str, Path]] = None,
    ) -> str:
        """Return *original_text* with *updates* applied as minimal in-place edits.

        Args:
            original_text: Full file content (BOM already stripped).
            updates: ``(requirement, new_version)`` pairs, all from this file.
            pin: Replace all specifiers with ``==new_version``.
            allow_hash_removal: Permit updating hashed requirements.
            path: Used only to label error messages.

        Raises:
            DepKeeperError: An update cannot be rendered.
        """

    def requires_python(self, path: Path) -> Optional[str]:
        """Return the file's declared Python constraint (e.g. ``>=3.9``), if any."""
        return None
