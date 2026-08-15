"""Unified data model exports for depkeeper.

Re-exports all core data models to provide a stable, convenient public API,
so callers can import from ``depkeeper.models`` instead of individual
submodules.

Example:
    >>> from depkeeper.models import Package, Requirement, Conflict
"""

from __future__ import annotations

from depkeeper.models.package import Package
from depkeeper.models.requirement import Requirement
from depkeeper.models.conflict import Conflict, ConflictSet

__all__ = [
    "Package",
    "Requirement",
    "Conflict",
    "ConflictSet",
]
