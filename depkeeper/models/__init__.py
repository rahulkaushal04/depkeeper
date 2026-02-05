"""
Unified data model exports for depkeeper.

This module re-exports all core data models to provide a stable and
convenient public API. Users can import models directly from
``depkeeper.models`` instead of individual submodules.

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
