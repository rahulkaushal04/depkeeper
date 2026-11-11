"""Adapter for pip ``requirements*.txt`` files (wraps the existing parser)."""

from __future__ import annotations

import io
from dataclasses import replace
import fnmatch
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

from depkeeper.exceptions import DepKeeperError
from depkeeper.models import Requirement
from depkeeper.core.parser import RequirementsParser
from depkeeper.utils.naming import normalize_package_name
from depkeeper.core.sources.base import SourceAdapter, SourceUpdate


def _is_continued(line: str) -> bool:
    """Whether *line* ends in an odd number of backslashes (pip continuation)."""
    text = line.rstrip("\r\n")
    return (len(text) - len(text.rstrip("\\"))) % 2 == 1


def _with_hashes(
    head: str,
    comment: Optional[str],
    digests: Sequence[str],
    *,
    multiline: bool,
    indent: str,
    eol: str,
) -> str:
    """Render *head* plus ``--hash=sha256:`` entries in the original layout.

    *head* must not carry the comment: it goes behind the last hash so a
    ``\\`` continuation is never swallowed by it.
    """
    tail = f"  # {comment}" if comment else ""
    hashes = [f"--hash=sha256:{d}" for d in digests]
    if not multiline:
        return " ".join([head] + hashes) + tail
    body = f" \\{eol}{indent}".join([head] + hashes)
    return body + tail


class RequirementsTxtAdapter(SourceAdapter):
    """``requirements.txt`` and friends; also the fallback for unknown files."""

    name = "requirements.txt"
    patterns = ("requirements*.txt",)
    fallback = True

    def can_handle(self, path: Path) -> bool:
        """Return True for ``requirements*.txt``, ``*.txt`` and ``*.in`` files."""
        return fnmatch.fnmatch(path.name.lower(), "requirements*.txt") or (
            path.suffix.lower() in (".txt", ".in")
        )

    def parse(self, path: Path) -> List[Requirement]:
        """Parse *path* with `RequirementsParser`."""
        reqs = RequirementsParser().parse_file(path)
        for req in reqs:
            req.source_format = self.name
        return reqs

    def apply_updates(
        self,
        original_text: str,
        updates: Sequence[SourceUpdate],
        *,
        pin: bool = False,
        allow_hash_removal: bool = False,
        refresh_hashes: bool = False,
        hash_digests: Optional[Mapping[Tuple[str, str], Sequence[str]]] = None,
        path: Optional[Union[str, Path]] = None,
    ) -> str:
        """See `SourceAdapter.apply_updates`.

        With *refresh_hashes*, hashed requirements are rewritten with
        ``--hash=sha256:...`` lines for the new version taken from
        *hash_digests* (``(normalized name, version)`` -> sha256 hex digests),
        in the layout the original used. A missing entry is an error.
        """
        label = str(path) if path is not None else "<requirements>"
        by_line: Dict[int, SourceUpdate] = {r.line_number: (r, v) for r, v in updates}
        # newline="" keeps every line's own terminator (CRLF / mixed files).
        lines = io.StringIO(original_text, newline="").readlines()

        out: List[str] = []
        skip_until = 0
        for line_number, line in enumerate(lines, start=1):
            if line_number <= skip_until:
                continue  # physical lines folded into a rewritten requirement
            hit = by_line.get(line_number)
            if hit is None:
                out.append(line)
                continue
            req, new_version = hit
            if req.hashes and not allow_hash_removal and not refresh_hashes:
                raise DepKeeperError(
                    f"Refusing to update hashed requirement at "
                    f"{label}:{line_number}. Re-run with "
                    "--allow-hash-removal to proceed without hashes."
                )
            # A ``\`` continued requirement spans several physical lines; the
            # rewrite replaces all of them (else hash lines orphan).
            last = line_number
            while last < len(lines) and _is_continued(lines[last - 1]):
                last += 1
            skip_until = last
            line_ending = lines[last - 1][len(lines[last - 1].rstrip("\r\n")) :]
            try:
                refreshing = refresh_hashes and bool(req.hashes)
                # The comment is re-attached after the hashes (see _with_hashes).
                head = (
                    replace(req, comment=None) if refreshing else req
                ).update_version(
                    new_version,
                    pin=pin,
                    preserve_trailing_newline=False,
                    allow_hash_removal=allow_hash_removal or refresh_hashes,
                )
                if refreshing:
                    digests = (hash_digests or {}).get(
                        (normalize_package_name(req.name), new_version)
                    )
                    if not digests:
                        raise DepKeeperError(
                            f"Cannot refresh hashes for {req.name}=={new_version} at "
                            f"{label}:{line_number}: no PyPI file digests available"
                        )
                    first = lines[line_number - 1]
                    eol = first[len(first.rstrip("\r\n")) :] or line_ending
                    # An own-line comment after a trailing ``\`` stays on its own line.
                    own = None
                    if last > line_number and lines[last - 1].lstrip().startswith("#"):
                        own, last = lines[last - 1], last - 1
                    indent = ""
                    if last > line_number:
                        nxt = lines[line_number]
                        indent = nxt[: len(nxt) - len(nxt.lstrip())]
                    out.append(
                        _with_hashes(
                            head,
                            None if own else req.comment,
                            sorted({d.lower() for d in digests}),
                            multiline=last > line_number,
                            indent=indent or "    ",
                            eol=eol,
                        )
                        + (eol if own else line_ending)
                    )
                    if own:
                        out.append(own)
                    continue
                out.append(head + line_ending)
            except ValueError as exc:
                raise DepKeeperError(
                    f"Cannot update requirement at {label}:{line_number}: {exc}"
                ) from exc
        return "".join(out)
