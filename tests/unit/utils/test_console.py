import sys
import logging
import threading
from unittest.mock import Mock, patch, MagicMock

import pytest
from rich.console import Console

from depkeeper.utils.console import (
    _should_use_color,
    _get_console,
    reconfigure_console,
    print_success,
    print_error,
    print_warning,
    print_info,
    print_table,
    confirm,
    get_raw_console,
    colorize_update_type,
    DEPKEEPER_THEME,
)


@pytest.fixture(autouse=True)
def reset_console():
    """Reset console state before and after each test."""
    reconfigure_console()
    yield
    reconfigure_console()


@pytest.fixture
def clean_env(monkeypatch):
    """Provide a clean environment without NO_COLOR or CI variables."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("CI", raising=False)
    reconfigure_console()
    yield


@pytest.fixture
def mock_logger():
    """Provide a mock logger for testing."""
    with patch("depkeeper.utils.console.logger") as mock:
        yield mock


@pytest.fixture
def mock_console():
    """Provide a mock Rich Console instance."""
    with patch("depkeeper.utils.console.Console") as MockConsole:
        mock_instance = MagicMock(spec=Console)
        MockConsole.return_value = mock_instance
        reconfigure_console()  # Force re-initialization with mock
        yield mock_instance


class TestShouldUseColor:
    """Test suite for color detection logic."""

    def test_color_enabled_by_default(self, clean_env):
        """Color should be enabled when all conditions are favorable."""
        with patch("sys.stdout.isatty", return_value=True):
            assert _should_use_color() is True

    def test_no_color_env_disables_color(self, monkeypatch):
        """NO_COLOR environment variable should disable color."""
        monkeypatch.setenv("NO_COLOR", "1")
        assert _should_use_color() is False

    def test_no_color_with_any_value(self, monkeypatch):
        """NO_COLOR should disable color regardless of value."""
        for value in ["1", "true", "yes", "0", "", "random"]:
            monkeypatch.setenv("NO_COLOR", value)
            assert _should_use_color() is False

    def test_ci_env_disables_color(self, monkeypatch, clean_env):
        """CI environment variable should disable color."""
        monkeypatch.setenv("CI", "true")
        assert _should_use_color() is False

    def test_ci_with_various_values(self, monkeypatch, clean_env):
        """CI variable should disable color with any value."""
        for value in ["1", "true", "yes"]:
            monkeypatch.setenv("CI", value)
            assert _should_use_color() is False

    def test_non_tty_disables_color(self, clean_env):
        """Non-TTY stdout should disable color."""
        with patch("sys.stdout.isatty", return_value=False):
            assert _should_use_color() is False

    def test_isatty_attribute_error(self, clean_env):
        """Missing isatty() method should disable color."""
        with patch.object(sys.stdout, "isatty", side_effect=AttributeError):
            assert _should_use_color() is False

    def test_isatty_os_error(self, clean_env):
        """OSError from isatty() should disable color."""
        with patch.object(sys.stdout, "isatty", side_effect=OSError):
            assert _should_use_color() is False

    def test_no_color_takes_precedence_over_tty(self, monkeypatch):
        """NO_COLOR should override TTY detection."""
        monkeypatch.setenv("NO_COLOR", "1")
        with patch("sys.stdout.isatty", return_value=True):
            assert _should_use_color() is False

    def test_ci_takes_precedence_over_tty(self, monkeypatch, clean_env):
        """CI should override TTY detection."""
        monkeypatch.setenv("CI", "1")
        with patch("sys.stdout.isatty", return_value=True):
            assert _should_use_color() is False


class TestGetConsole:
    """Test suite for console initialization and retrieval."""

    def test_console_lazy_initialization(self):
        """Console should be created on first access."""
        reconfigure_console()
        with patch("depkeeper.utils.console.Console") as MockConsole:
            mock_instance = MagicMock()
            MockConsole.return_value = mock_instance

            console = _get_console()

            MockConsole.assert_called_once()
            assert console is mock_instance

    def test_console_singleton_behavior(self):
        """Same console instance should be returned on multiple calls."""
        console1 = _get_console()
        console2 = _get_console()
        assert console1 is console2

    def test_console_theme_configuration(self, clean_env):
        """Console should be configured with DEPKEEPER_THEME."""
        with patch("depkeeper.utils.console.Console") as MockConsole:
            with patch("sys.stdout.isatty", return_value=True):
                reconfigure_console()
                _get_console()

                MockConsole.assert_called_once_with(
                    theme=DEPKEEPER_THEME,
                    no_color=False,
                    highlight=True,
                )

    def test_console_no_color_configuration(self, monkeypatch):
        """Console should disable color when NO_COLOR is set."""
        monkeypatch.setenv("NO_COLOR", "1")
        with patch("depkeeper.utils.console.Console") as MockConsole:
            reconfigure_console()
            _get_console()

            MockConsole.assert_called_once_with(
                theme=DEPKEEPER_THEME,
                no_color=True,
                highlight=False,
            )

    def test_console_thread_safety(self):
        """Console initialization should be thread-safe."""
        reconfigure_console()
        consoles = []
        errors = []

        def get_console_thread():
            try:
                consoles.append(_get_console())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=get_console_thread) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors, f"Thread safety errors: {errors}"
        # All threads should get the same instance
        assert all(c is consoles[0] for c in consoles)

    def test_console_double_checked_locking(self):
        """Console should use double-checked locking pattern."""
        reconfigure_console()
        with patch("depkeeper.utils.console.Console") as MockConsole:
            mock_instance = MagicMock()
            MockConsole.return_value = mock_instance

            # Simulate concurrent access
            console1 = _get_console()
            console2 = _get_console()

            # Should only create one instance
            assert MockConsole.call_count == 1
            assert console1 is console2


class TestReconfigureConsole:
    """Test suite for console reconfiguration."""

    def test_reconfigure_resets_console(self):
        """Reconfiguring should reset the console instance."""
        console1 = _get_console()
        reconfigure_console()
        console2 = _get_console()
        assert console1 is not console2

    def test_reconfigure_picks_up_env_changes(self, monkeypatch, clean_env):
        """Reconfiguring should pick up environment variable changes."""
        # First, get console with colors
        with patch("depkeeper.utils.console.Console") as MockConsole:
            with patch("sys.stdout.isatty", return_value=True):
                reconfigure_console()
                _get_console()
                assert MockConsole.call_args[1]["no_color"] is False

        # Set NO_COLOR
        monkeypatch.setenv("NO_COLOR", "1")

        # Reconfigure and get console again
        with patch("depkeeper.utils.console.Console") as MockConsole:
            reconfigure_console()
            _get_console()
            assert MockConsole.call_args[1]["no_color"] is True

    def test_reconfigure_thread_safety(self):
        """Reconfiguring should be thread-safe."""
        errors = []

        def reconfigure_thread():
            try:
                reconfigure_console()
                _get_console()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reconfigure_thread) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors, f"Thread safety errors: {errors}"


class TestPrintSuccess:
    """Test suite for success message printing."""

    def test_print_success_default_prefix(self, mock_console):
        """Should print success message with default prefix."""
        print_success("Test message")
        mock_console.print.assert_called_once_with("[OK] Test message", style="success")

    def test_print_success_custom_prefix(self, mock_console):
        """Should print success message with custom prefix."""
        print_success("Test message", prefix="✓")
        mock_console.print.assert_called_once_with("✓ Test message", style="success")

    def test_print_success_empty_prefix(self, mock_console):
        """Should print success message with empty prefix."""
        print_success("Test message", prefix="")
        mock_console.print.assert_called_once_with(" Test message", style="success")

    def test_print_success_with_special_characters(self, mock_console):
        """Should handle messages with special characters."""
        print_success("Success: 100% complete!")
        mock_console.print.assert_called_once()

    def test_print_success_multiline(self, mock_console):
        """Should handle multiline messages."""
        print_success("Line 1\nLine 2\nLine 3")
        mock_console.print.assert_called_once()


class TestPrintError:
    """Test suite for error message printing."""

    def test_print_error_default_prefix(self, mock_console):
        """Should print error message with default prefix."""
        print_error("Error occurred")
        mock_console.print.assert_called_once_with(
            "[ERROR] Error occurred", style="error"
        )

    def test_print_error_custom_prefix(self, mock_console):
        """Should print error message with custom prefix."""
        print_error("Error occurred", prefix="✗")
        mock_console.print.assert_called_once_with("✗ Error occurred", style="error")

    def test_print_error_empty_prefix(self, mock_console):
        """Should print error message with empty prefix."""
        print_error("Error occurred", prefix="")
        mock_console.print.assert_called_once_with(" Error occurred", style="error")


class TestPrintWarning:
    """Test suite for warning message printing."""

    def test_print_warning_default_prefix(self, mock_console):
        """Should print warning message with default prefix."""
        print_warning("Warning message")
        mock_console.print.assert_called_once_with(
            "[WARNING] Warning message", style="warning"
        )

    def test_print_warning_custom_prefix(self, mock_console):
        """Should print warning message with custom prefix."""
        print_warning("Warning message", prefix="⚠")
        mock_console.print.assert_called_once_with("⚠ Warning message", style="warning")


class TestPrintInfo:
    """Test suite for info message printing."""

    def test_print_info_when_logger_info_level(self, mock_console):
        """Should print info message when logger is at INFO level."""
        with patch("logging.getLogger") as mock_get_logger:
            mock_depkeeper_logger = Mock()
            mock_depkeeper_logger.getEffectiveLevel.return_value = logging.INFO
            mock_get_logger.return_value = mock_depkeeper_logger

            print_info("Info message")
            mock_console.print.assert_called_once_with(
                "[INFO] Info message", style="info"
            )

    def test_print_info_when_logger_debug_level(self, mock_console):
        """Should print info message when logger is at DEBUG level."""
        with patch("logging.getLogger") as mock_get_logger:
            mock_depkeeper_logger = Mock()
            mock_depkeeper_logger.getEffectiveLevel.return_value = logging.DEBUG
            mock_get_logger.return_value = mock_depkeeper_logger

            print_info("Info message")
            mock_console.print.assert_called_once()

    def test_print_info_suppressed_when_logger_warning_level(self, mock_console):
        """Should not print info message when logger is at WARNING level."""
        with patch("logging.getLogger") as mock_get_logger:
            mock_depkeeper_logger = Mock()
            mock_depkeeper_logger.getEffectiveLevel.return_value = logging.WARNING
            mock_get_logger.return_value = mock_depkeeper_logger

            print_info("Info message")
            mock_console.print.assert_not_called()

    def test_print_info_suppressed_when_logger_error_level(self, mock_console):
        """Should not print info message when logger is at ERROR level."""
        with patch("logging.getLogger") as mock_get_logger:
            mock_depkeeper_logger = Mock()
            mock_depkeeper_logger.getEffectiveLevel.return_value = logging.ERROR
            mock_get_logger.return_value = mock_depkeeper_logger

            print_info("Info message")
            mock_console.print.assert_not_called()

    def test_print_info_custom_prefix(self, mock_console):
        """Should print info message with custom prefix."""
        with patch("logging.getLogger") as mock_get_logger:
            mock_depkeeper_logger = Mock()
            mock_depkeeper_logger.getEffectiveLevel.return_value = logging.INFO
            mock_get_logger.return_value = mock_depkeeper_logger

            print_info("Info message", prefix="ℹ")
            mock_console.print.assert_called_once_with("ℹ Info message", style="info")


class TestPrintTable:
    """Test suite for table printing."""

    def test_print_table_basic(self, mock_console):
        """Should print a basic table with data."""
        data = [
            {"Package": "requests", "Version": "2.28.0"},
            {"Package": "click", "Version": "8.0.0"},
        ]
        print_table(data)
        mock_console.print.assert_called_once()

    def test_print_table_with_title(self, mock_console):
        """Should print table with title."""
        data = [{"Package": "requests"}]
        print_table(data, title="Test Table")
        # Verify table was created with title
        mock_console.print.assert_called_once()

    def test_print_table_with_caption(self, mock_console):
        """Should print table with caption."""
        data = [{"Package": "requests"}]
        print_table(data, caption="Test caption")
        mock_console.print.assert_called_once()

    def test_print_table_custom_headers(self, mock_console):
        """Should use custom headers when provided."""
        data = [{"col1": "val1", "col2": "val2"}]
        print_table(data, headers=["col2", "col1"])  # Reversed order
        mock_console.print.assert_called_once()

    def test_print_table_column_styles(self, mock_console):
        """Should apply column styles."""
        data = [{"Status": "OK", "Package": "requests"}]
        column_styles = {
            "Status": {"justify": "center", "width": 8},
            "Package": {"style": "bold"},
        }
        print_table(data, column_styles=column_styles)
        mock_console.print.assert_called_once()

    def test_print_table_row_styler(self, mock_console):
        """Should apply row styling function."""
        data = [
            {"Status": "error", "Package": "pkg1"},
            {"Status": "ok", "Package": "pkg2"},
        ]

        def row_styler(row):
            return "red" if row["Status"] == "error" else "green"

        print_table(data, row_styler=row_styler)
        mock_console.print.assert_called_once()

    def test_print_table_row_styler_none_return(self, mock_console):
        """Should handle row styler returning None."""
        data = [{"Package": "requests"}]

        def row_styler(row):
            return None

        print_table(data, row_styler=row_styler)
        mock_console.print.assert_called_once()

    def test_print_table_missing_keys(self, mock_console):
        """Should handle rows with missing keys gracefully."""
        data = [
            {"Package": "requests", "Version": "2.28.0"},
            {"Package": "click"},  # Missing Version
        ]
        print_table(data)
        mock_console.print.assert_called_once()

    def test_print_table_empty_data(self, mock_console, mock_logger):
        """Should handle empty data list gracefully."""
        print_table([])
        mock_console.print.assert_not_called()
        mock_logger.debug.assert_called_once_with("No data to display in table")

    def test_print_table_rich_markup(self, mock_console):
        """Should handle Rich markup in cell values."""
        data = [{"Status": "[green]OK[/green]", "Package": "requests"}]
        print_table(data)
        mock_console.print.assert_called_once()

    def test_print_table_column_style_options(self, mock_console):
        """Should apply all column style options."""
        data = [{"Col": "value"}]
        column_styles = {
            "Col": {
                "style": "bold red",
                "justify": "right",
                "no_wrap": True,
                "width": 20,
                "overflow": "ellipsis",
            }
        }
        print_table(data, column_styles=column_styles)
        mock_console.print.assert_called_once()

    def test_print_table_headers_from_first_row(self, mock_console):
        """Should infer headers from first data row when not provided."""
        data = [
            {"A": "1", "B": "2", "C": "3"},
            {"A": "4", "B": "5", "C": "6"},
        ]
        print_table(data)
        mock_console.print.assert_called_once()

    def test_print_table_all_options_combined(self, mock_console):
        """Should handle all options combined."""
        data = [
            {"Status": "[green]OK[/green]", "Package": "requests"},
            {"Status": "[red]ERROR[/red]", "Package": "click"},
        ]

        def row_styler(row):
            return "dim" if "ERROR" in row.get("Status", "") else None

        column_styles = {
            "Status": {"justify": "center", "width": 10},
        }

        print_table(
            data,
            headers=["Status", "Package"],
            title="Package Status",
            caption="2 packages",
            column_styles=column_styles,
            row_styler=row_styler,
        )
        mock_console.print.assert_called_once()


class TestConfirm:
    """Test suite for user confirmation prompts."""

    def test_confirm_yes_response(self, mock_console):
        """Should return True for 'yes' response."""
        with patch("builtins.input", return_value="yes"):
            result = confirm("Continue?")
            assert result is True

    def test_confirm_y_response(self, mock_console):
        """Should return True for 'y' response."""
        with patch("builtins.input", return_value="y"):
            result = confirm("Continue?")
            assert result is True

    def test_confirm_no_response(self, mock_console):
        """Should return False for 'no' response."""
        with patch("builtins.input", return_value="no"):
            result = confirm("Continue?")
            assert result is False

    def test_confirm_n_response(self, mock_console):
        """Should return False for 'n' response."""
        with patch("builtins.input", return_value="n"):
            result = confirm("Continue?")
            assert result is False

    def test_confirm_case_insensitive(self, mock_console):
        """Should be case-insensitive."""
        for response in ["YES", "Yes", "Y", "NO", "No", "N"]:
            with patch("builtins.input", return_value=response):
                result = confirm("Continue?")
                assert result in [True, False]

    def test_confirm_whitespace_stripped(self, mock_console):
        """Should strip whitespace from responses."""
        with patch("builtins.input", return_value="  yes  "):
            result = confirm("Continue?")
            assert result is True

    def test_confirm_empty_response_default_false(self, mock_console):
        """Should use default=False for empty response."""
        with patch("builtins.input", return_value=""):
            result = confirm("Continue?", default=False)
            assert result is False

    def test_confirm_empty_response_default_true(self, mock_console):
        """Should use default=True for empty response."""
        with patch("builtins.input", return_value=""):
            result = confirm("Continue?", default=True)
            assert result is True

    def test_confirm_default_false_prompt(self, mock_console):
        """Should show [y/N] for default=False."""
        with patch("builtins.input", return_value=""):
            confirm("Continue?", default=False)
            mock_console.print.assert_called_once()
            call_args = mock_console.print.call_args
            assert "[y/N]" in call_args[0][0]

    def test_confirm_default_true_prompt(self, mock_console):
        """Should show [Y/n] for default=True."""
        with patch("builtins.input", return_value=""):
            confirm("Continue?", default=True)
            mock_console.print.assert_called_once()
            call_args = mock_console.print.call_args
            assert "[Y/n]" in call_args[0][0]

    def test_confirm_keyboard_interrupt(self, mock_console):
        """Should return False on KeyboardInterrupt."""
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            result = confirm("Continue?")
            assert result is False

    def test_confirm_eof_error(self, mock_console):
        """Should return False on EOFError."""
        with patch("builtins.input", side_effect=EOFError):
            result = confirm("Continue?")
            assert result is False

    def test_confirm_prints_newline_on_interrupt(self, mock_console):
        """Should print newline after interrupt."""
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            confirm("Continue?")
            # Should be called twice: once for prompt, once for newline
            assert mock_console.print.call_count == 2

    def test_confirm_invalid_response_treated_as_no(self, mock_console):
        """Should treat invalid responses as no."""
        with patch("builtins.input", return_value="invalid"):
            result = confirm("Continue?", default=False)
            assert result is False


class TestGetRawConsole:
    """Test suite for raw console retrieval."""

    def test_get_raw_console_returns_console(self):
        """Should return the global console instance."""
        console = get_raw_console()
        assert console is _get_console()

    def test_get_raw_console_same_instance(self):
        """Should return same instance on multiple calls."""
        console1 = get_raw_console()
        console2 = get_raw_console()
        assert console1 is console2

    def test_get_raw_console_after_reconfigure(self):
        """Should return new instance after reconfiguration."""
        console1 = get_raw_console()
        reconfigure_console()
        console2 = get_raw_console()
        assert console1 is not console2


class TestColorizeUpdateType:
    """Test suite for update type colorization."""

    def test_colorize_major_update(self):
        """Should colorize 'major' as red."""
        result = colorize_update_type("major")
        assert result == "[red]major[/red]"

    def test_colorize_minor_update(self):
        """Should colorize 'minor' as yellow."""
        result = colorize_update_type("minor")
        assert result == "[yellow]minor[/yellow]"

    def test_colorize_patch_update(self):
        """Should colorize 'patch' as green."""
        result = colorize_update_type("patch")
        assert result == "[green]patch[/green]"

    def test_colorize_new_package(self):
        """Should colorize 'new' as cyan."""
        result = colorize_update_type("new")
        assert result == "[cyan]new[/cyan]"

    def test_colorize_downgrade(self):
        """Should colorize 'downgrade' as red."""
        result = colorize_update_type("downgrade")
        assert result == "[red]downgrade[/red]"

    def test_colorize_update(self):
        """Should colorize 'update' as yellow."""
        result = colorize_update_type("update")
        assert result == "[yellow]update[/yellow]"

    def test_colorize_case_insensitive(self):
        """Should handle case-insensitive matching."""
        assert colorize_update_type("MAJOR") == "[red]MAJOR[/red]"
        assert colorize_update_type("Minor") == "[yellow]Minor[/yellow]"
        assert colorize_update_type("PaTcH") == "[green]PaTcH[/green]"

    def test_colorize_unknown_type(self):
        """Should return unchanged for unknown types."""
        result = colorize_update_type("unknown")
        assert result == "unknown"

    def test_colorize_empty_string(self):
        """Should return empty string unchanged."""
        result = colorize_update_type("")
        assert result == ""

    def test_colorize_with_whitespace(self):
        """Should handle types with whitespace."""
        result = colorize_update_type("  major  ")
        assert result == "  major  "  # Whitespace prevents match


class TestDepkeeperTheme:
    """Test suite for theme configuration."""

    def test_theme_has_all_styles(self):
        """Theme should define all expected styles."""
        expected_styles = ["success", "error", "warning", "info", "dim", "highlight"]
        for style in expected_styles:
            assert style in DEPKEEPER_THEME.styles

    def test_theme_success_style(self):
        """Success style should be bold green."""
        style = DEPKEEPER_THEME.styles["success"]
        assert style.color.name == "green"
        assert style.bold is True

    def test_theme_error_style(self):
        """Error style should be bold red."""
        style = DEPKEEPER_THEME.styles["error"]
        assert style.color.name == "red"
        assert style.bold is True

    def test_theme_warning_style(self):
        """Warning style should be bold yellow."""
        style = DEPKEEPER_THEME.styles["warning"]
        assert style.color.name == "yellow"
        assert style.bold is True

    def test_theme_info_style(self):
        """Info style should be bold cyan."""
        style = DEPKEEPER_THEME.styles["info"]
        assert style.color.name == "cyan"
        assert style.bold is True

    def test_theme_dim_style(self):
        """Dim style should be dim."""
        style = DEPKEEPER_THEME.styles["dim"]
        assert style.dim is True

    def test_theme_highlight_style(self):
        """Highlight style should be bold magenta."""
        style = DEPKEEPER_THEME.styles["highlight"]
        assert style.color.name == "magenta"
        assert style.bold is True


class TestIntegration:
    """Integration tests for console module."""

    def test_environment_changes_persist_after_reconfigure(self, monkeypatch):
        """Environment changes should persist after reconfiguration."""
        # Start with no color
        monkeypatch.setenv("NO_COLOR", "1")
        reconfigure_console()
        assert _should_use_color() is False

        # Remove NO_COLOR
        monkeypatch.delenv("NO_COLOR")
        reconfigure_console()
        with patch("sys.stdout.isatty", return_value=True):
            assert _should_use_color() is True

    def test_multiple_print_functions_use_same_console(self):
        """All print functions should use the same console instance."""
        with patch("depkeeper.utils.console.Console") as MockConsole:
            mock_instance = MagicMock()
            MockConsole.return_value = mock_instance
            reconfigure_console()

            print_success("success")
            print_error("error")
            print_warning("warning")
            with patch("logging.getLogger") as mock_get_logger:
                mock_logger = Mock()
                mock_logger.getEffectiveLevel.return_value = logging.INFO
                mock_get_logger.return_value = mock_logger
                print_info("info")

            # All should use same console instance
            assert MockConsole.call_count == 1

    def test_console_survives_exception_in_print(self, mock_console):
        """Console should remain functional after print exception."""
        mock_console.print.side_effect = [Exception("Test error"), None]

        with pytest.raises(Exception):
            print_success("This will fail")

        # Console should still work
        print_success("This should work")
        assert mock_console.print.call_count == 2
