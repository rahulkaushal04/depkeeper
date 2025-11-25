"""
depkeeper version information.

This module provides a single source of truth for the package version.
It follows Semantic Versioning: https://semver.org/

Version format:
    MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]

Examples:
    0.1.0
    0.1.0.dev0
    1.0.0-rc1
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Main version (single source of truth)
# ---------------------------------------------------------------------------

__version__ = "0.1.0.dev0"


# ---------------------------------------------------------------------------
# Structured version metadata
# ---------------------------------------------------------------------------


def _parse_version(version: str):
    """
    Internal helper to break a semantic version into components.
    Avoids manual duplication and mistakes.

    Returns:
        dict: {
            "major": int,
            "minor": int,
            "patch": int,
            "prerelease": str | None,
            "is_dev": bool,
        }
    """

    pattern = r"^(\d+)\.(\d+)\.(\d+)(?:[.-]([a-zA-Z0-9]+))?$"
    match = re.match(pattern, version)

    if not match:
        error_message = f"Invalid version string: {version}"
        raise ValueError(error_message)

    major, minor, patch, pre = match.groups()

    return {
        "major": int(major),
        "minor": int(minor),
        "patch": int(patch),
        "prerelease": pre,
        "is_dev": pre is not None and pre.startswith("dev"),
    }


VERSION_INFO = _parse_version(__version__)


# ---------------------------------------------------------------------------
# Human-readable version (for CLI)
# ---------------------------------------------------------------------------

VERSION_STRING = f"depkeeper {__version__}"
