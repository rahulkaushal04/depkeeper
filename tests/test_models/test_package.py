"""Tests for :class:`depkeeper.models.Package`.

``Package`` carries one distribution through a whole run: what the file
declares, what PyPI publishes, what depkeeper intends to write, and which
conflicts constrain that decision. Two of its responsibilities are load-bearing
and are where the tests concentrate:

- **Status classification.** ``outdated`` / ``latest`` / ``downgrade`` /
  ``install`` / ``no-update`` drives the exit code, the table, and whether the
  update command touches the file at all. Every branch is covered against a
  realistic version triple, including the ones that only differ by a
  pre-release or a missing value.
- **JSON serialisation.** ``to_json`` is a public contract consumed by CI
  gates. Assertions compare whole documents rather than probing single keys, so
  an accidentally added, renamed or dropped field fails the test.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest
from packaging.version import Version

from depkeeper.models import Package
from tests.support.factories import make_conflict, make_package

# Conflicts constraining urllib3, reused wherever conflict rendering matters.
REQUESTS_CONSTRAINT = make_conflict(
    "requests", "<3,>=1.21.1", "urllib3", source_version="2.31.0",
    conflicting_version="1.20.0",
)
SDK_CONSTRAINT = make_conflict(
    "internal-sdk", "<2.0", "urllib3", source_version="4.2.0",
    conflicting_version="2.2.2",
)


# ---------------------------------------------------------------------------
# Identity and version parsing
# ---------------------------------------------------------------------------


class TestIdentity:
    """``Package.name`` is the key every other layer looks the package up by."""

    @pytest.mark.parametrize(
        ("declared", "canonical"),
        [
            ("Django", "django"),
            ("typing_extensions", "typing-extensions"),
            ("zope.interface", "zope-interface"),
            ("ruamel.yaml.clib", "ruamel-yaml-clib"),
            ("Backports.Zoneinfo", "backports-zoneinfo"),
            ("urllib3", "urllib3"),
        ],
        ids=["case", "underscore", "dot", "multi-dot", "mixed", "already-canonical"],
    )
    def test_name_is_normalised_to_pep503(self, declared: str, canonical: str) -> None:
        """A dotted distribution must not become a second, invisible identity."""
        assert Package(name=declared).name == canonical


class TestVersionParsing:
    """Version strings are parsed lazily and memoised."""

    @pytest.mark.parametrize(
        "version",
        ["2.31.0", "1.26.18", "6.4.post2", "2.0.0rc1", "1!2.0.0", "3.6.4.0", "1.0-alpha"],
        ids=["release", "patch", "post", "rc", "epoch", "four-part", "legacy-alpha"],
    )
    def test_valid_pep440_versions_parse(self, version: str) -> None:
        """``1.0-alpha`` is included deliberately: PEP 440 normalises it to
        ``1.0a0`` rather than rejecting it, so it must not be treated as junk.
        """
        assert make_package(current=version).current == Version(version)

    @pytest.mark.parametrize(
        "version",
        ["not-a-version", "2.0.0 (final)", "latest", ""],
        ids=["garbage", "annotated", "channel-name", "empty"],
    )
    def test_unparseable_versions_degrade_to_none(self, version: str) -> None:
        """Old uploads carry non-PEP-440 tags; they must not abort a run."""
        assert make_package(current=version).current is None

    def test_absent_versions_are_none(self) -> None:
        pkg = make_package("urllib3")

        assert (pkg.current, pkg.latest, pkg.recommended) == (None, None, None)

    def test_parsed_versions_are_memoised(self) -> None:
        """The resolver re-reads these inside a loop bounded only by graph size."""
        pkg = make_package(current="2.31.0")

        assert pkg.current is pkg.current

    def test_unparseable_versions_are_memoised_as_failures(self) -> None:
        """Otherwise every access re-raises and re-swallows the same exception."""
        pkg = make_package(current="not-a-version")

        assert pkg.current is None
        assert pkg._parsed_versions == {"not-a-version": None}


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------


class TestStatusClassification:
    """The five statuses that decide what the CLI reports and writes."""

    @pytest.mark.parametrize(
        ("pkg", "status", "has_update", "requires_downgrade"),
        [
            pytest.param(
                make_package("requests", current="2.28.2", latest="2.32.3", recommended="2.32.3"),
                "outdated",
                True,
                False,
                id="outdated-newer-recommended",
            ),
            pytest.param(
                make_package("requests", current="2.32.3", latest="2.32.3", recommended="2.32.3"),
                "latest",
                False,
                False,
                id="latest-already-current",
            ),
            pytest.param(
                # A conflict forced urllib3 back below its published latest.
                make_package("urllib3", current="2.2.2", latest="2.2.2", recommended="1.26.18"),
                "downgrade",
                False,
                True,
                id="downgrade-forced-by-a-conflict",
            ),
            pytest.param(
                make_package("urllib3", latest="2.2.2", recommended="2.2.2"),
                "install",
                False,
                False,
                id="install-unpinned-in-the-file",
            ),
            pytest.param(
                # The stub the checker returns when PyPI metadata is unavailable.
                make_package("internal-sdk", current="4.2.0"),
                "no-update",
                False,
                False,
                id="no-update-metadata-unavailable",
            ),
        ],
    )
    def test_status_summary(
        self,
        pkg: Package,
        status: str,
        has_update: bool,
        requires_downgrade: bool,
    ) -> None:
        assert pkg.get_status_summary()[0] == status
        assert pkg.has_update() is has_update
        assert pkg.requires_downgrade is requires_downgrade

    def test_summary_reports_the_raw_version_strings(self) -> None:
        """The table shows what the file and PyPI actually said, not parsed forms."""
        pkg = make_package(
            "requests", current="2.28.2", latest="2.32.3", recommended="2.31.0"
        )

        assert pkg.get_status_summary() == ("outdated", "2.28.2", "2.32.3", "2.31.0")

    def test_missing_versions_render_as_placeholders(self) -> None:
        """``none``/``error`` distinguish "not pinned" from "lookup failed"."""
        pkg = make_package("internal-sdk")

        assert pkg.get_status_summary() == ("no-update", "none", "error", None)

    @pytest.mark.parametrize(
        ("current", "recommended"),
        [("not-a-version", "2.32.3"), ("2.28.2", "not-a-version")],
        ids=["bad-current", "bad-recommended"],
    )
    def test_unparseable_versions_never_claim_an_update(
        self, current: str, recommended: str
    ) -> None:
        """Comparison is impossible, so proposing a write would be a guess."""
        pkg = make_package("requests", current=current, recommended=recommended)

        assert pkg.has_update() is False
        assert pkg.requires_downgrade is False

    def test_prerelease_recommendation_counts_as_an_update(self) -> None:
        """``2.0.0rc1 > 1.26.18`` under PEP 440, and the resolver may pick it."""
        pkg = make_package("urllib3", current="1.26.18", recommended="2.0.0rc1")

        assert pkg.has_update() is True


# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------


class TestConflicts:
    def test_no_conflicts_by_default(self) -> None:
        pkg = make_package("urllib3")

        assert pkg.has_conflicts() is False
        assert pkg.get_conflict_summary() == []
        assert pkg.get_conflict_details() == []

    def test_set_conflicts_replaces_rather_than_appends(self) -> None:
        """The resolver re-annotates on every pass; appending would duplicate."""
        pkg = make_package("urllib3")
        pkg.set_conflicts([REQUESTS_CONSTRAINT, SDK_CONSTRAINT])
        pkg.set_conflicts([SDK_CONSTRAINT])

        assert pkg.conflicts == [SDK_CONSTRAINT]

    def test_clearing_conflicts_is_reflected(self) -> None:
        """A later pass can resolve every conflict; the package must say so."""
        pkg = make_package("urllib3", conflicts=[REQUESTS_CONSTRAINT])
        pkg.set_conflicts([])

        assert pkg.has_conflicts() is False

    def test_resolved_version_overrides_the_recommendation(self) -> None:
        """Legacy escape hatch: the resolver may hand back the reconciled version.

        Regression M10 was caused by this override firing on a *stale* conflict,
        so the parameter is kept but callers in the resolver no longer use it.
        """
        pkg = make_package("urllib3", current="1.26.18", recommended="2.2.2")
        pkg.set_conflicts([SDK_CONSTRAINT], resolved_version="1.26.18")

        assert pkg.recommended_version == "1.26.18"

    def test_omitting_resolved_version_leaves_the_recommendation_alone(self) -> None:
        pkg = make_package("urllib3", current="1.26.18", recommended="2.2.2")
        pkg.set_conflicts([SDK_CONSTRAINT])

        assert pkg.recommended_version == "2.2.2"

    def test_summaries_are_compact_and_details_are_attributed(self) -> None:
        """The table shows the short form; ``--verbose`` shows the long form."""
        pkg = make_package("urllib3", conflicts=[REQUESTS_CONSTRAINT, SDK_CONSTRAINT])

        assert pkg.get_conflict_summary() == [
            "requests needs <3,>=1.21.1",
            "internal-sdk needs <2.0",
        ]
        assert pkg.get_conflict_details() == [
            "requests==2.31.0 requires urllib3<3,>=1.21.1",
            "internal-sdk==4.2.0 requires urllib3<2.0",
        ]


# ---------------------------------------------------------------------------
# Python compatibility metadata
# ---------------------------------------------------------------------------


class TestPythonRequirements:
    """``requires_python`` decides whether a recommendation is installable."""

    @pytest.fixture
    def pandas(self) -> Package:
        """pandas 2.2.2 raised its floor to 3.9, which is the interesting case."""
        return make_package(
            "pandas",
            current="2.0.3",
            latest="2.2.2",
            recommended="2.2.2",
            requires_python={
                "current": ">=3.8",
                "latest": ">=3.9",
                "recommended": ">=3.9",
            },
        )

    @pytest.mark.parametrize(
        "key", ["current", "latest", "recommended"],
    )
    def test_each_version_slot_is_readable(self, pandas: Package, key: str) -> None:
        assert pandas.get_version_python_req(key) is not None

    def test_missing_metadata_is_none(self) -> None:
        assert make_package("pandas").get_version_python_req("current") is None

    @pytest.mark.parametrize(
        "metadata",
        [
            pytest.param({"current_metadata": ">=3.8"}, id="metadata-not-a-dict"),
            pytest.param(
                {"current_metadata": {"requires_python": [">=3.8"]}},
                id="requires-python-not-a-string",
            ),
            pytest.param({"current_metadata": {}}, id="key-absent"),
        ],
    )
    def test_malformed_metadata_degrades_to_none(
        self, metadata: Dict[str, Any]
    ) -> None:
        """Upstream metadata is untrusted; a bad shape must not raise mid-run."""
        pkg = Package(name="pandas", current_version="2.0.3", metadata=metadata)

        assert pkg.get_version_python_req("current") is None

    def test_rendering_lists_current_and_latest(self, pandas: Package) -> None:
        assert pandas.render_python_compatibility().splitlines()[:2] == [
            "Current: >=3.8",
            "Latest: >=3.9",
        ]

    def test_rendering_includes_recommended_only_when_updating(
        self, pandas: Package
    ) -> None:
        """Its only purpose is to warn that *taking the update* needs a newer
        interpreter; on an up-to-date package that line is noise.
        """
        assert "Recommended:>=3.9" in pandas.render_python_compatibility()

        pandas.current_version = "2.2.2"
        assert "Recommended:" not in pandas.render_python_compatibility()

    def test_rendering_falls_back_to_a_placeholder(self) -> None:
        """Rich markup keeps the column aligned when nothing is known."""
        assert make_package("pandas").render_python_compatibility() == "[dim]-[/dim]"


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


class TestToJson:
    """``to_json`` is a public contract; whole documents are compared."""

    def test_outdated_package_document(self) -> None:
        assert make_package(
            "requests",
            current="2.28.2",
            latest="2.32.3",
            recommended="2.32.3",
            requires_python={"current": ">=3.7, <4", "recommended": ">=3.8"},
        ).to_json() == {
            "name": "requests",
            "status": "outdated",
            "versions": {
                "current": "2.28.2",
                "latest": "2.32.3",
                "recommended": "2.32.3",
            },
            "update_type": "minor",
            "python_requirements": {"current": ">=3.7, <4", "recommended": ">=3.8"},
        }

    def test_downgrade_document_reports_the_direction(self) -> None:
        """CI gates branch on ``update_type``; a downgrade must not read as an
        upgrade, because the two need opposite approvals.
        """
        assert make_package(
            "urllib3", current="2.2.2", latest="2.2.2", recommended="1.26.18"
        ).to_json() == {
            "name": "urllib3",
            "status": "downgrade",
            "versions": {
                "current": "2.2.2",
                "latest": "2.2.2",
                "recommended": "1.26.18",
            },
            "update_type": "downgrade",
        }

    def test_up_to_date_document_omits_update_type(self) -> None:
        """The key's absence is the signal that no action is required."""
        assert make_package(
            "requests", current="2.32.3", latest="2.32.3", recommended="2.32.3"
        ).to_json() == {
            "name": "requests",
            "status": "latest",
            "versions": {
                "current": "2.32.3",
                "latest": "2.32.3",
                "recommended": "2.32.3",
            },
        }

    def test_unavailable_package_document_carries_an_error(self) -> None:
        """The stub produced when a PyPI lookup fails must be distinguishable
        from a healthy package with nothing to do.
        """
        assert make_package("internal-sdk", current="4.2.0").to_json() == {
            "name": "internal-sdk",
            "status": "no-update",
            "versions": {"current": "4.2.0"},
            "error": "Package information unavailable",
        }

    def test_conflicts_are_embedded_in_order(self) -> None:
        pkg = make_package(
            "urllib3",
            current="1.26.18",
            latest="2.2.2",
            recommended="1.26.18",
            conflicts=[REQUESTS_CONSTRAINT, SDK_CONSTRAINT],
        )

        assert pkg.to_json()["conflicts"] == [
            REQUESTS_CONSTRAINT.to_json(),
            SDK_CONSTRAINT.to_json(),
        ]

    def test_name_is_serialised_in_canonical_form(self) -> None:
        """Consumers join this against their own PEP 503 keys."""
        assert make_package("Zope.Interface", current="5.4.0").to_json()["name"] == (
            "zope-interface"
        )


class TestDisplayData:
    """Derived values the table renderer reads, computed once per row."""

    def test_update_row(self) -> None:
        assert make_package(
            "requests", current="2.28.2", latest="2.32.3", recommended="2.32.3"
        ).get_display_data() == {
            "update_available": True,
            "requires_downgrade": False,
            "update_target": "2.32.3",
            "update_type": "minor",
            "has_conflicts": False,
            "conflict_summary": [],
        }

    def test_conflicted_downgrade_row(self) -> None:
        """The row a user must act on: a forced downgrade plus its reason."""
        assert make_package(
            "urllib3",
            current="2.2.2",
            latest="2.2.2",
            recommended="1.26.18",
            conflicts=[SDK_CONSTRAINT],
        ).get_display_data() == {
            "update_available": False,
            "requires_downgrade": True,
            "update_target": "1.26.18",
            "update_type": "downgrade",
            "has_conflicts": True,
            "conflict_summary": ["internal-sdk needs <2.0"],
        }

    def test_unchanged_row_reports_no_update_type(self) -> None:
        """``update_type`` is only meaningful when something is changing."""
        data = make_package(
            "requests", current="2.32.3", latest="2.32.3", recommended="2.32.3"
        ).get_display_data()

        assert data["update_available"] is False
        assert data["update_type"] is None


class TestRepresentations:
    @pytest.mark.parametrize(
        ("pkg", "expected"),
        [
            pytest.param(make_package("urllib3"), "urllib3", id="name-only"),
            pytest.param(
                make_package("urllib3", latest="2.2.2"),
                "urllib3 (latest: 2.2.2)",
                id="not-installed",
            ),
            pytest.param(
                make_package(
                    "requests", current="2.32.3", latest="2.32.3", recommended="2.32.3"
                ),
                "requests 2.32.3 → 2.32.3 (up-to-date)",
                id="up-to-date",
            ),
            pytest.param(
                make_package(
                    "requests", current="2.28.2", latest="2.32.3", recommended="2.31.0"
                ),
                "requests 2.28.2 → 2.32.3 (outdated) [recommended: 2.31.0]",
                id="outdated-shows-recommended-not-latest",
            ),
        ],
    )
    def test_str_summarises_the_package_state(
        self, pkg: Package, expected: str
    ) -> None:
        """``str`` appears in log lines, so the recommended version — the one
        depkeeper would actually write — has to be visible alongside latest.
        """
        assert str(pkg) == expected

    @pytest.mark.parametrize(
        ("recommended", "outdated"),
        [("2.32.3", True), ("2.28.2", False)],
        ids=["outdated", "current"],
    )
    def test_repr_reports_the_outdated_decision(
        self, recommended: Optional[str], outdated: bool
    ) -> None:
        pkg = make_package(
            "requests", current="2.28.2", latest="2.32.3", recommended=recommended
        )

        assert repr(pkg) == (
            "Package(name='requests', current_version='2.28.2', "
            f"latest_version='2.32.3', recommended_version={recommended!r}, "
            f"outdated={outdated})"
        )
