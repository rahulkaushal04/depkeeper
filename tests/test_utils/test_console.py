from __future__ import annotations

import sys
import threading
from unittest.mock import MagicMock, patch
from typing import Any, Dict, Generator, List

import pytest
from rich.table import Table
from rich.console import Console

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


# ==============================================================================
# Fixtures
# ==============================================================================


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

    Removes NO_COLOR variable to ensure consistent test state.
    """
    monkeypatch.delenv("NO_COLOR", raising=False)


@pytest.fixture
def mock_tty(clean_env: None) -> Generator[None, None, None]:
    """Mock stdout as a TTY with isatty() returning True."""
    with patch.object(sys.stdout, "isatty", return_value=True):
        yield


@pytest.fixture
def mock_non_tty(clean_env: None) -> Generator[None, None, None]:
    """Mock stdout as non-TTY with isatty() returning False."""
    with patch.object(sys.stdout, "isatty", return_value=False):
        yield


# ==============================================================================
# Theme Configuration Tests
# ==============================================================================


@pytest.mark.unit
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
            assert style_name in DEPKEEPER_THEME.styles, f"Missing style: {style_name}"
            assert DEPKEEPER_THEME.styles[style_name] is not None

    @pytest.mark.parametrize(
        "style_name,expected_value",
        [
            ("success", "bold green"),
            ("error", "bold red"),
            ("warning", "bold yellow"),
            ("info", "bold cyan"),
            ("dim", "dim"),
            ("highlight", "bold magenta"),
        ],
        ids=["success", "error", "warning", "info", "dim", "highlight"],
    )
    def test_theme_style_values(self, style_name: str, expected_value: str) -> None:
        """Test theme styles have expected color/formatting values.

        Verifies specific style attributes match the documented theme.
        """
        actual_style = str(DEPKEEPER_THEME.styles[style_name])
        # The string representation may include "Style(...)" wrapper
        assert expected_value in actual_style or actual_style == expected_value


# ==============================================================================
# Color Detection Tests
# ==============================================================================


@pytest.mark.unit
class TestShouldUseColor:
    """Tests for _should_use_color environment detection."""

    @pytest.mark.parametrize(
        "no_color_value",
        ["1", "true", "TRUE", "anything", "yes", ""],
        ids=[
            "one",
            "true-lower",
            "true-upper",
            "arbitrary-value",
            "yes",
            "empty-string",
        ],
    )
    def test_no_color_env_disables_color(
        self, monkeypatch: pytest.MonkeyPatch, no_color_value: str
    ) -> None:
        """Test NO_COLOR environment variable disables colored output.

        Per NO_COLOR spec (https://no-color.org/), any value (including empty)
        should disable color.
        """
        monkeypatch.setenv("NO_COLOR", no_color_value)
        # Arrange & Act
        result = _should_use_color()

        # Assert
        assert result is False, f"NO_COLOR={no_color_value!r} should disable color"

    def test_no_color_unset_checks_tty(
        self, monkeypatch: pytest.MonkeyPatch, clean_env: None
    ) -> None:
        """Test color detection falls back to TTY check when NO_COLOR is unset.

        When NO_COLOR is not set, should use stdout.isatty() to detect terminal.
        """
        # Arrange & Act - TTY
        with patch.object(sys.stdout, "isatty", return_value=True):
            result_tty = _should_use_color()

        # Assert
        assert result_tty is True, "Should enable color for TTY"

        # Arrange & Act - non-TTY
        with patch.object(sys.stdout, "isatty", return_value=False):
            result_non_tty = _should_use_color()

        # Assert
        assert result_non_tty is False, "Should disable color for non-TTY"

    def test_isatty_raises_attribute_error(
        self, monkeypatch: pytest.MonkeyPatch, clean_env: None
    ) -> None:
        """Test graceful handling when stdout has no isatty method.

        Edge case: Some file-like objects don't have isatty().
        """
        # Arrange
        with patch.object(sys, "stdout", spec=[]):  # No isatty attribute

            # Act
            result = _should_use_color()

        # Assert
        assert result is False, "Should disable color when isatty() unavailable"

    def test_isatty_raises_os_error(
        self, monkeypatch: pytest.MonkeyPatch, clean_env: None
    ) -> None:
        """Test graceful handling when isatty() raises OSError.

        Edge case: Some environments raise errors when checking TTY.
        """
        # Arrange
        mock_stdout = MagicMock()
        mock_stdout.isatty.side_effect = OSError("Not a terminal")

        with patch.object(sys, "stdout", mock_stdout):
            # Act
            result = _should_use_color()

        # Assert
        assert result is False, "Should disable color when isatty() raises OSError"

    def test_no_color_priority_over_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test NO_COLOR takes precedence over TTY detection.

        Even when stdout is a TTY, NO_COLOR should disable color.
        """
        # Arrange
        monkeypatch.setenv("NO_COLOR", "1")

        with patch.object(sys.stdout, "isatty", return_value=True):
            # Act
            result = _should_use_color()

        # Assert
        assert result is False, "NO_COLOR should override TTY detection"


# ==============================================================================
# Console Singleton Tests
# ==============================================================================


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.integration
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


@pytest.mark.unit
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
            print_success("✓ 成功 ��")

            assert "✓ 成功 ��" in mock_print.call_args[0][0]

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


# ==============================================================================
# Additional Parametrized Tests
# ==============================================================================


@pytest.mark.unit
class TestPrintFunctionsParametrized:
    """Parametrized tests for all print functions."""

    @pytest.mark.parametrize(
        "func,message,style",
        [
            (print_success, "Success message", "success"),
            (print_error, "Error message", "error"),
            (print_warning, "Warning message", "warning"),
        ],
        ids=["print_success", "print_error", "print_warning"],
    )
    def test_print_functions_basic(self, func: Any, message: str, style: str) -> None:
        """Test all print functions with basic messages.

        Parametrized test covering success/error/warning functions.
        """
        # Act
        with patch.object(Console, "print") as mock_print:
            func(message)

        # Assert
        assert mock_print.call_count == 1
        assert style in str(mock_print.call_args)
        assert message in mock_print.call_args[0][0]

    @pytest.mark.parametrize(
        "prefix,message",
        [
            ("✓", "Test passed"),
            ("DONE", "Completed successfully"),
            ("", "No prefix"),
            ("��", "Celebration"),
            ("[INFO]", "Information"),
        ],
        ids=["checkmark", "done", "empty-prefix", "emoji", "info-prefix"],
    )
    def test_print_success_various_prefixes(self, prefix: str, message: str) -> None:
        """Test print_success with various prefix and message combinations."""
        # Act
        with patch.object(Console, "print") as mock_print:
            print_success(message, prefix=prefix)

        # Assert
        mock_print.assert_called_once_with(f"{prefix} {message}", style="success")


# ==============================================================================
# Additional Table Edge Cases
# ==============================================================================


@pytest.mark.unit
class TestPrintTableAdvanced:
    """Advanced table rendering edge cases."""

    def test_table_single_row(self) -> None:
        """Test print_table with single row."""
        # Arrange
        data = [{"name": "Alice", "age": "30"}]

        # Act
        with patch.object(Console, "print") as mock_print:
            print_table(data)

        # Assert
        assert mock_print.call_count == 1

    def test_table_single_column(self) -> None:
        """Test print_table with single column."""
        # Arrange
        data = [{"name": "Alice"}, {"name": "Bob"}, {"name": "Charlie"}]

        # Act
        with patch.object(Console, "print") as mock_print:
            print_table(data)

        # Assert
        table_arg = mock_print.call_args[0][0]
        assert len(table_arg.columns) == 1

    def test_table_with_many_rows(self) -> None:
        """Test print_table with many rows.

        Edge case: Tables with many rows should work efficiently.
        """
        # Arrange
        data = [{"id": str(i), "value": f"val{i}"} for i in range(1000)]

        # Act
        with patch.object(Console, "print") as mock_print:
            print_table(data)

        # Assert
        assert mock_print.call_count == 1

    def test_table_with_mixed_types(self) -> None:
        """Test print_table with mixed data types.

        Edge case: Rows with different value types should be converted to strings.
        """
        # Arrange
        data = [
            {"name": "Alice", "age": 30, "active": True},
            {"name": "Bob", "age": None, "active": False},
        ]

        # Act
        with patch.object(Console, "print") as mock_print:
            print_table(data)

        # Assert
        assert mock_print.call_count == 1

    @pytest.mark.parametrize(
        "value,expected_contains",
        [
            (30, "30"),
            (95.5, "95.5"),
            (None, "None"),
            (True, "True"),
            (False, "False"),
        ],
        ids=["int", "float", "none", "bool-true", "bool-false"],
    )
    def test_table_value_conversion(self, value: Any, expected_contains: str) -> None:
        """Test print_table converts various types to strings."""
        # Arrange
        data = [{"name": "Test", "value": value}]

        # Act
        with patch.object(Console, "print") as mock_print:
            print_table(data)

        # Assert
        assert mock_print.call_count == 1


# ==============================================================================
# Confirm Advanced Tests
# ==============================================================================


@pytest.mark.unit
class TestConfirmAdvanced:
    """Advanced confirm interaction tests."""

    @pytest.mark.parametrize(
        "response,expected",
        [
            ("y", True),
            ("yes", True),
            ("Y", True),
            ("YES", True),
            ("Yes", True),
            ("n", False),
            ("no", False),
            ("N", False),
            ("NO", False),
            ("No", False),
        ],
        ids=[
            "y-lower",
            "yes-lower",
            "y-upper",
            "yes-upper",
            "yes-mixed",
            "n-lower",
            "no-lower",
            "n-upper",
            "no-upper",
            "no-mixed",
        ],
    )
    def test_confirm_all_valid_responses(self, response: str, expected: bool) -> None:
        """Test confirm with all valid yes/no variations."""
        # Act
        with patch("builtins.input", return_value=response):
            result = confirm("Proceed?")

        # Assert
        assert result is expected

    @pytest.mark.parametrize(
        "response,default,expected",
        [
            ("", True, True),
            ("", False, False),
            ("maybe", True, True),
            ("maybe", False, False),
            ("123", True, True),
            ("xyz", False, False),
        ],
        ids=[
            "empty-default-true",
            "empty-default-false",
            "maybe-default-true",
            "maybe-default-false",
            "numeric-default-true",
            "invalid-default-false",
        ],
    )
    def test_confirm_invalid_inputs_use_default(
        self, response: str, default: bool, expected: bool
    ) -> None:
        """Test confirm falls back to default for invalid inputs."""
        # Act
        with patch("builtins.input", return_value=response):
            result = confirm("Proceed?", default=default)

        # Assert
        assert result is expected

    def test_confirm_multiple_prompts(self) -> None:
        """Test multiple consecutive confirm calls."""
        # Act & Assert
        with patch("builtins.input", side_effect=["y", "n", "yes", "no"]):
            assert confirm("First?") is True
            assert confirm("Second?") is False
            assert confirm("Third?") is True
            assert confirm("Fourth?") is False


# ==============================================================================
# Thread Safety Tests
# ==============================================================================


@pytest.mark.unit
class TestThreadSafety:
    """Comprehensive thread safety tests."""

    def test_concurrent_console_access(self) -> None:
        """Test concurrent access to console from multiple threads."""
        # Arrange
        reconfigure_console()
        results: List[Console] = []
        lock = threading.Lock()

        def access_thread() -> None:
            console = _get_console()
            with lock:
                results.append(console)

        # Act
        threads = [threading.Thread(target=access_thread) for _ in range(50)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # Assert
        assert len(results) == 50
        assert all(console is results[0] for console in results)

    def test_concurrent_print_operations(self) -> None:
        """Test concurrent print operations are safe."""
        # Arrange
        results: List[bool] = []
        lock = threading.Lock()

        def print_thread(msg: str) -> None:
            with patch.object(Console, "print"):
                print_success(msg)
                print_error(msg)
                print_warning(msg)
                with lock:
                    results.append(True)

        # Act
        threads = [
            threading.Thread(target=print_thread, args=(f"Message {i}",))
            for i in range(30)
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # Assert
        assert len(results) == 30


# ==============================================================================
# Security and Safety Tests
# ==============================================================================


@pytest.mark.unit
class TestSecurityAndSafety:
    """Security and safety considerations per security instructions."""

    def test_no_code_execution_in_table_data(self) -> None:
        """Test print_table doesn't execute code in data values.

        SECURITY_NOTE: Ensure data values are safely rendered as strings.
        """
        # Arrange - Potentially dangerous string representations
        data = [
            {"cmd": "__import__('os').system('echo pwned')"},
            {"cmd": "eval('1+1')"},
            {"cmd": "exec('import sys')"},
        ]

        # Act & Assert - Should just render as strings, not execute
        with patch.object(Console, "print") as mock_print:
            print_table(data)

            # Verify no exception and table was printed
            assert mock_print.call_count == 1

    def test_no_code_execution_in_messages(self) -> None:
        """Test print functions don't execute code in message strings.

        SECURITY_NOTE: Message strings should be safe to print.
        """
        # Arrange
        dangerous = 'eval(\'__import__("os").system("echo pwned")\')'

        # Act & Assert
        with patch.object(Console, "print") as mock_print:
            print_success(dangerous)
            print_error(dangerous)
            print_warning(dangerous)

            # Should print safely without executing
            assert mock_print.call_count == 3

    def test_input_sanitization_in_confirm(self) -> None:
        """Test confirm properly handles potentially problematic input.

        SECURITY_NOTE: User input should be safely processed.
        """
        # Arrange - Various potentially problematic inputs
        inputs = [
            "\x00",  # Null byte
            "\x1b[31m",  # ANSI escape
            "y\0n",  # Embedded null
            "y" * 10000,  # Very long input
            "yes\nno",  # Embedded newline
        ]

        # Act & Assert
        for inp in inputs:
            with patch("builtins.input", return_value=inp):
                with patch.object(Console, "print"):
                    # Should handle safely without crashing
                    result = confirm("Test?", default=False)
                    assert isinstance(result, bool)


# ==============================================================================
# Error Handling Tests
# ==============================================================================


@pytest.mark.unit
class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_colorize_with_whitespace(self) -> None:
        """Test colorize_update_type with leading/trailing whitespace."""
        # Act & Assert - Should not match due to whitespace
        assert colorize_update_type(" major") == " major"
        assert colorize_update_type("major ") == "major "
        assert colorize_update_type(" minor ") == " minor "


# ==============================================================================
# Integration Tests - Real World Scenarios
# ==============================================================================


@pytest.mark.integration
class TestRealWorldScenarios:
    """Integration tests for real-world usage patterns."""

    def test_update_workflow_complete(self, mock_tty: None) -> None:
        """Test complete update workflow with all console features.

        Integration test: Simulates real CLI update workflow.
        """
        # Arrange
        updates = [
            {
                "package": "requests",
                "current": "2.28.0",
                "latest": "2.31.0",
                "type": colorize_update_type("minor"),
            },
            {
                "package": "numpy",
                "current": "1.24.0",
                "latest": "1.26.0",
                "type": colorize_update_type("major"),
            },
        ]

        # Act & Assert - Full workflow
        with patch.object(Console, "print"):
            # Initial message
            print_success("Checking for updates...")

            # Display table
            print_table(
                updates,
                title="Available Updates",
                headers=["package", "current", "latest", "type"],
                caption="2 updates found",
            )

            # Warning
            print_warning("Major updates may contain breaking changes")

            # Confirmation
            with patch("builtins.input", return_value="y"):
                proceed = confirm("Apply updates?", default=False)
                assert proceed is True

            # Success
            print_success("Updates applied successfully", prefix="✓")

    def test_error_recovery_workflow(self) -> None:
        """Test error display and recovery workflow."""
        # Act & Assert
        with patch.object(Console, "print"):
            print_error("Failed to connect to PyPI")
            print_warning("Retrying with different mirror...")
            print_success("Connected successfully")

    def test_reconfiguration_during_execution(
        self, monkeypatch: pytest.MonkeyPatch, mock_tty: None
    ) -> None:
        """Test runtime reconfiguration affects subsequent operations."""
        # Arrange - Start with color
        with patch.object(Console, "print") as mock_print:
            print_success("Initial message")
            initial_calls = mock_print.call_count

        # Act - Disable color
        monkeypatch.setenv("NO_COLOR", "1")
        reconfigure_console()

        # Assert - New console has no color
        console = _get_console()
        assert console.no_color is True

        with patch.object(Console, "print") as mock_print:
            print_success("After reconfigure")
            assert mock_print.call_count >= 1


# ==============================================================================
# Performance and Stress Tests
# ==============================================================================


@pytest.mark.unit
@pytest.mark.slow
class TestPerformance:
    """Performance and stress tests."""

    def test_large_table_rendering(self) -> None:
        """Test rendering large tables efficiently."""
        # Arrange - 10000 rows
        data = [
            {"id": str(i), "name": f"user{i}", "value": f"value{i}"}
            for i in range(10000)
        ]

        # Act
        with patch.object(Console, "print") as mock_print:
            print_table(data)

        # Assert
        assert mock_print.call_count == 1

    def test_very_long_messages(self) -> None:
        """Test handling of very long message strings."""
        # Arrange
        long_message = "x" * 1000000  # 1MB string

        # Act
        with patch.object(Console, "print") as mock_print:
            print_success(long_message)

        # Assert
        assert mock_print.call_count == 1
        assert long_message in mock_print.call_args[0][0]

    def test_many_sequential_operations(self) -> None:
        """Test many sequential console operations."""
        # Act
        with patch.object(Console, "print") as mock_print:
            for i in range(1000):
                print_success(f"Message {i}")
                print_error(f"Error {i}")
                print_warning(f"Warning {i}")

        # Assert
        assert mock_print.call_count == 3000
