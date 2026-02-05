"""Dependency analysis and conflict resolution for depkeeper.

This module owns two responsibilities:

1. **Cross-conflict detection** — given a proposed set of package versions
   (the *update set*), discover pairs where package A's dependency on B is
   incompatible with the version of B that is itself proposed.
2. **Iterative resolution** — attempt to repair each conflict by first
   trying to downgrade the *source* package (A) to a version whose
   requirement on B is satisfied, and falling back to constraining the
   *target* package (B) when no such source version exists.

All network I/O is routed through the shared :class:`~depkeeper.core.data_store.PyPIDataStore`
so that package metadata is fetched at most once per process.

Typical usage::

    from depkeeper.utils.http import HTTPClient
    from depkeeper.core.data_store import PyPIDataStore
    from depkeeper.core.dependency_analyzer import DependencyAnalyzer

    async with HTTPClient() as http:
        store    = PyPIDataStore(http)
        analyzer = DependencyAnalyzer(data_store=store)
        result   = await analyzer.resolve_and_annotate_conflicts(packages)

        # See exactly what was decided for each package:
        for pkg_name, info in result.resolved_versions.items():
            print(f"{pkg_name}: {info.original} → {info.resolved} ({info.status})")
"""

from __future__ import annotations

import asyncio
from enum import Enum
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from packaging.version import parse, InvalidVersion
from packaging.specifiers import SpecifierSet, InvalidSpecifier
from packaging.requirements import Requirement as PkgRequirement, InvalidRequirement

from depkeeper.models.package import Package
from depkeeper.utils.logger import get_logger
from depkeeper.core.data_store import PyPIDataStore
from depkeeper.models.conflict import Conflict, ConflictSet

logger = get_logger("dependency_analyzer")

# Public API
__all__ = [
    "DependencyAnalyzer",
    "ResolutionResult",
    "PackageResolution",
    "ResolutionStatus",
]

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

# Maximum number of resolution passes before giving up.
_MAX_RESOLUTION_ITERATIONS: int = 100

# How many candidate source versions to evaluate before stopping the search.
# Keeps the resolver fast for packages with hundreds of releases.
_MAX_SOURCE_CANDIDATES: int = 50

# How many target-major versions to scan when checking feasibility.
_MAX_TARGET_SCAN: int = 50


# ---------------------------------------------------------------------------
# Resolution result models
# ---------------------------------------------------------------------------


class ResolutionStatus(Enum):
    """Outcome of version resolution for a single package."""

    # Original recommendation was conflict-free
    KEPT_RECOMMENDED = "kept_recommended"
    UPGRADED = "upgraded"  # Successfully upgraded to a newer version
    DOWNGRADED = "downgraded"  # Had to downgrade due to conflicts
    KEPT_CURRENT = "kept_current"  # No safe upgrade found; stayed at current
    # Version was constrained by another package's requirements
    CONSTRAINED = "constrained"


@dataclass
class PackageResolution:
    """Resolution details for a single package.

    Attributes:
        name: Package name (normalized).
        original: Version that was initially proposed (from recommended_version
            or current_version).
        resolved: Final version chosen after conflict resolution.
        status: Why this version was chosen.
        conflicts: List of conflicts affecting this package (empty if none).
        compatible_alternative: Best alternative version that satisfies all
            conflicts, or None if no alternative exists.
    """

    name: str
    original: Optional[str]
    resolved: Optional[str]
    status: ResolutionStatus
    conflicts: List[Conflict]
    compatible_alternative: Optional[str] = None

    def was_changed(self) -> bool:
        """Return True if resolved version differs from original."""
        return self.original != self.resolved

    def has_conflicts(self) -> bool:
        """Return True if this package has unresolved conflicts."""
        return len(self.conflicts) > 0


@dataclass
class ResolutionResult:
    """Complete result of dependency conflict resolution.

    Attributes:
        resolved_versions: Map of package name → resolution details.
        total_packages: Total number of packages analyzed.
        packages_with_conflicts: Number of packages that have conflicts.
        iterations_used: How many resolution iterations were performed.
        converged: Whether resolution reached a stable state (True) or
            hit the iteration limit (False).
    """

    resolved_versions: Dict[str, PackageResolution]
    total_packages: int
    packages_with_conflicts: int
    iterations_used: int
    converged: bool

    def get_changed_packages(self) -> List[PackageResolution]:
        """Return packages whose resolved version differs from original.

        Returns:
            List of PackageResolution objects where version changed.

        Example::
            >>> for pkg in result.get_changed_packages():
            ...     print(f"{pkg.name}: {pkg.original} → {pkg.resolved}")
        """
        return [r for r in self.resolved_versions.values() if r.was_changed()]

    def get_conflicts(self) -> List[PackageResolution]:
        """Return packages that have unresolved conflicts.

        Returns:
            List of PackageResolution objects with conflicts.
        """
        return [r for r in self.resolved_versions.values() if r.has_conflicts()]

    def summary(self) -> str:
        """Generate a human-readable summary of resolution results.

        Returns:
            Multi-line summary string.

        Example::
            >>> print(result.summary())
            Resolution Summary:
            ==================
            Total packages: 15
            Packages with conflicts: 2
            Packages changed: 3
            Converged: Yes (5 iterations)
            ...
        """
        lines = [
            "Resolution Summary:",
            "=" * 50,
            f"Total packages: {self.total_packages}",
            f"Packages with conflicts: {self.packages_with_conflicts}",
            f"Packages changed: {len(self.get_changed_packages())}",
            f"Converged: {'Yes' if self.converged else 'No'} ({self.iterations_used} iterations)",
            "",
        ]

        if self.packages_with_conflicts > 0:
            lines.append("Packages with conflicts:")
            for pkg in self.get_conflicts():
                lines.append(f"  • {pkg.name}: {pkg.original} → {pkg.resolved}")
                for conflict in pkg.conflicts:
                    lines.append(
                        f"    - {conflict.source_package} requires {conflict.required_spec}"
                    )
                if pkg.compatible_alternative:
                    lines.append(
                        f"    Compatible alternative: {pkg.compatible_alternative}"
                    )
            lines.append("")

        changed = self.get_changed_packages()
        if changed:
            lines.append("Version changes:")
            for pkg in changed:
                lines.append(
                    f"  • {pkg.name}: {pkg.original} → {pkg.resolved} ({pkg.status.value})"
                )

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize(name: str) -> str:
    """Normalise a package name to lower-case with hyphens.

    Matches the canonicalisation rule used by PyPI so that
    ``"My_Package"`` and ``"my-package"`` map to the same key.

    Args:
        name: Raw package name in any casing / separator style.

    Returns:
        Canonical form, e.g. ``"my-package"``.

    Example::

        >>> _normalize("Flask_Login")
        'flask-login'
    """
    return name.lower().replace("_", "-")


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class DependencyAnalyzer:
    """Detect and resolve version conflicts across a dependency graph.

    The analyzer works exclusively through a :class:`PyPIDataStore`
    instance, which guarantees that every ``/pypi/{pkg}/json`` call is
    made at most once.  All public entry points are ``async``.

    Args:
        data_store: Shared PyPI data store.  **Required** — the class has
            no independent HTTP path.
        concurrent_limit: Upper bound on in-flight PyPI fetches.
            Forwarded to the internal semaphore.  Defaults to ``10``.

    Raises:
        TypeError: If *data_store* is ``None``.

    Example::

        >>> async with HTTPClient() as http:
        ...     store    = PyPIDataStore(http)
        ...     analyzer = DependencyAnalyzer(data_store=store)
        ...     result   = await analyzer.resolve_and_annotate_conflicts(pkgs)
        ...     print(result.summary())
    """

    def __init__(
        self,
        data_store: PyPIDataStore,
        concurrent_limit: int = 10,
    ) -> None:
        if data_store is None:
            raise TypeError(
                "data_store must not be None; pass a PyPIDataStore instance"
            )

        self.data_store: PyPIDataStore = data_store
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(concurrent_limit)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def resolve_and_annotate_conflicts(
        self,
        packages: List[Package],
    ) -> ResolutionResult:
        """Resolve conflicts and write results back into each :class:`Package`.

        Algorithm outline:

        1. Build an *update set* mapping each package name to its
           proposed version (``recommended_version`` if available,
           otherwise ``current_version``).
        2. Prefetch metadata for every package in one concurrent burst.
        3. Loop up to :data:`_MAX_RESOLUTION_ITERATIONS` times:

           a. Scan for cross-conflicts in the current update set.
           b. If none remain, stop — the set is self-consistent.
           c. Attempt resolution (downgrade source, then constrain
              target).  Break early when no progress is made.

        4. Annotate each :class:`Package` with its final version and any
           unresolved :class:`Conflict` objects.
        5. Return a :class:`ResolutionResult` with complete details.

        Args:
            packages: Mutable list of :class:`Package` objects.  Each
                object is updated in place with the resolved version and
                conflict metadata.

        Returns:
            :class:`ResolutionResult` containing the final version for each
            package, conflict details, and resolution statistics.

        Example::

            >>> result = await analyzer.resolve_and_annotate_conflicts(pkgs)
            >>> print(result.summary())
            >>> for pkg_name, info in result.resolved_versions.items():
            ...     if info.was_changed():
            ...         print(f"{pkg_name}: {info.original} → {info.resolved}")
        """
        # ── initialise update set ─────────────────────────────────────
        pkg_lookup: Dict[str, Package] = {pkg.name: pkg for pkg in packages}
        update_set: Dict[str, Optional[str]] = {}
        conflict_tracking: Dict[str, List[Conflict]] = {}

        # Track original proposed versions for comparison
        original_versions: Dict[str, Optional[str]] = {}

        for pkg in packages:
            # Prefer the already-computed recommendation; fall back to current
            proposed = pkg.recommended_version or pkg.current_version
            update_set[pkg.name] = proposed
            original_versions[pkg.name] = proposed

        # ── warm the cache in one round-trip ──────────────────────────
        await self.data_store.prefetch_packages([pkg.name for pkg in packages])

        # ── iterative conflict resolution ─────────────────────────────
        iterations_used = 0
        converged = False

        for iteration in range(_MAX_RESOLUTION_ITERATIONS):
            iterations_used = iteration + 1
            cross_conflicts = await self._find_cross_conflicts(packages, update_set)

            if not cross_conflicts:
                logger.debug(
                    "Update set is conflict-free after %d iteration(s)", iteration
                )
                converged = True
                break

            # Record every conflict for later annotation (with deduplication)
            for conflict in cross_conflicts:
                conflicts_list = conflict_tracking.setdefault(
                    conflict.target_package, []
                )
                # Deduplicate using conflict signature
                conflict_key = (
                    conflict.source_package,
                    conflict.source_version,
                    conflict.required_spec,
                    conflict.conflicting_version,
                )
                existing_keys = {
                    (
                        c.source_package,
                        c.source_version,
                        c.required_spec,
                        c.conflicting_version,
                    )
                    for c in conflicts_list
                }
                if conflict_key not in existing_keys:
                    conflicts_list.append(conflict)

            resolved_any = await self._resolve_by_downgrading_source(
                pkg_lookup, update_set, cross_conflicts
            )

            if not resolved_any:
                # No version change was made → further iterations would
                # produce the exact same conflict set; stop early.
                logger.warning(
                    "Conflict resolution stalled after %d iteration(s)",
                    iteration + 1,
                )
                break
        else:
            # for/else: exhausted all iterations without breaking
            logger.warning(
                "Conflict resolution did not converge within %d iterations",
                _MAX_RESOLUTION_ITERATIONS,
            )

        # ── annotate packages and build resolution map ────────────────
        resolved_versions: Dict[str, PackageResolution] = {}
        packages_with_conflicts = 0

        for pkg in packages:
            original = original_versions.get(pkg.name)
            resolved = update_set.get(pkg.name)
            conflicts = conflict_tracking.get(pkg.name, [])

            # Determine resolution status
            status = self._determine_status(pkg, original, resolved, conflicts)

            # Find compatible alternative if there are conflicts
            compatible_alt = None
            if conflicts:
                available = self.data_store.get_versions(pkg.name)
                conflict_set = ConflictSet(pkg.name)
                for c in conflicts:
                    conflict_set.add_conflict(c)
                compatible_alt = self.find_compatible_version(
                    conflict_set, available, pkg.current_version
                )
                packages_with_conflicts += 1

            # Update the Package object itself
            if resolved and resolved != pkg.recommended_version:
                # Only update recommended_version if resolution changed it
                pkg.recommended_version = (
                    resolved if resolved != pkg.current_version else pkg.current_version
                )

            if conflicts:
                pkg.set_conflicts(conflicts, resolved_version=compatible_alt)

            # Store resolution details
            resolved_versions[pkg.name] = PackageResolution(
                name=pkg.name,
                original=original,
                resolved=resolved,
                status=status,
                conflicts=conflicts,
                compatible_alternative=compatible_alt,
            )

        return ResolutionResult(
            resolved_versions=resolved_versions,
            total_packages=len(packages),
            packages_with_conflicts=packages_with_conflicts,
            iterations_used=iterations_used,
            converged=converged,
        )

    def _determine_status(
        self,
        pkg: Package,
        original: Optional[str],
        resolved: Optional[str],
        conflicts: List[Conflict],
    ) -> ResolutionStatus:
        """Determine why a particular version was chosen.

        Args:
            pkg: Package being analyzed.
            original: Originally proposed version.
            resolved: Final resolved version.
            conflicts: Conflicts affecting this package.

        Returns:
            ResolutionStatus enum indicating the outcome.
        """
        if original == resolved:
            # No change made during resolution
            return ResolutionStatus.KEPT_RECOMMENDED

        if resolved == pkg.current_version:
            # Reverted to current due to conflicts
            return ResolutionStatus.KEPT_CURRENT

        # Version changed - determine if upgrade or downgrade
        if original and resolved:
            try:
                original_parsed = parse(original)
                resolved_parsed = parse(resolved)

                if resolved_parsed > original_parsed:
                    return ResolutionStatus.UPGRADED
                elif resolved_parsed < original_parsed:
                    # Was downgraded due to conflicts
                    return (
                        ResolutionStatus.DOWNGRADED
                        if conflicts
                        else ResolutionStatus.CONSTRAINED
                    )
            except InvalidVersion:
                pass

        # Default: version was constrained by dependencies
        return ResolutionStatus.CONSTRAINED

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------

    async def _find_cross_conflicts(
        self,
        packages: List[Package],
        update_set: Dict[str, Optional[str]],
    ) -> List[Conflict]:
        """Scan the update set for pairwise version conflicts.

        For every package *P* at its proposed version *V*, fetch *V*'s
        dependency list.  For each dependency *D* that also appears in the
        update set, check whether the proposed version of *D* satisfies
        *P*'s requirement specifier.  If not, emit a :class:`Conflict`.

        Args:
            packages: Full package list (provides iteration order).
            update_set: Current name → proposed-version mapping.

        Returns:
            A (possibly empty) list of detected conflicts.
        """
        cross_conflicts: List[Conflict] = []

        for pkg in packages:
            proposed_version = update_set.get(pkg.name)
            if not proposed_version:
                continue

            deps = await self.data_store.get_version_dependencies(
                pkg.name, proposed_version
            )

            for dep_spec in deps:
                try:
                    req = PkgRequirement(dep_spec)
                except (InvalidVersion, InvalidRequirement):
                    # Malformed specifier in upstream metadata — skip
                    logger.debug(
                        "Unparseable requirement %r in %s==%s",
                        dep_spec,
                        pkg.name,
                        proposed_version,
                    )
                    continue

                req_name: str = _normalize(req.name)

                # Only interesting when the dependency is itself in our update set
                target_version = update_set.get(req_name)
                if (
                    target_version
                    and req.specifier
                    and target_version not in req.specifier
                ):
                    cross_conflicts.append(
                        Conflict(
                            source_package=pkg.name,
                            target_package=req_name,
                            required_spec=str(req.specifier),
                            conflicting_version=target_version,
                            source_version=proposed_version,
                        )
                    )

        return cross_conflicts

    # ------------------------------------------------------------------
    # Resolution strategies
    # ------------------------------------------------------------------

    async def _resolve_by_downgrading_source(
        self,
        pkg_lookup: Dict[str, Package],
        update_set: Dict[str, Optional[str]],
        cross_conflicts: List[Conflict],
    ) -> bool:
        """Attempt to eliminate conflicts by adjusting package versions.

        Two strategies are tried in order for each unique *source* package
        that appears in *cross_conflicts*:

        1. **Downgrade source** — find the highest version of the source
           whose requirement on the target is satisfied by the target's
           proposed version.
        2. **Constrain target** — find the highest version of the target
           (within its current major) that satisfies the source's
           requirement, and revert the source to its current version.

        If neither strategy produces a viable version, both packages are
        reverted to their *current* (installed) versions and a warning is
        logged.

        Args:
            pkg_lookup: Name → :class:`Package` mapping for quick access.
            update_set: Mutable name → proposed-version mapping; updated
                in place when a resolution is found.
            cross_conflicts: Conflicts to process.

        Returns:
            ``True`` when at least one version in *update_set* was changed
            during this call.
        """
        resolved_any: bool = False
        # Track which source packages have already been handled so that
        # multiple conflicts with the same source are not processed twice.
        processed_sources: Set[str] = set()

        for conflict in cross_conflicts:
            source_name: str = conflict.source_package
            target_name: str = conflict.target_package

            if source_name in processed_sources:
                continue

            source_pkg = pkg_lookup.get(source_name)
            target_pkg = pkg_lookup.get(target_name)
            if not source_pkg or not target_pkg:
                continue

            target_major: Optional[int] = _get_major_version(target_pkg.current_version)
            target_proposed: Optional[str] = update_set.get(target_name)

            logger.debug(
                "Attempting to resolve: %s==%s requires %s%s, "
                "target constrained to major %s",
                source_name,
                conflict.source_version,
                target_name,
                conflict.required_spec,
                target_major,
            )

            # ── strategy 1: downgrade source ──────────────────────────
            compatible_source = await self._find_compatible_source_version(
                source_pkg=source_pkg,
                target_name=target_name,
                target_proposed_version=target_proposed,
                target_major=target_major,
            )

            if compatible_source and compatible_source != update_set.get(source_name):
                logger.info(
                    "Resolved: %s %s → %s (compatible with %s==%s)",
                    source_name,
                    update_set.get(source_name),
                    compatible_source,
                    target_name,
                    target_proposed,
                )
                update_set[source_name] = compatible_source
                resolved_any = True
                processed_sources.add(source_name)
                continue  # move to next conflict

            # ── strategy 2: constrain target ──────────────────────────
            logger.debug(
                "No compatible %s version found; trying to constrain %s",
                source_name,
                target_name,
            )

            constrained_target = await self._find_constrained_target_version(
                target_name=target_name,
                target_major=target_major,
                required_spec=conflict.required_spec,
            )

            if constrained_target and constrained_target != target_proposed:
                logger.info(
                    "Resolved: constraining %s to %s (required by %s)",
                    target_name,
                    constrained_target,
                    source_name,
                )
                update_set[target_name] = constrained_target
                # Revert source to current since we gave up upgrading it
                if source_pkg.current_version:
                    update_set[source_name] = source_pkg.current_version
                resolved_any = True
            else:
                # ── fallback: revert both to current ──────────────────
                logger.warning(
                    "No compatible version found for %s ↔ %s; reverting both",
                    source_name,
                    target_name,
                )
                if source_pkg.current_version:
                    update_set[source_name] = source_pkg.current_version
                if target_pkg.current_version:
                    update_set[target_name] = target_pkg.current_version

            processed_sources.add(source_name)

        return resolved_any

    # ------------------------------------------------------------------
    # Version search helpers
    # ------------------------------------------------------------------

    async def _find_compatible_source_version(
        self,
        source_pkg: Package,
        target_name: str,
        target_proposed_version: Optional[str],
        target_major: Optional[int],
    ) -> Optional[str]:
        """Walk the source package's versions (newest first) for compatibility.

        A candidate version is *compatible* when it either has no
        dependency on *target_name* at all, or its dependency specifier is
        satisfied by *target_proposed_version* (or, as a last resort, by
        any stable version of the target within *target_major*).

        The search is bounded by :data:`_MAX_SOURCE_CANDIDATES` to avoid
        scanning packages with very long release histories.  Pre-releases
        and versions outside the source's current major are skipped but do
        **not** count against the candidate budget.

        Args:
            source_pkg: The source :class:`Package` being adjusted.
            target_name: Normalised name of the dependency that caused the
                conflict.
            target_proposed_version: The target's current entry in the
                update set (may be ``None``).
            target_major: Major version the target must stay within (or
                ``None`` to allow any major).

        Returns:
            The highest compatible source version string, or ``None`` when
            no candidate satisfies the constraints.

        Example::

            >>> v = await analyzer._find_compatible_source_version(
            ...     source_pkg=flask_pkg,
            ...     target_name="werkzeug",
            ...     target_proposed_version="3.0.1",
            ...     target_major=3,
            ... )
            >>> v
            '3.1.0'
        """
        source_name: str = source_pkg.name
        source_major: Optional[int] = _get_major_version(source_pkg.current_version)
        current_python: str = PyPIDataStore.get_current_python_version()

        available: List[str] = (
            await self.data_store.get_package_data(source_name)
        ).all_versions

        candidates_checked: int = 0

        for version_str in available:
            # ── hard budget on evaluated candidates ────────────────────
            if candidates_checked >= _MAX_SOURCE_CANDIDATES:
                break

            try:
                parsed = parse(version_str)
            except InvalidVersion:
                continue

            # Pre-releases and cross-major jumps are filtered but do NOT
            # consume from the candidate budget.
            if parsed.is_prerelease:
                continue
            if source_major is not None:
                version_major = parsed.release[0] if parsed.release else 0
                if version_major != source_major:
                    continue

            # Python-compatibility gate (cache-only, no I/O)
            if not self.data_store.is_python_compatible(
                source_name, version_str, current_python
            ):
                logger.debug(
                    "%s==%s incompatible with Python %s; skipping",
                    source_name,
                    version_str,
                    current_python,
                )
                continue

            # This version passed all filters — count it
            candidates_checked += 1

            # ── fetch deps and locate the requirement on target ────────
            deps = await self.data_store.get_version_dependencies(
                source_name, version_str
            )
            target_spec: Optional[SpecifierSet] = _extract_specifier_for(
                deps, target_name
            )

            # No dependency on target at all → trivially compatible
            if target_spec is None:
                logger.debug(
                    "%s==%s has no dependency on %s → compatible",
                    source_name,
                    version_str,
                    target_name,
                )
                return version_str

            # Proposed target version satisfies the specifier directly
            if target_proposed_version and target_proposed_version in target_spec:
                logger.debug(
                    "%s==%s requires %s%s; satisfied by %s==%s",
                    source_name,
                    version_str,
                    target_name,
                    target_spec,
                    target_name,
                    target_proposed_version,
                )
                return version_str

        return None

    async def _find_constrained_target_version(
        self,
        target_name: str,
        target_major: Optional[int],
        required_spec: str,
    ) -> Optional[str]:
        """Find the highest target version that satisfies *required_spec*.

        Only stable versions within *target_major* (when provided) are
        considered.  Returns ``None`` when the specifier itself is
        unparseable or no matching version exists.

        Args:
            target_name: Package whose versions are being scanned.
            target_major: If not ``None``, only versions sharing this
                major number are considered.
            required_spec: PEP-440 specifier string, e.g. ``">=2.0,<3"``.

        Returns:
            A version string, or ``None``.

        Example::

            >>> v = await analyzer._find_constrained_target_version(
            ...     target_name="werkzeug",
            ...     target_major=2,
            ...     required_spec=">=2.0,<3",
            ... )
            >>> v
            '2.3.7'
        """
        try:
            spec = SpecifierSet(required_spec)
        except InvalidSpecifier:
            logger.debug("Unparseable specifier %r for %s", required_spec, target_name)
            return None

        available: List[str] = (
            await self.data_store.get_package_data(target_name)
        ).all_versions

        for version_str in available:  # already sorted descending
            try:
                parsed = parse(version_str)
            except InvalidVersion:
                continue

            if parsed.is_prerelease:
                continue

            if target_major is not None:
                version_major = parsed.release[0] if parsed.release else 0
                if version_major != target_major:
                    continue

            if version_str in spec:
                return version_str  # first match is the highest

        return None

    # ------------------------------------------------------------------
    # Compatibility query
    # ------------------------------------------------------------------

    def find_compatible_version(
        self,
        conflict_set: ConflictSet,
        available_versions: List[str],
        min_version: Optional[str] = None,
    ) -> Optional[str]:
        """Pick the highest version from *available_versions* that satisfies
        every constraint in *conflict_set* and is at least *min_version*.

        Args:
            conflict_set: Aggregated conflicts for a single package.
            available_versions: Candidate versions (any order; the
                conflict_set itself determines compatibility).
            min_version: If provided, discard any candidate that parses
                below this version.  Typically the currently-installed
                version.

        Returns:
            A compatible version string, or ``None`` when no candidate
            passes all filters.

        Example::

            >>> v = analyzer.find_compatible_version(cs, ["2.1", "2.0", "1.9"], "2.0")
            >>> v
            '2.1'
        """
        if not conflict_set.has_conflicts():
            return None

        compatible: Optional[str] = conflict_set.get_max_compatible_version(
            available_versions
        )

        # Enforce the floor
        if compatible and min_version:
            try:
                if parse(compatible) < parse(min_version):
                    return None
            except InvalidVersion:
                return None

        return compatible

    # ------------------------------------------------------------------
    # Small utilities (private / static)
    # ------------------------------------------------------------------

    @staticmethod
    def _get_major_version(version: Optional[str]) -> Optional[int]:
        """Extract the major component from a version string.

        This is a thin, forgiving wrapper around ``packaging.version.parse``
        that returns ``None`` on any failure instead of raising.

        Args:
            version: Version string, or ``None``.

        Returns:
            The major version integer, or ``None``.

        Example::

            >>> DependencyAnalyzer._get_major_version("3.11.2")
            3
            >>> DependencyAnalyzer._get_major_version(None)
        """
        if not version:
            return None
        try:
            parsed = parse(version)
            return parsed.release[0] if parsed.release else None
        except InvalidVersion:
            return None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _get_major_version(version: Optional[str]) -> Optional[int]:
    """Module-level alias so resolution helpers can call without an instance.

    See :pymeth:`DependencyAnalyzer._get_major_version` for full docs.
    """
    return DependencyAnalyzer._get_major_version(version)


def _extract_specifier_for(deps: List[str], target_name: str) -> Optional[SpecifierSet]:
    """Scan a dependency list and return the specifier that targets *target_name*.

    Parsing failures for individual entries are logged at DEBUG and
    skipped so that one bad line does not prevent the rest from being
    checked.

    Args:
        deps: PEP-508 dependency strings (extras and markers already
            stripped by the data store).
        target_name: Normalised package name to search for.

    Returns:
        The :class:`SpecifierSet` for *target_name*, or ``None`` when the
        target does not appear in *deps*.

    Example::

        >>> _extract_specifier_for(["click>=8.0", "jinja2>=3.0"], "jinja2")
        <SpecifierSet('>=3.0')>
        >>> _extract_specifier_for(["click>=8.0"], "jinja2") is None
        True
    """
    normalised_target: str = _normalize(target_name)

    for dep in deps:
        try:
            req = PkgRequirement(dep)
        except (InvalidVersion, InvalidRequirement):
            logger.debug("Skipping unparseable dependency: %r", dep)
            continue

        if _normalize(req.name) == normalised_target:
            # may be an empty SpecifierSet (matches everything)
            return req.specifier

    return None
