"""Fuzzy conda specs (``numpy=1.24``) pin a series; updates need a newer series."""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from depkeeper.core.checker import VersionChecker
from depkeeper.core.sources.conda_yaml import CondaYamlAdapter
from depkeeper.models.package import Package
from depkeeper.models.requirement import Requirement
from tests.support.pypi import FakePyPIStore, package_data

VERSIONS = ["1.23.0", "1.24.0", "1.24.5", "1.26.4", "2.0.0"]


def _reqs(tmp_path: Path, deps: str) -> List[Requirement]:
    f = tmp_path / "environment.yml"
    f.write_text(f"dependencies:\n{deps}")
    return CondaYamlAdapter().parse(f)


async def _check(req: Requirement, versions: List[str] = VERSIONS) -> Package:
    store = FakePyPIStore(available={"numpy": package_data("numpy", versions)})
    (pkg,) = await VersionChecker(data_store=store).check_packages([req])
    return pkg


@pytest.mark.asyncio
async def test_same_series_is_not_an_update(tmp_path: Path) -> None:
    (req,) = _reqs(tmp_path, "  - numpy=1.24\n")
    assert req.series == 2
    pkg = await _check(req, ["1.23.0", "1.24.0", "1.24.5"])
    assert pkg.recommended_version == pkg.current_version


@pytest.mark.asyncio
async def test_newer_series_updates_at_same_granularity(tmp_path: Path) -> None:
    (req,) = _reqs(tmp_path, "  - numpy=1.24\n")
    pkg = await _check(req)
    assert pkg.recommended_version == "1.26.4"
    text = (tmp_path / "environment.yml").read_text()
    out = CondaYamlAdapter().apply_updates(text, [(req, "1.26.4")])
    assert "numpy=1.26\n" in out


@pytest.mark.asyncio
async def test_wildcard_series(tmp_path: Path) -> None:
    (req,) = _reqs(tmp_path, "  - numpy=1.26.*\n")
    pkg = await _check(req)
    assert pkg.recommended_version == pkg.current_version


def test_exact_and_build_forms(tmp_path: Path) -> None:
    reqs = _reqs(tmp_path, "  - numpy==1.24.1\n  - pandas=2.0.1=py311_0\n")
    assert [r.name for r in reqs] == ["numpy"]  # build strings are skipped
    assert reqs[0].series is None
