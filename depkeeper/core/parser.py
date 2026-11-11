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

    parser = RequirementsParser()
    requirements = parser.parse_file("requirements.txt")

    for req in requirements:
        print(f"{req.name} {req.specs}")

    content = \"\"\"
    requests>=2.25.0
    -r base.txt
    git+https://github.com/org/repo.git#egg=mypkg
    \"\"\"
    reqs = parser.parse_string(content, source_file_path="inline")

    constraints = parser.get_constraints()
    if "django" in constraints:
        print(f"Django constrained to {constraints['django'].specs}")

    parser.reset()
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

from packaging.markers import InvalidMarker, Marker
from packaging.requirements import Requirement as PkgRequirement, InvalidRequirement
from packaging.specifiers import Specifier

from depkeeper.models.requirement import Requirement
from depkeeper.utils import get_logger, safe_read_file
from depkeeper.utils.naming import normalize_package_name
from depkeeper.utils.redact import redact
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

#: Recognized VCS and network URL schemes.
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
    "ftp://",
    "git+file://",
    "hg+file://",
    "bzr+file://",
    "svn+file://",
    "svn+svn://",
)

# Accepts ``--hash=sha256:...`` and ``--hash sha256:...``. The same pattern both
# extracts the digest and strips the directive, so the two steps cannot disagree.
_HASH_DIRECTIVE_PATTERN = re.compile(r"--hash[=\s]+(\S+)")

# ``-r file``, ``-rfile``, ``-r=file``, ``--requirement file`` and
# ``--requirement=file`` (likewise for -c / --constraint), as pip accepts.
_INCLUDE_PATTERN = re.compile(r"(?:--requirement(?:\s*=\s*|\s+|$)|-r\s*=?\s*)(.*)$")
_CONSTRAINT_PATTERN = re.compile(r"(?:--constraint(?:\s*=\s*|\s+|$)|-c\s*=?\s*)(.*)$")

_URL_PREFIX_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")

# pip starts a comment at ``#`` only at the start of a line or after whitespace
# (``COMMENT_RE``); a ``#`` inside a token is part of it (URL fragments, markers).
_COMMENT_PATTERN = re.compile(r"(?:^|\s+)#")

# ``-e path``, ``-epath``, ``-e=path``, ``--editable path``, ``--editable=path``.
_EDITABLE_PATTERN = re.compile(r"(?:--editable(?:\s*=\s*|\s+|$)|-e\s*=?\s*)(.*)$")

# Per-requirement pip options that carry no information depkeeper uses.
_REQUIREMENT_OPTION_PATTERN = re.compile(
    r"\s+--(?:global-option|install-option|config-settings)(?:\s*=\s*|\s+)"
    r"(?:\"[^\"]*\"|'[^']*'|\S+)"
)

# Standalone option lines pip accepts that the shared constants do not list.
_EXTRA_NO_VALUE_OPTIONS = ("--no-index", "--require-hashes", "--always-unzip", "-Z")

_LINE_BREAK_PATTERN = re.compile(r"\r\n|\r|\n")

# A ``#egg=`` value is a project name, never a path.
_EGG_NAME_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")


def _join_continuations(content: str) -> List[Tuple[int, str]]:
    """Return ``(first_line_number, text)`` with ``\\`` continuations joined."""
    joined: List[Tuple[int, str]] = []
    pending: List[str] = []
    start = 0
    # Only \n, \r\n and \r end a line (as in pip and the update writer);
    # str.splitlines() would also split on \f, \v, U+2028 and friends.
    for number, line in enumerate(_LINE_BREAK_PATTERN.split(content), start=1):
        if not pending:
            start = number
        trailing = len(line) - len(line.rstrip("\\"))
        # pip never continues a comment line (COMMENT_RE).
        if trailing % 2 == 1 and not line.lstrip().startswith("#"):
            pending.append(line[:-1].strip())
            continue
        pending.append(line.strip() if pending else line)
        joined.append((start, " ".join(pending)))
        pending = []
    if pending:
        joined.append((start, " ".join(pending)))
    return joined


class RequirementsParser:
    """Stateful parser for pip-style requirements files.

    Maintains two pieces of internal state across multiple ``parse_file``
    calls:

    1. **Include stack** — tracks the chain of ``-r`` directives to detect
       circular dependencies.
    2. **Constraint map** — stores all requirements loaded via ``-c``
       directives; these are applied to matching package names during
       parsing.

    Call `reset` to clear state before reusing the parser on an
    unrelated set of files.
    """

    def __init__(self) -> None:
        """Initialize the parser with empty state."""
        self.logger = get_logger("parser")
        # Files currently being parsed; guards against include cycles.
        self._included_files_stack: List[Path] = []
        self._constraint_requirements: Dict[str, Requirement] = {}

    def parse_file(
        self,
        file_path: Union[str, Path],
        is_constraint_file: bool = False,
        _parent_directory_path: Optional[Path] = None,
    ) -> List[Requirement]:
        """Parse a requirements file from disk.

        Reads the file at *file_path*, processes all directives (``-r``,
        ``-c``, ``-e``, ``--hash``), and returns a flat list of
        `Requirement` objects.  If *file_path* is relative and
        *_parent_directory_path* is provided (internal use by ``-r``), the
        path is resolved relative to the parent.

        Circular include chains (``A.txt`` includes ``B.txt`` which
        includes ``A.txt``) are detected and raise `ParseError`.

        Args:
            file_path: Path to the requirements file (absolute or relative).
            is_constraint_file: If ``True``, all parsed requirements are
                stored as constraints (via `_constraint_requirements`)
                rather than returned.  Used internally by ``-c`` handlers.
            _parent_directory_path: Internal parameter used when resolving
                ``-r`` includes; the parent's directory is used as the base
                for relative paths.

        Returns:
            List of `Requirement` objects (empty if
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
        `parse_line`.  Requirements loaded from ``-r`` includes are
        flattened into the result list.

        Args:
            requirements_content: Multi-line requirements text.
            source_file_path: Optional file path for error messages (purely
                informational; does not affect parsing).
            is_constraint_file: If ``True``, all parsed requirements are
                stored in `_constraint_requirements` instead of being
                returned.
            _current_directory_path: Internal parameter; the directory
                containing the "file" being parsed (used to resolve
                relative ``-r`` / ``-c`` paths).

        Returns:
            List of `Requirement` objects.

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
        # A BOM survives non-BOM-aware decoding and is not removed by strip().
        if requirements_content.startswith(BOM_CHARACTER):
            requirements_content = requirements_content[len(BOM_CHARACTER) :]

        parsed_requirements: List[Requirement] = []
        logical_lines = _join_continuations(requirements_content)
        total_lines = len(logical_lines)
        self.logger.debug(
            "Parsing %d line(s)%s",
            total_lines,
            f" from {source_file_path}" if source_file_path else "",
        )

        for line_number, line_text in logical_lines:
            parse_result = self.parse_line(
                line_text,
                line_number,
                source_file_path,
                _current_directory_path=_current_directory_path,
            )

            if parse_result is None:
                continue

            if isinstance(parse_result, list):
                self.logger.debug(
                    "Included %d requirement(s) from directive on line %d",
                    len(parse_result),
                    line_number,
                )
                parsed_requirements.extend(parse_result)
            elif isinstance(parse_result, Requirement):
                # Included requirements (list branch) already carry their own
                # source_file from the recursive call.
                parse_result.source_file = source_file_path

                if is_constraint_file:
                    existing = self._constraint_requirements.get(parse_result.name)
                    if existing is None:
                        self._constraint_requirements[parse_result.name] = parse_result
                    else:
                        # pip intersects repeated constraints for one name.
                        existing.specs.extend(
                            s for s in parse_result.specs if s not in existing.specs
                        )
                    self.logger.debug(
                        "Stored constraint: %s %s",
                        parse_result.name,
                        parse_result.specs,
                    )
                else:
                    parsed_requirements.append(parse_result)

        # Constraints apply globally, wherever the ``-c`` line appears.
        for requirement in parsed_requirements:
            self._apply_constraint_to_requirement(requirement)

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
        - ``-e <url-or-path>`` → editable `Requirement`
        - ``pkg==1.0 --hash sha256:...`` → `Requirement` with hashes
        - Standard PEP 508 specs → `Requirement`

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

        requirement_spec, inline_comment = self._extract_inline_comment(stripped_line)

        if requirement_spec.startswith((INCLUDE_DIRECTIVE, INCLUDE_DIRECTIVE_LONG)):
            return self._handle_include_directive(
                requirement_spec,
                line_number,
                source_file_path,
                _current_directory_path,
            )

        if requirement_spec.startswith(
            (CONSTRAINT_DIRECTIVE, CONSTRAINT_DIRECTIVE_LONG)
        ):
            self._handle_constraint_directive(
                requirement_spec,
                line_number,
                source_file_path,
                _current_directory_path,
            )
            return None

        # Recognized pip global options are installer settings, not requirements.
        if self._is_supported_global_option_line(requirement_spec):
            self.logger.debug(
                "Line %d: Skipping supported pip global option: %s",
                line_number,
                redact(requirement_spec),
            )
            return None

        requirement_spec = self._remove_surrounding_quotes(requirement_spec)

        is_editable = requirement_spec.startswith(
            (EDITABLE_DIRECTIVE, EDITABLE_DIRECTIVE_LONG)
        )
        if is_editable:
            match = _EDITABLE_PATTERN.match(requirement_spec)
            requirement_spec = self._remove_surrounding_quotes(
                match.group(1).strip() if match else ""
            )
            if not requirement_spec:
                raise ParseError(
                    "Editable directive requires a path or URL.",
                    line_number=line_number,
                    line_content=redact(line_text),
                    file_path=source_file_path,
                )

        requirement_spec = _REQUIREMENT_OPTION_PATTERN.sub("", requirement_spec)

        hash_values: List[str] = _HASH_DIRECTIVE_PATTERN.findall(requirement_spec)
        if hash_values:
            requirement_spec = _HASH_DIRECTIVE_PATTERN.sub(" ", requirement_spec)
            requirement_spec = " ".join(requirement_spec.split())

        url_marker: Optional[str] = None
        if self._is_url_or_path_line(requirement_spec):
            requirement_spec, url_marker = self._split_url_marker(
                requirement_spec, line_number, source_file_path
            )

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

        if url_marker:
            parsed_requirement.markers = url_marker

        return self._apply_constraint_to_requirement(parsed_requirement)

    def _is_url_or_path_line(self, requirement_spec: str) -> bool:
        """Whether *requirement_spec* is a bare URL or local path (not ``name @ url``)."""
        return bool(
            self._parse_direct_url(requirement_spec)
            or self._parse_local_file_path(requirement_spec)
        )

    @staticmethod
    def _split_url_marker(
        requirement_spec: str, line_number: int, source_file_path: Optional[str]
    ) -> Tuple[str, Optional[str]]:
        """Split ``<url-or-path> ; <marker>`` as pip does (``;`` after whitespace)."""
        match = re.search(r"\s;", requirement_spec)
        if not match:
            return requirement_spec, None
        marker_text = requirement_spec[match.end() :].strip()
        try:
            marker = str(Marker(marker_text))
        except InvalidMarker as exc:
            raise ParseError(
                f"Invalid environment marker: {redact(str(exc))}",
                line_number=line_number,
                line_content=redact(requirement_spec),
                file_path=source_file_path,
            ) from exc
        return requirement_spec[: match.start()].strip(), marker

    def get_constraints(self) -> Dict[str, Requirement]:
        """Return a copy of all constraint requirements loaded via ``-c``.

        Returns:
            Dictionary mapping normalized package names to their constraint
            `Requirement` objects.
        """
        return self._constraint_requirements.copy()

    def reset(self) -> None:
        """Clear all internal state (include stack and constraints).

        Call this before reusing the parser on a new, unrelated set of
        files to prevent cross-contamination.
        """
        self._included_files_stack = []
        self._constraint_requirements = {}

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
        match = _INCLUDE_PATTERN.match(directive_line)
        included_file_path = self._remove_surrounding_quotes(
            match.group(1).strip() if match else ""
        )
        if not included_file_path:
            self.logger.warning(
                "Line %d: Include directive missing file path", line_number
            )
            return None

        self._reject_remote_path(included_file_path, line_number, source_file_path)

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
                f"Failed to process include directive: {redact(str(exc))}",
                line_number=line_number,
                line_content=redact(directive_line),
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
        all requirements are stored in `_constraint_requirements`
        rather than being returned.

        Args:
            directive_line: The full line text (e.g., ``"-c versions.txt"``).
            line_number: Line number for error messages.
            source_file_path: Source file path for error context.
            current_directory: Directory of the current file.

        Raises:
            ParseError: The constraint file cannot be read or is malformed.
        """
        match = _CONSTRAINT_PATTERN.match(directive_line)
        constraint_file_path = self._remove_surrounding_quotes(
            match.group(1).strip() if match else ""
        )
        if not constraint_file_path:
            self.logger.warning(
                "Line %d: Constraint directive missing file path", line_number
            )
            return

        self._reject_remote_path(constraint_file_path, line_number, source_file_path)

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
                f"Failed to process constraint directive: {redact(str(exc))}",
                line_number=line_number,
                line_content=redact(directive_line),
                file_path=source_file_path,
            ) from exc

    @staticmethod
    def _reject_remote_path(
        path: str, line_number: int, source_file_path: Optional[str]
    ) -> None:
        """Fail on ``-r``/``-c`` URLs: depkeeper reads local files only."""
        if _URL_PREFIX_PATTERN.match(path):
            raise ParseError(
                "Remote requirements/constraints files are not supported.",
                line_number=line_number,
                line_content=redact(path),
                file_path=source_file_path,
            )

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
        """Build a `Requirement` from a standard PEP 508 specifier.

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
            A populated `Requirement` object.

        Raises:
            ParseError: The spec is not valid PEP 508 syntax.
        """
        try:
            parsed_pkg = PkgRequirement(requirement_spec)
        except InvalidRequirement as exc:
            raise ParseError(
                f"Invalid requirement syntax: {redact(str(exc))}",
                line_number=line_number,
                line_content=redact(requirement_spec),
                file_path=source_file_path,
            ) from exc

        # Guards only against a specifier that parsed with an empty version.
        for spec in parsed_pkg.specifier:
            if not spec.version:
                raise ParseError(
                    f"Invalid version specifier: empty version in '{spec.operator}{spec.version}'",
                    line_number=line_number,
                    line_content=redact(requirement_spec),
                    file_path=source_file_path,
                )

        return Requirement(
            name=_normalize_package_name(parsed_pkg.name),
            specs=_ordered_specs(parsed_pkg.specifier, requirement_spec),
            extras=sorted(parsed_pkg.extras),
            markers=str(parsed_pkg.marker) if parsed_pkg.marker else None,
            url=getattr(parsed_pkg, "url", None),
            direct_reference=bool(getattr(parsed_pkg, "url", None)),
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
        """Build a `Requirement` from a direct URL (VCS or network).

        The package name is extracted from the ``#egg=`` fragment.  If
        absent, the parser attempts to infer it from the URL path.

        Args:
            url_string: Full URL string.
            url_components: Dict with ``"scheme"``, ``"path"``, ``"egg"``
                keys (from `_parse_direct_url`).
            is_editable: Whether ``-e`` was present.
            hash_values: Hash strings from ``--hash`` directives.
            inline_comment: Inline comment text.
            original_line: Raw line for error reporting.
            line_number: Line number for error reporting.

        Returns:
            A `Requirement` with the URL stored in the ``url`` field.

        Raises:
            ParseError: The URL lacks ``#egg=`` and the package name cannot
                be inferred.
        """
        package_name = url_components.get("egg")

        if not package_name:
            # Best-effort fallback; the warning tells users to add #egg= if wrong.
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
                    line_content=redact(url_string),
                )

        self._validate_egg_name(package_name, line_number, url_string)

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

    @staticmethod
    def _validate_egg_name(name: str, line_number: int, line_content: str) -> None:
        """Reject ``#egg=`` values that are not plain project names."""
        if not _EGG_NAME_PATTERN.fullmatch(name):
            raise ParseError(
                f"Invalid '#egg=' name {name!r}: must be a project name, not a path.",
                line_number=line_number,
                line_content=redact(line_content),
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
        """Build a `Requirement` from a local file path.

        The path is resolved to an absolute ``file://`` URI.  The package
        name is extracted from ``#egg=`` if present, otherwise inferred
        from the filename.

        Args:
            path_components: Dict with ``"path"`` and ``"egg"`` keys (from
                `_parse_local_file_path`).
            current_directory: Directory of the current file (for resolving
                relative paths).
            is_editable: Whether ``-e`` was present.
            hash_values: Hash strings from ``--hash`` directives.
            inline_comment: Inline comment text.
            original_line: Raw line for error reporting.
            line_number: Line number for error reporting.

        Returns:
            A `Requirement` with the ``url`` field set to a
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
        if path_components.get("egg"):
            self._validate_egg_name(package_name, line_number, path_value)

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
            Absolute `Path`.
        """
        if parent_directory and not file_path.is_absolute():
            # parent_directory is the including file; pip resolves against its folder.
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
        lowered = requirement_line.lower()
        for scheme in URL_SCHEMES:
            if lowered.startswith(scheme):
                egg_name: Optional[str] = None

                if "#egg=" in requirement_line:
                    url_part, egg_part = requirement_line.split("#egg=", 1)
                    # May be followed by other fragment keys (&subdirectory=...);
                    # an empty fragment means no name, so inference applies.
                    egg_tokens = egg_part.split("&")[0].split()
                    egg_name = egg_tokens[0] if egg_tokens else None
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

        # Windows drive letter (``C:\``); positional check so ``pkg==1.0`` never matches.
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
            # An empty fragment yields no name, so path-based inference applies.
            egg_tokens = egg_part.split("&")[0].split()
            egg_name = egg_tokens[0] if egg_tokens else None
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
        # Fragment and query are never part of the package name.
        url_path = url.split("#", 1)[0].split("?", 1)[0]
        url_path = url_path.split("://", 1)[1] if "://" in url_path else url_path
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
            or option_name in _EXTRA_NO_VALUE_OPTIONS
        )

    def _extract_inline_comment(self, line: str) -> Tuple[str, Optional[str]]:
        """Extract an inline comment from a requirement line.

        As in pip, a ``#`` starts a comment only at the start of the line or
        after whitespace, so URL fragments (``#egg=``) and ``#`` inside a
        token or a quoted marker value are never mistaken for one.

        Args:
            line: Full requirement line (may contain ``#`` in multiple
                contexts).

        Returns:
            A tuple ``(requirement_text, comment_text)``.  *comment_text*
            is ``None`` when no comment is found.
        """
        match = _COMMENT_PATTERN.search(line)
        if match is None:
            return line, None
        return line[: match.start()].strip(), line[match.end() :].strip()

    def _apply_constraint_to_requirement(self, requirement: Requirement) -> Requirement:
        """Apply stored constraints to a requirement if a match exists.

        The constraint's specs are recorded in ``requirement.constraint_specs``
        (never ``specs``, which is rendered back into the file).

        **Side-effect:** Mutates *requirement.constraint_specs* in place.

        Args:
            requirement: Requirement to potentially constrain.

        Returns:
            The same `Requirement` object (possibly modified).
        """
        if requirement.name in self._constraint_requirements:
            constraint = self._constraint_requirements[requirement.name]
            requirement.constraint_specs = list(constraint.specs)

        return requirement


def _normalize_package_name(package_name: str) -> str:
    """Normalize a package name per PEP 503.

    Thin alias for `depkeeper.utils.naming.normalize_package_name`.

    Args:
        package_name: Raw package name.

    Returns:
        Normalized package name.
    """
    return normalize_package_name(package_name)


_SPEC_TOKEN_PATTERN = re.compile(r"(===|==|!=|<=|>=|~=|<|>)\s*([^\s,;()]+)")


def _ordered_specs(
    specifier_set: Iterable[Specifier],
    requirement_spec: str,
) -> List[Tuple[str, str]]:
    """Return specifier pairs in the order they appear in the source text.

    ``packaging`` stores specifiers in an unordered ``frozenset``, so iteration
    order varies between processes (PEP 456 string hash randomization). The
    update command rewrites requirement lines from these pairs, so an unstable
    order would produce spurious, non-reproducible diffs. Specifiers that
    cannot be located sort last in a stable, deterministic order.

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

    # Source order from the specifier text itself; marker operators come after ';'.
    tokens = [
        (match.group(1), match.group(2))
        for match in _SPEC_TOKEN_PATTERN.finditer(requirement_spec.split(";", 1)[0])
    ]
    remaining = list(specs)
    ordered: List[Tuple[str, str]] = []
    for token in tokens:
        if token in remaining:
            remaining.remove(token)
            ordered.append(token)
    return ordered + sorted(remaining)
