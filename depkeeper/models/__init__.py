"""
Unified data model exports for depkeeper.

This module provides convenient import access to all core data models, so users
can simply do:

    from depkeeper.models import Package, Requirement, VersionInfo

instead of importing each model from its submodule.
"""

from __future__ import annotations

from depkeeper.models.package import Package
from depkeeper.models.version import VersionInfo
from depkeeper.models.requirement import Requirement
from depkeeper.models.update_result import UpdateResult

__all__ = ["Package", "Requirement", "VersionInfo", "UpdateResult"]
