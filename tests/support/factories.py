"""Builders for depkeeper's domain models.

These are thin, keyword-only wrappers around the dataclasses. They exist to
keep test bodies focused on the *one* attribute under test: a test that cares
about extras should not have to spell out five unrelated fields, and a test
that cares about hashes should not silently inherit a version pin it never
declared.

Defaults are deliberately realistic (``requests``/``flask`` style values taken
from real releases) so that a failure message reads like production data.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

from depkeeper.models import Conflict, Package, Requirement
from depkeeper.models.conflict import ConflictSet

#: A ``(operator, version)`` pair as stored on :class:`Requirement`.
Spec = Tuple[str, str]


def make_requirement(
    name: str = "requests",
    *,
    specs: Optional[Sequence[Spec]] = None,
    extras: Optional[Sequence[str]] = None,
    markers: Optional[str] = None,
    url: Optional[str] = None,
    editable: bool = False,
    hashes: Optional[Sequence[str]] = None,
    comment: Optional[str] = None,
    line_number: int = 1,
    raw_line: Optional[str] = None,
    source_file: Optional[str] = None,
) -> Requirement:
    """Build a :class:`Requirement` with only the fields a test cares about.

    Args:
        name: Distribution name, used verbatim (the model does not normalise).
        specs: ``(operator, version)`` pairs in declaration order. Order is
            significant — the writer renders them in this order.
        extras: PEP 508 extras, e.g. ``["redis"]``.
        markers: PEP 508 environment marker expression.
        url: Direct reference (VCS/URL/local path). When set, the model omits
            version specifiers from the rendered line.
        editable: Whether the line carried ``-e``.
        hashes: ``--hash`` digests, e.g. ``["sha256:..."]``.
        comment: Inline comment text without the leading ``#``.
        line_number: 1-indexed position in the source file.
        raw_line: Original unmodified line text.
        source_file: Path of the file this requirement was parsed from.

    Returns:
        A fully constructed :class:`Requirement`.
    """
    return Requirement(
        name=name,
        specs=list(specs or []),
        extras=list(extras or []),
        markers=markers,
        url=url,
        editable=editable,
        hashes=list(hashes or []),
        comment=comment,
        line_number=line_number,
        raw_line=raw_line,
        source_file=source_file,
    )


def make_package(
    name: str = "requests",
    *,
    current: Optional[str] = None,
    latest: Optional[str] = None,
    recommended: Optional[str] = None,
    requires_python: Optional[dict] = None,
    conflicts: Optional[Sequence[Conflict]] = None,
) -> Package:
    """Build a :class:`Package` in a specific lifecycle state.

    Args:
        name: Distribution name (normalised by the model to PEP 503 form).
        current: Version currently declared in the requirements file.
        latest: Newest version published upstream (informational only).
        recommended: Version depkeeper would apply. ``None`` models the
            "metadata unavailable" stub the checker returns on a PyPI failure.
        requires_python: Mapping of ``"current"``/``"latest"``/``"recommended"``
            to a ``requires_python`` specifier, expanded into the nested
            ``*_metadata`` shape the model reads.
        conflicts: Conflicts to attach.

    Returns:
        A fully constructed :class:`Package`.
    """
    metadata = {
        f"{key}_metadata": {"requires_python": value}
        for key, value in (requires_python or {}).items()
    }

    return Package(
        name=name,
        current_version=current,
        latest_version=latest,
        recommended_version=recommended,
        metadata=metadata,
        conflicts=list(conflicts or []),
    )


def make_conflict(
    source: str,
    required_spec: str,
    target: str,
    *,
    source_version: Optional[str] = None,
    conflicting_version: str = "0.0.0",
) -> Conflict:
    """Build a :class:`Conflict` using the order it reads in prose.

    ``make_conflict("flask", ">=2.2,<2.3", "werkzeug")`` mirrors the sentence
    "flask requires werkzeug>=2.2,<2.3".

    Args:
        source: Package that declares the dependency.
        required_spec: Specifier the source demands of the target.
        target: Package being constrained.
        source_version: Version of the source that declares *required_spec*.
            Conflict liveness checks compare against this, so scenarios that
            exercise the resolver should always set it.
        conflicting_version: Target version that violates *required_spec*.

    Returns:
        A frozen :class:`Conflict`.
    """
    return Conflict(
        source_package=source,
        target_package=target,
        required_spec=required_spec,
        conflicting_version=conflicting_version,
        source_version=source_version,
    )


def make_conflict_set(package: str, conflicts: Iterable[Conflict]) -> ConflictSet:
    """Build a :class:`ConflictSet` for *package* from *conflicts*."""
    return ConflictSet(package_name=package, conflicts=list(conflicts))


def specs(*pairs: str) -> List[Spec]:
    """Parse a shorthand specifier list, e.g. ``specs(">=5.0", "<6.0")``.

    Keeps parameterised cases readable by letting them declare specifiers the
    way a requirements file spells them rather than as tuples.

    Args:
        *pairs: Specifier strings such as ``">=2.31.0"`` or ``"==1.26.18"``.

    Returns:
        ``(operator, version)`` pairs in the given order.

    Raises:
        ValueError: A specifier did not start with a known operator.
    """
    # Longest operators first so "==" is not mistaken for "=".
    operators = ("===", "==", "!=", "<=", ">=", "~=", "<", ">")
    parsed: List[Spec] = []

    for pair in pairs:
        for operator in operators:
            if pair.startswith(operator):
                parsed.append((operator, pair[len(operator):]))
                break
        else:
            raise ValueError(f"Not a version specifier: {pair!r}")

    return parsed
