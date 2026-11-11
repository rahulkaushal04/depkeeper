"""``check --format json-v2`` envelope and bare-array backward compatibility."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from depkeeper.models import Package
from tests.test_commands.test_check_output_streams import _isolated_console, _run_check  # noqa: F401
from tests.test_commands.test_update_cli_options import STUB


def _pkg(name: str, cur: str, rec: str, **kw: Any) -> Package:
    return Package(
        name=name,
        current_version=cur,
        latest_version=rec,
        recommended_version=rec,
        **kw,
    )


@pytest.mark.unit
class TestBareArrayStaysDefault:
    def test_json_is_still_a_list(self, tmp_path: Path) -> None:
        r = _run_check(
            tmp_path, ["check", "-f", "json"], packages=[_pkg("a", "1.0.0", "1.0.1")]
        )
        data = json.loads(r.stdout)
        assert isinstance(data, list) and data[0]["name"] == "a"
        assert "links" not in data[0] and "file" not in data[0]

    def test_ignored_flag_is_additive(self, tmp_path: Path) -> None:
        r = _run_check(
            tmp_path,
            ["check", "-f", "json"],
            packages=[_pkg("a", "1", "1", ignored=True)],
        )
        assert json.loads(r.stdout)[0]["ignored"] is True


@pytest.mark.unit
class TestEnvelope:
    def _run(
        self, tmp_path: Path, pkgs: Any, *args: str, contents: str = "a==1.0.0\n"
    ) -> Any:
        r = _run_check(
            tmp_path,
            ["check", "-f", "json-v2", *args],
            packages=pkgs,
            contents=contents,
        )
        return r, json.loads(r.stdout)

    def test_shape(self, tmp_path: Path) -> None:
        released = datetime.now(timezone.utc) - timedelta(days=5)
        r, env = self._run(
            tmp_path, [_pkg("a", "1.0.0", "1.0.1", recommended_released=released)]
        )
        assert set(env) == {
            "schema_version",
            "summary",
            "python",
            "files",
            "packages",
            "errors",
        }
        assert env["schema_version"] == 2
        assert env["summary"]["total"] == 1 and env["summary"]["outdated"] == 1
        assert env["summary"]["by_update_type"] == {"patch": 1}
        (f,) = env["files"]
        assert (
            f["path"].endswith("requirements.txt") and f["format"] == "requirements.txt"
        )
        (p,) = env["packages"]
        assert p["file"] == f["path"] and p["line"] == 1
        assert p["source_format"] == "requirements.txt"
        assert p["age_days"] == 5 and p["held"] is False and p["ignored"] is False
        assert p["update_type"] == "patch" and p["links"] == {}
        assert env["errors"] == []

    def test_held_ignored_calver_and_errors(self, tmp_path: Path) -> None:
        pkgs = [
            _pkg("h", "1.0.0", "1.0.0", held=True),
            _pkg("cal", "2023.1.0", "2024.2.0", versioning="calver"),
            STUB,
        ]
        r, env = self._run(tmp_path, pkgs)
        by = {p["name"]: p for p in env["packages"]}
        assert by["h"]["held"] is True
        assert (
            by["cal"]["update_type"] == "year" and by["cal"]["versioning"] == "calver"
        )
        assert env["summary"]["held"] == 1 and env["summary"]["errors"] == 1
        assert env["errors"][0]["package"] == "ghost"
        assert r.exit_code == 4

    def test_multi_file(self, tmp_path: Path) -> None:
        (tmp_path / "requirements-dev.txt").write_text("b==1.0.0\n")
        r, env = self._run(
            tmp_path,
            [_pkg("a", "1.0.0", "1.0.1"), _pkg("b", "1.0.0", "1.0.1")],
            str(tmp_path),
        )
        assert len(env["files"]) == 2
        assert {Path(p["file"]).name for p in env["packages"]} == {
            "requirements.txt",
            "requirements-dev.txt",
        }

    def test_empty_run_still_emits_envelope(self, tmp_path: Path) -> None:
        r, env = self._run(tmp_path, [_pkg("a", "1", "1")], "--outdated-only")
        assert env["packages"] == [] and env["schema_version"] == 2


@pytest.mark.unit
class TestReleaseLinks:
    def test_data_store_extracts_http_links_only(self) -> None:
        from depkeeper.core.data_store import PyPIDataStore

        info = {
            "version": "1.0",
            "project_urls": {
                "Changelog": "https://x.example/CHANGES",
                "Release Notes": "https://x.example/rel",
                "Source": "javascript:alert(1)",
            },
            "home_page": "https://x.example",
        }
        data = PyPIDataStore(None)._parse_package_data(
            "x", {"info": info, "releases": {}}
        )  # type: ignore[arg-type]
        assert data.release_links() == {
            "changelog": "https://x.example/CHANGES",
            "release_notes": "https://x.example/rel",
            "homepage": "https://x.example",
        }

    def test_links_surface_in_markdown_and_json(self, tmp_path: Path) -> None:
        from unittest import mock

        from depkeeper.commands import _report

        links = {
            "a": {"changelog": "https://x.example/c", "homepage": "https://x.example"}
        }
        with mock.patch.object(_report, "collect_links", lambda *a, **k: links):
            md = _run_check(
                tmp_path,
                ["check", "-f", "markdown"],
                packages=[_pkg("a", "1.0.0", "1.0.1")],
            )
            js = _run_check(
                tmp_path,
                ["check", "-f", "json-v2"],
                packages=[_pkg("a", "1.0.0", "1.0.1")],
            )
            bare = _run_check(
                tmp_path,
                ["check", "-f", "json"],
                packages=[_pkg("a", "1.0.0", "1.0.1")],
            )
        assert "[changelog](https://x.example/c)" in md.stdout
        assert (
            json.loads(js.stdout)["packages"][0]["links"]["changelog"]
            == "https://x.example/c"
        )
        assert json.loads(bare.stdout)[0]["links"]["homepage"] == "https://x.example"


@pytest.mark.unit
def test_conflict_held_package_is_counted_and_flagged() -> None:
    from depkeeper.commands import _report

    held = _pkg("black", "21.12b0", "21.12b0", conflict_held=True)
    env = _report.build_envelope([_report.Row(held)], (None, "running interpreter"))
    assert env["summary"]["conflicts"] == 1
    assert env["packages"][0]["conflict_held"] is True


@pytest.mark.unit
@pytest.mark.parametrize("python", [(None, "x"), ("3.9", "cli")])
def test_markdown_header_has_no_leading_bullet(python: Any) -> None:
    from depkeeper.commands import _report

    out = _report.render_markdown(
        [_report.Row(_pkg("a", "1", "2"))], title="t", python=python
    )
    line = out.splitlines()[2]
    assert line.startswith("**1** of 1") and "target Python" in line


@pytest.mark.unit
@pytest.mark.parametrize(
    "spec,expected",
    [
        (">=3.8.5", "3.8"),
        (">=3.9", "3.9"),
        ("==3.*", None),
        ("3", None),
        ("3.10", "3.10"),
    ],
)
def test_minimum_python_rule(spec: str, expected: Any) -> None:
    from depkeeper.commands._report import minimum_python

    assert minimum_python(spec) == expected
