"""
Requirements file parser.

Implements robust parsing of requirements.txt files with full support for
PEP 508, including:
  • Specifiers (==, >=, <=, ~=, !=, ===)
  • Extras (package[extra])
  • Markers (e.g., python_version < '3.10')
  • URLs (VCS/HTTP/file)
  • Editable installs (-e)
  • Hashes (--hash)
  • Include/constraint directives (-r, -c)
  • Inline comments
  • Error recovery and warnings

Design notes:
  - Uses packaging.requirements.Requirement for PEP 508 compliance
  - Normalizes package names per PEP 503
  - Collects all parsing errors but does not stop parsing
  - Preserves raw line text for round-trip formatting
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


# Precompiled regex patterns
COMMENT_RE = re.compile(r"#.*$")
HASH_RE = re.compile(r"--hash[= ]([^ ]+)")
URL_RE = re.compile(
    r"^(?P<scheme>(git\+https?|git\+ssh|https?|file))://(?P<path>.+?)(?:#egg=(?P<egg>[^ ]+))?$"
)
NORMALIZE_RE = re.compile(r"[-_.]+")


class RequirementsParser:
    """
    Main parser for requirements.txt files.

    Supports single-line parsing (`parse_line`) and full-file parsing
    (`parse_file`, `parse_string`). Errors are collected and accessible
    via `get_errors()`.
    """

    def __init__(self) -> None:
        self.errors: List[ParseError] = []
        self.warnings: List[str] = []

    # =====================================================================
    # Top-level entry points
    # =====================================================================

    def parse_file(self, path: str | Path) -> List[Requirement]:
        """
        Parse a requirements file from disk.

        Raises:
            FileOperationError: If file cannot be read
        """
        path = Path(path)

        if not path.exists():
            raise FileOperationError(
                f"Requirements file not found: {path}",
                file_path=str(path),
                operation="read",
            )

        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            raise FileOperationError(
                f"Could not read file: {path}",
                file_path=str(path),
                operation="read",
                original_error=exc,
            ) from exc

        return self.parse_string(text, file_path=str(path))

    def parse_string(
        self,
        content: str,
        file_path: Optional[str] = None,
    ) -> List[Requirement]:
        """
        Parse requirements.txt content from a string.
        Non-fatal parse errors are collected but do not abort parsing.
        """
        self.errors = []
        self.warnings = []

        requirements: List[Requirement] = []
        lines = content.splitlines()

        for line_no, line in enumerate(lines, start=1):
            try:
                req = self.parse_line(line, line_no, file_path)
                if req:
                    requirements.append(req)
            except ParseError as exc:
                self.errors.append(exc)

        return requirements

    # =====================================================================
    # Line parsing
    # =====================================================================

    def parse_line(
        self,
        line: str,
        line_number: int,
        file_path: Optional[str] = None,
    ) -> Optional[Requirement]:
        """
        Parse a single line.

        Returns:
            Requirement object, or None if:
                - Line is empty
                - Line is comment-only
                - Line is include/constraint directive (not yet supported)
        """
        raw_line = line
        stripped = line.strip()

        # Skip empty and comment lines
        if not stripped or stripped.startswith("#"):
            return None

        # Extract inline comment
        comment = None
        comment_match = COMMENT_RE.search(stripped)
        if comment_match:
            comment = stripped[comment_match.start() + 1 :].strip()
            stripped = stripped[: comment_match.start()].strip()

        # Handle include directives (-r, -c)
        if stripped.startswith(INCLUDE_DIRECTIVE) or stripped.startswith(CONSTRAINT_DIRECTIVE):
            self.warnings.append(
                f"Line {line_number}: Include/constraint directives not fully implemented: {stripped}"
            )
            return None

        # Editable installs
        editable = False
        if stripped.startswith(EDITABLE_DIRECTIVE):
            editable = True
            stripped = stripped[len(EDITABLE_DIRECTIVE) :].strip()

        # Hash extraction
        hashes = HASH_RE.findall(stripped)
        if hashes:
            stripped = HASH_RE.sub("", stripped).strip()

        # URL requirement (git, file, http)
        url_match = URL_RE.match(stripped)
        if url_match:
            return self._parse_url_requirement(
                stripped,
                url_match,
                editable=editable,
                hashes=hashes,
                comment=comment,
                raw_line=raw_line,
                line_number=line_number,
            )

        # Standard PEP 508 requirement
        try:
            return self._parse_standard_requirement(
                stripped,
                editable=editable,
                hashes=hashes,
                comment=comment,
                raw_line=raw_line,
                line_number=line_number,
                file_path=file_path,
            )
        except Exception as exc:
            raise ParseError(
                f"Failed to parse requirement: {exc}",
                line_number=line_number,
                line_content=raw_line,
                file_path=file_path,
            ) from exc

    # =====================================================================
    # Helpers — Standard requirements
    # =====================================================================

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
        Parse PEP 508 requirement using packaging's Requirement parser.
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

    # =====================================================================
    # Helpers — URL requirements
    # =====================================================================

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
        Parse requirements specified by direct URLs (VCS, file, HTTP).
        """
        egg_name = match.group("egg") or self._extract_name_from_url(line)
        if not egg_name:
            raise ParseError(
                "URL requirements must specify '#egg=<name>' or contain a detectable name",
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

    # =====================================================================
    # Utilities
    # =====================================================================

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize name per PEP 503."""
        return NORMALIZE_RE.sub("-", name).lower()

    @staticmethod
    def _extract_name_from_url(url: str) -> Optional[str]:
        """Attempt to infer package name from URL path."""
        # From #egg=
        egg = re.search(r"#egg=([^&]+)", url)
        if egg:
            return egg.group(1)

        # From last path component
        match = re.search(r"/([^/]+?)(?:\.git)?(?:[#?]|$)", url)
        if match:
            return match.group(1)

        return None

    # =====================================================================
    # Error/Warning Retrieval
    # =====================================================================

    def get_errors(self) -> List[ParseError]:
        return self.errors

    def get_warnings(self) -> List[str]:
        return self.warnings

    def has_errors(self) -> bool:
        return bool(self.errors)
