"""Core subsystem exports for depkeeper.

Provides convenient access to the core subsystems. Importing from here keeps
user-facing imports stable even if internal modules are reorganized::

    from depkeeper.core import RequirementsParser

New core components should be re-exported here to maintain one consistent
public API.
"""

from __future__ import annotations

from depkeeper.core.checker import VersionChecker
from depkeeper.core.parser import RequirementsParser
from depkeeper.core.data_store import PyPIDataStore, PyPIPackageData
from depkeeper.core.dependency_analyzer import DependencyAnalyzer, ResolutionResult

__all__ = [
    "RequirementsParser",
    "VersionChecker",
    "PyPIDataStore",
    "PyPIPackageData",
    "DependencyAnalyzer",
    "ResolutionResult",
]
