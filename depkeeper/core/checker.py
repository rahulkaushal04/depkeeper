"""Version checking with strict major version boundary enforcement.

Determines which version of a package should be recommended for upgrade,
never crossing a major version boundary.

All PyPI metadata is sourced through `PyPIDataStore`
to ensure that every ``/pypi/{pkg}/json`` call is made at most once per process.

The recommendation algorithm prioritises:

1. **Major-version stability** — recommendations **never** cross major version
   boundaries. If current is 2.x.x, recommended will always be 2.y.z (never 3.0.0).
2. **Python compatibility** — versions that do not support the running
   interpreter are skipped.
3. **Stable releases** — pre-releases are never recommended.

Typical usage::

    from depkeeper.utils.http import HTTPClient
    from depkeeper.core.data_store import PyPIDataStore
    from depkeeper.core.checker import VersionChecker
    from depkeeper.core.parser import RequirementsParser

    async with HTTPClient() as http:
        store   = PyPIDataStore(http)
        checker = VersionChecker(data_store=store)

        parser = RequirementsParser()
        requirements = parser.parse_file("requirements.txt")

        packages = await checker.check_packages(requirements)

        for pkg in packages:
            if pkg.recommended_version:
                print(f"{pkg.name}: {pkg.current_version} → {pkg.recommended_version}")
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)
from packaging.version import InvalidVersion

from depkeeper.exceptions import NetworkError
from depkeeper.models.package import Package
from depkeeper.utils.logger import get_logger
from depkeeper.config import DepKeeperConfig, PackagePolicy
from depkeeper.utils.naming import normalize_package_name
from depkeeper.utils.version_utils import (
    detect_versioning,
    get_update_type,
    gating_type,
    update_rank,
    parse_version_lenient,
    implied_major_bounds,
    retained_specs,
    specs_allow_version,
    specs_to_string,
)
from depkeeper.models.requirement import Requirement
from depkeeper.core.data_store import PyPIDataStore, PyPIPackageData

logger = get_logger("version_checker")


def _newer_series(candidates: List[str], current: str, series: int) -> List[str]:
    """Keep versions whose first *series* components exceed *current*'s."""

    def key(v: str) -> Tuple[int, ...]:
        rel = parse_version_lenient(v)
        r = rel.release if rel else ()
        return (tuple(r) + (0,) * series)[:series]

    base = key(current)
    return [v for v in candidates if parse_version_lenient(v) and key(v) > base]


class VersionChecker:
    """Async package version checker with strict major version boundaries.

    Fetches metadata from PyPI (via the shared data store) and determines
    the highest Python-compatible version for each package, **strictly
    respecting major-version boundaries** when a current version is known:
    a newer major is never recommended, even if one exists.

    All network I/O is delegated to *data_store*, which guarantees that
    each unique package is fetched at most once.

    Args:
        data_store: Shared PyPI metadata cache. **Required**.
        infer_version_from_constraints: When ``True`` and a requirement has
            no pinned version (``==``), attempt to infer a "current" version
            from range constraints like ``>=2.0``. Defaults to ``True``.
        target_python: Python version (``"3.9"``) candidates must support.
            ``None`` (default) means the running interpreter.
        versioning: ``"auto"`` (default), ``"semver"`` or ``"calver"``. Calver
            packages (``2024.8.30``) have no major boundary: recommendations
            may cross the leading year, and update types are labelled
            ``year``/``month``/``patch``.
        min_age: Release cooldown. Versions uploaded less than this long ago
            are not recommended; the newest older eligible version is used
            instead, never one below the current version. Versions without
            upload data count as old.
        policies: Per-package `PackagePolicy`, keyed by normalized name
            (``max_update``, ``hold``, ``allow_prerelease``, ``versioning``,
            ``ignore``).
        allow_major: Package names (or ``"*"`` for all) whose recommendation may
            cross the current major. The requirement's own upper bounds,
            ``max_update``, Python compatibility and the cooldown still apply.
        max_update: Run-wide cap (CLI ``--max-update``). Applied before choosing
            a candidate, but only for packages opted into major upgrades; for the
            rest the command filters afterwards, as before.
        clock: Returns the current UTC time (injectable for tests).

    Raises:
        TypeError: If *data_store* is ``None``.
    """

    def __init__(
        self,
        data_store: PyPIDataStore,
        infer_version_from_constraints: bool = True,
        target_python: Optional[str] = None,
        versioning: str = "auto",
        min_age: Optional[timedelta] = None,
        policies: Optional[Mapping[str, PackagePolicy]] = None,
        clock: Optional[Callable[[], datetime]] = None,
        allow_major: Iterable[str] = (),
        max_update: Optional[str] = None,
    ) -> None:
        if data_store is None:
            raise TypeError(
                "data_store must not be None; pass a PyPIDataStore instance"
            )

        self.data_store: PyPIDataStore = data_store
        self.infer_version_from_constraints: bool = infer_version_from_constraints
        self.target_python: Optional[str] = target_python
        self.versioning: str = versioning
        self.min_age: Optional[timedelta] = min_age
        self.policies: Dict[str, PackagePolicy] = {
            normalize_package_name(k): v for k, v in (policies or {}).items()
        }
        self._clock: Callable[[], datetime] = clock or (
            lambda: datetime.now(timezone.utc)
        )
        self._warned_undated: Set[str] = set()
        self.max_update: Optional[str] = max_update
        self._allow_major: Set[str] = {normalize_package_name(n) for n in allow_major}

    @classmethod
    def from_config(
        cls,
        data_store: PyPIDataStore,
        config: DepKeeperConfig,
        **overrides: Any,
    ) -> "VersionChecker":
        """Build a checker from a loaded config.

        Args:
            data_store: Shared PyPI metadata cache.
            config: Loaded configuration.
            **overrides: Constructor arguments (e.g. CLI ``target_python`` or
                ``min_age``) that win over the config's values unless ``None``.
        """
        kwargs: Dict[str, Any] = {
            "infer_version_from_constraints": not config.strict_version_matching,
            "target_python": config.python_version,
            "versioning": config.versioning,
            "min_age": config.min_age,
            "policies": config.packages,
        }
        kwargs.update({k: v for k, v in overrides.items() if v is not None})
        return cls(data_store, **kwargs)

    def allows_major(self, name: str) -> bool:
        """Return whether *name* may be recommended across its current major."""
        key = normalize_package_name(name)
        policy = self.policies.get(key)
        return (
            "*" in self._allow_major
            or key in self._allow_major
            or bool(policy and policy.allow_major)
        )

    def _cap_for(self, name: str, policy: PackagePolicy) -> Optional[str]:
        """Stricter of the policy cap and the run-wide cap (opted-in packages)."""
        caps = [policy.max_update]
        if self.allows_major(name):
            caps.append(self.max_update)
        set_caps = [c for c in caps if c]
        return min(set_caps, key=update_rank) if set_caps else None

    async def get_package_info(
        self,
        name: str,
        current_version: Optional[str] = None,
        constraints: Optional[Sequence[Tuple[str, str]]] = None,
        series: Optional[int] = None,
    ) -> Package:
        """Fetch metadata and compute a recommended version for *name*.

        Recommendations never cross major version boundaries: if
        *current_version* is ``2.x.x``, the recommendation is ``2.y.z`` even
        when ``3.0.0`` is the latest release on PyPI.

        Args:
            name: Package name (any casing / separator style).
            current_version: The version currently installed (if known).
                When provided, the recommendation stays within the same
                major version. If no compatible version exists in that
                major, stays on current version rather than crossing
                the boundary.
            constraints: Additional ``(operator, version)`` specifiers the
                recommendation must satisfy — typically the upper bounds and
                exclusions declared by the requirement itself (see
                `retained_specs`).
                Recommending a version that violates them would produce an
                unsatisfiable requirement line.
            series: For fuzzy conda specs (``=1.24``): number of significant
                release components. An update then needs a newer *series*
                (1.25, 2.0), never just a newer patch of the same one.

        Returns:
            A `Package` with ``latest_version``,
            ``recommended_version``, and metadata fields populated. When PyPI
            data cannot be retrieved (missing package, unexpected status,
            timeout, rate limiting) an *unavailable stub* is returned instead
            — see `create_unavailable_package`.
        """
        try:
            pkg_data = await self.data_store.get_package_data(name)
        except NetworkError:
            # PyPIError is a NetworkError: a stub keeps one bad package from
            # failing the whole run.
            logger.warning("Package '%s' unavailable; creating stub", name)
            return self.create_unavailable_package(name, current_version)

        package = self._build_package_from_data(
            pkg_data, current_version, constraints, series
        )
        package.retained_specs = list(constraints or ())
        return package

    async def check_packages(
        self,
        requirements: List[Requirement],
    ) -> List[Package]:
        """Check multiple packages concurrently.

        For each requirement, extracts the current version (via
        `extract_current_version`) and calls `get_package_info`.
        Errors for individual packages are caught and replaced with
        unavailable stubs so that one bad package does not block the rest.

        Args:
            requirements: Parsed requirements from a requirements file.

        Returns:
            List of `Package` objects, one per requirement.
        """
        tasks = [self._create_package_check_task(req) for req in requirements]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return self._process_check_results(requirements, results)

    def extract_current_version(
        self,
        req: Requirement,
    ) -> Optional[str]:
        """Infer a "current" version from a requirement's version specifiers.

        Heuristic:

        1. If the requirement has exactly one specifier and it is ``==``,
           return that version (pinned).
        2. If `infer_version_from_constraints` is ``False``, stop here.
        3. Otherwise, scan for the first ``>=``, ``>``, or ``~=`` specifier
           and return its version. This treats ``>=2.0`` as "currently on
           2.0" for major-version boundary purposes.

        Args:
            req: A parsed `Requirement`.

        Returns:
            The inferred version string, or ``None`` when inference is not
            possible.
        """
        if not req.specs:
            return None

        # Any exact pin anchors the version, even alongside ``!=`` etc.
        for operator, version in req.specs:
            if operator in ("==", "===") and "*" not in version:
                return version

        if not self.infer_version_from_constraints:
            return None

        for operator, version in req.specs:
            if operator in (">=", ">", "~="):
                return version

        return None

    def create_unavailable_package(
        self,
        name: str,
        current_version: Optional[str],
    ) -> Package:
        """Create a stub `Package` when PyPI data is unavailable.

        Keeps the package in the result list (rather than dropping it) so the
        report still shows what is declared in the file, while the missing
        ``latest_version`` renders as an error row and no update is proposed.

        Args:
            name: Package name.
            current_version: The version that was installed (if known).

        Returns:
            A `Package` with ``latest_version`` and
            ``recommended_version`` both set to ``None``.
        """
        return Package(
            name=name,
            current_version=current_version,
            latest_version=None,
            recommended_version=None,
            metadata={},
        )

    def _create_package_check_task(
        self,
        requirement: Requirement,
    ) -> asyncio.Task[Package]:
        """Spawn a task that checks *requirement*, honouring its declared range."""
        current_version = self.extract_current_version(requirement)
        return asyncio.create_task(
            self.get_package_info(
                requirement.name,
                current_version,
                # -c constraint caps always bind (never rewritten, so all kept).
                retained_specs(requirement.specs)
                + implied_major_bounds(requirement.specs)
                + list(requirement.constraint_specs),
                requirement.series,
            )
        )

    def _process_check_results(
        self,
        requirements: List[Requirement],
        results: Sequence[Union[Package, BaseException]],
    ) -> List[Package]:
        """Replace failed check results with unavailable stubs, keeping order."""
        packages: List[Package] = []

        for requirement, result in zip(requirements, results):
            if isinstance(result, BaseException):
                logger.error(
                    "Failed to fetch package info for %s: %s",
                    requirement.name,
                    result,
                )
                packages.append(
                    self.create_unavailable_package(
                        requirement.name,
                        self.extract_current_version(requirement),
                    )
                )
            else:
                packages.append(result)

        return packages

    def _build_package_from_data(
        self,
        pkg_data: PyPIPackageData,
        current_version: Optional[str],
        constraints: Optional[Sequence[Tuple[str, str]]] = None,
        series: Optional[int] = None,
    ) -> Package:
        """Construct a `Package` from cached PyPI metadata.

        Recommendation algorithm:

        1. If *current_version* is provided and parseable, determine its
           major version number.
        2. Find **all** Python-compatible versions within that same major
           (using `PyPIPackageData.get_python_compatible_versions`).
        3. Discard candidates rejected by *constraints* (the requirement's
           own upper bounds / exclusions).
        4. Return the **highest** version from that filtered list as the
           recommendation.
        5. If no compatible version exists in the current major, **stay on
           current version** rather than suggesting a major upgrade.
        6. If no *current_version* is provided, find the highest
           Python-compatible stable version across all majors.

        Calver packages have no major boundary, and hold/ignore policies,
        ``max_update`` and the cooldown further restrict the candidates.
        """
        latest_version: Optional[str] = pkg_data.latest_version
        python_version: str = (
            self.target_python or PyPIDataStore.get_current_python_version()
        )
        policy = self.policies.get(pkg_data.name) or PackagePolicy()
        scheme = detect_versioning(
            policy.versioning or self.versioning, current_version, pkg_data.all_versions
        )

        recommended_version: Optional[str] = None
        cooldown_skipped: Optional[str] = None
        major_available: Optional[str] = None
        held = bool(policy.hold and current_version)

        if held or policy.ignore:
            recommended_version = current_version
        elif current_version:
            try:
                # Calver has no breaking major boundary; semver never crosses it.
                boundary = (
                    None
                    if scheme == "calver"
                    else self._major_from_version(current_version)
                )
                if scheme != "calver" and boundary is None:
                    logger.warning(
                        "%s: cannot determine major version from %s",
                        pkg_data.name,
                        current_version,
                    )
                    recommended_version = current_version
                else:
                    # Opt-in drops only depkeeper's own boundary; the user's
                    # declared bounds still filter via *constraints*.
                    candidates = self._candidates(
                        pkg_data,
                        python_version,
                        None if self.allows_major(pkg_data.name) else boundary,
                        constraints,
                        policy,
                    )
                    candidates = self._cap_update(
                        candidates,
                        current_version,
                        self._cap_for(pkg_data.name, policy),
                        scheme,
                    )
                    if series:
                        candidates = _newer_series(candidates, current_version, series)
                    recommended_version, cooldown_skipped = self._apply_cooldown(
                        pkg_data, candidates, current_version
                    )
                    if recommended_version is None and series:
                        recommended_version = current_version  # same series: no update
                    elif recommended_version is None:
                        # Deliberate: never fall through to the next major.
                        logger.warning(
                            "%s: no eligible version found (Python %s, "
                            "constraints '%s'), staying on %s",
                            pkg_data.name,
                            python_version,
                            specs_to_string(constraints or []),
                            current_version,
                        )
                        recommended_version = current_version
                    if scheme != "calver" and not series:
                        major_available = self._higher_major(
                            pkg_data,
                            python_version,
                            constraints,
                            policy,
                            current_version,
                            recommended_version,
                        )
            except InvalidVersion:
                logger.warning(
                    "%s: invalid current version %s, cannot recommend",
                    pkg_data.name,
                    current_version,
                )
                recommended_version = None
        else:
            # No current version means no major anchor: take the highest.
            candidates = self._candidates(
                pkg_data, python_version, None, constraints, policy
            )
            recommended_version, cooldown_skipped = self._apply_cooldown(
                pkg_data, candidates, None
            )

        metadata: Dict[str, Any] = {
            "dependencies": pkg_data.latest_dependencies,
            "latest_metadata": {
                "requires_python": pkg_data.latest_requires_python,
            },
        }

        if recommended_version:
            metadata["recommended_metadata"] = {
                "requires_python": pkg_data.python_requirements.get(
                    recommended_version
                ),
            }

        if current_version:
            metadata["current_metadata"] = {
                "requires_python": pkg_data.python_requirements.get(current_version),
            }

        times = pkg_data.upload_times
        return Package(
            name=pkg_data.name,
            current_version=current_version,
            latest_version=latest_version,
            recommended_version=recommended_version,
            metadata=metadata,
            versioning=scheme,
            held=held,
            ignored=policy.ignore,
            recommended_released=times.get(recommended_version or ""),
            current_released=times.get(current_version or ""),
            latest_released=times.get(latest_version or ""),
            cooldown_skipped=cooldown_skipped,
            major_available=major_available,
            major_capped=bool(major_available and self.allows_major(pkg_data.name)),
        )

    def _higher_major(
        self,
        pkg_data: PyPIPackageData,
        python_version: str,
        constraints: Optional[Sequence[Tuple[str, str]]],
        policy: PackagePolicy,
        current_version: str,
        recommended: str,
    ) -> Optional[str]:
        """Newest eligible version in a higher major than *recommended*, if any.

        Ignores ``max_update`` (that cap is why it was not applied) but keeps
        the user's declared bounds, Python compatibility and the cooldown, so
        it is only ever something the user could opt in to.
        """
        top, _ = self._apply_cooldown(
            pkg_data,
            self._candidates(pkg_data, python_version, None, constraints, policy),
            current_version,
        )
        if top is None:
            return None
        top_major = self._major_from_version(top)
        rec_major = self._major_from_version(recommended)
        if top_major is None or rec_major is None or top_major <= rec_major:
            return None
        return top

    @staticmethod
    def _candidates(
        pkg_data: PyPIPackageData,
        python_version: str,
        major: Optional[int],
        constraints: Optional[Sequence[Tuple[str, str]]],
        policy: PackagePolicy,
    ) -> List[str]:
        """Python-compatible, constraint-satisfying versions, newest first."""
        compatible = pkg_data.get_python_compatible_versions(
            python_version, major=major, include_prereleases=policy.allow_prerelease
        )
        return VersionChecker._filter_by_constraints(
            compatible, constraints, pkg_data.name
        )

    @staticmethod
    def _cap_update(
        candidates: List[str],
        current_version: str,
        max_update: Optional[str],
        scheme: str,
    ) -> List[str]:
        """Drop upgrades larger than *max_update*.

        Uses ``gating_type`` so calver ``year`` ranks as minor, like the CLI
        ``--max-update``/``--fail-on`` gates.
        """
        if not max_update:
            return candidates
        cap = update_rank(max_update)
        current = parse_version_lenient(current_version)
        kept = []
        for v in candidates:
            parsed = parse_version_lenient(v)
            if current is None or parsed is None or parsed <= current:
                kept.append(v)
            elif (
                update_rank(gating_type(get_update_type(current_version, v, scheme)))
                <= cap
            ):
                kept.append(v)
        return kept

    def restrict_versions(
        self,
        pkg_data: PyPIPackageData,
        versions: List[str],
        current_version: Optional[str],
        scheme: str = "semver",
    ) -> List[str]:
        """Apply hold/ignore, ``max_update`` and the cooldown to *versions*.

        Lets the conflict analyzer honour the same policy as the checker.
        Order is preserved; versions at or below *current_version* are never
        removed (they are not upgrades).
        """
        policy = self.policies.get(pkg_data.name) or PackagePolicy()
        current = parse_version_lenient(current_version)
        if (policy.hold and current_version) or policy.ignore:
            return [
                v
                for v in versions
                if current is not None
                and (p := parse_version_lenient(v)) is not None
                and p <= current
            ]
        if current_version:
            versions = self._cap_update(
                versions,
                current_version,
                self._cap_for(pkg_data.name, policy),
                scheme,
            )
        if self.min_age is None:
            return versions
        now = self._clock()
        kept = []
        for v in versions:
            p = parse_version_lenient(v)
            at_or_below = current is not None and p is not None and p <= current
            up = pkg_data.upload_times.get(v)
            if at_or_below or up is None or now - up >= self.min_age:
                kept.append(v)
        return kept

    def include_prereleases(self, name: str) -> bool:
        """Return whether the per-package policy allows pre-release candidates."""
        policy = self.policies.get(normalize_package_name(name))
        return bool(policy and policy.allow_prerelease)

    def _apply_cooldown(
        self,
        pkg_data: PyPIPackageData,
        candidates: List[str],
        current_version: Optional[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Pick the newest candidate outside the ``min_age`` window.

        Returns ``(recommended, skipped)``; *skipped* is the newer version the
        cooldown withheld. A fallback below *current_version* is never chosen
        (``None`` is returned so the caller stays put).
        """
        if not candidates:
            return None, None
        if self.min_age is None:
            return candidates[0], None

        now = self._clock()
        current = parse_version_lenient(current_version)
        for version in candidates:
            parsed = parse_version_lenient(version)
            if current is not None and parsed is not None and parsed <= current:
                break  # nothing at/above current is eligible
            uploaded = pkg_data.upload_times.get(version)
            if uploaded is None:
                # Fails open: an undated release cannot be aged. Warn once.
                if pkg_data.name not in self._warned_undated:
                    self._warned_undated.add(pkg_data.name)
                    logger.warning(
                        "%s: no upload date for %s; min_age cooldown treats "
                        "undated releases as old",
                        pkg_data.name,
                        version,
                    )
            elif now - uploaded < self.min_age:
                continue
            skipped = candidates[0] if version != candidates[0] else None
            if skipped:
                logger.debug(
                    "%s: %s withheld by min_age cooldown, using %s",
                    pkg_data.name,
                    skipped,
                    version,
                )
            return version, skipped
        return None, candidates[0]

    @staticmethod
    def _major_from_version(version: str) -> Optional[int]:
        """Return the major release component of *version*.

        Accepts a PEP 440 wildcard band (``2.*``) so a wildcard pin still
        anchors the major boundary.

        Args:
            version: Version string, or a wildcard band such as ``"2.*"``.

        Returns:
            The major release number, or ``None`` if there is no release part.

        Raises:
            InvalidVersion: *version* cannot be resolved to a major number.
        """
        parsed = parse_version_lenient(version)
        if parsed is None:
            raise InvalidVersion(f"Invalid version: '{version}'")

        return parsed.release[0] if parsed.release else None

    @staticmethod
    def _filter_by_constraints(
        versions: List[str],
        constraints: Optional[Sequence[Tuple[str, str]]],
        package_name: str,
    ) -> List[str]:
        """Drop candidate versions rejected by the requirement's own range.

        Upper bounds, exclusions and wildcard bands survive a rewrite of the
        line, so a violating recommendation would yield an unsatisfiable
        requirement (e.g. ``flask>=2.3.3,<2.3``).

        Args:
            versions: Candidate versions, highest first.
            constraints: Specifiers every candidate must satisfy. ``None`` or
                empty disables filtering.
            package_name: Used for debug logging only.

        Returns:
            The subset of *versions* satisfying *constraints*, order preserved.
        """
        if not constraints:
            return versions

        allowed = [
            version for version in versions if specs_allow_version(constraints, version)
        ]

        if len(allowed) != len(versions):
            logger.debug(
                "%s: %d of %d candidate version(s) excluded by declared "
                "constraint '%s'",
                package_name,
                len(versions) - len(allowed),
                len(versions),
                specs_to_string(constraints),
            )

        return allowed
