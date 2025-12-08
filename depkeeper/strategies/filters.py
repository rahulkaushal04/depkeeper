"""
Package filtering utilities.

Provides filtering capabilities for packages based on whitelists, blacklists,
version constraints, and pre-release policies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set

from packaging.version import Version, parse as parse_version, InvalidVersion

from depkeeper.models.package import Package
from depkeeper.models.version import VersionInfo


@dataclass
class PackageFilter:
    """
    Filter for applying inclusion/exclusion rules to packages.

    Provides flexible filtering based on:
    - Whitelist: Only include specified packages
    - Blacklist: Exclude specified packages
    - Pre-release exclusion
    - Version constraints (min/max)

    Attributes:
        whitelist: Set of package names to include (None = include all)
        blacklist: Set of package names to exclude
        exclude_pre_release: Skip pre-release versions
        min_version: Minimum acceptable version (per package)
        max_version: Maximum acceptable version (per package)
    """

    whitelist: Optional[Set[str]] = None
    blacklist: Set[str] = field(default_factory=set)
    exclude_pre_release: bool = True
    min_version: dict[str, str] = field(default_factory=dict)
    max_version: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize package names in filters."""
        # Normalize whitelist
        if self.whitelist is not None:
            self.whitelist = {self._normalize_name(name) for name in self.whitelist}

        # Normalize blacklist
        self.blacklist = {self._normalize_name(name) for name in self.blacklist}

        # Normalize version constraint keys
        self.min_version = {
            self._normalize_name(name): version
            for name, version in self.min_version.items()
        }
        self.max_version = {
            self._normalize_name(name): version
            for name, version in self.max_version.items()
        }

    @staticmethod
    def _normalize_name(name: str) -> str:
        """
        Normalize package name per PEP 503.

        Args:
            name: Package name

        Returns:
            Normalized package name
        """
        return name.lower().replace("_", "-")

    def is_allowed(self, package: Package) -> bool:
        """
        Check if a package passes all filter criteria.

        Args:
            package: Package to check

        Returns:
            True if package passes all filters
        """
        normalized_name = self._normalize_name(package.name)

        # Check whitelist (if defined)
        if self.whitelist is not None:
            if normalized_name not in self.whitelist:
                return False

        # Check blacklist
        if normalized_name in self.blacklist:
            return False

        # Check pre-release exclusion
        if self.exclude_pre_release:
            if package.latest_version:
                try:
                    latest = VersionInfo(package.latest_version)
                    if latest.is_prerelease:
                        return False
                except (ValueError, InvalidVersion):
                    pass

        # Check version constraints
        if not self._check_version_constraints(package):
            return False

        return True

    def _check_version_constraints(self, package: Package) -> bool:
        """
        Check if package version satisfies min/max constraints.

        Args:
            package: Package to check

        Returns:
            True if version constraints are satisfied
        """
        normalized_name = self._normalize_name(package.name)

        # Get version to check (use latest_version)
        version_str = package.latest_version
        if not version_str:
            return True  # No version to check

        try:
            version = parse_version(version_str)
        except InvalidVersion:
            return True  # Can't parse, allow through

        # Check minimum version
        if normalized_name in self.min_version:
            try:
                min_ver = parse_version(self.min_version[normalized_name])
                if version < min_ver:
                    return False
            except InvalidVersion:
                pass  # Invalid constraint, ignore

        # Check maximum version
        if normalized_name in self.max_version:
            try:
                max_ver = parse_version(self.max_version[normalized_name])
                if version > max_ver:
                    return False
            except InvalidVersion:
                pass  # Invalid constraint, ignore

        return True

    def apply_filters(self, packages: List[Package]) -> List[Package]:
        """
        Apply all filters to a list of packages.

        Args:
            packages: List of packages to filter

        Returns:
            Filtered list of packages
        """
        return [pkg for pkg in packages if self.is_allowed(pkg)]

    def filter_package_versions(
        self,
        package: Package,
        versions: List[str],
    ) -> List[str]:
        """
        Filter available versions for a package based on constraints.

        Args:
            package: Package being filtered
            versions: List of version strings to filter

        Returns:
            Filtered list of version strings
        """
        normalized_name = self._normalize_name(package.name)
        filtered = []

        for version_str in versions:
            try:
                version = parse_version(version_str)
                version_info = VersionInfo(version_str)
            except (InvalidVersion, ValueError):
                continue  # Skip invalid versions

            # Check pre-release exclusion
            if self.exclude_pre_release and version_info.is_prerelease:
                continue

            # Check minimum version
            if normalized_name in self.min_version:
                try:
                    min_ver = parse_version(self.min_version[normalized_name])
                    if version < min_ver:
                        continue
                except InvalidVersion:
                    pass

            # Check maximum version
            if normalized_name in self.max_version:
                try:
                    max_ver = parse_version(self.max_version[normalized_name])
                    if version > max_ver:
                        continue
                except InvalidVersion:
                    pass

            filtered.append(version_str)

        return filtered

    def add_to_whitelist(self, *package_names: str) -> None:
        """
        Add packages to whitelist.

        Args:
            *package_names: Package names to add
        """
        if self.whitelist is None:
            self.whitelist = set()

        for name in package_names:
            self.whitelist.add(self._normalize_name(name))

    def add_to_blacklist(self, *package_names: str) -> None:
        """
        Add packages to blacklist.

        Args:
            *package_names: Package names to add
        """
        for name in package_names:
            self.blacklist.add(self._normalize_name(name))

    def remove_from_whitelist(self, *package_names: str) -> None:
        """
        Remove packages from whitelist.

        Args:
            *package_names: Package names to remove
        """
        if self.whitelist is None:
            return

        for name in package_names:
            self.whitelist.discard(self._normalize_name(name))

    def remove_from_blacklist(self, *package_names: str) -> None:
        """
        Remove packages from blacklist.

        Args:
            *package_names: Package names to remove
        """
        for name in package_names:
            self.blacklist.discard(self._normalize_name(name))

    def set_min_version(self, package_name: str, version: str) -> None:
        """
        Set minimum version constraint for a package.

        Args:
            package_name: Package name
            version: Minimum version string
        """
        self.min_version[self._normalize_name(package_name)] = version

    def set_max_version(self, package_name: str, version: str) -> None:
        """
        Set maximum version constraint for a package.

        Args:
            package_name: Package name
            version: Maximum version string
        """
        self.max_version[self._normalize_name(package_name)] = version

    def clear_version_constraints(self, package_name: str) -> None:
        """
        Clear all version constraints for a package.

        Args:
            package_name: Package name
        """
        normalized_name = self._normalize_name(package_name)
        self.min_version.pop(normalized_name, None)
        self.max_version.pop(normalized_name, None)

    def has_constraints_for(self, package_name: str) -> bool:
        """
        Check if package has any filter constraints.

        Args:
            package_name: Package name

        Returns:
            True if package has constraints
        """
        normalized_name = self._normalize_name(package_name)

        # Check whitelist
        if self.whitelist is not None and normalized_name not in self.whitelist:
            return True

        # Check blacklist
        if normalized_name in self.blacklist:
            return True

        # Check version constraints
        if normalized_name in self.min_version or normalized_name in self.max_version:
            return True

        return False

    def get_stats(self) -> dict[str, int]:
        """
        Get statistics about the filter configuration.

        Returns:
            Dictionary with filter statistics
        """
        return {
            "whitelist_count": len(self.whitelist) if self.whitelist else 0,
            "blacklist_count": len(self.blacklist),
            "min_version_constraints": len(self.min_version),
            "max_version_constraints": len(self.max_version),
        }


# =============================================================================
# Utility Functions
# =============================================================================


def create_filter_from_config(config: dict) -> PackageFilter:
    """
    Create a PackageFilter from a configuration dictionary.

    Args:
        config: Configuration dictionary with filter settings

    Returns:
        Configured PackageFilter instance

    Example:
        config = {
            "whitelist": ["django", "requests"],
            "blacklist": ["old-package"],
            "exclude_pre_release": True,
            "min_version": {"django": "3.0.0"},
            "max_version": {"django": "4.2.0"}
        }
    """
    whitelist = config.get("whitelist")
    if whitelist is not None:
        whitelist = set(whitelist)

    return PackageFilter(
        whitelist=whitelist,
        blacklist=set(config.get("blacklist", [])),
        exclude_pre_release=config.get("exclude_pre_release", True),
        min_version=config.get("min_version", {}),
        max_version=config.get("max_version", {}),
    )


def combine_filters(*filters: PackageFilter) -> PackageFilter:
    """
    Combine multiple filters into a single filter.

    Combines whitelists (intersection), blacklists (union), and version
    constraints (most restrictive).

    Args:
        *filters: PackageFilter instances to combine

    Returns:
        Combined PackageFilter
    """
    if not filters:
        return PackageFilter()

    # Combine whitelists (intersection if any exist)
    whitelists = [f.whitelist for f in filters if f.whitelist is not None]
    combined_whitelist = None
    if whitelists:
        combined_whitelist = set.intersection(*whitelists)

    # Combine blacklists (union)
    combined_blacklist = set().union(*(f.blacklist for f in filters))

    # Combine exclude_pre_release (any True means True)
    exclude_pre = any(f.exclude_pre_release for f in filters)

    # Combine min_version (take maximum)
    combined_min: dict[str, str] = {}
    for f in filters:
        for pkg, ver in f.min_version.items():
            if pkg not in combined_min:
                combined_min[pkg] = ver
            else:
                try:
                    current = parse_version(combined_min[pkg])
                    new = parse_version(ver)
                    if new > current:
                        combined_min[pkg] = ver
                except InvalidVersion:
                    pass

    # Combine max_version (take minimum)
    combined_max: dict[str, str] = {}
    for f in filters:
        for pkg, ver in f.max_version.items():
            if pkg not in combined_max:
                combined_max[pkg] = ver
            else:
                try:
                    current = parse_version(combined_max[pkg])
                    new = parse_version(ver)
                    if new < current:
                        combined_max[pkg] = ver
                except InvalidVersion:
                    pass

    return PackageFilter(
        whitelist=combined_whitelist,
        blacklist=combined_blacklist,
        exclude_pre_release=exclude_pre,
        min_version=combined_min,
        max_version=combined_max,
    )
