"""Version comparison utilities for depkeeper.

Helpers for classifying version changes and for rewriting PEP 440 version
specifier sets. All parsing is delegated to ``packaging`` so depkeeper agrees
with pip about what a version means.
"""

from __future__ import annotations

import datetime as _dt
from typing import Iterable, List, Optional, Sequence, Set, Tuple
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version, parse

#: Operators that describe the *floor* of an accepted version range. These are
#: the only specifiers that are rewritten when a requirement is updated in
#: range-preserving mode.
LOWER_BOUND_OPERATORS: Tuple[str, ...] = (">=", ">", "~=")

#: Operators that pin a requirement to a single version.
EXACT_OPERATORS: Tuple[str, ...] = ("==", "===")

#: PEP 440 requires ``~=`` to carry at least two release components.
_MIN_COMPATIBLE_RELEASE_PARTS = 2

#: A parsed ``(operator, version)`` specifier pair.
Spec = Tuple[str, str]

#: Accepted ``versioning`` settings.
VERSIONING_CHOICES: Tuple[str, ...] = ("auto", "semver", "calver")

#: Update labels ordered by severity; calver labels map onto the semver ranks.
UPDATE_RANK = {"patch": 0, "month": 1, "minor": 1, "year": 2, "major": 2}

_FIRST_CALVER_YEAR = 1990


def update_rank(update_type: str) -> int:
    """Return the severity rank of an update label, or -1 if unranked.

    Ranks are patch 0, minor/month 1, major/year 2.
    """
    return UPDATE_RANK.get(update_type, -1)


def gating_type(update_type: str) -> str:
    """Map an update label onto the semver label used by ``--fail-on``/``--max-update``.

    A calver ``year`` change is at most ``minor``-equivalent (it is not a
    breaking boundary); ``month`` is ``minor``. Other labels pass through.
    """
    return {"year": "minor", "month": "minor"}.get(update_type, update_type)


def _leading_is_year(version: str) -> bool:
    """Return whether the first release component looks like a calendar year."""
    try:
        release = Version(version).release
    except InvalidVersion:
        return False
    return bool(release) and (
        _FIRST_CALVER_YEAR <= release[0] <= _dt.date.today().year + 1
    )


def _history_is_yy_m(versions: Sequence[str]) -> bool:
    """Strong evidence of ``YY.M`` calver: every stable release looks like it."""
    yy = _dt.date.today().year % 100
    parsed = []
    for raw in versions:
        try:
            v = Version(raw)
        except InvalidVersion:
            continue
        if not v.is_prerelease:
            parsed.append(v.release)
    if len(parsed) < 5:
        return False
    if any(
        len(r) < 2 or not (15 <= r[0] <= yy + 1) or not (1 <= r[1] <= 12)
        for r in parsed
    ):
        return False
    return len({r[0] for r in parsed}) >= 2


def detect_versioning(
    mode: str = "auto",
    current_version: Optional[str] = None,
    history: Sequence[str] = (),
) -> str:
    """Resolve a ``versioning`` setting to ``"semver"`` or ``"calver"``.

    ``"semver"``/``"calver"`` are returned as-is. ``"auto"`` picks calver when
    the current (else newest historical) version leads with a plausible 4-digit
    year (1990..this year+1, e.g. ``2024.8.30``), or when the whole release
    history strongly looks like ``YY.M`` (e.g. black ``24.2.0``). A lone
    ``23.1.0`` is never guessed to be calver.
    """
    if mode in ("semver", "calver"):
        return mode
    sample = current_version or (history[0] if history else None)
    if sample and _leading_is_year(sample):
        return "calver"
    return "calver" if _history_is_yy_m(history) else "semver"


def get_update_type(
    current_version: Optional[str],
    target_version: Optional[str],
    versioning: str = "semver",
) -> str:
    """Determine the semantic update type between two versions.

    Args:
        current_version: Currently installed version, or ``None`` if not installed.
        target_version: Target version to compare against.
        versioning: ``"semver"`` or ``"calver"``; selects the classification
            scheme for upgrades.

    Returns:
        One of:
            - ``"new"``       : No current version exists
            - ``"same"``      : Versions are identical
            - ``"downgrade"`` : Target version is lower than current
            - ``"major"``     : Major version change
            - ``"minor"``     : Minor version change
            - ``"patch"``     : Patch-level change
            - ``"year"`` / ``"month"`` / ``"patch"`` : calver
              (*versioning* ``"calver"``): leading year, second, later part
            - ``"update"``    : Update that cannot be classified further
            - ``"unknown"``   : Invalid or unsupported version comparison

    Example::
        >>> get_update_type("1.0.0", "2.0.0")
        'major'
        >>> get_update_type(None, "1.0.0")
        'new'
        >>> get_update_type("1.2.3", "1.2.3")
        'same'
    """
    if current_version is None and target_version is None:
        return "unknown"

    if current_version is None:
        return "new"

    if target_version is None:
        return "unknown"

    try:
        current = parse(current_version)
        target = parse(target_version)

        if target == current:
            return "same"

        if target < current:
            return "downgrade"

        if versioning == "calver":
            return _classify_calver(current, target)
        return _classify_upgrade(current, target)

    except InvalidVersion:
        return "unknown"


def _classify_calver(current: Version, target: Version) -> str:
    """Classify an upgrade of calendar-versioned releases."""
    c, t = _normalize_release(current), _normalize_release(target)
    if c[0] != t[0]:
        return "year"
    if c[1] != t[1]:
        return "month"
    if c[2] != t[2]:
        return "patch"
    return "update"


def _classify_upgrade(current: Version, target: Version) -> str:
    """Classify an upgrade between two valid versions.

    Args:
        current: Lower of the two versions.
        target: Higher of the two versions.

    Returns:
        ``"major"``, ``"minor"``, ``"patch"``, or ``"update"`` when the
        release segments are identical (pre-release promotions and
        metadata-only changes).
    """
    current_major, current_minor, current_patch = _normalize_release(current)
    target_major, target_minor, target_patch = _normalize_release(target)

    if current_major != target_major:
        return "major"

    if current_minor != target_minor:
        return "minor"

    if current_patch != target_patch:
        return "patch"

    # Pre-release promotion or metadata-only change.
    return "update"


def _normalize_release(version: Version) -> Tuple[int, int, int]:
    """Pad a version's release segment to a ``(major, minor, patch)`` triple.

    Missing components default to ``0`` so ``2`` and ``2.0.0`` compare equal.
    """
    release = version.release
    major = release[0] if len(release) > 0 else 0
    minor = release[1] if len(release) > 1 else 0
    patch = release[2] if len(release) > 2 else 0
    return major, minor, patch


def parse_version_lenient(version: Optional[str]) -> Optional[Version]:
    """Parse *version*, tolerating a PEP 440 wildcard band as its floor.

    A concrete version (``2.3.3``) parses exactly as
    `parse` would. A wildcard band (``2.*``) is not
    itself a valid `Version` — a wildcard is only meaningful inside a
    `SpecifierSet` — so it is resolved from its
    release prefix instead, giving ``2.*`` the same comparable value as
    ``2``. This lets callers that need a comparable version (major-boundary
    checks, "is an update available") treat a wildcard exact pin
    (``pkg==2.*``) sensibly instead of as unparseable.

    Args:
        version: Version string, wildcard band, or ``None``.

    Returns:
        The parsed `Version`, or ``None`` when *version* is ``None``
        or cannot be resolved to a version by either path.

    Example::
        >>> parse_version_lenient("2.3.3") == Version("2.3.3")
        True
        >>> parse_version_lenient("2.*") == Version("2")
        True
        >>> parse_version_lenient("not-a-version") is None
        True
    """
    if version is None:
        return None

    try:
        return Version(version)
    except InvalidVersion:
        pass

    if "*" not in version:
        return None

    prefix = version.rstrip("*").rstrip(".")
    if not prefix:
        return None

    try:
        return Version(prefix)
    except InvalidVersion:
        return None


def specs_to_string(specs: Iterable[Spec]) -> str:
    """Render ``(operator, version)`` pairs as a PEP 440 specifier string.

    Args:
        specs: Specifier pairs in declaration order.

    Returns:
        Comma-joined specifier string, e.g. ``">=2.0,<3.0"``. Empty when
        *specs* is empty.

    Example::
        >>> specs_to_string([(">=", "2.0"), ("<", "3.0")])
        '>=2.0,<3.0'
        >>> specs_to_string([])
        ''
    """
    return ",".join(f"{operator}{version}" for operator, version in specs)


def is_lower_bound(operator: str) -> bool:
    """Return whether *operator* constrains only the floor of a range.

    Args:
        operator: A PEP 440 comparison operator.

    Returns:
        ``True`` for ``>=``, ``>`` and ``~=``.

    Example::
        >>> is_lower_bound(">=")
        True
        >>> is_lower_bound("<")
        False
    """
    return operator in LOWER_BOUND_OPERATORS


def retained_specs(specs: Iterable[Spec]) -> List[Spec]:
    """Return the specifiers that survive a version rewrite unchanged.

    A version update only moves the *floor* of a requirement. Upper bounds
    (``<``, ``<=``), exclusions (``!=``) and wildcard bands (``==2.*``) are
    deliberate compatibility statements and are carried through verbatim.
    Consequently any version depkeeper proposes must satisfy them.

    Args:
        specs: The requirement's declared specifier pairs.

    Returns:
        The subset of *specs* that `rewrite_version_specs` preserves.

    Example::
        >>> retained_specs([(">=", "5.0"), ("<", "6.0")])
        [('<', '6.0')]
        >>> retained_specs([("==", "2.20.0")])
        []
        >>> retained_specs([("==", "2.*")])
        [('==', '2.*')]
    """
    return [
        (operator, version)
        for operator, version in specs
        if _is_retained(operator, version)
    ]


def specs_allow_version(specs: Iterable[Spec], version: str) -> bool:
    """Check whether *version* satisfies every specifier in *specs*.

    Mirrors pip's permissive behavior: an unparseable specifier or version
    is treated as "allowed" rather than silently discarding an update.
    Pre-releases are accepted so that an explicitly requested pre-release
    target is not rejected by `SpecifierSet`
    defaults.

    Args:
        specs: Specifier pairs to evaluate.
        version: Candidate version string.

    Returns:
        ``True`` when the version satisfies all specifiers (or the inputs
        cannot be interpreted), ``False`` otherwise.

    Example::
        >>> specs_allow_version([("<", "3.0")], "2.9.0")
        True
        >>> specs_allow_version([("<", "3.0")], "3.1.0")
        False
        >>> specs_allow_version([], "1.0.0")
        True
    """
    specifier_string = specs_to_string(specs)
    if not specifier_string:
        return True

    try:
        specifier_set = SpecifierSet(specifier_string)
    except InvalidSpecifier:
        return True

    # Parsed explicitly rather than passed as a string: packaging 26.0
    # changed contains() to return False for a bad version instead of
    # raising, which would silently veto it instead of permitting it.
    try:
        parsed_version = Version(version)
    except InvalidVersion:
        return True

    return specifier_set.contains(parsed_version, prereleases=True)


def rewrite_version_specs(specs: Sequence[Spec], new_version: str) -> List[Spec]:
    """Rewrite a specifier set so it targets *new_version*.

    Only the specifiers that describe the currently-selected version are
    changed:

    - ``>=`` and ``>`` become ``>=new_version`` (``>`` is widened to ``>=``
      so the newly selected version itself remains installable).
    - ``~=`` keeps the compatible-release form and the author's chosen
      precision, e.g. ``~=2.0`` with ``2.3.3`` becomes ``~=2.3``.
    - A non-wildcard ``==`` / ``===`` pin is repinned to *new_version*.
    - Upper bounds, exclusions and wildcard bands are preserved verbatim.

    A requirement with no specifiers gains an exact pin, matching the
    "add a version pin" behavior of the update command. A requirement that
    declares only upper bounds/exclusions gains an explicit ``>=`` floor so
    the selected version is actually recorded.

    Args:
        specs: The requirement's declared specifier pairs, in order.
        new_version: The version to move the requirement to.

    Returns:
        A new list of specifier pairs. Duplicates introduced by the rewrite
        (e.g. ``>=2.0,>2.1`` collapsing to two identical floors) are removed
        while preserving order.

    Example::
        >>> rewrite_version_specs([(">=", "5.0"), ("<", "6.0")], "5.5.3")
        [('>=', '5.5.3'), ('<', '6.0')]
        >>> rewrite_version_specs([("~=", "2.0")], "2.3.3")
        [('~=', '2.3')]
        >>> rewrite_version_specs([], "1.0.0")
        [('==', '1.0.0')]
    """
    if not specs:
        return [("==", new_version)]

    rewritten: List[Spec] = []
    replaced = False

    for operator, version in specs:
        if operator == "~=":
            rewritten.append(("~=", _match_release_precision(new_version, version)))
            replaced = True
        elif operator in (">=", ">"):
            rewritten.append((">=", new_version))
            replaced = True
        elif operator in EXACT_OPERATORS and not _has_wildcard(version):
            rewritten.append((operator, new_version))
            replaced = True
        else:
            rewritten.append((operator, version))

    if not replaced:
        # Only upper bounds / exclusions / wildcard bands were declared, so
        # nothing recorded the selected version. Add an explicit floor.
        rewritten.append((">=", new_version))

    return _dedupe_specs(rewritten)


def _is_retained(operator: str, version: str) -> bool:
    """Return whether a single specifier survives a rewrite unchanged."""
    if is_lower_bound(operator):
        return False
    if operator in EXACT_OPERATORS:
        # `==2.*` is a compatibility band, not a pin, so it is preserved.
        return _has_wildcard(version)
    return True


def _has_wildcard(version: str) -> bool:
    """Return whether a specifier version uses PEP 440 wildcard matching."""
    return "*" in version


def _dedupe_specs(specs: Iterable[Spec]) -> List[Spec]:
    """Drop duplicate specifier pairs while preserving first-seen order."""
    seen: Set[Spec] = set()
    result: List[Spec] = []
    for spec in specs:
        if spec not in seen:
            seen.add(spec)
            result.append(spec)
    return result


def _match_release_precision(new_version: str, template_version: str) -> str:
    """Truncate *new_version* to the release precision of *template_version*.

    Keeps the author's chosen ``~=`` granularity: ``~=2.0`` (two components)
    updated to ``2.3.3`` yields ``2.3``, preserving the ``2.*`` band while
    raising the floor.
    """
    try:
        template = parse(template_version)
        target = parse(new_version)
    except InvalidVersion:
        return new_version

    precision = max(_MIN_COMPATIBLE_RELEASE_PARTS, len(template.release))
    release = list(target.release[:precision])
    release.extend([0] * (precision - len(release)))

    rendered = ".".join(str(part) for part in release)
    return f"{target.epoch}!{rendered}" if target.epoch else rendered
