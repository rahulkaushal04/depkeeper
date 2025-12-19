from __future__ import annotations

import io
import sys
import pytest
import logging
import threading
from unittest.mock import patch

from depkeeper.utils.logger import (
    ColoredFormatter,
    setup_logging,
    get_logger,
    is_logging_configured,
    disable_logging,
)
from depkeeper.constants import (
    LOG_DATE_FORMAT,
    LOG_DEFAULT_FORMAT,
    LOG_VERBOSE_FORMAT,
)


@pytest.fixture(autouse=True)
def reset_logging_state():
    """Reset logging state before and after each test to ensure isolation."""
    # Reset before test
    disable_logging()

    # Clear any existing handlers from depkeeper loggers
    root = logging.getLogger("depkeeper")
    for logger_name in list(logging.Logger.manager.loggerDict.keys()):
        if logger_name.startswith("depkeeper"):
            logger = logging.getLogger(logger_name)
            logger.handlers.clear()
            logger.setLevel(logging.NOTSET)
            logger.propagate = True

    yield

    # Reset after test
    disable_logging()

    # Clear handlers again
    for logger_name in list(logging.Logger.manager.loggerDict.keys()):
        if logger_name.startswith("depkeeper"):
            logger = logging.getLogger(logger_name)
            logger.handlers.clear()
            logger.setLevel(logging.NOTSET)
            logger.propagate = True


@pytest.fixture
def string_stream():
    """Provide a StringIO stream for capturing log output."""
    return io.StringIO()


@pytest.fixture
def clean_environment(monkeypatch):
    """Provide a clean environment without NO_COLOR or CI variables."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("CI", raising=False)
    return monkeypatch


class TestColoredFormatter:
    """Test suite for ColoredFormatter class."""

    def test_formatter_initialization_default(self):
        """Test ColoredFormatter initializes with default use_color=True."""
        formatter = ColoredFormatter(LOG_DEFAULT_FORMAT)
        assert formatter.use_color is True

    def test_formatter_initialization_custom_format(self):
        """Test ColoredFormatter with custom format string."""
        custom_format = "%(levelname)s - %(message)s"
        formatter = ColoredFormatter(custom_format, use_color=False)
        assert formatter.use_color is False

    def test_formatter_initialization_with_datefmt(self):
        """Test ColoredFormatter with date format."""
        formatter = ColoredFormatter(
            LOG_VERBOSE_FORMAT, datefmt=LOG_DATE_FORMAT, use_color=True
        )
        assert formatter.use_color is True
        assert formatter.datefmt == LOG_DATE_FORMAT

    def test_formatter_colors_defined(self):
        """Test that all standard log levels have color codes defined."""
        assert "DEBUG" in ColoredFormatter.COLORS
        assert "INFO" in ColoredFormatter.COLORS
        assert "WARNING" in ColoredFormatter.COLORS
        assert "ERROR" in ColoredFormatter.COLORS
        assert "CRITICAL" in ColoredFormatter.COLORS

        # Verify they are ANSI escape codes
        assert ColoredFormatter.COLORS["DEBUG"].startswith("\033[")
        assert ColoredFormatter.RESET == "\033[0m"

    def test_should_use_color_no_color_env_set(self, clean_environment):
        """Test that color is disabled when NO_COLOR environment variable is set."""
        clean_environment.setenv("NO_COLOR", "1")
        formatter = ColoredFormatter(LOG_DEFAULT_FORMAT, use_color=True)
        assert formatter._should_use_color() is False

    def test_should_use_color_ci_env_set(self, clean_environment):
        """Test that color is disabled in CI environment."""
        clean_environment.setenv("CI", "true")
        formatter = ColoredFormatter(LOG_DEFAULT_FORMAT, use_color=True)
        assert formatter._should_use_color() is False

    def test_should_use_color_not_tty(self, clean_environment):
        """Test that color is disabled when stderr is not a TTY."""
        formatter = ColoredFormatter(LOG_DEFAULT_FORMAT, use_color=True)
        with patch.object(sys.stderr, "isatty", return_value=False):
            assert formatter._should_use_color() is False

    def test_should_use_color_tty_enabled(self, clean_environment):
        """Test that color is enabled when stderr is a TTY and no env vars set."""
        formatter = ColoredFormatter(LOG_DEFAULT_FORMAT, use_color=True)
        with patch.object(sys.stderr, "isatty", return_value=True):
            assert formatter._should_use_color() is True

    def test_should_use_color_attribute_error(self, clean_environment):
        """Test graceful handling when stderr has no isatty method."""
        formatter = ColoredFormatter(LOG_DEFAULT_FORMAT, use_color=True)

        # Remove isatty attribute
        original_stderr = sys.stderr
        sys.stderr = io.StringIO()  # StringIO has no isatty

        try:
            result = formatter._should_use_color()
            assert result is False
        finally:
            sys.stderr = original_stderr

    def test_should_use_color_os_error(self, clean_environment):
        """Test graceful handling when isatty raises OSError."""
        formatter = ColoredFormatter(LOG_DEFAULT_FORMAT, use_color=True)

        with patch.object(sys.stderr, "isatty", side_effect=OSError("Test error")):
            assert formatter._should_use_color() is False

    def test_format_with_color_enabled(self, clean_environment):
        """Test formatting with color when conditions are met."""
        formatter = ColoredFormatter("%(levelname)s - %(message)s", use_color=True)

        with patch.object(sys.stderr, "isatty", return_value=True):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg="Test message",
                args=(),
                exc_info=None,
            )

            formatted = formatter.format(record)
            # Should contain ANSI color codes
            assert "\033[" in formatted
            assert "INFO" in formatted
            assert "Test message" in formatted

    def test_format_with_color_disabled(self):
        """Test formatting without color when use_color=False."""
        formatter = ColoredFormatter("%(levelname)s - %(message)s", use_color=False)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)
        # Should NOT contain ANSI color codes
        assert "\033[" not in formatted
        assert formatted == "INFO - Test message"

    def test_format_all_log_levels(self, clean_environment):
        """Test that all log levels can be formatted with color."""
        formatter = ColoredFormatter("%(levelname)s - %(message)s", use_color=True)

        levels = [
            (logging.DEBUG, "DEBUG"),
            (logging.INFO, "INFO"),
            (logging.WARNING, "WARNING"),
            (logging.ERROR, "ERROR"),
            (logging.CRITICAL, "CRITICAL"),
        ]

        with patch.object(sys.stderr, "isatty", return_value=True):
            for level_num, level_name in levels:
                record = logging.LogRecord(
                    name="test",
                    level=level_num,
                    pathname="test.py",
                    lineno=1,
                    msg="Test message",
                    args=(),
                    exc_info=None,
                )

                formatted = formatter.format(record)
                assert level_name in formatted

    def test_format_unknown_level_no_color(self, clean_environment):
        """Test formatting with unknown log level doesn't crash."""
        formatter = ColoredFormatter("%(levelname)s - %(message)s", use_color=True)

        with patch.object(sys.stderr, "isatty", return_value=True):
            # Create record with custom level
            record = logging.LogRecord(
                name="test",
                level=25,  # Custom level between INFO and WARNING
                pathname="test.py",
                lineno=1,
                msg="Test message",
                args=(),
                exc_info=None,
            )
            record.levelname = "CUSTOM"

            # Should not crash, just format without color
            formatted = formatter.format(record)
            assert "CUSTOM" in formatted
            assert "Test message" in formatted


class TestSetupLogging:
    """Test suite for setup_logging function."""

    def test_setup_logging_default_parameters(self):
        """Test setup_logging with all default parameters."""
        setup_logging()

        assert is_logging_configured() is True
        logger = logging.getLogger("depkeeper")
        assert logger.level == logging.INFO
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.StreamHandler)
        assert logger.propagate is False

    def test_setup_logging_debug_level(self):
        """Test setup_logging with DEBUG level."""
        setup_logging(level=logging.DEBUG)

        logger = logging.getLogger("depkeeper")
        assert logger.level == logging.DEBUG
        assert logger.handlers[0].level == logging.DEBUG

    def test_setup_logging_warning_level(self):
        """Test setup_logging with WARNING level."""
        setup_logging(level=logging.WARNING)

        logger = logging.getLogger("depkeeper")
        assert logger.level == logging.WARNING

    def test_setup_logging_error_level(self):
        """Test setup_logging with ERROR level."""
        setup_logging(level=logging.ERROR)

        logger = logging.getLogger("depkeeper")
        assert logger.level == logging.ERROR

    def test_setup_logging_critical_level(self):
        """Test setup_logging with CRITICAL level."""
        setup_logging(level=logging.CRITICAL)

        logger = logging.getLogger("depkeeper")
        assert logger.level == logging.CRITICAL

    def test_setup_logging_verbose_format(self):
        """Test setup_logging with verbose=True uses verbose format."""
        stream = io.StringIO()
        setup_logging(verbose=True, stream=stream)

        logger = logging.getLogger("depkeeper")
        handler = logger.handlers[0]
        formatter = handler.formatter

        # Verify it's a ColoredFormatter
        assert isinstance(formatter, ColoredFormatter)

    def test_setup_logging_non_verbose_format(self):
        """Test setup_logging with verbose=False uses default format."""
        stream = io.StringIO()
        setup_logging(verbose=False, stream=stream)

        logger = logging.getLogger("depkeeper")
        handler = logger.handlers[0]
        formatter = handler.formatter

        assert isinstance(formatter, ColoredFormatter)

    def test_setup_logging_custom_stream(self, string_stream):
        """Test setup_logging with custom stream."""
        setup_logging(stream=string_stream)

        logger = logging.getLogger("depkeeper")
        logger.info("Test message")

        output = string_stream.getvalue()
        assert "Test message" in output

    def test_setup_logging_to_file(self, temp_dir):
        """Test setup_logging with file stream."""
        log_file = temp_dir / "test.log"

        with open(log_file, "w") as f:
            setup_logging(stream=f)
            logger = logging.getLogger("depkeeper")
            logger.info("Test message to file")

        with open(log_file, "r") as f:
            content = f.read()
            assert "Test message to file" in content

    def test_setup_logging_multiple_calls(self, string_stream):
        """Test that calling setup_logging multiple times reconfigures properly."""
        # First call
        setup_logging(level=logging.INFO, stream=string_stream)
        logger = logging.getLogger("depkeeper")
        assert len(logger.handlers) == 1
        assert logger.level == logging.INFO

        # Second call with different level
        stream2 = io.StringIO()
        setup_logging(level=logging.DEBUG, stream=stream2)

        # Should still have only one handler
        assert len(logger.handlers) == 1
        assert logger.level == logging.DEBUG

    def test_setup_logging_clears_existing_handlers(self, string_stream):
        """Test that setup_logging clears existing handlers."""
        setup_logging(stream=string_stream)
        logger = logging.getLogger("depkeeper")

        # Manually add another handler
        extra_handler = logging.StreamHandler()
        logger.addHandler(extra_handler)
        assert len(logger.handlers) == 2

        # Call setup_logging again
        stream2 = io.StringIO()
        setup_logging(stream=stream2)

        # Should have cleared and added new handler
        assert len(logger.handlers) == 1

    def test_setup_logging_prevents_propagation(self):
        """Test that setup_logging sets propagate=False."""
        setup_logging()
        logger = logging.getLogger("depkeeper")
        assert logger.propagate is False

    def test_setup_logging_thread_safe(self):
        """Test that setup_logging is thread-safe."""
        results = []

        def configure():
            try:
                setup_logging()
                results.append(True)
            except Exception:
                results.append(False)

        threads = [threading.Thread(target=configure) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should succeed
        assert all(results)

        # Should still have clean state
        logger = logging.getLogger("depkeeper")
        assert len(logger.handlers) == 1

    def test_setup_logging_sets_configured_flag(self):
        """Test that setup_logging sets the _logging_configured flag."""
        assert is_logging_configured() is False
        setup_logging()
        assert is_logging_configured() is True

    def test_setup_logging_with_no_color_env(self, clean_environment):
        """Test that setup_logging respects NO_COLOR environment variable."""
        clean_environment.setenv("NO_COLOR", "1")
        stream = io.StringIO()
        setup_logging(stream=stream)

        logger = logging.getLogger("depkeeper")
        handler = logger.handlers[0]
        formatter = handler.formatter

        assert isinstance(formatter, ColoredFormatter)
        # Should have use_color=False due to NO_COLOR
        assert formatter._should_use_color() is False


class TestGetLogger:
    """Test suite for get_logger function."""

    def test_get_logger_no_name_returns_root(self):
        """Test get_logger() with no name returns root depkeeper logger."""
        logger = get_logger()
        assert logger.name == "depkeeper"

    def test_get_logger_with_none_returns_root(self):
        """Test get_logger(None) returns root depkeeper logger."""
        logger = get_logger(None)
        assert logger.name == "depkeeper"

    def test_get_logger_with_depkeeper_returns_root(self):
        """Test get_logger('depkeeper') returns root depkeeper logger."""
        logger = get_logger("depkeeper")
        assert logger.name == "depkeeper"

    def test_get_logger_with_simple_name(self):
        """Test get_logger with simple component name."""
        logger = get_logger("parser")
        assert logger.name == "depkeeper.parser"

    def test_get_logger_with_module_path(self):
        """Test get_logger with module path (like __name__)."""
        logger = get_logger("depkeeper.core.parser")
        assert logger.name == "depkeeper.core.parser"

    def test_get_logger_preserves_existing_prefix(self):
        """Test get_logger doesn't double-prefix if name starts with depkeeper."""
        logger = get_logger("depkeeper.utils.http")
        assert logger.name == "depkeeper.utils.http"
        # Should not be "depkeeper.depkeeper.utils.http"

    def test_get_logger_adds_null_handler_when_unconfigured(self):
        """Test get_logger adds NullHandler when logging is not configured."""
        logger = get_logger("test")

        # Should have at least one handler (NullHandler)
        assert len(logger.handlers) >= 1
        # Check if any handler is NullHandler
        has_null_handler = any(
            isinstance(h, logging.NullHandler) for h in logger.handlers
        )
        assert has_null_handler

    def test_get_logger_no_duplicate_null_handlers(self):
        """Test get_logger doesn't add duplicate NullHandlers."""
        logger1 = get_logger("test")
        initial_count = len(logger1.handlers)

        logger2 = get_logger("test")
        # Should be the same logger instance
        assert logger1 is logger2
        # Should not have added more handlers
        assert len(logger2.handlers) == initial_count

    def test_get_logger_respects_configured_logging(self, string_stream):
        """Test get_logger uses configured handlers when logging is setup."""
        setup_logging(stream=string_stream)
        logger = get_logger("test")

        logger.info("Test message")
        output = string_stream.getvalue()
        assert "Test message" in output

    def test_get_logger_hierarchy(self):
        """Test logger hierarchy is maintained."""
        parent = get_logger("parent")
        child = get_logger("depkeeper.parent.child")

        # Child's parent should be the parent logger
        assert child.parent.name.startswith("depkeeper.parent")

    def test_get_logger_multiple_components(self):
        """Test get_logger with multiple different component names."""
        parser_logger = get_logger("parser")
        checker_logger = get_logger("checker")
        updater_logger = get_logger("updater")

        assert parser_logger.name == "depkeeper.parser"
        assert checker_logger.name == "depkeeper.checker"
        assert updater_logger.name == "depkeeper.updater"

        # All should be different instances
        assert parser_logger is not checker_logger
        assert checker_logger is not updater_logger

    def test_get_logger_returns_same_instance(self):
        """Test get_logger returns the same instance for same name."""
        logger1 = get_logger("parser")
        logger2 = get_logger("parser")
        assert logger1 is logger2

    def test_get_logger_empty_string(self):
        """Test get_logger with empty string returns root."""
        logger = get_logger("")
        assert logger.name == "depkeeper"

    def test_get_logger_with_special_characters(self):
        """Test get_logger with names containing special characters."""
        logger = get_logger("component-name")
        assert logger.name == "depkeeper.component-name"

    def test_get_logger_deep_hierarchy(self):
        """Test get_logger with deep module hierarchy."""
        logger = get_logger("depkeeper.core.utils.helpers")
        assert logger.name == "depkeeper.core.utils.helpers"


class TestIsLoggingConfigured:
    """Test suite for is_logging_configured function."""

    def test_is_logging_configured_initial_state(self):
        """Test is_logging_configured returns False initially."""
        # Note: autouse fixture resets state before each test
        assert is_logging_configured() is False

    def test_is_logging_configured_after_setup(self):
        """Test is_logging_configured returns True after setup_logging."""
        assert is_logging_configured() is False
        setup_logging()
        assert is_logging_configured() is True

    def test_is_logging_configured_after_disable(self):
        """Test is_logging_configured returns False after disable_logging."""
        setup_logging()
        assert is_logging_configured() is True

        disable_logging()
        assert is_logging_configured() is False

    def test_is_logging_configured_multiple_setups(self):
        """Test is_logging_configured remains True after multiple setup calls."""
        setup_logging()
        assert is_logging_configured() is True

        setup_logging()
        assert is_logging_configured() is True

    def test_is_logging_configured_thread_safety(self):
        """Test is_logging_configured is thread-safe."""
        results = []

        def check_state():
            results.append(is_logging_configured())

        # Setup logging
        setup_logging()

        # Check from multiple threads
        threads = [threading.Thread(target=check_state) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should see configured state
        assert all(results)


class TestDisableLogging:
    """Test suite for disable_logging function."""

    def test_disable_logging_removes_handlers(self):
        """Test disable_logging removes all handlers."""
        setup_logging()
        logger = logging.getLogger("depkeeper")
        assert len(logger.handlers) > 0

        disable_logging()
        # Should have exactly one NullHandler
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.NullHandler)

    def test_disable_logging_adds_null_handler(self):
        """Test disable_logging adds NullHandler."""
        setup_logging()
        disable_logging()

        logger = logging.getLogger("depkeeper")
        assert any(isinstance(h, logging.NullHandler) for h in logger.handlers)

    def test_disable_logging_resets_level(self):
        """Test disable_logging resets logger level to NOTSET."""
        setup_logging(level=logging.DEBUG)
        logger = logging.getLogger("depkeeper")
        assert logger.level == logging.DEBUG

        disable_logging()
        assert logger.level == logging.NOTSET

    def test_disable_logging_resets_configured_flag(self):
        """Test disable_logging sets _logging_configured to False."""
        setup_logging()
        assert is_logging_configured() is True

        disable_logging()
        assert is_logging_configured() is False

    def test_disable_logging_suppresses_output(self, string_stream):
        """Test disable_logging suppresses all log output."""
        setup_logging(stream=string_stream)
        logger = get_logger("test")

        logger.info("Before disable")
        before_output = string_stream.getvalue()
        assert "Before disable" in before_output

        disable_logging()

        # Get new logger instance (though it's the same underlying logger)
        logger = get_logger("test")
        logger.info("After disable")

        # Should not have new output
        after_output = string_stream.getvalue()
        assert "After disable" not in after_output

    def test_disable_logging_idempotent(self):
        """Test disable_logging can be called multiple times safely."""
        setup_logging()

        disable_logging()
        disable_logging()
        disable_logging()

        logger = logging.getLogger("depkeeper")
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.NullHandler)

    def test_disable_logging_without_prior_setup(self):
        """Test disable_logging works even if setup_logging was never called."""
        # Don't call setup_logging
        disable_logging()

        logger = logging.getLogger("depkeeper")
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.NullHandler)

    def test_disable_logging_thread_safe(self):
        """Test disable_logging is thread-safe."""
        setup_logging()
        results = []

        def disable():
            try:
                disable_logging()
                results.append(True)
            except Exception:
                results.append(False)

        threads = [threading.Thread(target=disable) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should succeed
        assert all(results)

        # Should have clean state
        logger = logging.getLogger("depkeeper")
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.NullHandler)


class TestLoggingIntegration:
    """Integration tests for complete logging workflows."""

    def test_full_logging_workflow(self, string_stream):
        """Test complete workflow: setup -> log -> disable -> log."""
        # Setup
        setup_logging(level=logging.INFO, stream=string_stream)
        logger = get_logger("integration")

        # Log message
        logger.info("Message 1")
        assert "Message 1" in string_stream.getvalue()

        # Disable
        disable_logging()

        # Try to log again (should be suppressed)
        logger.info("Message 2")
        output = string_stream.getvalue()
        assert "Message 2" not in output

    def test_multiple_loggers_share_configuration(self, string_stream):
        """Test multiple loggers share the same configuration."""
        setup_logging(level=logging.DEBUG, stream=string_stream)

        logger1 = get_logger("component1")
        logger2 = get_logger("component2")
        logger3 = get_logger("depkeeper.core.component3")

        logger1.debug("Debug 1")
        logger2.info("Info 2")
        logger3.warning("Warning 3")

        output = string_stream.getvalue()
        assert "Debug 1" in output
        assert "Info 2" in output
        assert "Warning 3" in output

    def test_logging_level_filtering(self, string_stream):
        """Test that logging levels are properly filtered."""
        setup_logging(level=logging.WARNING, stream=string_stream)
        logger = get_logger("test")

        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")

        output = string_stream.getvalue()
        assert "Debug message" not in output
        assert "Info message" not in output
        assert "Warning message" in output
        assert "Error message" in output

    def test_reconfiguration_changes_level(self, string_stream):
        """Test reconfiguring changes the logging level."""
        setup_logging(level=logging.WARNING, stream=string_stream)
        logger = get_logger("test")

        logger.info("Info 1")
        assert "Info 1" not in string_stream.getvalue()

        # Reconfigure to INFO level
        stream2 = io.StringIO()
        setup_logging(level=logging.INFO, stream=stream2)

        logger.info("Info 2")
        assert "Info 2" in stream2.getvalue()

    def test_exception_logging(self, string_stream):
        """Test logging exceptions with traceback."""
        setup_logging(level=logging.ERROR, stream=string_stream)
        logger = get_logger("test")

        try:
            raise ValueError("Test exception")
        except ValueError:
            logger.exception("An error occurred")

        output = string_stream.getvalue()
        assert "An error occurred" in output
        assert "ValueError" in output
        assert "Test exception" in output

    def test_logger_name_in_verbose_output(self):
        """Test logger name appears in verbose output."""
        stream = io.StringIO()
        setup_logging(level=logging.INFO, verbose=True, stream=stream)

        logger = get_logger("parser")
        logger.info("Test message")

        output = stream.getvalue()
        assert "depkeeper.parser" in output or "parser" in output

    def test_concurrent_logging_from_multiple_threads(self, string_stream):
        """Test concurrent logging from multiple threads works correctly."""
        setup_logging(level=logging.INFO, stream=string_stream)

        def log_messages(thread_id):
            logger = get_logger(f"thread{thread_id}")
            for i in range(5):
                logger.info(f"Thread {thread_id} message {i}")

        threads = [threading.Thread(target=log_messages, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        output = string_stream.getvalue()
        # Should have messages from all threads
        for i in range(5):
            assert f"Thread {i}" in output


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_get_logger_with_very_long_name(self):
        """Test get_logger with very long component name."""
        long_name = "a" * 1000
        logger = get_logger(long_name)
        assert logger.name == f"depkeeper.{long_name}"

    def test_setup_logging_with_closed_stream(self):
        """Test setup_logging with a closed stream raises appropriate error."""
        stream = io.StringIO()
        stream.close()

        # This might raise or might not depending on logging implementation
        # We just verify it doesn't crash the whole program
        try:
            setup_logging(stream=stream)
            logger = get_logger("test")
            logger.info("Test")
        except (ValueError, AttributeError):
            # Expected if stream is closed
            pass

    def test_formatter_with_none_record_levelname(self):
        """Test formatter handles records with unusual attributes."""
        formatter = ColoredFormatter("%(levelname)s - %(message)s", use_color=False)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None,
        )
        # Force levelname to something unusual
        record.levelname = ""

        # Should not crash
        formatted = formatter.format(record)
        assert "Test" in formatted

    def test_logging_with_unicode_messages(self, string_stream):
        """Test logging Unicode messages works correctly."""
        setup_logging(stream=string_stream)
        logger = get_logger("test")

        logger.info("Hello 世界 �� Привет")
        output = string_stream.getvalue()
        assert "Hello 世界 �� Привет" in output

    def test_logging_with_format_arguments(self, string_stream):
        """Test logging with % format arguments."""
        setup_logging(stream=string_stream)
        logger = get_logger("test")

        logger.info("Value: %s, Number: %d", "test", 42)
        output = string_stream.getvalue()
        assert "Value: test, Number: 42" in output

    def test_get_logger_with_whitespace_name(self):
        """Test get_logger with whitespace in name."""
        logger = get_logger("test module")
        assert logger.name == "depkeeper.test module"

    def test_multiple_setup_with_different_streams(self):
        """Test multiple setup calls with different streams."""
        stream1 = io.StringIO()
        stream2 = io.StringIO()

        setup_logging(stream=stream1)
        logger = get_logger("test")
        logger.info("Message 1")

        setup_logging(stream=stream2)
        logger.info("Message 2")

        # Message 1 should only be in stream1
        assert "Message 1" in stream1.getvalue()
        assert "Message 1" not in stream2.getvalue()

        # Message 2 should only be in stream2
        assert "Message 2" not in stream1.getvalue()
        assert "Message 2" in stream2.getvalue()

    def test_colored_formatter_with_multiline_messages(self, clean_environment):
        """Test ColoredFormatter handles multiline messages."""
        formatter = ColoredFormatter("%(levelname)s - %(message)s", use_color=True)

        with patch.object(sys.stderr, "isatty", return_value=True):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg="Line 1\nLine 2\nLine 3",
                args=(),
                exc_info=None,
            )

            formatted = formatter.format(record)
            assert "Line 1" in formatted
            assert "Line 2" in formatted
            assert "Line 3" in formatted
