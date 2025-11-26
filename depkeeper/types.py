"""
Type definitions and protocols for depkeeper.

Provides type aliases, TypedDicts, and Protocols used throughout the codebase
for dependency injection, stronger type checking, and better documentation.
"""

from __future__ import annotations

from typing import (
    Any,
    Dict,
    List,
    Protocol,
    TypedDict,
    Literal,
    Optional,
    Tuple,
)


# =============================================================================
# Basic Type Aliases
# =============================================================================

PackageName = str
Version = str

# (operator, version) e.g. (">=", "1.2.0")
Specifier = Tuple[str, str]
VersionSpecifiers = List[Specifier]


# =============================================================================
# Strategy & Logging Literals
# =============================================================================

UpdateStrategyType = Literal["conservative", "moderate", "aggressive", "custom"]

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


# =============================================================================
# Configuration TypedDicts
# =============================================================================


class CacheConfig(TypedDict, total=False):
    """Cache configuration options."""

    ttl: int
    directory: str
    enabled: bool
    max_size: int


class HTTPConfig(TypedDict, total=False):
    """HTTP client configuration."""

    timeout: int
    max_retries: int
    concurrent_requests: int
    user_agent: str
    verify_ssl: bool


class UpdateConfig(TypedDict, total=False):
    """Update logic configuration."""

    strategy: UpdateStrategyType
    include_pre_release: bool
    dry_run: bool
    create_backup: bool
    auto_confirm: bool


class SecurityConfig(TypedDict, total=False):
    """Security scanning configuration."""

    enabled: bool
    fail_on_critical: bool
    fail_on_high: bool
    ignore_ids: List[str]


class PyPIConfig(TypedDict, total=False):
    """PyPI index configuration."""

    index_url: str
    extra_index_urls: List[str]
    trusted_hosts: List[str]


class DepKeeperConfig(TypedDict, total=False):
    """Main combined configuration."""

    cache: CacheConfig
    http: HTTPConfig
    update: UpdateConfig
    security: SecurityConfig
    pypi: PyPIConfig
    log_level: LogLevel
    color: bool


# =============================================================================
# Protocols for Dependency Injection
# =============================================================================


class ParserProtocol(Protocol):
    """Protocol for requirement parsers."""

    def parse_file(self, path: str) -> List[Any]:
        """Parse a requirements file."""
        ...

    def parse_string(self, content: str) -> List[Any]:
        """Parse requirements from a multi-line string."""
        ...

    def parse_line(self, line: str, line_number: int) -> Any:
        """Parse a single line entry."""
        ...


class CheckerProtocol(Protocol):
    """Protocol for version checkers."""

    async def check_version(self, package_name: PackageName) -> Dict[str, Any]:
        """Return available versions & metadata."""
        ...

    async def get_latest_version(self, package_name: PackageName) -> Version:
        """Return the latest stable version."""
        ...


class UpdaterProtocol(Protocol):
    """Protocol for update engines."""

    def update(
        self,
        requirements: List[Any],
        strategy: UpdateStrategyType,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Apply updates to a list of parsed requirements."""
        ...

    def create_backup(self, file_path: str) -> str:
        """Create a backup before modifying the file."""
        ...


class ResolverProtocol(Protocol):
    """Protocol for dependency resolvers."""

    def resolve(self, requirements: List[Any]) -> Dict[str, Any]:
        """Resolve all dependencies recursively."""
        ...

    def check_conflicts(self, requirements: List[Any]) -> List[Any]:
        """Return a list of detected conflicts."""
        ...


class CacheProtocol(Protocol):
    """Protocol for cache backends."""

    def get(self, key: str) -> Any:
        """Retrieve an item from cache."""
        ...

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Store an item in cache."""
        ...

    def delete(self, key: str) -> None:
        """Remove an item from the cache."""
        ...

    def clear(self) -> None:
        """Clear all cache entries."""
        ...


# =============================================================================
# Results TypedDicts
# =============================================================================


class ParseResult(TypedDict):
    """Result of a parsing operation."""

    requirements: List[Any]
    errors: List[Dict[str, Any]]
    warnings: List[Dict[str, Any]]
    file_path: str


class UpdateResult(TypedDict):
    """Result of an update operation."""

    success: bool
    updated_packages: Dict[PackageName, Tuple[Version, Version]]
    failed_packages: Dict[PackageName, str]
    conflicts: List[Dict[str, Any]]
    backup_path: Optional[str]
    duration: float


class CheckResult(TypedDict):
    """Version check result."""

    package_name: PackageName
    current_version: Optional[Version]
    latest_version: Version
    available_versions: List[Version]
    has_update: bool
    metadata: Dict[str, Any]


class SecurityResult(TypedDict):
    """Security scan result."""

    vulnerabilities: List[Dict[str, Any]]
    total_packages: int
    vulnerable_packages: int
    severity_counts: Dict[str, int]
    timestamp: str


# =============================================================================
# Metadata TypedDicts
# =============================================================================


class PackageMetadata(TypedDict, total=False):
    """Metadata fetched from a package index."""

    name: PackageName
    version: Version
    summary: str
    author: str
    license: str
    home_page: str
    requires_python: str
    requires_dist: List[str]
    project_urls: Dict[str, str]
    upload_time: str


class VulnerabilityInfo(TypedDict):
    """Information on a discovered vulnerability."""

    id: str
    package_name: PackageName
    affected_versions: List[Version]
    fixed_versions: List[Version]
    severity: str
    cve_id: Optional[str]
    description: str
    references: List[str]
