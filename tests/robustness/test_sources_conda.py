"""Adversarial and property tests for the conda environment.yml source adapter."""

from __future__ import annotations

import random
from pathlib import Path
from typing import List, Optional, Tuple

import pytest

from depkeeper.core.sources.conda_yaml import CondaYamlAdapter
from depkeeper.exceptions import DepKeeperError, ParseError

C = CondaYamlAdapter()
HEAD = "name: x\nchannels:\n  - conda-forge\ndependencies:\n"


def _parse(tmp_path: Path, text: str, raw: Optional[bytes] = None):
    p = tmp_path / "environment.yml"
    p.write_bytes(raw if raw is not None else text.encode())
    return p, C.parse(p)


def _by_name(reqs):
    return {r.name: r for r in reqs}


# ---------------------------------------------------------------- regressions


@pytest.mark.parametrize(
    "name", ["librosa", "libsass", "libclang", "libcst", "libusb1", "Librosa"]
)
def test_pypi_packages_with_lib_prefix_are_checked(tmp_path: Path, name: str) -> None:
    _, reqs = _parse(tmp_path, HEAD + f"  - {name}=0.10\n")
    assert [r.name for r in reqs] == [name]


@pytest.mark.parametrize(
    "name",
    ["libgcc-ng", "libffi", "libstdcxx-ng", "_openmp_mutex", "r-base", "cuda-toolkit"],
)
def test_conda_only_packages_stay_skipped(tmp_path: Path, name: str) -> None:
    _, reqs = _parse(tmp_path, HEAD + f"  - {name}=1.0\n")
    assert reqs == []


def test_unpinned_pip_item_keeps_its_spelling(tmp_path: Path) -> None:
    text = (
        HEAD + "  - pip:\n    - Requests[socks] ; python_version<'3.9'\n    - Flask\n"
    )
    _, reqs = _parse(tmp_path, text)
    new = C.apply_updates(text, [(r, "2.5.0") for r in reqs])
    assert new == text.replace(
        "Requests[socks] ;", "Requests[socks] ==2.5.0 ;"
    ).replace("Flask", "Flask==2.5.0")


def test_pip_direct_references_are_never_rewritten(tmp_path: Path) -> None:
    text = HEAD + (
        "  - pip:\n    - ./local\n    - foo @ https://x/y.whl\n"
        "    - git+https://github.com/a/b.git#egg=b\n    - bar>=1\n"
    )
    _, reqs = _parse(tmp_path, text)
    new = C.apply_updates(text, [(r, "9.0") for r in reqs])
    assert new == text.replace("bar>=1", "bar>=9.0")


# ---------------------------------------------------------------- layout quirks


def test_crlf_bom_and_comments_round_trip(tmp_path: Path) -> None:
    body = (
        "name: x\r\n# c\r\ndependencies:\r\n  - numpy=1.24  # pin\r\n"
        "  - pip:\r\n    - requests>=2.0  # http\r\n"
    )
    _, reqs = _parse(tmp_path, body, raw=b"\xef\xbb\xbf" + body.encode())
    new = C.apply_updates(body, [(r, "3.1.2") for r in reqs])
    assert new == body.replace("=1.24", "=3.1").replace(">=2.0", ">=3.1.2")


def test_sequence_flush_with_key_and_nested_pip_indent(tmp_path: Path) -> None:
    text = "dependencies:\n- numpy=1.24\n- pip:\n  - requests>=2\n- scipy=1.9\n"
    _, reqs = _parse(tmp_path, text)
    assert [(r.name, r.source_format) for r in reqs] == [
        ("numpy", "conda"),
        ("requests", "environment.yml"),
        ("scipy", "conda"),
    ]


@pytest.mark.parametrize(
    "text,fragment",
    [
        ("dependencies: [numpy=1.24]\n", "block-style"),
        ("dependencies:\n  - pip: [a, b]\n", "block-style"),
        ("dependencies:\n\t- numpy\n", "Tabs"),
        ('dependencies:\n  - "numpy=1.24\n', "Unterminated"),
        ("dependencies:\n  - numpy\n  stray: 1\n", "list item"),
    ],
)
def test_unsupported_shapes_fail_loudly(
    tmp_path: Path, text: str, fragment: str
) -> None:
    with pytest.raises(ParseError, match=fragment):
        _parse(tmp_path, text)
    p = tmp_path / "environment.yml"
    assert C.requires_python(p) is None


def test_undecodable_file_is_parse_error(tmp_path: Path) -> None:
    p = tmp_path / "environment.yml"
    p.write_bytes(b"\xff\xfedependencies:\n")
    with pytest.raises(ParseError):
        C.parse(p)
    assert C.requires_python(p) is None


@pytest.mark.parametrize(
    "item",
    [
        "numpy=1.24=py311_0",
        "a=*",
        "a=1|2",
        "c *",
        "a[version='>=1']",
        "&anchor numpy=1.24",
        "*alias",
        "key: value",
    ],
)
def test_skipped_items_do_not_disturb_neighbours(tmp_path: Path, item: str) -> None:
    text = HEAD + f"  - {item}\n  - pandas=2.0\n"
    _, reqs = _parse(tmp_path, text)
    assert [r.name for r in reqs] == ["pandas"]


def test_python_pin_variants(tmp_path: Path) -> None:
    cases = {
        "python=3.10": "==3.10.*",
        "python 3.10.*": "==3.10.*",
        "python>=3.9,<3.12": ">=3.9,<3.12",
        "python==3.10.4": "==3.10.4",
        "conda-forge::python=3.11": "==3.11.*",
        "python": None,
        "python=3.10=h1_0": None,
    }
    for item, want in cases.items():
        p, reqs = _parse(tmp_path, HEAD + f"  - {item}\n  - numpy=1.2\n")
        assert C.requires_python(p) == want, item
        assert [r.name for r in reqs] == ["numpy"]


def test_pypi_name_mapping_and_series(tmp_path: Path) -> None:
    text = HEAD + "  - PyTorch=2.0\n  - matplotlib-base=3.7.*\n  - numpy>=1.2\n"
    _, reqs = _parse(tmp_path, text)
    assert [(r.name, r.series, r.approximate) for r in reqs] == [
        ("torch", 2, True),
        ("matplotlib", 2, True),
        ("numpy", None, True),
    ]
    new = C.apply_updates(text, [(reqs[0], "2.4.1"), (reqs[1], "3.9.2")])
    assert "PyTorch=2.4" in new and "matplotlib-base=3.9.*" in new


def test_pin_mode_and_unpinned(tmp_path: Path) -> None:
    text = HEAD + "  - numpy=1.24\n  - pandas\n  - scipy>=1.0,<3\n"
    _, reqs = _parse(tmp_path, text)
    got = C.apply_updates(text, [(r, "2.1.0") for r in reqs[:2]], pin=True)
    assert "numpy==2.1.0" in got and "pandas=2.1.0" in got


def test_stale_and_mismatched_spans_raise(tmp_path: Path) -> None:
    text = HEAD + "  - numpy=1.24\n  - pip:\n    - requests>=2.0\n"
    _, reqs = _parse(tmp_path, text)
    for stale in (
        text.replace("1.24", "1.25"),
        "# x\n" + text,
        text.replace("requests>=2.0", "requests>=2.1"),
    ):
        with pytest.raises(DepKeeperError):
            C.apply_updates(stale, [(r, "9.0") for r in reqs])


def test_excluding_cap_names_file_and_line(tmp_path: Path) -> None:
    text = HEAD + "  - scipy>=1.0,<2\n"
    p, reqs = _parse(tmp_path, text)
    with pytest.raises(DepKeeperError, match=r"environment\.yml:5"):
        C.apply_updates(text, [(reqs[0], "3.0")], path=p)


def test_same_package_in_conda_and_pip(tmp_path: Path) -> None:
    text = HEAD + "  - numpy=1.24\n  - pip:\n    - numpy>=1.20\n"
    _, reqs = _parse(tmp_path, text)
    assert [r.name for r in reqs] == ["numpy", "numpy"]
    new = C.apply_updates(text, [(r, "1.26.4") for r in reqs])
    assert new == text.replace("=1.24", "=1.26").replace(">=1.20", ">=1.26.4")


def test_huge_environment(tmp_path: Path) -> None:
    n = 3000
    text = HEAD + "".join(f"  - pkg{i}=1.{i}  # c\n" for i in range(n))
    _, reqs = _parse(tmp_path, text)
    assert len(reqs) == n
    new = C.apply_updates(text, [(r, "7.7") for r in reqs])
    assert new.count("=7.7") == n and new.count("# c") == n


# ------------------------------------------------------------ properties

# (spec text, expected-text template, expected version fragment from new)
CONDA_SPECS = [
    ("=1.24", "=%s", lambda v: ".".join(v.split(".")[:2])),
    ("=1", "=%s", lambda v: v.split(".")[0]),
    ("=1.24.*", "=%s.*", lambda v: ".".join(v.split(".")[:2])),
    (" 1.2.*", " %s.*", lambda v: ".".join(v.split(".")[:2])),
    ("==1.24.1", "==%s", lambda v: v),
    (">=1.0", ">=%s", lambda v: v),
    (">=1.0,<99", ">=%s,<99", lambda v: v),
    (">=1.0, <99", ">=%s, <99", lambda v: v),
    ("!=1.1,>=1.0", "!=1.1,>=%s", lambda v: v),
]
PIP_SPECS = ["", ">=1.0", "==1.2.3", "~=1.2", ">=1,<99", " >= 1.0"]
VERSIONS = ["2.5", "3.0.1", "10.2.3", "4"]


@pytest.mark.parametrize("seed", range(80))
def test_random_environments_minimal_idempotent_and_match_yaml(
    tmp_path: Path, seed: int
) -> None:
    yaml = pytest.importorskip("yaml")
    rng = random.Random(seed)
    eol = rng.choice(["\n", "\r\n"])
    ind = " " * rng.choice([2, 4])
    new_v = rng.choice(VERSIONS)
    flush = rng.random() < 0.2
    pre = "" if flush else ind
    out = ["# top" + eol, "name: x" + eol, "channels:" + eol, "  - defaults" + eol]
    out.append("dependencies:" + eol)
    want: List[Tuple[str, str, str]] = []  # (name, old_spec, new_spec)
    n_items = rng.randint(1, 8)
    for i in range(n_items):
        kind = rng.random()
        name = rng.choice(["numpy", "pandas", "scipy", "flask", "rich", "toolz"]) + str(
            i
        )
        if kind < 0.65:
            spec_t, fmt, fn = rng.choice(CONDA_SPECS)
            ch = rng.choice(["", "", "conda-forge::"])
            q = rng.choice(["", "", "'", '"'])
            core = f"{ch}{name}{spec_t}"
            comment = rng.choice(["", "  # note", " # a: b"])
            out.append(f"{pre}- {q}{core}{q}{comment}{eol}")
            want.append((name, spec_t, fmt % fn(new_v)))
        elif kind < 0.8:
            out.append(
                f"{pre}- {rng.choice(['libgcc-ng', 'python=3.10', 'pip', 'mkl=1.0'])}{eol}"
            )
        else:
            out.append(f"{pre}- pip:{eol}")
            for j in range(rng.randint(1, 3)):
                spec = rng.choice(PIP_SPECS)
                out.append(
                    f"{pre}{ind}- pk{i}x{j}{spec}{rng.choice(['', '  # p'])}{eol}"
                )
                want.append((f"pk{i}x{j}", spec, ""))
    text = "".join(out)

    # differential: a real YAML reader sees the same dependency scalars
    data = yaml.safe_load(text)
    flat: List[str] = []
    for d in data["dependencies"]:
        flat.extend(d["pip"] if isinstance(d, dict) else [d])
    p, reqs = _parse(tmp_path, text)
    assert all(r.raw_line in flat for r in reqs)
    assert len(reqs) == len(want)

    new = C.apply_updates(text, [(r, new_v) for r in reqs])
    # the result still parses with the YAML reader and only spec bytes changed
    yaml.safe_load(new)
    pos = 0
    for r in sorted(reqs, key=lambda r: r.span):  # type: ignore[arg-type,return-value]
        s, e = r.span  # type: ignore[misc]
        one = C.apply_updates(text, [(r, new_v)])
        assert one[:s] == text[:s] and one.endswith(text[e:])
        assert s >= pos
        pos = e
    # conda items match the hand-computed rendering
    for r, (name, old, exp) in zip(reqs, want):
        if r.source_format == "conda":
            s, e = r.span  # type: ignore[misc]
            assert text[s:e] == old.strip()
            one = C.apply_updates(text, [(r, new_v)])
            assert one[s : len(one) - (len(text) - e)] == exp.strip()

    # idempotent: apply, re-read, apply again at the same version
    p.write_bytes(new.encode())
    again = C.parse(p)
    assert len(again) == len(reqs)
    assert C.apply_updates(new, [(r, new_v) for r in again]) == new
