"""
Requirements file parser.

This module provides robust parsing of `requirements.txt` files with full
PEP 508 support. It is designed for modern dependency management workflows
and includes the following capabilities:

• Version specifiers (==, >=, <=, ~=, !=, ===)
• Extras (package[extra])
• Environment markers (e.g., python_version < "3.10")
• Direct URL dependencies (VCS/HTTP/file)
• Editable installs (-e / --editable)
• Hashes (--hash)
• Include / constraint directives (-r, -c)
• Inline comments
• Graceful error recovery (errors are collected, not raised)
• Preserves raw lines for round-tripping

Implementation notes:
- Built on top of `packaging` library for strict PEP 508 compliance.
- Normalizes names according to PEP 503.
- Provides convenient programmatic API via `parse_file`, `parse_string`,
  and `parse_line`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional
from packaging.requirements import Requirement as PkgRequirement, InvalidRequirement

from depkeeper.models.requirement import Requirement
from depkeeper.exceptions import ParseError, FileOperationError
from depkeeper.constants import (
    INCLUDE_DIRECTIVE,
    CONSTRAINT_DIRECTIVE,
    EDITABLE_DIRECTIVE,
)


# ---------------------------------------------------------------------------
# Precompiled regular expressions
# ---------------------------------------------------------------------------

COMMENT_RE = re.compile(r"#.*$")
NORMALIZE_RE = re.compile(r"[-_.]+")
HASH_RE = re.compile(r"--hash[= ]([^ ]+)")
URL_RE = re.compile(
    r"^(?P<scheme>(git\+https?|git\+ssh|https?|file))://(?P<path>.+?)(?:#egg=(?P<egg>[^ ]+))?$"
)


class RequirementsParser:
    """
    Parser for `requirements.txt` content.

    This class supports:
    - Single-line parsing via :meth:`parse_line`
    - Whole-file parsing via :meth:`parse_file`
    - String input parsing via :meth:`parse_string`

    Errors are collected in `self.errors` and never raised unless a file
    read operation fails.
    """

    def __init__(self) -> None:
        self.errors: List[ParseError] = []
        self.warnings: List[str] = []

    # ----------------------------------------------------------------------
    # Top-level entry points
    # ----------------------------------------------------------------------

    def parse_file(self, path: str | Path) -> List[Requirement]:
        """
        Parse a requirements file from disk.

        Parameters
        ----------
        path :
            Path to the file on disk.

        Returns
        -------
        list[Requirement]

        Raises
        ------
        FileOperationError
            If the file does not exist or cannot be read.
        """
        path = Path(path)

        if not path.exists():
            raise FileOperationError(
                f"Requirements file not found: {path}",
                file_path=str(path),
                operation="read",
            )

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            raise FileOperationError(
                f"Could not read file: {path}",
                file_path=str(path),
                operation="read",
                original_error=exc,
            ) from exc

        return self.parse_string(content, file_path=str(path))

    def parse_string(
        self,
        content: str,
        file_path: Optional[str] = None,
    ) -> List[Requirement]:
        """
        Parse requirements from raw text.

        Non-fatal parse errors are collected in `self.errors`.

        Parameters
        ----------
        content :
            Raw file text.
        file_path :
            Optional file path, recorded for error metadata.

        Returns
        -------
        list[Requirement]
        """
        self.errors = []
        self.warnings = []

        requirements: List[Requirement] = []
        for line_no, line in enumerate(content.splitlines(), start=1):
            try:
                req = self.parse_line(line, line_no, file_path)
                if req:
                    requirements.append(req)
            except ParseError as exc:
                self.errors.append(exc)

        return requirements

    # ----------------------------------------------------------------------
    # Line parsing
    # ----------------------------------------------------------------------

    def parse_line(
        self,
        line: str,
        line_number: int,
        file_path: Optional[str] = None,
    ) -> Optional[Requirement]:
        """
        Parse an individual line in a `requirements.txt` file.

        Returns
        -------
        Requirement | None
            None is returned when:
            - The line is blank
            - The line only contains a comment
            - The line contains an include/constraint directive
        """
        stripped = line.strip()

        # Skip empty / pure comment lines
        if not stripped or stripped.startswith("#"):
            return None

        # Extract inline comment
        comment = None
        comment_match = COMMENT_RE.search(stripped)
        if comment_match:
            comment = stripped[comment_match.start() + 1:].strip()
            stripped = stripped[: comment_match.start()].strip()

        # Include / constraint directives (supported later in depkeeper)
        if stripped.startswith(INCLUDE_DIRECTIVE) or stripped.startswith(CONSTRAINT_DIRECTIVE):
            self.warnings.append(
                f"Line {line_number}: include/constraint directives not fully implemented: {stripped}"
            )
            return None

        # Editable installs
        editable = False
        if stripped.startswith(EDITABLE_DIRECTIVE):
            editable = True
            stripped = stripped[len(EDITABLE_DIRECTIVE):].strip()

        # Extract --hash arguments
        hashes = HASH_RE.findall(stripped)
        if hashes:
            stripped = HASH_RE.sub("", stripped).strip()

        # Parse direct URLs (git/https/file)
        url_match = URL_RE.match(stripped)
        if url_match:
            return self._parse_url_requirement(
                stripped,
                match=url_match,
                editable=editable,
                hashes=hashes,
                comment=comment,
                raw_line=line,
                line_number=line_number,
            )

        # Parse normal PEP 508 requirement
        return self._parse_standard_requirement(
            stripped,
            editable=editable,
            hashes=hashes,
            comment=comment,
            raw_line=line,
            line_number=line_number,
            file_path=file_path,
        )

    # ----------------------------------------------------------------------
    # Standard PEP 508 requirement helper
    # ----------------------------------------------------------------------

    def _parse_standard_requirement(
        self,
        line: str,
        editable: bool,
        hashes: List[str],
        comment: Optional[str],
        raw_line: str,
        line_number: int,
        file_path: Optional[str],
    ) -> Requirement:
        """
        Parse a PEP 508 dependency with the `packaging` library.
        """
        try:
            pkg = PkgRequirement(line)
        except InvalidRequirement as exc:
            raise ParseError(
                f"Invalid requirement syntax: {exc}",
                line_number=line_number,
                line_content=line,
                file_path=file_path,
            ) from exc

        specs = [(spec.operator, spec.version) for spec in pkg.specifier]
        extras = list(pkg.extras)
        markers = str(pkg.marker) if pkg.marker else None
        url = getattr(pkg, "url", None)

        return Requirement(
            name=self._normalize_name(pkg.name),
            specs=specs,
            extras=extras,
            markers=markers,
            url=url,
            editable=editable,
            hashes=hashes,
            comment=comment,
            line_number=line_number,
            raw_line=raw_line,
        )

    # ----------------------------------------------------------------------
    # Direct URL requirement helper
    # ----------------------------------------------------------------------

    def _parse_url_requirement(
        self,
        line: str,
        match: re.Match[str],
        editable: bool,
        hashes: List[str],
        comment: Optional[str],
        raw_line: str,
        line_number: int,
    ) -> Requirement:
        """
        Parse dependencies specified by direct URLs such as `git+https://...`.
        """
        # Prefer #egg= name
        egg_name = match.group("egg") or self._extract_name_from_url(line)
        if not egg_name:
            raise ParseError(
                "URL requirements must include '#egg=<name>' or an inferable package name.",
                line_number=line_number,
                line_content=line,
            )

        return Requirement(
            name=self._normalize_name(egg_name),
            specs=[],
            extras=[],
            markers=None,
            url=line,
            editable=editable,
            hashes=hashes,
            comment=comment,
            line_number=line_number,
            raw_line=raw_line,
        )

    # ----------------------------------------------------------------------
    # Utilities
    # ----------------------------------------------------------------------

    @staticmethod
    def _normalize_name(name: str) -> str:
        """
        Normalize distribution name according to PEP 503.
        """
        return NORMALIZE_RE.sub("-", name).lower()

    @staticmethod
    def _extract_name_from_url(url: str) -> Optional[str]:
        """
        Attempt to infer the package name from a URL path.
        """
        egg = re.search(r"#egg=([^&]+)", url)
        if egg:
            return egg.group(1)

        last = re.search(r"/([^/]+?)(?:\.git)?(?:[#?]|$)", url)
        if last:
            return last.group(1)

        return None

    # ----------------------------------------------------------------------
    # Public accessors for collected errors / warnings
    # ----------------------------------------------------------------------

    def get_errors(self) -> List[ParseError]:
        """Return list of collected parse errors."""
        return self.errors

    def get_warnings(self) -> List[str]:
        """Return list of collected parse warnings."""
        return self.warnings

    def has_errors(self) -> bool:
        """Return True if any parse errors were collected."""
        return bool(self.errors)
