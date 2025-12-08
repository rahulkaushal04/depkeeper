from __future__ import annotations

from typing import Dict, Optional

from depkeeper.models.version import VersionInfo
from depkeeper.strategies.base import BaseStrategy


class ConservativeStrategy(BaseStrategy):
    """
    Conservative update strategy - patch updates only.

    Only allows updates within the same major.minor version.
    Example: 1.2.3 -> 1.2.4 (allowed), 1.2.3 -> 1.3.0 (blocked)

    Special handling for pre-1.0 versions:
    - 0.x.y versions are treated as unstable
    - Only patch updates allowed (0.1.2 -> 0.1.3)
    """

    @property
    def name(self) -> str:
        """Strategy name."""
        return "conservative"

    def should_update(self, current: VersionInfo, latest: VersionInfo) -> bool:
        """
        Allow only patch-level updates (same major.minor).

        Args:
            current: Current version
            latest: Version to evaluate

        Returns:
            True if latest is a valid patch update
        """
        # Must be newer
        if latest.version <= current.version:
            return False

        # Same major and minor version
        return latest.major == current.major and latest.minor == current.minor


class ModerateStrategy(BaseStrategy):
    """
    Moderate update strategy - minor and patch updates.

    Allows updates within the same major version.
    Example: 1.2.3 -> 1.9.0 (allowed), 1.2.3 -> 2.0.0 (blocked)

    Special handling for pre-1.0 versions:
    - 0.x.y versions: Only minor/patch updates within 0.x series
    - 0.1.2 -> 0.2.0 (allowed), 0.1.2 -> 1.0.0 (blocked)
    """

    @property
    def name(self) -> str:
        """Strategy name."""
        return "moderate"

    def should_update(self, current: VersionInfo, latest: VersionInfo) -> bool:
        """
        Allow minor and patch updates (same major).

        Args:
            current: Current version
            latest: Version to evaluate

        Returns:
            True if latest is a valid minor/patch update
        """
        # Must be newer
        if latest.version <= current.version:
            return False

        # Same major version
        return latest.major == current.major


class AggressiveStrategy(BaseStrategy):
    """
    Aggressive update strategy - all updates including major versions.

    Allows all newer versions regardless of breaking changes.
    Example: 1.2.3 -> 2.0.0 (allowed), 1.2.3 -> 3.5.1 (allowed)

    This strategy accepts any version greater than current, including:
    - Major version bumps (breaking changes)
    - Pre-1.0 to 1.0+ transitions
    - Calendar versioning changes
    """

    @property
    def name(self) -> str:
        """Strategy name."""
        return "aggressive"

    def should_update(self, current: VersionInfo, latest: VersionInfo) -> bool:
        """
        Allow all updates that are newer than current.

        Args:
            current: Current version
            latest: Version to evaluate

        Returns:
            True if latest is newer than current
        """
        return latest.version > current.version


class CustomStrategy(BaseStrategy):
    """
    Custom update strategy with per-package rules.

    Allows defining custom update policies for individual packages.
    Rules can specify different strategies for different packages or
    custom version constraints.

    Example rules:
        {
            "django": {"strategy": "conservative", "max_version": "4.2.0"},
            "requests": {"strategy": "aggressive"},
            "numpy": {"min_version": "1.20.0", "max_version": "1.26.0"}
        }
    """

    def __init__(
        self,
        rules: Optional[Dict[str, Dict[str, str]]] = None,
        default_strategy: str = "moderate",
        include_pre_release: bool = False,
    ):
        """
        Initialize custom strategy with per-package rules.

        Args:
            rules: Dictionary mapping package names to custom rules
            default_strategy: Default strategy for packages without rules
            include_pre_release: Whether to include pre-release versions
        """
        super().__init__(include_pre_release=include_pre_release)
        self.rules = rules or {}
        self.default_strategy = default_strategy

        # Cache strategy instances
        self._strategies: Dict[str, BaseStrategy] = {
            "conservative": ConservativeStrategy(include_pre_release),
            "moderate": ModerateStrategy(include_pre_release),
            "aggressive": AggressiveStrategy(include_pre_release),
        }

    @property
    def name(self) -> str:
        """Strategy name."""
        return "custom"

    def should_update(self, current: VersionInfo, latest: VersionInfo) -> bool:
        """
        Apply default strategy for updates.

        Note: For package-specific rules, use get_package_strategy() method.

        Args:
            current: Current version
            latest: Version to evaluate

        Returns:
            True if update should be applied per default strategy
        """
        default = self._strategies.get(
            self.default_strategy, self._strategies["moderate"]
        )
        return default.should_update(current, latest)

    def get_package_strategy(self, package_name: str) -> BaseStrategy:
        """
        Get the appropriate strategy for a specific package.

        Args:
            package_name: Name of the package

        Returns:
            Strategy instance for the package
        """
        # Normalize package name
        normalized_name = package_name.lower().replace("_", "-")

        # Check if package has custom rules
        if normalized_name in self.rules:
            rule = self.rules[normalized_name]
            strategy_name = rule.get("strategy", self.default_strategy)
            return self._strategies.get(
                strategy_name, self._strategies[self.default_strategy]
            )

        # Return default strategy
        return self._strategies.get(self.default_strategy, self._strategies["moderate"])

    def should_update_package(
        self,
        package_name: str,
        current: VersionInfo,
        latest: VersionInfo,
    ) -> bool:
        """
        Check if a specific package should be updated with custom rules.

        Args:
            package_name: Name of the package
            current: Current version
            latest: Version to evaluate

        Returns:
            True if update should be applied per package rules
        """
        # Get package-specific strategy
        strategy = self.get_package_strategy(package_name)

        # Check base strategy rules
        if not strategy.should_update(current, latest):
            return False

        # Apply additional version constraints if defined
        normalized_name = package_name.lower().replace("_", "-")
        if normalized_name in self.rules:
            rule = self.rules[normalized_name]

            # Check min_version constraint
            if "min_version" in rule:
                min_ver = VersionInfo(rule["min_version"])
                if latest.version < min_ver.version:
                    return False

            # Check max_version constraint
            if "max_version" in rule:
                max_ver = VersionInfo(rule["max_version"])
                if latest.version > max_ver.version:
                    return False

        return True

    def filter_versions_for_package(
        self,
        package_name: str,
        versions: list[VersionInfo],
        current: VersionInfo,
    ) -> list[VersionInfo]:
        """
        Filter versions for a specific package with custom rules.

        Args:
            package_name: Name of the package
            versions: All available versions
            current: Current version

        Returns:
            Filtered list of acceptable versions
        """
        filtered = []

        for version in versions:
            # Skip pre-releases unless explicitly allowed
            if version.is_prerelease and not self.include_pre_release:
                continue

            # Skip current and older versions
            if version.version <= current.version:
                continue

            # Check if this version is acceptable per package rules
            if self.should_update_package(package_name, current, version):
                filtered.append(version)

        # Sort by version
        return sorted(filtered, key=lambda v: v.version)


# =============================================================================
# Utility Functions
# =============================================================================


def detect_versioning_scheme(version: VersionInfo) -> str:
    """
    Detect the versioning scheme used by a package.

    Args:
        version: Version to analyze

    Returns:
        Versioning scheme: "semver", "calver", or "unknown"
    """
    if version.is_semver():
        return "semver"
    elif version.is_calver():
        return "calver"
    else:
        return "unknown"


def is_pre_one_version(version: VersionInfo) -> bool:
    """
    Check if version is pre-1.0 (0.x.y).

    Pre-1.0 versions are considered unstable in semantic versioning.

    Args:
        version: Version to check

    Returns:
        True if version is 0.x.y
    """
    return version.major == 0


def is_breaking_change(current: VersionInfo, latest: VersionInfo) -> bool:
    """
    Determine if update represents a breaking change per semver rules.

    Breaking changes occur when:
    - Major version increases (for versions >= 1.0.0)
    - Minor version increases for 0.x.y versions

    Args:
        current: Current version
        latest: New version

    Returns:
        True if update is likely to have breaking changes
    """
    # For stable versions (>= 1.0.0), major bump is breaking
    if current.major >= 1:
        return latest.major > current.major

    # For pre-1.0 versions, minor bump is breaking
    if current.major == 0:
        return latest.minor > current.minor

    return False


def get_update_type(current: VersionInfo, latest: VersionInfo) -> str:
    """
    Classify the type of update between two versions.

    Args:
        current: Current version
        latest: New version

    Returns:
        Update type: "major", "minor", "patch", or "none"
    """
    if latest.version <= current.version:
        return "none"

    if latest.major > current.major:
        return "major"
    elif latest.minor > current.minor:
        return "minor"
    elif latest.patch > current.patch:
        return "patch"

    return "none"


def select_strategy(strategy_name: str, **kwargs) -> BaseStrategy:
    """
    Factory function to create strategy instances by name.

    Args:
        strategy_name: Name of the strategy ("conservative", "moderate", "aggressive", "custom")
        **kwargs: Additional arguments for strategy initialization

    Returns:
        Strategy instance

    Raises:
        ValueError: If strategy name is not recognized
    """
    strategies = {
        "conservative": ConservativeStrategy,
        "moderate": ModerateStrategy,
        "aggressive": AggressiveStrategy,
        "custom": CustomStrategy,
    }

    strategy_class = strategies.get(strategy_name.lower())
    if strategy_class is None:
        raise ValueError(
            f"Unknown strategy: {strategy_name}. "
            f"Available: {', '.join(strategies.keys())}"
        )

    return strategy_class(**kwargs)
