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
from typing import List, Optional, Dict, Tuple
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


NORMALIZE_RE = re.compile(r"[-_.]+")
HASH_RE = re.compile(r"--hash[=\s]+(\S+)")

URL_SCHEMES = (
    "git+https://",
    "git+http://",
    "git+ssh://",
    "git+git://",
    "bzr+https://",
    "bzr+http://",
    "bzr+ssh://",
    "hg+https://",
    "hg+http://",
    "hg+ssh://",
    "svn+https://",
    "svn+http://",
    "svn+ssh://",
    "https://",
    "http://",
    "file://",
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
        path = self._resolve_path(path=Path(path), parent=_parent_path)

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
            return self.parse_string(
                content,
                file_path=str(path),
                is_constraint=is_constraint,
                _current_path=path,
            )
        finally:
            self._include_stack.pop()

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

        stripped, comment = self._split_comment_from_line(stripped)

        # Handle include directives (-r)
        if stripped.startswith((INCLUDE_DIRECTIVE, "--requirement")):
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
        editable = stripped.startswith((EDITABLE_DIRECTIVE, "--editable"))
        if editable:
            stripped = stripped.split(None, 1)[1] if " " in stripped else ""

        # Extract --hash arguments
        hashes = HASH_RE.findall(stripped)
        if hashes:
            stripped = " ".join(
                part for part in stripped.split() if not part.startswith("--hash")
            )

        # Parse direct URLs FIRST (git/https/file) - must come before local paths
        url_info = self._parse_url(stripped)
        if url_info:
            req = self._build_url_requirement(
                url=stripped,
                url_info=url_info,
                editable=editable,
                hashes=hashes,
                comment=comment,
                raw_line=line,
                line_number=line_number,
            )

        elif path_info := self._parse_local_path(stripped):
            req = self._build_path_requirement(
                path_info=path_info,
                current_path=_current_path,
                editable=editable,
                hashes=hashes,
                comment=comment,
                raw_line=line,
                line_number=line_number,
            )

        else:
            req = self._build_standard_requirement(
                line=stripped,
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

    def _build_standard_requirement(
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

        return Requirement(
            name=self._normalize_name(pkg.name),
            specs=[(spec.operator, spec.version) for spec in pkg.specifier],
            extras=list(pkg.extras),
            markers=str(pkg.marker) if pkg.marker else None,
            url=getattr(pkg, "url", None),
            editable=editable,
            hashes=hashes,
            comment=comment,
            line_number=line_number,
            raw_line=raw_line,
        )

    # ----------------------------------------------------------------------
    # Direct URL requirement helper
    # ----------------------------------------------------------------------

    def _build_url_requirement(
        self,
        url: str,
        url_info: Dict[str, str],
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
        egg_name = url_info.get("egg") or self._extract_name_from_url(url)
        if not egg_name:
            raise ParseError(
                "URL requirements must include '#egg=<name>' or an inferable package name.",
                line_number=line_number,
                line_content=url,
            )

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
    # Path-based requirement helper
    # ----------------------------------------------------------------------

    def _build_path_requirement(
        self,
        path_info: Dict[str, str],
        current_path: Optional[Path],
        editable: bool,
        hashes: List[str],
        comment: Optional[str],
        raw_line: str,
        line_number: int,
    ) -> Requirement:
        """
        Parse local path-based dependencies.
        """
        path = self._resolve_path(path=Path(path_info["path"]), parent=current_path)
        egg_name = path_info.get("egg") or self._extract_package_name_from_path(path)

        return Requirement(
            name=self._normalize_name(egg_name),
            specs=[],
            extras=[],
            markers=None,
            url=path.as_uri(),
            editable=editable,
            hashes=hashes,
            comment=comment,
            line_number=line_number,
            raw_line=raw_line,
        )

    # ----------------------------------------------------------------------
    # Utilities
    # ----------------------------------------------------------------------

    def _resolve_path(self, path: Path, parent: Optional[Path]) -> Path:
        if parent and not path.is_absolute():
            return (parent.parent / path).resolve()
        return path.resolve()

    def _parse_url(self, line: str) -> Optional[Dict[str, str]]:
        for scheme in URL_SCHEMES:
            if line.startswith(scheme):
                egg = None
                if "#egg=" in line:
                    url_part, egg_part = line.split("#egg=", 1)
                    egg = egg_part.split("&")[0].split()[0]
                    return {
                        "scheme": scheme,
                        "path": url_part[len(scheme) :],
                        "egg": egg,
                    }
                return {"scheme": scheme, "path": line[len(scheme) :], "egg": None}
        return None

    def _parse_local_path(self, line: str) -> Optional[Dict[str, str]]:

        is_path = False

        if line.startswith(("./", "../", ".\\", ":\\")):
            is_path = True

        elif line.startswith("/") or (len(line) > 3 and line[1:3] == ":\\"):
            is_path = True

        if not is_path:
            return None

        if "#egg=" in line:
            path_part, egg_part = line.split("#egg=", 1)
            egg = egg_part.split("&")[0].split()[0]
            return {"path": path_part, "egg": egg}

        return {"path": line, "egg": None}

    def _extract_package_name_from_path(self, path: Path):
        name = path.name

        for ext in (".tar.gz", ".tar.bz2", ".zip", ".whl"):
            if name.endswith(ext):
                return name[: -len(ext)]
        return name

    def _normalize_name(self, name: str) -> str:
        """
        Normalize distribution name according to PEP 503.
        """
        return NORMALIZE_RE.sub("-", name).lower()

    def _remove_quotes(self, text: str) -> str:
        """
        Remove surrounding quotes from a line.
        """
        if len(text) >= 2 and text[0] in ('"', "'") and text[0] == text[-1]:
            return text[1:-1]
        return text



    def _extract_name_from_url(self, url: str) -> Optional[str]:
        """
        Attempt to infer the package name from a URL path.
        """
        path = url.split("://", 1)[1] if "://" in url else url
        path = path.rstrip("/")

        if path.endswith(".git"):
            path = path[:-4]

        segments = path.replace("\\", "/").split("/")
        for segment in reversed(segments):
            if segment and segment not in ("#", "?"):
                return segment

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

    def _split_comment_from_line(self, line: str) -> Tuple[str, Optional[str]]:
        for i, char in enumerate(line):
            if char != "#":
                continue

            before = line[:i]
            url_start = before.rfind("://")

            if url_start == -1 or " " in before[url_start:]:
                return line[:i].strip(), line[i + 1 :].strip()

        return line, None

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
