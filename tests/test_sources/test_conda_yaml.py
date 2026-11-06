"""CondaYamlAdapter: reading, approximate semantics and minimal write-back."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Dict, List

import pytest

from depkeeper.exceptions import DepKeeperError, ParseError
from depkeeper.core.sources import get_adapter
from depkeeper.core.sources.conda_yaml import CondaYamlAdapter

ENV = """\
# data science env
name: ds
channels:
  - conda-forge
  - defaults
dependencies:
  - python=3.11
  - pip
  - numpy=1.24  # pinned
  - pandas=2.0.*
  - conda-forge::scipy>=1.10,<2
  - scikit-learn 1.2.*
  - "matplotlib==3.7.1"
  - 'requests'
  - mkl=2023.1
  - libgcc-ng
  - pytorch=2.0
  - openblas=0.3.21=h1234_0
  - pip:
    - requests>=2.28,<3  # http
    - "rich==13.0.0"
    - --index-url https://example.com/simple
    - git+https://github.com/x/y.git#egg=y
"""


def write(tmp_path: Path, text: str, name: str = "environment.yml") -> Path:
    p = tmp_path / name
    p.write_bytes(text.encode())
    return p


def apply(text: str, updates: Dict[str, str], tmp_path: Path, **kw: bool) -> str:
    a = CondaYamlAdapter()
    reqs = {r.name: r for r in a.parse(write(tmp_path, text))}
    return a.apply_updates(text, [(reqs[n], v) for n, v in updates.items()], **kw)


def diff(a: str, b: str) -> List[str]:
    d = [
        x
        for x in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0)
        if x[0] in "+-" and x[:3] not in ("+++", "---")
    ]
    return [x for x in d if x[0] == "-"] + [x for x in d if x[0] == "+"]


def test_can_handle_and_registry(tmp_path: Path) -> None:
    a = CondaYamlAdapter()
    assert get_adapter(tmp_path / "environment.yaml").name == a.name
    other = write(tmp_path, "dependencies:\n  - a\n", "ci.yml")
    assert a.can_handle(other)
    assert not a.can_handle(write(tmp_path, "foo: 1\n", "x.yml"))
    assert not a.can_handle(tmp_path / "missing.yml")


def test_parse_realistic_env(tmp_path: Path) -> None:
    a = CondaYamlAdapter()
    reqs = {r.name: r for r in a.parse(write(tmp_path, ENV))}
    # python, pip, mkl, libgcc-ng and the build-string pin are skipped quietly
    assert set(reqs) == {
        "numpy", "pandas", "scipy", "scikit-learn", "matplotlib", "requests",
        "torch", "rich", "y",
    }  # fmt: skip
    assert reqs["numpy"].specs == [("==", "1.24")]
    assert reqs["pandas"].specs == [("==", "2.0")]
    assert reqs["scipy"].specs == [(">=", "1.10"), ("<", "2")]
    assert reqs["scikit-learn"].specs == [("==", "1.2")]
    assert reqs["matplotlib"].specs == [("==", "3.7.1")]
    assert reqs["numpy"].source_format == "conda" and reqs["numpy"].approximate
    assert reqs["rich"].source_format == a.name and not reqs["rich"].approximate
    assert a.requires_python(tmp_path / "environment.yml") == "==3.11.*"


def test_requires_python_variants(tmp_path: Path) -> None:
    a = CondaYamlAdapter()
    p = write(tmp_path, "dependencies:\n  - python>=3.9\n")
    assert a.requires_python(p) == ">=3.9"
    p = write(tmp_path, "dependencies:\n  - numpy\n")
    assert a.requires_python(p) is None


def test_roundtrip_minimal_diff(tmp_path: Path) -> None:
    new = apply(
        ENV,
        {
            "numpy": "1.26.4",
            "pandas": "2.2.1",
            "scipy": "1.13.0",
            "scikit-learn": "1.4.2",
            "matplotlib": "3.8.4",
            "rich": "13.7.1",
        },
        tmp_path,
    )
    assert diff(ENV, new) == [
        "-  - numpy=1.24  # pinned",
        "-  - pandas=2.0.*",
        "-  - conda-forge::scipy>=1.10,<2",
        "-  - scikit-learn 1.2.*",
        '-  - "matplotlib==3.7.1"',
        '-    - "rich==13.0.0"',
        "+  - numpy=1.26  # pinned",
        "+  - pandas=2.2.*",
        "+  - conda-forge::scipy>=1.13.0,<2",
        "+  - scikit-learn 1.4.*",
        '+  - "matplotlib==3.8.4"',
        '+    - "rich==13.7.1"',
    ]


def test_pip_item_keeps_comment_and_noop_is_identical(tmp_path: Path) -> None:
    new = apply(ENV, {"requests": "2.32.0"}, tmp_path)
    assert "    - requests>=2.32.0,<3  # http" in new
    assert apply(ENV, {}, tmp_path) == ENV


def test_pin_and_unpinned(tmp_path: Path) -> None:
    text = "dependencies:\n  - numpy=1.24\n  - flask\n"
    new = apply(text, {"numpy": "1.26.4", "flask": "3.0.0"}, tmp_path, pin=True)
    assert new == "dependencies:\n  - numpy==1.26.4\n  - flask=3.0.0\n"
    new = apply(text, {"flask": "3.0.0"}, tmp_path)
    assert new.endswith("  - flask=3.0.0\n")


def test_cap_excludes_version_raises(tmp_path: Path) -> None:
    with pytest.raises(DepKeeperError, match="excludes"):
        apply("dependencies:\n  - scipy>=1,<2\n", {"scipy": "2.1.0"}, tmp_path)


def test_crlf_preserved(tmp_path: Path) -> None:
    text = ENV.replace("\n", "\r\n")
    new = apply(text, {"numpy": "1.26.4", "rich": "13.7.1"}, tmp_path)
    assert new.count("\r\n") == text.count("\r\n") == new.count("\n")
    assert "numpy=1.26  # pinned\r\n" in new


def test_bom_and_dash_at_key_indent(tmp_path: Path) -> None:
    p = tmp_path / "environment.yml"
    p.write_bytes(b"\xef\xbb\xbfdependencies:\n- numpy=1.24\n- pip:\n  - rich==1.0\n")
    assert [r.name for r in CondaYamlAdapter().parse(p)] == ["numpy", "rich"]


def test_stale_pip_span_raises(tmp_path: Path) -> None:
    a = CondaYamlAdapter()
    reqs = a.parse(write(tmp_path, ENV))
    rich = next(r for r in reqs if r.name == "rich")
    with pytest.raises(DepKeeperError, match="changed"):
        a.apply_updates(ENV.replace("13.0.0", "13.0.1"), [(rich, "14.0.0")])


@pytest.mark.parametrize(
    "text",
    [
        "dependencies: [numpy, pandas]\n",
        "dependencies:\n  - 'numpy=1.24\n",
        "dependencies:\n\t- numpy\n",
        "dependencies:\n  foo: bar\n",
        "dependencies:\n  - pip: [a, b]\n",
    ],
)
def test_malformed_raises_parse_error(tmp_path: Path, text: str) -> None:
    with pytest.raises(ParseError):
        CondaYamlAdapter().parse(write(tmp_path, text))


def test_no_dependencies_key_and_empty(tmp_path: Path) -> None:
    a = CondaYamlAdapter()
    assert a.parse(write(tmp_path, "name: x\nchannels:\n  - defaults\n")) == []
    assert a.parse(write(tmp_path, "dependencies: []\n")) == []


def test_unsupported_specs_are_skipped(tmp_path: Path) -> None:
    text = (
        "dependencies:\n  - a=1.0=py_0\n  - b 1.0 py_0\n  - c=1|2\n  - d=*\n  - e=2\n"
    )
    assert [r.name for r in CondaYamlAdapter().parse(write(tmp_path, text))] == ["e"]


def test_unparsable_item_warns_with_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from depkeeper.core.sources.conda_yaml import CondaYamlAdapter

    f = tmp_path / "environment.yml"
    f.write_text("dependencies:\n  - [bad\n  - numpy\n")
    with caplog.at_level("WARNING"):
        reqs = CondaYamlAdapter().parse(f)
    assert [r.name for r in reqs] == ["numpy"]
    assert any(f"{f}:2" in r.getMessage() for r in caplog.records)


def test_conda_stale_text_at_span_is_refused(tmp_path: Path) -> None:
    import pytest
    from depkeeper.core.sources.conda_yaml import CondaYamlAdapter
    from depkeeper.exceptions import DepKeeperError

    f = tmp_path / "environment.yml"
    text = "dependencies:\n  - numpy=1.20\n"
    f.write_text(text)
    a = CondaYamlAdapter()
    (req,) = a.parse(f)
    with pytest.raises(DepKeeperError, match="changed since"):
        a.apply_updates("# hdr line\n" + text, [(req, "1.30")])


def test_pip_item_keeps_marker_spacing(tmp_path: Path) -> None:
    from depkeeper.core.sources.conda_yaml import CondaYamlAdapter

    f = tmp_path / "environment.yml"
    text = 'dependencies:\n  - pip:\n    - flask[async]>=1.0 ; python_version>"3"\n'
    f.write_text(text)
    a = CondaYamlAdapter()
    (req,) = a.parse(f)
    assert a.apply_updates(text, [(req, "2.0")]) == text.replace(">=1.0", ">=2.0")
