"""Adversarial tests of ``check`` output formats, markup safety and exit codes."""

from __future__ import annotations

import io
import json
import random
from pathlib import Path
from typing import Any, List

import pytest
from rich.cells import cell_len
from rich.console import Console

from depkeeper.commands import _report
from depkeeper.commands.check import _display_table
from depkeeper.core.dependency_analyzer import (
    PackageResolution,
    ResolutionResult,
    ResolutionStatus,
)
from depkeeper.models import Package
from depkeeper.models.conflict import Conflict
from depkeeper.utils import console as console_module
from tests.test_commands.test_check_output_streams import _run_check

FORMATS = ["table", "simple", "json", "json-v2", "markdown"]
HOSTILE = ["[red]x[/red]", "[/]", "[bold", "a]b[c", "\\[x]", "[link=http://e]z[/link]"]


def _pkg(name: str = "flask", cur: str = "1.0.0", rec: str = "2.0.0") -> Package:
    return Package(
        name=name, current_version=cur, latest_version=rec, recommended_version=rec
    )


def _render_table(pkgs: List[Package], width: int) -> str:
    buf = io.StringIO()
    console_module.reconfigure_console()
    console_module._consoles[False] = Console(file=buf, width=width, no_color=True)
    _display_table(pkgs)
    return buf.getvalue()


def _flat(text: str) -> str:
    return "".join(c for c in text if c not in " \n│┃")


def _no_nan(token: str) -> Any:
    raise AssertionError(f"non-finite JSON constant {token}")


@pytest.fixture(autouse=True)
def _plain(no_color: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)


class TestSimpleFormat:
    def test_long_lines_are_not_wrapped(self, tmp_path: Path) -> None:
        pkg = _pkg("a" * 90)
        r = _run_check(tmp_path, ["check", "-f", "simple"], packages=[pkg])
        lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
        assert len(lines) == 1, r.stdout
        assert lines[0].startswith("[OUTDATED]") and "2.0.0" in lines[0]

    def test_markup_like_names_survive(self, tmp_path: Path) -> None:
        r = _run_check(
            tmp_path, ["check", "-f", "simple"], packages=[_pkg("[red]x[/red]")]
        )
        assert "[red]x[/red]" in r.stdout


class TestTableMarkupSafety:
    @pytest.mark.parametrize("name", HOSTILE)
    def test_name_rendered_literally(self, name: str) -> None:
        assert _flat(name) in _flat(_render_table([_pkg(name)], width=200))

    def test_conflict_text_rendered_literally(self) -> None:
        pkg = _pkg()
        pkg.conflicts = [Conflict("src", "flask", ">=[red]1[/]", "0.1")]
        assert _flat(">=[red]1[/]") in _flat(_render_table([pkg], width=300))

    def test_resolution_summary_escapes_names(self) -> None:
        buf = io.StringIO()
        console_module.reconfigure_console()
        console_module._consoles[True] = Console(file=buf, width=120, no_color=True)
        res = ResolutionResult(
            resolved_versions={
                "x": PackageResolution(
                    name="[red]x[/red]",
                    original="1[",
                    resolved="2",
                    status=ResolutionStatus.DOWNGRADED,
                    conflicts=[],
                )
            },
            total_packages=1,
            packages_with_conflicts=0,
            iterations_used=1,
            converged=True,
        )
        _report.display_resolution_summary(res, stderr=True)
        assert "[red]x[/red]: 1[ → 2" in buf.getvalue()

    @pytest.mark.parametrize("fn", ["print_error", "print_warning", "print_success"])
    @pytest.mark.parametrize("msg", HOSTILE)
    def test_print_helpers_are_literal(
        self, fn: str, msg: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        getattr(console_module, fn)(msg, stderr=False)
        assert msg in capsys.readouterr().out.replace("\n", "")


@pytest.mark.parametrize("width", [40, 60, 80, 120, 200])
def test_table_fits_width_with_wide_glyphs(width: int) -> None:
    pkgs = [
        _pkg("日本語パッケージ", "1", "2"),
        _pkg("x😀y", "1.0", "1.1"),
        Package(name="ghost", current_version=None, latest_version=None),
    ]
    lines = _render_table(pkgs, width=width).splitlines()
    assert lines
    assert max(cell_len(ln) for ln in lines) <= width


class TestMarkdownInjection:
    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "data:text/html,<script>",
            "ftp://example.com/x",
            "https://",
            "",
            "vbscript:x",
        ],
    )
    def test_non_http_links_dropped(self, url: str) -> None:
        row = _report.Row(_pkg(), None, {"changelog": url})
        md = _report.render_markdown([row], title="t", python=(None, "x"))
        assert "changelog" not in md and ":alert" not in md and "<script>" not in md

    @pytest.mark.parametrize(
        "url",
        [
            "https://a.com/x|y",
            "https://a.com/a\nb",
            "https://a.com/a](javascript:1)",
            "https://a.com/<img src=x onerror=1>",
            "https://a.com/`x`",
            "https://a.com/(a)",
            'https://a.com/"q"',
        ],
    )
    def test_http_links_cannot_break_out(self, url: str) -> None:
        row = _report.Row(_pkg(), None, {"changelog": url})
        md = _report.render_markdown([row], title="t", python=(None, "x"))
        line = next(ln for ln in md.splitlines() if ln.startswith("| `flask`"))
        target = line.split("](", 1)[1].split(")", 1)[0]
        assert target.startswith("https://a.com/")
        assert not any(c in target for c in '|\n<>`[]" ')
        assert line.count("|") == 6  # 5 cells, no stray cell separators
        assert line.endswith("(https://pypi.org/project/flask/) |")

    def test_cell_cannot_inject_rows(self) -> None:
        assert "\n" not in _report._cell("a\r\nb|c")
        assert _report._cell("a|b") == "a\\|b"


class TestMachineFormatsStaySeparate:
    @pytest.mark.parametrize("fmt", ["json", "json-v2", "markdown", "simple"])
    def test_payload_clean_when_lookup_fails(self, tmp_path: Path, fmt: str) -> None:
        ghost = Package(name="ghost", current_version="1.0", latest_version=None)
        r = _run_check(
            tmp_path,
            ["-v", "check", "-f", fmt],
            packages=[ghost, _pkg()],
            contents="a==1\nb==1\n",
        )
        assert r.exit_code == 4
        assert "could not be checked" in r.stderr
        if fmt != "markdown":  # the report itself lists lookup failures
            assert "could not be checked" not in r.stdout
        assert "WARNING" not in r.stdout and "[ERROR]" not in r.stdout
        if fmt == "json":
            assert {
                p["name"] for p in json.loads(r.stdout, parse_constant=_no_nan)
            } == {
                "ghost",
                "flask",
            }
        elif fmt == "json-v2":
            doc = json.loads(r.stdout, parse_constant=_no_nan)
            assert list(doc) == [
                "schema_version",
                "summary",
                "python",
                "files",
                "packages",
                "errors",
            ]
            assert doc["summary"]["errors"] == 1 == len(doc["errors"])
        elif fmt == "markdown":
            assert r.stdout.startswith("## Dependency report")

    def test_json_v2_hostile_names_round_trip(self, tmp_path: Path) -> None:
        pkgs = [_pkg(n) for n in HOSTILE + ["日本", "a b", "q\"'\\"]]
        r = _run_check(tmp_path, ["check", "-f", "json-v2"], packages=pkgs)
        doc = json.loads(r.stdout, parse_constant=_no_nan)
        assert [p["name"] for p in doc["packages"]] == [p.name for p in pkgs]
        assert json.loads(json.dumps(doc)) == doc

    @pytest.mark.parametrize("fmt", FORMATS)
    @pytest.mark.parametrize("args,code", [([], 0), (["--fail-on", "updates"], 3)])
    def test_exit_codes_in_every_format(
        self, tmp_path: Path, fmt: str, args: List[str], code: int
    ) -> None:
        r = _run_check(tmp_path, ["check", "-f", fmt, *args], packages=[_pkg()])
        assert r.exit_code == code

    @pytest.mark.parametrize("fmt", ["json", "json-v2", "markdown"])
    def test_outdated_only_everything_current_still_emits_document(
        self, tmp_path: Path, fmt: str
    ) -> None:
        r = _run_check(
            tmp_path,
            ["check", "-f", fmt, "--outdated-only"],
            packages=[_pkg(cur="2.0.0", rec="2.0.0")],
        )
        assert r.exit_code == 0 and r.stdout.strip()
        if fmt != "markdown":
            json.loads(r.stdout)


def test_envelope_fuzz_is_stable_and_serialisable() -> None:
    rng = random.Random(1234)
    alphabet = 'ab-_.[]|`\\ 日😀\n"<>'
    for _ in range(150):
        rows = []
        for _i in range(rng.randint(0, 6)):
            name = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 12)))
            ver = rng.choice(["1.0", "2.0.1", "0.0.1", None])
            rec = rng.choice(["1.0", "2.0.1", "3.0", None])
            pkg = Package(
                name=name,
                current_version=ver,
                latest_version=rng.choice([rec, None]),
                recommended_version=rec,
            )
            rows.append(_report.Row(pkg, None, {"homepage": "https://x.io/a|b"}))
        doc = _report.build_envelope(rows, (None, "running interpreter"))
        text = json.dumps(doc, allow_nan=False)
        assert json.loads(text) == doc
        assert doc["summary"]["total"] == len(rows) == len(doc["packages"])
        md = _report.render_markdown(rows, title="t", python=(None, "x"))
        for line in md.splitlines():
            if line.startswith("| `"):
                assert "\r" not in line
        assert md.endswith("\n") and not md.endswith("\n\n")
