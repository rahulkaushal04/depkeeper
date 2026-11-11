"""`--max-update` and per-package `max_update` cap the candidate for every package."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pytest

from tests.robustness.test_update_check_agreement import invoke
from tests.support.pypi import FakePyPIStore, package_data

HISTORIES = {
    "requests": ["2.25.0", "2.25.1", "2.26.0", "2.29.0", "2.34.2", "3.0.0"],
    "calver": ["2023.1.1", "2023.1.2", "2023.2.0", "2024.1.0", "2024.1.1"],
}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)


def _store() -> FakePyPIStore:
    return FakePyPIStore({n: package_data(n, h) for n, h in HISTORIES.items()})


def _update(tmp_path: Path, line: str, *args: str) -> str:
    f = tmp_path / "requirements.txt"
    f.write_text(line + "\n")
    r = invoke(_store(), "update", "-y", *args, str(f))
    assert r.exit_code == 0, r.stdout + r.stderr
    return f.read_text().strip()


@pytest.mark.parametrize(
    "extra,expected",
    [
        (["--max-update", "patch"], "requests==2.25.1"),
        (["--max-update", "minor"], "requests==2.34.2"),
        (["--max-update", "major"], "requests==2.34.2"),
        (["--max-update", "patch", "--allow-major", "requests"], "requests==2.25.1"),
        (["--max-update", "minor", "--allow-major", "requests"], "requests==2.34.2"),
        (["--max-update", "major", "--allow-major", "requests"], "requests==3.0.0"),
        (["--max-update", "patch", "--allow-major", "*"], "requests==2.25.1"),
    ],
)
def test_run_cap_picks_best_in_cap(
    tmp_path: Path, extra: List[str], expected: str
) -> None:
    assert _update(tmp_path, "requests==2.25.0", *extra) == expected


@pytest.mark.parametrize(
    "policy,cli_cap,expected",
    [
        ("patch", None, "requests==2.25.1"),
        ("patch", "minor", "requests==2.25.1"),
        ("minor", "patch", "requests==2.25.1"),
        ("minor", None, "requests==2.34.2"),
    ],
)
def test_policy_and_run_cap_take_the_stricter(
    tmp_path: Path, policy: str, cli_cap: Optional[str], expected: str
) -> None:
    (tmp_path / "depkeeper.toml").write_text(
        f'[depkeeper.packages.requests]\nmax_update = "{policy}"\n'
    )
    extra = ["--max-update", cli_cap] if cli_cap else []
    assert _update(tmp_path, "requests==2.25.0", *extra) == expected


@pytest.mark.parametrize(
    "cap,expected",
    [("patch", "calver==2023.1.2"), ("minor", "calver==2024.1.1")],
)
def test_calver_cap(tmp_path: Path, cap: str, expected: str) -> None:
    assert _update(tmp_path, "calver==2023.1.1", "--max-update", cap) == expected


def test_policy_cap_drives_check_exit_codes(tmp_path: Path) -> None:
    (tmp_path / "depkeeper.toml").write_text(
        '[depkeeper.packages.requests]\nmax_update = "patch"\n'
    )
    f = tmp_path / "requirements.txt"
    f.write_text("requests==2.25.0\n")
    store = _store()
    assert invoke(store, "check", "--fail-on", "minor", str(f)).exit_code == 0
    assert invoke(store, "check", "--fail-on", "updates", str(f)).exit_code == 3
