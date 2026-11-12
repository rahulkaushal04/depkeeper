"""Dependency conflict analysis with strict major version boundaries.

Resolves cross-package version conflicts without ever moving a package into a
different major version. When no compatible version exists in the current
major, the package stays on its current version; packages whose PyPI metadata
cannot be fetched degrade to the same fallback instead of aborting the run.
Every conflict is reported, including unresolved ones.

All network I/O goes through the shared `PyPIDataStore`.

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

from enum import Enum
from functools import lru_cache
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Set, Tuple

from packaging.version import parse, InvalidVersion
from packaging.specifiers import SpecifierSet, InvalidSpecifier
from packaging.requirements import Requirement as PkgRequirement, InvalidRequirement

from depkeeper.exceptions import NetworkError
from depkeeper.models.package import Package
from depkeeper.utils.logger import get_logger
from depkeeper.utils.naming import normalize_package_name
from depkeeper.utils.version_utils import parse_version_lenient, specs_allow_version
from depkeeper.core.data_store import PyPIDataStore, PyPIPackageData
from depkeeper.models.conflict import Conflict, ConflictSet

if TYPE_CHECKING:
    from depkeeper.core.checker import VersionChecker

logger = get_logger("dependency_analyzer")

__all__ = [
    "DependencyAnalyzer",
    "ResolutionResult",
    "PackageResolution",
    "ResolutionStatus",
]

_MAX_RESOLUTION_ITERATIONS: int = 100

# Bounds the search for packages with hundreds of releases.
_MAX_SOURCE_CANDIDATES: int = 50


class ResolutionStatus(Enum):
    """Outcome of version resolution for a single package."""

    KEPT_RECOMMENDED = "kept_recommended"
    UPGRADED = "upgraded"
    DOWNGRADED = "downgraded"
    KEPT_CURRENT = "kept_current"
    CONSTRAINED = "constrained"


@dataclass
class PackageResolution:
    """Resolution details for a single package.

    Attributes:
        name: Package name (normalized).
        original: Version that was initially proposed (from recommended_version
            or current_version).
        resolved: Final version chosen after conflict resolution. This is the
            version that is applied — `Package.recommended_version` is
            set to exactly this value.
        status: Why this version was chosen.
        conflicts: Every conflict recorded for this package during resolution,
            including ones a later iteration went on to resolve.
        compatible_alternative: Advisory only. Best version satisfying *all*
            recorded conflicts at once, or None if no such version exists.
            It is adopted into `resolved` only when the resolution loop
            left a conflict unresolved; otherwise it is display data and does
            not affect what gets written.
    """

    name: str
    original: Optional[str]
    resolved: Optional[str]
    status: ResolutionStatus
    conflicts: List[Conflict]
    compatible_alternative: Optional[str] = None

    def was_changed(self) -> bool:
        """Return ``True`` when the resolved version differs from the original."""
        return self.original != self.resolved

    def has_conflicts(self) -> bool:
        """Return ``True`` when any conflict was recorded for this package."""
        return len(self.conflicts) > 0


@dataclass
class ResolutionResult:
    """Complete result of dependency conflict resolution.

    Attributes:
        resolved_versions: Map of package name → resolution details.
        total_packages: Total number of packages analyzed.
        packages_with_conflicts: Number of packages that had a conflict recorded
            at any point, including ones a later iteration resolved.
        packages_unresolved: Number of packages whose conflict is still live in
            the final set. This, not ``packages_with_conflicts``, is what to
            report as "unresolved".
        iterations_used: How many resolution iterations were performed.
        converged: Whether resolution reached a stable state (True) or
            hit the iteration limit (False).
        dependency_lookup_failures: Names of packages whose dependency
            metadata could not be fetched; conflicts involving them could not
            be detected.
    """

    resolved_versions: Dict[str, PackageResolution]
    total_packages: int
    packages_with_conflicts: int
    iterations_used: int
    converged: bool
    dependency_lookup_failures: List[str] = field(default_factory=list)
    packages_unresolved: int = 0

    @property
    def conflict_check_complete(self) -> bool:
        """Whether every dependency lookup succeeded."""
        return not self.dependency_lookup_failures

    def get_changed_packages(self) -> List[PackageResolution]:
        """Return packages whose resolved version differs from the original."""
        return [r for r in self.resolved_versions.values() if r.was_changed()]

    def get_conflicts(self) -> List[PackageResolution]:
        """Return packages that had at least one conflict recorded."""
        return [r for r in self.resolved_versions.values() if r.has_conflicts()]

    def summary(self) -> str:
        """Render a human-readable summary of the resolution run.

        Returns:
            Multi-line summary covering totals, convergence, conflicts and
            every version change.
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


def _normalize(name: str) -> str:
    """Normalize *name* (PEP 503) so upstream metadata matches update set keys."""
    return normalize_package_name(name)


def _get_major_version(version: Optional[str]) -> Optional[int]:
    """Return the major component of *version*, or ``None`` if unavailable."""
    if not version:
        return None
    try:
        parsed = parse(version)
        return parsed.release[0] if parsed.release else None
    except InvalidVersion:
        return None


#: Boundary marker for calver packages: a year/month change is routine, so
#: the candidate search is not restricted to the current leading number.
_UNBOUNDED = -1


def _boundary(
    pkg: Package, checker: Optional["VersionChecker"] = None
) -> Optional[int]:
    """Scheme-aware search boundary: major for semver, unbounded for calver.

    A package the user opted into major upgrades for is unbounded too, so the
    conflict search can reach the same versions the checker may recommend.
    """
    if pkg.versioning == "calver" or (checker and checker.allows_major(pkg.name)):
        return _UNBOUNDED
    return _get_major_version(pkg.current_version)


def _lower_proposal(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """Return the lower of *a* and *b*.

    ``None`` and unparseable values mean "no preference"; the other operand
    wins, and ``None`` is returned only when neither is usable.
    """
    if a is None:
        return b
    if b is None:
        return a

    parsed_a = parse_version_lenient(a)
    parsed_b = parse_version_lenient(b)

    if parsed_a is None:
        return b if parsed_b is not None else a
    if parsed_b is None:
        return a

    return a if parsed_a <= parsed_b else b


def _satisfies(version: Optional[str], required_spec: str) -> bool:
    """Return ``True`` when *version* satisfies *required_spec*.

    Unparseable specifiers and versions count as satisfied so malformed
    upstream metadata cannot veto a version.
    """
    if version is None:
        return True
    try:
        specifier = SpecifierSet(required_spec)
    except InvalidSpecifier:
        return True
    return _specifier_allows(version, specifier)


def _specifier_allows(version: Optional[str], specifier: SpecifierSet) -> bool:
    """Return ``True`` when *version* satisfies an already-parsed *specifier*.

    Like `_satisfies` for a prebuilt `SpecifierSet`. The version is parsed
    explicitly so an unparseable version is never vetoed, and pre-releases
    are accepted (``in`` would reject a pinned pre-release on older
    ``packaging``).
    """
    if version is None:
        return True
    try:
        parsed_version = parse(version)
    except InvalidVersion:
        return True
    return specifier.contains(parsed_version, prereleases=True)


def _compatible_versions(
    data: Optional[PyPIPackageData],
    major: Optional[int],
    retained: Sequence[Tuple[str, str]] = (),
    python_version: Optional[str] = None,
    checker: Optional["VersionChecker"] = None,
    current: Optional[str] = None,
    scheme: str = "semver",
) -> List[str]:
    """Python-compatible versions in *major* that honour *retained*.

    With a *checker*, pre-release policy, hold/``max_update`` and the
    ``min_age`` cooldown are applied as well, so backports and alternatives
    chosen here obey the same rules as the checker's own recommendation.
    """
    if data is None:
        return []
    found = [
        v
        for v in data.get_python_compatible_versions(
            python_version or PyPIDataStore.get_current_python_version(),
            major=None if major == _UNBOUNDED else major,
            include_prereleases=bool(
                checker and checker.include_prereleases(data.name)
            ),
        )
        if specs_allow_version(retained, v)
    ]
    if checker is not None:
        found = checker.restrict_versions(data, found, current, scheme)
    return found


def _satisfies_all(version: Optional[str], conflicts: List[Conflict]) -> bool:
    """Return ``True`` when *version* satisfies every conflict's specifier."""
    return all(_satisfies(version, c.required_spec) for c in conflicts)


def _live_conflicts(
    update_set: Dict[str, Optional[str]],
    target_name: str,
    target_version: Optional[str],
    conflicts: List[Conflict],
) -> List[Conflict]:
    """Return the *conflicts* that the final update set still violates.

    Recorded conflicts accumulate across iterations, including ones a later
    iteration resolved. A conflict is live only while the source is still
    proposed at ``source_version`` and the target's version still fails
    ``required_spec``. Each live requirement appears once, reported against
    *target_version*, in a deterministic order.

    Args:
        update_set: Final name -> proposed-version mapping.
        target_name: Package the conflicts are recorded against.
        target_version: *target_name*'s entry in *update_set*.
        conflicts: Conflicts accumulated for *target_name*.
    """
    by_key: Dict[Tuple[str, Optional[str], str, str], Conflict] = {}

    for conflict in conflicts:
        if update_set.get(conflict.source_package) != conflict.source_version:
            continue
        if _satisfies(target_version, conflict.required_spec):
            continue
        # The same requirement may be recorded against several earlier target
        # versions; report it once, against the version the update set holds.
        by_key.setdefault(
            _violation_key(conflict),
            replace(conflict, conflicting_version=target_version)
            if target_version
            else conflict,
        )

    live = [by_key[k] for k in sorted(by_key, key=lambda k: tuple(x or "" for x in k))]

    if live:
        logger.debug(
            "%s has %d live conflict(s) of %d recorded at %s",
            target_name,
            len(live),
            len(conflicts),
            target_version,
        )

    return live


@lru_cache(maxsize=65536)
def _parse_dependency(dep: str) -> Optional[PkgRequirement]:
    """Parse a PEP 508 string once; ``None`` when it is malformed.

    The same strings are re-read on every pass and for every candidate, and
    parsing dominates the cost of large runs.
    """
    try:
        return PkgRequirement(dep)
    except (InvalidVersion, InvalidRequirement):
        return None


def _violation_key(conflict: Conflict) -> Tuple[str, Optional[str], str, str]:
    """Identify a violated requirement independently of the target's version."""
    return (
        conflict.source_package,
        conflict.source_version,
        conflict.target_package,
        conflict.required_spec,
    )


def _record_conflicts(
    tracking: Dict[str, List[Conflict]], conflicts: Sequence[Conflict]
) -> None:
    """Add *conflicts* to *tracking* (keyed by target), skipping known signatures."""
    for conflict in conflicts:
        recorded = tracking.setdefault(conflict.target_package, [])
        if conflict not in recorded:
            recorded.append(conflict)


class DependencyAnalyzer:
    """Detect and resolve version conflicts within major version boundaries.

    Conflict resolution never moves a package into a different major version,
    so resolving one dependency's requirement cannot silently introduce a
    breaking change elsewhere.

    The analyzer works exclusively through a `PyPIDataStore`
    instance, which guarantees that every ``/pypi/{pkg}/json`` call is
    made at most once. All public entry points are ``async``.

    Args:
        data_store: Shared PyPI data store. **Required** — the class has
            no independent HTTP path.
        concurrent_limit: Accepted for backward compatibility; unused
            (fetch concurrency is bounded by the data store).
        target_python: Python version (e.g. ``"3.9"``) every candidate must
            support. ``None`` (default) uses the running interpreter.
        checker: Optional `VersionChecker`. When given, versions the analyzer
            picks obey its ``min_age`` cooldown, pre-release and per-package
            policy (hold, ``max_update``), so conflict resolution cannot
            bypass them.

    Raises:
        TypeError: If *data_store* is ``None``.
    """

    def __init__(
        self,
        data_store: PyPIDataStore,
        concurrent_limit: int = 10,
        target_python: Optional[str] = None,
        checker: Optional["VersionChecker"] = None,
    ) -> None:
        if data_store is None:
            raise TypeError(
                "data_store must not be None; pass a PyPIDataStore instance"
            )
        self.data_store: PyPIDataStore = data_store
        self.target_python: Optional[str] = target_python
        self.checker: Optional["VersionChecker"] = checker

        # Names whose fetch failed; avoids retrying them on every pass.
        self._unavailable_packages: Set[str] = set()
        # Packages whose dependency lookup failed; reported once per resolution.
        self._dependency_failures: Dict[str, None] = {}

    async def _get_package_data_or_none(self, name: str) -> Optional[PyPIPackageData]:
        """Fetch metadata for *name*, returning ``None`` when unavailable.

        The first failure per name is logged at WARNING and remembered, so
        later passes skip the package instead of retrying.
        """
        normalized = _normalize(name)

        if normalized in self._unavailable_packages:
            return None

        try:
            return await self.data_store.get_package_data(name)
        except NetworkError as exc:
            # PyPIError subclasses NetworkError, so this covers 404 as well.
            self._unavailable_packages.add(normalized)
            logger.warning(
                "PyPI metadata for '%s' is unavailable (%s); "
                "conflict resolution will skip this package",
                name,
                exc,
            )
            return None

    async def _get_dependencies(self, name: str, version: str) -> List[str]:
        """Return the dependencies of ``name==version``; ``[]`` if the lookup fails."""
        try:
            return await self.data_store.get_version_dependencies(name, version)
        except NetworkError as exc:
            logger.debug("Dependencies of %s==%s unavailable: %s", name, version, exc)
            self._dependency_failures.setdefault(name, None)
            return []

    async def _requirements_of(
        self,
        name: str,
        version: str,
        memo: Dict[Tuple[str, str], Dict[str, SpecifierSet]],
    ) -> Dict[str, SpecifierSet]:
        """Map each package ``name==version`` requires to its specifier (memoised)."""
        key = (name, version)
        if key not in memo:
            found: Dict[str, SpecifierSet] = {}
            for dep in await self._get_dependencies(name, version):
                req = _parse_dependency(dep)
                if req is not None:
                    found.setdefault(_normalize(req.name), req.specifier)
            memo[key] = found
        return memo[key]

    def _refresh_recommended_metadata(self, pkg: Package, resolved: str) -> None:
        """Recompute recommendation metadata for *resolved* from cached data only."""
        cached = self.data_store.get_cached_package(pkg.name)
        if cached is None:
            return

        pkg.metadata["recommended_metadata"] = {
            "requires_python": cached.python_requirements.get(resolved),
        }
        pkg.recommended_released = cached.upload_times.get(resolved)
        # Only a withheld version newer than the applied one is still "skipped".
        skipped = parse_version_lenient(pkg.cooldown_skipped)
        chosen = parse_version_lenient(resolved)
        if skipped is None or chosen is None or skipped <= chosen:
            pkg.cooldown_skipped = None

    async def resolve_and_annotate_conflicts(
        self,
        packages: List[Package],
    ) -> ResolutionResult:
        """Resolve cross-package conflicts without crossing major boundaries.

        Outline:

        1. Build an *update set* mapping each package name to its
           proposed version (``recommended_version`` if available,
           otherwise ``current_version``). Recommended versions already
           respect major version boundaries.
        2. Prefetch metadata for every package in one concurrent burst.
        3. Loop up to `_MAX_RESOLUTION_ITERATIONS` times:

           a. Scan for cross-conflicts in the current update set.
           b. If none remain, stop — the set is self-consistent.
           c. Attempt resolution within major version boundaries only:

              - Try to find a compatible source version within its current major
              - If that fails, try to constrain the target within its current major
              - If both fail, revert both packages to their current versions

           d. Break early when no progress is made.

        4. For packages the loop could not fix, adopt the best version that
           satisfies every conflict at once, when one exists.
        5. Annotate each `Package` with its final version and any
           conflicts still live against that final version.
        6. Return a `ResolutionResult` with complete details.

        For every package declared once, ``pkg.recommended_version`` equals
        ``result.resolved_versions[pkg.name].resolved`` afterwards.

        A name declared more than once (e.g. via two ``-r`` includes) is
        resolved per declaration: a name-level adjustment reaches a
        declaration's ``recommended_version`` only when a real conflict was
        recorded for that name. ``resolved_versions`` holds one entry per
        name, so read each `Package.recommended_version` for the
        per-declaration outcome.

        Args:
            packages: Packages, updated in place with the resolved version
                and conflict metadata.

        Returns:
            A `ResolutionResult` with the final version per package, conflict
            details and resolution statistics.
        """
        packages = [pkg for pkg in packages if not (pkg.direct or pkg.not_applicable)]
        pkg_lookup: Dict[str, Package] = {pkg.name: pkg for pkg in packages}
        update_set: Dict[str, Optional[str]] = {}
        conflict_tracking: Dict[str, List[Conflict]] = {}

        # update_set is rewritten in place; keep the initial proposals.
        original_versions: Dict[str, Optional[str]] = {}

        # Parallel to `packages`; distinguishes duplicate declarations of a name.
        own_proposals: List[Optional[str]] = [
            pkg.recommended_version or pkg.current_version for pkg in packages
        ]

        for pkg, proposed in zip(packages, own_proposals):
            # Duplicates seed the name-level value from their lowest proposal;
            # this never overrides a declaration's own recommendation unless a
            # real conflict is found for that name.
            if pkg.name in update_set:
                proposed = _lower_proposal(update_set[pkg.name], proposed)
            update_set[pkg.name] = proposed
            original_versions[pkg.name] = proposed

        await self.data_store.prefetch_packages([pkg.name for pkg in packages])

        iterations_used = 0
        converged = False

        # Two proposals can keep undoing each other; a repeated state means
        # more passes would only replay the same moves.
        seen_states = {tuple(sorted(update_set.items()))}

        for iteration in range(_MAX_RESOLUTION_ITERATIONS):
            iterations_used = iteration + 1
            cross_conflicts = await self._find_cross_conflicts(packages, update_set)

            if not cross_conflicts:
                logger.debug(
                    "Update set is conflict-free after %d iteration(s)", iteration
                )
                converged = True
                break

            # The same conflict is re-detected each pass; dedupe by signature.
            _record_conflicts(conflict_tracking, cross_conflicts)

            resolved_any = await self._resolve_conflicts_within_major(
                pkg_lookup, update_set, cross_conflicts
            )

            if not resolved_any:
                # No change means the next pass would find the same conflicts.
                logger.warning(
                    "Conflict resolution stalled after %d iteration(s)",
                    iteration + 1,
                )
                break

            state = tuple(sorted(update_set.items()))
            if state in seen_states:
                logger.warning(
                    "Conflict resolution is cycling between the same versions "
                    "after %d iteration(s)",
                    iteration + 1,
                )
                break
            seen_states.add(state)
        else:
            # Loop exhausted without breaking.
            logger.warning(
                "Conflict resolution did not converge within %d iterations",
                _MAX_RESOLUTION_ITERATIONS,
            )

        # The last move of an exhausted loop was never scanned.
        remaining: List[Conflict] = []
        if not converged:
            remaining = await self._find_cross_conflicts(packages, update_set)
            _record_conflicts(conflict_tracking, remaining)

        # Advisory alternatives from one stable snapshot. Tracked conflicts
        # include ones the loop resolved, so an alternative must not override
        # the loop's decision unless that is still broken.
        alternatives: Dict[str, Optional[str]] = {}
        live_conflicts: Dict[str, List[Conflict]] = {}

        for pkg in packages:
            conflicts = conflict_tracking.get(pkg.name, [])
            if not conflicts:
                continue
            live_conflicts[pkg.name] = _live_conflicts(
                update_set, pkg.name, update_set.get(pkg.name), conflicts
            )
            # Stale conflicts would over-constrain the intersection.
            alternatives[pkg.name] = self._find_alternative_within_major(
                pkg, live_conflicts[pkg.name] or conflicts
            )

        # Adopt only where the decision is still broken and the alternative
        # introduces no new violation, judged against one snapshot so package
        # order does not matter.
        snapshot = dict(update_set)
        known = {
            _violation_key(c)
            for c in await self._find_cross_conflicts(packages, snapshot)
        }
        adopted: Dict[str, str] = {}
        for name, live in live_conflicts.items():
            alternative = alternatives.get(name)
            if not live or not alternative or alternative == snapshot.get(name):
                continue
            if not _satisfies_all(alternative, live):
                continue
            trial = {**snapshot, name: alternative}
            introduced = {
                _violation_key(c)
                for c in await self._find_cross_conflicts(packages, trial)
            } - known
            if introduced:
                logger.debug(
                    "Not adopting %s==%s: it would introduce %d new conflict(s)",
                    name,
                    alternative,
                    len(introduced),
                )
                continue
            logger.info(
                "Adopting compatible alternative for %s: %s → %s "
                "(%d conflict(s) unresolved by the resolution loop)",
                name,
                snapshot.get(name),
                alternative,
                len(live),
            )
            adopted[name] = alternative
        update_set.update(adopted)

        # Adoptions can interact; record whatever the final set still violates.
        if adopted:
            remaining = await self._find_cross_conflicts(packages, update_set)
            _record_conflicts(conflict_tracking, remaining)

        # A stalled or cycling loop can still end on a consistent set.
        converged = not remaining

        resolved_versions: Dict[str, PackageResolution] = {}
        packages_with_conflicts = 0
        packages_unresolved = 0

        for pkg, own_proposal in zip(packages, own_proposals):
            name = pkg.name
            original = original_versions.get(name)
            name_resolved = update_set.get(name)
            raw_conflicts = conflict_tracking.get(name, [])
            compatible_alt = alternatives.get(name)

            # The name-level value is a real decision only if it moved from its
            # seed (as conflict target or source). Otherwise this declaration
            # keeps its own proposal.
            name_changed = name_resolved != original_versions.get(name)
            if name_resolved is None:
                instance_resolved: Optional[str] = None
            elif not name_changed:
                instance_resolved = own_proposal
            else:
                instance_resolved = name_resolved

            # Use the final update_set so a conflict resolved by alternative
            # adoption is not shown.
            live = _live_conflicts(update_set, name, name_resolved, raw_conflicts)

            # Counts recorded, not just live, conflicts: a fallback revert
            # always looks resolved to `_live_conflicts`.
            if raw_conflicts:
                packages_with_conflicts += 1
            if live:
                packages_unresolved += 1

            status = self._determine_status(pkg, original, name_resolved, raw_conflicts)

            # May differ from the name-level summary for duplicated names. An
            # unavailable stub (no recommendation) must not gain one.
            if instance_resolved is not None and (
                pkg.recommended_version is not None or name_changed
            ):
                pkg.recommended_version = instance_resolved
                self._refresh_recommended_metadata(pkg, instance_resolved)
            pkg.set_conflicts(live)
            pkg.conflict_held = bool(raw_conflicts)

            resolved_versions[name] = PackageResolution(
                name=name,
                original=original,
                resolved=name_resolved,
                status=status,
                conflicts=raw_conflicts,
                compatible_alternative=compatible_alt,
            )

        failures = list(self._dependency_failures)
        self._dependency_failures.clear()
        if failures:
            logger.warning(
                "Dependency metadata unavailable for %d package(s): %s; "
                "conflict check incomplete",
                len(failures),
                ", ".join(failures),
            )
        return ResolutionResult(
            resolved_versions=resolved_versions,
            total_packages=len(packages),
            packages_with_conflicts=packages_with_conflicts,
            packages_unresolved=packages_unresolved,
            iterations_used=iterations_used,
            converged=converged,
            dependency_lookup_failures=failures,
        )

    def _find_alternative_within_major(
        self,
        pkg: Package,
        conflicts: List[Conflict],
    ) -> Optional[str]:
        """Find the highest version satisfying *every* recorded conflict.

        Advisory: it intersects all specifiers at once, unlike the
        one-conflict-at-a-time loop, so it may differ from the resolved
        version. The search stays within the current major and never goes
        below the installed version.

        Args:
            pkg: Package the conflicts are recorded against.
            conflicts: Conflicts accumulated for *pkg* across all iterations.

        Returns:
            A version string, or ``None`` when the major version cannot be
            determined or no candidate satisfies every conflict.
        """
        current_major = _boundary(pkg, self.checker)
        if current_major is None:
            return None

        available_in_major = _compatible_versions(
            self.data_store.get_cached_package(pkg.name),
            current_major,
            pkg.retained_specs,
            self.target_python,
            self.checker,
            pkg.current_version,
            pkg.versioning,
        )

        conflict_set = ConflictSet(pkg.name)
        for conflict in conflicts:
            conflict_set.add_conflict(conflict)

        return self.find_compatible_version(
            conflict_set, available_in_major, pkg.current_version
        )

    def _determine_status(
        self,
        pkg: Package,
        original: Optional[str],
        resolved: Optional[str],
        conflicts: List[Conflict],
    ) -> ResolutionStatus:
        """Classify how *resolved* relates to the *original* proposal."""
        if original == resolved:
            return ResolutionStatus.KEPT_RECOMMENDED

        if resolved == pkg.current_version:
            return ResolutionStatus.KEPT_CURRENT

        if original and resolved:
            try:
                original_parsed = parse(original)
                resolved_parsed = parse(resolved)

                if resolved_parsed > original_parsed:
                    return ResolutionStatus.UPGRADED
                elif resolved_parsed < original_parsed:
                    # A step back with no recorded conflict was dictated by
                    # another package's requirement.
                    return (
                        ResolutionStatus.DOWNGRADED
                        if conflicts
                        else ResolutionStatus.CONSTRAINED
                    )
            except InvalidVersion:
                pass

        return ResolutionStatus.CONSTRAINED

    async def _find_cross_conflicts(
        self,
        packages: List[Package],
        update_set: Dict[str, Optional[str]],
    ) -> List[Conflict]:
        """Scan the update set for pairwise version conflicts.

        For every package *P* at its proposed version *V*, fetch *V*'s
        dependency list. For each dependency *D* that also appears in the
        update set, check whether the proposed version of *D* satisfies
        *P*'s requirement specifier. If not, emit a `Conflict`.

        Args:
            packages: Full package list.
            update_set: Current name → proposed-version mapping.

        Returns:
            A (possibly empty) list of detected conflicts.
        """
        cross_conflicts: List[Conflict] = []

        # Resolution consumes conflicts in order; sorting keeps the outcome
        # independent of how the files happened to list the packages.
        for pkg in sorted(packages, key=lambda p: p.name):
            proposed_version = update_set.get(pkg.name)
            if not proposed_version:
                continue

            deps = await self._get_dependencies(pkg.name, proposed_version)

            for dep_spec in deps:
                req = _parse_dependency(dep_spec)
                if req is None:
                    logger.debug(
                        "Unparseable requirement %r in %s==%s",
                        dep_spec,
                        pkg.name,
                        proposed_version,
                    )
                    continue

                req_name: str = _normalize(req.name)

                # A package's requirement on itself (e.g. a self-referencing
                # extra) is not a cross-package conflict and no move can fix it.
                if req_name == pkg.name:
                    continue

                # Dependencies outside the update set cannot be adjusted.
                target_version = update_set.get(req_name)

                if (
                    target_version
                    and req.specifier
                    and not _specifier_allows(target_version, req.specifier)
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

    async def _resolve_conflicts_within_major(
        self,
        pkg_lookup: Dict[str, Package],
        update_set: Dict[str, Optional[str]],
        cross_conflicts: List[Conflict],
    ) -> bool:
        """Try to eliminate conflicts without crossing major boundaries.

        For each unique source package in *cross_conflicts*, in order:

        1. Pick the highest source version (within its major) whose
           requirement on the target is satisfied by the target's proposal.
        2. Pick the highest target version (within its major) satisfying the
           source's requirement, and revert the source to its current version.

        If neither works, both packages revert to their current versions and
        a warning is logged.

        Args:
            pkg_lookup: Name → `Package` mapping for quick access.
            update_set: Name -> proposed-version mapping, updated in place.
            cross_conflicts: Conflicts to process.

        Returns:
            ``True`` when at least one version in *update_set* was changed
            during this call.
        """
        resolved_any: bool = False

        processed_sources: Set[str] = set()
        # Per-pass memo: a pass reads every proposal's requirements once.
        requirements_memo: Dict[Tuple[str, str], Dict[str, SpecifierSet]] = {}

        for conflict in cross_conflicts:
            source_name: str = conflict.source_package
            target_name: str = conflict.target_package

            if source_name in processed_sources:
                continue

            source_pkg = pkg_lookup.get(source_name)
            target_pkg = pkg_lookup.get(target_name)

            if not source_pkg or not target_pkg:
                continue

            source_major = _boundary(source_pkg, self.checker)
            target_major = _boundary(target_pkg, self.checker)
            target_proposed = update_set.get(target_name)
            logger.debug(
                "Resolving conflict: %s (major %s) vs %s (major %s)",
                source_name,
                source_major,
                target_name,
                target_major,
            )

            compatible_source = await self._find_compatible_source_within_major(
                source_pkg=source_pkg,
                source_major=source_major,
                target_name=target_name,
                target_proposed_version=target_proposed,
                update_set=update_set,
            )

            if compatible_source and compatible_source != update_set.get(source_name):
                logger.info(
                    "Resolved: %s %s → %s (compatible with %s==%s, within major %s)",
                    source_name,
                    update_set.get(source_name),
                    compatible_source,
                    target_name,
                    target_proposed,
                    source_major,
                )
                update_set[source_name] = compatible_source
                resolved_any = True
                processed_sources.add(source_name)
                continue

            # A held or ignored target must stay put: lowering it would rewrite
            # a requirement the user told depkeeper not to touch.
            if target_pkg.held or target_pkg.ignored:
                constrained_target: Optional[str] = None
            else:
                constrained_target = await self._find_constrained_target_within_major(
                    target_name=target_name,
                    target_major=target_major,
                    required_spec=conflict.required_spec,
                    retained=target_pkg.retained_specs,
                    current_version=target_pkg.current_version,
                    scheme=target_pkg.versioning,
                    update_set=update_set,
                    source_name=source_name,
                    requirements_memo=requirements_memo,
                )

            if constrained_target and constrained_target != target_proposed:
                logger.info(
                    "Resolved: constraining %s to %s (required by %s, within major %s)",
                    target_name,
                    constrained_target,
                    source_name,
                    target_major,
                )
                update_set[target_name] = constrained_target

                # Upgrading the source was abandoned; revert it.
                if source_pkg.current_version:
                    update_set[source_name] = source_pkg.current_version
                resolved_any = True
            else:
                logger.warning(
                    "No compatible version found for %s ↔ %s within major boundaries; reverting both",
                    source_name,
                    target_name,
                )
                before = (update_set.get(source_name), update_set.get(target_name))
                if source_pkg.current_version:
                    update_set[source_name] = source_pkg.current_version
                if target_pkg.current_version:
                    update_set[target_name] = target_pkg.current_version
                # Report progress so the loop rescans the reverted state.
                if before != (update_set.get(source_name), update_set.get(target_name)):
                    resolved_any = True

            processed_sources.add(source_name)

        return resolved_any

    async def _find_compatible_source_within_major(
        self,
        source_pkg: Package,
        source_major: Optional[int],
        target_name: str,
        target_proposed_version: Optional[str],
        update_set: Optional[Dict[str, Optional[str]]] = None,
    ) -> Optional[str]:
        """Find a source version, within its major, compatible with the target.

        Walks the source's versions newest first. A candidate is compatible
        when it has no dependency on *target_name*, or its specifier is
        satisfied by *target_proposed_version*; given *update_set*, its
        requirements on every other proposed package must hold too, so a
        step back cannot trade one conflict for another. At most
        `_MAX_SOURCE_CANDIDATES` candidates are evaluated, and the search
        stops below the installed version.

        Args:
            source_pkg: The source `Package` being adjusted.
            source_major: Boundary the source must stay within, or ``None``
                if it cannot be determined.
            target_name: Normalized name of the conflicting dependency.
            target_proposed_version: The target's entry in the update set.
            update_set: Current proposals; when given, requirements on
                packages other than the target are enforced as well.

        Returns:
            The highest compatible source version, or ``None`` when none
            qualifies or the source's metadata is unavailable.
        """
        if source_major is None:
            logger.debug(
                "Cannot determine source major version for %s", source_pkg.name
            )
            return None

        source_name: str = source_pkg.name

        source_data = await self._get_package_data_or_none(source_name)
        if source_data is None:
            return None

        available_in_major = _compatible_versions(
            source_data,
            source_major,
            source_pkg.retained_specs,
            self.target_python,
            self.checker,
            source_pkg.current_version,
            source_pkg.versioning,
        )
        floor = parse_version_lenient(source_pkg.current_version)

        candidates_checked: int = 0

        for version_str in available_in_major:
            if candidates_checked >= _MAX_SOURCE_CANDIDATES:
                break

            # Descending list: everything further is below the installed version.
            candidate = parse_version_lenient(version_str)
            if floor is not None and candidate is not None and candidate < floor:
                break

            candidates_checked += 1

            deps = await self._get_dependencies(source_name, version_str)

            target_spec: Optional[SpecifierSet] = _extract_specifier_for(
                deps, target_name
            )

            if update_set is not None and _violates_update_set(
                deps, {**update_set, target_name: None}, source_name
            ):
                continue

            if target_spec is None:
                logger.debug(
                    "%s==%s has no dependency on %s → compatible",
                    source_name,
                    version_str,
                    target_name,
                )
                return version_str

            if target_proposed_version and _specifier_allows(
                target_proposed_version, target_spec
            ):
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

    async def _find_constrained_target_within_major(
        self,
        target_name: str,
        target_major: Optional[int],
        required_spec: str,
        retained: Sequence[Tuple[str, str]] = (),
        current_version: Optional[str] = None,
        scheme: str = "semver",
        update_set: Optional[Dict[str, Optional[str]]] = None,
        source_name: Optional[str] = None,
        requirements_memo: Optional[
            Dict[Tuple[str, str], Dict[str, SpecifierSet]]
        ] = None,
    ) -> Optional[str]:
        """Find the highest target version within its major satisfying *required_spec*.

        Given *update_set*, a candidate must also satisfy what every other
        proposed package (not *source_name*, which is being reverted) requires
        of the target, and its own requirements on the proposals, so
        satisfying one dependent cannot break another.

        Args:
            target_name: Package whose versions are scanned.
            target_major: Boundary to stay within; ``None`` returns ``None``.
            required_spec: PEP 440 specifier string, e.g. ``">=2.0,<3"``.
            retained: Bounds from the target's own requirement.
            current_version: The target's installed version.
            scheme: Versioning scheme of the target.
            update_set: Current proposals, enabling the extra checks above.
            source_name: Dependent exempt from them.
            requirements_memo: Shared cache of per-version requirements.

        Returns:
            A version string, or ``None`` when the specifier is unparseable,
            metadata is unavailable, or no version matches.
        """
        if target_major is None:
            logger.debug("Cannot determine target major version for %s", target_name)
            return None

        try:
            spec = SpecifierSet(required_spec)
        except InvalidSpecifier:
            logger.debug("Unparseable specifier %r for %s", required_spec, target_name)
            return None

        target_data = await self._get_package_data_or_none(target_name)
        if target_data is None:
            return None

        memo = requirements_memo if requirements_memo is not None else {}
        others: List[SpecifierSet] = []
        for name, proposed in (update_set or {}).items():
            if name in (target_name, source_name) or not proposed:
                continue
            required = (await self._requirements_of(name, proposed, memo)).get(
                target_name
            )
            if required:
                others.append(required)

        for version_str in _compatible_versions(
            target_data,
            target_major,
            retained,
            self.target_python,
            self.checker,
            current_version,
            scheme,
        ):
            if not _specifier_allows(version_str, spec):
                continue
            if any(not _specifier_allows(version_str, o) for o in others):
                continue
            if update_set is not None and _violates_update_set(
                await self._get_dependencies(target_name, version_str),
                update_set,
                target_name,
            ):
                continue
            return version_str  # descending, so the first match is highest

        return None

    def find_compatible_version(
        self,
        conflict_set: ConflictSet,
        available_versions: List[str],
        min_version: Optional[str] = None,
    ) -> Optional[str]:
        """Return the highest of *available_versions* satisfying *conflict_set*.

        The result is also at least *min_version*.

        Args:
            conflict_set: Aggregated conflicts for a single package.
            available_versions: Candidate versions, typically pre-filtered to
                the current major.
            min_version: Reject a result below this version (typically the
                installed one).

        Returns:
            A compatible version string, or ``None`` when no candidate
            passes all filters.
        """
        if not conflict_set.has_conflicts():
            return None

        compatible: Optional[str] = conflict_set.get_max_compatible_version(
            available_versions
        )

        # Never propose a downgrade.
        if compatible and min_version:
            try:
                if parse(compatible) < parse(min_version):
                    return None
            except InvalidVersion:
                return None

        return compatible


def _violates_update_set(
    deps: List[str], update_set: Dict[str, Optional[str]], skip: str
) -> bool:
    """Return ``True`` when any of *deps* is violated by the proposals in *update_set*.

    *skip* names the package the deps belong to (a self-requirement is not a
    cross-package conflict) so the check matches `_find_cross_conflicts`.
    """
    for dep in deps:
        req = _parse_dependency(dep)
        if req is None:
            continue
        name = _normalize(req.name)
        proposed = update_set.get(name)
        if (
            name != skip
            and proposed
            and req.specifier
            and not _specifier_allows(proposed, req.specifier)
        ):
            return True
    return False


def _extract_specifier_for(deps: List[str], target_name: str) -> Optional[SpecifierSet]:
    """Return the specifier *deps* places on *target_name*.

    Unparseable entries are skipped.

    Args:
        deps: PEP 508 dependency strings.
        target_name: Package name to search for.

    Returns:
        The `SpecifierSet` (empty means any version), or ``None`` when
        *target_name* is not in *deps*.
    """
    normalized_target: str = _normalize(target_name)

    for dep in deps:
        req = _parse_dependency(dep)
        if req is None:
            logger.debug("Skipping unparseable dependency: %r", dep)
            continue

        if _normalize(req.name) == normalized_target:
            return req.specifier

    return None
