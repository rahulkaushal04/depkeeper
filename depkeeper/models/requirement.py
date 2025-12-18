"""Requirement data model for depkeeper.

This module defines the Requirement dataclass that represents a single line
from a requirements.txt file, including all possible components like version
specifiers, extras, environment markers, hashes, and comments.

The Requirement model is designed to faithfully represent the full complexity
of pip requirement specifications while providing convenient serialization
back to requirements.txt format. It supports PEP 508 requirement specifiers
including editable installs, direct URLs, VCS sources, and hash-checking mode.

Examples
--------
Basic version-pinned requirement:

    >>> from depkeeper.models.requirement import Requirement
    >>> req = Requirement(
    ...     name="requests",
    ...     specs=[("==", "2.31.0")],
    ...     line_number=1
    ... )
    >>> str(req)
    'requests==2.31.0'

Requirement with version range:

    >>> req = Requirement(
    ...     name="click",
    ...     specs=[(">=", "8.0.0"), ("<", "9.0.0")],
    ... )
    >>> str(req)
    'click>=8.0.0,<9.0.0'

Requirement with extras:

    >>> req = Requirement(
    ...     name="requests",
    ...     specs=[(">=", "2.28.0")],
    ...     extras=["security", "socks"]
    ... )
    >>> str(req)
    'requests[security,socks]>=2.28.0'

Requirement with environment markers:

    >>> req = Requirement(
    ...     name="pathlib2",
    ...     specs=[("==", "2.3.7")],
    ...     markers="python_version < '3.4'"
    ... )
    >>> str(req)
    "pathlib2==2.3.7 ; python_version < '3.4'"

Editable VCS requirement:

    >>> req = Requirement(
    ...     name="mypackage",
    ...     url="git+https://github.com/user/repo.git@v1.0",
    ...     editable=True
    ... )
    >>> str(req)
    '-e git+https://github.com/user/repo.git@v1.0'

Requirement with hash verification:

    >>> req = Requirement(
    ...     name="certifi",
    ...     specs=[("==", "2023.7.22")],
    ...     hashes=["sha256:abc123...", "sha256:def456..."]
    ... )
    >>> req.to_string()
    'certifi==2023.7.22 --hash=sha256:abc123... --hash=sha256:def456...'

Requirement with inline comment:

    >>> req = Requirement(
    ...     name="flask",
    ...     specs=[(">=", "3.0.0")],
    ...     comment="Web framework"
    ... )
    >>> str(req)
    'flask>=3.0.0  # Web framework'

Notes
-----
The Requirement class supports all features of pip requirement specifiers:

**Version Specifiers (PEP 440)**:
- Exact: ==1.0.0
- Greater/less than: >=1.0.0, <2.0.0, !=1.5.0
- Compatible release: ~=1.4.2
- Arbitrary equality: ===1.0.0

**Extras**:
- Single: package[extra]
- Multiple: package[extra1,extra2]

**Environment Markers (PEP 508)**:
- Python version: python_version >= '3.8'
- Platform: sys_platform == 'win32'
- Combined: python_version >= '3.8' and sys_platform == 'linux'

**URL Requirements**:
- Direct: https://github.com/user/repo/archive/master.zip
- VCS: git+https://github.com/user/repo.git@branch
- Editable: -e git+https://github.com/user/repo.git

**Hash Checking Mode**:
- Single hash: --hash=sha256:abc123
- Multiple hashes: --hash=sha256:abc123 --hash=sha256:def456

The raw_line attribute preserves the original line for round-trip safety,
ensuring that reformatting doesn't lose important formatting or edge cases.

See Also
--------
packaging.requirements.Requirement : PEP 508 requirement parsing
packaging.specifiers.SpecifierSet : Version specifier handling
depkeeper.core.parser : Requirements file parser
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Requirement:
    """Single requirement line from a requirements.txt file.

    A dataclass that represents all components of a pip requirement
    specification, including package name, version constraints, extras,
    environment markers, URLs, hashes, and comments. Designed to support
    the full complexity of requirements.txt syntax while providing
    convenient serialization.

    The Requirement class handles both simple version-pinned requirements
    (e.g., "requests==2.31.0") and complex requirements with extras, markers,
    hashes, and editable VCS sources.

    Parameters
    ----------
    name : str
        Package name, typically normalized to lowercase. For URL requirements,
        this is the inferred package name.
    specs : list[tuple[str, str]], optional
        List of (operator, version) tuples representing version constraints.
        Common operators: "==", ">=", "<=", ">", "<", "!=", "~=", "===".
        Example: [(">=", "2.0.0"), ("<", "3.0.0")].
        Default is empty list.
    extras : list[str], optional
        Optional extras to install, e.g., ["security", "socks"] for
        requests[security,socks]. Default is empty list.
    markers : str, optional
        Environment marker string (PEP 508) for conditional installation,
        e.g., "python_version < '3.11'" or "sys_platform == 'win32'".
        Default is None.
    url : str, optional
        Direct URL or VCS source for the package. Examples:
        - "https://example.com/package-1.0.tar.gz"
        - "git+https://github.com/user/repo.git@v1.0"
        When set, version specs are typically not used.
        Default is None.
    editable : bool, optional
        Whether this is an editable install (uses "-e" flag). Typically
        combined with url for VCS sources. Default is False.
    hashes : list[str], optional
        List of "--hash=" values for verification in hash-checking mode.
        Format: "algorithm:digest", e.g., "sha256:abc123...".
        Default is empty list.
    comment : str, optional
        Inline comment for this requirement (text after "#"), without
        the "#" prefix. Default is None.
    line_number : int, optional
        Original line number in the requirements file, useful for error
        reporting and tracking. Default is 0.
    raw_line : str, optional
        Complete unmodified original line from the requirements file.
        Preserves exact formatting for round-trip safety. Default is None.

    Attributes
    ----------
    name : str
        Normalized package name.
    specs : list[tuple[str, str]]
        Version constraint tuples.
    extras : list[str]
        Extra requirements list.
    markers : str or None
        Environment marker string.
    url : str or None
        Direct URL or VCS source.
    editable : bool
        Editable install flag.
    hashes : list[str]
        Hash verification strings.
    comment : str or None
        Inline comment text.
    line_number : int
        Original file line number.
    raw_line : str or None
        Original unmodified line.

    Examples
    --------
    Simple pinned requirement:

    >>> from depkeeper.models.requirement import Requirement
    >>> req = Requirement(name="requests", specs=[("==", "2.31.0")])
    >>> str(req)
    'requests==2.31.0'

    Version range with multiple constraints:

    >>> req = Requirement(
    ...     name="click",
    ...     specs=[(">=", "8.0.0"), ("<", "9.0.0")]
    ... )
    >>> str(req)
    'click>=8.0.0,<9.0.0'

    Requirement with extras:

    >>> req = Requirement(
    ...     name="requests",
    ...     specs=[(">=", "2.28.0")],
    ...     extras=["security", "socks"],
    ...     comment="HTTP library with extra features"
    ... )
    >>> str(req)
    'requests[security,socks]>=2.28.0  # HTTP library with extra features'

    Conditional requirement with marker:

    >>> req = Requirement(
    ...     name="typing-extensions",
    ...     specs=[(">=", "4.0.0")],
    ...     markers="python_version < '3.10'"
    ... )
    >>> str(req)
    "typing-extensions>=4.0.0 ; python_version < '3.10'"

    Editable VCS requirement:

    >>> req = Requirement(
    ...     name="myproject",
    ...     url="git+https://github.com/user/myproject.git@develop",
    ...     editable=True
    ... )
    >>> str(req)
    '-e git+https://github.com/user/myproject.git@develop'

    Requirement with hash verification:

    >>> req = Requirement(
    ...     name="certifi",
    ...     specs=[("==", "2023.7.22")],
    ...     hashes=[
    ...         "sha256:539cc1d13202e33ca466e88b2807e29f4c13049d6d87031a3c110744495cb082",
    ...         "sha256:92d6037539857d8206b8f6ae472e8b77db8058fec5937a1ef3f54304089edbb9"
    ...     ]
    ... )

    Direct URL requirement:

    >>> req = Requirement(
    ...     name="package",
    ...     url="https://files.example.com/package-1.0.tar.gz"
    ... )

    Notes
    -----
    Version specifier operators follow PEP 440:
    - "==": Exact match (1.0.0 only)
    - "!=": Not equal (anything except 1.0.0)
    - ">=", "<=", ">", "<": Comparison operators
    - "~=": Compatible release (~=1.4.2 means >=1.4.2,<1.5.0)
    - "===": Arbitrary equality (exact string match)

    Multiple version specs are combined with AND logic:
    specs=[(">=", "1.0"), ("<", "2.0")] means 1.0 <= version < 2.0

    Environment markers (PEP 508) support various conditions:
    - python_version, python_full_version
    - platform_system, platform_machine
    - sys_platform, os_name
    - implementation_name, implementation_version
    Combine with "and", "or", "not" operators.

    Hash-checking mode (--hash) requires all dependencies to have hashes.
    Multiple hashes for the same package support different platforms/formats.

    The raw_line attribute preserves the original formatting, including:
    - Exact whitespace
    - Comment formatting
    - Quote styles
    This enables accurate round-trip parsing and writing.

    See Also
    --------
    to_string : Serialize requirement back to string format
    depkeeper.core.parser.RequirementsParser : Parse requirements files
    """

    name: str
    specs: List[Tuple[str, str]] = field(default_factory=list)
    extras: List[str] = field(default_factory=list)
    markers: Optional[str] = None
    url: Optional[str] = None
    editable: bool = False
    hashes: List[str] = field(default_factory=list)
    comment: Optional[str] = None
    line_number: int = 0
    raw_line: Optional[str] = None

    def to_string(
        self,
        include_hashes: bool = True,
        include_comment: bool = True,
    ) -> str:
        """Convert requirement to canonical string for requirements.txt.

        Serializes the requirement back to a properly formatted string
        suitable for writing to a requirements.txt file. Handles all
        components including editable flag, version specs, extras,
        markers, hashes, and comments.

        The output follows standard requirements.txt format and is
        compatible with pip install -r.

        Parameters
        ----------
        include_hashes : bool, optional
            Whether to include --hash= values in the output. Set to False
            to generate requirements without hash verification.
            Default is True.
        include_comment : bool, optional
            Whether to include inline comments in the output. Set to False
            to strip comments (e.g., for automated processing).
            Default is True.

        Returns
        -------
        str
            Formatted requirement string ready for requirements.txt.
            Format varies based on requirement type:
            - Simple: "package==1.0.0"
            - With extras: "package[extra1,extra2]==1.0.0"
            - With marker: "package==1.0.0 ; python_version >= '3.8'"
            - Editable: "-e git+https://..."
            - With hash: "package==1.0.0 --hash=sha256:..."
            - With comment: "package==1.0.0  # comment"

        Examples
        --------
        Basic version-pinned package:

        >>> req = Requirement(name="requests", specs=[("==", "2.31.0")])
        >>> req.to_string()
        'requests==2.31.0'

        Package with extras and version range:

        >>> req = Requirement(
        ...     name="requests",
        ...     specs=[(">=", "2.28.0"), ("<", "3.0.0")],
        ...     extras=["security", "socks"]
        ... )
        >>> req.to_string()
        'requests[security,socks]>=2.28.0,<3.0.0'

        With environment marker:

        >>> req = Requirement(
        ...     name="pathlib2",
        ...     specs=[("==", "2.3.7")],
        ...     markers="python_version < '3.4'"
        ... )
        >>> req.to_string()
        "pathlib2==2.3.7 ; python_version < '3.4'"

        Editable VCS requirement:

        >>> req = Requirement(
        ...     name="mypackage",
        ...     url="git+https://github.com/user/repo.git@v1.0",
        ...     editable=True
        ... )
        >>> req.to_string()
        '-e git+https://github.com/user/repo.git@v1.0'

        With hash verification:

        >>> req = Requirement(
        ...     name="certifi",
        ...     specs=[("==", "2023.7.22")],
        ...     hashes=["sha256:abc123", "sha256:def456"]
        ... )
        >>> req.to_string()
        'certifi==2023.7.22 --hash=sha256:abc123 --hash=sha256:def456'

        Without hashes:

        >>> req.to_string(include_hashes=False)
        'certifi==2023.7.22'

        With inline comment:

        >>> req = Requirement(
        ...     name="flask",
        ...     specs=[(">=", "3.0.0")],
        ...     comment="Web framework"
        ... )
        >>> req.to_string()
        'flask>=3.0.0  # Web framework'

        Without comment:

        >>> req.to_string(include_comment=False)
        'flask>=3.0.0'

        Notes
        -----
        The serialization follows these rules:

        1. Editable flag comes first: "-e"
        2. Package name or URL
        3. Extras in brackets: "[extra1,extra2]"
        4. Version specs concatenated: ">=1.0,<2.0"
        5. Environment marker after semicolon: "; marker"
        6. Hashes with --hash= prefix
        7. Comment with "# " prefix

        Multiple version specs are joined with commas without spaces.
        Comments are separated from the requirement with two spaces.

        For URL requirements, version specs are typically omitted as the
        version is implied by the URL (e.g., git tag or commit hash).

        See Also
        --------
        __str__ : Convenience wrapper calling to_string() with defaults
        """
        parts: List[str] = []

        # Editable flag
        if self.editable:
            parts.append("-e")

        # Package or URL
        if self.url:
            pkg = self.url
        else:
            pkg = self.name
            if self.extras:
                pkg += f"[{','.join(self.extras)}]"

            if self.specs:
                spec_str = ",".join(f"{op}{ver}" for op, ver in self.specs)
                pkg += spec_str

        parts.append(pkg)

        # Markers
        if self.markers:
            parts.append(f"; {self.markers}")

        req = " ".join(parts)

        # Hashes
        if include_hashes and self.hashes:
            for h in self.hashes:
                req += f" --hash={h}"

        # Comment
        if include_comment and self.comment:
            req += f"  # {self.comment}"

        return req

    def __str__(self) -> str:
        """Return human-readable string representation of the requirement.

        Convenience method that calls to_string() with default parameters
        to produce a properly formatted requirement string.

        Returns
        -------
        str
            Formatted requirement string with all components (hashes,
            comments, etc.) included.

        Examples
        --------
        >>> req = Requirement(
        ...     name="requests",
        ...     specs=[("==", "2.31.0")],
        ...     comment="HTTP library"
        ... )
        >>> str(req)
        'requests==2.31.0  # HTTP library'

        >>> req = Requirement(name="click", specs=[(">=", "8.0")])
        >>> str(req)
        'click>=8.0'

        Notes
        -----
        Equivalent to calling req.to_string(include_hashes=True,
        include_comment=True).

        See Also
        --------
        to_string : Full serialization with customizable options
        """
        return self.to_string()

    def __repr__(self) -> str:
        """Return developer-friendly string representation of the requirement.

        Provides a detailed representation suitable for debugging and logging,
        showing key attributes in a concise format.

        Returns
        -------
        str
            String in format:
            "Requirement(name='...', specs=[...], extras=[...], editable=..., line_number=...)"

        Examples
        --------
        >>> req = Requirement(
        ...     name="requests",
        ...     specs=[("==", "2.31.0")],
        ...     extras=["security"],
        ...     editable=False,
        ...     line_number=5
        ... )
        >>> repr(req)
        "Requirement(name='requests', specs=[('==', '2.31.0')], extras=['security'], editable=False, line_number=5)"

        >>> req = Requirement(name="flask", specs=[(">=", "3.0")])
        >>> repr(req)
        "Requirement(name='flask', specs=[('>=', '3.0')], extras=[], editable=False, line_number=0)"

        Notes
        -----
        This representation includes the most important attributes for
        debugging but omits some details like markers, hashes, and comments
        for brevity. Use str(req) or req.to_string() for the full
        requirement specification.
        """
        return (
            f"Requirement(name={self.name!r}, specs={self.specs!r}, "
            f"extras={self.extras!r}, editable={self.editable}, "
            f"line_number={self.line_number})"
        )
