"""Tests for :class:`depkeeper.models.Requirement`.

``Requirement`` is the only component that turns depkeeper's internal state
back into a line of ``requirements.txt``. Anything it renders is written
verbatim to a user's file and then fed to pip, so the bar for every assertion
here is *installability*, not merely "the expected substring is present".

Test data uses real distributions and real published versions. A rendering bug
that only shows up on a line like ``celery[redis]>=5.0,<6.0`` is exactly the
bug that reaches production, and it is invisible when the fixture is ``pkg==1.0``.
"""

from __future__ import annotations

import pytest

from depkeeper.models import Requirement
from tests.support.factories import make_requirement, specs

# A real editable checkout line, used wherever a direct reference is needed.
INTERNAL_SDK_URL = "git+ssh://git@github.com/acme/internal-sdk.git@main#egg=internal-sdk"

# Real-length sha256 digests, so tests exercise realistic line lengths.
CLICK_SHA256 = (
    "sha256:ae74fb96c20a0277a1d615f1e4d73c8414f5a98db8b799a7931d1582f3390c28"
)
CLICK_SHA256_SDIST = (
    "sha256:ca9853ad459e787e2192211578cc907e7594e294c7ccc834310722b41b9ca6de"
)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    """Field defaults and dataclass semantics."""

    def test_only_name_is_required(self) -> None:
        req = Requirement(name="requests")

        assert (req.specs, req.extras, req.hashes) == ([], [], [])
        assert (req.markers, req.url, req.comment, req.raw_line) == (None,) * 4
        assert req.editable is False
        assert req.line_number == 0
        assert req.source_file is None

    def test_mutable_defaults_are_not_shared_between_instances(self) -> None:
        """A shared default list would let one parsed line corrupt another."""
        first = Requirement(name="requests")
        second = Requirement(name="flask")

        first.specs.append(("==", "2.31.0"))
        first.extras.append("socks")
        first.hashes.append(CLICK_SHA256)

        assert second.specs == []
        assert second.extras == []
        assert second.hashes == []

    def test_source_file_is_excluded_from_equality(self) -> None:
        """Provenance is bookkeeping for the writer, not part of identity.

        The same requirement reached through ``-r base.txt`` and read directly
        must still compare equal; only the file it gets written back to differs.
        """
        via_include = make_requirement(
            "requests",
            specs=specs("==2.31.0"),
            source_file="/app/requirements/base.txt",
        )
        direct = make_requirement(
            "requests", specs=specs("==2.31.0"), source_file="/app/requirements.txt"
        )

        assert via_include == direct

    def test_differing_specs_are_not_equal(self) -> None:
        """Guard for the above: equality must still notice real differences."""
        assert make_requirement("requests", specs=specs("==2.31.0")) != make_requirement(
            "requests", specs=specs("==2.32.3")
        )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestToString:
    """``to_string`` must emit a line pip can install."""

    @pytest.mark.parametrize(
        ("req", "expected"),
        [
            pytest.param(make_requirement("urllib3"), "urllib3", id="bare-name"),
            pytest.param(
                make_requirement("requests", specs=specs("==2.31.0")),
                "requests==2.31.0",
                id="exact-pin",
            ),
            pytest.param(
                make_requirement("django", specs=specs(">=3.2", "<5.0", "!=4.0.*")),
                "django>=3.2,<5.0,!=4.0.*",
                id="range-with-exclusion-keeps-declaration-order",
            ),
            pytest.param(
                make_requirement("sqlalchemy", specs=specs("~=2.0")),
                "sqlalchemy~=2.0",
                id="compatible-release",
            ),
            pytest.param(
                make_requirement("celery", extras=["redis"], specs=specs(">=5.3.4")),
                "celery[redis]>=5.3.4",
                id="single-extra",
            ),
            pytest.param(
                make_requirement("django", extras=["argon2", "bcrypt"]),
                "django[argon2,bcrypt]",
                id="multiple-extras-keep-order",
            ),
            pytest.param(
                make_requirement(
                    "typing-extensions",
                    specs=specs(">=4.6.0"),
                    markers='python_version < "3.11"',
                ),
                'typing-extensions>=4.6.0 ; python_version < "3.11"',
                id="environment-marker",
            ),
            pytest.param(
                make_requirement("internal-sdk", url=INTERNAL_SDK_URL, editable=True),
                f"-e {INTERNAL_SDK_URL}",
                id="editable-vcs-checkout",
            ),
            pytest.param(
                make_requirement(
                    "flask", specs=specs("==2.3.3"), comment="CVE-2023-30861"
                ),
                "flask==2.3.3  # CVE-2023-30861",
                id="inline-comment",
            ),
        ],
    )
    def test_renders_expected_line(self, req: Requirement, expected: str) -> None:
        assert req.to_string() == expected

    def test_renders_every_component_in_pip_order(self) -> None:
        """The full grammar: -e, name, extras, specs, marker, hashes, comment."""
        req = make_requirement(
            "celery",
            specs=specs(">=5.3.4", "<6.0"),
            extras=["redis", "msgpack"],
            markers='python_version >= "3.8"',
            hashes=[CLICK_SHA256],
            comment="broker client",
        )

        assert req.to_string() == (
            "celery[redis,msgpack]>=5.3.4,<6.0"
            ' ; python_version >= "3.8"'
            f" --hash={CLICK_SHA256}"
            "  # broker client"
        )

    def test_multiple_hashes_are_each_prefixed(self) -> None:
        """``pip --require-hashes`` needs one ``--hash`` per published artifact."""
        req = make_requirement(
            "click", specs=specs("==8.1.7"), hashes=[CLICK_SHA256, CLICK_SHA256_SDIST]
        )

        assert req.to_string() == (
            f"click==8.1.7 --hash={CLICK_SHA256} --hash={CLICK_SHA256_SDIST}"
        )

    @pytest.mark.parametrize(
        ("include_hashes", "include_comment", "expected"),
        [
            (True, True, f"click==8.1.7 --hash={CLICK_SHA256}  # pinned by lockfile"),
            (True, False, f"click==8.1.7 --hash={CLICK_SHA256}"),
            (False, True, "click==8.1.7  # pinned by lockfile"),
            (False, False, "click==8.1.7"),
        ],
        ids=["both", "hashes-only", "comment-only", "neither"],
    )
    def test_hash_and_comment_flags_are_independent(
        self, include_hashes: bool, include_comment: bool, expected: str
    ) -> None:
        req = make_requirement(
            "click",
            specs=specs("==8.1.7"),
            hashes=[CLICK_SHA256],
            comment="pinned by lockfile",
        )

        assert (
            req.to_string(
                include_hashes=include_hashes, include_comment=include_comment
            )
            == expected
        )

    def test_comment_containing_a_hash_symbol_is_not_escaped(self) -> None:
        """Issue references are the most common comment; ``#`` must survive."""
        req = make_requirement(
            "urllib3", specs=specs("<2.0"), comment="see acme/platform#4127"
        )

        assert req.to_string() == "urllib3<2.0  # see acme/platform#4127"


class TestDirectReferenceRendering:
    """Regression C2: specifiers must never be appended to a direct reference.

    PEP 508 direct references carry their version in the URL. Emitting
    ``git+https://...#egg=pkg==9.9.9`` produces a line pip cannot install, and
    depkeeper used to do exactly that whenever a URL requirement also carried
    specs (which the constraint machinery can attach).
    """

    @pytest.mark.parametrize(
        ("req", "expected"),
        [
            pytest.param(
                make_requirement(
                    "internal-sdk", url=INTERNAL_SDK_URL, specs=specs("==9.9.9")
                ),
                INTERNAL_SDK_URL,
                id="vcs",
            ),
            pytest.param(
                make_requirement(
                    "internal-sdk",
                    url=INTERNAL_SDK_URL,
                    specs=specs("==9.9.9"),
                    editable=True,
                ),
                f"-e {INTERNAL_SDK_URL}",
                id="editable-vcs",
            ),
            pytest.param(
                make_requirement(
                    "rich",
                    url=(
                        "https://files.pythonhosted.org/packages/"
                        "rich-13.7.1-py3-none-any.whl"
                    ),
                    specs=specs(">=13.0.0"),
                ),
                (
                    "https://files.pythonhosted.org/packages/"
                    "rich-13.7.1-py3-none-any.whl"
                ),
                id="wheel-url",
            ),
        ],
    )
    def test_specs_are_dropped(self, req: Requirement, expected: str) -> None:
        assert req.to_string() == expected

    def test_extras_are_still_rendered(self) -> None:
        """Guard: dropping specs must not also drop the extras selector.

        The extra still selects which optional dependency group pip installs
        from the direct reference, so it carries meaning the URL does not.
        """
        req = make_requirement(
            "celery",
            url="https://github.com/celery/celery/archive/v5.4.0.zip",
            extras=["redis"],
            specs=specs("==9.9.9"),
        )

        assert req.to_string() == (
            "https://github.com/celery/celery/archive/v5.4.0.zip[redis]"
        )

    def test_update_version_leaves_the_reference_installable(self) -> None:
        req = make_requirement("internal-sdk", url=INTERNAL_SDK_URL, editable=True)

        assert req.update_version("2.4.0") == f"-e {INTERNAL_SDK_URL}\n"


# ---------------------------------------------------------------------------
# Version updates
# ---------------------------------------------------------------------------


class TestUpdateVersionPreservesDeclaredRanges:
    """Regression M5: an update moves the floor and nothing else.

    Upper bounds, exclusions and wildcard bands are deliberate compatibility
    statements. Collapsing ``celery[redis]>=5.0,<6.0`` to ``celery[redis]==5.4.0``
    silently discards the author's guarantee that 6.x is untested, and the next
    engineer has no way to recover that intent from the diff.
    """

    @pytest.mark.parametrize(
        ("declared", "target", "expected"),
        [
            pytest.param(
                ">=5.0,<6.0", "5.4.0", "celery>=5.4.0,<6.0", id="floor-moves-cap-stays"
            ),
            pytest.param(
                ">=2.28,<3,!=2.30.0",
                "2.32.3",
                "celery>=2.32.3,<3,!=2.30.0",
                id="exclusion-survives",
            ),
            pytest.param(
                ">2.0",
                "2.32.3",
                "celery>=2.32.3",
                id="strict-floor-widens-to-inclusive",
            ),
            pytest.param("~=2.0", "2.3.3", "celery~=2.3", id="tilde-keeps-precision"),
            pytest.param(
                "~=2.0.1", "2.3.3", "celery~=2.3.3", id="tilde-keeps-finer-precision"
            ),
            pytest.param("==1.26.5", "1.26.18", "celery==1.26.18", id="pin-is-repinned"),
            pytest.param(
                # A cap-only requirement has no floor to move, so one is
                # appended rather than inserted; the cap keeps its position.
                "<3.0",
                "2.32.3",
                "celery<3.0,>=2.32.3",
                id="cap-only-gains-a-floor",
            ),
        ],
    )
    def test_rewrite(self, declared: str, target: str, expected: str) -> None:
        req = make_requirement("celery", specs=specs(*declared.split(",")))

        assert req.update_version(target, preserve_trailing_newline=False) == expected

    def test_unspecified_requirement_gains_a_pin(self) -> None:
        """A bare ``urllib3`` is an implicit "whatever is latest", so pin it."""
        req = make_requirement("urllib3")

        assert req.update_version("2.2.2", preserve_trailing_newline=False) == (
            "urllib3==2.2.2"
        )

    def test_pin_mode_collapses_the_range(self) -> None:
        """``--pin`` is the explicit opt-in to lock-everything behaviour."""
        req = make_requirement("celery", extras=["redis"], specs=specs(">=5.0", "<6.0"))

        assert (
            req.update_version("5.4.0", pin=True, preserve_trailing_newline=False)
            == "celery[redis]==5.4.0"
        )

    def test_target_excluded_by_its_own_constraint_is_rejected(self) -> None:
        """Writing 2.3.3 under ``<2.3`` would emit ``flask>=2.3.3,<2.3``.

        That line is unsatisfiable: pip fails at install time, far away from the
        command that produced it. Failing here keeps the error next to its cause.
        """
        req = make_requirement("flask", specs=specs(">=2.0", "<2.3"))

        with pytest.raises(ValueError, match="excludes that version"):
            req.update_version("2.3.3")

    def test_pin_mode_can_override_an_excluding_constraint(self) -> None:
        """``pin=True`` discards the constraint, so there is nothing left to violate."""
        req = make_requirement("flask", specs=specs(">=2.0", "<2.3"))

        assert (
            req.update_version("2.3.3", pin=True, preserve_trailing_newline=False)
            == "flask==2.3.3"
        )

    def test_compatible_release_rewrite_converges(self) -> None:
        """Re-applying the same target must not churn the file.

        ``~=`` is rewritten at the author's declared precision, so the output of
        one update is the input of the next. If that were not a fixed point,
        depkeeper would report the same update forever and every run would
        produce a diff.
        """
        first_pass = make_requirement("flask", specs=specs("~=2.0")).update_version(
            "2.3.3", preserve_trailing_newline=False
        )
        second_pass = make_requirement(
            "flask", specs=specs(first_pass[len("flask"):])
        ).update_version("2.3.3", preserve_trailing_newline=False)

        assert first_pass == second_pass == "flask~=2.3"

    def test_target_already_inside_the_compatible_band_is_a_no_op(self) -> None:
        """``~=2.0`` already admits 2.0.30, so the line must not be rewritten.

        Emitting ``~=2.0.30`` here would narrow the author's band on every patch
        release — a silent tightening of the dependency contract.
        """
        req = make_requirement("sqlalchemy", specs=specs("~=2.0"))

        assert req.update_version("2.0.30", preserve_trailing_newline=False) == (
            "sqlalchemy~=2.0"
        )


class TestUpdateVersionPreservesLineContent:
    """Everything the author wrote that is not a version must survive."""

    def test_extras_markers_and_comment_are_carried_through(self) -> None:
        req = make_requirement(
            "django",
            specs=specs(">=3.2", "<5.0", "!=4.0.*"),
            extras=["argon2", "bcrypt"],
            markers='python_version >= "3.8"',
            comment="4.0.x is EOL",
            line_number=17,
            source_file="/app/requirements/base.txt",
        )

        assert req.update_version("4.2.11", preserve_trailing_newline=False) == (
            'django[argon2,bcrypt]>=4.2.11,<5.0,!=4.0.* ; python_version >= "3.8"'
            "  # 4.0.x is EOL"
        )

    def test_editable_flag_survives(self) -> None:
        req = make_requirement("internal-sdk", specs=specs("==2.3.0"), editable=True)

        assert req.update_version("2.4.0").startswith("-e ")

    @pytest.mark.parametrize(
        ("preserve", "expected"),
        [(True, "requests==2.32.3\n"), (False, "requests==2.32.3")],
        ids=["with-newline", "without-newline"],
    )
    def test_trailing_newline_is_caller_controlled(
        self, preserve: bool, expected: str
    ) -> None:
        """The file writer re-attaches each line's own terminator, so it opts out."""
        req = make_requirement("requests", specs=specs("==2.31.0"))

        assert (
            req.update_version("2.32.3", preserve_trailing_newline=preserve) == expected
        )


class TestUpdateVersionHashGuard:
    """Regression C3: a version bump must not silently strip ``--hash`` pins.

    Hashes are version-specific, so an update necessarily invalidates them.
    Dropping them turns a hash-verified install into an unverified one — a
    supply-chain regression no diff reviewer would flag, because the line still
    looks like a routine version bump.
    """

    @pytest.fixture
    def hashed(self) -> Requirement:
        """A hash-pinned line as ``pip-compile --generate-hashes`` emits it."""
        return make_requirement(
            "click",
            specs=specs("==8.1.3"),
            hashes=[CLICK_SHA256, CLICK_SHA256_SDIST],
        )

    def test_update_is_refused_by_default(self, hashed: Requirement) -> None:
        with pytest.raises(ValueError, match="hash-removal opt-in"):
            hashed.update_version("8.1.7")

    def test_refusal_is_not_bypassable_via_pin(self, hashed: Requirement) -> None:
        with pytest.raises(ValueError, match="hash-removal opt-in"):
            hashed.update_version("8.1.7", pin=True)

    def test_explicit_opt_in_updates_and_drops_stale_hashes(
        self, hashed: Requirement
    ) -> None:
        result = hashed.update_version(
            "8.1.7", allow_hash_removal=True, preserve_trailing_newline=False
        )

        assert result == "click==8.1.7"

    def test_unhashed_requirements_are_unaffected(self) -> None:
        req = make_requirement("click", specs=specs("==8.1.3"))

        assert req.update_version("8.1.7", preserve_trailing_newline=False) == (
            "click==8.1.7"
        )


# ---------------------------------------------------------------------------
# Representations
# ---------------------------------------------------------------------------


class TestRepresentations:
    def test_str_is_the_rendered_line(self) -> None:
        """``str`` reaches user-facing output, so it must be the real line."""
        req = make_requirement(
            "celery", extras=["redis"], specs=specs(">=5.3.4", "<6.0")
        )

        assert str(req) == "celery[redis]>=5.3.4,<6.0"

    def test_repr_exposes_the_fields_needed_to_triage_a_bad_write(self) -> None:
        """Line number and specs are what a corrupted-file report is triaged on."""
        req = make_requirement(
            "flask", specs=specs(">=2.2", "<3.0"), extras=["async"], line_number=42
        )

        assert repr(req) == (
            "Requirement(name='flask', specs=[('>=', '2.2'), ('<', '3.0')], "
            "extras=['async'], editable=False, line_number=42)"
        )
