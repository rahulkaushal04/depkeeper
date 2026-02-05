"""
Version information for depkeeper.

This module exposes the canonical version string for the depkeeper
package. It is intentionally isolated to avoid import cycles and to
allow tools (CLI, packaging, docs) to query the version reliably.
"""

from __future__ import annotations

#: Current depkeeper version (PEP 440 compliant).
__version__: str = "0.1.0.dev1"
