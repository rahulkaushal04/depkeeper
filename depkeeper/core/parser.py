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
• Include / constraint directives (-r, -c) with recursive parsing
• Local path-based dependencies (relative/absolute)
• Quoted URL support
• Circular dependency detection
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
from typing import List, Optional, Dict
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
QUOTES_RE = re.compile(r'^["\'](.+)["\']$')

# Enhanced URL pattern to support various schemes
URL_RE = re.compile(
    r"^(?P<scheme>(git\+https?|git\+ssh|git\+git|bzr\+https?|hg\+https?|svn\+https?|https?|file))://"
    r"(?P<path>.+?)(?:#egg=(?P<egg>[^ ]+))?$"
)

# Local path pattern (matches relative and absolute paths)
LOCAL_PATH_RE = re.compile(
    r"^(?P<path>(?:\.{1,2}[/\\]|[/\\]|[a-zA-Z]:[/\\]).+?)(?:#egg=(?P<egg>[^ ]+))?$"
)


class RequirementsParser:
    """
    Parser for `requirements.txt` content.

    This class supports:
    - Single-line parsing via :meth:`parse_line`
    - Whole-file parsing via :meth:`parse_file`
    - String input parsing via :meth:`parse_string`
    - Recursive include directives (-r)
    - Constraint directives (-c)
    - Circular dependency detection

    Errors are collected in `self.errors` and never raised unless a file
    read operation fails.
    """

    def __init__(self) -> None:
        self.errors: List[ParseError] = []
        self.warnings: List[str] = []
        self._include_stack: List[Path] = []
        self._constraints: Dict[str, Requirement] = {}

    # ----------------------------------------------------------------------
    # Top-level entry points
    # ----------------------------------------------------------------------

    def parse_file(
        self,
        path: str | Path,
        is_constraint: bool = False,
        _parent_path: Optional[Path] = None,
    ) -> List[Requirement]:
        """
        Parse a requirements file from disk.

        Parameters
        ----------
        path :
            Path to the file on disk.
        is_constraint :
            If True, treat as constraint file (doesn't return requirements).
        _parent_path :
            Internal parameter for recursive includes.

        Returns
        -------
        list[Requirement]

        Raises
        ------
        FileOperationError
            If the file does not exist or cannot be read.
        ParseError
            If circular dependency is detected.
        """
        path = Path(path)

        # Resolve relative paths from parent file
        if _parent_path and not path.is_absolute():
            path = (_parent_path.parent / path).resolve()
        else:
            path = path.resolve()

        # Check for circular dependencies
        if path in self._include_stack:
            cycle = " -> ".join(str(p) for p in self._include_stack + [path])
            raise ParseError(
                f"Circular dependency detected: {cycle}",
                file_path=str(path),
            )

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

        # Track include stack for circular dependency detection
        self._include_stack.append(path)
        try:
            result = self.parse_string(
                content,
                file_path=str(path),
                is_constraint=is_constraint,
                _current_path=path,
            )
        finally:
            self._include_stack.pop()

        return result

    def parse_string(
        self,
        content: str,
        file_path: Optional[str] = None,
        is_constraint: bool = False,
        _current_path: Optional[Path] = None,
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
        is_constraint :
            If True, store as constraints instead of returning.
        _current_path :
            Internal parameter for recursive includes.

        Returns
        -------
        list[Requirement]
        """
        requirements: List[Requirement] = []

        for line_no, line in enumerate(content.splitlines(), start=1):
            try:
                result = self.parse_line(
                    line, line_no, file_path, _current_path=_current_path
                )

                if result is None:
                    continue

                # Handle include directive result
                if isinstance(result, list):
                    requirements.extend(result)
                elif isinstance(result, Requirement):
                    if is_constraint:
                        # Store constraints for later application
                        self._constraints[result.name] = result
                    else:
                        requirements.append(result)

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
        _current_path: Optional[Path] = None,
    ) -> Optional[Requirement | List[Requirement]]:
        """
        Parse an individual line in a `requirements.txt` file.

        Returns
        -------
        Requirement | List[Requirement] | None
            - Requirement: A single parsed requirement
            - List[Requirement]: Multiple requirements from include directive
            - None: Empty/comment line or processed directive
        """
        stripped = line.strip()

        # Skip empty / pure comment lines
        if not stripped or stripped.startswith("#"):
            return None

        # Extract inline comment (but not URL fragments like #egg=)
        # We need to be smart: # is a comment UNLESS it's part of a URL
        comment = None
        comment_match = self._extract_comment(stripped)
        if comment_match:
            comment = comment_match[1]
            stripped = comment_match[0]

        # Handle include directives (-r)
        if stripped.startswith(INCLUDE_DIRECTIVE):
            return self._handle_include_directive(
                stripped, line_number, file_path, _current_path
            )

        # Handle constraint directives (-c)
        if stripped.startswith(CONSTRAINT_DIRECTIVE):
            return self._handle_constraint_directive(
                stripped, line_number, file_path, _current_path
            )

        # Remove quotes if present
        stripped = self._remove_quotes(stripped)

        # Editable installs
        editable = False
        if stripped.startswith(EDITABLE_DIRECTIVE):
            editable = True
            stripped = stripped[len(EDITABLE_DIRECTIVE) :].strip()

        # Extract --hash arguments
        hashes = HASH_RE.findall(stripped)
        if hashes:
            stripped = HASH_RE.sub("", stripped).strip()

        # Parse direct URLs FIRST (git/https/file) - must come before local paths
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

        # Parse local paths (after URLs to avoid conflicts)
        local_path_match = LOCAL_PATH_RE.match(stripped)
        if local_path_match:
            return self._parse_path_requirement(
                match=local_path_match,
                editable=editable,
                hashes=hashes,
                comment=comment,
                raw_line=line,
                line_number=line_number,
                _current_path=_current_path,
            )

        # Parse normal PEP 508 requirement
        req = self._parse_standard_requirement(
            stripped,
            editable=editable,
            hashes=hashes,
            comment=comment,
            raw_line=line,
            line_number=line_number,
            file_path=file_path,
        )

        # Apply constraints if applicable
        return self._apply_constraints(req)

    # ----------------------------------------------------------------------
    # Directive handlers
    # ----------------------------------------------------------------------

    def _handle_include_directive(
        self,
        line: str,
        line_number: int,
        file_path: Optional[str],
        current_path: Optional[Path],
    ) -> Optional[List[Requirement]]:
        """Handle -r/--requirement directive."""
        parts = line.split(maxsplit=1)
        if len(parts) < 2:
            self.warnings.append(
                f"Line {line_number}: Include directive missing file path"
            )
            return None

        include_path = parts[1].strip()

        if not current_path:
            self.warnings.append(
                f"Line {line_number}: Cannot resolve include path without base file"
            )
            return None

        try:
            return self.parse_file(
                include_path, is_constraint=False, _parent_path=current_path
            )
        except (FileOperationError, ParseError) as exc:
            self.errors.append(
                ParseError(
                    f"Failed to process include directive: {exc}",
                    line_number=line_number,
                    line_content=line,
                    file_path=file_path,
                )
            )
            return None

    def _handle_constraint_directive(
        self,
        line: str,
        line_number: int,
        file_path: Optional[str],
        current_path: Optional[Path],
    ) -> None:
        """Handle -c/--constraint directive."""
        parts = line.split(maxsplit=1)
        if len(parts) < 2:
            self.warnings.append(
                f"Line {line_number}: Constraint directive missing file path"
            )
            return None

        constraint_path = parts[1].strip()

        if not current_path:
            self.warnings.append(
                f"Line {line_number}: Cannot resolve constraint path without base file"
            )
            return None

        try:
            self.parse_file(
                constraint_path, is_constraint=True, _parent_path=current_path
            )
        except (FileOperationError, ParseError) as exc:
            self.errors.append(
                ParseError(
                    f"Failed to process constraint directive: {exc}",
                    line_number=line_number,
                    line_content=line,
                    file_path=file_path,
                )
            )

        return None

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
    # Path-based requirement helper
    # ----------------------------------------------------------------------

    def _parse_path_requirement(
        self,
        match: re.Match[str],
        editable: bool,
        hashes: List[str],
        comment: Optional[str],
        raw_line: str,
        line_number: int,
        _current_path: Optional[Path],
    ) -> Requirement:
        """
        Parse local path-based dependencies.
        """
        path_str = match.group("path")
        egg_name = match.group("egg")

        # Resolve path
        path = Path(path_str)
        if _current_path and not path.is_absolute():
            path = (_current_path.parent / path).resolve()
        else:
            path = path.resolve()

        # Extract package name
        if not egg_name:
            egg_name = path.name
            if egg_name.endswith(".tar.gz"):
                egg_name = egg_name[:-7]
            elif egg_name.endswith(".zip"):
                egg_name = egg_name[:-4]

        # Convert to file:// URL for consistency
        url = path.as_uri()

        return Requirement(
            name=self._normalize_name(egg_name),
            specs=[],
            extras=[],
            markers=None,
            url=url,
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
    def _remove_quotes(line: str) -> str:
        """
        Remove surrounding quotes from a line.
        """
        match = QUOTES_RE.match(line)
        if match:
            return match.group(1)
        return line

    @staticmethod
    def _extract_comment(line: str) -> Optional[tuple[str, str]]:
        """
        Extract comment from line, being careful not to treat URL fragments as comments.

        Returns
        -------
        tuple[str, str] | None
            (line_without_comment, comment) or None if no comment found
        """
        # Find all # positions
        hash_positions = [i for i, char in enumerate(line) if char == "#"]

        if not hash_positions:
            return None

        # Check each # to see if it's a URL fragment or actual comment
        for pos in hash_positions:
            # Look backwards to see if this # is part of a URL
            # URLs typically have :// before the #
            before = line[:pos]

            # If we find ://, this # is likely part of URL (like #egg=, #subdirectory=)
            # But if there's a space before #, it's definitely a comment
            if " " in before[before.rfind("://") :] if "://" in before else True:
                # This is a comment
                comment = line[pos + 1 :].strip()
                line_clean = line[:pos].strip()
                return (line_clean, comment)

        return None

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

    def _apply_constraints(self, req: Requirement) -> Requirement:
        """
        Apply stored constraints to a requirement.
        """
        if req.name in self._constraints:
            constraint = self._constraints[req.name]
            # Merge specs from constraint
            if constraint.specs and not req.specs:
                req.specs = constraint.specs
        return req

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

    def get_constraints(self) -> Dict[str, Requirement]:
        """Return dictionary of loaded constraints."""
        return self._constraints.copy()

    def reset(self) -> None:
        """Reset parser state for reuse."""
        self.errors = []
        self.warnings = []
        self._include_stack = []
        self._constraints = {}
