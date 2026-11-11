"""Adversarial and property tests for the pyproject.toml source adapter."""

from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest
import tomli
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from depkeeper.core.sources import get_adapter
from depkeeper.core.sources.pyproject_toml import PyprojectTomlAdapter
from depkeeper.exceptions import DepKeeperError, ParseError

A = PyprojectTomlAdapter()


def _parse(tmp_path: Path, text: str, raw: Optional[bytes] = None):
    p = tmp_path / "pyproject.toml"
    p.write_bytes(raw if raw is not None else text.encode())
    return p, A.parse(p)


def _names(reqs) -> List[str]:
    return [r.name for r in reqs]


# ---------------------------------------------------------------- regressions


def test_escaped_marker_quotes_do_not_hide_dependency(tmp_path: Path) -> None:
    text = '[project]\ndependencies = ["a>=1; python_version<\\"3.9\\"", "b>=2"]\n'
    _, reqs = _parse(tmp_path, text)
    assert _names(reqs) == ["a", "b"]
    assert reqs[0].markers == 'python_version<"3.9"'
    new = A.apply_updates(text, [(reqs[0], "1.5")])
    assert new == text.replace("a>=1;", "a>=1.5;")


def test_escape_inside_version_is_skipped_not_misread(tmp_path: Path) -> None:
    text = '[project]\ndependencies = ["a\\u003e=1", "b>=2"]\n'
    _, reqs = _parse(tmp_path, text)
    assert _names(reqs) == ["b"]


def test_multiline_string_escape_in_marker(tmp_path: Path) -> None:
    text = '[project]\ndependencies = ["""a>=1; os_name == \\"nt\\""""]\n'
    _, reqs = _parse(tmp_path, text)
    assert reqs[0].name == "a" and reqs[0].markers == 'os_name == "nt"'


@pytest.mark.parametrize(
    "table,body",
    [
        ("[tool.uv]", 'dev-dependencies = ["pytest>=7"]'),
        ("[tool.pdm.dev-dependencies]", 'test = ["pytest>=7"]'),
        ("[tool.hatch.envs.default]", 'dependencies = ["pytest>=7"]'),
        ("[tool.hatch.envs.lint]", 'extra-dependencies = ["pytest>=7"]'),
    ],
)
def test_tool_specific_dev_dependencies(tmp_path: Path, table: str, body: str) -> None:
    text = f"{table}\n{body}\n"
    p, reqs = _parse(tmp_path, text)
    assert A.has_dependencies(p) and _names(reqs) == ["pytest"]
    assert A.apply_updates(text, [(reqs[0], "8.1")]) == text.replace(">=7", ">=8.1")


def test_explicit_broken_pyproject_reports_toml_error(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    p.write_text("[proj\nx")
    assert isinstance(get_adapter(p), PyprojectTomlAdapter)
    with pytest.raises(ParseError, match="Invalid TOML"):
        A.parse(p)


def test_pdm_editable_entries_are_quiet(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    text = '[tool.pdm.dev-dependencies]\ndev = ["-e file:///x#egg=x", "a>=1"]\n'
    with caplog.at_level("WARNING"):
        _, reqs = _parse(tmp_path, text)
    assert _names(reqs) == ["a"] and "skipping invalid" not in caplog.text


# ------------------------------------------------------------ TOML quirks


QUIRKS = [
    "[project]\r\ndependencies = [\r\n \"a>=1\", # c\r\n 'b==2',\r\n]\r\n",
    "[project]\ndependencies = [\"\"\"a>=1\"\"\", '''b==2''']\n",
    'project.dependencies = ["a>=1", "b==2"]\n',
    'project = {dependencies = ["a>=1", "b==2"]}\n',
    '[ project ]\n  dependencies = [ "a>=1" ,\n"b==2" ,]\n',
    '[project]\n"dependencies" = ["a>=1", "b==2"] # tail',
    '[project]\nx = {k = "}", j = [1, "]"]}\nd = 1979-05-27 07:32:00\n'
    'dependencies = ["a>=1", "b==2"]\n',
    "[project]\nn = \"\"\"\nline \\\n  two\"\"\"\nm = '''it's'''\n"
    'dependencies = ["a>=1", "b==2"]\n',
    "[[tool.x]]\na = 1\n[[tool.x]]\n[tool.x.sub]\n"
    '[project]\ndependencies = ["a>=1", "b==2"]\n',
    '[project]\n"é.k" = 1\n\'c\\d\' = 2\ndependencies = ["a>=1", "b==2"]\n',
]


@pytest.mark.parametrize("text", QUIRKS)
def test_quirky_layouts_parse_and_update_minimally(tmp_path: Path, text: str) -> None:
    _, reqs = _parse(tmp_path, text)
    assert _names(reqs) == ["a", "b"]
    new = A.apply_updates(text, [(r, "9") for r in reqs])
    assert new == text.replace("a>=1", "a>=9").replace("b==2", "b==9")


def test_bom_file_parses_and_spans_match_stripped_text(tmp_path: Path) -> None:
    body = '[project]\ndependencies = ["a>=1"]\n'
    _, reqs = _parse(tmp_path, body, raw=b"\xef\xbb\xbf" + body.encode())
    assert A.apply_updates(body, [(reqs[0], "2")]) == body.replace(">=1", ">=2")


@pytest.mark.parametrize(
    "text",
    [
        '[project]\ndependencies = ["a>=1"]\ndependencies = ["b"]\n',
        "[project]\ndependencies = [\n",
        '[project]\ndependencies = ["a>=1\n',
        "\x00[project]\n",
    ],
)
def test_invalid_toml_raises_parse_error(tmp_path: Path, text: str) -> None:
    p = tmp_path / "pyproject.toml"
    p.write_bytes(text.encode())
    with pytest.raises(ParseError):
        A.parse(p)
    assert A.requires_python(p) is None


def test_non_array_dependencies_is_a_parse_error(tmp_path: Path) -> None:
    for text in (
        '[project]\ndependencies = "a>=1"\n',
        '[project.optional-dependencies]\nx = "a"\n',
        '[dependency-groups]\ndev = "a"\n',
    ):
        with pytest.raises(ParseError):
            _parse(tmp_path, text)


def test_same_package_in_several_sections_is_reported_each_time(
    tmp_path: Path,
) -> None:
    text = (
        '[project]\ndependencies = ["Foo_Bar>=1"]\n'
        '[project.optional-dependencies]\nx = ["foo-bar>=1"]\n'
        '[dependency-groups]\ndev = ["FOO.BAR>=1", {include-group = "lint"}]\n'
        'lint = ["ruff"]\n[build-system]\nrequires = ["foo_bar>=1"]\n'
    )
    _, reqs = _parse(tmp_path, text)
    assert len(reqs) == 5
    new = A.apply_updates(text, [(r, "2") for r in reqs if r.name != "ruff"])
    assert new.count(">=2") == 4 and "ruff" in new and "ruff==" not in new


def test_huge_dependency_array(tmp_path: Path) -> None:
    n = 5000
    text = "[project]\ndependencies = [\n" + "".join(
        f'  "pkg{i}>={i}.0",  # c{i}\n' for i in range(n)
    )
    text += "]\n"
    _, reqs = _parse(tmp_path, text)
    assert len(reqs) == n
    new = A.apply_updates(text, [(r, "99") for r in reqs])
    assert new.count(">=99") == n and new.count("# c") == n


# ------------------------------------------------------------ Poetry


def test_poetry_forms(tmp_path: Path) -> None:
    text = """\
[tool.poetry.dependencies]
python = "^3.8"
a = "^1.2"
b = {version = "~1.2.3", extras = ["x"], python = ">=3.9"}
c = "*"
d = {git = "https://x/y.git", rev = "v1"}
e = [{version = "^1", python = "<3.9"}, {version = "^2", python = ">=3.9"}]
f = "^1 || ^2"
g = ">=1.0,<2.0"
h = "1.4.2"
i.version = "^0.3.1"

[tool.poetry.dependencies.j]
version = "^4"
optional = true

[tool.poetry.group.dev.dependencies]
k = "^7"
[tool.poetry.dev-dependencies]
l = "==3.0.0"
"""
    _, reqs = _parse(tmp_path, text)
    assert sorted(_names(reqs)) == ["a", "b", "g", "h", "i", "j", "k", "l"]
    new = A.apply_updates(text, [(r, "10.5.0") for r in reqs if r.name != "g"])
    expect = (
        text.replace('"^1.2"', '"^10.5.0"')
        .replace('"~1.2.3"', '"~10.5.0"')
        .replace('"1.4.2"', '"10.5.0"')
        .replace('"^0.3.1"', '"^10.5.0"')
        .replace('"^4"', '"^10.5.0"')
        .replace('"^7"', '"^10.5.0"')
        .replace('"==3.0.0"', '"==10.5.0"')
    )
    assert new == expect


def test_poetry_pin_replaces_caret(tmp_path: Path) -> None:
    text = '[tool.poetry.dependencies]\na = "^1.2"\nb = ">=1,<3"\n'
    _, reqs = _parse(tmp_path, text)
    new = A.apply_updates(text, [(r, "2.1") for r in reqs], pin=True)
    assert new == '[tool.poetry.dependencies]\na = "==2.1"\nb = "==2.1"\n'


def test_poetry_caret_ranges_match_poetry_semantics(tmp_path: Path) -> None:
    cases = {
        "^1.2.3": (">=1.2.3", "<2"),
        "^0.2.3": (">=0.2.3", "<0.3"),
        "^0.0.3": (">=0.0.3", "<0.0.4"),
        "^0": (">=0", "<1"),
        "~1.2.3": (">=1.2.3", "<1.3"),
        "~1": (">=1", "<2"),
        "~1.2": (">=1.2", "<1.3"),
    }
    body = "".join(f'p{i} = "{c}"\n' for i, c in enumerate(cases))
    _, reqs = _parse(tmp_path, "[tool.poetry.dependencies]\n" + body)
    for r, got in zip(reqs, cases.values()):
        assert tuple(f"{o}{v}" for o, v in r.specs) == got


# ------------------------------------------------------------ update safety


def test_stale_span_raises(tmp_path: Path) -> None:
    text = '[project]\ndependencies = ["a>=1", "b>=2"]\n'
    _, reqs = _parse(tmp_path, text)
    for stale in (
        text.replace("a>=1", "a>=7"),  # same length, different specifier
        "# header\n" + text,  # shifted
    ):
        with pytest.raises(DepKeeperError):
            A.apply_updates(stale, [(r, "3") for r in reqs])


@pytest.mark.parametrize("bad", ['1"2', "1\n2", "1\\"])
def test_invalid_result_is_never_returned(tmp_path: Path, bad: str) -> None:
    text = '[project]\ndependencies = ["a>=1"]\n'
    _, reqs = _parse(tmp_path, text)
    with pytest.raises(DepKeeperError):
        A.apply_updates(text, [(reqs[0], bad)])


def test_excluding_cap_raises_with_location(tmp_path: Path) -> None:
    text = '[project]\ndependencies = ["a>=1,<2"]\n'
    p, reqs = _parse(tmp_path, text)
    with pytest.raises(DepKeeperError, match=r"pyproject\.toml:2"):
        A.apply_updates(text, [(reqs[0], "3.0")], path=p)


def test_direct_reference_update_is_a_noop(tmp_path: Path) -> None:
    text = '[project]\ndependencies = ["c @ https://x/y.whl", "a>=1"]\n'
    _, reqs = _parse(tmp_path, text)
    assert A.apply_updates(text, [(r, "5") for r in reqs]) == text.replace(">=1", ">=5")


def test_requires_python(tmp_path: Path) -> None:
    p, _ = _parse(tmp_path, '[project]\nrequires-python = ">=3.9"\ndependencies = []\n')
    assert A.requires_python(p) == ">=3.9"
    p.write_text("[project]\nrequires-python = 3\n")
    assert A.requires_python(p) is None


# ------------------------------------------------------------ properties

NAMES = ["requests", "Django", "typing_extensions", "zope.interface", "a-b", "x1"]
SPECS = [
    "",
    ">=1.0",
    "==2.3.4",
    "~=1.4",
    "~=1.4.2",
    ">1,<3",
    "<3",
    ">=1.0,!=1.5",
    "==1.*",
    " >= 1.0 , < 2.0 ",
    ">=1.0,<2",
    "===1.2",
]
CANDIDATES = ["0.5", "1.5", "1.6.1", "2.3.4", "2.9.9", "10.0", "1.2"]
MARKERS = ["", '; python_version<"3.9"', " ; os_name == 'nt'", ";sys_platform=='win32'"]
Q = ['"', "'", '"""', "'''"]


def _gen_doc(rng: random.Random) -> Tuple[str, Dict[str, List[str]]]:
    """Random pyproject text and, per section, the dependency strings it holds."""
    eol = rng.choice(["\n", "\r\n"])
    sections: Dict[str, List[str]] = {}
    out: List[str] = []

    def array(key: str, n: int) -> str:
        items, strings = [], []
        for _ in range(n):
            extras = rng.choice(["", "[x]", "[x, y]", " [x]"])
            s = rng.choice(NAMES) + extras + rng.choice(SPECS) + rng.choice(MARKERS)
            strings.append(s)
            q = rng.choice(Q)
            if len(q) == 1 and q in s:
                q = "'" if q == '"' and "'" not in s else '"""'
            items.append(q + s + q)
        sections[key] = strings
        if rng.random() < 0.3:
            return "[" + ", ".join(items) + "]"
        lines = [
            rng.choice(["  ", "\t", ""])
            + it
            + rng.choice([",", ",", " ,"])
            + rng.choice(["", "  # c ] [", ' # "x"'])
            for it in items
        ]
        return "[" + eol + eol.join(lines) + eol + "]"

    if rng.random() < 0.7:
        out.append("[project]")
        out.append('name = "demo"')
        out.append(f"dependencies = {array('project', rng.randint(0, 4))}")
        if rng.random() < 0.5:
            out.append("[project.optional-dependencies]")
            out.append(f"dev = {array('opt-dev', rng.randint(0, 3))}")
            out.append(f'"my-extra" = {array("opt-x", rng.randint(0, 2))}')
    if rng.random() < 0.5:
        out.append("[dependency-groups]")
        out.append(f"test = {array('group-test', rng.randint(1, 3))}")
        out.append('lint = [{include-group = "test"}, "ruff>=0.1"]')
        sections["group-lint"] = ["ruff>=0.1"]
    if rng.random() < 0.4:
        out.append("[build-system]")
        out.append(f"requires = {array('build', rng.randint(1, 3))}")
    return eol.join(out) + eol, sections


def _satisfying(spec_text: str, rng: random.Random) -> Optional[str]:
    m = re.search(r"[<>=!~].*", re.sub(r";.*", "", spec_text))
    ok = []
    for c in CANDIDATES:
        if m is None or SpecifierSet(m.group().replace(" ", "")).contains(
            Version(c), prereleases=True
        ):
            ok.append(c)
    return rng.choice(ok) if ok else None


@pytest.mark.parametrize("seed", range(120))
def test_random_documents_update_minimally_and_idempotently(
    tmp_path: Path, seed: int
) -> None:
    rng = random.Random(seed)
    text, sections = _gen_doc(rng)
    data = tomli.loads(text)  # oracle: the generator produced valid TOML
    expected = [s for strings in sections.values() for s in strings]
    got_strings = (
        data.get("project", {}).get("dependencies", [])
        + [
            s
            for v in data.get("project", {}).get("optional-dependencies", {}).values()
            for s in v
        ]
        + [
            s
            for v in data.get("dependency-groups", {}).values()
            for s in v
            if isinstance(s, str)
        ]
        + data.get("build-system", {}).get("requires", [])
    )
    assert sorted(got_strings) == sorted(expected)

    p, reqs = _parse(tmp_path, text)
    assert len(reqs) == len(expected)
    assert sorted(r.name.lower() for r in reqs) == sorted(
        re.match(r"[A-Za-z0-9._-]+", s).group().lower()
        for s in expected  # type: ignore[union-attr]
    )

    updates = []
    for r in reqs:
        seg = text[r.span[0] : r.span[1]]  # type: ignore[index]
        ver = _satisfying(seg, rng)
        if ver and rng.random() < 0.7:
            updates.append((r, ver))
    if not updates:
        return
    new = A.apply_updates(text, updates)

    # every update touches only its own span, and only with specifier characters
    middles = {}
    for r, ver in updates:
        s, e = r.span  # type: ignore[misc]
        one = A.apply_updates(text, [(r, ver)])
        assert one[:s] == text[:s] and one.endswith(text[e:])
        middle = one[s : len(one) - (len(text) - e)]
        assert re.fullmatch(r"[0-9A-Za-z.,<>=!~* ]*", middle), middle
        # A compatible-release bound that already admits the target is kept.
        kept = middle.startswith("~=") and SpecifierSet(middle).contains(ver)
        assert ver in middle or kept, (r.span, ver, middle)
        middles[(s, e)] = middle
    expected_text = text
    for (s, e), middle in sorted(middles.items(), reverse=True):
        expected_text = expected_text[:s] + middle + expected_text[e:]
    assert new == expected_text
    tomli.loads(new)

    # idempotent: re-reading and applying the same versions changes nothing
    p.write_bytes(new.encode())  # bytes: text mode would turn \n into \r\n on Windows
    again = A.parse(p)
    assert len(again) == len(reqs)
    chosen = {id(r): v for r, v in updates}
    redo = [(n, chosen[id(o)]) for o, n in zip(reqs, again) if id(o) in chosen]
    assert A.apply_updates(new, redo) == new
