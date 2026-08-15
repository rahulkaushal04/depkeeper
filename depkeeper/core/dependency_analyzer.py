"""Dependency conflict analysis with strict major version boundaries.

Resolves cross-package version conflicts without ever crossing a major
version boundary, so conflict resolution can never introduce a breaking
change the user did not ask for.

Design guarantees:

1. **Strict major version boundaries** — a package is never moved into a
   different major version to satisfy a conflict.
2. **Major-constrained compatibility search** — candidate versions are drawn
   only from the package's current major.
3. **Safe fallback** — when no compatible version exists in the current major,
   the package stays on its current version. Packages whose PyPI metadata
   cannot be fetched (deleted projects, private-index-only distributions,
   network failures) degrade to the same fallback instead of aborting the run.
4. **Explicit tracking** — every conflict is reported, including ones that
   could not be resolved within the boundaries above.

All network I/O is routed through the shared `PyPIDataStore`
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

from depkeeper.exceptions import NetworkError
from depkeeper.models.package import Package
from depkeeper.utils.logger import get_logger
from depkeeper.utils.naming import normalize_package_name
from depkeeper.utils.version_utils import parse_version_lenient
from depkeeper.core.data_store import PyPIDataStore, PyPIPackageData
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

# ---------------------------------------------------------------------------
# Resolution result models
# ---------------------------------------------------------------------------


class ResolutionStatus(Enum):
    """Outcome of version resolution for a single package."""

    KEPT_RECOMMENDED = "kept_recommended"  # Original recommendation was conflict-free
    UPGRADED = "upgraded"  # Moved to a newer version than first proposed
    DOWNGRADED = "downgraded"  # Had to move back due to conflicts
    KEPT_CURRENT = "kept_current"  # No safe upgrade found; stayed at current
    CONSTRAINED = "constrained"  # Version dictated by another package's requirement


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize(name: str) -> str:
    """Normalize a package name to its canonical PEP 503 form.

    Thin alias for `depkeeper.utils.naming.normalize_package_name`.
    Upstream ``requires_dist`` metadata spells names however the author
    typed them (``zope.interface``), while the update set is keyed by the
    parser's canonical form (``zope-interface``); both sides must use this
    one rule or cross-package conflicts are silently missed.

    Args:
        name: Raw package name in any casing / separator style.

    Returns:
        Canonical form, e.g. ``"my-package"``.
    """
    return normalize_package_name(name)


def _get_major_version(version: Optional[str]) -> Optional[int]:
    """Extract the major component from a version string.

    This is a thin, forgiving wrapper around ``packaging.version.parse``
    that returns ``None`` on any failure instead of raising.

    Args:
        version: Version string, or ``None``.

    Returns:
        The major version integer, or ``None``.
    """
    if not version:
        return None
    try:
        parsed = parse(version)
        return parsed.release[0] if parsed.release else None
    except InvalidVersion:
        return None


def _lower_proposal(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """Return whichever of *a*/*b* is the lower version.

    Seeds a single name-level working proposal when the same package name
    is declared more than once, so conflict detection has one conservative
    starting point without discarding either declaration's own proposal.
    ``None``/unparseable values are treated as "no preference".

    Args:
        a: One candidate version string, or ``None``.
        b: The other candidate version string, or ``None``.

    Returns:
        The lower of the two parseable versions, or whichever operand is
        usable when the other is ``None``/unparseable, or ``None`` when
        neither is.
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

    Unparseable specifiers and versions are treated as *satisfied* so that
    malformed upstream metadata can never, on its own, veto a version the
    resolution loop already accepted.

    Args:
        version: Candidate version string, or ``None``.
        required_spec: PEP-440 specifier string, e.g. ``">=2.0,<3"``.

    Returns:
        Whether the candidate is allowed by the specifier.
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

    Same permissive-on-unparseable-version handling as `_satisfies`,
    for callers that already hold a `SpecifierSet` rather than a
    specifier string. *version* is parsed explicitly first rather than
    relying on ``in specifier`` to raise on a bad version: as of
    ``packaging`` 26.0, that no longer raises ``InvalidVersion`` for an
    unparseable version — it returns ``False``, which would silently veto
    the version instead of treating it as satisfied.

    Args:
        version: Candidate version string, or ``None``.
        specifier: Already-parsed specifier set.

    Returns:
        Whether the candidate is allowed by the specifier.
    """
    if version is None:
        return True
    try:
        parsed_version = parse(version)
    except InvalidVersion:
        return True
    return parsed_version in specifier


def _satisfies_all(version: Optional[str], conflicts: List[Conflict]) -> bool:
    """Return ``True`` when *version* satisfies every conflict's specifier."""
    return all(_satisfies(version, c.required_spec) for c in conflicts)


def _live_conflicts(
    update_set: Dict[str, Optional[str]],
    target_name: str,
    target_version: Optional[str],
    conflicts: List[Conflict],
) -> List[Conflict]:
    """Filter accumulated conflicts down to those the final set still violates.

    ``conflict_tracking`` is cumulative across iterations, so it also holds
    conflicts that a later iteration resolved — typically by stepping the
    *source* package back to a release with a laxer requirement. Such a
    conflict is history, not a live problem, and must not influence the
    version that gets applied.

    A conflict is *live* when both halves of the pair are still proposed as
    recorded: the source package is still headed for ``source_version`` and
    the target's final version still fails ``required_spec``.

    Args:
        update_set: Final name → proposed-version mapping.
        target_name: Package the conflicts are recorded against.
        target_version: *target_name*'s entry in the final update set.
        conflicts: Conflicts accumulated for *target_name*.

    Returns:
        The subset of *conflicts* still violated by the final update set.
    """
    live: List[Conflict] = []

    for conflict in conflicts:
        if update_set.get(conflict.source_package) != conflict.source_version:
            # The source moved on; this requirement is no longer proposed.
            continue
        if _satisfies(target_version, conflict.required_spec):
            continue
        live.append(conflict)

    if live:
        logger.debug(
            "%s has %d live conflict(s) of %d recorded at %s",
            target_name,
            len(live),
            len(conflicts),
            target_version,
        )

    return live


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


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
        concurrent_limit: Upper bound on in-flight PyPI fetches.
            Forwarded to the internal semaphore. Defaults to ``10``.

    Raises:
        TypeError: If *data_store* is ``None``.
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

        # Normalized names whose metadata could not be fetched during this
        # resolution run. Remembering them keeps the resolution loop from
        # re-issuing (and re-retrying) a request that is already known to fail.
        self._unavailable_packages: Set[str] = set()

    # ------------------------------------------------------------------
    # Data access helpers
    # ------------------------------------------------------------------

    async def _get_package_data_or_none(self, name: str) -> Optional[PyPIPackageData]:
        """Fetch metadata for *name*, degrading to ``None`` when unavailable.

        Mirrors the stub strategy used by
        `get_package_info`: a
        package that PyPI cannot serve (deleted project, private-index-only
        distribution, rate limiting, network outage) must not abort the whole
        run. The first failure for a given name is logged at WARNING and
        remembered, so subsequent resolution passes skip the package instead
        of paying for another retry cycle.

        Args:
            name: Package name (any casing / separator style).

        Returns:
            The `PyPIPackageData` snapshot, or ``None`` when metadata
            could not be retrieved.
        """
        normalized = _normalize(name)

        if normalized in self._unavailable_packages:
            return None

        try:
            return await self.data_store.get_package_data(name)
        except NetworkError as exc:
            # PyPIError (404 / unexpected status) subclasses NetworkError, so
            # this also covers timeouts, rate-limit exhaustion and 5xx.
            self._unavailable_packages.add(normalized)
            logger.warning(
                "PyPI metadata for '%s' is unavailable (%s); "
                "conflict resolution will skip this package",
                name,
                exc,
            )
            return None

    def _refresh_recommended_metadata(self, pkg: Package, resolved: str) -> None:
        """Keep ``recommended_metadata`` in sync with the version being applied.

        ``VersionChecker`` populates ``recommended_metadata`` once, for its
        initial proposal. When conflict resolution moves
        ``recommended_version`` elsewhere, that metadata otherwise keeps
        describing the abandoned proposal. Recomputed from the data store's
        cache only, so this never triggers new network I/O; left untouched
        when *pkg* isn't cached (unavailable package).

        Args:
            pkg: The package whose ``recommended_version`` was just set.
            resolved: The version now stored in ``pkg.recommended_version``.
        """
        cached = self.data_store.get_cached_package(pkg.name)
        if cached is None:
            return

        pkg.metadata["recommended_metadata"] = {
            "requires_python": cached.python_requirements.get(resolved),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def resolve_and_annotate_conflicts(
        self,
        packages: List[Package],
    ) -> ResolutionResult:
        """Resolve conflicts while strictly respecting major version boundaries.

        Algorithm outline:

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

        Invariant: after this call, ``pkg.recommended_version`` equals
        ``result.resolved_versions[pkg.name].resolved`` for every package
        declared **once**. `ResolutionResult` is therefore the
        single source of truth for a singly-declared package — the version
        reported in the summary is always the version applied by
        ``depkeeper update``.

        Duplicate declarations (the same normalized package name appearing
        more than once in *packages*, e.g. the same distribution pulled in
        via two ``-r`` includes with different constraints) are each
        resolved **independently**: cross-package conflict detection still
        reasons about the name as a whole, but a name-level adjustment only
        reaches a given declaration's ``recommended_version`` when a *real*
        conflict was recorded for that name. Absent one, each declaration
        keeps the recommendation it already had. ``resolved_versions``
        still holds one summary entry per *name*, so for a duplicated name
        it reports a single representative outcome — consult each
        `Package.recommended_version` directly for the authoritative
        per-declaration outcome.

        Args:
            packages: Mutable list of `Package` objects. Each
                object is updated in place with the resolved version and
                conflict metadata.

        Returns:
            `ResolutionResult` containing the final version for each
            package, conflict details, and resolution statistics.
        """
        # ── initialize update set ─────────────────────────────────────
        pkg_lookup: Dict[str, Package] = {pkg.name: pkg for pkg in packages}
        update_set: Dict[str, Optional[str]] = {}
        conflict_tracking: Dict[str, List[Conflict]] = {}

        # Kept separately so PackageResolution can report what was originally
        # proposed even after update_set has been rewritten in place.
        original_versions: Dict[str, Optional[str]] = {}

        # Each package instance's own pre-resolution proposal, captured
        # positionally (parallel to `packages`) before any name-collapsing,
        # so a duplicated name's declarations can be told apart later.
        own_proposals: List[Optional[str]] = [
            pkg.recommended_version or pkg.current_version for pkg in packages
        ]

        for pkg, proposed in zip(packages, own_proposals):
            # recommended_version already respects major boundaries; falling
            # back to current_version means "propose no change". A name
            # declared more than once seeds the name-level working value
            # from the lower of its duplicates' proposals -- bookkeeping
            # only, it never overrides an individual declaration's own
            # recommendation unless a real conflict is found for that name.
            if pkg.name in update_set:
                proposed = _lower_proposal(update_set[pkg.name], proposed)
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

            # Record every conflict for later annotation. The same conflict can
            # be re-detected on each pass, so identical signatures are dropped.
            for conflict in cross_conflicts:
                conflicts_list = conflict_tracking.setdefault(
                    conflict.target_package, []
                )

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

            # Attempt resolution while respecting major version boundaries
            resolved_any = await self._resolve_conflicts_within_major(
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

        # ── advisory alternatives, computed from one stable snapshot ──
        # `conflict_tracking` is cumulative: it holds every conflict seen in
        # *any* iteration, including ones the loop went on to resolve. The
        # alternative search below is therefore only advisory — it must never
        # silently override the version the loop actually decided on (that
        # divergence is exactly what made the printed summary disagree with
        # the version written to the file).
        alternatives: Dict[str, Optional[str]] = {}
        live_conflicts: Dict[str, List[Conflict]] = {}

        for pkg in packages:
            conflicts = conflict_tracking.get(pkg.name, [])
            if not conflicts:
                continue
            alternatives[pkg.name] = self._find_alternative_within_major(
                pkg, conflicts
            )
            live_conflicts[pkg.name] = _live_conflicts(
                update_set, pkg.name, update_set.get(pkg.name), conflicts
            )

        # ── adopt an alternative only where the decision is still broken ──
        # Every decision above is made against the same pre-adoption snapshot
        # so the outcome does not depend on package ordering.
        for name, live in live_conflicts.items():
            alternative = alternatives.get(name)
            if not live or not alternative or alternative == update_set.get(name):
                continue
            if not _satisfies_all(alternative, live):
                continue
            logger.info(
                "Adopting compatible alternative for %s: %s → %s "
                "(%d conflict(s) unresolved by the resolution loop)",
                name,
                update_set.get(name),
                alternative,
                len(live),
            )
            update_set[name] = alternative

        # ── annotate packages and build resolution map ────────────────
        resolved_versions: Dict[str, PackageResolution] = {}
        packages_with_conflicts = 0

        for pkg, own_proposal in zip(packages, own_proposals):
            name = pkg.name
            original = original_versions.get(name)
            name_resolved = update_set.get(name)
            raw_conflicts = conflict_tracking.get(name, [])
            compatible_alt = alternatives.get(name)

            # A name-level value only reflects a *real* resolution decision
            # when it moved away from its initial seed -- whether this name
            # was the target of a conflict, or was adjusted as the source of
            # one (conflicts are recorded by target only, so
            # `conflict_tracking` alone can't tell the two apart). Absent
            # any such move, a divergence between `name_resolved` and this
            # declaration's own proposal is just the seeding above; it must
            # not change what THIS declaration recommends.
            name_changed = name_resolved != original_versions.get(name)
            if name_resolved is None:
                instance_resolved: Optional[str] = None
            elif not name_changed:
                instance_resolved = own_proposal
            else:
                instance_resolved = name_resolved

            # Recomputed against the FINAL update_set (after alternative
            # adoption above), not the pre-adoption snapshot used only to
            # decide whether to adopt -- otherwise a conflict the adoption
            # step just resolved would still be reported as live. Only used
            # for what `pkg` actually displays: a shown conflict must never
            # cite a source/target pairing that was never applied.
            live = _live_conflicts(update_set, name, name_resolved, raw_conflicts)

            # Counts every name a conflict was ever recorded for, not just
            # the still-live ones: a fallback revert always looks resolved
            # to `_live_conflicts` even when the reverted pairing is, in
            # reality, still incompatible.
            if raw_conflicts:
                packages_with_conflicts += 1

            status = self._determine_status(pkg, original, name_resolved, raw_conflicts)

            # Applies what THIS declaration resolves to, which for a
            # duplicated name may legitimately differ from the name-level
            # summary below (see the docstring).
            if instance_resolved is not None:
                pkg.recommended_version = instance_resolved
                self._refresh_recommended_metadata(pkg, instance_resolved)
            pkg.set_conflicts(live)

            resolved_versions[name] = PackageResolution(
                name=name,
                original=original,
                resolved=name_resolved,
                status=status,
                conflicts=raw_conflicts,
                compatible_alternative=compatible_alt,
            )

        return ResolutionResult(
            resolved_versions=resolved_versions,
            total_packages=len(packages),
            packages_with_conflicts=packages_with_conflicts,
            iterations_used=iterations_used,
            converged=converged,
        )

    def _find_alternative_within_major(
        self,
        pkg: Package,
        conflicts: List[Conflict],
    ) -> Optional[str]:
        """Find the highest version satisfying *every* recorded conflict.

        Purely advisory: the search is independent of the resolution loop
        (it intersects all specifiers at once, whereas the loop handles one
        conflict at a time), so its answer may legitimately differ from the
        resolved version. Callers must treat the result as a suggestion and
        never as the applied version.

        The search never leaves the package's current major version and never
        goes below the installed version, matching the resolver's own safety
        policy.

        Args:
            pkg: Package the conflicts are recorded against.
            conflicts: Conflicts accumulated for *pkg* across all iterations.

        Returns:
            A version string, or ``None`` when the major version cannot be
            determined or no candidate satisfies every conflict.
        """
        current_major = _get_major_version(pkg.current_version)
        if current_major is None:
            return None

        available_in_major = [
            v
            for v in self.data_store.get_versions(pkg.name)
            if _get_major_version(v) == current_major
        ]

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
                    # A step back with no recorded conflict means another
                    # package's requirement, not a conflict, dictated it.
                    return (
                        ResolutionStatus.DOWNGRADED
                        if conflicts
                        else ResolutionStatus.CONSTRAINED
                    )
            except InvalidVersion:
                pass

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
        dependency list. For each dependency *D* that also appears in the
        update set, check whether the proposed version of *D* satisfies
        *P*'s requirement specifier. If not, emit a `Conflict`.

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

                # A dependency outside the update set is not something this
                # run can adjust, so it cannot be a resolvable conflict.
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

    # ------------------------------------------------------------------
    # Resolution strategies (major-version constrained)
    # ------------------------------------------------------------------

    async def _resolve_conflicts_within_major(
        self,
        pkg_lookup: Dict[str, Package],
        update_set: Dict[str, Optional[str]],
        cross_conflicts: List[Conflict],
    ) -> bool:
        """Attempt to eliminate conflicts while never crossing major boundaries.

        Two strategies are tried in order for each unique *source* package
        that appears in *cross_conflicts*:

        1. **Downgrade source within its major** — find the highest version
           of the source (within its current major) whose requirement on the
           target is satisfied by the target's proposed version.
        2. **Constrain target within its major** — find the highest version
           of the target (within its current major) that satisfies the
           source's requirement, and revert the source to its current version.

        If neither strategy produces a viable version within major boundaries,
        both packages are reverted to their *current* (installed) versions and
        a warning is logged.

        Args:
            pkg_lookup: Name → `Package` mapping for quick access.
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

            # Get major versions for both packages (boundaries we cannot cross)
            source_major = _get_major_version(source_pkg.current_version)
            target_major = _get_major_version(target_pkg.current_version)
            target_proposed = update_set.get(target_name)
            logger.debug(
                "Resolving conflict: %s (major %s) vs %s (major %s)",
                source_name,
                source_major,
                target_name,
                target_major,
            )

            # ── strategy 1: find compatible source within its major ──────
            compatible_source = await self._find_compatible_source_within_major(
                source_pkg=source_pkg,
                source_major=source_major,
                target_name=target_name,
                target_proposed_version=target_proposed,
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
                continue  # move to next conflict

            # ── strategy 2: constrain target within its major ────────────
            constrained_target = await self._find_constrained_target_within_major(
                target_name=target_name,
                target_major=target_major,
                required_spec=conflict.required_spec,
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

                # Revert source to current since we gave up upgrading it
                if source_pkg.current_version:
                    update_set[source_name] = source_pkg.current_version
                resolved_any = True
            else:
                # ── fallback: revert both to current ──────────────────
                logger.warning(
                    "No compatible version found for %s ↔ %s within major boundaries; reverting both",
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
    # Version search helpers (major-constrained)
    # ------------------------------------------------------------------

    async def _find_compatible_source_within_major(
        self,
        source_pkg: Package,
        source_major: Optional[int],
        target_name: str,
        target_proposed_version: Optional[str],
    ) -> Optional[str]:
        """Find compatible source version ONLY within source's current major.

        Walk the source package's versions (newest first, within its current
        major version only) for compatibility. A candidate version is
        *compatible* when it either has no dependency on *target_name* at all,
        or its dependency specifier is satisfied by *target_proposed_version*.

        The search is bounded by `_MAX_SOURCE_CANDIDATES` to avoid
        scanning packages with very long release histories. Pre-releases are
        skipped but do **not** count against the candidate budget.

        Args:
            source_pkg: The source `Package` being adjusted.
            source_major: Major version the source must stay within (or
                ``None`` if major cannot be determined).
            target_name: Normalized name of the dependency that caused the
                conflict.
            target_proposed_version: The target's current entry in the
                update set (may be ``None``).

        Returns:
            The highest compatible source version string (within the same
            major), ``None`` when no candidate satisfies the constraints, or
            ``None`` when PyPI metadata for the source cannot be fetched.
        """
        if source_major is None:
            logger.debug(
                "Cannot determine source major version for %s", source_pkg.name
            )
            return None

        source_name: str = source_pkg.name
        python_version: str = PyPIDataStore.get_current_python_version()

        source_data = await self._get_package_data_or_none(source_name)
        if source_data is None:
            return None

        # Get all versions in source's current major that are Python-compatible
        available_in_major = source_data.get_python_compatible_versions(
            python_version, major=source_major
        )

        candidates_checked: int = 0

        for version_str in available_in_major:
            # ── hard budget on evaluated candidates ────────────────────
            if candidates_checked >= _MAX_SOURCE_CANDIDATES:
                break

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
    ) -> Optional[str]:
        """Find target version satisfying spec ONLY within target's current major.

        Only stable versions within *target_major* are considered. Returns
        ``None`` when the specifier itself is unparseable, when major version
        cannot be determined, when PyPI metadata for the target cannot be
        fetched, or when no matching version exists within the major boundary.

        Args:
            target_name: Package whose versions are being scanned.
            target_major: If not ``None``, only versions sharing this
                major number are considered. If ``None``, returns ``None``
                immediately (cannot constrain without knowing the boundary).
            required_spec: PEP-440 specifier string, e.g. ``">=2.0,<3"``.

        Returns:
            A version string (within the specified major), or ``None``.
        """
        if target_major is None:
            logger.debug("Cannot determine target major version for %s", target_name)
            return None

        try:
            spec = SpecifierSet(required_spec)
        except InvalidSpecifier:
            logger.debug("Unparseable specifier %r for %s", required_spec, target_name)
            return None

        # Get all versions in target's current major
        target_data = await self._get_package_data_or_none(target_name)
        if target_data is None:
            return None

        available = target_data.all_versions

        for version_str in available:  # already sorted descending
            try:
                parsed = parse(version_str)

                if parsed.is_prerelease:
                    continue

                version_major = parsed.release[0] if parsed.release else None
                if version_major != target_major:
                    continue

                if version_str in spec:
                    return version_str  # first match is the highest

            except InvalidVersion:
                continue

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
                conflict_set itself determines compatibility). Typically
                pre-filtered to only include versions within the current
                major.
            min_version: If provided, discard any candidate that parses
                below this version. Typically the currently-installed
                version.

        Returns:
            A compatible version string, or ``None`` when no candidate
            passes all filters.
        """
        if not conflict_set.has_conflicts():
            return None

        compatible: Optional[str] = conflict_set.get_max_compatible_version(
            available_versions
        )

        # A candidate below the installed version would be a downgrade the
        # caller never asked for, so reject rather than propose it.
        if compatible and min_version:
            try:
                if parse(compatible) < parse(min_version):
                    return None
            except InvalidVersion:
                return None

        return compatible


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _extract_specifier_for(deps: List[str], target_name: str) -> Optional[SpecifierSet]:
    """Scan a dependency list and return the specifier that targets *target_name*.

    Parsing failures for individual entries are logged at DEBUG and
    skipped so that one bad line does not prevent the rest from being
    checked.

    Args:
        deps: PEP-508 dependency strings (extras and markers already
            stripped by the data store).
        target_name: Normalized package name to search for.

    Returns:
        The `SpecifierSet` for *target_name*, or ``None`` when the
        target does not appear in *deps*. The set may be empty, which means
        "any version".
    """
    normalized_target: str = _normalize(target_name)

    for dep in deps:
        try:
            req = PkgRequirement(dep)
        except (InvalidVersion, InvalidRequirement):
            logger.debug("Skipping unparseable dependency: %r", dep)
            continue

        if _normalize(req.name) == normalized_target:
            return req.specifier

    return None
