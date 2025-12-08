"""
Core functionality exports for depkeeper.

This module provides convenient access to the core subsystems of depkeeper.
Importing from here keeps user-facing imports clean and stable:

    from depkeeper.core import RequirementsParser

As additional core components are added (Resolver, Updater, Validator, etc.),
they should be re-exported here to maintain a consistent public API.
"""

from __future__ import annotations

from depkeeper.core.parser import RequirementsParser
from depkeeper.core.validator import RequirementsValidator
from depkeeper.core.updater import RequirementsUpdater

__all__ = [
    "RequirementsParser",
    "RequirementsUpdater",
    "RequirementsValidator",
]
