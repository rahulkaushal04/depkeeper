"""
Version comparison utilities for depkeeper.

This module provides helpers for classifying version changes using
PEP 440–compatible version parsing.
"""

from __future__ import annotations

from typing import Optional, Tuple

from packaging.version import InvalidVersion, Version, parse


def get_update_type(
    current_version: Optional[str],
    target_version: Optional[str],
) -> str:
    """Determine the semantic update type between two versions.

    Args:
        current_version: Currently installed version, or ``None`` if not installed.
        target_version: Target version to compare against.

    Returns:
        One of:
            - ``"new"``       : No current version exists
            - ``"same"``      : Versions are identical
            - ``"downgrade"`` : Target version is lower than current
            - ``"major"``     : Major version change
            - ``"minor"``     : Minor version change
            - ``"patch"``     : Patch-level change
            - ``"update"``    : Update that cannot be classified further
            - ``"unknown"``   : Invalid or unsupported version comparison

    Examples:
        >>> get_update_type("1.0.0", "2.0.0")
        'major'
        >>> get_update_type(None, "1.0.0")
        'new'
        >>> get_update_type("1.2.3", "1.2.3")
        'same'
    """
    if current_version is None and target_version is None:
        return "unknown"

    if current_version is None:
        return "new"

    if target_version is None:
        return "unknown"

    try:
        current = _parse_version(current_version)
        target = _parse_version(target_version)

        if target == current:
            return "same"

        if target < current:
            return "downgrade"

        return _classify_upgrade(current, target)

    except InvalidVersion:
        return "unknown"


def _parse_version(value: str) -> Version:
    """Parse a version string into a PEP 440 Version object."""
    parsed = parse(value)
    if not isinstance(parsed, Version):
        raise InvalidVersion(value)
    return parsed


def _classify_upgrade(current: Version, target: Version) -> str:
    """Classify an upgrade between two valid versions."""
    current_major, current_minor, current_patch = _normalize_release(current)
    target_major, target_minor, target_patch = _normalize_release(target)

    if current_major != target_major:
        return "major"

    if current_minor != target_minor:
        return "minor"

    if current_patch != target_patch:
        return "patch"

    # Covers pre-release → release or metadata-only updates
    return "update"


def _normalize_release(version: Version) -> Tuple[int, int, int]:
    """Normalize a version's release segment to (major, minor, patch)."""
    release = version.release
    major = release[0] if len(release) > 0 else 0
    minor = release[1] if len(release) > 1 else 0
    patch = release[2] if len(release) > 2 else 0
    return major, minor, patch
