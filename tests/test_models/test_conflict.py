"""Tests for :class:`Conflict` and :class:`ConflictSet`.

A conflict is depkeeper's record of "package A, at the version we intend to
install, forbids the version of package B we intend to install". Two properties
matter:

1. **Identity.** Conflict endpoints are matched against ``Package.name`` keys.
   If ``zope.interface`` and ``zope-interface`` are not the same identity, a
   real conflict is silently dropped and depkeeper writes a broken file.
2. **Arithmetic.** ``get_max_compatible_version`` intersects *every* constraint
   on a package. Getting it wrong by one version is the difference between a
   working install and a runtime ``ImportError``.

The scenarios below are drawn from real dependency graphs, because both
properties only get interesting once several packages constrain the same
target with overlapping — not identical — ranges.
"""

from __future__ import annotations

from typing import List, Optional

import pytest

from depkeeper.models.conflict import ConflictSet
from tests.support.factories import make_conflict, make_conflict_set

#: urllib3's real published history, newest last. Three of these sit in the
#: 1.26 series and two in 2.x, which is what makes ``<2.0`` style caps — very
#: common in the wild — actually discriminating.
URLLIB3_VERSIONS = ["1.25.11", "1.26.5", "1.26.18", "2.0.7", "2.2.2"]


# ---------------------------------------------------------------------------
# Conflict
# ---------------------------------------------------------------------------


class TestConflictIdentity:
    """Endpoints must be comparable to the keys used everywhere else."""

    @pytest.mark.parametrize(
        ("declared", "canonical"),
        [
            ("Django", "django"),
            ("zope.interface", "zope-interface"),
            ("ruamel_yaml", "ruamel-yaml"),
            ("typing_Extensions", "typing-extensions"),
            ("backports.zoneinfo", "backports-zoneinfo"),
        ],
        ids=["case", "dot", "underscore", "mixed", "dotted-namespace"],
    )
    def test_endpoints_are_normalised_to_pep503(
        self, declared: str, canonical: str
    ) -> None:
        """PyPI metadata, requirements files and the CLI all spell names
        differently; the conflict must land on the canonical key regardless.
        """
        conflict = make_conflict(declared, ">=1.0", declared)

        assert conflict.source_package == canonical
        assert conflict.target_package == canonical

    def test_conflicts_differing_only_in_spelling_are_equal(self) -> None:
        """Otherwise the same conflict is reported twice in the summary."""
        from_pypi_metadata = make_conflict("Zope.Interface", ">=6.0", "SQLAlchemy")
        from_requirements = make_conflict("zope-interface", ">=6.0", "sqlalchemy")

        assert from_pypi_metadata == from_requirements

    def test_conflicts_differing_in_specifier_are_not_equal(self) -> None:
        """Guard: normalisation must not flatten genuinely different records."""
        assert make_conflict("flask", ">=2.2,<2.3", "werkzeug") != make_conflict(
            "flask", ">=2.3.7", "werkzeug"
        )

    def test_conflicts_are_immutable(self) -> None:
        """Conflicts are cached and shared across resolution passes.

        A mutable conflict could be rewritten by one pass and then re-evaluated
        as if it had always said something else.
        """
        conflict = make_conflict("flask", ">=2.3.7", "werkzeug")

        with pytest.raises(AttributeError):
            conflict.required_spec = ">=3.0"  # type: ignore[misc]


class TestConflictRendering:
    """Conflict text reaches CLI output and JSON consumers."""

    def test_display_string_names_the_source_version_when_known(self) -> None:
        """Without the version the user cannot tell which release imposed it."""
        conflict = make_conflict(
            "flask", ">=2.3.7", "werkzeug", source_version="2.3.3"
        )

        assert conflict.to_display_string() == "flask==2.3.3 requires werkzeug>=2.3.7"

    def test_display_string_omits_an_unknown_source_version(self) -> None:
        conflict = make_conflict("flask", ">=2.3.7", "werkzeug")

        assert conflict.to_display_string() == "flask requires werkzeug>=2.3.7"

    def test_short_string_drops_the_target_for_table_cells(self) -> None:
        """The target is the table row, so repeating it wastes column width."""
        conflict = make_conflict(
            "celery", ">=5.3.4,<6.0", "kombu", source_version="5.3.6"
        )

        assert conflict.to_short_string() == "celery needs >=5.3.4,<6.0"

    def test_str_is_the_display_string(self) -> None:
        conflict = make_conflict(
            "django", "<4,>=3.6.0", "asgiref", source_version="4.2.11"
        )

        assert str(conflict) == conflict.to_display_string()

    def test_json_carries_every_field_a_consumer_needs_to_act(self) -> None:
        """CI gates parse this payload; a missing key silently disables a check."""
        conflict = make_conflict(
            "celery",
            ">=5.3.4,<6.0",
            "kombu",
            source_version="5.3.6",
            conflicting_version="5.2.4",
        )

        assert conflict.to_json() == {
            "source_package": "celery",
            "source_version": "5.3.6",
            "target_package": "kombu",
            "required_spec": ">=5.3.4,<6.0",
            "conflicting_version": "5.2.4",
        }

    def test_json_normalises_names_like_the_model_does(self) -> None:
        """The payload must key on the same identity the rest of the run uses."""
        payload = make_conflict("SQLAlchemy", ">=6.0", "Zope.Interface").to_json()

        assert payload["source_package"] == "sqlalchemy"
        assert payload["target_package"] == "zope-interface"

    def test_repr_is_debuggable(self) -> None:
        conflict = make_conflict(
            "flask", ">=2.3.7", "werkzeug", conflicting_version="2.2.3"
        )

        assert repr(conflict) == (
            "Conflict(source_package='flask', target_package='werkzeug', "
            "required_spec='>=2.3.7', conflicting_version='2.2.3')"
        )


# ---------------------------------------------------------------------------
# ConflictSet
# ---------------------------------------------------------------------------


class TestConflictSetBasics:
    def test_starts_empty(self) -> None:
        conflict_set = ConflictSet(package_name="urllib3")

        assert conflict_set.has_conflicts() is False
        assert len(conflict_set) == 0
        assert list(conflict_set) == []

    def test_package_name_is_normalised(self) -> None:
        assert ConflictSet(package_name="Zope.Interface").package_name == (
            "zope-interface"
        )

    def test_accumulates_conflicts_in_arrival_order(self) -> None:
        """Order is preserved so the summary lists constraints deterministically."""
        conflict_set = ConflictSet(package_name="urllib3")
        conflict_set.add_conflict(make_conflict("requests", "<3,>=1.21.1", "urllib3"))
        conflict_set.add_conflict(make_conflict("internal-sdk", "<2.0", "urllib3"))

        assert [c.source_package for c in conflict_set] == ["requests", "internal-sdk"]
        assert len(conflict_set) == 2
        assert conflict_set.has_conflicts() is True

    def test_duplicate_constraints_from_distinct_sources_are_both_kept(self) -> None:
        """Two packages independently demanding ``<2.0`` is real signal.

        Deduplicating would hide that relaxing one of them is not enough.
        """
        conflict_set = make_conflict_set(
            "urllib3",
            [
                make_conflict("internal-sdk", "<2.0", "urllib3"),
                make_conflict("legacy-client", "<2.0", "urllib3"),
            ],
        )

        assert len(conflict_set) == 2


class TestMaxCompatibleVersionAcrossRealGraphs:
    """``get_max_compatible_version`` intersects every constraint at once.

    Each scenario below is a shape that occurs in practice, and each one breaks
    a different naive implementation: taking the last constraint, taking the
    tightest floor, or ignoring the fact that ranges only *partially* overlap.
    """

    def test_no_conflicts_means_nothing_to_solve(self) -> None:
        """``None`` here means "not applicable", not "unsatisfiable"."""
        assert ConflictSet("urllib3").get_max_compatible_version(URLLIB3_VERSIONS) is (
            None
        )

    def test_three_concurrent_constraints_intersect_to_one_version(self) -> None:
        """requests, an internal SDK and a legacy client all cap urllib3.

        - ``requests==2.31.0`` allows ``<3,>=1.21.1`` (wide)
        - ``internal-sdk`` is stuck on ``<2.0`` (blocks the 2.x line)
        - ``legacy-client`` needs ``>=1.26.0`` (blocks 1.25.x)

        Only the 1.26 series survives all three, and the newest member wins.
        """
        conflict_set = make_conflict_set(
            "urllib3",
            [
                make_conflict("requests", "<3,>=1.21.1", "urllib3", source_version="2.31.0"),
                make_conflict("internal-sdk", "<2.0", "urllib3", source_version="4.2.0"),
                make_conflict("legacy-client", ">=1.26.0", "urllib3", source_version="1.9.0"),
            ],
        )

        assert conflict_set.get_max_compatible_version(URLLIB3_VERSIONS) == "1.26.18"

    def test_partially_overlapping_ranges_resolve_to_the_overlap(self) -> None:
        """Flask 2.2.5 wants ``>=2.2.2`` and an internal plugin wants ``<2.3``.

        Neither constraint alone excludes 2.3.7; together they leave exactly the
        2.2.x band.
        """
        conflict_set = make_conflict_set(
            "werkzeug",
            [
                make_conflict("flask", ">=2.2.2", "werkzeug", source_version="2.2.5"),
                make_conflict("acme-auth", "<2.3", "werkzeug", source_version="1.4.0"),
            ],
        )

        resolved = conflict_set.get_max_compatible_version(
            ["2.0.3", "2.1.2", "2.2.3", "2.3.7", "3.0.3"]
        )

        assert resolved == "2.2.3"

    def test_nested_ranges_resolve_to_the_innermost(self) -> None:
        """One constraint fully contains the other; the tighter one governs.

        Celery 5.3.6 admits the whole ``>=5.3.4,<6.0`` band, while an internal
        broker shim is only validated against ``>=5.3.4,<5.3.7``.
        """
        conflict_set = make_conflict_set(
            "kombu",
            [
                make_conflict("celery", ">=5.3.4,<6.0", "kombu", source_version="5.3.6"),
                make_conflict(
                    "acme-broker", ">=5.3.4,<5.3.7", "kombu", source_version="2.1.0"
                ),
            ],
        )

        resolved = conflict_set.get_max_compatible_version(
            ["5.2.4", "5.3.4", "5.3.5", "5.3.7"]
        )

        assert resolved == "5.3.5"

    def test_disjoint_constraints_are_unsatisfiable(self) -> None:
        """A hard security floor against a legacy cap has no answer.

        Returning a version anyway would be worse than reporting failure: the
        user would get a file that satisfies neither dependant.
        """
        conflict_set = make_conflict_set(
            "urllib3",
            [
                make_conflict("internal-sdk", "<2.0", "urllib3"),
                make_conflict("security-policy", ">=2.2.0", "urllib3"),
            ],
        )

        assert conflict_set.get_max_compatible_version(URLLIB3_VERSIONS) is None

    def test_no_published_version_satisfies_the_constraint(self) -> None:
        """A dependant may require a version that simply does not exist yet."""
        conflict_set = make_conflict_set(
            "urllib3", [make_conflict("future-client", ">=3.0", "urllib3")]
        )

        assert conflict_set.get_max_compatible_version(URLLIB3_VERSIONS) is None

    def test_empty_release_history_yields_no_answer(self) -> None:
        """Models a package whose metadata fetch failed: no candidates at all."""
        conflict_set = make_conflict_set(
            "urllib3", [make_conflict("requests", ">=1.21.1", "urllib3")]
        )

        assert conflict_set.get_max_compatible_version([]) is None

    @pytest.mark.parametrize(
        ("spec", "expected"),
        [
            pytest.param("<=2.0.7", "2.0.7", id="inclusive-cap-admits-the-boundary"),
            pytest.param("<2.0.7", "1.26.18", id="exclusive-cap-excludes-it"),
            pytest.param(">=2.2.2", "2.2.2", id="inclusive-floor-admits-the-boundary"),
            pytest.param(">2.0.7", "2.2.2", id="exclusive-floor-skips-it"),
            pytest.param("==1.26.18", "1.26.18", id="exact-pin"),
            pytest.param("!=2.2.2", "2.0.7", id="exclusion-falls-back-one-release"),
            pytest.param("~=1.26.5", "1.26.18", id="compatible-release-stays-in-series"),
        ],
    )
    def test_boundary_conditions(self, spec: str, expected: str) -> None:
        """Off-by-one at a range boundary is the classic resolver defect."""
        conflict_set = make_conflict_set(
            "urllib3", [make_conflict("requests", spec, "urllib3")]
        )

        assert conflict_set.get_max_compatible_version(URLLIB3_VERSIONS) == expected

    def test_prereleases_are_never_selected(self) -> None:
        """Silently upgrading a production file to an alpha is unacceptable.

        The release candidate satisfies the specifier, so only the explicit
        pre-release filter keeps it out.
        """
        conflict_set = make_conflict_set(
            "urllib3", [make_conflict("requests", ">=2.0", "urllib3")]
        )

        resolved = conflict_set.get_max_compatible_version(
            ["2.0.7", "2.2.2", "2.3.0rc1", "3.0.0a1"]
        )

        assert resolved == "2.2.2"

    def test_a_history_of_only_prereleases_has_no_answer(self) -> None:
        conflict_set = make_conflict_set(
            "urllib3", [make_conflict("requests", ">=2.0", "urllib3")]
        )

        assert (
            conflict_set.get_max_compatible_version(["2.0.0a1", "2.5.0b1", "3.0.0rc1"])
            is None
        )


class TestMaxCompatibleVersionRobustness:
    """Upstream metadata is untrusted input and is routinely malformed."""

    def test_unparseable_specifier_yields_no_recommendation(self) -> None:
        """A broken ``requires_dist`` entry must not be guessed at.

        Proposing a version derived from a specifier we could not read would be
        a fabricated answer; declining is the honest outcome.
        """
        conflict_set = make_conflict_set(
            "urllib3", [make_conflict("broken-pkg", "not a specifier", "urllib3")]
        )

        assert conflict_set.get_max_compatible_version(URLLIB3_VERSIONS) is None

    def test_one_unparseable_specifier_poisons_the_whole_set(self) -> None:
        """The constraints are intersected as one specifier string.

        Documenting this deliberately: a single malformed entry disables the
        recommendation for that package rather than being skipped, so the user
        is never handed a version that only satisfies *some* of its dependants.
        """
        conflict_set = make_conflict_set(
            "urllib3",
            [
                make_conflict("requests", "<2.0", "urllib3"),
                make_conflict("broken-pkg", ">>>1.0", "urllib3"),
            ],
        )

        assert conflict_set.get_max_compatible_version(URLLIB3_VERSIONS) is None

    def test_unparseable_versions_are_skipped_not_fatal(self) -> None:
        """Legacy uploads carry non-PEP-440 tags; they must not abort the run."""
        conflict_set = make_conflict_set(
            "urllib3", [make_conflict("requests", ">=1.0", "urllib3")]
        )

        resolved = conflict_set.get_max_compatible_version(
            ["1.26.18", "not-a-version", "2.0.7", "1.0-alpha"]
        )

        assert resolved == "2.0.7"

    def test_selection_is_by_version_order_not_string_order(self) -> None:
        """``"1.26.18" < "1.26.5"`` as strings; as versions the reverse holds."""
        conflict_set = make_conflict_set(
            "urllib3", [make_conflict("requests", ">=1.21.1,<2.0", "urllib3")]
        )

        resolved = conflict_set.get_max_compatible_version(
            ["1.26.5", "1.26.18", "1.26.9"]
        )

        assert resolved == "1.26.18"

    def test_post_releases_are_eligible(self) -> None:
        """``6.4.post2`` is a real, installable zope-interface release."""
        conflict_set = make_conflict_set(
            "zope-interface", [make_conflict("sqlalchemy", ">=6.0", "zope-interface")]
        )

        resolved = conflict_set.get_max_compatible_version(
            ["5.4.0", "6.0", "6.4.post2"]
        )

        assert resolved == "6.4.post2"

    @pytest.mark.parametrize(
        ("available", "expected"),
        [
            pytest.param(["1.4.0", "1.4.2", "1.4.9", "1.5.0"], "1.4.9", id="four-part-floor"),
            pytest.param(["1.2.3.3", "1.2.3.4", "1.2.4.0"], "1.2.4.0", id="four-part-history"),
        ],
    )
    def test_multi_segment_versions_compare_numerically(
        self, available: List[str], expected: Optional[str]
    ) -> None:
        """Versions like ``3.6.4.0`` (billiard) and ``1.2.3.4`` occur upstream."""
        spec = "~=1.4.2" if expected == "1.4.9" else ">=1.2.3.4"
        conflict_set = make_conflict_set(
            "billiard", [make_conflict("celery", spec, "billiard")]
        )

        assert conflict_set.get_max_compatible_version(available) == expected


class TestConflictSetWorkflow:
    """The sequence the resolver actually performs, end to end."""

    def test_collect_then_resolve_then_report(self) -> None:
        """Three services constrain urllib3; the set drives both outputs.

        This is the shape of a real ``depkeeper check`` run: conflicts arrive
        one at a time from different sources, then a single version is chosen
        and the same set is rendered for the user.
        """
        conflict_set = ConflictSet(package_name="urllib3")
        assert conflict_set.has_conflicts() is False

        conflict_set.add_conflict(
            make_conflict("requests", "<3,>=1.21.1", "urllib3", source_version="2.31.0")
        )
        conflict_set.add_conflict(
            make_conflict("internal-sdk", "<2.0", "urllib3", source_version="4.2.0")
        )
        conflict_set.add_conflict(
            make_conflict("legacy-client", ">=1.26.0", "urllib3", source_version="1.9.0")
        )

        assert conflict_set.get_max_compatible_version(URLLIB3_VERSIONS) == "1.26.18"

        assert [c.to_display_string() for c in conflict_set] == [
            "requests==2.31.0 requires urllib3<3,>=1.21.1",
            "internal-sdk==4.2.0 requires urllib3<2.0",
            "legacy-client==1.9.0 requires urllib3>=1.26.0",
        ]
        assert [c.to_json()["source_package"] for c in conflict_set] == [
            "requests",
            "internal-sdk",
            "legacy-client",
        ]

    def test_relaxing_one_constraint_unblocks_the_upgrade(self) -> None:
        """Demonstrates why the intersection — not any single cap — decides.

        Dropping the internal SDK's ``<2.0`` is exactly the remediation
        depkeeper's output is meant to prompt, and it moves the answer two
        majors.
        """
        blocking = make_conflict("internal-sdk", "<2.0", "urllib3")
        shared = make_conflict("requests", "<3,>=1.21.1", "urllib3")

        with_sdk = make_conflict_set("urllib3", [shared, blocking])
        without_sdk = make_conflict_set("urllib3", [shared])

        assert with_sdk.get_max_compatible_version(URLLIB3_VERSIONS) == "1.26.18"
        assert without_sdk.get_max_compatible_version(URLLIB3_VERSIONS) == "2.2.2"
