"""Tests for :mod:`depkeeper.utils.console`.

The load-bearing responsibility here is **stream separation** (regression M11).
``depkeeper check --format json`` writes a machine-readable payload to stdout;
every status message, warning and summary must go to stderr, or a downstream
``jq`` receives a document with English prose appended to it. Colour handling
matters for the same reason: a piped stdout and an interactive stderr must be
judged independently.

Assertions run against *rendered output* captured from a real
:class:`rich.console.Console` bound to an in-memory buffer, rather than against
a patched ``Console.print``. Mocking the printer only proves the function was
called; it cannot catch a message routed to the wrong stream, swallowed by Rich
markup, or rendered into the wrong column — which is what the defects in this
area actually were.
"""

from __future__ import annotations

import io
import sys
import threading
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import pytest
from rich.console import Console

from depkeeper.utils import console as console_module
from depkeeper.utils.console import (
    DEPKEEPER_THEME,
    _get_console,
    _should_use_color,
    colorize_update_type,
    confirm,
    get_raw_console,
    print_error,
    print_success,
    print_table,
    print_warning,
    reconfigure_console,
)

#: Rows shaped like a real ``depkeeper check`` table.
CHECK_ROWS: List[Dict[str, Any]] = [
    {
        "Package": "requests",
        "Current": "2.28.2",
        "Latest": "2.32.3",
        "Recommended": "2.32.3",
        "Status": "outdated",
    },
    {
        "Package": "urllib3",
        "Current": "2.2.2",
        "Latest": "2.2.2",
        "Recommended": "1.26.18",
        "Status": "downgrade",
    },
    {
        "Package": "certifi",
        "Current": "2024.7.4",
        "Latest": "2024.7.4",
        "Recommended": "2024.7.4",
        "Status": "latest",
    },
]


@pytest.fixture
def captured_streams(monkeypatch: pytest.MonkeyPatch) -> Iterator[Tuple[io.StringIO, io.StringIO]]:
    """Bind the stdout and stderr consoles to in-memory buffers.

    Both buffers are wide and colourless so assertions can compare plain text
    without fighting Rich's terminal detection or line wrapping.

    Yields:
        The ``(stdout, stderr)`` buffers.
    """
    out, err = io.StringIO(), io.StringIO()
    consoles = {
        False: Console(file=out, theme=DEPKEEPER_THEME, no_color=True, width=200),
        True: Console(file=err, theme=DEPKEEPER_THEME, no_color=True, width=200),
    }
    monkeypatch.setattr(
        console_module, "_get_console", lambda *, stderr=False: consoles[stderr]
    )
    yield out, err


class _FakeStream:
    """Minimal stream stand-in whose ``isatty`` can be scripted."""

    def __init__(self, *, tty: bool = False, error: Optional[Exception] = None) -> None:
        self._tty = tty
        self._error = error

    def isatty(self) -> bool:
        if self._error is not None:
            raise self._error
        return self._tty


# ---------------------------------------------------------------------------
# Colour decisions
# ---------------------------------------------------------------------------


class TestColourDetection:
    """Colour is enabled per stream, and ``NO_COLOR`` always wins."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)

    @pytest.mark.parametrize("stderr", [False, True], ids=["stdout", "stderr"])
    def test_a_tty_enables_colour(
        self, monkeypatch: pytest.MonkeyPatch, stderr: bool
    ) -> None:
        monkeypatch.setattr(
            sys, "stderr" if stderr else "stdout", _FakeStream(tty=True)
        )

        assert _should_use_color(stderr=stderr) is True

    @pytest.mark.parametrize("stderr", [False, True], ids=["stdout", "stderr"])
    def test_a_redirected_stream_disables_colour(
        self, monkeypatch: pytest.MonkeyPatch, stderr: bool
    ) -> None:
        monkeypatch.setattr(
            sys, "stderr" if stderr else "stdout", _FakeStream(tty=False)
        )

        assert _should_use_color(stderr=stderr) is False

    def test_each_stream_is_judged_independently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``depkeeper check -f json | jq`` is the motivating case.

        stdout is a pipe and must stay clean, while stderr is still the user's
        terminal and should keep its colours.
        """
        monkeypatch.setattr(sys, "stdout", _FakeStream(tty=False))
        monkeypatch.setattr(sys, "stderr", _FakeStream(tty=True))

        assert _should_use_color(stderr=False) is False
        assert _should_use_color(stderr=True) is True

    @pytest.mark.parametrize("value", ["1", "true", "anything"])
    def test_no_color_overrides_a_tty(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        """``NO_COLOR`` is an ecosystem convention; any value disables colour."""
        monkeypatch.setattr(sys, "stdout", _FakeStream(tty=True))
        monkeypatch.setenv("NO_COLOR", value)

        assert _should_use_color() is False

    @pytest.mark.parametrize(
        "error",
        [AttributeError("no isatty"), OSError("bad file descriptor")],
        ids=["attribute-error", "os-error"],
    )
    def test_an_unusable_stream_degrades_to_no_colour(
        self, monkeypatch: pytest.MonkeyPatch, error: Exception
    ) -> None:
        """Some CI harnesses replace stdio with objects that cannot answer.

        Failing here would abort the run before a single result is printed.
        """
        monkeypatch.setattr(sys, "stdout", _FakeStream(error=error))

        assert _should_use_color() is False


class TestConsoleCaching:
    """One console per stream, created once."""

    def test_each_stream_gets_its_own_console(self) -> None:
        assert _get_console(stderr=False) is not _get_console(stderr=True)

    @pytest.mark.parametrize("stderr", [False, True], ids=["stdout", "stderr"])
    def test_repeated_lookups_return_the_same_console(self, stderr: bool) -> None:
        assert _get_console(stderr=stderr) is _get_console(stderr=stderr)

    def test_get_raw_console_exposes_the_cached_instance(self) -> None:
        """``check`` reaches for the raw console to bypass Rich markup."""
        assert get_raw_console() is _get_console(stderr=False)
        assert get_raw_console(stderr=True) is _get_console(stderr=True)

    def test_reconfigure_drops_both_consoles(self) -> None:
        """Colour is decided at construction, so a settings change needs a reset."""
        stdout_console = _get_console(stderr=False)
        stderr_console = _get_console(stderr=True)

        reconfigure_console()

        assert _get_console(stderr=False) is not stdout_console
        assert _get_console(stderr=True) is not stderr_console

    def test_reconfigure_picks_up_a_changed_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setattr(sys, "stdout", _FakeStream(tty=True))
        reconfigure_console()
        assert _get_console().no_color is False

        monkeypatch.setenv("NO_COLOR", "1")
        reconfigure_console()

        assert _get_console().no_color is True

    def test_concurrent_first_use_creates_exactly_one_console(self) -> None:
        """The double-checked lock must not hand out two consoles.

        Two consoles would each buffer independently and interleave output
        mid-line. 50 threads racing on a cold cache is enough to expose a
        missing lock reliably.
        """
        reconfigure_console()
        seen: List[Console] = []
        barrier = threading.Barrier(50)

        def grab() -> None:
            barrier.wait()
            seen.append(_get_console())

        threads = [threading.Thread(target=grab) for _ in range(50)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(seen) == 50
        assert len(set(id(console) for console in seen)) == 1


# ---------------------------------------------------------------------------
# Status messages
# ---------------------------------------------------------------------------


class TestStatusMessages:
    """Where each helper writes, and what it writes."""

    @pytest.mark.parametrize(
        ("printer", "default_prefix"),
        [(print_success, "[OK]"), (print_warning, "[WARNING]"), (print_error, "[ERROR]")],
        ids=["success", "warning", "error"],
    )
    def test_default_prefix_is_prepended(
        self,
        captured_streams: Tuple[io.StringIO, io.StringIO],
        printer: Callable[..., None],
        default_prefix: str,
    ) -> None:
        out, err = captured_streams

        printer("2 package(s) have updates available")

        assert f"{default_prefix} 2 package(s) have updates available" in (
            out.getvalue() + err.getvalue()
        )

    def test_errors_default_to_stderr(
        self, captured_streams: Tuple[io.StringIO, io.StringIO]
    ) -> None:
        """Regression M11: an error on stdout corrupts a JSON payload.

        This is the one default that differs from the other helpers, and it is
        the one that mattered.
        """
        out, err = captured_streams

        print_error("requirements.txt not found")

        assert "requirements.txt not found" in err.getvalue()
        assert out.getvalue() == ""

    @pytest.mark.parametrize(
        "printer", [print_success, print_warning], ids=["success", "warning"]
    )
    def test_status_helpers_default_to_stdout(
        self,
        captured_streams: Tuple[io.StringIO, io.StringIO],
        printer: Callable[..., None],
    ) -> None:
        """Unchanged for the human-readable table format, which is the default."""
        out, err = captured_streams

        printer("All dependencies are up to date")

        assert "All dependencies are up to date" in out.getvalue()
        assert err.getvalue() == ""

    @pytest.mark.parametrize(
        "printer", [print_success, print_warning, print_error], ids=["ok", "warn", "err"]
    )
    def test_every_helper_can_be_redirected_to_stderr(
        self,
        captured_streams: Tuple[io.StringIO, io.StringIO],
        printer: Callable[..., None],
    ) -> None:
        """Machine-readable formats redirect all of them at once."""
        out, err = captured_streams

        printer("Resolution Summary", stderr=True)

        assert "Resolution Summary" in err.getvalue()
        assert out.getvalue() == ""

    def test_a_custom_prefix_replaces_the_default(
        self, captured_streams: Tuple[io.StringIO, io.StringIO]
    ) -> None:
        out, _err = captured_streams

        print_success("wrote requirements.txt", prefix="[UPDATED]")

        assert "[UPDATED] wrote requirements.txt" in out.getvalue()

    def test_bracketed_text_in_a_message_is_not_eaten_as_markup(
        self, captured_streams: Tuple[io.StringIO, io.StringIO]
    ) -> None:
        """Regression M4's failure mode: Rich reads ``[outdated]`` as a style
        tag and renders nothing. Status labels are bracketed by convention, so
        this silently blanked the ``--format simple`` output.
        """
        out, _err = captured_streams

        print_warning("requests [outdated] -> 2.32.3")

        assert "requests" in out.getvalue()
        assert "2.32.3" in out.getvalue()


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


class TestPrintTable:
    def test_renders_headers_and_every_row(
        self, captured_streams: Tuple[io.StringIO, io.StringIO]
    ) -> None:
        out, _err = captured_streams

        print_table(CHECK_ROWS)

        rendered = out.getvalue()
        for header in ("Package", "Current", "Latest", "Recommended", "Status"):
            assert header in rendered
        for row in CHECK_ROWS:
            assert row["Package"] in rendered
            assert row["Recommended"] in rendered

    def test_empty_data_prints_nothing(
        self, captured_streams: Tuple[io.StringIO, io.StringIO]
    ) -> None:
        """An empty requirements file must not emit a headerless empty frame."""
        out, err = captured_streams

        print_table([])

        assert out.getvalue() == ""
        assert err.getvalue() == ""

    def test_explicit_headers_select_and_order_the_columns(
        self, captured_streams: Tuple[io.StringIO, io.StringIO]
    ) -> None:
        """Callers project a subset; unlisted keys must not leak into the table."""
        out, _err = captured_streams

        print_table(CHECK_ROWS, headers=["Package", "Status"])

        rendered = out.getvalue()
        assert "Package" in rendered and "Status" in rendered
        assert "Recommended" not in rendered
        assert rendered.index("Package") < rendered.index("Status")

    def test_missing_keys_render_as_empty_cells(
        self, captured_streams: Tuple[io.StringIO, io.StringIO]
    ) -> None:
        """An unavailable package has no ``Latest``; the row must still render."""
        out, _err = captured_streams

        print_table(
            [
                {"Package": "requests", "Latest": "2.32.3"},
                {"Package": "internal-sdk"},
            ],
            headers=["Package", "Latest"],
        )

        rendered = out.getvalue()
        assert "internal-sdk" in rendered
        assert "None" not in rendered

    def test_non_string_values_are_stringified(
        self, captured_streams: Tuple[io.StringIO, io.StringIO]
    ) -> None:
        """Counts and flags arrive as ints and bools straight from the models."""
        out, _err = captured_streams

        print_table([{"Package": "requests", "Conflicts": 3, "Pinned": True}])

        rendered = out.getvalue()
        assert "3" in rendered
        assert "True" in rendered

    def test_title_and_caption_are_rendered(
        self, captured_streams: Tuple[io.StringIO, io.StringIO]
    ) -> None:
        out, _err = captured_streams

        print_table(CHECK_ROWS, title="Dependency Report", caption="3 packages")

        assert "Dependency Report" in out.getvalue()
        assert "3 packages" in out.getvalue()

    def test_row_styler_is_consulted_for_every_row(
        self, captured_streams: Tuple[io.StringIO, io.StringIO]
    ) -> None:
        """The styler highlights rows needing action; skipping any row would
        hide a downgrade in a long report.
        """
        styled: List[str] = []

        def styler(row: Dict[str, Any]) -> Optional[str]:
            styled.append(row["Package"])
            return "warning" if row["Status"] == "downgrade" else None

        print_table(CHECK_ROWS, row_styler=styler)

        assert styled == ["requests", "urllib3", "certifi"]

    def test_table_can_be_routed_to_stderr(
        self, captured_streams: Tuple[io.StringIO, io.StringIO]
    ) -> None:
        out, err = captured_streams

        print_table(CHECK_ROWS, stderr=True)

        assert "requests" in err.getvalue()
        assert out.getvalue() == ""


# ---------------------------------------------------------------------------
# Confirmation prompt
# ---------------------------------------------------------------------------


class TestConfirm:
    """``update`` writes to a user's files only after this returns True."""

    @pytest.mark.parametrize(
        ("response", "expected"),
        [
            ("y", True),
            ("Y", True),
            ("yes", True),
            ("YES", True),
            (" yes ", True),
            ("n", False),
            ("N", False),
            ("no", False),
            (" NO ", False),
        ],
    )
    def test_recognised_responses(
        self,
        captured_streams: Tuple[io.StringIO, io.StringIO],
        monkeypatch: pytest.MonkeyPatch,
        response: str,
        expected: bool,
    ) -> None:
        monkeypatch.setattr("builtins.input", lambda: response)

        assert confirm("Apply 4 updates?") is expected

    @pytest.mark.parametrize(
        "response", ["", "maybe", "1", "yolo"], ids=["enter", "word", "digit", "typo"]
    )
    @pytest.mark.parametrize("default", [True, False], ids=["default-yes", "default-no"])
    def test_unrecognised_input_falls_back_to_the_default(
        self,
        captured_streams: Tuple[io.StringIO, io.StringIO],
        monkeypatch: pytest.MonkeyPatch,
        response: str,
        default: bool,
    ) -> None:
        """Deliberate design: an ambiguous answer never *escalates* privilege,
        because callers pass ``default=False`` for destructive operations.
        """
        monkeypatch.setattr("builtins.input", lambda: response)

        assert confirm("Apply 4 updates?", default=default) is default

    def test_the_prompt_advertises_a_default_of_yes(
        self,
        captured_streams: Tuple[io.StringIO, io.StringIO],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        out, _err = captured_streams
        monkeypatch.setattr("builtins.input", lambda: "")

        confirm("Apply 4 updates?", default=True)

        assert "[Y/n]" in out.getvalue()

    def test_the_prompt_advertises_a_default_of_no(
        self,
        captured_streams: Tuple[io.StringIO, io.StringIO],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Regression: ``confirm`` renders with ``markup=False``.

        ``[y/N]`` used to be swallowed as a (meaningless) Rich style tag, so
        the user was asked ``Apply 4 updates? :`` with no indication that
        pressing Enter declines. ``[Y/n]`` survived only by accident of
        Rich's tag grammar, which is why the ``default=True`` case above
        always passed.

        Every destructive call site uses ``default=False``, so this is
        exactly the prompt that matters.
        """
        out, _err = captured_streams
        monkeypatch.setattr("builtins.input", lambda: "")

        confirm("Apply 4 updates?", default=False)

        assert "[y/N]" in out.getvalue()

    @pytest.mark.parametrize(
        "interruption", [KeyboardInterrupt, EOFError], ids=["ctrl-c", "eof"]
    )
    def test_an_interrupted_prompt_declines(
        self,
        captured_streams: Tuple[io.StringIO, io.StringIO],
        monkeypatch: pytest.MonkeyPatch,
        interruption: type,
    ) -> None:
        """Ctrl+C and a closed stdin (a non-interactive CI job) must both mean
        "do not touch my files" — never "proceed with the default".
        """

        def _raise() -> str:
            raise interruption()

        monkeypatch.setattr("builtins.input", _raise)

        assert confirm("Apply 4 updates?", default=True) is False

    def test_consecutive_prompts_read_independent_answers(
        self,
        captured_streams: Tuple[io.StringIO, io.StringIO],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        answers = iter(["y", "n", "yes"])
        monkeypatch.setattr("builtins.input", lambda: next(answers))

        assert [confirm("?") for _ in range(3)] == [True, False, True]


# ---------------------------------------------------------------------------
# Update-type colouring
# ---------------------------------------------------------------------------


class TestColorizeUpdateType:
    @pytest.mark.parametrize(
        ("update_type", "colour"),
        [
            ("major", "red"),
            ("minor", "yellow"),
            ("patch", "green"),
            ("new", "cyan"),
            ("downgrade", "red"),
            ("update", "yellow"),
        ],
    )
    def test_known_types_are_wrapped_in_their_colour(
        self, update_type: str, colour: str
    ) -> None:
        """Red for major and downgrade is the only cue that a change needs
        review rather than a rubber stamp.
        """
        assert colorize_update_type(update_type) == (
            f"[{colour}]{update_type}[/{colour}]"
        )

    def test_matching_is_case_insensitive_and_preserves_the_label(self) -> None:
        """The label is echoed verbatim so the table still reads correctly."""
        assert colorize_update_type("MAJOR") == "[red]MAJOR[/red]"

    @pytest.mark.parametrize("update_type", ["", "unknown", "same"])
    def test_unknown_types_pass_through_unstyled(self, update_type: str) -> None:
        """Inventing a colour for an unclassified change would imply a severity
        the caller never asserted.
        """
        assert colorize_update_type(update_type) == update_type
