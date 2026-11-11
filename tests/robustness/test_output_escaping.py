"""Markup, control-sequence and Markdown injection safety of every output path."""

from __future__ import annotations

import ast
import io
import random
import re
from pathlib import Path
from typing import List, Optional, Tuple

import pytest
from rich.console import Console

from depkeeper.commands import update as update_cmd
from depkeeper.commands._report import Row, md, md_code, render_markdown
from depkeeper.commands.check import _display_simple, _display_table
from depkeeper.models import Package, Requirement
from depkeeper.models.conflict import Conflict
from depkeeper.utils import console as console_module
from depkeeper.utils.console import (
    _SafeConsole,
    print_error,
    print_table,
    print_warning,
    safe_text,
    strip_controls,
)

ESC_NOT_SGR = re.compile(r"\x1b(?!\[[0-9;]*m)")
EVIL = "[link=https://evil.example]>=3.8[/link][bold red]HI"
CONTROLS = "\x1b]8;;http://evil\x07x\x1b[2J\r\x08\x00\u202eabc\x9b31m"


@pytest.fixture
def term(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
    """A colour terminal whose raw bytes the test can inspect."""
    buf = io.StringIO()
    console_module.reconfigure_console()
    forced = _SafeConsole(
        file=buf,
        force_terminal=True,
        color_system="truecolor",
        width=200,
        theme=console_module.DEPKEEPER_THEME,
    )
    monkeypatch.setitem(console_module._consoles, False, forced)
    monkeypatch.setitem(console_module._consoles, True, forced)
    yield buf
    console_module.reconfigure_console()


def _assert_inert(raw: str) -> None:
    assert "\x1b]" not in raw, raw
    assert not ESC_NOT_SGR.search(raw), raw
    assert not any(c in raw for c in "\x07\x08\r\x00\u202e"), raw


class TestHelpers:
    def test_strip_controls_keeps_newline_and_tab(self) -> None:
        assert strip_controls("a\tb\nc\x1bd\re\u202ef") == "a\tb\ncdef"

    def test_safe_text_escapes_markup(self) -> None:
        out = safe_text("[red]x[/red]\x1b")
        assert "\x1b" not in out
        assert Console(color_system=None).render_str(out).plain == "[red]x[/red]"


class TestUpdatePlan:
    def _plan(self, source: str, python_req: str) -> None:
        pkg = Package(
            name="[red]p",
            current_version="1.0[b]",
            latest_version="2.0",
            recommended_version="2.0",
            metadata={"recommended_metadata": {"requires_python": python_req}},
        )
        reqs = [
            Requirement(
                name="p", specs=[("==", "1.0")], source_file=source, line_number=1
            ),
            Requirement(
                name="q",
                specs=[("==", "1.0")],
                source_file="/o/other.txt",
                line_number=2,
            ),
        ]
        update_cmd._display_update_plan(
            [(r, pkg, "2.0[/link]") for r in reqs], dry_run=False
        )

    def test_requires_python_cannot_inject_link_or_style(
        self, term: io.StringIO
    ) -> None:
        self._plan("req[red]s.txt", EVIL)
        raw = term.getvalue()
        assert "\x1b]8" not in raw
        plain = re.sub(r"\x1b\[[0-9;]*m", "", raw)
        assert "[link=https://evil.example]" in plain
        assert "req[red]s.txt" in plain

    def test_control_characters_are_removed(self, term: io.StringIO) -> None:
        self._plan("a" + CONTROLS + ".txt", CONTROLS)
        _assert_inert(term.getvalue())


class TestMessages:
    def test_status_lines_strip_controls(self, term: io.StringIO) -> None:
        print_error("bad " + CONTROLS + " [red]")
        print_warning(CONTROLS, stderr=True)
        _assert_inert(term.getvalue())
        assert "[red]" in re.sub(r"\x1b\[[0-9;]*m", "", term.getvalue())

    def test_print_table_strips_controls(self, term: io.StringIO) -> None:
        print_table([{"A": CONTROLS}])
        _assert_inert(term.getvalue())


def _hostile_package(rng: random.Random) -> Package:
    junk = "".join(rng.choice("[]/\\ab\x1b\x07\r|`*_<>#-\u202e") for _ in range(12))
    return Package(
        name=junk,
        current_version="1." + junk,
        latest_version="2." + junk,
        recommended_version="2." + junk,
        metadata={"recommended_metadata": {"requires_python": junk}},
        conflicts=[
            Conflict(
                source_package=junk,
                target_package=junk,
                required_spec=junk,
                conflicting_version=junk,
            )
        ],
        cooldown_skipped=junk,
        major_available=junk,
    )


class TestCheckOutputFuzz:
    def test_table_and_simple_never_emit_terminal_controls(
        self, term: io.StringIO
    ) -> None:
        rng = random.Random(1234)
        for _ in range(60):
            pkgs = [_hostile_package(rng) for _ in range(3)]
            term.truncate(0)
            term.seek(0)
            _display_table(pkgs)
            _display_simple(pkgs)
            _assert_inert(term.getvalue())
            assert "\x1b]8" not in term.getvalue()


def _split_row(line: str) -> List[str]:
    """Split a GFM table row on unescaped pipes."""
    cells, cur, i = [], "", 0
    body = line.strip()[1:-1]
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            cur += body[i : i + 2]
            i += 2
            continue
        if ch == "|":
            cells.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    cells.append(cur)
    return cells


class TestMarkdown:
    def _render(self, rng: random.Random, multi: bool) -> str:
        alphabet = "ab|`\\[]()<>*_#-~&\n\r\t\x1b\u202e\u200b:!"
        rows = []
        for i in range(4):
            junk = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 14)))
            pkg = Package(
                name=junk,
                current_version=junk,
                latest_version="2.0",
                recommended_version=junk,
            )
            req = Requirement(
                name=junk,
                specs=[("==", "1")],
                source_file=("f%d" % (i if multi else 0)) + junk,
                line_number=i + 1,
            )
            rows.append(Row(pkg, req, {"homepage": "https://x.example/" + junk}, junk))
        return render_markdown(rows, title="t", python=("3.8", "src"), change_rows=rows)

    @pytest.mark.parametrize("multi", [False, True])
    def test_every_table_row_keeps_its_column_count(self, multi: bool) -> None:
        rng = random.Random(99)
        for _ in range(150):
            text = self._render(rng, multi)
            assert not any(c in text for c in "\r\x1b\u202e\u200b")
            table_lines = [ln for ln in text.split("\n") if ln.startswith("| ")]
            assert table_lines
            width = len(_split_row(table_lines[0]))
            assert width == (6 if "| Source |" in table_lines[0] else 5)
            for ln in table_lines:
                assert len(_split_row(ln)) == width, ln

    def test_no_live_markup_survives(self) -> None:
        text = self._one("<img src=x onerror=1>[a](http://e)`code`*b*")
        assert not re.search(
            r"(?<!\\)[<`\[]a?(?!PyPI)", text.split("| `p` |")[1].split("[PyPI]")[0]
        )
        assert "\\<img" in text and "\\[a\\]" in text

    @staticmethod
    def _one(junk: str) -> str:
        pkg = Package(name="p", current_version=junk, recommended_version="2")
        return render_markdown(
            [Row(pkg, None, {}, "2")],
            title="t",
            python=(None, ""),
            change_rows=[Row(pkg, None, {}, "2")],
        )

    def test_code_span_fence_outgrows_backticks(self) -> None:
        assert md_code("a`b") == "``a`b``"
        assert md_code("`a``") == "``` `a`` ```"
        assert md("a`b|c") == "a\\`b&#124;c"

    def test_pypi_link_name_is_percent_encoded(self) -> None:
        pkg = Package(name="x)\u202e[", recommended_version="2")
        text = render_markdown(
            [Row(pkg, None, {}, "2")],
            title="t",
            python=(None, ""),
            change_rows=[Row(pkg, None, {}, "2")],
        )
        assert "(https://pypi.org/project/x%29%E2%80%AE%5B/)" in text


# --- static guard: no raw dynamic value reaches a Rich markup string --------

_SAFE_CALLS = {"safe_text", "len", "md", "md_code", "age_short", "int", "str_len"}
# Locals that hold already-escaped or fixed text (checked by hand).
_SAFE_NAMES = {
    "dash",
    "status",
    "update_type",
    "colored_type",
    "recommended_display",
    "conflicts_display",
    "python_support",
    "python_req",
    "source",
    "fmt",
    "marker",
    "status_label",
    "title",
    "convergence_status",
}
_SAFE_ATTRS = {"total_packages", "packages_with_conflicts", "iterations_used", "value"}
_TABLE_FUNCS = {
    "_display_update_plan",
    "_create_table_row",
    "_base_table_row",
    "build",
    "_python_cell",
    "_display_table",
}
_COMMANDS = sorted(Path(update_cmd.__file__).parent.glob("*.py"))


def _call_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name):
            return f.id
        if isinstance(f, ast.Attribute):
            return f.attr
    return None


def _is_safe(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.JoinedStr):
        return all(_is_safe(v) for v in node.values)
    if isinstance(node, ast.FormattedValue):
        return _is_safe(node.value)
    if isinstance(node, ast.Attribute):
        return node.attr in _SAFE_ATTRS
    if isinstance(node, ast.Name):
        return node.id in _SAFE_NAMES
    if isinstance(node, ast.Dict):
        return all(v is not None and _is_safe(v) for v in node.values)
    if isinstance(node, ast.IfExp):
        return _is_safe(node.body) and _is_safe(node.orelse)
    if isinstance(node, ast.BinOp):
        return _is_safe(node.left) and _is_safe(node.right)
    if isinstance(node, ast.Call):
        name = _call_name(node)
        if name in _SAFE_CALLS:
            return True
        f = node.func
        if (
            isinstance(f, ast.Attribute)
            and f.attr in ("lower", "upper")
            and _is_safe(f.value)
        ):
            return True
        if name == "join" and node.args and isinstance(node.args[0], ast.GeneratorExp):
            return _is_safe(node.args[0].elt)
        return False
    return False


def _unsafe_sites(path: Path) -> List[Tuple[str, int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad: List[Tuple[str, int, str]] = []

    def visit(node: ast.AST, func: str) -> None:
        for child in ast.iter_child_nodes(node):
            fn = child.name if isinstance(child, ast.FunctionDef) else func
            if isinstance(child, ast.Dict) and func in _TABLE_FUNCS:
                for v in child.values:
                    if not _is_safe(v):
                        bad.append((fn, v.lineno, ast.dump(v)[:60]))
            if isinstance(child, ast.Call) and _call_name(child) == "print":
                f = child.func
                owner = f.value if isinstance(f, ast.Attribute) else None
                markup_off = any(
                    k.arg == "markup"
                    and isinstance(k.value, ast.Constant)
                    and k.value.value is False
                    for k in child.keywords
                )
                if isinstance(owner, ast.Name) and owner.id == "console":
                    if not markup_off:
                        for a in child.args:
                            if isinstance(a, ast.JoinedStr) and not _is_safe(a):
                                bad.append((fn, a.lineno, "console.print"))
            if (
                isinstance(child, (ast.Assign, ast.AugAssign))
                and func in _TABLE_FUNCS
                and not _is_safe(child.value)
            ):
                targets = (
                    child.targets if isinstance(child, ast.Assign) else [child.target]
                )
                if any(isinstance(t, ast.Subscript) for t in targets):
                    bad.append((fn, child.lineno, "row cell"))
            visit(child, fn)

    visit(tree, "")
    return bad


@pytest.mark.parametrize("path", _COMMANDS, ids=lambda p: p.name)
def test_commands_never_interpolate_unescaped_values_into_markup(path: Path) -> None:
    assert _unsafe_sites(path) == []


def test_guard_detects_an_unescaped_cell(tmp_path: Path) -> None:
    src = tmp_path / "bad.py"
    src.write_text(
        "def _base_table_row(pkg):\n    return {'Package': pkg.name}\n"
        "def f(console, x):\n    console.print(f'[b]{x}[/b]')\n"
    )
    assert len(_unsafe_sites(src)) == 2


class TestLogRecordsAreSanitised:
    """Log text carrying terminal control sequences is cleaned on output."""

    @pytest.mark.parametrize("use_color", [True, False])
    def test_controls_do_not_reach_the_stream(self, use_color: bool) -> None:
        import logging

        from depkeeper.utils.logger import ColoredFormatter

        formatter = ColoredFormatter("%(levelname)s %(message)s", use_color=use_color)
        record = logging.LogRecord(
            "depkeeper",
            logging.WARNING,
            __file__,
            1,
            "bad \x1b]8;;http://evil\x07link\r%s",
            ("arg\x1b[2J",),
            None,
        )
        text = formatter.format(record)
        assert "\r" not in text and "\x07" not in text and "\x1b[2J" not in text
        assert "\x1b]8" not in text
        assert record.msg == "bad \x1b]8;;http://evil\x07link\r%s"
        assert record.args == ("arg\x1b[2J",)


class TestStripControlsByCategory:
    """``strip_controls`` removes by Unicode category, not hand-written ranges."""

    @pytest.mark.parametrize(
        "char",
        [
            "\x00",
            "\x07",
            "\x08",
            "\x0b",
            "\x0c",
            "\r",
            "\x1b",
            "\x7f",
            "\x85",
            "\x9b",
            "\u200b",
            "\u200d",
            "\u200f",
            "\u2028",
            "\u2029",
            "\u202e",
            "\u2066",
            "\u2069",
            "\ufeff",
            "\U000e0041",
            "\U000e007f",
        ],
    )
    def test_removed(self, char: str) -> None:
        assert strip_controls(f"a{char}b") == "ab"

    @pytest.mark.parametrize(
        "text", ["é", "日本語", "🔒", "Ωmega", "a\tb\nc", "name_with-dots.1", "ａｂ"]
    )
    def test_kept(self, text: str) -> None:
        assert strip_controls(text) == text

    def test_non_string_values_are_stringified(self) -> None:
        assert strip_controls(12) == "12"
        assert strip_controls(None) == "None"
