"""Per-package policy: config validation and checker application."""

from pathlib import Path
from typing import Any, Dict

import pytest

from depkeeper.config import DepKeeperConfig, PackagePolicy, load_config
from depkeeper.core.checker import VersionChecker
from depkeeper.exceptions import ConfigError
from tests.support.pypi import FakePyPIStore, package_data


def _cfg(tmp_path: Path, body: str, pyproject: bool = False) -> DepKeeperConfig:
    f = tmp_path / ("pyproject.toml" if pyproject else "depkeeper.toml")
    f.write_text(body)
    return load_config(f)


def test_policy_tables_normalized(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path, '[depkeeper.packages.Flask_Login]\nmax_update="minor"\nhold=true\n'
    )
    assert cfg.packages["flask-login"] == PackagePolicy(max_update="minor", hold=True)


def test_pyproject_tables(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path,
        '[tool.depkeeper.packages.django]\nallow_prerelease=true\nversioning="calver"\n',
        True,
    )
    assert cfg.packages["django"].versioning == "calver"


def test_legacy_flat_keys_still_work(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path,
        '[depkeeper]\nfail_on="minor"\nignore=["a"]\npython_version="3.9"\nmin_age="7d"\n',
    )
    assert (cfg.fail_on, cfg.ignore, cfg.python_version) == ("minor", ["a"], "3.9")
    assert cfg.min_age.days == 7


@pytest.mark.parametrize(
    "body",
    [
        "[depkeeper.packages.a]\nmax_update='huge'",
        "[depkeeper.packages.a]\nhold='yes'",
        "[depkeeper.packages.a]\nbogus=1",
        "[depkeeper.packages.a]\nversioning='x'",
        "[depkeeper.packages.A_b]\nhold=true\n[depkeeper.packages.a-b]\nhold=true",
        "[depkeeper]\npackages=3",
        "[depkeeper]\npython_version='three'",
        "[depkeeper]\nmin_age='soon'",
        "[depkeeper]\nversioning='x'",
    ],
)
def test_invalid(tmp_path: Path, body: str) -> None:
    with pytest.raises(ConfigError):
        _cfg(tmp_path, body)


def _checker(**policies: Dict[str, Any]) -> VersionChecker:
    data = package_data("x", ["1.0.0", "1.0.1", "1.1.0", "1.2.0", "1.3.0b1"])
    return VersionChecker(
        FakePyPIStore({"x": data}),
        policies={k: PackagePolicy(**v) for k, v in policies.items()},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cap,expected", [("patch", "1.0.1"), ("minor", "1.2.0")])
async def test_max_update(cap: str, expected: str) -> None:
    pkg = await _checker(x={"max_update": cap}).get_package_info("x", "1.0.0")
    assert pkg.recommended_version == expected


@pytest.mark.asyncio
async def test_hold_ignore_prerelease() -> None:
    assert (await _checker(x={"hold": True}).get_package_info("x", "1.0.0")).held
    assert (
        await _checker(x={"hold": True}).get_package_info("x", "1.0.0")
    ).recommended_version == "1.0.0"
    ign = await _checker(x={"ignore": True}).get_package_info("x", "1.0.0")
    assert ign.ignored and ign.recommended_version == "1.0.0"
    pre = await _checker(x={"allow_prerelease": True}).get_package_info("x", "1.0.0")
    assert pre.recommended_version == "1.3.0b1"
    assert (
        await _checker().get_package_info("x", "1.0.0")
    ).recommended_version == "1.2.0"


@pytest.mark.asyncio
async def test_from_config(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path,
        '[depkeeper]\npython_version="3.9"\n[depkeeper.packages.x]\nhold=true\n',
    )
    c = VersionChecker.from_config(FakePyPIStore({}), cfg, min_age=None)
    assert c.target_python == "3.9" and "x" in c.policies
