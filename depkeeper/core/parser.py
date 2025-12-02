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

from depkeeper.utils.logger import get_logger
from depkeeper.models.requirement import Requirement
from depkeeper.exceptions import ParseError, FileOperationError
from depkeeper.constants import (
    HASH_DIRECTIVE,
    INCLUDE_DIRECTIVE,
    CONSTRAINT_DIRECTIVE,
    EDITABLE_DIRECTIVE,
    INCLUDE_DIRECTIVE_LONG,
    CONSTRAINT_DIRECTIVE_LONG,
    EDITABLE_DIRECTIVE_LONG,
)


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

    Attributes
    ----------
    logger : logging.Logger
        Logger instance for outputting warnings and debug information.
    """

    def __init__(self) -> None:
        """Initialize the parser with empty state."""
        self.logger = get_logger("parser")
        self._included_files_stack: List[Path] = []
        self._constraint_requirements: Dict[str, Requirement] = {}

    # ----------------------------------------------------------------------
    # Top-level entry points
    # ----------------------------------------------------------------------

    def parse_file(
        self,
        file_path: str | Path,
        is_constraint_file: bool = False,
        _parent_directory_path: Optional[Path] = None,
    ) -> List[Requirement]:
        """
        Parse a requirements file from disk.

        Parameters
        ----------
        file_path : str | Path
            Path to the requirements file on disk.
        is_constraint_file : bool, optional
            If True, treat as constraint file (stores constraints, doesn't return requirements).
            Default is False.
        _parent_directory_path : Path, optional
            Internal parameter for resolving relative paths in recursive includes.

        Returns
        -------
        List[Requirement]
            List of parsed requirement objects. Empty if is_constraint_file is True.

        Raises
        ------
        FileOperationError
            If the file does not exist or cannot be read.
        ParseError
            If circular dependency is detected in include directives.
        """
        resolved_path = self._resolve_file_path(
            file_path=Path(file_path), parent_directory=_parent_directory_path
        )

        # Check for circular dependencies in include directives
        if resolved_path in self._included_files_stack:
            cycle_path = " -> ".join(
                str(p) for p in self._included_files_stack + [resolved_path]
            )
            raise ParseError(
                f"Circular dependency detected: {cycle_path}",
                file_path=str(resolved_path),
            )

        if not resolved_path.exists():
            raise FileOperationError(
                f"Requirements file not found: {resolved_path}",
                file_path=str(resolved_path),
                operation="read",
            )

        try:
            file_content = resolved_path.read_text(encoding="utf-8")
        except Exception as exc:
            raise FileOperationError(
                f"Could not read file: {resolved_path}",
                file_path=str(resolved_path),
                operation="read",
                original_error=exc,
            ) from exc

        # Track include stack for circular dependency detection
        self._included_files_stack.append(resolved_path)
        try:
            return self.parse_string(
                file_content,
                source_file_path=str(resolved_path),
                is_constraint_file=is_constraint_file,
                _current_directory_path=resolved_path,
            )
        finally:
            self._included_files_stack.pop()

    def parse_string(
        self,
        requirements_content: str,
        source_file_path: Optional[str] = None,
        is_constraint_file: bool = False,
        _current_directory_path: Optional[Path] = None,
    ) -> List[Requirement]:
        """
        Parse requirements from raw text content.

        Parameters
        ----------
        requirements_content : str
            Raw text content of a requirements file.
        source_file_path : str, optional
            Optional file path for error metadata and context.
        is_constraint_file : bool, optional
            If True, store parsed requirements as constraints instead of returning them.
            Default is False.
        _current_directory_path : Path, optional
            Internal parameter for resolving relative paths in recursive includes.

        Returns
        -------
        List[Requirement]
            List of parsed requirement objects. Empty if is_constraint_file is True.
        """
        parsed_requirements: List[Requirement] = []

        for line_number, line_text in enumerate(
            requirements_content.splitlines(), start=1
        ):
            parse_result = self.parse_line(
                line_text,
                line_number,
                source_file_path,
                _current_directory_path=_current_directory_path,
            )

            if parse_result is None:
                continue

            # Handle include directive result (returns list of requirements)
            if isinstance(parse_result, list):
                parsed_requirements.extend(parse_result)
            elif isinstance(parse_result, Requirement):
                if is_constraint_file:
                    # Store constraints for later application to requirements
                    self._constraint_requirements[parse_result.name] = parse_result
                else:
                    parsed_requirements.append(parse_result)

        return parsed_requirements

    # ----------------------------------------------------------------------
    # Line parsing
    # ----------------------------------------------------------------------

    def parse_line(
        self,
        line_text: str,
        line_number: int,
        source_file_path: Optional[str] = None,
        _current_directory_path: Optional[Path] = None,
    ) -> Optional[Requirement | List[Requirement]]:
        """
        Parse an individual line from a requirements.txt file.

        Parameters
        ----------
        line_text : str
            The raw line text to parse.
        line_number : int
            The line number in the source file (for error reporting).
        source_file_path : str, optional
            The source file path for error metadata.
        _current_directory_path : Path, optional
            Internal parameter for resolving relative paths.

        Returns
        -------
        Requirement | List[Requirement] | None
            - Requirement: A single parsed requirement
            - List[Requirement]: Multiple requirements from include directive
            - None: Empty line, comment line, or processed constraint directive
        """
        stripped_line = line_text.strip()

        # Skip empty lines and pure comment lines
        if not stripped_line or stripped_line.startswith("#"):
            return None

        requirement_spec, inline_comment = self._extract_inline_comment(stripped_line)

        # Handle include directives (-r / --requirement)
        if requirement_spec.startswith((INCLUDE_DIRECTIVE, INCLUDE_DIRECTIVE_LONG)):
            return self._handle_include_directive(
                requirement_spec, line_number, source_file_path, _current_directory_path
            )

        # Handle constraint directives (-c / --constraint)
        if requirement_spec.startswith(
            (CONSTRAINT_DIRECTIVE, CONSTRAINT_DIRECTIVE_LONG)
        ):
            return self._handle_constraint_directive(
                requirement_spec, line_number, source_file_path, _current_directory_path
            )

        # Remove surrounding quotes if present
        requirement_spec = self._remove_surrounding_quotes(requirement_spec)

        # Check if this is an editable install
        is_editable = requirement_spec.startswith(
            (EDITABLE_DIRECTIVE, EDITABLE_DIRECTIVE_LONG)
        )
        if is_editable:
            requirement_spec = (
                requirement_spec.split(None, 1)[1] if " " in requirement_spec else ""
            )

        # Extract hash values from --hash arguments
        hash_values = re.findall(pattern=r"--hash[=\s]+(\S+)", string=requirement_spec)
        if hash_values:
            requirement_spec = " ".join(
                token
                for token in requirement_spec.split()
                if not token.startswith(HASH_DIRECTIVE)
            )

        # Parse direct URLs FIRST (git/https/file) - must come before local paths
        url_components = self._parse_direct_url(requirement_spec)
        if url_components:
            parsed_requirement = self._build_url_based_requirement(
                url_string=requirement_spec,
                url_components=url_components,
                is_editable=is_editable,
                hash_values=hash_values,
                inline_comment=inline_comment,
                original_line=line_text,
                line_number=line_number,
            )

        elif local_path_components := self._parse_local_file_path(requirement_spec):
            parsed_requirement = self._build_local_path_requirement(
                path_components=local_path_components,
                current_directory=_current_directory_path,
                is_editable=is_editable,
                hash_values=hash_values,
                inline_comment=inline_comment,
                original_line=line_text,
                line_number=line_number,
            )

        else:
            parsed_requirement = self._build_standard_pep508_requirement(
                requirement_spec=requirement_spec,
                is_editable=is_editable,
                hash_values=hash_values,
                inline_comment=inline_comment,
                original_line=line_text,
                line_number=line_number,
                source_file_path=source_file_path,
            )

        # Apply constraint specifications if applicable
        return self._apply_constraint_to_requirement(parsed_requirement)

    # ----------------------------------------------------------------------
    # Directive handlers
    # ----------------------------------------------------------------------

    def _handle_include_directive(
        self,
        directive_line: str,
        line_number: int,
        source_file_path: Optional[str],
        current_directory: Optional[Path],
    ) -> Optional[List[Requirement]]:
        """
        Handle -r/--requirement include directive.

        Parameters
        ----------
        directive_line : str
            The directive line to parse.
        line_number : int
            Line number for error reporting.
        source_file_path : str, optional
            Source file path for error context.
        current_directory : Path, optional
            Current directory for resolving relative paths.

        Returns
        -------
        List[Requirement] | None
            List of requirements from the included file, or None if error occurred.
        """
        line_parts = directive_line.split(maxsplit=1)
        if len(line_parts) < 2:
            self.logger.warning(
                f"Line {line_number}: Include directive missing file path"
            )
            return None

        included_file_path = line_parts[1].strip()

        if not current_directory:
            self.logger.warning(
                f"Line {line_number}: Cannot resolve include path without base file"
            )
            return None

        try:
            return self.parse_file(
                included_file_path,
                is_constraint_file=False,
                _parent_directory_path=current_directory,
            )
        except (FileOperationError, ParseError) as exc:
            raise ParseError(
                f"Failed to process include directive: {exc}",
                line_number=line_number,
                line_content=directive_line,
                file_path=source_file_path,
            ) from exc

    def _handle_constraint_directive(
        self,
        directive_line: str,
        line_number: int,
        source_file_path: Optional[str],
        current_directory: Optional[Path],
    ) -> None:
        """
        Handle -c/--constraint directive.

        Parameters
        ----------
        directive_line : str
            The directive line to parse.
        line_number : int
            Line number for error reporting.
        source_file_path : str, optional
            Source file path for error context.
        current_directory : Path, optional
            Current directory for resolving relative paths.

        Returns
        -------
        None
            Constraints are stored internally, not returned.
        """
        line_parts = directive_line.split(maxsplit=1)
        if len(line_parts) < 2:
            self.logger.warning(
                f"Line {line_number}: Constraint directive missing file path"
            )
            return None

        constraint_file_path = line_parts[1].strip()

        if not current_directory:
            self.logger.warning(
                f"Line {line_number}: Cannot resolve constraint path without base file"
            )
            return None

        try:
            self.parse_file(
                constraint_file_path,
                is_constraint_file=True,
                _parent_directory_path=current_directory,
            )
        except (FileOperationError, ParseError) as exc:
            raise ParseError(
                f"Failed to process constraint directive: {exc}",
                line_number=line_number,
                line_content=directive_line,
                file_path=source_file_path,
            ) from exc

        return None

    # ----------------------------------------------------------------------
    # Requirement builders
    # ----------------------------------------------------------------------

    def _build_standard_pep508_requirement(
        self,
        requirement_spec: str,
        is_editable: bool,
        hash_values: List[str],
        inline_comment: Optional[str],
        original_line: str,
        line_number: int,
        source_file_path: Optional[str],
    ) -> Requirement:
        """
        Build a standard PEP 508 requirement using the `packaging` library.

        Parameters
        ----------
        requirement_spec : str
            The requirement specification string (e.g., "requests>=2.28.0").
        is_editable : bool
            Whether this is an editable install.
        hash_values : List[str]
            List of hash values for verification.
        inline_comment : str, optional
            Inline comment from the requirement line.
        original_line : str
            The original unparsed line text.
        line_number : int
            Line number for error reporting.
        source_file_path : str, optional
            Source file path for error context.

        Returns
        -------
        Requirement
            Parsed requirement object.

        Raises
        ------
        ParseError
            If the requirement syntax is invalid.
        """
        try:
            parsed_pkg = PkgRequirement(requirement_spec)
        except InvalidRequirement as exc:
            raise ParseError(
                f"Invalid requirement syntax: {exc}",
                line_number=line_number,
                line_content=requirement_spec,
                file_path=source_file_path,
            ) from exc

        for spec in parsed_pkg.specifier:
            if not spec.version:
                raise ParseError(
                    f"Invalid version specifier: empty version in '{spec.operator}{spec.version}'",
                    line_number=line_number,
                    line_content=requirement_spec,
                    file_path=source_file_path,
                )

        return Requirement(
            name=self._normalize_package_name(parsed_pkg.name),
            specs=[(spec.operator, spec.version) for spec in parsed_pkg.specifier],
            extras=list(parsed_pkg.extras),
            markers=str(parsed_pkg.marker) if parsed_pkg.marker else None,
            url=getattr(parsed_pkg, "url", None),
            editable=is_editable,
            hashes=hash_values,
            comment=inline_comment,
            line_number=line_number,
            raw_line=original_line,
        )

    def _build_url_based_requirement(
        self,
        url_string: str,
        url_components: Dict[str, str],
        is_editable: bool,
        hash_values: List[str],
        inline_comment: Optional[str],
        original_line: str,
        line_number: int,
    ) -> Requirement:
        """
        Build a requirement from a direct URL (e.g., git+https://...).

        Parameters
        ----------
        url_string : str
            The complete URL string.
        url_components : Dict[str, str]
            Parsed URL components including scheme, path, and egg name.
        is_editable : bool
            Whether this is an editable install.
        hash_values : List[str]
            List of hash values for verification.
        inline_comment : str, optional
            Inline comment from the requirement line.
        original_line : str
            The original unparsed line text.
        line_number : int
            Line number for error reporting.

        Returns
        -------
        Requirement
            Parsed requirement object.

        Raises
        ------
        ParseError
            If package name cannot be determined from URL.
        """
        package_name = url_components.get("egg")

        if not package_name:
            package_name = self._infer_package_name_from_url(url_string)

            if package_name:
                self.logger.warning(
                    f"Line {line_number}: URL without '#egg=' - inferred name '{package_name}'"
                )
            else:
                raise ParseError(
                    "URL requirements must include '#egg=<name>' or an inferable package name.",
                    line_number=line_number,
                    line_content=url_string,
                )

        return Requirement(
            name=self._normalize_package_name(package_name),
            specs=[],
            extras=[],
            markers=None,
            url=url_string,
            editable=is_editable,
            hashes=hash_values,
            comment=inline_comment,
            line_number=line_number,
            raw_line=original_line,
        )

    def _build_local_path_requirement(
        self,
        path_components: Dict[str, str],
        current_directory: Optional[Path],
        is_editable: bool,
        hash_values: List[str],
        inline_comment: Optional[str],
        original_line: str,
        line_number: int,
    ) -> Requirement:
        """
        Build a requirement from a local file path.

        Parameters
        ----------
        path_components : Dict[str, str]
            Parsed path components including path and optional egg name.
        current_directory : Path, optional
            Current directory for resolving relative paths.
        is_editable : bool
            Whether this is an editable install.
        hash_values : List[str]
            List of hash values for verification.
        inline_comment : str, optional
            Inline comment from the requirement line.
        original_line : str
            The original unparsed line text.
        line_number : int
            Line number for error reporting.

        Returns
        -------
        Requirement
            Parsed requirement object.
        """
        resolved_path = self._resolve_file_path(
            file_path=Path(path_components["path"]), parent_directory=current_directory
        )
        package_name = path_components.get("egg") or self._infer_package_name_from_path(
            resolved_path
        )

        return Requirement(
            name=self._normalize_package_name(package_name),
            specs=[],
            extras=[],
            markers=None,
            url=resolved_path.as_uri(),
            editable=is_editable,
            hashes=hash_values,
            comment=inline_comment,
            line_number=line_number,
            raw_line=original_line,
        )

    # ----------------------------------------------------------------------
    # Path and URL parsing utilities
    # ----------------------------------------------------------------------

    def _resolve_file_path(
        self, file_path: Path, parent_directory: Optional[Path]
    ) -> Path:
        """
        Resolve a file path, handling relative paths from a parent directory.

        Parameters
        ----------
        file_path : Path
            The file path to resolve.
        parent_directory : Path, optional
            Parent directory for resolving relative paths.

        Returns
        -------
        Path
            Resolved absolute path.
        """
        if parent_directory and not file_path.is_absolute():
            return (parent_directory.parent / file_path).resolve()
        return file_path.resolve()

    def _parse_direct_url(self, requirement_line: str) -> Optional[Dict[str, str]]:
        """
        Parse a direct URL requirement (e.g., git+https://...).

        Parameters
        ----------
        requirement_line : str
            The requirement line to parse.

        Returns
        -------
        Dict[str, str] | None
            Dictionary with 'scheme', 'path', and 'egg' keys if URL found, None otherwise.
        """
        for scheme in URL_SCHEMES:
            if requirement_line.startswith(scheme):
                egg_name = None
                if "#egg=" in requirement_line:
                    url_part, egg_part = requirement_line.split("#egg=", 1)
                    egg_name = egg_part.split("&")[0].split()[0]
                    return {
                        "scheme": scheme,
                        "path": url_part[len(scheme) :],
                        "egg": egg_name,
                    }
                return {
                    "scheme": scheme,
                    "path": requirement_line[len(scheme) :],
                    "egg": None,
                }
        return None

    def _parse_local_file_path(self, requirement_line: str) -> Optional[Dict[str, str]]:
        """
        Parse a local file path requirement.

        Parameters
        ----------
        requirement_line : str
            The requirement line to parse.

        Returns
        -------
        Dict[str, str] | None
            Dictionary with 'path' and 'egg' keys if local path found, None otherwise.
        """
        is_local_path = False

        # Check for current directory (single dot)
        if requirement_line == "." or requirement_line.startswith(".#"):
            is_local_path = True
        # Check for relative paths (Unix and Windows)
        elif requirement_line.startswith(("./", "../", ".\\", ":\\")):
            is_local_path = True
        # Check for absolute paths (Unix and Windows)
        elif requirement_line.startswith("/") or (
            len(requirement_line) > 3 and requirement_line[1:3] == ":\\"
        ):
            is_local_path = True

        if not is_local_path:
            return None

        if "#egg=" in requirement_line:
            path_part, egg_part = requirement_line.split("#egg=", 1)
            egg_name = egg_part.split("&")[0].split()[0]
            return {"path": path_part, "egg": egg_name}

        return {"path": requirement_line, "egg": None}

    def _infer_package_name_from_path(self, file_path: Path) -> str:
        """
        Infer package name from a file path.

        Parameters
        ----------
        file_path : Path
            The file path to extract the package name from.

        Returns
        -------
        str
            Inferred package name.
        """
        filename = file_path.name

        # Remove common archive extensions
        for extension in (".tar.gz", ".tar.bz2", ".zip", ".whl"):
            if filename.endswith(extension):
                return filename[: -len(extension)]
        return filename

    def _infer_package_name_from_url(self, url: str) -> Optional[str]:
        """
        Attempt to infer the package name from a URL path.

        Parameters
        ----------
        url : str
            The URL to parse.

        Returns
        -------
        str | None
            Inferred package name or None if unable to infer.
        """
        # Remove scheme
        url_path = url.split("://", 1)[1] if "://" in url else url
        url_path = url_path.rstrip("/")

        # Remove .git extension if present
        if url_path.endswith(".git"):
            url_path = url_path[:-4]

        # Split by path separator and find last meaningful segment
        path_segments = url_path.replace("\\", "/").split("/")
        for segment in reversed(path_segments):
            if segment and segment not in ("#", "?"):
                return segment

        return None

    # ----------------------------------------------------------------------
    # String manipulation utilities
    # ----------------------------------------------------------------------

    def _normalize_package_name(self, package_name: str) -> str:
        """
        Normalize distribution name according to PEP 503.

        Parameters
        ----------
        package_name : str
            The package name to normalize.

        Returns
        -------
        str
            Normalized package name (lowercase with hyphens).
        """
        return re.sub(pattern=r"[-_.]+", repl="-", string=package_name).lower()

    def _remove_surrounding_quotes(self, text: str) -> str:
        """
        Remove surrounding quotes from a string.

        Parameters
        ----------
        text : str
            The text to process.

        Returns
        -------
        str
            Text with surrounding quotes removed if present.
        """
        if len(text) >= 2 and text[0] in ('"', "'") and text[0] == text[-1]:
            return text[1:-1]
        return text

    def _extract_inline_comment(self, line: str) -> Tuple[str, Optional[str]]:
        """
        Extract inline comment from a requirement line.

        Handles URLs containing '#' by checking for '://' prefix and '#egg=' fragments.

        Parameters
        ----------
        line : str
            The line to parse.

        Returns
        -------
        Tuple[str, str | None]
            Tuple of (requirement_spec, comment) where comment may be None.
        """
        for char_index, char in enumerate(line):
            if char != "#":
                continue

            text_before_hash = line[:char_index]
            text_after_hash = line[char_index + 1 :]
            url_scheme_position = text_before_hash.rfind("://")

            # Check if this is a URL fragment (#egg=, #subdirectory=, etc.)
            if text_after_hash.startswith(
                ("egg=", "subdirectory=", "sha1=", "sha256=")
            ):
                continue

            # If no URL scheme or there's whitespace after scheme, this is a comment
            if (
                url_scheme_position == -1
                or " " in text_before_hash[url_scheme_position:]
            ):
                return text_before_hash.strip(), text_after_hash.strip()

        return line, None

    # ----------------------------------------------------------------------
    # Constraint application
    # ----------------------------------------------------------------------

    def _apply_constraint_to_requirement(self, requirement: Requirement) -> Requirement:
        """
        Apply stored constraints to a requirement.

        Parameters
        ----------
        requirement : Requirement
            The requirement to apply constraints to.

        Returns
        -------
        Requirement
            The requirement with constraints applied.
        """
        if requirement.name in self._constraint_requirements:
            constraint = self._constraint_requirements[requirement.name]
            # Merge specs from constraint if requirement has no specs
            if constraint.specs and not requirement.specs:
                requirement.specs = constraint.specs
        return requirement

    # ----------------------------------------------------------------------
    # Public accessors
    # ----------------------------------------------------------------------

    def get_constraints(self) -> Dict[str, Requirement]:
        """
        Return dictionary of loaded constraints.

        Returns
        -------
        Dict[str, Requirement]
            Copy of internal constraints dictionary.
        """
        return self._constraint_requirements.copy()

    def reset(self) -> None:
        """
        Reset parser state for reuse.

        Clears include stack and constraints.
        """
        self._included_files_stack = []
        self._constraint_requirements = {}
