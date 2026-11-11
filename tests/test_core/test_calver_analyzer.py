"""Calver packages resolve across years; semver keeps its major boundary."""

from __future__ import annotations

from typing import List, Tuple

import pytest

from depkeeper.core.dependency_analyzer import DependencyAnalyzer
from depkeeper.models.package import Package
from tests.support.pypi import FakePyPIStore, package_data


def _run(versioning: str) -> Tuple[DependencyAnalyzer, List[Package]]:
    store = FakePyPIStore(
        available={
            "app": package_data("app", ["1.0.0"]),
            "certifi": package_data("certifi", ["2023.7.22", "2024.2.2", "2025.1.31"]),
        },
        dependencies={"app==1.0.0": ["certifi>=2024.2.2"]},
    )
    packages = [
        Package(name="app", current_version="1.0.0", recommended_version="1.0.0"),
        Package(
            name="certifi",
            current_version="2023.7.22",
            recommended_version="2023.7.22",
            versioning=versioning,
        ),
    ]
    return DependencyAnalyzer(data_store=store), packages


@pytest.mark.asyncio
async def test_calver_resolves_across_years() -> None:
    analyzer, packages = _run("calver")
    result = await analyzer.resolve_and_annotate_conflicts(packages)
    assert result.resolved_versions["certifi"].resolved == "2025.1.31"


@pytest.mark.asyncio
async def test_semver_keeps_major_boundary() -> None:
    analyzer, packages = _run("semver")
    result = await analyzer.resolve_and_annotate_conflicts(packages)
    assert result.resolved_versions["certifi"].resolved == "2023.7.22"
