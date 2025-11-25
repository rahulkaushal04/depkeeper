"""
depkeeper — Modern Python Dependency Management Tool

depkeeper is an intelligent, safety-focused dependency manager that helps
developers keep their Python environments up-to-date, secure, and
reproducible.

Features include:
    • Smart dependency updates with semantic versioning
    • Security vulnerability scanning (OSV / PyPA)
    • Lock file generation for reproducible builds
    • Dependency health scoring
    • Multi-format support (requirements.txt, pyproject.toml, Pipfile, etc.)
    • CI/CD integration and automation

For documentation, examples, and API reference:
    https://docs.depkeeper.dev
"""

from __future__ import annotations

from depkeeper.__version__ import __version__

# ---------------------------------------------------------------------------
# Package Metadata
# ---------------------------------------------------------------------------

__author__ = "depkeeper Contributors"
__license__ = "Apache-2.0"
__url__ = "https://github.com/rahulkaushal04/depkeeper"
__description__ = "Modern Python dependency management for requirements.txt and beyond."

# ---------------------------------------------------------------------------
# Public API (Phase 1+)
#
# Only expose stable, documented interfaces here.
# Once core API classes are implemented, they should be exported via __all__.
# ---------------------------------------------------------------------------

__all__ = [
    "__version__",
    # "DepKeeperClient",   # Example (future)
]
