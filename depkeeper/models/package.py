"""Package data model for depkeeper.

This module defines the Package dataclass that represents Python package
information including version data, metadata, and compatibility checks.
The Package model is used throughout depkeeper to track package state,
detect available updates, and verify Python version compatibility.

The Package class provides version parsing and comparison utilities, Python
compatibility checking based on requires_python metadata, and convenient
properties for accessing parsed version objects.

Examples
--------
Create a package with version information:

    >>> from depkeeper.models.package import Package
    >>> pkg = Package(
    ...     name="requests",
    ...     current_version="2.28.0",
    ...     latest_version="2.31.0"
    ... )
    >>> print(pkg)
    requests 2.28.0 → 2.31.0 (outdated)

Check if package has updates available:

    >>> pkg.has_update()
    True
    >>> pkg.current  # Parsed Version object
    <Version('2.28.0')>
    >>> pkg.latest  # Parsed Version object
    <Version('2.31.0')>

Check Python version compatibility:

    >>> pkg.metadata = {"requires_python": ">=3.8"}
    >>> pkg.is_python_compatible("3.9.0")
    True
    >>> pkg.is_python_compatible("3.7.0")
    False

Handle packages with no updates:

    >>> current_pkg = Package(
    ...     name="click",
    ...     current_version="8.1.7",
    ...     latest_version="8.1.7"
    ... )
    >>> current_pkg.has_update()
    False
    >>> print(current_pkg)
    click 8.1.7 → 8.1.7 (up-to-date)

Notes
-----
Package names are automatically normalized following PEP 503:
- Converted to lowercase
- Underscores replaced with hyphens
- This ensures consistent package name handling across PyPI

Version parsing uses the packaging library's Version class, which
follows PEP 440 versioning standards. Invalid version strings are
handled gracefully by returning None.

See Also
--------
packaging.version.Version : Version parsing and comparison
packaging.specifiers.SpecifierSet : Python version requirement parsing
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from packaging.specifiers import SpecifierSet
from packaging.version import Version, InvalidVersion, parse


def _parse(version: Optional[str]) -> Optional[Version]:
    """Safely parse version strings into Version objects.

    Internal helper function that wraps packaging.version.parse with
    exception handling to gracefully handle invalid version strings.

    Parameters
    ----------
    version : str or None
        Version string to parse (e.g., "2.31.0", "1.0.0a1").
        If None, returns None.

    Returns
    -------
    Version or None
        Parsed Version object if successful, None if version is None
        or parsing fails due to InvalidVersion exception.

    Examples
    --------
    >>> from depkeeper.models.package import _parse
    >>> _parse("2.31.0")
    <Version('2.31.0')>
    >>> _parse(None)
    None
    >>> _parse("invalid")
    None

    Notes
    -----
    This is an internal helper function not exposed in the public API.
    Uses packaging.version.parse which follows PEP 440 versioning.
    """
    if version is None:
        return None
    try:
        return parse(version)
    except InvalidVersion:
        return None


@dataclass
class Package:
    """Python package representation with version tracking and compatibility checks.

    A dataclass that encapsulates all information about a Python package
    including its current version, latest available version, metadata from
    PyPI, and compatibility information. Provides utility methods for version
    comparison and Python version compatibility checking.

    The Package class automatically normalizes package names following PEP 503
    conventions and provides convenient properties for accessing parsed Version
    objects instead of raw version strings.

    Parameters
    ----------
    name : str
        Package name (will be normalized to lowercase with hyphens).
    current_version : str, optional
        Currently installed or specified version string. Default is None.
    latest_version : str, optional
        Latest available version from PyPI. Default is None.
    compatible_version : str, optional
        Latest version compatible with current Python interpreter.
        Default is None.
    metadata : dict[str, Any], optional
        Additional package metadata from PyPI such as summary, author,
        requires_python, license, etc. Default is empty dict.

    Attributes
    ----------
    name : str
        Normalized package name (lowercase, hyphens instead of underscores).
    current_version : str or None
        String representation of current version.
    latest_version : str or None
        String representation of latest version.
    compatible_version : str or None
        String representation of maximum compatible version.
    metadata : dict[str, Any]
        Package metadata dictionary from PyPI.

    Examples
    --------
    Create a basic package:

    >>> from depkeeper.models.package import Package
    >>> pkg = Package(name="requests", current_version="2.28.0")
    >>> pkg.name
    'requests'

    Package name normalization (PEP 503):

    >>> pkg = Package(name="Flask_RESTful")
    >>> pkg.name
    'flask-restful'

    Create with full version information:

    >>> pkg = Package(
    ...     name="click",
    ...     current_version="8.0.0",
    ...     latest_version="8.1.7",
    ...     metadata={"summary": "Command line interface toolkit"}
    ... )
    >>> pkg.has_update()
    True

    Access parsed version objects:

    >>> pkg.current  # Returns packaging.version.Version
    <Version('8.0.0')>
    >>> pkg.latest
    <Version('8.1.7')>
    >>> pkg.current < pkg.latest
    True

    Check Python compatibility:

    >>> pkg.metadata = {"requires_python": ">=3.8"}
    >>> pkg.is_python_compatible("3.9.0")
    True
    >>> pkg.is_python_compatible("3.7.0")
    False

    Handle invalid versions gracefully:

    >>> pkg = Package(name="test", current_version="invalid")
    >>> pkg.current  # Returns None for invalid versions
    None

    Notes
    -----
    Package name normalization follows PEP 503:
    - All names converted to lowercase
    - Underscores (_) replaced with hyphens (-)
    - Ensures consistency with PyPI canonical names

    Version parsing uses packaging.version.Version which follows PEP 440.
    Invalid version strings result in None being returned by the version
    properties (current, latest) to prevent crashes.

    The metadata dictionary can contain any information from PyPI's JSON API,
    commonly including:
    - summary: Package description
    - author: Package author
    - requires_python: Python version requirement (e.g., ">=3.8")
    - license: Package license
    - home_page: Project homepage URL

    See Also
    --------
    has_update : Check if newer version is available
    is_python_compatible : Check Python version compatibility
    get_requires_python : Extract Python version requirement
    """

    name: str
    current_version: Optional[str] = None
    latest_version: Optional[str] = None
    compatible_version: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize package name following PEP 503 conventions.

        Automatically called after dataclass initialization to ensure
        package names are in canonical form (lowercase with hyphens).
        This prevents issues with package name variations.

        Returns
        -------
        None

        Notes
        -----
        Normalization follows PEP 503:
        - Converts name to lowercase
        - Replaces underscores with hyphens

        This ensures that "Flask-RESTful", "flask_restful", and
        "FLASK_RESTFUL" all become "flask-restful".
        """
        self.name = self.name.lower().replace("_", "-")

    @property
    def current(self) -> Optional[Version]:
        """Get parsed Version object for current version.

        Returns
        -------
        Version or None
            Parsed Version object if current_version is set and valid,
            None if current_version is None or invalid.

        Examples
        --------
        >>> pkg = Package(name="requests", current_version="2.28.0")
        >>> pkg.current
        <Version('2.28.0')>
        >>> pkg.current > Version("2.0.0")
        True

        Notes
        -----
        Uses packaging.version.Version for PEP 440 compliant parsing.
        Invalid version strings return None instead of raising exceptions.
        """
        return _parse(self.current_version)

    @property
    def latest(self) -> Optional[Version]:
        """Get parsed Version object for latest version.

        Returns
        -------
        Version or None
            Parsed Version object if latest_version is set and valid,
            None if latest_version is None or invalid.

        Examples
        --------
        >>> pkg = Package(name="click", latest_version="8.1.7")
        >>> pkg.latest
        <Version('8.1.7')>

        Notes
        -----
        Uses packaging.version.Version for PEP 440 compliant parsing.
        Invalid version strings return None instead of raising exceptions.
        """
        return _parse(self.latest_version)

    def has_update(self) -> bool:
        """Check if a newer version is available than the current version.

        Compares the current version with the latest version to determine
        if an update is available. Returns False if either version is
        missing or invalid.

        Returns
        -------
        bool
            True if latest version is greater than current version,
            False otherwise (including when versions are missing or invalid).

        Examples
        --------
        Package with available update:

        >>> pkg = Package(
        ...     name="requests",
        ...     current_version="2.28.0",
        ...     latest_version="2.31.0"
        ... )
        >>> pkg.has_update()
        True

        Package already at latest version:

        >>> pkg = Package(
        ...     name="click",
        ...     current_version="8.1.7",
        ...     latest_version="8.1.7"
        ... )
        >>> pkg.has_update()
        False

        Missing version information:

        >>> pkg = Package(name="test", current_version="1.0.0")
        >>> pkg.has_update()  # No latest_version set
        False

        Notes
        -----
        Uses parsed Version objects for comparison, ensuring PEP 440
        compliant version ordering (e.g., 2.0.0 > 2.0.0a1).

        If version parsing fails for either version, returns False to
        prevent false positives.
        """
        if self.current is None or self.latest is None:
            return False
        return self.latest > self.current

    def get_requires_python(self) -> Optional[str]:
        """Get the Python version requirement from package metadata.

        Extracts the requires_python field from the metadata dictionary,
        which specifies the Python version(s) the package supports.

        Returns
        -------
        str or None
            Python version specifier string (e.g., '>=3.8', '>=3.7,<4.0')
            from metadata, or None if not specified.

        Examples
        --------
        >>> pkg = Package(
        ...     name="requests",
        ...     metadata={"requires_python": ">=3.8"}
        ... )
        >>> pkg.get_requires_python()
        '>=3.8'

        >>> pkg = Package(name="test")
        >>> pkg.get_requires_python()  # No requirement
        None

        Notes
        -----
        The requires_python field follows PEP 440 version specifier format.
        Common patterns:
        - ">=3.8": Python 3.8 or higher
        - ">=3.7,<4.0": Python 3.7+ but not 4.0+
        - "~=3.8": Compatible release (3.8.x)

        See Also
        --------
        is_python_compatible : Check compatibility with specific Python version
        """
        return self.metadata.get("requires_python")

    def is_python_compatible(self, python_version: Optional[str] = None) -> bool:
        """Check if package is compatible with a specific Python version.

        Validates the package's requires_python metadata against a target
        Python version. If no requirement is specified, assumes compatibility.
        Uses current Python version if no version is provided.

        Parameters
        ----------
        python_version : str, optional
            Python version string to check compatibility against (e.g., '3.9.0',
            '3.11.5'). If None, uses the current running Python interpreter's
            version. Default is None.

        Returns
        -------
        bool
            True if the package is compatible with the specified Python version,
            False if incompatible. Returns True if no requires_python constraint
            is specified or if parsing fails (assumes compatible).

        Examples
        --------
        Check against specific Python version:

        >>> pkg = Package(
        ...     name="requests",
        ...     metadata={"requires_python": ">=3.8"}
        ... )
        >>> pkg.is_python_compatible("3.9.0")
        True
        >>> pkg.is_python_compatible("3.7.0")
        False

        Check against current Python:

        >>> pkg.is_python_compatible()  # Uses sys.version_info
        True

        Complex version requirements:

        >>> pkg = Package(
        ...     name="test",
        ...     metadata={"requires_python": ">=3.8,<4.0"}
        ... )
        >>> pkg.is_python_compatible("3.11.0")
        True
        >>> pkg.is_python_compatible("4.0.0")
        False

        No requirement specified:

        >>> pkg = Package(name="test")
        >>> pkg.is_python_compatible("3.7.0")
        True

        Notes
        -----
        Uses packaging.specifiers.SpecifierSet to evaluate version constraints
        following PEP 440 rules.

        Current Python version is determined from sys.version_info in format:
        "major.minor.micro" (e.g., "3.11.5").

        If requires_python parsing fails, returns True (assumes compatible)
        to avoid false negatives.

        See Also
        --------
        get_requires_python : Get the raw requires_python string
        """
        requires_python = self.get_requires_python()
        if not requires_python:
            # No requirement specified, assume compatible
            return True

        if python_version is None:
            # Use current Python version
            python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        try:
            spec = SpecifierSet(requires_python)
            return python_version in spec
        except Exception:
            # If we can't parse, assume compatible
            return True

    def get_version_python_req(self, version_key: str) -> Optional[str]:
        """Get Python requirement for a specific version of the package.

        Retrieves the requires_python metadata for a particular version
        (current, latest, or compatible) from version-specific metadata
        stored in the metadata dictionary.

        Parameters
        ----------
        version_key : str
            Version identifier key. Must be one of:
            - 'current': Get requirement for current version
            - 'latest': Get requirement for latest version
            - 'compatible': Get requirement for compatible version

        Returns
        -------
        str or None
            Python version requirement string for the specified version,
            or None if not available in metadata.

        Examples
        --------
        >>> pkg = Package(
        ...     name="requests",
        ...     current_version="2.28.0",
        ...     metadata={
        ...         "current_metadata": {"requires_python": ">=3.7"},
        ...         "latest_metadata": {"requires_python": ">=3.8"}
        ...     }
        ... )
        >>> pkg.get_version_python_req("current")
        '>=3.7'
        >>> pkg.get_version_python_req("latest")
        '>=3.8'

        Notes
        -----
        This method expects version-specific metadata to be stored in
        the metadata dict with keys like:
        - current_metadata: Metadata for current version
        - latest_metadata: Metadata for latest version
        - compatible_metadata: Metadata for compatible version

        Each version metadata dict should contain a 'requires_python' field.
        """
        version_metadata = self.metadata.get(f"{version_key}_metadata", {})
        requires_python: Optional[str] = version_metadata.get("requires_python")
        return requires_python

    def has_compatible_version(self) -> bool:
        """Check if a Python-compatible version exists that differs from latest.

        Determines whether the package has a compatible_version set that is
        different from the latest_version. This is useful when the latest
        version requires a newer Python than currently available.

        Returns
        -------
        bool
            True if compatible_version is set and differs from latest_version,
            False otherwise.

        Examples
        --------
        Compatible version available:

        >>> pkg = Package(
        ...     name="numpy",
        ...     current_version="1.24.0",
        ...     latest_version="1.26.0",
        ...     compatible_version="1.24.4"
        ... )
        >>> pkg.has_compatible_version()
        True

        No separate compatible version:

        >>> pkg = Package(
        ...     name="click",
        ...     latest_version="8.1.7",
        ...     compatible_version="8.1.7"
        ... )
        >>> pkg.has_compatible_version()
        False

        Notes
        -----
        This scenario occurs when the latest version requires Python 3.11+
        but you're running Python 3.9, so a compatible_version of the last
        release supporting Python 3.9 is identified.

        See Also
        --------
        is_python_compatible : Check Python version compatibility
        """
        return (
            self.compatible_version is not None
            and self.compatible_version != self.latest_version
        )

    def __str__(self) -> str:
        """Return human-readable string representation of the package.

        Provides a concise, informative string showing package name, versions,
        and update status. Format varies based on available version information.

        Returns
        -------
        str
            Formatted string representation:
            - With current and latest: "name current → latest (status)"
            - Latest only: "name (latest: version)"
            - Name only: "name"

        Examples
        --------
        >>> pkg = Package(
        ...     name="requests",
        ...     current_version="2.28.0",
        ...     latest_version="2.31.0"
        ... )
        >>> str(pkg)
        'requests 2.28.0 → 2.31.0 (outdated)'

        >>> pkg = Package(
        ...     name="click",
        ...     current_version="8.1.7",
        ...     latest_version="8.1.7"
        ... )
        >>> str(pkg)
        'click 8.1.7 → 8.1.7 (up-to-date)'

        >>> pkg = Package(name="flask", latest_version="3.0.0")
        >>> str(pkg)
        'flask (latest: 3.0.0)'
        """
        if self.current_version and self.latest_version:
            status = "outdated" if self.has_update() else "up-to-date"
            return (
                f"{self.name} {self.current_version} → "
                f"{self.latest_version} ({status})"
            )
        if self.latest_version:
            return f"{self.name} (latest: {self.latest_version})"
        return self.name

    def __repr__(self) -> str:
        """Return developer-friendly string representation of the package.

        Provides a detailed representation suitable for debugging and logging,
        showing all key attributes and computed status.

        Returns
        -------
        str
            String in format:
            "Package(name='...', current_version='...', latest_version='...', outdated=...)"

        Examples
        --------
        >>> pkg = Package(
        ...     name="requests",
        ...     current_version="2.28.0",
        ...     latest_version="2.31.0"
        ... )
        >>> repr(pkg)
        "Package(name='requests', current_version='2.28.0', latest_version='2.31.0', outdated=True)"

        Notes
        -----
        The 'outdated' field is computed by has_update() and not stored.
        """
        return (
            f"Package(name={self.name!r}, current_version={self.current_version!r}, "
            f"latest_version={self.latest_version!r}, outdated={self.has_update()})"
        )
