"""Conflict, ConflictSet, ResolutionResult and helper semantics."""

from __future__ import annotations

import random
from typing import List

import pytest
from packaging.version import parse

from depkeeper.core.dependency_analyzer import (
    PackageResolution,
    ResolutionResult,
    ResolutionStatus,
    _get_major_version,
    _lower_proposal,
    _satisfies,
)
from depkeeper.models.conflict import Conflict, ConflictSet


def _c(
    src: str = "a", tgt: str = "b", spec: str = ">=2", ver: str = "1", sv: str = "1.0"
) -> Conflict:
    return Conflict(src, tgt, spec, ver, sv)


class TestConflict:
    def test_names_are_pep503_normalised(self) -> None:
        c = _c("Foo.Bar_baz", "Zope__Interface")
        assert (c.source_package, c.target_package) == ("foo-bar-baz", "zope-interface")

    def test_equality_and_hash_cover_every_field(self) -> None:
        assert _c() == _c("A", "B")
        assert hash(_c()) == hash(_c("A", "B"))
        for other in (
            _c(spec=">=3"),
            _c(ver="0"),
            _c(sv="2.0"),
            _c(src="x"),
            _c(tgt="y"),
        ):
            assert other != _c()
        assert len({_c(), _c("A"), _c(sv="2")}) == 2

    def test_is_immutable(self) -> None:
        with pytest.raises(AttributeError):
            _c().source_package = "x"  # type: ignore[misc]

    def test_display_and_short_strings(self) -> None:
        assert str(_c()) == "a==1.0 requires b>=2"
        assert _c(sv=None).to_display_string() == "a requires b>=2"  # type: ignore[arg-type]
        assert _c().to_short_string() == "a needs >=2"

    def test_to_json_is_complete_and_serialisable(self) -> None:
        import json

        d = _c().to_json()
        assert set(d) == {
            "source_package",
            "source_version",
            "target_package",
            "required_spec",
            "conflicting_version",
        }
        assert json.loads(json.dumps(d)) == d
        assert _c(sv=None).to_json()["source_version"] is None  # type: ignore[arg-type]

    @pytest.mark.parametrize("text", ["ünï", "a b", "", "x" * 5000])
    def test_odd_text_does_not_break_rendering(self, text: str) -> None:
        c = Conflict(text or "a", "t", text, "1", None)
        assert isinstance(str(c), str) and isinstance(repr(c), str)


class TestConflictSet:
    def _set(self, *specs: str) -> ConflictSet:
        return ConflictSet(
            "T", [Conflict("s%d" % i, "t", s, "0") for i, s in enumerate(specs)]
        )

    def test_basics(self) -> None:
        cs = ConflictSet("Some_Pkg")
        assert cs.package_name == "some-pkg" and not cs.has_conflicts() and len(cs) == 0
        cs.add_conflict(_c())
        assert cs.has_conflicts() and list(cs) == [_c()]

    def test_duplicates_are_kept_but_harmless(self) -> None:
        cs = self._set(">=1", ">=1")
        assert len(cs) == 2 and cs.get_max_compatible_version(["1.0", "2.0"]) == "2.0"

    @pytest.mark.parametrize(
        "specs, versions, expected",
        [
            ([], ["1.0"], None),
            ([">=1"], [], None),
            ([">=1", "<2"], ["0.9", "1.0", "1.5", "2.0"], "1.5"),
            ([">=1,<2"], ["1.5", "1.9"], "1.9"),
            ([">=1", "!=1.9"], ["1.9", "1.8"], "1.8"),
            (["<2"], ["2.0rc1", "1.0"], "1.0"),  # pre-releases are never offered
            ([">=2.0rc1"], ["2.0rc1"], None),
            (["==1.0"], ["1.0+local", "0.9"], "1.0+local"),
            (["junk"], ["1.0"], None),
            ([">=1", "junk"], ["1.0"], None),
            (["<1", ">=2"], ["0.5", "2.5"], None),
            ([""], ["1.0", "3.0"], "3.0"),
            ([">=1"], ["bad", "1.0", "x.y"], "1.0"),
            ([">=1"], ["1.0", "1.0.0"], "1.0"),
        ],
    )
    def test_max_compatible(
        self, specs: List[str], versions: List[str], expected: object
    ) -> None:
        assert self._set(*specs).get_max_compatible_version(versions) == expected

    def test_result_is_independent_of_candidate_order(self) -> None:
        versions = ["1.%d.0" % i for i in range(30)]
        cs = self._set(">=1.3", "<1.20", "!=1.19.0")
        expected = cs.get_max_compatible_version(versions)
        assert expected == "1.18.0"
        rnd = random.Random(3)
        for _ in range(20):
            rnd.shuffle(versions)
            assert cs.get_max_compatible_version(versions) == expected

    def test_matches_a_bruteforce_check_of_every_spec(self) -> None:
        rnd = random.Random(11)
        pool = [">=1.1", "<2", "!=1.3.0", ">1.0", "<=1.8", "~=1.2", "==1.*", ""]
        versions = ["1.%d.%d" % (i, j) for i in range(10) for j in range(3)] + [
            "2.0.0",
            "0.9",
        ]
        for _ in range(200):
            specs = rnd.sample(pool, rnd.randint(1, 4))
            got = self._set(*specs).get_max_compatible_version(versions)
            ok = [
                v
                for v in versions
                if all(
                    __import__("packaging.specifiers", fromlist=["x"])
                    .SpecifierSet(s)
                    .contains(v)
                    for s in specs
                )
            ]
            assert got == (max(ok, key=parse) if ok else None), specs


class TestResolutionResult:
    def _result(self) -> ResolutionResult:
        a = PackageResolution(
            "a", "1.5", "1.0", ResolutionStatus.KEPT_CURRENT, [_c("x", "a")], "1.0"
        )
        b = PackageResolution("b", "2.0", "2.0", ResolutionStatus.KEPT_RECOMMENDED, [])
        return ResolutionResult({"a": a, "b": b}, 2, 1, 3, False)

    def test_queries(self) -> None:
        r = self._result()
        assert [p.name for p in r.get_changed_packages()] == ["a"]
        assert [p.name for p in r.get_conflicts()] == ["a"]
        assert r.resolved_versions["a"].was_changed()
        assert not r.resolved_versions["b"].was_changed()
        assert r.resolved_versions["a"].has_conflicts()

    def test_summary_mentions_every_fact(self) -> None:
        text = self._result().summary()
        for needle in (
            "Total packages: 2",
            "Packages with conflicts: 1",
            "Packages changed: 1",
            "Converged: No (3 iterations)",
            "x requires >=2",
            "Compatible alternative: 1.0",
            "a: 1.5 → 1.0 (kept_current)",
        ):
            assert needle in text


class TestHelpers:
    @pytest.mark.parametrize(
        "a, b, expected",
        [
            (None, None, None),
            (None, "1.0", "1.0"),
            ("1.0", None, "1.0"),
            ("1.0", "2.0", "1.0"),
            ("2.0", "1.0", "1.0"),
            ("1.0", "1.0", "1.0"),
            ("garbage", "1.0", "1.0"),
            ("1.0", "garbage", "1.0"),
            ("garbage", "junk", "garbage"),
            ("1.0rc1", "1.0", "1.0rc1"),
        ],
    )
    def test_lower_proposal(self, a: object, b: object, expected: object) -> None:
        assert _lower_proposal(a, b) == expected  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "v, expected",
        [
            ("1.2.3", 1),
            ("0.1", 0),
            ("2024.1.0", 2024),
            ("1!2.0", 2),
            ("v3.1", 3),
            ("bad", None),
            ("", None),
            (None, None),
        ],
    )
    def test_major(self, v: object, expected: object) -> None:
        assert _get_major_version(v) == expected  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "v, spec, expected",
        [
            (None, ">=1", True),
            ("1.0", "bogus", True),
            ("bad", ">=1", True),
            ("2.0rc1", ">=1", True),
            ("1.0", ">=2", False),
            ("1.0+local", "==1.0", True),
            ("1.0", "", True),
        ],
    )
    def test_satisfies(self, v: object, spec: str, expected: bool) -> None:
        assert _satisfies(v, spec) is expected  # type: ignore[arg-type]
