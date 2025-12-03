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
