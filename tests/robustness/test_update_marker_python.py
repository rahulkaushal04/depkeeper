"""A requirement whose own Python marker is false for the target Python is left alone."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from depkeeper.core.dependency_analyzer import DependencyAnalyzer
from depkeeper.models import Package
from tests.robustness.test_update_check_agreement import invoke
from tests.support.pypi import FakePyPIStore, package_data

VERSIONS = ["2.25.0", "2.25.1", "2.34.2"]
LINE = 'requests==2.25.0 ; python_version<"3.9"'


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)


def _store() -> FakePyPIStore:
    return FakePyPIStore(
        {
            "requests": package_data(
                "requests", VERSIONS, requires_python={"2.34.2": ">=3.10"}
            )
        }
    )


def _file(tmp_path: Path, line: str) -> Path:
    f = tmp_path / "requirements.txt"
    f.write_text(line + "\n")
    return f


def test_false_marker_is_not_updated(tmp_path: Path) -> None:
    f = _file(tmp_path, LINE)
    r = invoke(_store(), "update", "-y", "--python-version", "3.12", str(f))
    assert r.exit_code == 0, r.stdout + r.stderr
    assert f.read_text() == LINE + "\n"
    assert "up to date" in r.stdout + r.stderr


def test_true_marker_keeps_python_compatibility_filter(tmp_path: Path) -> None:
    f = _file(tmp_path, LINE)
    r = invoke(_store(), "update", "-y", "--python-version", "3.8", str(f))
    assert r.exit_code == 0, r.stdout + r.stderr
    assert f.read_text() == 'requests==2.25.1 ; python_version<"3.9"\n'


@pytest.mark.parametrize(
    "line",
    [
        'requests==2.25.0 ; sys_platform == "win32"',
        'requests==2.25.0 ; extra == "x"',
        'requests==2.25.0 ; python_version<"3.9" and sys_platform == "win32"',
        "requests==2.25.0",
    ],
)
def test_other_markers_behave_as_before(tmp_path: Path, line: str) -> None:
    f = _file(tmp_path, line)
    r = invoke(_store(), "update", "-y", "--python-version", "3.12", str(f))
    assert r.exit_code == 0, r.stdout + r.stderr
    assert f.read_text().startswith("requests==2.34.2"), f.read_text()


def test_full_version_marker(tmp_path: Path) -> None:
    f = _file(tmp_path, 'requests==2.25.0 ; python_full_version < "3.10"')
    invoke(_store(), "update", "-y", "--python-version", "3.12", str(f))
    assert f.read_text().startswith("requests==2.25.0 ;")


def test_check_reports_status_in_every_format(tmp_path: Path) -> None:
    f = _file(tmp_path, LINE)
    store = _store()
    args = ["check", "--python-version", "3.12", str(f)]

    ok = invoke(store, *args, "--fail-on", "updates")
    assert ok.exit_code == 0, ok.stdout
    assert "[N/A]" in ok.stdout

    plain = json.loads(invoke(store, *args, "--format", "json").stdout)
    assert plain[0]["status"] == "not-applicable"
    assert plain[0]["target_python"] == "3.12"
    assert "recommended" not in plain[0].get("versions", {})

    v2 = json.loads(invoke(store, *args, "--format", "json-v2").stdout)
    assert v2["packages"][0]["status"] == "not-applicable"
    assert v2["summary"]["outdated"] == 0

    simple = invoke(store, *args, "--format", "simple").stdout
    assert "[NOT-APPLICABLE]" in simple
    assert "not applicable for target Python 3.12" in simple

    md = invoke(store, *args, "--format", "markdown").stdout
    assert "Not applicable for target Python 3.12" in md
    assert "`requests`" in md


def test_marker_true_is_reported_normally(tmp_path: Path) -> None:
    f = _file(tmp_path, LINE)
    out = invoke(
        _store(), "check", "--python-version", "3.8", "--format", "json", str(f)
    )
    entry = json.loads(out.stdout)[0]
    assert entry["status"] == "outdated"
    assert entry["versions"]["recommended"] == "2.25.1"


@pytest.mark.asyncio
async def test_not_applicable_line_does_not_join_conflict_analysis() -> None:
    store = _store()
    skipped = Package(name="requests", current_version="2.25.0", not_applicable="3.12")
    live = Package(name="other", current_version="1.0", recommended_version="1.0")
    await DependencyAnalyzer(data_store=store).resolve_and_annotate_conflicts(
        [skipped, live]
    )
    assert store.prefetch_calls == [["other"]]
