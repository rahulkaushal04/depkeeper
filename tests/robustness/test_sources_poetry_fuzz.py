"""Poetry constraint strings never crash the pyproject adapter with anything but ParseError."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import List

import pytest

from depkeeper.core.sources.pyproject_toml import PyprojectTomlAdapter, _release
from depkeeper.exceptions import DepKeeperError, ParseError

A = PyprojectTomlAdapter()

HAND = [
    "^1.²", "~1.²", "^١.٢", "^1.٣.4", ">=1.²", "==1.²", "^", "~", "^^1", "~~1",
    "^1..2", "~1..2", "^.1", "^1.", "", " ", "   ", "*", "||", "^1 || ^2", "^1||^2",
    "^1,", ",", ",,", "^ 1", "~ 1.2", "^1 ,<3", ">=1,<2,", "^1.2.3.4.5", "^0", "^0.0",
    "^0.0.0", "~0", "^999999999999999999999999.1", "^1.x", "^1.*", "~=", "~=1.²",
    "^ 1", "^1 ", "^１.２", "^1\x00", "^1\n", "!=", "==", ">=", "^-1", "^1e5",
    "^1.0rc1", "^1.0.post1", "~1.0a1", "1.²", "١.٢", "1.*", "*.*", "^1.2,^3",
]  # fmt: skip


def _file(tmp: Path, constraint: str) -> Path:
    p = tmp / "pyproject.toml"
    p.write_text(
        '[tool.poetry]\nname = "d"\nversion = "0"\n\n[tool.poetry.dependencies]\n'
        "python = %s\nsix = %s\n" % (json.dumps(constraint), json.dumps(constraint)),
        encoding="utf-8",
    )
    return p


def _exercise(p: Path) -> None:
    try:
        reqs = A.parse(p)
        A.requires_python(p)
    except ParseError:
        return
    try:  # an update the constraint cannot hold is a documented DepKeeperError
        A.apply_updates(
            p.read_text(encoding="utf-8"), [(r, "9.9.9") for r in reqs], path=p
        )
    except DepKeeperError:
        pass


@pytest.mark.parametrize("constraint", HAND)
def test_hand_picked_constraints(constraint: str, tmp_path: Path) -> None:
    _exercise(_file(tmp_path, constraint))


@pytest.mark.parametrize("bad", ["²", "١", "1.²", "１"])
def test_release_rejects_non_ascii_digits(bad: str) -> None:
    assert _release(bad) is None
    assert _release("1.2.3") == [1, 2, 3]


def test_non_ascii_digit_caret_is_skipped_not_crashed(tmp_path: Path) -> None:
    reqs = A.parse(_file(tmp_path, "^1.²"))
    assert [r for r in reqs if r.name == "six" and r.specs] == []


PIECES = ["^", "~", "~=", ">=", "<", "==", "!=", ",", " ", "||", "*", ".", "1", "0",
          "2", "²", "١", "x", "rc1", "-", "+", "!", " "]  # fmt: skip


@pytest.mark.parametrize("seed", range(25))
def test_random_constraint_soup(seed: int, tmp_path: Path) -> None:
    rng = random.Random(seed)
    cases: List[str] = []
    for _ in range(40):
        cases.append("".join(rng.choice(PIECES) for _ in range(rng.randint(0, 9))))
    for c in cases:
        _exercise(_file(tmp_path, c))
