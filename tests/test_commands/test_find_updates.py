"""Tests for update selection (``_find_updates``).

Primary purpose: guard against regression C2 — direct references
(VCS/URL/local-path/editable installs) are not version-managed by PyPI
metadata. Selecting them for update appends a version specifier to the URL,
producing an uninstallable line such as
``-e git+https://...#egg=pkg==9.9.9``. They must be skipped entirely.
"""

from __future__ import annotations

from depkeeper.commands.update import _find_hashed_updates, _find_updates
from depkeeper.models import Package, Requirement


def _pkg(name: str, *, current: str | None, recommended: str | None) -> Package:
    return Package(
        name=name,
        current_version=current,
        recommended_version=recommended,
    )


def test_editable_vcs_requirement_is_skipped() -> None:
    """C2: an editable VCS requirement must never be selected for update."""
    req = Requirement(
        name="devpkg",
        specs=[],
        url="git+https://github.com/user/repo.git#egg=devpkg",
        editable=True,
    )
    pkg = _pkg("devpkg", current=None, recommended="9.9.9")

    assert _find_updates([pkg], [req]) == []


def test_non_editable_url_requirement_is_skipped() -> None:
    """C2: a plain URL requirement (non-editable) is also skipped."""
    req = Requirement(
        name="mypackage",
        specs=[],
        url="https://github.com/user/repo/archive/main.zip#egg=mypackage",
    )
    pkg = _pkg("mypackage", current=None, recommended="2.0.0")

    assert _find_updates([pkg], [req]) == []


def test_local_path_requirement_is_skipped() -> None:
    """C2: a local-path reference (url set) is skipped."""
    req = Requirement(
        name="mypackage",
        specs=[],
        url="file:///home/user/mypackage",
        editable=True,
    )
    pkg = _pkg("mypackage", current=None, recommended="1.2.3")

    assert _find_updates([pkg], [req]) == []


def test_regular_pinned_requirement_still_updates() -> None:
    """Regression guard: normal PyPI requirements are unaffected by the skip."""
    req = Requirement(name="flask", specs=[("==", "2.0.0")])
    pkg = _pkg("flask", current="2.0.0", recommended="2.3.3")

    updates = _find_updates([pkg], [req])

    assert updates == [(req, pkg, "2.3.3")]


def test_mixed_set_updates_only_pypi_requirements() -> None:
    """Only PyPI-managed requirements are selected from a mixed file."""
    url_req = Requirement(
        name="devpkg",
        specs=[],
        url="git+https://github.com/user/repo.git#egg=devpkg",
        editable=True,
    )
    pinned_req = Requirement(name="flask", specs=[("==", "2.0.0")])

    url_pkg = _pkg("devpkg", current=None, recommended="9.9.9")
    pinned_pkg = _pkg("flask", current="2.0.0", recommended="2.3.3")

    updates = _find_updates([url_pkg, pinned_pkg], [url_req, pinned_req])

    assert updates == [(pinned_req, pinned_pkg, "2.3.3")]


def test_find_hashed_updates_only_returns_hashed_requirements() -> None:
    """Hash guard helper should target only requirements carrying hashes."""
    hashed_req = Requirement(
        name="requests",
        specs=[("==", "2.28.0")],
        hashes=["sha256:abc123"],
    )
    plain_req = Requirement(name="flask", specs=[("==", "2.0.0")])

    hashed_pkg = _pkg("requests", current="2.28.0", recommended="2.31.0")
    plain_pkg = _pkg("flask", current="2.0.0", recommended="2.3.3")

    updates = [
        (hashed_req, hashed_pkg, "2.31.0"),
        (plain_req, plain_pkg, "2.3.3"),
    ]

    assert _find_hashed_updates(updates) == [(hashed_req, hashed_pkg, "2.31.0")]


# ---------------------------------------------------------------------------
# M5 — declared ranges are preserved, so targets they exclude must be skipped
# ---------------------------------------------------------------------------


def test_target_excluded_by_upper_bound_is_skipped() -> None:
    """M5: writing 2.3.3 under ``<2.3`` would yield ``flask>=2.3.3,<2.3``.

    The conflict resolver can override the checker's constraint-filtered
    recommendation, so the writer input is validated as a second gate.
    """
    req = Requirement(name="flask", specs=[(">=", "2.0"), ("<", "2.3")])
    pkg = _pkg("flask", current="2.0", recommended="2.3.3")

    assert _find_updates([pkg], [req]) == []


def test_target_excluded_by_exclusion_is_skipped() -> None:
    """M5: a version the file explicitly excludes is never written."""
    req = Requirement(name="flask", specs=[(">=", "2.0"), ("!=", "2.3.3")])
    pkg = _pkg("flask", current="2.0", recommended="2.3.3")

    assert _find_updates([pkg], [req]) == []


def test_target_inside_declared_range_still_updates() -> None:
    """Guard: a target that honours the declared cap is still selected."""
    req = Requirement(name="celery", specs=[(">=", "5.0"), ("<", "6.0")])
    pkg = _pkg("celery", current="5.0", recommended="5.5.3")

    assert _find_updates([pkg], [req]) == [(req, pkg, "5.5.3")]


def test_pin_mode_ignores_declared_constraints() -> None:
    """``--pin`` discards the declared range, so nothing blocks the update."""
    req = Requirement(name="flask", specs=[(">=", "2.0"), ("<", "2.3")])
    pkg = _pkg("flask", current="2.0", recommended="2.3.3")

    assert _find_updates([pkg], [req], pin=True) == [(req, pkg, "2.3.3")]


def test_noop_rewrite_is_skipped() -> None:
    """A target already covered by the declared floor is not an update.

    ``~=2.3`` keeps selecting 2.3.3 at the author's two-component precision,
    so without this guard the command would never converge.
    """
    req = Requirement(name="flask", specs=[("~=", "2.3")])
    pkg = _pkg("flask", current="2.3", recommended="2.3.3")

    assert _find_updates([pkg], [req]) == []


def test_compatible_release_still_updates_when_floor_moves() -> None:
    """Guard: the no-op skip must not block a real ``~=`` bump."""
    req = Requirement(name="flask", specs=[("~=", "2.0")])
    pkg = _pkg("flask", current="2.0", recommended="2.3.3")

    assert _find_updates([pkg], [req]) == [(req, pkg, "2.3.3")]


# ---------------------------------------------------------------------------
# M9 — requirement/package matching uses one canonical (PEP 503) name
# ---------------------------------------------------------------------------


def test_dotted_requirement_matches_its_package() -> None:
    """``Requirement`` does not self-normalise, but ``Package`` does.

    Matching on bare ``.lower()`` split ``zope.interface`` from
    ``zope-interface`` and silently dropped the update.
    """
    req = Requirement(name="zope.interface", specs=[("==", "5.4.0")])
    pkg = _pkg("zope.interface", current="5.4.0", recommended="5.5.2")

    assert pkg.name == "zope-interface"
    assert _find_updates([pkg], [req]) == [(req, pkg, "5.5.2")]


def test_underscore_requirement_matches_its_package() -> None:
    """Baseline: the pre-existing underscore case must not regress."""
    req = Requirement(name="Flask_Login", specs=[("==", "0.6.0")])
    pkg = _pkg("Flask_Login", current="0.6.0", recommended="0.6.3")

    assert _find_updates([pkg], [req]) == [(req, pkg, "0.6.3")]


def test_unrelated_package_still_does_not_match() -> None:
    """Guard: canonicalisation must not fabricate matches."""
    req = Requirement(name="flask", specs=[("==", "2.0.0")])
    pkg = _pkg("django", current="4.0.0", recommended="4.2.0")

    assert _find_updates([pkg], [req]) == []


# ---------------------------------------------------------------------------
# Duplicate requirement lines must each match their own package.
# ---------------------------------------------------------------------------


def test_duplicate_requirement_lines_each_produce_their_own_update() -> None:
    """Two lines pinning the same package must both be selected for update."""
    req_line1 = Requirement(name="click", specs=[("==", "8.0.0")], line_number=1)
    req_line3 = Requirement(name="click", specs=[("==", "8.0.0")], line_number=3)

    pkg_line1 = _pkg("click", current="8.0.0", recommended="8.4.2")
    pkg_line3 = _pkg("click", current="8.0.0", recommended="8.4.2")

    updates = _find_updates([pkg_line1, pkg_line3], [req_line1, req_line3])

    assert updates == [
        (req_line1, pkg_line1, "8.4.2"),
        (req_line3, pkg_line3, "8.4.2"),
    ]
    assert updates[0][0].line_number == 1
    assert updates[1][0].line_number == 3


def test_duplicate_requirements_with_different_constraints_use_their_own() -> None:
    """Each duplicate must be checked against its own declared constraints."""
    req_bounded = Requirement(
        name="requests", specs=[(">=", "2.20"), ("<", "2.32")], line_number=1
    )
    req_unbounded = Requirement(name="requests", specs=[("==", "2.25.0")], line_number=3)

    pkg_bounded = _pkg("requests", current="2.20", recommended="2.34.2")
    pkg_unbounded = _pkg("requests", current="2.25.0", recommended="2.34.2")

    updates = _find_updates(
        [pkg_bounded, pkg_unbounded], [req_bounded, req_unbounded]
    )

    assert updates == [(req_unbounded, pkg_unbounded, "2.34.2")]
