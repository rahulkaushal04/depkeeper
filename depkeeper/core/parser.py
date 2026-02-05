"""Requirements file parser for PEP 440/508 specifications.

Parses ``requirements.txt`` files following the same conventions as pip:

- Standard PEP 508 package specifiers (``requests>=2.25.0``)
- Direct URLs with VCS schemes (``git+https://...#egg=pkg``)
- Local file paths (relative or absolute, with optional ``#egg=`` fragment)
- Editable installs (``-e .`` or ``-e git+...``)
- Include directives (``-r other.txt`` or ``--requirement other.txt``)
- Constraint files (``-c constraints.txt`` or ``--constraint constraints.txt``)
- Hash verification (``--hash sha256:...``)
- Inline comments (everything after ``#`` unless part of a URL fragment)

Typical usage::

    from depkeeper.parser import RequirementsParser

    # Parse from file
    parser = RequirementsParser()
    requirements = parser.parse_file("requirements.txt")

    for req in requirements:
        print(f"{req.name} {req.specs}")

    # Parse from string
    content = \"\"\"
    requests>=2.25.0
    -r base.txt
    git+https://github.com/org/repo.git#egg=mypkg
    \"\"\"
    reqs = parser.parse_string(content, source_file_path="inline")

    # Access constraint requirements loaded via -c
    constraints = parser.get_constraints()
    if "django" in constraints:
        print(f"Django constrained to {constraints['django'].specs}")

    # Reset parser state before reusing
    parser.reset()
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

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

# ---------------------------------------------------------------------------
# Recognized VCS and network URL schemes
# ---------------------------------------------------------------------------

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
    """Stateful parser for pip-style requirements files.

    Maintains two pieces of internal state across multiple ``parse_file``
    calls:

    1. **Include stack** — tracks the chain of ``-r`` directives to detect
       circular dependencies.
    2. **Constraint map** — stores all requirements loaded via ``-c``
       directives; these are applied to matching package names during
       parsing.

    Call :meth:`reset` to clear state before reusing the parser on an
    unrelated set of files.

    Example::

        >>> parser = RequirementsParser()
        >>> reqs = parser.parse_file("requirements.txt")
        >>> len(reqs)
        42
        >>> parser.get_constraints()
        {'django': <Requirement django==3.2>}
        >>> parser.reset()
    """

    def __init__(self) -> None:
        """Initialise the parser with empty state."""
        self.logger = get_logger("parser")

        # Stack of files currently being parsed (guards against cycles)
        self._included_files_stack: List[Path] = []

        # Constraint requirements loaded via -c directives
        self._constraint_requirements: Dict[str, Requirement] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_file(
        self,
        file_path: Union[str, Path],
        is_constraint_file: bool = False,
        _parent_directory_path: Optional[Path] = None,
    ) -> List[Requirement]:
        """Parse a requirements file from disk.

        Reads the file at *file_path*, processes all directives (``-r``,
        ``-c``, ``-e``, ``--hash``), and returns a flat list of
        :class:`Requirement` objects.  If *file_path* is relative and
        *_parent_directory_path* is provided (internal use by ``-r``), the
        path is resolved relative to the parent.

        Circular include chains (``A.txt`` includes ``B.txt`` which
        includes ``A.txt``) are detected and raise :exc:`ParseError`.

        Args:
            file_path: Path to the requirements file (absolute or relative).
            is_constraint_file: If ``True``, all parsed requirements are
                stored as constraints (via :attr:`_constraint_requirements`)
                rather than returned.  Used internally by ``-c`` handlers.
            _parent_directory_path: Internal parameter used when resolving
                ``-r`` includes; the parent's directory is used as the base
                for relative paths.

        Returns:
            List of :class:`Requirement` objects (empty if
            *is_constraint_file* is ``True``).

        Raises:
            FileOperationError: The file does not exist or cannot be read.
            ParseError: A circular include was detected or the file contains
                invalid syntax.

        Example::

            >>> parser = RequirementsParser()
            >>> reqs = parser.parse_file("requirements/prod.txt")
            >>> [r.name for r in reqs if r.editable]
            ['my-local-package']
        """
        resolved_path = self._resolve_file_path(
            file_path=Path(file_path),
            parent_directory=_parent_directory_path,
        )

        self.logger.debug(
            "Parsing file: %s%s",
            resolved_path,
            " (constraint file)" if is_constraint_file else "",
        )

        # Detect circular includes before reading
        if resolved_path in self._included_files_stack:
            cycle_path = " -> ".join(
                str(p) for p in self._included_files_stack + [resolved_path]
            )
            self.logger.error("Circular dependency detected: %s", cycle_path)
            raise ParseError(
                f"Circular dependency detected: {cycle_path}",
                file_path=str(resolved_path),
            )

        file_content = safe_read_file(resolved_path)

        self._included_files_stack.append(resolved_path)
        try:
            result = self.parse_string(
                file_content,
                source_file_path=str(resolved_path),
                is_constraint_file=is_constraint_file,
                _current_directory_path=resolved_path,
            )
            self.logger.debug(
                "Parsed %d requirement(s) from %s",
                len(result),
                resolved_path.name,
            )
            return result
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

        Splits *requirements_content* into lines and processes each via
        :meth:`parse_line`.  Requirements loaded from ``-r`` includes are
        flattened into the result list.

        Args:
            requirements_content: Multi-line requirements text.
            source_file_path: Optional file path for error messages (purely
                informational; does not affect parsing).
            is_constraint_file: If ``True``, all parsed requirements are
                stored in :attr:`_constraint_requirements` instead of being
                returned.
            _current_directory_path: Internal parameter; the directory
                containing the "file" being parsed (used to resolve
                relative ``-r`` / ``-c`` paths).

        Returns:
            List of :class:`Requirement` objects.

        Example::

            >>> content = \"\"\"
            ... flask>=2.0
            ... # A comment
            ... requests>=2.25.0
            ... \"\"\"
            >>> parser = RequirementsParser()
            >>> reqs = parser.parse_string(content)
            >>> [r.name for r in reqs]
            ['flask', 'requests']
        """
        parsed_requirements: List[Requirement] = []
        total_lines = len(requirements_content.splitlines())
        self.logger.debug(
            "Parsing %d line(s)%s",
            total_lines,
            f" from {source_file_path}" if source_file_path else "",
        )

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
                # Comment or blank line
                continue

            if isinstance(parse_result, list):
                # Nested requirements from -r directive
                self.logger.debug(
                    "Included %d requirement(s) from directive on line %d",
                    len(parse_result),
                    line_number,
                )
                parsed_requirements.extend(parse_result)
            elif isinstance(parse_result, Requirement):
                if is_constraint_file:
                    # Store in constraint map instead of returning
                    self._constraint_requirements[parse_result.name] = parse_result
                    self.logger.debug(
                        "Stored constraint: %s %s",
                        parse_result.name,
                        parse_result.specs,
                    )
                else:
                    parsed_requirements.append(parse_result)

        self.logger.debug(
            "Completed parsing: %d requirement(s)", len(parsed_requirements)
        )
        return parsed_requirements

    def parse_line(
        self,
        line_text: str,
        line_number: int,
        source_file_path: Optional[str] = None,
        _current_directory_path: Optional[Path] = None,
    ) -> Optional[Union[Requirement, List[Requirement]]]:
        """Parse a single line from a requirements file.

        Handles all pip-supported line types:

        - Blank lines and ``#`` comments → ``None``
        - ``-r file.txt`` → ``List[Requirement]`` (nested parse)
        - ``-c file.txt`` → ``None`` (side-effect: populates constraints)
        - ``-e <url-or-path>`` → editable :class:`Requirement`
        - ``pkg==1.0 --hash sha256:...`` → :class:`Requirement` with hashes
        - Standard PEP 508 specs → :class:`Requirement`

        Args:
            line_text: Raw line text (may include leading/trailing whitespace).
            line_number: Line number (1-indexed) for error reporting.
            source_file_path: Optional source file path for error messages.
            _current_directory_path: Internal; directory of the file being
                parsed (used to resolve relative ``-r`` / ``-c`` paths).

        Returns:
            - ``None`` for comments, blank lines, or ``-c`` directives.
            - ``List[Requirement]`` when the line is a ``-r`` include.
            - ``Requirement`` for all other valid package specs.

        Raises:
            ParseError: The line contains invalid syntax or a directive
                that cannot be processed.

        Example::

            >>> parser = RequirementsParser()
            >>> parser.parse_line("requests>=2.25.0", 1)
            <Requirement requests>=2.25.0>
            >>> parser.parse_line("# comment", 2) is None
            True
            >>> parser.parse_line("-r base.txt", 3)  # returns List[Requirement]
        """
        stripped_line = line_text.strip()

        # Blank lines and pure comments are skipped
        if not stripped_line or stripped_line.startswith("#"):
            return None

        # Extract inline comment (everything after a non-URL '#')
        requirement_spec, inline_comment = self._extract_inline_comment(stripped_line)

        # ── Handle -r / --requirement (include another file) ──────────
        if requirement_spec.startswith((INCLUDE_DIRECTIVE, INCLUDE_DIRECTIVE_LONG)):
            return self._handle_include_directive(
                requirement_spec,
                line_number,
                source_file_path,
                _current_directory_path,
            )

        # ── Handle -c / --constraint (load constraints) ───────────────
        if requirement_spec.startswith(
            (CONSTRAINT_DIRECTIVE, CONSTRAINT_DIRECTIVE_LONG)
        ):
            self._handle_constraint_directive(
                requirement_spec,
                line_number,
                source_file_path,
                _current_directory_path,
            )
            return None  # constraints are stored, not returned

        # Strip quotes that may wrap the entire spec
        requirement_spec = self._remove_surrounding_quotes(requirement_spec)

        # ── Check for -e / --editable flag ────────────────────────────
        is_editable = requirement_spec.startswith(
            (EDITABLE_DIRECTIVE, EDITABLE_DIRECTIVE_LONG)
        )
        if is_editable:
            # Extract everything after "-e " or "--editable "
            requirement_spec = (
                requirement_spec.split(None, 1)[1] if " " in requirement_spec else ""
            )

        # ── Extract --hash directives ──────────────────────────────────
        hash_values: List[str] = re.findall(r"--hash[=\s]+(\S+)", requirement_spec)
        if hash_values:
            # Remove all --hash tokens from the spec
            requirement_spec = " ".join(
                token
                for token in requirement_spec.split()
                if not token.startswith(HASH_DIRECTIVE)
            )

        # ── Dispatch to appropriate builder ────────────────────────────
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
            # Standard PEP 508 package specifier
            parsed_requirement = self._build_standard_pep508_requirement(
                requirement_spec=requirement_spec,
                is_editable=is_editable,
                hash_values=hash_values,
                inline_comment=inline_comment,
                original_line=line_text,
                line_number=line_number,
                source_file_path=source_file_path,
            )

        # Apply any constraint loaded via -c directive
        return self._apply_constraint_to_requirement(parsed_requirement)

    def get_constraints(self) -> Dict[str, Requirement]:
        """Return a copy of all constraint requirements loaded via ``-c``.

        Returns:
            Dictionary mapping normalised package names to their constraint
            :class:`Requirement` objects.

        Example::

            >>> parser = RequirementsParser()
            >>> parser.parse_file("requirements.txt")  # includes -c constraints.txt
            >>> constraints = parser.get_constraints()
            >>> constraints.get("django")
            <Requirement django==3.2>
        """
        return self._constraint_requirements.copy()

    def reset(self) -> None:
        """Clear all internal state (include stack and constraints).

        Call this before reusing the parser on a new, unrelated set of
        files to prevent cross-contamination.

        Example::

            >>> parser = RequirementsParser()
            >>> parser.parse_file("projectA/requirements.txt")
            >>> parser.reset()
            >>> parser.parse_file("projectB/requirements.txt")  # clean slate
        """
        self._included_files_stack = []
        self._constraint_requirements = {}

    # ------------------------------------------------------------------
    # Directive handlers (private)
    # ------------------------------------------------------------------

    def _handle_include_directive(
        self,
        directive_line: str,
        line_number: int,
        source_file_path: Optional[str],
        current_directory: Optional[Path],
    ) -> Optional[List[Requirement]]:
        """Process a ``-r`` or ``--requirement`` include directive.

        Recursively parses the referenced file and returns its requirements
        as a flat list.

        Args:
            directive_line: The full line text (e.g., ``"-r base.txt"``).
            line_number: Line number for error messages.
            source_file_path: Source file path for error context.
            current_directory: Directory of the current file (used to
                resolve relative paths).

        Returns:
            List of requirements from the included file, or ``None`` if the
            directive is malformed (a warning is logged).

        Raises:
            ParseError: The included file cannot be read or contains a
                circular reference.
        """
        line_parts = directive_line.split(maxsplit=1)
        if len(line_parts) < 2:
            self.logger.warning(
                "Line %d: Include directive missing file path", line_number
            )
            return None

        included_file_path = line_parts[1].strip()

        if not current_directory:
            self.logger.warning(
                "Line %d: Cannot resolve include path without base file", line_number
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
        """Process a ``-c`` or ``--constraint`` directive.

        Parses the referenced file with ``is_constraint_file=True`` so that
        all requirements are stored in :attr:`_constraint_requirements`
        rather than being returned.

        Args:
            directive_line: The full line text (e.g., ``"-c versions.txt"``).
            line_number: Line number for error messages.
            source_file_path: Source file path for error context.
            current_directory: Directory of the current file.

        Raises:
            ParseError: The constraint file cannot be read or is malformed.
        """
        line_parts = directive_line.split(maxsplit=1)
        if len(line_parts) < 2:
            self.logger.warning(
                "Line %d: Constraint directive missing file path", line_number
            )
            return

        constraint_file_path = line_parts[1].strip()

        if not current_directory:
            self.logger.warning(
                "Line %d: Cannot resolve constraint path without base file",
                line_number,
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

    # ------------------------------------------------------------------
    # Requirement builders (private)
    # ------------------------------------------------------------------

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
        """Build a :class:`Requirement` from a standard PEP 508 specifier.

        Delegates parsing to ``packaging.requirements.Requirement``, then
        extracts name, version specifiers, extras, and markers.

        Args:
            requirement_spec: PEP 508 string, e.g., ``"requests>=2.25.0"``.
            is_editable: Whether ``-e`` was present.
            hash_values: Hash strings extracted from ``--hash`` directives.
            inline_comment: Text after the ``#`` (if any).
            original_line: Raw line text for error reporting.
            line_number: Line number for error reporting.
            source_file_path: Source file for error context.

        Returns:
            A populated :class:`Requirement` object.

        Raises:
            ParseError: The spec is not valid PEP 508 syntax.

        Example (internal)::

            >>> req = self._build_standard_pep508_requirement(
            ...     "flask>=2.0,<3", False, [], None, "flask>=2.0,<3", 1, None
            ... )
            >>> req.name
            'flask'
            >>> req.specs
            [('>=', '2.0'), ('<', '3')]
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

        # The packaging library already validates version strings; no need
        # to loop through spec.version.  However, we check for empty
        # versions as an extra safety net (shouldn't happen in practice).
        for spec in parsed_pkg.specifier:
            if not spec.version:
                raise ParseError(
                    f"Invalid version specifier: empty version in '{spec.operator}{spec.version}'",
                    line_number=line_number,
                    line_content=requirement_spec,
                    file_path=source_file_path,
                )

        return Requirement(
            name=_normalize_package_name(parsed_pkg.name),
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
        """Build a :class:`Requirement` from a direct URL (VCS or network).

        The package name is extracted from the ``#egg=`` fragment.  If
        absent, the parser attempts to infer it from the URL path.

        Args:
            url_string: Full URL string.
            url_components: Dict with ``"scheme"``, ``"path"``, ``"egg"``
                keys (from :meth:`_parse_direct_url`).
            is_editable: Whether ``-e`` was present.
            hash_values: Hash strings from ``--hash`` directives.
            inline_comment: Inline comment text.
            original_line: Raw line for error reporting.
            line_number: Line number for error reporting.

        Returns:
            A :class:`Requirement` with the URL stored in the ``url`` field.

        Raises:
            ParseError: The URL lacks ``#egg=`` and the package name cannot
                be inferred.

        Example (internal)::

            >>> req = self._build_url_based_requirement(
            ...     "git+https://github.com/org/repo.git#egg=mypkg",
            ...     {"scheme": "git+https://", "path": "...", "egg": "mypkg"},
            ...     False, [], None, "...", 1
            ... )
            >>> req.name
            'mypkg'
            >>> req.url
            'git+https://github.com/org/repo.git#egg=mypkg'
        """
        package_name = url_components.get("egg")

        if not package_name:
            # Attempt to infer from URL path
            package_name = self._infer_package_name_from_url(url_string)

            if package_name:
                self.logger.warning(
                    "Line %d: URL without '#egg=' - inferred name '%s'",
                    line_number,
                    package_name,
                )
            else:
                raise ParseError(
                    "URL requirements must include '#egg=<name>' or an inferable package name.",
                    line_number=line_number,
                    line_content=url_string,
                )

        return Requirement(
            name=_normalize_package_name(package_name),
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
        """Build a :class:`Requirement` from a local file path.

        The path is resolved to an absolute ``file://`` URI.  The package
        name is extracted from ``#egg=`` if present, otherwise inferred
        from the filename.

        Args:
            path_components: Dict with ``"path"`` and ``"egg"`` keys (from
                :meth:`_parse_local_file_path`).
            current_directory: Directory of the current file (for resolving
                relative paths).
            is_editable: Whether ``-e`` was present.
            hash_values: Hash strings from ``--hash`` directives.
            inline_comment: Inline comment text.
            original_line: Raw line for error reporting.
            line_number: Line number for error reporting.

        Returns:
            A :class:`Requirement` with the ``url`` field set to a
            ``file://`` URI.

        Raises:
            ValueError: The ``path`` key is missing from *path_components*.

        Example (internal)::

            >>> req = self._build_local_path_requirement(
            ...     {"path": "./local-pkg", "egg": None},
            ...     Path("/project"),
            ...     True, [], None, "-e ./local-pkg", 1
            ... )
            >>> req.editable
            True
            >>> req.url.startswith("file://")
            True
        """
        path_value = path_components.get("path")
        if not path_value:
            raise ValueError("Path component is required")

        resolved_path = self._resolve_file_path(
            file_path=Path(path_value),
            parent_directory=current_directory,
        )

        # Extract package name from #egg= or infer from filename
        package_name = path_components.get("egg") or self._infer_package_name_from_path(
            resolved_path
        )

        return Requirement(
            name=_normalize_package_name(package_name),
            specs=[],
            extras=[],
            markers=None,
            url=resolved_path.as_uri(),  # Convert to file:// URI
            editable=is_editable,
            hashes=hash_values,
            comment=inline_comment,
            line_number=line_number,
            raw_line=original_line,
        )

    # ------------------------------------------------------------------
    # Parsing helpers (private)
    # ------------------------------------------------------------------

    def _resolve_file_path(
        self, file_path: Path, parent_directory: Optional[Path]
    ) -> Path:
        """Resolve a file path to absolute form.

        Relative paths are resolved relative to *parent_directory* if
        provided; otherwise they are resolved relative to the current
        working directory.

        Args:
            file_path: Path object (may be relative or absolute).
            parent_directory: Optional parent directory (typically the
                directory containing the file currently being parsed).

        Returns:
            Absolute :class:`Path`.

        Example (internal)::

            >>> self._resolve_file_path(Path("base.txt"), Path("/project/requirements.txt"))
            Path('/project/base.txt')
        """
        if parent_directory and not file_path.is_absolute():
            # Resolve relative to parent's directory (not parent itself)
            return (parent_directory.parent / file_path).resolve()
        return file_path.resolve()

    def _parse_direct_url(
        self, requirement_line: str
    ) -> Optional[Dict[str, Optional[str]]]:
        """Detect and parse a direct URL requirement.

        Checks whether *requirement_line* starts with any recognised VCS or
        network scheme.  If so, extracts the scheme, path, and optional
        ``#egg=`` fragment.

        Args:
            requirement_line: Requirement string (may or may not be a URL).

        Returns:
            A dict with ``"scheme"``, ``"path"``, and ``"egg"`` keys, or
            ``None`` if the line is not a URL.

        Example (internal)::

            >>> self._parse_direct_url("git+https://github.com/org/repo.git#egg=pkg")
            {'scheme': 'git+https://', 'path': 'github.com/org/repo.git', 'egg': 'pkg'}
            >>> self._parse_direct_url("requests>=2.25") is None
            True
        """
        for scheme in URL_SCHEMES:
            if requirement_line.startswith(scheme):
                egg_name: Optional[str] = None

                # Extract #egg= fragment if present
                if "#egg=" in requirement_line:
                    url_part, egg_part = requirement_line.split("#egg=", 1)
                    # Stop at the first & or whitespace after egg=
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
        """Detect and parse a local file path requirement.

        Recognises:

        - Current directory: ``.`` or ``.#egg=...``
        - Relative paths: ``./pkg`` or ``../other``
        - Absolute Unix paths: ``/path/to/pkg``
        - Absolute Windows paths: ``C:\\path\\to\\pkg``

        Args:
            requirement_line: Requirement string.

        Returns:
            A dict with ``"path"`` and ``"egg"`` keys, or ``None`` if the
            line is not a local path.

        Example (internal)::

            >>> self._parse_local_file_path("./local-pkg#egg=mypkg")
            {'path': './local-pkg', 'egg': 'mypkg'}
            >>> self._parse_local_file_path("requests>=2.25") is None
            True
        """
        is_local_path = False

        # Current directory patterns
        if requirement_line == "." or requirement_line.startswith(".#"):
            is_local_path = True

        # Relative path prefixes (Unix and Windows)
        elif requirement_line.startswith(("./", "../", ".\\", "..\\")):
            is_local_path = True

        # Absolute Unix path (starts with /)
        elif requirement_line.startswith("/"):
            is_local_path = True

        # Absolute Windows path (e.g., C:\...)
        # Check for drive letter pattern: single char, colon, backslash
        elif (
            len(requirement_line) >= 3
            and requirement_line[1] == ":"
            and requirement_line[2] == "\\"
        ):
            is_local_path = True

        if not is_local_path:
            return None

        # Extract #egg= fragment if present
        if "#egg=" in requirement_line:
            path_part, egg_part = requirement_line.split("#egg=", 1)
            egg_name = egg_part.split("&")[0].split()[0]
            return {"path": path_part, "egg": egg_name}

        return {"path": requirement_line, "egg": None}

    def _infer_package_name_from_path(self, file_path: Path) -> str:
        """Infer a package name from a file or directory path.

        Strips common archive extensions (``tar.gz``, ``zip``, ``whl``) and
        returns the resulting basename.

        Args:
            file_path: Path to a file or directory.

        Returns:
            Inferred package name (filename without extension).

        Example (internal)::

            >>> self._infer_package_name_from_path(Path("mypkg-1.0.tar.gz"))
            'mypkg-1.0'
            >>> self._infer_package_name_from_path(Path("/path/to/local-pkg"))
            'local-pkg'
        """
        filename = file_path.name

        for extension in (".tar.gz", ".tar.bz2", ".zip", ".whl"):
            if filename.endswith(extension):
                return filename[: -len(extension)]

        return filename

    def _infer_package_name_from_url(self, url: str) -> Optional[str]:
        """Infer a package name from a URL by extracting the last path segment.

        Strips trailing slashes and the ``.git`` suffix if present.

        Args:
            url: Full URL string.

        Returns:
            Inferred package name, or ``None`` if the URL has no meaningful
            path segments.

        Example (internal)::

            >>> self._infer_package_name_from_url("git+https://github.com/org/repo.git")
            'repo'
            >>> self._infer_package_name_from_url("https://example.com/files/")
            'files'
        """
        # Strip scheme
        url_path = url.split("://", 1)[1] if "://" in url else url
        url_path = url_path.rstrip("/")

        # Remove .git suffix (common for VCS URLs)
        if url_path.endswith(".git"):
            url_path = url_path[:-4]

        # Split by / and take the last non-empty segment
        path_segments = url_path.replace("\\", "/").split("/")
        for segment in reversed(path_segments):
            if segment and segment not in ("#", "?"):
                return segment

        return None

    def _remove_surrounding_quotes(self, text: str) -> str:
        """Strip matching single or double quotes from a string.

        Only removes quotes when the first and last characters match and
        are either ``'`` or ``"``.

        Args:
            text: String that may be quoted.

        Returns:
            Unquoted string, or the original if not quoted.

        Example (internal)::

            >>> self._remove_surrounding_quotes('"requests>=2.25"')
            'requests>=2.25'
            >>> self._remove_surrounding_quotes("requests")
            'requests'
        """
        if len(text) >= 2 and text[0] in ('"', "'") and text[0] == text[-1]:
            return text[1:-1]
        return text

    def _extract_inline_comment(self, line: str) -> Tuple[str, Optional[str]]:
        """Extract an inline comment from a requirement line.

        Scans the line for ``#`` characters.  A ``#`` is considered the
        start of a comment when:

        1. It is **not** part of a URL fragment (e.g., ``#egg=``,
           ``#subdirectory=``).
        2. It does **not** appear immediately after ``://`` within the same
           token (which would make it part of a URL).

        This heuristic handles most real-world cases, including URLs with
        fragments and inline comments after the requirement spec.

        Args:
            line: Full requirement line (may contain ``#`` in multiple
                contexts).

        Returns:
            A tuple ``(requirement_text, comment_text)``.  *comment_text*
            is ``None`` when no comment is found.

        Example (internal)::

            >>> self._extract_inline_comment("requests>=2.25  # a comment")
            ('requests>=2.25', 'a comment')
            >>> self._extract_inline_comment("git+https://github.com/org/repo.git#egg=pkg")
            ('git+https://github.com/org/repo.git#egg=pkg', None)
        """
        for char_index, char in enumerate(line):
            if char != "#":
                continue

            text_before_hash = line[:char_index]
            text_after_hash = line[char_index + 1 :]

            # Skip URL fragments (#egg=, #subdirectory=, #sha256=, etc.)
            if text_after_hash.startswith(
                ("egg=", "subdirectory=", "sha1=", "sha256=")
            ):
                continue

            # Check if this # is part of a URL (no space after ://)
            url_scheme_position = text_before_hash.rfind("://")
            if (
                url_scheme_position == -1  # no :// at all
                or " " in text_before_hash[url_scheme_position:]  # space after ://
            ):
                # This # is a comment delimiter
                return text_before_hash.strip(), text_after_hash.strip()

        # No comment found
        return line, None

    def _apply_constraint_to_requirement(self, requirement: Requirement) -> Requirement:
        """Apply stored constraints to a requirement if a match exists.

        When a requirement has no version specs (``specs == []``) and a
        constraint for the same package name exists in
        :attr:`_constraint_requirements`, the constraint's specs are copied
        to the requirement.

        **Side-effect:** Mutates *requirement.specs* in place when a
        constraint is applied.

        Args:
            requirement: Requirement to potentially constrain.

        Returns:
            The same :class:`Requirement` object (possibly modified).

        Example (internal)::

            >>> # After loading constraint: django==3.2
            >>> req = Requirement(name="django", specs=[], ...)
            >>> constrained = self._apply_constraint_to_requirement(req)
            >>> constrained.specs
            [('==', '3.2')]
        """
        if requirement.name in self._constraint_requirements:
            constraint = self._constraint_requirements[requirement.name]
            if constraint.specs and not requirement.specs:
                # Mutate in place (caller already holds a reference)
                requirement.specs = constraint.specs

        return requirement


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _normalize_package_name(package_name: str) -> str:
    """Normalise a package name per PEP 503.

    Replaces runs of ``-``, ``_``, and ``.`` with a single ``-``, then
    converts to lowercase.

    Args:
        package_name: Raw package name.

    Returns:
        Normalised package name.

    Example::

        >>> _normalize_package_name("My_Cool.Package")
        'my-cool-package'
        >>> _normalize_package_name("requests")
        'requests'
    """
    return re.sub(r"[-_.]+", "-", package_name).lower()
