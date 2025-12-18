"""Requirements file parser for depkeeper.

This module provides a robust parser for requirements.txt files and related
dependency specification formats used in Python projects. It handles the full
spectrum of pip requirements file syntax including version specifiers, URLs,
local paths, editable installs, hashes, constraints, and nested includes.

The RequirementsParser class follows PEP 440 and PEP 508 standards while also
supporting pip-specific extensions like -r (include), -c (constraints), -e
(editable), and --hash directives.

Examples
--------
Basic file parsing:

    >>> from depkeeper.core.parser import RequirementsParser
    >>> parser = RequirementsParser()
    >>> requirements = parser.parse_file("requirements.txt")
    >>> for req in requirements:
    ...     print(f"{req.name}: {req.specs}")

Parsing from string content:

    >>> content = '''
    ... requests>=2.28.0
    ... click~=8.0
    ... # Development dependencies
    ... pytest>=7.0
    ... '''
    >>> requirements = parser.parse_string(content)

Handling constraints:

    >>> # First parse constraints file
    >>> parser.parse_file("constraints.txt", is_constraint_file=True)
    >>> # Then parse requirements (constraints will be applied)
    >>> requirements = parser.parse_file("requirements.txt")

Single line parsing:

    >>> req = parser.parse_line("requests>=2.28.0,<3.0", line_number=1)
    >>> print(req.name, req.specs)
    requests [('>=', '2.28.0'), ('<', '3.0')]

Notes
-----
The parser preserves original formatting and comments from the source files,
allowing round-trip parsing and modification without losing user formatting.

Circular include dependencies are detected and raise ParseError to prevent
infinite loops.

See Also
--------
depkeeper.models.requirement.Requirement : Requirement data model
packaging.requirements : PEP 508 requirement parsing
pip : Reference implementation for requirements file format
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from packaging.requirements import Requirement as PkgRequirement, InvalidRequirement

from depkeeper.models.requirement import Requirement
from depkeeper.utils import get_logger, safe_read_file
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
    """Parser for requirements.txt files and dependency specifications.

    A comprehensive parser that handles the full syntax of pip requirements files
    including PEP 440 version specifiers, PEP 508 dependency specifications, and
    pip-specific extensions. Supports nested includes, constraints, editable
    installs, direct URLs, local paths, and integrity hashes.

    The parser maintains state for constraint files and include directives,
    allowing complex multi-file dependency specifications to be processed
    correctly. It detects circular includes and applies constraints
    automatically when parsing requirements.

    Attributes
    ----------
    logger : logging.Logger
        Logger instance for outputting warnings and debug information.

    Examples
    --------
    Basic usage:

        >>> from depkeeper.core.parser import RequirementsParser
        >>> parser = RequirementsParser()
        >>> requirements = parser.parse_file("requirements.txt")
        >>> print(f"Found {len(requirements)} packages")

    Parsing with constraints:

        >>> parser = RequirementsParser()
        >>> # Load constraints first
        >>> parser.parse_file("constraints.txt", is_constraint_file=True)
        >>> # Parse requirements (constraints applied automatically)
        >>> requirements = parser.parse_file("requirements.txt")
        >>> for req in requirements:
        ...     if req.name in parser.get_constraints():
        ...         print(f"{req.name} has constraints applied")

    String parsing:

        >>> content = "requests>=2.28.0\\nclick~=8.0"
        >>> requirements = parser.parse_string(content)

    Reusing parser:

        >>> parser.reset()  # Clear state for new parsing session
        >>> requirements = parser.parse_file("another-requirements.txt")

    Notes
    -----
    The parser is stateful and maintains:
    - Stack of included files (for circular dependency detection)
    - Dictionary of constraint requirements (applied during parsing)

    Call reset() to clear state between independent parsing sessions.

    The parser preserves formatting and comments, making it suitable for
    round-trip parsing and modification.

    See Also
    --------
    parse_file : Parse a requirements file from disk
    parse_string : Parse requirements from string content
    parse_line : Parse a single line
    reset : Clear parser state
    """

    def __init__(self) -> None:
        """Initialize the parser with empty state.

        Creates a new parser instance with no included files or constraints.
        The parser is ready to parse requirements immediately after creation.

        Examples
        --------
        >>> parser = RequirementsParser()
        >>> requirements = parser.parse_file("requirements.txt")
        """
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
        """Parse a requirements file from disk.

        Reads and parses a requirements file, handling all pip requirements.txt
        syntax including includes, constraints, and complex version specifiers.
        Automatically detects and prevents circular include dependencies.

        Parameters
        ----------
        file_path : str | Path
            Path to the requirements file on disk. Can be absolute or relative.
            If relative and _parent_directory_path is provided, resolved
            relative to that directory.
        is_constraint_file : bool, optional
            If True, treat as constraint file. Constraints are stored internally
            and applied to subsequent requirement parsing, but not returned.
            Default is False.
        _parent_directory_path : Path, optional
            Internal parameter used for resolving relative paths in recursive
            include directives. Should not be set by external callers.

        Returns
        -------
        List[Requirement]
            List of parsed requirement objects from the file. Empty list if
            is_constraint_file is True (constraints are stored, not returned).

        Raises
        ------
        FileOperationError
            If the file does not exist, cannot be read, or exceeds size limits.
        ParseError
            If circular dependency is detected in include directives or if
            file contains invalid syntax.

        Examples
        --------
        Basic file parsing:

            >>> parser = RequirementsParser()
            >>> requirements = parser.parse_file("requirements.txt")
            >>> for req in requirements:
            ...     print(f"{req.name}: {req.specs}")

        Parse constraints file:

            >>> parser = RequirementsParser()
            >>> parser.parse_file("constraints.txt", is_constraint_file=True)
            >>> # Constraints stored, empty list returned
            >>> requirements = parser.parse_file("requirements.txt")
            >>> # Requirements now have constraints applied

        Handle parsing errors:

            >>> try:
            ...     requirements = parser.parse_file("bad-requirements.txt")
            ... except ParseError as e:
            ...     print(f"Parse error on line {e.line_number}: {e.message}")

        See Also
        --------
        parse_string : Parse from string content
        parse_line : Parse a single line
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

        # Use safe_read_file for validated file reading with size checks
        file_content = safe_read_file(resolved_path)

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
        """Parse requirements from raw text content.

        Parses requirements from a string containing requirements.txt format
        content. Useful for parsing in-memory content or content from sources
        other than files.

        Parameters
        ----------
        requirements_content : str
            Raw text content of a requirements file. May contain multiple lines
            with requirements, comments, and directives.
        source_file_path : str, optional
            Optional file path for error metadata and better error messages.
            If provided, appears in error messages for context. Default is None.
        is_constraint_file : bool, optional
            If True, store parsed requirements as constraints instead of returning
            them. Constraints are applied to future requirement parsing.
            Default is False.
        _current_directory_path : Path, optional
            Internal parameter for resolving relative paths in include directives.
            Should not be set by external callers.

        Returns
        -------
        List[Requirement]
            List of parsed requirement objects. Empty list if is_constraint_file
            is True (constraints are stored internally, not returned).

        Examples
        --------
        Parse simple requirements:

            >>> content = '''
            ... requests>=2.28.0
            ... click~=8.0
            ... '''
            >>> parser = RequirementsParser()
            >>> requirements = parser.parse_string(content)
            >>> print(len(requirements))
            2

        Parse with comments:

            >>> content = '''
            ... # Web framework
            ... flask>=2.0.0
            ... # CLI tools
            ... click>=8.0
            ... '''
            >>> requirements = parser.parse_string(content)

        Parse constraints:

            >>> constraints = "requests<3.0\\nclick>=7.0,<9.0"
            >>> parser.parse_string(constraints, is_constraint_file=True)
            []  # Empty, constraints stored internally

        With source file for better errors:

            >>> try:
            ...     parser.parse_string(content, source_file_path="reqs.txt")
            ... except ParseError as e:
            ...     print(f"Error in {e.file_path} on line {e.line_number}")

        Notes
        -----
        The parser processes line-by-line, preserving line numbers for error
        reporting. Each line is parsed independently via parse_line().

        See Also
        --------
        parse_file : Parse from a file on disk
        parse_line : Parse a single requirement line
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
        """Parse an individual line from a requirements.txt file.

        Handles a single line from a requirements file, supporting all pip
        requirements.txt syntax including version specifiers, URLs, local paths,
        editable installs, hashes, comments, and directives.

        Parameters
        ----------
        line_text : str
            The raw line text to parse. May include inline comments.
        line_number : int
            The line number in the source file (1-indexed). Used for error
            reporting and requirement tracking.
        source_file_path : str, optional
            The source file path for error metadata. Included in ParseError
            exceptions for better error messages. Default is None.
        _current_directory_path : Path, optional
            Internal parameter for resolving relative paths in include and
            local path directives. Should not be set by external callers.

        Returns
        -------
        Requirement | List[Requirement] | None
            Returns different types based on the line content:
            - Requirement: Single parsed requirement (most common case)
            - List[Requirement]: Multiple requirements from -r include directive
            - None: Empty line, pure comment, or processed -c constraint directive

        Examples
        --------
        Parse basic requirement:

            >>> parser = RequirementsParser()
            >>> req = parser.parse_line("requests>=2.28.0", 1)
            >>> print(req.name, req.specs)
            requests [('>=', '2.28.0')]

        Parse with inline comment:

            >>> req = parser.parse_line("click~=8.0  # CLI framework", 2)
            >>> print(req.comment)
            # CLI framework

        Parse editable install:

            >>> req = parser.parse_line("-e git+https://github.com/user/repo.git", 3)
            >>> print(req.editable, req.url)
            True git+https://github.com/user/repo.git

        Parse with hash:

            >>> line = "requests==2.28.0 --hash=sha256:abc123..."
            >>> req = parser.parse_line(line, 4)
            >>> print(req.hashes)
            ['sha256:abc123...']

        Empty line returns None:

            >>> result = parser.parse_line("", 5)
            >>> print(result)
            None

        Comment line returns None:

            >>> result = parser.parse_line("# This is a comment", 6)
            >>> print(result)
            None

        Include directive returns list:

            >>> result = parser.parse_line("-r dev-requirements.txt", 7)
            >>> isinstance(result, list)
            True

        Notes
        -----
        The parser detects line type in this order:
        1. Empty lines and pure comments (return None)
        2. Include directives -r/--requirement (return List[Requirement])
        3. Constraint directives -c/--constraint (return None, stores internally)
        4. Direct URLs (git+https://, https://, file://, etc.)
        5. Local file paths (. or file://)
        6. Standard PEP 508 package specifications

        Inline comments (text after #) are preserved in the Requirement object.

        See Also
        --------
        parse_string : Parse multiple lines from string
        parse_file : Parse from file on disk
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
            self._handle_constraint_directive(
                requirement_spec, line_number, source_file_path, _current_directory_path
            )
            return None

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
        """Handle -r/--requirement include directive.

        Processes include directives that reference other requirements files,
        recursively parsing the included file and returning its requirements.
        Supports both short (-r) and long (--requirement) forms.

        Parameters
        ----------
        directive_line : str
            The complete directive line (e.g., "-r dev-requirements.txt").
        line_number : int
            Line number in source file for error reporting.
        source_file_path : str, optional
            Source file path for error context and messaging.
        current_directory : Path, optional
            Current directory for resolving relative include paths.
            Required for resolving relative file paths correctly.

        Returns
        -------
        List[Requirement] | None
            List of requirements from the included file, or None if the
            directive is malformed or path cannot be resolved.

        Raises
        ------
        ParseError
            If the included file cannot be parsed or contains errors.
            Original exception is wrapped with line context.

        Notes
        -----
        The parser maintains an include stack to detect circular dependencies.
        If a file tries to include itself (directly or indirectly), a ParseError
        is raised with details about the circular path.
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
        """Handle -c/--constraint directive.

        Processes constraint directives that reference constraint files,
        parsing and storing constraints for later application to requirements.
        Supports both short (-c) and long (--constraint) forms.

        Parameters
        ----------
        directive_line : str
            The complete directive line (e.g., "-c constraints.txt").
        line_number : int
            Line number in source file for error reporting.
        source_file_path : str, optional
            Source file path for error context and messaging.
        current_directory : Path, optional
            Current directory for resolving relative constraint file paths.
            Required for resolving relative file paths correctly.

        Returns
        -------
        None
            Constraints are stored in _constraint_requirements dict and
            automatically applied to subsequent requirements during parsing.

        Raises
        ------
        ParseError
            If the constraint file cannot be parsed or contains errors.
            Original exception is wrapped with line context.

        Notes
        -----
        Constraints are applied to requirements by merging version specifiers
        when a requirement doesn't specify its own versions. This allows
        separating version constraints from basic requirement specifications.
        """
        line_parts = directive_line.split(maxsplit=1)
        if len(line_parts) < 2:
            self.logger.warning(
                f"Line {line_number}: Constraint directive missing file path"
            )
            return

        constraint_file_path = line_parts[1].strip()

        if not current_directory:
            self.logger.warning(
                f"Line {line_number}: Cannot resolve constraint path without base file"
            )
            return

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
        """Build a standard PEP 508 requirement using packaging library.

        Parses a standard package requirement specification following PEP 508
        and PEP 440 standards. Handles package names, version specifiers,
        extras, and environment markers.

        Parameters
        ----------
        requirement_spec : str
            The requirement specification string. Examples:
            - "requests>=2.28.0"
            - "click~=8.0,<8.2"
            - "package[extra1,extra2]>=1.0; python_version >= '3.8'"
        is_editable : bool
            Whether this is an editable install (-e flag present).
        hash_values : List[str]
            List of hash values from --hash directives for integrity checking.
        inline_comment : str, optional
            Inline comment from the requirement line (text after #).
        original_line : str
            The original unparsed line text for reference.
        line_number : int
            Line number in source file for error reporting.
        source_file_path : str, optional
            Source file path for error context in exceptions.

        Returns
        -------
        Requirement
            Parsed requirement object with normalized package name, version
            specifications, extras, markers, and metadata.

        Raises
        ------
        ParseError
            If the requirement syntax is invalid or version specifiers are
            malformed. Includes line context for debugging.

        Notes
        -----
        Package names are normalized according to PEP 503 (lowercase with
        hyphens replacing underscores and dots).

        Version specifiers are validated to ensure they contain actual version
        numbers (empty version strings are rejected).
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
        url_components: Dict[str, Optional[str]],
        is_editable: bool,
        hash_values: List[str],
        inline_comment: Optional[str],
        original_line: str,
        line_number: int,
    ) -> Requirement:
        """Build a requirement from a direct URL.

        Parses URL-based requirements for direct installation from version
        control systems or direct downloads. Supports git, hg, svn, bzr, and
        direct file URLs.

        Parameters
        ----------
        url_string : str
            The complete URL string. Examples:
            - "git+https://github.com/user/repo.git@v1.0#egg=package"
            - "https://example.com/package-1.0.tar.gz"
            - "file:///path/to/package.whl"
        url_components : Dict[str, Optional[str]]
            Parsed URL components with keys:
            - 'scheme': URL scheme (git+https, https, file, etc.)
            - 'path': URL path after scheme
            - 'egg': Package name from #egg= fragment (if present)
        is_editable : bool
            Whether this is an editable install (-e flag present).
        hash_values : List[str]
            List of hash values from --hash directives for integrity checking.
        inline_comment : str, optional
            Inline comment from the requirement line (text after #).
        original_line : str
            The original unparsed line text for reference.
        line_number : int
            Line number in source file for error reporting.

        Returns
        -------
        Requirement
            Parsed requirement object with URL and inferred or explicit
            package name.

        Raises
        ------
        ParseError
            If package name cannot be determined from URL (no #egg= and
            name inference fails).

        Notes
        -----
        Best practice is to always include #egg=packagename in URLs for
        clarity. If missing, the parser attempts to infer the name from
        the URL path but this may not always be accurate.
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
        path_components: Dict[str, Optional[str]],
        current_directory: Optional[Path],
        is_editable: bool,
        hash_values: List[str],
        inline_comment: Optional[str],
        original_line: str,
        line_number: int,
    ) -> Requirement:
        """Build a requirement from a local file path.

        Parses requirements that reference local directories or archive files,
        commonly used for development installations or vendored dependencies.

        Parameters
        ----------
        path_components : Dict[str, Optional[str]]
            Parsed path components with keys:
            - 'path': Local file system path (relative or absolute)
            - 'egg': Package name from #egg= fragment (if present)
        current_directory : Path, optional
            Current directory for resolving relative paths. Required when
            path is relative.
        is_editable : bool
            Whether this is an editable install (-e flag present). Common
            for development dependencies.
        hash_values : List[str]
            List of hash values from --hash directives for integrity checking.
        inline_comment : str, optional
            Inline comment from the requirement line (text after #).
        original_line : str
            The original unparsed line text for reference.
        line_number : int
            Line number in source file for error reporting.

        Returns
        -------
        Requirement
            Parsed requirement object with file:// URL and inferred or
            explicit package name.

        Notes
        -----
        The path is resolved to an absolute path and converted to a file://
        URL for storage in the Requirement object.

        Package name is inferred from the path's directory or file name if
        #egg= is not provided. For best practices, always include #egg= for
        local paths.

        Common patterns:
        - "." - Current directory (editable install)
        - "./path/to/package" - Relative path
        - "/absolute/path" - Absolute path
        """
        path_value = path_components.get("path")
        if not path_value:
            raise ValueError("Path component is required")

        resolved_path = self._resolve_file_path(
            file_path=Path(path_value), parent_directory=current_directory
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
        """Resolve a file path to absolute form.

        Handles both relative and absolute paths, resolving relative paths
        against a parent directory if provided. Used for include directives
        and local path requirements.

        Parameters
        ----------
        file_path : Path
            The file path to resolve. May be relative or absolute.
        parent_directory : Path, optional
            Parent directory for resolving relative paths. If None and
            file_path is relative, resolved against current working directory.

        Returns
        -------
        Path
            Resolved absolute path with all symlinks resolved and '.' and
            '..' components normalized.

        Notes
        -----
        When parent_directory is provided and file_path is relative, the path
        is resolved relative to parent_directory.parent, not parent_directory
        itself. This is correct for requirements files where the parent is the
        file being parsed, not a directory.
        """
        if parent_directory and not file_path.is_absolute():
            return (parent_directory.parent / file_path).resolve()
        return file_path.resolve()

    def _parse_direct_url(
        self, requirement_line: str
    ) -> Optional[Dict[str, Optional[str]]]:
        """Parse a direct URL requirement.

        Detects and parses URL-based requirements with various schemes including
        version control systems and direct downloads.

        Parameters
        ----------
        requirement_line : str
            The requirement line to parse. Should start with a URL scheme.

        Returns
        -------
        Dict[str, Optional[str]] | None
            Dictionary with parsed components if URL detected:
            - 'scheme': URL scheme (e.g., 'git+https://', 'https://')
            - 'path': URL path after the scheme
            - 'egg': Package name from #egg= fragment (None if absent)
            Returns None if line doesn't start with a recognized URL scheme.

        Notes
        -----
        Supported URL schemes:
        - VCS: git+https://, git+ssh://, hg+https://, svn+https://, bzr+https://
        - Direct: https://, http://, file://

        The #egg=packagename fragment is extracted if present. Other URL
        fragments like #subdirectory= are preserved in the path.
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

    def _parse_local_file_path(
        self, requirement_line: str
    ) -> Optional[Dict[str, Optional[str]]]:
        """Parse a local file path requirement.

        Detects and parses local file system paths in requirements, supporting
        both Unix and Windows path formats.

        Parameters
        ----------
        requirement_line : str
            The requirement line to parse. Should be a file system path.

        Returns
        -------
        Dict[str, Optional[str]] | None
            Dictionary with parsed components if local path detected:
            - 'path': File system path (may be relative or absolute)
            - 'egg': Package name from #egg= fragment (None if absent)
            Returns None if line is not a recognized local path.

        Notes
        -----
        Recognized path patterns:
        - Current directory: "." or "#egg=..."
        - Relative paths: "./", "../", ".\\" (Windows), "..\\" (Windows)
        - Absolute Unix: "/path/to/package"
        - Absolute Windows: "C:\\path\\to\\package"

        The #egg=packagename fragment is extracted if present for package
        name identification.
        """
        is_local_path = False

        # Check for current directory (single dot)
        if requirement_line == "." or requirement_line.startswith(".#"):
            is_local_path = True
        # Check for relative paths (Unix and Windows)
        elif requirement_line.startswith(("./", "../", ".\\", "..\\")):
            is_local_path = True
        # Check for absolute paths (Unix and Windows)
        elif requirement_line.startswith("/") or (
            len(requirement_line) >= 3
            and requirement_line[1] == ":"
            and requirement_line[2] == "\\"
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
        """Infer package name from a file path.

        Extracts a package name from a file path by examining the filename
        and removing common archive extensions.

        Parameters
        ----------
        file_path : Path
            The file path to extract the package name from. May be a directory
            or archive file.

        Returns
        -------
        str
            Inferred package name derived from the file or directory name.

        Notes
        -----
        Common archive extensions are stripped:
        - .tar.gz, .tar.bz2 (source distributions)
        - .zip (source or wheel zips)
        - .whl (wheel packages)

        For example:
        - "requests-2.28.0.tar.gz" → "requests-2.28.0"
        - "package.whl" → "package"
        - "my-package/" → "my-package"
        """
        filename = file_path.name

        # Remove common archive extensions
        for extension in (".tar.gz", ".tar.bz2", ".zip", ".whl"):
            if filename.endswith(extension):
                return filename[: -len(extension)]
        return filename

    def _infer_package_name_from_url(self, url: str) -> Optional[str]:
        """Attempt to infer the package name from a URL.

        Extracts a package name from a URL by analyzing the path components,
        useful when #egg= fragment is not provided.

        Parameters
        ----------
        url : str
            The URL to parse. May be any URL format including VCS URLs.

        Returns
        -------
        str | None
            Inferred package name from the last meaningful path segment,
            or None if unable to infer a valid name.

        Notes
        -----
        The algorithm:
        1. Strips the URL scheme (everything before ://)
        2. Removes trailing slashes
        3. Removes .git extension if present
        4. Takes the last non-empty path segment

        Examples:
        - "git+https://github.com/user/package.git" → "package"
        - "https://example.com/downloads/package-1.0.tar.gz" → "package-1.0.tar.gz"
        - "https://github.com/user/repo/tree/main" → "main"

        This is a best-effort approach and may not always produce the correct
        package name. Always prefer explicit #egg=packagename.
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
        """Normalize package name according to PEP 503.

        Converts package names to a canonical form for consistent comparison
        and storage, following Python packaging standards.

        Parameters
        ----------
        package_name : str
            The package name to normalize. May contain uppercase, underscores,
            dots, or hyphens.

        Returns
        -------
        str
            Normalized package name in lowercase with hyphens.

        Notes
        -----
        PEP 503 normalization rules:
        - Convert to lowercase
        - Replace any runs of [._, -] with a single hyphen

        Examples:
        - "Django" → "django"
        - "python_dateutil" → "python-dateutil"
        - "Pillow" → "pillow"
        - "some.package" → "some-package"

        This ensures that "python_dateutil", "python-dateutil", and
        "Python.Dateutil" are all treated as the same package.

        See Also
        --------
        PEP 503: https://peps.python.org/pep-0503/
        """
        return re.sub(pattern=r"[-_.]+", repl="-", string=package_name).lower()

    def _remove_surrounding_quotes(self, text: str) -> str:
        """Remove surrounding quotes from a string.

        Strips matching quotes from the beginning and end of a string,
        handling both single and double quotes.

        Parameters
        ----------
        text : str
            The text to process. May or may not be quoted.

        Returns
        -------
        str
            Text with surrounding quotes removed if they were present,
            otherwise the original text unchanged.

        Notes
        -----
        Only removes quotes when:
        - String has at least 2 characters
        - First and last characters are matching quotes (' or ")

        Examples:
        - '"package"' → 'package'
        - "'package'" → 'package'
        - 'package' → 'package' (unchanged)
        - '"package' → '"package' (unchanged, mismatched)
        """
        if len(text) >= 2 and text[0] in ('"', "'") and text[0] == text[-1]:
            return text[1:-1]
        return text

    def _extract_inline_comment(self, line: str) -> Tuple[str, Optional[str]]:
        """Extract inline comment from a requirement line.

        Carefully separates requirement specifications from inline comments,
        handling special cases where # appears in URLs or fragments.

        Parameters
        ----------
        line : str
            The complete line to parse, potentially containing both requirement
            and comment.

        Returns
        -------
        Tuple[str, str | None]
            Tuple of (requirement_spec, comment):
            - requirement_spec: The requirement portion (before comment)
            - comment: The comment text (after #), or None if no comment

        Notes
        -----
        The parser intelligently distinguishes between:
        - Inline comments: "requests>=2.28.0  # HTTP library"
        - URL fragments: "git+https://github.com/user/repo.git#egg=package"
        - URL fragments: "package @ https://example.com/file.tar.gz#sha256=abc"

        URL fragments that start with special keywords are preserved:
        - #egg= (package name)
        - #subdirectory= (VCS subdirectory)
        - #sha1=, #sha256= (integrity hashes)

        The algorithm checks for :// before # to detect URLs, and only treats
        # as a comment marker when it's not part of a URL or after whitespace
        following a URL scheme.

        Examples:
        - "requests>=2.28.0  # comment" → ("requests>=2.28.0", "comment")
        - "git+https://repo.git#egg=pkg" → ("git+https://repo.git#egg=pkg", None)
        - "pkg  # comment with # inside" → ("pkg", "comment with # inside")
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
        """Apply stored constraints to a requirement.

        Merges version constraints from previously loaded constraint files
        into requirements that don't specify their own versions.

        Parameters
        ----------
        requirement : Requirement
            The requirement to apply constraints to.

        Returns
        -------
        Requirement
            The same requirement object, potentially modified with constraints.
            If no matching constraint exists or requirement already has specs,
            returned unchanged.

        Notes
        -----
        Constraint application rules:
        - Only applies if a constraint exists for this package name
        - Only applies if requirement has no version specs of its own
        - Constraint specs replace the empty specs list

        This allows separating version pinning (constraints.txt) from basic
        package declarations (requirements.txt).

        Example workflow:
        1. Parse constraints.txt with is_constraint_file=True
        2. Parse requirements.txt normally
        3. This method automatically applies constraints during step 2

        Example:
        Constraint: "requests<3.0,>=2.28"
        Requirement: "requests"
        Result: "requests<3.0,>=2.28"
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
        """Get all loaded constraint requirements.

        Returns a copy of the internal constraints dictionary that was populated
        by parsing constraint files (files parsed with is_constraint_file=True).

        Returns
        -------
        Dict[str, Requirement]
            Dictionary mapping package names to their constraint Requirement
            objects. Returns a copy to prevent external modification of internal
            state.

        Examples
        --------
        Check constraints after parsing:

            >>> parser = RequirementsParser()
            >>> parser.parse_file("constraints.txt", is_constraint_file=True)
            >>> constraints = parser.get_constraints()
            >>> if "requests" in constraints:
            ...     print(f"Requests constrained to: {constraints['requests'].specs}")

        Verify constraint application:

            >>> parser.parse_file("constraints.txt", is_constraint_file=True)
            >>> requirements = parser.parse_file("requirements.txt")
            >>> constraints = parser.get_constraints()
            >>> for req in requirements:
            ...     if req.name in constraints:
            ...         print(f"{req.name} has constraint applied")

        Notes
        -----
        Constraints are automatically applied to requirements during parsing.
        This method is primarily useful for inspection and debugging.

        See Also
        --------
        parse_file : Parse files (including constraint files)
        reset : Clear all constraints
        """
        return self._constraint_requirements.copy()

    def reset(self) -> None:
        """Reset parser state for independent parsing sessions.

        Clears all internal state including the include file stack and stored
        constraints. Use this to reuse a parser instance for parsing unrelated
        requirement files without constraint contamination.

        Returns
        -------
        None

        Examples
        --------
        Reuse parser for multiple projects:

            >>> parser = RequirementsParser()
            >>> # Parse first project
            >>> reqs1 = parser.parse_file("project1/requirements.txt")
            >>> parser.reset()  # Clear state
            >>> # Parse second project independently
            >>> reqs2 = parser.parse_file("project2/requirements.txt")

        Clear constraints between sessions:

            >>> parser = RequirementsParser()
            >>> parser.parse_file("constraints.txt", is_constraint_file=True)
            >>> print(len(parser.get_constraints()))  # Has constraints
            3
            >>> parser.reset()
            >>> print(len(parser.get_constraints()))  # Cleared
            0

        Notes
        -----
        After reset(), the parser is in the same state as a newly created
        instance. This is more efficient than creating a new parser instance
        for each parsing session.

        See Also
        --------
        get_constraints : View current constraints
        __init__ : Parser initialization
        """
        self._included_files_stack = []
        self._constraint_requirements = {}
