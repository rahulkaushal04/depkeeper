"""Version information for depkeeper.

This module provides the single source of truth for depkeeper's version
number and related metadata. It follows Semantic Versioning 2.0.0 as
specified at https://semver.org/

The version string is automatically parsed into structured components,
making it easy to perform version comparisons and feature detection
based on the current version.

Version Format
--------------
Semantic Versioning format:

    MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]

Where:

- **MAJOR**: Incompatible API changes
- **MINOR**: Backwards-compatible functionality additions
- **PATCH**: Backwards-compatible bug fixes
- **PRERELEASE**: Optional pre-release identifier (dev, alpha, beta, rc)
- **BUILD**: Optional build metadata (not used in depkeeper)

Examples
--------
Valid version strings:

    >>> __version__ = "0.1.0"          # Development release
    >>> __version__ = "0.1.0.dev0"     # Pre-release (dev)
    >>> __version__ = "1.0.0-alpha1"   # Alpha release
    >>> __version__ = "1.0.0-beta2"    # Beta release
    >>> __version__ = "1.0.0-rc1"      # Release candidate
    >>> __version__ = "1.2.3"          # Stable release

Accessing version information:

    >>> from depkeeper import __version__
    >>> print(__version__)
    0.1.0.dev0

Pre-release Identifiers
-----------------------
Pre-release versions are indicated by a hyphen or dot followed by an
identifier:

- **dev**: Development/nightly builds (e.g., 0.1.0.dev0, 0.1.0.dev1)
- **alpha/a**: Alpha releases (e.g., 1.0.0-alpha1)
- **beta/b**: Beta releases (e.g., 1.0.0-beta1)
- **rc**: Release candidates (e.g., 1.0.0-rc1)

Development versions (dev) are considered less stable than any other
identifier and should not be used in production.

Notes
-----
This module should be the only place where the version is defined.
All other modules should import from here:

    >>> from depkeeper.__version__ import __version__

Version comparison should be done using the packaging library:

    >>> from packaging.version import Version
    >>> from depkeeper import __version__
    >>> if Version(__version__) >= Version("1.0.0"):
    ...     print("Stable release")

See Also
--------
packaging.version : PEP 440 compliant version parsing
https://semver.org/ : Semantic Versioning specification
https://peps.python.org/pep-0440/ : Python version identification
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Main version (single source of truth)
# ---------------------------------------------------------------------------

__version__ = "0.1.0.dev0"
