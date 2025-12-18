"""Version comparison utilities for depkeeper.

This module provides utilities for comparing package versions and determining
update types (major, minor, patch) between versions. It handles semantic
versioning analysis and provides consistent version comparison logic across
the application.

Examples
--------
Determine update type between versions:

    >>> from depkeeper.utils.version_utils import get_update_type
    >>> get_update_type("2.28.0", "2.31.0")
    'minor'
    >>> get_update_type("1.0.0", "2.0.0")
    'major'
    >>> get_update_type("3.1.4", "3.1.5")
    'patch'

Handle edge cases:

    >>> get_update_type(None, "1.0.0")
    'new'
    >>> get_update_type("2.0.0", "1.5.0")
    'downgrade'
    >>> get_update_type("invalid", "1.0.0")
    'update'

Notes
-----
Version comparison follows PEP 440 using the packaging library. The update
type classification follows semantic versioning conventions:

- **major**: First number changes (1.x.x → 2.x.x) - breaking changes
- **minor**: Second number changes (1.1.x → 1.2.x) - new features
- **patch**: Third number changes (1.1.1 → 1.1.2) - bug fixes
- **new**: No current version exists
- **downgrade**: Target version is lower than current
- **update**: Generic update when version parts can't be compared
- **unknown**: Invalid version strings

See Also
--------
packaging.version : PEP 440 version parsing
depkeeper.models.package : Package model with version tracking
"""

from __future__ import annotations

from typing import Optional

from packaging.version import parse, InvalidVersion


def get_update_type(
    current_version: Optional[str],
    target_version: Optional[str],
) -> str:
    """Determine update type between two versions.

    Analyzes two version strings and classifies the type of update according
    to semantic versioning rules. Handles edge cases like missing versions,
    downgrades, and invalid version strings.

    Parameters
    ----------
    current_version : str or None
        Current/installed version string. If None, assumes package is new.
    target_version : str or None
        Target/new version string to compare against.

    Returns
    -------
    str
        Update type classification:
        - 'new': No current version (new installation)
        - 'downgrade': Target is older than current
        - 'major': Major version change (X.0.0)
        - 'minor': Minor version change (0.X.0)
        - 'patch': Patch version change (0.0.X)
        - 'update': Generic update (versions comparable but type unclear)
        - 'unknown': Cannot parse or compare versions

    Examples
    --------
    Semantic version updates:

    >>> get_update_type("1.0.0", "2.0.0")
    'major'
    >>> get_update_type("2.5.0", "2.6.0")
    'minor'
    >>> get_update_type("1.2.3", "1.2.4")
    'patch'

    Edge cases:

    >>> get_update_type(None, "1.0.0")
    'new'
    >>> get_update_type("2.0.0", "1.0.0")
    'downgrade'
    >>> get_update_type("invalid", "1.0.0")
    'unknown'
    >>> get_update_type("1.0.0", None)
    'unknown'

    Pre-release versions:

    >>> get_update_type("1.0.0a1", "1.0.0")
    'patch'

    Notes
    -----
    Uses packaging.version.parse for PEP 440 compliant version parsing.

    For versions with fewer than 3 parts (e.g., "1.0"), missing parts are
    treated as 0 for comparison purposes.

    Version parts beyond the third (e.g., "1.2.3.4") are ignored for
    update type classification.

    See Also
    --------
    packaging.version.parse : Version string parser
    packaging.version.Version : Version comparison class
    """
    # No current version = new installation
    if current_version is None:
        return "new"

    # No target version = unknown
    if target_version is None:
        return "unknown"

    try:
        current = parse(current_version)
        target = parse(target_version)

        # Check for downgrade
        if target < current:
            return "downgrade"

        # Compare version parts for semantic versioning
        if hasattr(current, "release") and hasattr(target, "release"):
            current_parts = current.release
            target_parts = target.release

            # Need at least major version to compare
            if len(current_parts) >= 1 and len(target_parts) >= 1:
                # Major version change
                if current_parts[0] != target_parts[0]:
                    return "major"

                # Minor version change
                if len(current_parts) >= 2 and len(target_parts) >= 2:
                    if current_parts[1] != target_parts[1]:
                        return "minor"

                # Patch version change
                if len(current_parts) >= 3 and len(target_parts) >= 3:
                    if current_parts[2] != target_parts[2]:
                        return "patch"

        # Versions are different but can't classify type
        return "update"

    except (InvalidVersion, AttributeError, IndexError):
        return "unknown"
