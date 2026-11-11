"""Tests for update selection (``_find_updates``)."""

from __future__ import annotations

from typing import Any

from depkeeper.commands.update import _find_hashed_updates, _find_updates
from depkeeper.models import Package, Requirement


def _pkg(name: str, *, current: str | None, recommended: str | None) -> Package:
    return Package(
        name=name,
        current_version=current,
        recommended_version=recommended,
    )


def test_editable_vcs_requirement_is_skipped() -> None:
    """an editable VCS requirement must never be selected for update."""
    req = Requirement(
        name="devpkg",
        specs=[],
        url="git+https://github.com/user/repo.git#egg=devpkg",
        editable=True,
    )
    pkg = _pkg("devpkg", current=None, recommended="9.9.9")

    assert _find_updates([pkg], [req]) == []


def test_non_editable_url_requirement_is_skipped() -> None:
    """a plain URL requirement (non-editable) is also skipped."""
    req = Requirement(
        name="mypackage",
        specs=[],
        url="https://github.com/user/repo/archive/main.zip#egg=mypackage",
    )
    pkg = _pkg("mypackage", current=None, recommended="2.0.0")

    assert _find_updates([pkg], [req]) == []


def test_local_path_requirement_is_skipped() -> None:
    """a local-path reference (url set) is skipped."""
    req = Requirement(
        name="mypackage",
        specs=[],
        url="file:///home/user/mypackage",
        editable=True,
    )
    pkg = _pkg("mypackage", current=None, recommended="1.2.3")

    assert _find_updates([pkg], [req]) == []


def test_regular_pinned_requirement_still_updates() -> None:
    """Normal PyPI requirements are unaffected by the skip."""
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


def test_target_excluded_by_upper_bound_is_skipped() -> None:
    """A target above the declared upper bound is not written."""
    req = Requirement(name="flask", specs=[(">=", "2.0"), ("<", "2.3")])
    pkg = _pkg("flask", current="2.0", recommended="2.3.3")

    assert _find_updates([pkg], [req]) == []


def test_target_excluded_by_exclusion_is_skipped() -> None:
    """a version the file explicitly excludes is never written."""
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
    """A target already covered by the declared floor is not an update."""
    req = Requirement(name="flask", specs=[("~=", "2.3")])
    pkg = _pkg("flask", current="2.3", recommended="2.3.3")

    assert _find_updates([pkg], [req]) == []


def test_compatible_release_still_updates_when_floor_moves() -> None:
    """Guard: the no-op skip must not block a real ``~=`` bump."""
    req = Requirement(name="flask", specs=[("~=", "2.0")])
    pkg = _pkg("flask", current="2.0", recommended="2.3.3")

    assert _find_updates([pkg], [req]) == [(req, pkg, "2.3.3")]


def test_dotted_requirement_matches_its_package() -> None:
    """A dotted requirement name matches its normalised package."""
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
    req_unbounded = Requirement(
        name="requests", specs=[("==", "2.25.0")], line_number=3
    )

    pkg_bounded = _pkg("requests", current="2.20", recommended="2.34.2")
    pkg_unbounded = _pkg("requests", current="2.25.0", recommended="2.34.2")

    updates = _find_updates([pkg_bounded, pkg_unbounded], [req_bounded, req_unbounded])

    assert updates == [(req_unbounded, pkg_unbounded, "2.34.2")]


def _pair(text: str, latest: str, recommended: str, current: str) -> Any:
    from depkeeper.core import RequirementsParser

    reqs = RequirementsParser().parse_string(text)
    pkg = Package(
        name=reqs[0].name,
        current_version=current,
        latest_version=latest,
        recommended_version=recommended,
    )
    return [pkg], reqs


def test_ignore_skips_package() -> None:
    pkgs, reqs = _pair("click==8.0.0\n", "8.1.7", "8.1.7", "8.0.0")
    assert _find_updates(pkgs, reqs, ignore={"click"}) == []
    assert len(_find_updates(pkgs, reqs)) == 1


def test_max_update_filters_by_level() -> None:
    pkgs, reqs = _pair("click==8.0.0\n", "8.1.7", "8.1.7", "8.0.0")
    assert _find_updates(pkgs, reqs, max_update="patch") == []
    assert len(_find_updates(pkgs, reqs, max_update="minor")) == 1


def test_bare_name_in_pyproject_or_conda_is_pinned_only_with_pin() -> None:
    for fmt in ("pyproject", "conda"):
        req = Requirement(name="wheel", specs=[], source_format=fmt)
        pkg = _pkg("wheel", current=None, recommended="1.0")
        assert _find_updates([pkg], [req]) == []
        assert len(_find_updates([pkg], [req], pin=True)) == 1


def test_bare_name_in_requirements_is_still_pinned() -> None:
    req = Requirement(name="wheel", specs=[], source_format="requirements.txt")
    assert (
        len(_find_updates([_pkg("wheel", current=None, recommended="1.0")], [req])) == 1
    )
