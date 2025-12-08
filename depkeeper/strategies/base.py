from abc import ABC, abstractmethod
from typing import List, Protocol

from depkeeper.models.version import VersionInfo


class UpdateStrategy(Protocol):
    """
    Protocol defining the interface for update strategies.

    Update strategies determine which version updates are acceptable
    based on semantic versioning rules or custom logic.
    """

    @property
    def name(self) -> str:
        """Strategy name."""
        ...

    def should_update(self, current: VersionInfo, latest: VersionInfo) -> bool:
        """
        Determine if package should be updated from current to latest version.

        Args:
            current: Current version
            latest: Latest available version

        Returns:
            True if update should be applied
        """
        ...

    def filter_versions(
        self,
        versions: List[VersionInfo],
        current: VersionInfo,
    ) -> List[VersionInfo]:
        """
        Filter versions list to acceptable updates from current version.

        Args:
            versions: List of all available versions
            current: Current version

        Returns:
            List of acceptable versions for update
        """
        ...


class BaseStrategy(ABC):
    """
    Abstract base class for update strategies.

    Provides common functionality for version filtering and comparison.
    """

    def __init__(self, include_pre_release: bool = False):
        """
        Initialize strategy.

        Args:
            include_pre_release: Whether to include pre-release versions
        """
        self.include_pre_release = include_pre_release

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy name."""
        pass

    @abstractmethod
    def should_update(self, current: VersionInfo, latest: VersionInfo) -> bool:
        """
        Determine if package should be updated.

        Args:
            current: Current version
            latest: Latest available version

        Returns:
            True if update should be applied
        """
        pass

    def filter_versions(
        self,
        versions: List[VersionInfo],
        current: VersionInfo,
    ) -> List[VersionInfo]:
        """
        Filter versions to acceptable updates.

        Args:
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

            # Check if this version is acceptable per strategy
            if self.should_update(current, version):
                filtered.append(version)

        # Sort by version
        return sorted(filtered, key=lambda v: v.version)

    def get_latest_acceptable(
        self,
        versions: List[VersionInfo],
        current: VersionInfo,
    ) -> VersionInfo | None:
        """
        Get the latest acceptable version for update.

        Args:
            versions: All available versions
            current: Current version

        Returns:
            Latest acceptable version or None
        """
        acceptable = self.filter_versions(versions, current)
        return acceptable[-1] if acceptable else None
