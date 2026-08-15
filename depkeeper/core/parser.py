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

    from depkeeper.core.parser import RequirementsParser

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
from typing import Dict, Iterable, List, Optional, Tuple, Union

from packaging.requirements import Requirement as PkgRequirement, InvalidRequirement
from packaging.specifiers import Specifier

from depkeeper.models.requirement import Requirement
from depkeeper.utils import get_logger, safe_read_file
from depkeeper.utils.naming import normalize_package_name
from depkeeper.exceptions import ParseError, FileOperationError
from depkeeper.constants import (
    INCLUDE_DIRECTIVE,
    CONSTRAINT_DIRECTIVE,
    EDITABLE_DIRECTIVE,
    INCLUDE_DIRECTIVE_LONG,
    CONSTRAINT_DIRECTIVE_LONG,
    EDITABLE_DIRECTIVE_LONG,
    PIP_GLOBAL_OPTIONS_WITH_VALUES,
    PIP_GLOBAL_OPTIONS_NO_VALUES,
    BOM_CHARACTER,
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

# ---------------------------------------------------------------------------
# --hash directive matching
# ---------------------------------------------------------------------------
# pip accepts both ``--hash=sha256:...`` and ``--hash sha256:...`` (space
# form).  A single pattern is used for BOTH extracting the digest (capture
# group) and removing the entire directive from the spec, so the two steps
# can never disagree.  ``[=\s]+`` tolerates the ``=`` separator, one or more
# spaces, or line-continuation whitespace between the flag and the digest.
_HASH_DIRECTIVE_PATTERN = re.compile(r"--hash[=\s]+(\S+)")


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
    """

    def __init__(self) -> None:
        """Initialize the parser with empty state."""
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
        # A byte order mark is a stream-level signature, not part of line 1.
        # It survives non-BOM-aware decoding and is not removed by strip().
        if requirements_content.startswith(BOM_CHARACTER):
            requirements_content = requirements_content[len(BOM_CHARACTER):]

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
                # Record provenance so the update writer can rewrite the
                # correct file. Requirements flattened in from -r includes
                # (the list branch above) already carry the included file's
                # path set by the recursive parse_string call.
                parse_result.source_file = source_file_path

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
        - Pip global option lines (e.g. ``--index-url ...``) → ``None``
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
        """
        stripped_line = line_text.strip()

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

        # Recognized pip global options configure installer behavior and are
        # not package requirements, so they should be ignored by the parser.
        if self._is_supported_global_option_line(requirement_spec):
            self.logger.debug(
                "Line %d: Skipping supported pip global option: %s",
                line_number,
                requirement_spec,
            )
            return None

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
        hash_values: List[str] = _HASH_DIRECTIVE_PATTERN.findall(requirement_spec)
        if hash_values:
            # Remove the entire ``--hash <digest>`` / ``--hash=<digest>``
            # directive (flag AND digest) using the same pattern that
            # extracted it.  Token-based filtering only dropped the ``--hash``
            # flag and left the space-separated digest behind, which then
            # failed PEP 508 parsing.
            requirement_spec = _HASH_DIRECTIVE_PATTERN.sub(" ", requirement_spec)
            requirement_spec = " ".join(requirement_spec.split())

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
            Dictionary mapping normalized package names to their constraint
            :class:`Requirement` objects.
        """
        return self._constraint_requirements.copy()

    def reset(self) -> None:
        """Clear all internal state (include stack and constraints).

        Call this before reusing the parser on a new, unrelated set of
        files to prevent cross-contamination.
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

        # ``packaging`` already validates version strings; this guards only
        # against a specifier that parsed with an empty version.
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
            specs=_ordered_specs(parsed_pkg.specifier, requirement_spec),
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
        """
        package_name = url_components.get("egg")

        if not package_name:
            # Inference is a best-effort fallback; the warning tells the user
            # to add an explicit #egg= fragment if the guess is wrong.
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
        """
        path_value = path_components.get("path")
        if not path_value:
            raise ValueError("Path component is required")

        resolved_path = self._resolve_file_path(
            file_path=Path(path_value),
            parent_directory=current_directory,
        )

        package_name = path_components.get("egg") or self._infer_package_name_from_path(
            resolved_path
        )

        return Requirement(
            name=_normalize_package_name(package_name),
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
        """
        if parent_directory and not file_path.is_absolute():
            # parent_directory is the including *file*, so relative includes
            # resolve against its directory, matching pip's behavior.
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
        """
        for scheme in URL_SCHEMES:
            if requirement_line.startswith(scheme):
                egg_name: Optional[str] = None

                if "#egg=" in requirement_line:
                    url_part, egg_part = requirement_line.split("#egg=", 1)
                    # An egg fragment may be followed by other fragment keys
                    # (&subdirectory=...) or by trailing options.
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
        """
        is_local_path = False

        if requirement_line == "." or requirement_line.startswith(".#"):
            is_local_path = True

        elif requirement_line.startswith(("./", "../", ".\\", "..\\")):
            is_local_path = True

        elif requirement_line.startswith("/"):
            is_local_path = True

        # Windows drive letter (``C:\``). Checked positionally rather than
        # with a regex so a spec such as ``pkg==1.0`` can never match.
        elif (
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
        """Infer a package name from a file or directory path.

        Strips common archive extensions (``tar.gz``, ``zip``, ``whl``) and
        returns the resulting basename.

        Args:
            file_path: Path to a file or directory.

        Returns:
            Inferred package name (filename without extension).
        """
        filename = file_path.name

        for extension in (".tar.gz", ".tar.bz2", ".zip", ".whl"):
            if filename.endswith(extension):
                return filename[: -len(extension)]

        return filename

    def _infer_package_name_from_url(self, url: str) -> Optional[str]:
        """Infer a package name from a URL by taking the last path segment.

        Strips trailing slashes and a ``.git`` suffix. This is a heuristic:
        for an archive URL the last segment is a filename, not a project name
        (``.../rich-13.7.1-py3-none-any.whl`` yields a filename-shaped result),
        so callers should prefer an explicit ``#egg=`` fragment.

        Args:
            url: Full URL string.

        Returns:
            Inferred package name, or ``None`` if the URL has no meaningful
            path segments.
        """
        url_path = url.split("://", 1)[1] if "://" in url else url
        url_path = url_path.rstrip("/")

        if url_path.endswith(".git"):
            url_path = url_path[:-4]

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
        """
        if len(text) >= 2 and text[0] in ('"', "'") and text[0] == text[-1]:
            return text[1:-1]
        return text

    def _is_supported_global_option_line(self, requirement_line: str) -> bool:
        """Return whether a line is a supported pip global option.

        These lines are legal in requirements files but are not package
        specifiers and should not be parsed by ``packaging``.
        """
        stripped = requirement_line.strip()
        if not stripped.startswith("-"):
            return False

        first_token = stripped.split(None, 1)[0]
        option_name = first_token.split("=", 1)[0]

        return (
            option_name in PIP_GLOBAL_OPTIONS_WITH_VALUES
            or option_name in PIP_GLOBAL_OPTIONS_NO_VALUES
        )

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
        """
        for char_index, char in enumerate(line):
            if char != "#":
                continue

            text_before_hash = line[:char_index]
            text_after_hash = line[char_index + 1 :]

            # Known URL fragment keys are never comment delimiters.
            if text_after_hash.startswith(
                ("egg=", "subdirectory=", "sha1=", "sha256=")
            ):
                continue

            # Otherwise the '#' belongs to a URL only if a scheme precedes it
            # with no intervening whitespace.
            url_scheme_position = text_before_hash.rfind("://")
            if (
                url_scheme_position == -1
                or " " in text_before_hash[url_scheme_position:]
            ):
                return text_before_hash.strip(), text_after_hash.strip()

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
        """
        if requirement.name in self._constraint_requirements:
            constraint = self._constraint_requirements[requirement.name]
            if constraint.specs and not requirement.specs:
                requirement.specs = constraint.specs

        return requirement


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _normalize_package_name(package_name: str) -> str:
    """Normalize a package name per PEP 503.

    Thin alias for :func:`depkeeper.utils.naming.normalize_package_name`.

    Args:
        package_name: Raw package name.

    Returns:
        Normalized package name.
    """
    return normalize_package_name(package_name)


def _ordered_specs(
    specifier_set: Iterable[Specifier],
    requirement_spec: str,
) -> List[Tuple[str, str]]:
    """Return specifier pairs in the order they appear in the source text.

    ``packaging`` stores specifiers in an unordered ``frozenset``, so iteration
    order varies between processes (PEP 456 string hash randomization). The
    update command rewrites requirement lines from these pairs, so an unstable
    order would produce spurious, non-reproducible diffs. Specifiers that
    cannot be located verbatim (e.g. written with internal whitespace) sort
    last in a stable, deterministic order.

    Args:
        specifier_set: Parsed specifiers for one requirement.
        requirement_spec: The PEP 508 source text they were parsed from.

    Returns:
        ``(operator, version)`` pairs in source order.

    Example::

        >>> from packaging.requirements import Requirement as PkgRequirement
        >>> _ordered_specs(PkgRequirement("flask>=2.0,<3").specifier, "flask>=2.0,<3")
        [('>=', '2.0'), ('<', '3')]
    """
    specs = [(spec.operator, spec.version) for spec in specifier_set]

    def sort_key(spec: Tuple[str, str]) -> Tuple[int, str, str]:
        index = requirement_spec.find(f"{spec[0]}{spec[1]}")
        if index < 0:
            index = len(requirement_spec)
        return index, spec[0], spec[1]

    return sorted(specs, key=sort_key)
