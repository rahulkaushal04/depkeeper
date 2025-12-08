"""
Update strategies for version filtering.

This module provides strategies for determining which package updates
are acceptable based on semantic versioning rules or custom logic.
"""

from depkeeper.strategies.base import BaseStrategy, UpdateStrategy
from depkeeper.strategies.semver import (
    ConservativeStrategy,
    ModerateStrategy,
    AggressiveStrategy,
    CustomStrategy,
    detect_versioning_scheme,
    is_pre_one_version,
    is_breaking_change,
    get_update_type,
    select_strategy,
)
from depkeeper.strategies.filters import (
    PackageFilter,
    create_filter_from_config,
    combine_filters,
)

__all__ = [
    # Base classes and protocols
    "BaseStrategy",
    "UpdateStrategy",
    # Semantic versioning strategies
    "ConservativeStrategy",
    "ModerateStrategy",
    "AggressiveStrategy",
    "CustomStrategy",
    # Strategy utilities
    "detect_versioning_scheme",
    "is_pre_one_version",
    "is_breaking_change",
    "get_update_type",
    "select_strategy",
    # Package filtering
    "PackageFilter",
    "create_filter_from_config",
    "combine_filters",
]
