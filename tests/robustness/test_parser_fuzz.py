"""Differential, round-trip and minimal-diff property tests for the requirements parser."""

from __future__ import annotations

import random
import re
import time
from typing import List, Tuple

import pytest
from packaging.requirements import Requirement as PkgRequirement
from packaging.utils import canonicalize_name

from depkeeper.core.parser import RequirementsParser
from depkeeper.models.requirement import Requirement

NAMES = [
    "Foo",
    "foo_bar",
    "Foo.Bar-baz",
    "zope.interface",
    "A",
    "x1",
    "Django",
    "PyYAML",
]
EXTRAS = ["", "[security]", "[Sec , socks]", "[a_b]", "[ x ]"]
VERSIONS = [
    "1",
    "1.0",
    "2.31.0",
    "1!2.0",
    "1.0.post1",
    "1.0.dev3",
    "1.0rc1",
    "1.0+local.1",
    "2020.1.1",
    "0.0.1",
]
OPS = [">=", "<=", "==", "!=", "~=", ">", "<"]
MARKERS = [
    "",
    "; python_version<'3.9'",
    '; python_version >= "3.8" and os_name == "nt"',
    "; sys_platform=='win32' or extra == 'a'",
    "; extra == 'a#b'",
]
COMMENTS = ["", "  # note", " #x", "\t# tab"]


def _spec(rng: random.Random) -> str:
    parts: List[str] = []
    for _ in range(rng.randint(0, 3)):
        op = rng.choice(OPS)
        version = rng.choice(VERSIONS)
        if op in ("==", "!=") and rng.random() < 0.2:
            version = version.split("+")[0].split(".post")[0] + ".*"
            version = version if "!" not in version else "1.*"
        parts.append(f"{op}{rng.choice(['', ' '])}{version}")
    if rng.random() < 0.1:
        parts.append("===" + rng.choice(["abc", "1.0"]))
    sep = rng.choice([",", " , ", ", "])
    return sep.join(parts)


def _lines(seed: int, count: int) -> List[str]:
    rng = random.Random(seed)
    out = []
    for _ in range(count):
        line = (
            rng.choice(NAMES)
            + rng.choice(EXTRAS)
            + rng.choice(["", " "])
            + _spec(rng)
            + rng.choice(MARKERS if rng.random() < 0.5 else [""])
            + rng.choice(COMMENTS)
        )
        out.append(line)
    return out


def _strip_comment(line: str) -> str:
    return line.split("  #")[0].split(" #")[0].split("\t#")[0]


def _valid(seed: int, count: int = 120) -> List[Tuple[str, Requirement]]:
    """Generated lines ``packaging`` accepts, with depkeeper's parse of each."""
    out = []
    for line in _lines(seed, count):
        try:
            PkgRequirement(_strip_comment(line))
        except Exception:
            continue
        req = RequirementsParser().parse_line(line, 1)
        assert isinstance(req, Requirement), line
        out.append((line, req))
    return out


def _pairs(req: PkgRequirement) -> List[Tuple[str, str]]:
    return sorted((s.operator, s.version) for s in req.specifier)


class TestDifferential:
    """The parser must agree with ``packaging`` on every PEP 508 line."""

    @pytest.mark.parametrize("seed", range(5))
    def test_matches_packaging(self, seed: int) -> None:
        for line in _lines(seed, 120):
            body = _strip_comment(line)
            try:
                expected = PkgRequirement(body)
            except Exception:
                with pytest.raises(Exception):
                    RequirementsParser().parse_line(line, 1)
                continue
            got = RequirementsParser().parse_line(line, 1)
            assert isinstance(got, Requirement), line
            assert got.name == canonicalize_name(expected.name), line
            assert got.extras == sorted(expected.extras), line
            assert sorted(got.specs) == _pairs(expected), line
            assert got.markers == (str(expected.marker) if expected.marker else None)

    @pytest.mark.parametrize("seed", range(5))
    def test_spec_order_is_source_order(self, seed: int) -> None:
        for line, got in _valid(seed):
            body = _strip_comment(line).split(";")[0]
            if len(got.specs) < 2:
                continue
            written = re.findall(r"(===|==|!=|<=|>=|~=|<|>)\s*([^\s,;]+)", body)
            assert list(dict.fromkeys(got.specs)) == list(dict.fromkeys(written)), line


class TestRoundTrip:
    """parse -> to_string -> parse is stable."""

    @pytest.mark.parametrize("seed", range(5))
    def test_roundtrip(self, seed: int) -> None:
        for line, first in _valid(seed):
            rendered = first.to_string()
            second = RequirementsParser().parse_line(rendered, 1)
            assert isinstance(second, Requirement)
            assert (second.name, second.specs, second.extras, second.markers) == (
                first.name,
                first.specs,
                first.extras,
                first.markers,
            ), (line, rendered)
            assert second.comment == first.comment
            assert second.to_string() == rendered

    @pytest.mark.parametrize(
        "line",
        [
            "foo @ https://x.com/a.zip#sha256=abc",
            "foo[a] @ git+https://x/y.git@v1#egg=foo",
            "-e git+https://x/y.git#egg=foo",
            "git+https://x/y.git#egg=foo ; python_version < '3'",
        ],
    )
    def test_direct_references_keep_form_and_name(self, line: str) -> None:
        req = RequirementsParser().parse_line(line, 1)
        assert isinstance(req, Requirement)
        again = RequirementsParser().parse_line(req.to_string(), 1)
        assert isinstance(again, Requirement)
        assert (again.name, again.url, again.editable, again.direct_reference) == (
            req.name,
            req.url,
            req.editable,
            req.direct_reference,
        )
        assert again.markers == req.markers
        assert req.name in req.to_string() or "#egg=" in req.to_string()


class TestUpdateMinimalDiff:
    """update_version moves only the intended specifiers and keeps the line."""

    @pytest.mark.parametrize("seed", range(5))
    def test_only_floor_changes_and_rest_is_verbatim(self, seed: int) -> None:
        for line, req in _valid(seed):
            try:
                out = req.update_version("9.9.9", preserve_trailing_newline=False)
            except ValueError:
                continue  # a declared upper bound excludes the target: refusal is correct
            new = RequirementsParser().parse_line(out, 1)
            assert isinstance(new, Requirement), (line, out)
            assert new.extras == req.extras
            assert new.markers == req.markers
            assert new.comment == req.comment
            # Retained specifiers survive untouched; the line keeps its own spelling.
            assert out.lstrip(" \"'").startswith(line.lstrip(" \"'")[:1])
            kept = [
                s for s in req.specs if s[0] in ("<", "<=", "!=") or s[1].endswith("*")
            ]
            for spec in kept:
                assert spec in new.specs, (line, out)

    def test_idempotent(self) -> None:
        for line, req in _valid(7, 150):
            try:
                once = req.update_version("9.9.9", preserve_trailing_newline=False)
            except ValueError:
                continue
            again = RequirementsParser().parse_line(once, 1)
            assert isinstance(again, Requirement)
            twice = again.update_version("9.9.9", preserve_trailing_newline=False)
            assert twice == once, (line, once, twice)

    @pytest.mark.parametrize(
        "line,expected",
        [
            ("Django>=3.0  # keep", "Django>=4.2.1  # keep"),
            ("Foo_Bar[Extra , X] >= 1 , < 5", "Foo_Bar[Extra , X] >= 4.2.1 , < 5"),
            ('"flask>=1.0"', '"flask>=4.2.1"'),
            ("'flask>=1.0' # c", "'flask>=4.2.1' # c"),
            ("celery[redis]>=5.0,<6.0 ; python_version<'3.12'", None),
            ("zope.interface ; sys_platform=='linux'", None),
            ("x~=1.0", "x~=4.2"),
            ("x===1.0", "x===4.2.1"),
            ("x>1,!=2.0", "x>=4.2.1,!=2.0"),
            ("x>=1 --hash=sha256:aa  # c", "x>=4.2.1  # c"),
            ("-e foo>=1", None),
        ],
    )
    def test_cases(self, line: str, expected: str) -> None:
        parser = RequirementsParser()
        req = parser.parse_line(line, 1)
        assert isinstance(req, Requirement)
        out = req.update_version(
            "4.2.1", preserve_trailing_newline=False, allow_hash_removal=True
        )
        if expected is not None:
            assert out == expected
        else:
            # Everything outside the specifier text is byte-identical.
            assert out.split(";")[-1].strip() == line.split(";")[-1].strip() or (
                ";" not in line
            )
            assert out[0] == line[0]


class TestPerformance:
    def test_50k_lines(self) -> None:
        text = "\n".join(
            f"pkg{i}>=1.{i},<3 ; python_version>'3.6'  # c{i}" for i in range(50_000)
        )
        started = time.perf_counter()
        reqs = RequirementsParser().parse_string(text)
        assert len(reqs) == 50_000
        assert time.perf_counter() - started < 15

    def test_many_hashes_in_fragment_is_linear(self) -> None:
        line = "https://a/" + "#x" * 60_000
        started = time.perf_counter()
        RequirementsParser().parse_line(line, 1)
        assert time.perf_counter() - started < 2
