"""PyprojectTomlAdapter: parsing and byte-minimal in-place edits."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from depkeeper.exceptions import DepKeeperError, ParseError
from depkeeper.models.requirement import Requirement
from depkeeper.core.sources import get_adapter
from depkeeper.core.sources.pyproject_toml import PyprojectTomlAdapter

A = PyprojectTomlAdapter()

FLIT = '''\
[build-system]
requires = ["flit_core >=3.2,<4"]  # backend
build-backend = "flit_core.buildapi"

[project]
name = "demo"
requires-python = ">=3.8"
dependencies = [
    "requests>=2.0",   # http
    'click [extra1, extra2] >= 8.0 ; python_version >= "3.8"',
    "rich",
    "pkg @ https://example.com/pkg.whl",
    """tomli==1.0""",
]

[project.optional-dependencies]
test = ["pytest~=7.0", "coverage"]
'''

SETUPTOOLS_UV = """\
[build-system]
requires = ["setuptools>=61", "wheel"]

[project]
name = "x"
dependencies = ["numpy>=1.20,<2"]

[dependency-groups]
dev = ["pytest>=7", {include-group = "lint"}]
lint = ["ruff==0.1.0"]
"""

POETRY = """\
[tool.poetry]
name = "p"

[tool.poetry.dependencies]
python = "^3.8"
requests = "^2.25"
flask = "~1.1.2"
attrs = "21.2.0"
pyyaml = "==5.4"
click = ">=7.0,<9"
django = { version = "^3.2", extras = ["argon2"] }
mylib = { git = "https://github.com/a/b.git" }
local = { path = "../local" }
star = "*"

[tool.poetry.group.dev.dependencies]
pytest = "^7.0"
"""


def _parse(
    tmp_path: Path, text: str, newline: str = "\n"
) -> Tuple[Path, str, List[Requirement]]:
    p = tmp_path / "pyproject.toml"
    p.write_bytes(text.replace("\n", newline).encode())
    return p, p.read_bytes().decode(), A.parse(p)


def _apply(
    text: str, reqs: List[Requirement], versions: Dict[str, str], **kw: Any
) -> str:
    ups = [(r, versions[r.name]) for r in reqs if r.name in versions]
    return A.apply_updates(text, ups, **kw)


def _changed_lines(a: str, b: str) -> List[str]:
    d = difflib.ndiff(a.splitlines(True), b.splitlines(True))
    return [x for x in d if x[0] in "+-"]


def test_flit_parse(tmp_path: Path) -> None:
    p, _, reqs = _parse(tmp_path, FLIT)
    by = {r.name: r for r in reqs}
    assert set(by) == {
        "flit_core",
        "requests",
        "click",
        "rich",
        "pkg",
        "tomli",
        "pytest",
        "coverage",
    }
    assert by["click"].extras == ["extra1", "extra2"]
    assert by["click"].markers == 'python_version >= "3.8"'
    assert by["click"].specs == [(">=", "8.0")]
    assert by["pkg"].url and by["pkg"].span is None
    assert by["rich"].specs == [] and by["rich"].span is not None
    assert all(r.source_format == "pyproject" for r in reqs)
    assert A.requires_python(p) == ">=3.8"


def test_flit_roundtrip_minimal_diff(tmp_path: Path) -> None:
    _, text, reqs = _parse(tmp_path, FLIT)
    new = _apply(
        text,
        reqs,
        {
            "requests": "2.31.0",
            "click": "8.1.7",
            "flit_core": "3.9.0",
            "rich": "13.0.0",
            "tomli": "2.0.1",
            "pkg": "9",
        },
    )
    assert new.splitlines()[1] == 'requires = ["flit_core >=3.9.0,<4"]  # backend'
    assert '    "requests>=2.31.0",   # http' in new
    assert "'click [extra1, extra2] >=8.1.7 ; python_version >= \"3.8\"'" in new
    assert '    "rich==13.0.0",' in new
    assert '"""tomli==2.0.1"""' in new
    assert "pkg @ https://example.com/pkg.whl" in new
    assert len([x for x in _changed_lines(text, new) if x[0] == "-"]) == 5


def test_noop_is_identical(tmp_path: Path) -> None:
    _, text, reqs = _parse(tmp_path, FLIT)
    assert A.apply_updates(text, []) == text
    assert A.apply_updates(text, [(r, "1") for r in reqs if r.url]) == text


def test_pin(tmp_path: Path) -> None:
    _, text, reqs = _parse(tmp_path, FLIT)
    new = _apply(text, reqs, {"flit_core": "3.9.0"}, pin=True)
    assert 'requires = ["flit_core ==3.9.0"]' in new


@pytest.mark.parametrize("nl", ["\n", "\r\n"])
def test_uv_setuptools_groups(tmp_path: Path, nl: str) -> None:
    _, text, reqs = _parse(tmp_path, SETUPTOOLS_UV, nl)
    assert sorted(r.name for r in reqs) == [
        "numpy",
        "pytest",
        "ruff",
        "setuptools",
        "wheel",
    ]
    new = _apply(
        text,
        reqs,
        {"pytest": "8.0", "ruff": "0.5.0", "numpy": "1.26.0", "wheel": "0.42"},
    )
    assert 'dev = ["pytest>=8.0", {include-group = "lint"}]' in new
    assert 'lint = ["ruff==0.5.0"]' in new and '"numpy>=1.26.0,<2"' in new
    assert (
        text.count("\r\n")
        == new.count("\r\n")
        == (text.count("\n") if nl == "\r\n" else 0)
    )
    assert len(_changed_lines(text, new)) == 8


def test_poetry_parse(tmp_path: Path) -> None:
    _, _, reqs = _parse(tmp_path, POETRY)
    by = {r.name: r.specs for r in reqs}
    assert set(by) == {
        "requests",
        "flask",
        "attrs",
        "pyyaml",
        "click",
        "django",
        "pytest",
    }
    assert by["requests"] == [(">=", "2.25"), ("<", "3")]
    assert by["flask"] == [(">=", "1.1.2"), ("<", "1.2")]
    assert by["attrs"] == [("==", "21.2.0")]
    assert by["click"] == [(">=", "7.0"), ("<", "9")]


def test_poetry_roundtrip(tmp_path: Path) -> None:
    _, text, reqs = _parse(tmp_path, POETRY)
    new = _apply(
        text,
        reqs,
        {
            "requests": "2.31.0",
            "flask": "1.1.4",
            "attrs": "23.1.0",
            "pyyaml": "6.0",
            "click": "8.1",
            "django": "3.2.9",
            "pytest": "7.4.0",
        },
    )
    assert 'requests = "^2.31.0"' in new and 'flask = "~1.1.4"' in new
    assert 'attrs = "23.1.0"' in new and 'pyyaml = "==6.0"' in new
    assert 'click = ">=8.1,<9"' in new
    assert 'django = { version = "^3.2.9", extras = ["argon2"] }' in new
    assert 'python = "^3.8"' in new and 'star = "*"' in new
    assert len(_changed_lines(text, new)) == 14
    assert (
        _apply(text, reqs, {"requests": "2.31.0"}, pin=True).count(
            'requests = "==2.31.0"'
        )
        == 1
    )


def test_literal_strings_and_multiline(tmp_path: Path) -> None:
    text = "[project]\nname='x'\ndependencies = [\n  'a>=1', # c1\n\n  \"b==2\",  \n]\n"
    _, text, reqs = _parse(tmp_path, text)
    new = _apply(text, reqs, {"a": "1.5", "b": "3"})
    assert new == text.replace("a>=1", "a>=1.5").replace("b==2", "b==3")


def test_invalid_toml(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    p.write_text("[project]\nname = \n dependencies = [")
    assert A.can_handle(p) is True
    with pytest.raises(ParseError) as ei:
        A.parse(p)
    assert ei.value.line_number == 2


def test_can_handle(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    p.write_text("[tool.ruff]\nline-length = 88\n")
    assert A.can_handle(p) is True and A.has_dependencies(p) is False
    p.write_text('[project]\nname = "x"\n')
    assert A.can_handle(p) is True and A.has_dependencies(p) is False
    p.write_text("[project]\ndependencies = []\n")
    assert A.has_dependencies(p) is True
    assert A.can_handle(p) is True and isinstance(get_adapter(p), PyprojectTomlAdapter)
    assert A.can_handle(tmp_path / "other.toml") is False
    assert A.can_handle(tmp_path / "missing" / "pyproject.toml") is False


def test_excluded_constraint_raises(tmp_path: Path) -> None:
    _, text, reqs = _parse(tmp_path, '[project]\ndependencies = ["a<2"]\n')
    with pytest.raises(DepKeeperError, match="pyproject.toml:2"):
        A.apply_updates(text, [(reqs[0], "3.0")], path="pyproject.toml")


def test_requires_python_absent(tmp_path: Path) -> None:
    p, _, _ = _parse(tmp_path, '[project]\ndependencies = ["a"]\n')
    assert A.requires_python(p) is None


def test_escaped_string_skip_is_loud(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    f = tmp_path / "pyproject.toml"
    f.write_text(
        '[project]\nname = "d"\ndependencies = [\n    "ok>=1.0",\n    "a\\u0062c>=1.0",\n]\n'
    )
    with caplog.at_level("WARNING"):
        reqs = A.parse(f)
    assert [r.name for r in reqs] == ["ok"]
    assert any(f"{f}:5" in r.getMessage() for r in caplog.records)


def test_wrong_type_dependencies_is_parse_error(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    p.write_text('[project]\ndependencies = "requests"\n')
    with pytest.raises(ParseError) as ei:
        A.parse(p)
    assert ei.value.line_number == 2


def test_invalid_entries_warn_with_location(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    p = tmp_path / "pyproject.toml"
    p.write_text('[project]\ndependencies = [\n  "not a req!!",\n  5,\n  "ok>=1",\n]\n')
    with caplog.at_level(logging.WARNING):
        reqs = A.parse(p)
    assert [r.name for r in reqs] == ["ok"]
    assert "pyproject.toml:3" in caplog.text and "pyproject.toml:4" in caplog.text


def test_stale_text_at_span_is_refused(tmp_path: Path) -> None:
    _, text, reqs = _parse(tmp_path, '[project]\ndependencies = ["a>=1.0"]\n')
    with pytest.raises(DepKeeperError, match="changed since"):
        A.apply_updates("# new header line\n" + text, [(reqs[0], "2.0")], path="p")
