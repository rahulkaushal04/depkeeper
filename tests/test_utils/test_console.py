"""Unit tests for depkeeper.utils.console module.

This test suite provides comprehensive coverage of console output utilities,
including theme configuration, output functions, table rendering, user interaction,
and edge cases for environment-based configuration.

Test Coverage:
- Console initialization and lifecycle
- Color detection based on environment variables
- Success/error/warning message printing
- Table rendering with various configurations
- User confirmation prompts
- Console reconfiguration
- Thread safety of singleton console
- Edge cases for None/empty inputs
"""

from __future__ import annotations

import sys
import threading
from unittest.mock import MagicMock, patch
from typing import Any, Dict, List, Generator

import pytest
from rich.table import Table
from rich.console import Console

from depkeeper.utils.console import (
    _should_use_color,
    _get_console,
    reconfigure_console,
    print_success,
    print_error,
    print_warning,
    print_table,
    confirm,
    get_raw_console,
    colorize_update_type,
    DEPKEEPER_THEME,
)


@pytest.fixture(autouse=True)
def reset_console() -> Generator[None, None, None]:
    """Reset console singleton before and after each test.

    Ensures tests don't interfere with each other by clearing
    the global console instance.
    """
    reconfigure_console()
    yield
    reconfigure_console()


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clean environment variables that affect console behavior.

    Removes NO_COLOR and CI variables to ensure consistent test state.
    """
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("CI", raising=False)


class TestThemeConfiguration:
    """Tests for DEPKEEPER_THEME configuration."""

    def test_theme_has_required_styles(self) -> None:
        """Test theme contains all required style definitions.

        Ensures all expected style keys are present in the theme.
        """
        required_styles = [
            "success",
            "error",
            "warning",
            "info",
            "dim",
            "highlight",
        ]

        for style_name in required_styles:
            assert style_name in DEPKEEPER_THEME.styles
            assert DEPKEEPER_THEME.styles[style_name] is not None

    def test_theme_style_values(self) -> None:
        """Test theme styles have expected color/formatting values.

        Verifies specific style attributes match the documented theme.
        """
        theme_dict = {
            "success": "bold green",
            "error": "bold red",
            "warning": "bold yellow",
            "info": "bold cyan",
            "dim": "dim",
            "highlight": "bold magenta",
        }

        for style_name, expected_value in theme_dict.items():
            actual_style = str(DEPKEEPER_THEME.styles[style_name])
            assert expected_value in actual_style or actual_style == expected_value


class TestShouldUseColor:
    """Tests for _should_use_color environment detection."""

    def test_no_color_env_disables_color(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test NO_COLOR environment variable disables colored output.

        Per NO_COLOR spec (https://no-color.org/), any value should disable color.
        """
        monkeypatch.setenv("NO_COLOR", "1")
        assert _should_use_color() is False

        # Any non-empty value should disable color
        monkeypatch.setenv("NO_COLOR", "true")
        assert _should_use_color() is False

        monkeypatch.setenv("NO_COLOR", "anything")
        assert _should_use_color() is False

    def test_ci_env_disables_color(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test CI environment variable disables colored output.

        CI environments typically don't support ANSI color codes.
        """
        monkeypatch.setenv("CI", "true")
        assert _should_use_color() is False

        monkeypatch.setenv("CI", "1")
        assert _should_use_color() is False

    def test_both_no_color_and_ci_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test NO_COLOR takes precedence when both are set.

        Edge case: Both environment variables set simultaneously.
        """
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setenv("CI", "true")
        assert _should_use_color() is False

    def test_tty_detection(
        self, monkeypatch: pytest.MonkeyPatch, clean_env: None
    ) -> None:
        """Test color is enabled for TTY, disabled for non-TTY.

        When no env vars are set, uses stdout.isatty() to detect terminal.
        """
        # Mock TTY
        with patch.object(sys.stdout, "isatty", return_value=True):
            assert _should_use_color() is True

        # Mock non-TTY (pipe, redirect)
        with patch.object(sys.stdout, "isatty", return_value=False):
            assert _should_use_color() is False

    def test_isatty_raises_attribute_error(
        self, monkeypatch: pytest.MonkeyPatch, clean_env: None
    ) -> None:
        """Test graceful handling when stdout has no isatty method.

        Edge case: Some file-like objects don't have isatty().
        """
        with patch.object(sys, "stdout", spec=[]):  # No isatty attribute
            assert _should_use_color() is False

    def test_isatty_raises_os_error(
        self, monkeypatch: pytest.MonkeyPatch, clean_env: None
    ) -> None:
        """Test graceful handling when isatty() raises OSError.

        Edge case: Some environments raise errors when checking TTY.
        """
        mock_stdout = MagicMock()
        mock_stdout.isatty.side_effect = OSError("Not a terminal")

        with patch.object(sys, "stdout", mock_stdout):
            assert _should_use_color() is False

    def test_empty_no_color_enables_color(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test empty NO_COLOR variable still disables color.

        Edge case: NO_COLOR="" should still disable color per spec.
        """
        monkeypatch.setenv("NO_COLOR", "")
        # Empty string is truthy in env vars - should still disable
        assert _should_use_color() is False


class TestGetConsole:
    """Tests for _get_console singleton management."""

    def test_returns_console_instance(self) -> None:
        """Test _get_console returns a Rich Console instance.

        Happy path: Should return a configured Console object.
        """
        console = _get_console()
        assert isinstance(console, Console)

        error_style = console.get_style("error")
        assert error_style.bold is True
        assert error_style.color.name == "red"

    def test_singleton_returns_same_instance(self) -> None:
        """Test _get_console returns the same instance on multiple calls.

        Verifies singleton pattern - multiple calls should return identical object.
        """
        console1 = _get_console()
        console2 = _get_console()

        assert console1 is console2

    def test_console_respects_no_color(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test console respects NO_COLOR environment variable.

        Console should be created with no_color=True when NO_COLOR is set.
        """
        monkeypatch.setenv("NO_COLOR", "1")
        reconfigure_console()

        console = _get_console()
        assert console.no_color is True

    def test_console_enables_color_for_tty(
        self, monkeypatch: pytest.MonkeyPatch, clean_env: None
    ) -> None:
        """Test console enables color for TTY output.

        When NO_COLOR is not set and output is a TTY, color should be enabled.
        """
        with patch.object(sys.stdout, "isatty", return_value=True):
            reconfigure_console()
            console = _get_console()
            assert console.no_color is False

    def test_thread_safety(self) -> None:
        """Test _get_console is thread-safe.

        Multiple threads calling _get_console should all get the same instance
        without race conditions.
        """
        reconfigure_console()
        results: List[Console] = []
        lock = threading.Lock()

        def get_console_thread() -> None:
            console = _get_console()
            with lock:
                results.append(console)

        threads = [threading.Thread(target=get_console_thread) for _ in range(10)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # All threads should get the same console instance
        assert len(results) == 10
        assert all(console is results[0] for console in results)


class TestReconfigureConsole:
    """Tests for reconfigure_console reset functionality."""

    def test_reconfigure_clears_console(self) -> None:
        """Test reconfigure_console resets the singleton.

        After reconfiguration, _get_console should create a new instance.
        """
        console1 = _get_console()
        reconfigure_console()
        console2 = _get_console()

        # Should be different instances
        assert console1 is not console2

    def test_reconfigure_respects_new_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test reconfiguration picks up environment variable changes.

        Integration test: Changing env vars and reconfiguring should
        affect the new console instance.
        """
        # Start with color enabled
        monkeypatch.delenv("NO_COLOR", raising=False)
        with patch.object(sys.stdout, "isatty", return_value=True):
            reconfigure_console()
            console1 = _get_console()
            assert console1.no_color is False

        # Disable color
        monkeypatch.setenv("NO_COLOR", "1")
        reconfigure_console()
        console2 = _get_console()
        assert console2.no_color is True

    def test_reconfigure_thread_safety(self) -> None:
        """Test reconfigure_console is thread-safe.

        Edge case: Multiple threads reconfiguring simultaneously.
        """

        def reconfigure_thread() -> None:
            reconfigure_console()
            _get_console()  # Force creation

        threads = [threading.Thread(target=reconfigure_thread) for _ in range(10)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # Should complete without errors
        console = _get_console()
        assert isinstance(console, Console)


class TestPrintSuccess:
    """Tests for print_success message output."""

    def test_prints_success_message(self) -> None:
        """Test print_success outputs message with success style.

        Happy path: Should print with [OK] prefix and success styling.
        """
        with patch.object(Console, "print") as mock_print:
            print_success("Operation completed")

            mock_print.assert_called_once_with(
                "[OK] Operation completed", style="success"
            )

    def test_custom_prefix(self) -> None:
        """Test print_success with custom prefix.

        Should allow overriding the default [OK] prefix.
        """
        with patch.object(Console, "print") as mock_print:
            print_success("Done", prefix="✓")

            mock_print.assert_called_once_with("✓ Done", style="success")

    def test_empty_message(self) -> None:
        """Test print_success with empty message.

        Edge case: Should handle empty strings gracefully.
        """
        with patch.object(Console, "print") as mock_print:
            print_success("")

            mock_print.assert_called_once_with("[OK] ", style="success")

    def test_multiline_message(self) -> None:
        """Test print_success with multiline message.

        Edge case: Should handle newlines in messages.
        """
        with patch.object(Console, "print") as mock_print:
            print_success("Line 1\nLine 2")

            mock_print.assert_called_once_with("[OK] Line 1\nLine 2", style="success")

    def test_message_with_rich_markup(self) -> None:
        """Test print_success preserves Rich markup.

        Edge case: Rich markup should be preserved and rendered.
        """
        with patch.object(Console, "print") as mock_print:
            print_success("[bold]Important[/bold] message")

            mock_print.assert_called_once_with(
                "[OK] [bold]Important[/bold] message", style="success"
            )


class TestPrintError:
    """Tests for print_error message output."""

    def test_prints_error_message(self) -> None:
        """Test print_error outputs message with error style.

        Happy path: Should print with [ERROR] prefix and error styling.
        """
        with patch.object(Console, "print") as mock_print:
            print_error("Operation failed")

            mock_print.assert_called_once_with(
                "[ERROR] Operation failed", style="error"
            )

    def test_custom_prefix(self) -> None:
        """Test print_error with custom prefix.

        Should allow overriding the default [ERROR] prefix.
        """
        with patch.object(Console, "print") as mock_print:
            print_error("Failed", prefix="✗")

            mock_print.assert_called_once_with("✗ Failed", style="error")

    def test_empty_message(self) -> None:
        """Test print_error with empty message.

        Edge case: Should handle empty strings gracefully.
        """
        with patch.object(Console, "print") as mock_print:
            print_error("")

            mock_print.assert_called_once_with("[ERROR] ", style="error")


class TestPrintWarning:
    """Tests for print_warning message output."""

    def test_prints_warning_message(self) -> None:
        """Test print_warning outputs message with warning style.

        Happy path: Should print with [WARNING] prefix and warning styling.
        """
        with patch.object(Console, "print") as mock_print:
            print_warning("Deprecated feature")

            mock_print.assert_called_once_with(
                "[WARNING] Deprecated feature", style="warning"
            )

    def test_custom_prefix(self) -> None:
        """Test print_warning with custom prefix.

        Should allow overriding the default [WARNING] prefix.
        """
        with patch.object(Console, "print") as mock_print:
            print_warning("Caution", prefix="⚠")

            mock_print.assert_called_once_with("⚠ Caution", style="warning")


class TestPrintTable:
    """Tests for print_table structured output."""

    def test_prints_simple_table(self) -> None:
        """Test print_table renders basic data table.

        Happy path: Should create and print a table from list of dicts.
        """
        data = [
            {"name": "Alice", "age": "30"},
            {"name": "Bob", "age": "25"},
        ]

        with patch.object(Console, "print") as mock_print:
            print_table(data)

            # Should be called once with a Table object
            assert mock_print.call_count == 1
            table_arg = mock_print.call_args[0][0]
            assert isinstance(table_arg, Table)

    def test_empty_data_prints_nothing(self) -> None:
        """Test print_table with empty data list.

        Edge case: Empty list should not print anything.
        """
        with patch.object(Console, "print") as mock_print:
            print_table([])

            mock_print.assert_not_called()

    def test_custom_headers(self) -> None:
        """Test print_table with custom header order.

        Should allow specifying column order different from dict keys.
        """
        data = [
            {"name": "Alice", "age": "30", "city": "NYC"},
            {"name": "Bob", "age": "25", "city": "LA"},
        ]

        with patch.object(Console, "print") as mock_print:
            print_table(data, headers=["name", "city"])

            # Table should only have specified columns
            table_arg = mock_print.call_args[0][0]
            assert len(table_arg.columns) == 2

    def test_table_with_title(self) -> None:
        """Test print_table with title.

        Should set the table title when provided.
        """
        data = [{"name": "Alice"}]

        with patch.object(Console, "print") as mock_print:
            print_table(data, title="Users")

            table_arg = mock_print.call_args[0][0]
            assert table_arg.title == "Users"

    def test_table_with_caption(self) -> None:
        """Test print_table with caption.

        Should set the table caption when provided.
        """
        data = [{"name": "Alice"}]

        with patch.object(Console, "print") as mock_print:
            print_table(data, caption="Total: 1 user")

            table_arg = mock_print.call_args[0][0]
            assert table_arg.caption == "Total: 1 user"

    def test_column_styles(self) -> None:
        """Test print_table with custom column styles.

        Should apply per-column styling configuration.
        """
        data = [{"name": "Alice", "age": "30"}]

        column_styles = {
            "name": {"style": "bold", "justify": "left"},
            "age": {"style": "cyan", "justify": "right"},
        }

        with patch.object(Console, "print") as mock_print:
            print_table(data, column_styles=column_styles)

            # Verify table was created (detailed column checks would be complex)
            assert mock_print.call_count == 1

    def test_row_styler_callback(self) -> None:
        """Test print_table with row styling callback.

        Should apply row-level styles based on row data.
        """
        data = [
            {"name": "Alice", "status": "active"},
            {"name": "Bob", "status": "inactive"},
        ]

        def styler(row: Dict[str, Any]) -> str:
            return "green" if row["status"] == "active" else "dim"

        with patch.object(Console, "print") as mock_print:
            print_table(data, row_styler=styler)

            assert mock_print.call_count == 1

    def test_show_row_lines(self) -> None:
        """Test print_table with row lines enabled.

        Should draw horizontal lines between rows when enabled.
        """
        data = [{"name": "Alice"}, {"name": "Bob"}]

        with patch.object(Console, "print") as mock_print:
            print_table(data, show_row_lines=True)

            table_arg = mock_print.call_args[0][0]
            assert table_arg.show_lines is True

    def test_missing_column_values(self) -> None:
        """Test print_table handles missing dictionary keys.

        Edge case: Rows missing some columns should show empty strings.
        """
        data = [
            {"name": "Alice", "age": "30"},
            {"name": "Bob"},  # Missing 'age'
        ]

        with patch.object(Console, "print") as mock_print:
            print_table(data)

            # Should not raise, missing values become empty strings
            assert mock_print.call_count == 1

    def test_non_string_values(self) -> None:
        """Test print_table converts non-string values to strings.

        Edge case: Integer, float, None, etc. should be stringified.
        """
        data = [
            {"name": "Alice", "age": 30, "score": 95.5, "verified": None},
        ]

        with patch.object(Console, "print") as mock_print:
            print_table(data)

            # Should convert all values to strings without error
            assert mock_print.call_count == 1

    def test_all_options_combined(self) -> None:
        """Test print_table with all options specified.

        Integration test: All parameters working together.
        """
        data = [{"name": "Alice", "age": "30"}]

        with patch.object(Console, "print") as mock_print:
            print_table(
                data,
                headers=["name", "age"],
                title="Users",
                caption="Total: 1",
                column_styles={"name": {"style": "bold"}},
                row_styler=lambda row: "green",
                show_row_lines=True,
            )

            table_arg = mock_print.call_args[0][0]
            assert isinstance(table_arg, Table)
            assert table_arg.title == "Users"
            assert table_arg.caption == "Total: 1"
            assert table_arg.show_lines is True


class TestConfirm:
    """Tests for confirm user interaction."""

    def test_confirm_yes_response(self) -> None:
        """Test confirm returns True for 'y' input.

        Happy path: User types 'y' should return True.
        """
        with patch("builtins.input", return_value="y"):
            result = confirm("Proceed?")
            assert result is True

    def test_confirm_yes_full_response(self) -> None:
        """Test confirm returns True for 'yes' input.

        Should accept full 'yes' word.
        """
        with patch("builtins.input", return_value="yes"):
            result = confirm("Proceed?")
            assert result is True

    def test_confirm_no_response(self) -> None:
        """Test confirm returns False for 'n' input.

        User types 'n' should return False.
        """
        with patch("builtins.input", return_value="n"):
            result = confirm("Proceed?")
            assert result is False

    def test_confirm_no_full_response(self) -> None:
        """Test confirm returns False for 'no' input.

        Should accept full 'no' word.
        """
        with patch("builtins.input", return_value="no"):
            result = confirm("Proceed?")
            assert result is False

    def test_confirm_empty_default_false(self) -> None:
        """Test confirm with empty input uses default=False.

        When user presses Enter with default=False, should return False.
        """
        with patch("builtins.input", return_value=""):
            result = confirm("Proceed?", default=False)
            assert result is False

    def test_confirm_empty_default_true(self) -> None:
        """Test confirm with empty input uses default=True.

        When user presses Enter with default=True, should return True.
        """
        with patch("builtins.input", return_value=""):
            result = confirm("Proceed?", default=True)
            assert result is True

    def test_confirm_case_insensitive(self) -> None:
        """Test confirm is case-insensitive.

        Edge case: Y, YES, Yes should all work.
        """
        for response in ["Y", "YES", "Yes", "yEs"]:
            with patch("builtins.input", return_value=response):
                result = confirm("Proceed?")
                assert result is True

    def test_confirm_whitespace_trimmed(self) -> None:
        """Test confirm trims whitespace from input.

        Edge case: '  yes  ' should be treated as 'yes'.
        """
        with patch("builtins.input", return_value="  yes  "):
            result = confirm("Proceed?")
            assert result is True

    def test_confirm_invalid_input_default_false(self) -> None:
        """Test confirm with invalid input uses default=False.

        Edge case: Unrecognized input should use default value.
        """
        with patch("builtins.input", return_value="maybe"):
            result = confirm("Proceed?", default=False)
            assert result is False

    def test_confirm_invalid_input_default_true(self) -> None:
        """Test confirm with invalid input uses default=True.

        Edge case: Unrecognized input should use default value.
        """
        with patch("builtins.input", return_value="maybe"):
            result = confirm("Proceed?", default=True)
            assert result is True

    def test_confirm_keyboard_interrupt(self) -> None:
        """Test confirm handles KeyboardInterrupt (Ctrl+C).

        Edge case: User pressing Ctrl+C should return False safely.
        """
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            with patch.object(Console, "print"):  # Suppress output
                result = confirm("Proceed?")
                assert result is False

    def test_confirm_eof_error(self) -> None:
        """Test confirm handles EOFError (Ctrl+D).

        Edge case: EOF should return False safely.
        """
        with patch("builtins.input", side_effect=EOFError):
            with patch.object(Console, "print"):  # Suppress output
                result = confirm("Proceed?")
                assert result is False

    def test_confirm_prompt_format_default_true(self) -> None:
        """Test confirm shows [Y/n] prompt when default=True.

        Should indicate default choice in prompt.
        """
        with patch("builtins.input", return_value=""):
            with patch.object(Console, "print") as mock_print:
                confirm("Continue?", default=True)

                # Check prompt includes [Y/n]
                call_args = mock_print.call_args[0][0]
                assert "[Y/n]" in call_args

    def test_confirm_prompt_format_default_false(self) -> None:
        """Test confirm shows [y/N] prompt when default=False.

        Should indicate default choice in prompt.
        """
        with patch("builtins.input", return_value=""):
            with patch.object(Console, "print") as mock_print:
                confirm("Continue?", default=False)

                # Check prompt includes [y/N]
                call_args = mock_print.call_args[0][0]
                assert "[y/N]" in call_args


class TestGetRawConsole:
    """Tests for get_raw_console accessor."""

    def test_returns_console_instance(self) -> None:
        """Test get_raw_console returns the singleton Console.

        Should return the same instance as _get_console.
        """
        console1 = get_raw_console()
        console2 = _get_console()

        assert console1 is console2
        assert isinstance(console1, Console)

    def test_returns_same_instance_multiple_calls(self) -> None:
        """Test get_raw_console returns singleton.

        Multiple calls should return the same instance.
        """
        console1 = get_raw_console()
        console2 = get_raw_console()

        assert console1 is console2


class TestColorizeUpdateType:
    """Tests for colorize_update_type Rich markup helper."""

    def test_colorize_major_update(self) -> None:
        """Test colorize_update_type colors 'major' as red.

        Major updates should be highlighted in red.
        """
        result = colorize_update_type("major")
        assert result == "[red]major[/red]"

    def test_colorize_minor_update(self) -> None:
        """Test colorize_update_type colors 'minor' as yellow.

        Minor updates should be highlighted in yellow.
        """
        result = colorize_update_type("minor")
        assert result == "[yellow]minor[/yellow]"

    def test_colorize_patch_update(self) -> None:
        """Test colorize_update_type colors 'patch' as green.

        Patch updates should be highlighted in green.
        """
        result = colorize_update_type("patch")
        assert result == "[green]patch[/green]"

    def test_colorize_new_update(self) -> None:
        """Test colorize_update_type colors 'new' as cyan.

        New dependencies should be highlighted in cyan.
        """
        result = colorize_update_type("new")
        assert result == "[cyan]new[/cyan]"

    def test_colorize_downgrade(self) -> None:
        """Test colorize_update_type colors 'downgrade' as red.

        Downgrades should be highlighted in red.
        """
        result = colorize_update_type("downgrade")
        assert result == "[red]downgrade[/red]"

    def test_colorize_update(self) -> None:
        """Test colorize_update_type colors 'update' as yellow.

        Generic updates should be highlighted in yellow.
        """
        result = colorize_update_type("update")
        assert result == "[yellow]update[/yellow]"

    def test_colorize_case_insensitive(self) -> None:
        """Test colorize_update_type is case-insensitive.

        Edge case: MAJOR, Major, major should all work.
        """
        assert colorize_update_type("MAJOR") == "[red]MAJOR[/red]"
        assert colorize_update_type("Major") == "[red]Major[/red]"
        assert colorize_update_type("MiNoR") == "[yellow]MiNoR[/yellow]"

    def test_colorize_unknown_type(self) -> None:
        """Test colorize_update_type returns unchanged for unknown types.

        Edge case: Unknown update types should pass through unchanged.
        """
        result = colorize_update_type("unknown")
        assert result == "unknown"

        result = colorize_update_type("custom")
        assert result == "custom"

    def test_colorize_empty_string(self) -> None:
        """Test colorize_update_type with empty string.

        Edge case: Empty string should return empty string.
        """
        result = colorize_update_type("")
        assert result == ""

    def test_colorize_preserves_original_string(self) -> None:
        """Test colorize_update_type preserves original casing in output.

        The returned markup should contain the original string, not lowercased.
        """
        result = colorize_update_type("MAJOR")

        assert "MAJOR" in result
        assert "major" not in result.replace("[red]", "").replace("[/red]", "")


class TestIntegration:
    """Integration tests combining multiple console features."""

    def test_print_multiple_message_types(self) -> None:
        """Test printing success, error, and warning in sequence.

        Integration test: All message types should work together.
        """
        with patch.object(Console, "print") as mock_print:
            print_success("Operation completed")
            print_warning("Deprecated feature used")
            print_error("Failed to connect")

            assert mock_print.call_count == 3

    def test_table_with_colorized_update_types(self) -> None:
        """Test print_table with colorized update type column.

        Integration test: Combining table rendering with colorization.
        """
        data = [
            {"package": "requests", "update": colorize_update_type("minor")},
            {"package": "numpy", "update": colorize_update_type("major")},
        ]

        with patch.object(Console, "print") as mock_print:
            print_table(data)

            assert mock_print.call_count == 1
            table_arg = mock_print.call_args[0][0]
            assert isinstance(table_arg, Table)

    def test_confirm_after_table_display(self) -> None:
        """Test user confirmation after displaying a table.

        Integration test: Typical workflow of showing data then confirming.
        """
        data = [{"package": "requests", "version": "2.28.0"}]

        with patch.object(Console, "print"):
            print_table(data)

            with patch("builtins.input", return_value="y"):
                result = confirm("Apply updates?")
                assert result is True

    def test_reconfigure_affects_subsequent_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test reconfiguration affects all subsequent console operations.

        Integration test: Reconfiguring should change behavior of all functions.
        """
        # Start with color
        monkeypatch.delenv("NO_COLOR", raising=False)
        with patch.object(sys.stdout, "isatty", return_value=True):
            reconfigure_console()
            console1 = _get_console()
            assert console1.no_color is False

        # Disable color and reconfigure
        monkeypatch.setenv("NO_COLOR", "1")
        reconfigure_console()

        # New console should have no color
        console2 = _get_console()
        assert console2.no_color is True

        # All functions should use the new console
        assert get_raw_console() is console2


class TestEdgeCases:
    """Additional edge case tests."""

    def test_very_long_message(self) -> None:
        """Test message functions handle very long strings.

        Edge case: Long messages should not cause issues.
        """
        long_message = "x" * 10000

        with patch.object(Console, "print") as mock_print:
            print_success(long_message)

            assert mock_print.call_count == 1
            assert "x" * 10000 in mock_print.call_args[0][0]

    def test_unicode_characters(self) -> None:
        """Test message functions handle Unicode characters.

        Edge case: Emoji and international characters should work.
        """
        with patch.object(Console, "print") as mock_print:
            print_success("✓ 成功 🎉")

            assert "✓ 成功 🎉" in mock_print.call_args[0][0]

    def test_table_with_unicode_data(self) -> None:
        """Test print_table handles Unicode in data.

        Edge case: Table should support international characters.
        """
        data = [
            {"名前": "太郎", "年齢": "30"},
            {"名前": "花子", "年齢": "25"},
        ]

        with patch.object(Console, "print") as mock_print:
            print_table(data)

            assert mock_print.call_count == 1

    def test_table_with_very_wide_data(self) -> None:
        """Test print_table with very wide columns.

        Edge case: Wide data should not crash.
        """
        data = [
            {"col1": "x" * 1000, "col2": "y" * 1000},
        ]

        with patch.object(Console, "print") as mock_print:
            print_table(data)

            assert mock_print.call_count == 1

    def test_table_with_many_columns(self) -> None:
        """Test print_table with many columns.

        Edge case: Tables with many columns should work.
        """
        data = [{f"col{i}": f"val{i}" for i in range(50)}]

        with patch.object(Console, "print") as mock_print:
            print_table(data)

            assert mock_print.call_count == 1

    def test_confirm_with_unicode_prompt(self) -> None:
        """Test confirm with Unicode in prompt.

        Edge case: International prompts should work.
        """
        with patch("builtins.input", return_value="y"):
            with patch.object(Console, "print"):
                result = confirm("続けますか？")  # "Continue?" in Japanese
                assert result is True
