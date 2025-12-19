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

from depkeeper.utils.version_utils import get_update_type


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
    safe_upgrade_version : str, optional
        Latest version safe to upgrade to (same major version).
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
    safe_upgrade_version : str or None
        String representation of maximum safe upgrade version.
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
    safe_upgrade_version: Optional[str] = None
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

        Compares the current version with the target upgrade version to determine
        if an update is available. The target version is safe_upgrade_version if
        set (indicating a compatibility constraint), otherwise latest_version.
        Returns False if either version is missing or invalid.

        Returns
        -------
        bool
            True if target version (safe_upgrade or latest) is greater than
            current version, False otherwise (including when versions are
            missing or invalid).

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

        Package with safe upgrade constraint:

        >>> pkg = Package(
        ...     name="numpy",
        ...     current_version="1.24.0",
        ...     latest_version="1.26.0",
        ...     safe_upgrade_version="1.24.4"  # Latest requires newer Python
        ... )
        >>> pkg.has_update()  # Compares against safe_upgrade (1.24.4)
        True

        Missing version information:

        >>> pkg = Package(name="test", current_version="1.0.0")
        >>> pkg.has_update()  # No latest_version set
        False

        Notes
        -----
        Uses parsed Version objects for comparison, ensuring PEP 440
        compliant version ordering (e.g., 2.0.0 > 2.0.0a1).

        When safe_upgrade_version is set, it takes precedence over latest_version
        for the comparison. This ensures we only report updates to versions that
        are actually installable in the current environment.

        If version parsing fails for either version, returns False to
        prevent false positives.

        See Also
        --------
        has_safe_upgrade_version : Check if safe upgrade version exists
        """
        if self.current is None or self.latest is None:
            return False

        # Parse target version (safe_upgrade takes precedence over latest)
        target_version_str = (
            self.safe_upgrade_version
            if self.safe_upgrade_version
            else self.latest_version
        )

        try:
            target_version = _parse(target_version_str)
            if target_version is None:
                return False
            return target_version > self.current
        except (InvalidVersion, TypeError):
            return False

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
            - 'safe_upgrade': Get requirement for safe upgrade version

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
        - safe_upgrade_metadata: Metadata for safe upgrade version

        Each version metadata dict should contain a 'requires_python' field.
        """
        version_metadata = self.metadata.get(f"{version_key}_metadata", {})
        requires_python: Optional[str] = version_metadata.get("requires_python")
        return requires_python

    def has_safe_upgrade_version(self) -> bool:
        """Check if a safe upgrade version exists that is actionable.

        Determines whether the package has a safe_upgrade_version that represents
        an actual upgrade opportunity. Returns True if the safe_upgrade_version:
        1. Differs from latest_version (indicating a compatibility constraint), OR
        2. Is newer than current_version (indicating an available upgrade)

        This is useful when the latest version requires a newer Python than
        currently available, or when showing users that a safe upgrade path exists.

        Returns
        -------
        bool
            True if safe_upgrade_version is set and represents an actionable
            upgrade (differs from latest OR is newer than current), False otherwise.

        Examples
        --------
        Safe upgrade due to Python compatibility constraint:

        >>> pkg = Package(
        ...     name="numpy",
        ...     current_version="1.24.0",
        ...     latest_version="1.26.0",
        ...     safe_upgrade_version="1.24.4"  # Latest needs Python 3.11+
        ... )
        >>> pkg.has_safe_upgrade_version()
        True

        Safe upgrade same as latest (but upgrade available):

        >>> pkg = Package(
        ...     name="requests",
        ...     current_version="2.28.0",
        ...     latest_version="2.31.0",
        ...     safe_upgrade_version="2.31.0"  # Same as latest, but newer than current
        ... )
        >>> pkg.has_safe_upgrade_version()
        True

        Already at safe upgrade version:

        >>> pkg = Package(
        ...     name="click",
        ...     current_version="8.1.7",
        ...     latest_version="8.1.7",
        ...     safe_upgrade_version="8.1.7"
        ... )
        >>> pkg.has_safe_upgrade_version()
        False

        Notes
        -----
        This method helps distinguish between different upgrade scenarios:

        - **Compatibility constraint**: safe_upgrade != latest (Python version limit)
        - **Standard upgrade**: safe_upgrade == latest but > current
        - **No upgrade**: safe_upgrade == current (already at target)

        The method returns False when current_version equals safe_upgrade_version,
        as there's no actual upgrade action to take.

        See Also
        --------
        is_python_compatible : Check Python version compatibility
        has_update : Check if any update is available
        """
        if not self.safe_upgrade_version:
            return False

        # Safe upgrade version is meaningful if it differs from latest
        # (meaning there's a compatibility constraint)
        if self.safe_upgrade_version != self.latest_version:
            return True

        # Also check if it differs from current (upgrade available to safe version)
        if self.current_version and self.safe_upgrade_version != self.current_version:
            try:
                safe_upgrade = _parse(self.safe_upgrade_version)
                if safe_upgrade is None or self.current is None:
                    return False
                return safe_upgrade > self.current
            except (InvalidVersion, TypeError):
                return False

        return False

    def needs_action(self) -> bool:
        """Check if package needs action (incompatible or needs downgrade).

        Determines if the package requires user attention beyond a simple update.
        This includes cases where the current version is incompatible with the
        Python environment or needs to be downgraded to a compatible version.

        Returns
        -------
        bool
            True if package is incompatible with current Python or needs downgrade,
            False if package is up-to-date or has a straightforward update path.

        Examples
        --------
        Package needing downgrade:

        >>> pkg = Package(
        ...     name="test",
        ...     current_version="2.0.0",
        ...     latest_version="3.0.0",
        ...     compatible_version="1.5.0"
        ... )
        >>> pkg.needs_action()
        True

        Package with incompatible latest version:

        >>> pkg = Package(
        ...     name="test",
        ...     current_version="1.0.0",
        ...     latest_version="2.0.0"
        ... )
        >>> pkg.metadata = {"requires_python": ">=3.12"}
        >>> pkg.needs_action()  # If running Python < 3.12
        True

        Normal update (no action needed):

        >>> pkg = Package(
        ...     name="test",
        ...     current_version="1.0.0",
        ...     latest_version="1.5.0",
        ...     compatible_version="1.5.0"
        ... )
        >>> pkg.needs_action()
        False

        Notes
        -----
        This method identifies packages that require special handling:

        1. **Downgrade needed**: Current version is higher than the maximum
           safe upgrade version for the current Python environment.

        2. **Incompatible**: Latest version requires a newer Python version
           and no safe upgrade alternative is available.

        Regular updates (where current < safe_upgrade/latest) return False as
        they follow the normal update path.

        See Also
        --------
        has_safe_upgrade_version : Check if safe upgrade version exists
        is_python_compatible : Check Python version compatibility
        has_update : Check if update is available
        """
        # Check if there's a safe upgrade version and current is greater (needs downgrade)
        if self.has_safe_upgrade_version() and self.current_version:
            try:
                current = _parse(self.current_version)
                safe_upgrade = _parse(self.safe_upgrade_version)
                if current and safe_upgrade and current > safe_upgrade:
                    return True
            except Exception:
                pass

        # Check if latest is incompatible and no safe upgrade version found
        if not self.is_python_compatible() and not self.has_safe_upgrade_version():
            return True

        return False

    def get_simple_status(self) -> tuple[str, str, str, Optional[str]]:
        """Get simple status information for the package.

        Returns a tuple of status information suitable for simple text output
        or logging. Provides a quick overview of package state without complex
        formatting. Determines status by directly comparing current version
        against the target upgrade version (safe_upgrade if set, otherwise latest).

        Returns
        -------
        tuple[str, str, str, str | None]
            Tuple containing (status, installed_version, latest_version, safe_upgrade_version):
            - status: "error", "outdated", or "latest"
            - installed_version: Current version or "none"
            - latest_version: Latest version or "error" if unavailable
            - safe_upgrade_version: Safe upgrade version or None

        Examples
        --------
        Package with update available:

        >>> pkg = Package(
        ...     name="requests",
        ...     current_version="2.28.0",
        ...     latest_version="2.31.0",
        ...     safe_upgrade_version="2.31.0"
        ... )
        >>> pkg.get_simple_status()
        ('outdated', '2.28.0', '2.31.0', '2.31.0')

        Package with compatibility constraint:

        >>> pkg = Package(
        ...     name="numpy",
        ...     current_version="1.24.0",
        ...     latest_version="1.26.0",
        ...     safe_upgrade_version="1.24.4"
        ... )
        >>> pkg.get_simple_status()  # Status based on safe_upgrade, not latest
        ('outdated', '1.24.0', '1.26.0', '1.24.4')

        Package with no version info:

        >>> pkg = Package(name="missing")
        >>> pkg.get_simple_status()
        ('error', 'none', 'error', None)

        Up-to-date package:

        >>> pkg = Package(
        ...     name="click",
        ...     current_version="8.1.7",
        ...     latest_version="8.1.7"
        ... )
        >>> pkg.get_simple_status()
        ('latest', '8.1.7', '8.1.7', None)

        Notes
        -----
        Status determination logic:
        - **error**: Package information unavailable (no latest_version)
        - **outdated**: Target version > current version
        - **latest**: Target version <= current version

        The target version is safe_upgrade_version if set, otherwise latest_version.
        This ensures the status reflects what's actually installable, not just
        what's newest.

        The safe_upgrade_version in the return tuple is only included if it differs
        from latest_version or provides an upgrade path from current, as determined
        by has_safe_upgrade_version().

        Version comparison uses packaging.version.parse for PEP 440 compliance,
        with fallback to string comparison if parsing fails.

        See Also
        --------
        to_json : Get detailed JSON representation
        has_update : Check if update is available
        has_safe_upgrade_version : Check if safe upgrade exists
        """
        installed = self.current_version or "none"
        latest = self.latest_version or "error"
        safe_upgrade = (
            self.safe_upgrade_version if self.has_safe_upgrade_version() else None
        )

        if not self.latest_version:
            status = "error"
        else:
            # Determine target version for comparison (safe upgrade takes precedence)
            target_version = (
                self.safe_upgrade_version
                if self.safe_upgrade_version
                else self.latest_version
            )

            # Compare current with target
            if not self.current_version:
                status = "outdated"  # No current version means needs installation
            else:
                try:
                    current_parsed = _parse(self.current_version)
                    target_parsed = _parse(target_version)
                    status = "outdated" if target_parsed > current_parsed else "latest"
                except (InvalidVersion, TypeError):
                    # If we can't parse versions, fall back to string comparison
                    status = (
                        "outdated"
                        if target_version != self.current_version
                        else "latest"
                    )

        return (status, installed, latest, safe_upgrade)

    def to_json(self) -> dict[str, Any]:
        """Convert package to JSON-serializable dictionary.

        Creates a comprehensive dictionary representation of the package
        suitable for JSON serialization, API responses, or structured logging.
        Includes all version information, status, update type, and Python
        requirements.

        Returns
        -------
        dict[str, Any]
            Dictionary with package information including:
            - name: Package name
            - status: "error", "outdated", or "latest"
            - versions: Dict of current/latest/safe_upgrade versions (if available)
            - update_type: Type of update (if outdated)
            - python_requirements: Python version requirements per version
            - error: Error message (if status is "error")

        Examples
        --------
        Outdated package:

        >>> pkg = Package(
        ...     name="requests",
        ...     current_version="2.28.0",
        ...     latest_version="2.31.0",
        ...     safe_upgrade_version="2.31.0"
        ... )
        >>> import json
        >>> print(json.dumps(pkg.to_json(), indent=2))
        {
          "name": "requests",
          "status": "outdated",
          "versions": {
            "current": "2.28.0",
            "latest": "2.31.0",
            "safe_upgrade": "2.31.0"
          },
          "update_type": "minor"
        }

        Package with error:

        >>> pkg = Package(name="missing")
        >>> pkg.to_json()
        {'name': 'missing', 'status': 'error', 'error': 'Package information unavailable'}

        Package with Python requirements:

        >>> pkg = Package(
        ...     name="typing-extensions",
        ...     current_version="4.5.0",
        ...     latest_version="4.8.0"
        ... )
        >>> pkg.metadata = {"requires_python": ">=3.8"}
        >>> data = pkg.to_json()
        >>> data["python_requirements"]
        {'latest': '>=3.8'}

        Notes
        -----
        The returned dictionary structure:

        - **name** (always present): Package name
        - **status** (always present): "error", "outdated", or "latest"
        - **versions** (if available): Dict with current/latest/safe_upgrade
        - **update_type** (if outdated): "major", "minor", "patch", etc.
        - **python_requirements** (if available): Requirements per version
        - **error** (if error status): Error description

        This method is used for JSON output format in the CLI and can be
        used for API responses or structured logging.

        See Also
        --------
        get_simple_status : Get simpler status tuple
        __str__ : Get human-readable string
        """
        # Determine status based on version availability and update status
        if not self.latest_version:
            status = "error"
        elif self.has_update():
            status = "outdated"
        else:
            status = "latest"

        entry = {
            "name": self.name,
            "status": status,
        }

        # Add version information
        versions = {}
        if self.current_version:
            versions["current"] = self.current_version
        if self.latest_version:
            versions["latest"] = self.latest_version
        if self.safe_upgrade_version:
            versions["safe_upgrade"] = self.safe_upgrade_version

        if versions:
            entry["versions"] = versions

        # Add update type if outdated (use target version for accurate type)
        if status == "outdated":
            target_version = (
                self.safe_upgrade_version
                if self.safe_upgrade_version
                else self.latest_version
            )
            update_type = get_update_type(self.current_version, target_version)
            if update_type:
                entry["update_type"] = update_type

        # Build python_requirements only with non-null values
        python_reqs = {}
        installed_req = self.get_version_python_req("current")
        if installed_req:
            python_reqs["current"] = installed_req

        latest_req = self.get_requires_python()
        if latest_req:
            python_reqs["latest"] = latest_req

        if self.has_safe_upgrade_version():
            safe_upgrade_req = self.get_version_python_req("safe_upgrade")
            if safe_upgrade_req:
                python_reqs["safe_upgrade"] = safe_upgrade_req

        if python_reqs:
            entry["python_requirements"] = python_reqs

        # Add error field if package fetch failed
        if status == "error":
            entry["error"] = "Package information unavailable"

        return entry

    def format_python_requirements(self) -> str:
        """Format detailed Python requirements for all versions.

        Creates a formatted string showing Python version requirements for
        the current, latest, and compatible versions. Useful for displaying
        in tables or reports where users need to see Python compatibility
        at a glance.

        Returns
        -------
        str
            Formatted string with Python requirements, using Rich markup
            for colored output. Returns "[dim]-[/dim]" if no requirements
            are available.

        Examples
        --------
        Package with multiple version requirements:

        >>> pkg = Package(
        ...     name="test",
        ...     current_version="1.0.0",
        ...     latest_version="2.0.0",
        ...     safe_upgrade_version="1.5.0"
        ... )
        >>> pkg.metadata = {
        ...     "version_info": {
        ...         "1.0.0": {"requires_python": ">=3.7"},
        ...         "2.0.0": {"requires_python": ">=3.10"},
        ...         "1.5.0": {"requires_python": ">=3.8"}
        ...     }
        ... }
        >>> print(pkg.format_python_requirements())
        Current: >=3.7
        Latest: >=3.10
        Safe Upgrade: >=3.8

        Package with only latest requirement:

        >>> pkg = Package(name="test", latest_version="1.0.0")
        >>> pkg.metadata = {"requires_python": ">=3.8"}
        >>> print(pkg.format_python_requirements())
        Latest: >=3.8

        Incompatible latest version:

        >>> pkg = Package(
        ...     name="test",
        ...     current_version="1.0.0",
        ...     latest_version="2.0.0",
        ...     safe_upgrade_version="1.5.0"
        ... )
        >>> # Latest requires Python 3.12, but running 3.10
        >>> result = pkg.format_python_requirements()

        Notes
        -----
        The output format uses Rich markup for colored display:
        - Current version in default color
        - Latest version in green (if compatible) or red (if incompatible)
        - Safe upgrade version in cyan
        - Warnings in yellow for incompatibility

        Requirements are separated by newlines for multi-line table cells.
        Returns "[dim]-[/dim]" if no Python requirements are available for
        any version.

        This method is primarily used by the check command for displaying
        Python compatibility information in the output table.

        See Also
        --------
        get_version_python_req : Get Python requirement for specific version
        get_requires_python : Get Python requirement from metadata
        is_python_compatible : Check if compatible with Python version
        """
        parts = []

        # Current version requirement
        current_req = self.get_version_python_req("current")
        if current_req:
            parts.append(f"Current: {current_req}")

        # Available (latest) version requirement
        latest_req = self.get_version_python_req("latest") or self.get_requires_python()
        if latest_req:
            # Color code based on compatibility
            if self.is_python_compatible():
                parts.append(f"Latest: [green]{latest_req}[/green]")
            else:
                parts.append(f"Latest: [red]{latest_req}[/red]")

        # Safe upgrade version requirement (if different from latest)
        if self.has_safe_upgrade_version():
            safe_upgrade_req = self.get_version_python_req("safe_upgrade")
            if safe_upgrade_req and safe_upgrade_req != latest_req:
                parts.append(
                    f"Safe Upgrade: [bright_cyan]{safe_upgrade_req}[/bright_cyan]"
                )
        elif not self.is_python_compatible() and self.latest_version:
            # No safe upgrade version found
            parts.append(
                f"[yellow]⚠ No safe upgrade version for current Python[/yellow]"
            )

        return "\n".join(parts) if parts else "[dim]-[/dim]"

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
            result = (
                f"{self.name} {self.current_version} → "
                f"{self.latest_version} ({status})"
            )
            # Add safe upgrade info if it differs from latest
            if self.has_safe_upgrade_version():
                result += f" [safe: {self.safe_upgrade_version}]"
            return result
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
            f"latest_version={self.latest_version!r}, "
            f"safe_upgrade_version={self.safe_upgrade_version!r}, outdated={self.has_update()})"
        )
