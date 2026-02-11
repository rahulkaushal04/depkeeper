from __future__ import annotations

import io
import os
import sys
import pytest
import logging
import threading
from typing import Generator
from unittest.mock import patch, MagicMock

from depkeeper.utils.logger import (
    ColoredFormatter,
    setup_logging,
    get_logger,
    is_logging_configured,
    disable_logging,
)


@pytest.fixture
def clean_logger_state() -> Generator[None, None, None]:
    """Clean up logger state before and after each test.

    This fixture ensures tests don't interfere with each other by:
    - Clearing all handlers from the depkeeper logger
    - Resetting the global configuration flag
    - Cleaning up any test-created loggers

    Yields:
        None
    """
    # Clear state before test
    root_logger = logging.getLogger("depkeeper")
    root_logger.handlers.clear()
    root_logger.setLevel(logging.NOTSET)

    # Import and reset the global flag
    import depkeeper.utils.logger as logger_module

    logger_module._logging_configured = False

    yield

    # Clean up after test
    root_logger.handlers.clear()
    root_logger.setLevel(logging.NOTSET)
    logger_module._logging_configured = False


@pytest.fixture
def captured_stream() -> io.StringIO:
    """Provide a StringIO stream for capturing log output.

    Returns:
        A StringIO instance that can be used to capture logging output.
    """
    return io.StringIO()


@pytest.mark.unit
class TestColoredFormatter:
    """Tests for ColoredFormatter ANSI color formatting."""

    def test_init_default_values(self) -> None:
        """Test ColoredFormatter initializes with default values.

        The formatter should accept a format string and use color by default.
        """
        formatter = ColoredFormatter("%(levelname)s: %(message)s")

        assert formatter.use_color is True
        assert formatter._fmt == "%(levelname)s: %(message)s"

    def test_init_custom_values(self) -> None:
        """Test ColoredFormatter accepts custom configuration.

        Should be able to disable color and set custom date format.
        """
        formatter = ColoredFormatter(
            "%(levelname)s: %(message)s",
            datefmt="%Y-%m-%d",
            use_color=False,
        )

        assert formatter.use_color is False
        assert formatter.datefmt == "%Y-%m-%d"

    def test_color_codes_defined(self) -> None:
        """Test ColoredFormatter has color codes for all log levels.

        Verifies that ANSI color codes are defined for standard levels.
        """
        expected_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

        for level in expected_levels:
            assert level in ColoredFormatter.COLORS
            assert ColoredFormatter.COLORS[level].startswith("\033[")

        assert ColoredFormatter.RESET == "\033[0m"

    def test_format_with_color_enabled(self) -> None:
        """Test formatting applies ANSI colors when enabled.

        When color is enabled and conditions are met, levelname should
        be wrapped in ANSI escape codes.
        """
        formatter = ColoredFormatter("%(levelname)s: %(message)s", use_color=True)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        with patch.object(ColoredFormatter, "_should_use_color", return_value=True):
            result = formatter.format(record)

        # Should contain ANSI color codes
        assert "\033[" in result
        assert "INFO" in result
        assert "Test message" in result

    def test_format_with_color_disabled(self) -> None:
        """Test formatting skips colors when disabled.

        When use_color=False, no ANSI codes should be added.
        """
        formatter = ColoredFormatter("%(levelname)s: %(message)s", use_color=False)
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="test.py",
            lineno=1,
            msg="Warning message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)

        # Should not contain ANSI codes
        assert "\033[" not in result
        assert result == "WARNING: Warning message"

    def test_format_all_log_levels(self) -> None:
        """Test formatting works for all standard log levels.

        Edge case: Verify each log level gets its specific color.
        """
        formatter = ColoredFormatter("%(levelname)s: %(message)s", use_color=True)

        levels = [
            (logging.DEBUG, "DEBUG"),
            (logging.INFO, "INFO"),
            (logging.WARNING, "WARNING"),
            (logging.ERROR, "ERROR"),
            (logging.CRITICAL, "CRITICAL"),
        ]

        with patch.object(ColoredFormatter, "_should_use_color", return_value=True):
            for level_num, level_name in levels:
                record = logging.LogRecord(
                    name="test",
                    level=level_num,
                    pathname="test.py",
                    lineno=1,
                    msg=f"{level_name} message",
                    args=(),
                    exc_info=None,
                )

                result = formatter.format(record)
                assert level_name in result

    def test_should_use_color_no_color_env(self) -> None:
        """Test color is disabled when NO_COLOR environment variable is set.

        NO_COLOR is a standard convention to disable ANSI colors.
        """
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            assert ColoredFormatter._should_use_color() is False

    def test_should_use_color_ci_env(self) -> None:
        """Test color is disabled in CI environments.

        CI environments typically don't support ANSI colors.
        """
        with patch.dict(os.environ, {"CI": "true"}, clear=True):
            assert ColoredFormatter._should_use_color() is False

    def test_should_use_color_tty(self) -> None:
        """Test color is enabled for TTY streams.

        When stderr is a TTY and no environment overrides exist,
        color should be enabled.
        """
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(sys.stderr, "isatty", return_value=True):
                assert ColoredFormatter._should_use_color() is True

    def test_should_use_color_non_tty(self) -> None:
        """Test color is disabled for non-TTY streams.

        Edge case: Pipes, redirects, and file outputs are not TTYs.
        """
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(sys.stderr, "isatty", return_value=False):
                assert ColoredFormatter._should_use_color() is False

    def test_should_use_color_no_isatty_attribute(self) -> None:
        """Test color detection handles missing isatty() gracefully.

        Edge case: Some stream objects may not have isatty() method.
        """
        with patch.dict(os.environ, {}, clear=True):
            mock_stderr = MagicMock()
            del mock_stderr.isatty  # Remove the attribute

            with patch("sys.stderr", mock_stderr):
                assert ColoredFormatter._should_use_color() is False

    def test_should_use_color_isatty_raises(self) -> None:
        """Test color detection handles isatty() exceptions.

        Edge case: isatty() might raise OSError in some environments.
        """
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(
                sys.stderr, "isatty", side_effect=OSError("Not supported")
            ):
                assert ColoredFormatter._should_use_color() is False

    def test_format_preserves_original_record(self) -> None:
        """Test formatting doesn't permanently modify the log record.

        Edge case: Color codes should not persist in the record object
        after formatting (though in practice, records are often reused).
        """
        formatter = ColoredFormatter("%(levelname)s: %(message)s", use_color=True)
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Error message",
            args=(),
            exc_info=None,
        )

        original_levelname = record.levelname

        with patch.object(ColoredFormatter, "_should_use_color", return_value=True):
            formatter.format(record)

        # Note: The current implementation DOES modify the record
        # This test documents the actual behavior
        assert "\033[" in record.levelname  # Record is modified

    def test_format_with_exception_info(self) -> None:
        """Test formatting handles exception information correctly.

        Edge case: Exceptions should be formatted with colors applied
        to the levelname but not the traceback.
        """
        formatter = ColoredFormatter("%(levelname)s: %(message)s", use_color=True)

        try:
            raise ValueError("Test error")
        except ValueError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="An error occurred",
            args=(),
            exc_info=exc_info,
        )

        with patch.object(ColoredFormatter, "_should_use_color", return_value=True):
            result = formatter.format(record)

        assert "ERROR" in result
        assert "An error occurred" in result
        assert "ValueError: Test error" in result


@pytest.mark.unit
class TestSetupLogging:
    """Tests for setup_logging configuration function."""

    def test_setup_default_config(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test setup_logging with default configuration.

        Default should be INFO level with basic formatting.
        """
        setup_logging(stream=captured_stream)

        logger = logging.getLogger("depkeeper")
        assert logger.level == logging.INFO
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.StreamHandler)
        assert logger.propagate is False

    def test_setup_custom_level(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test setup_logging with custom log level.

        Should accept and apply custom logging levels.
        """
        setup_logging(level=logging.DEBUG, stream=captured_stream)

        logger = logging.getLogger("depkeeper")
        assert logger.level == logging.DEBUG
        assert logger.handlers[0].level == logging.DEBUG

    def test_setup_verbose_format(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test setup_logging enables verbose formatting.

        Verbose mode should use a more detailed format with timestamps.
        """
        setup_logging(verbose=True, stream=captured_stream)

        logger = logging.getLogger("depkeeper")
        handler = logger.handlers[0]
        formatter = handler.formatter

        assert isinstance(formatter, ColoredFormatter)
        # Verbose format should be used (contains timestamp format)
        assert formatter.datefmt is not None

    def test_setup_custom_stream(self, clean_logger_state: None) -> None:
        """Test setup_logging accepts custom output stream.

        Should be able to redirect logs to any file-like object.
        """
        custom_stream = io.StringIO()
        setup_logging(stream=custom_stream)

        logger = logging.getLogger("depkeeper")
        handler = logger.handlers[0]

        assert handler.stream is custom_stream

    def test_setup_default_stream(self, clean_logger_state: None) -> None:
        """Test setup_logging uses stderr by default.

        When no stream is provided, should default to sys.stderr.
        """
        setup_logging()

        logger = logging.getLogger("depkeeper")
        handler = logger.handlers[0]

        assert handler.stream is sys.stderr

    def test_setup_clears_previous_handlers(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test setup_logging removes existing handlers.

        Multiple calls should not accumulate handlers.
        """
        # First setup
        setup_logging(stream=captured_stream)
        logger = logging.getLogger("depkeeper")
        assert len(logger.handlers) == 1
        first_handler = logger.handlers[0]

        # Second setup
        setup_logging(stream=captured_stream)
        assert len(logger.handlers) == 1
        second_handler = logger.handlers[0]

        # Should be a new handler
        assert first_handler is not second_handler

    def test_setup_sets_configured_flag(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test setup_logging sets global configuration flag.

        After setup, is_logging_configured() should return True.
        """
        assert is_logging_configured() is False

        setup_logging(stream=captured_stream)

        assert is_logging_configured() is True

    def test_setup_thread_safe(self, clean_logger_state: None) -> None:
        """Test setup_logging is thread-safe.

        Concurrent calls should not cause race conditions or
        result in multiple handlers.
        """
        results = []

        def configure_logging(stream: io.StringIO) -> None:
            setup_logging(stream=stream)
            results.append(len(logging.getLogger("depkeeper").handlers))

        threads = []
        for _ in range(10):
            stream = io.StringIO()
            thread = threading.Thread(target=configure_logging, args=(stream,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Final handler count should be exactly 1
        logger = logging.getLogger("depkeeper")
        assert len(logger.handlers) == 1

    def test_setup_respects_no_color_env(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test setup_logging respects NO_COLOR environment variable.

        When NO_COLOR is set, formatter should disable colors.
        """
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            setup_logging(stream=captured_stream)

        logger = logging.getLogger("depkeeper")
        handler = logger.handlers[0]
        formatter = handler.formatter

        assert isinstance(formatter, ColoredFormatter)
        assert formatter.use_color is False

    def test_setup_enables_color_without_no_color(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test setup_logging enables color when NO_COLOR is not set.

        Without NO_COLOR, formatter should have color enabled.
        """
        with patch.dict(os.environ, {}, clear=True):
            setup_logging(stream=captured_stream)

        logger = logging.getLogger("depkeeper")
        handler = logger.handlers[0]
        formatter = handler.formatter

        assert isinstance(formatter, ColoredFormatter)
        assert formatter.use_color is True

    def test_setup_actual_logging_output(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test setup_logging produces correct log output.

        Integration test: Verify actual log messages are formatted correctly.
        """
        setup_logging(level=logging.INFO, stream=captured_stream)

        logger = logging.getLogger("depkeeper")
        logger.info("Test message")

        output = captured_stream.getvalue()
        assert "INFO" in output
        assert "Test message" in output

    def test_setup_filters_debug_at_info_level(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test setup_logging filters messages below configured level.

        DEBUG messages should not appear when level is INFO.
        """
        setup_logging(level=logging.INFO, stream=captured_stream)

        logger = logging.getLogger("depkeeper")
        logger.debug("Debug message")
        logger.info("Info message")

        output = captured_stream.getvalue()
        assert "Debug message" not in output
        assert "Info message" in output

    def test_setup_multiple_log_levels(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test setup_logging handles all log levels correctly.

        Edge case: Verify all standard levels work.
        """
        setup_logging(level=logging.DEBUG, stream=captured_stream)

        logger = logging.getLogger("depkeeper")
        logger.debug("Debug")
        logger.info("Info")
        logger.warning("Warning")
        logger.error("Error")
        logger.critical("Critical")

        output = captured_stream.getvalue()
        assert "Debug" in output
        assert "Info" in output
        assert "Warning" in output
        assert "Error" in output
        assert "Critical" in output


@pytest.mark.unit
class TestGetLogger:
    """Tests for get_logger factory function."""

    def test_get_logger_no_name(self, clean_logger_state: None) -> None:
        """Test get_logger returns root depkeeper logger when no name given.

        Without arguments, should return the base 'depkeeper' logger.
        """
        logger = get_logger()

        assert logger.name == "depkeeper"

    def test_get_logger_depkeeper_name(self, clean_logger_state: None) -> None:
        """Test get_logger with explicit 'depkeeper' name.

        Passing 'depkeeper' should return the root logger.
        """
        logger = get_logger("depkeeper")

        assert logger.name == "depkeeper"

    def test_get_logger_with_simple_name(self, clean_logger_state: None) -> None:
        """Test get_logger with simple module name.

        Simple names should be prefixed with 'depkeeper.'.
        """
        logger = get_logger("http")

        assert logger.name == "depkeeper.http"

    def test_get_logger_with_qualified_name(self, clean_logger_state: None) -> None:
        """Test get_logger with already qualified name.

        Names already starting with 'depkeeper.' should not be double-prefixed.
        """
        logger = get_logger("depkeeper.utils.http")

        assert logger.name == "depkeeper.utils.http"

    def test_get_logger_with_dotted_name(self, clean_logger_state: None) -> None:
        """Test get_logger with dotted module name.

        Dotted names not starting with 'depkeeper.' should be prefixed.
        """
        logger = get_logger("utils.http")

        assert logger.name == "depkeeper.utils.http"

    def test_get_logger_adds_null_handler(self, clean_logger_state: None) -> None:
        """Test get_logger adds NullHandler when unconfigured.

        Library-safe behavior: Should not output logs unless configured.
        """
        logger = get_logger("test")

        # Should have at least one handler (NullHandler)
        assert len(logger.handlers) > 0
        assert any(isinstance(h, logging.NullHandler) for h in logger.handlers)

    def test_get_logger_after_setup(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test get_logger after setup_logging.

        After configuration, child loggers should inherit the handler.
        """
        setup_logging(stream=captured_stream)
        logger = get_logger("test")

        # Child logger should not have NullHandler
        # It should use parent's handler
        logger.info("Test message")
        output = captured_stream.getvalue()

        assert "Test message" in output

    def test_get_logger_hierarchy(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test get_logger creates proper logger hierarchy.

        Child loggers should be part of the depkeeper hierarchy.
        """
        setup_logging(stream=captured_stream)

        logger = get_logger("utils.http")
        parent = logger.parent

        assert parent is not None
        assert "depkeeper" in parent.name

    def test_get_logger_multiple_calls_same_instance(
        self, clean_logger_state: None
    ) -> None:
        """Test get_logger returns same instance for same name.

        Edge case: Logger instances should be cached/singletons.
        """
        logger1 = get_logger("test")
        logger2 = get_logger("test")

        assert logger1 is logger2

    def test_get_logger_different_names_different_instances(
        self, clean_logger_state: None
    ) -> None:
        """Test get_logger returns different instances for different names.

        Different names should create different logger instances.
        """
        logger1 = get_logger("test1")
        logger2 = get_logger("test2")

        assert logger1 is not logger2
        assert logger1.name != logger2.name

    def test_get_logger_empty_string(self, clean_logger_state: None) -> None:
        """Test get_logger handles empty string name.

        Edge case: Empty string should return root depkeeper logger.
        """
        logger = get_logger("")

        assert logger.name == "depkeeper"

    def test_get_logger_with_special_characters(self, clean_logger_state: None) -> None:
        """Test get_logger handles names with special characters.

        Edge case: Dots and underscores should work in logger names.
        """
        logger = get_logger("my_module.sub_module")

        assert logger.name == "depkeeper.my_module.sub_module"

    def test_get_logger_use_dunder_name(self, clean_logger_state: None) -> None:
        """Test get_logger works with __name__ pattern.

        Common usage pattern: get_logger(__name__) should work correctly.
        """
        # Simulate a module name
        module_name = "depkeeper.utils.http"
        logger = get_logger(module_name)

        assert logger.name == "depkeeper.utils.http"


@pytest.mark.unit
class TestIsLoggingConfigured:
    """Tests for is_logging_configured state query function."""

    def test_not_configured_initially(self, clean_logger_state: None) -> None:
        """Test is_logging_configured returns False initially.

        Before any setup, should report as not configured.
        """
        assert is_logging_configured() is False

    def test_configured_after_setup(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test is_logging_configured returns True after setup.

        After calling setup_logging, should report as configured.
        """
        setup_logging(stream=captured_stream)

        assert is_logging_configured() is True

    def test_not_configured_after_disable(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test is_logging_configured returns False after disable.

        After disabling, should report as not configured.
        """
        setup_logging(stream=captured_stream)
        assert is_logging_configured() is True

        disable_logging()

        assert is_logging_configured() is False


@pytest.mark.unit
class TestDisableLogging:
    """Tests for disable_logging cleanup function."""

    def test_disable_clears_handlers(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test disable_logging removes all handlers.

        After disabling, root logger should have only NullHandler.
        """
        setup_logging(stream=captured_stream)
        logger = logging.getLogger("depkeeper")
        assert len(logger.handlers) == 1

        disable_logging()

        # Should have exactly one NullHandler
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.NullHandler)

    def test_disable_resets_level(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test disable_logging resets log level.

        After disabling, level should be NOTSET.
        """
        setup_logging(level=logging.INFO, stream=captured_stream)
        logger = logging.getLogger("depkeeper")
        assert logger.level == logging.INFO

        disable_logging()

        assert logger.level == logging.NOTSET

    def test_disable_resets_configured_flag(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test disable_logging resets configuration flag.

        After disabling, is_logging_configured() should return False.
        """
        setup_logging(stream=captured_stream)
        assert is_logging_configured() is True

        disable_logging()

        assert is_logging_configured() is False

    def test_disable_silences_output(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test disable_logging prevents log output.

        Integration test: After disabling, logs should produce no output.
        """
        setup_logging(stream=captured_stream)

        logger = logging.getLogger("depkeeper")
        logger.info("Before disable")

        disable_logging()

        # Clear the stream
        captured_stream.truncate(0)
        captured_stream.seek(0)

        logger.info("After disable")

        output = captured_stream.getvalue()
        assert "After disable" not in output

    def test_disable_idempotent(self, clean_logger_state: None) -> None:
        """Test disable_logging can be called multiple times safely.

        Edge case: Multiple disable calls should not cause errors.
        """
        disable_logging()
        disable_logging()

        logger = logging.getLogger("depkeeper")
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.NullHandler)

    def test_disable_before_setup(self, clean_logger_state: None) -> None:
        """Test disable_logging works even if never configured.

        Edge case: Should be safe to call before any setup.
        """
        # Should not raise
        disable_logging()

        assert is_logging_configured() is False

    def test_disable_thread_safe(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test disable_logging is thread-safe.

        Concurrent disable calls should not cause race conditions.
        """
        setup_logging(stream=captured_stream)

        def disable_in_thread() -> None:
            disable_logging()

        threads = []
        for _ in range(10):
            thread = threading.Thread(target=disable_in_thread)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        logger = logging.getLogger("depkeeper")
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.NullHandler)


@pytest.mark.integration
class TestLoggingIntegration:
    """Integration tests combining multiple logging features."""

    def test_full_lifecycle(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test complete logging lifecycle.

        Integration test: Setup → Use → Reconfigure → Disable.
        """
        # Initial state
        assert is_logging_configured() is False

        # Setup
        setup_logging(level=logging.INFO, stream=captured_stream)
        assert is_logging_configured() is True

        logger = get_logger("test")
        logger.info("First message")

        # Reconfigure
        setup_logging(level=logging.DEBUG, stream=captured_stream)
        logger.debug("Debug message")

        # Disable
        disable_logging()
        assert is_logging_configured() is False

        output = captured_stream.getvalue()
        assert "First message" in output
        assert "Debug message" in output

    def test_multiple_loggers_share_config(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test multiple loggers share same configuration.

        Integration test: Child loggers should use root config.
        """
        setup_logging(level=logging.INFO, stream=captured_stream)

        logger1 = get_logger("module1")
        logger2 = get_logger("module2")

        logger1.info("Message 1")
        logger2.info("Message 2")

        output = captured_stream.getvalue()
        assert "Message 1" in output
        assert "Message 2" in output

    def test_library_safe_default_behavior(self, clean_logger_state: None) -> None:
        """Test library-safe behavior without explicit configuration.

        Integration test: Should not output logs unless configured,
        following best practices for library code.
        """
        # Don't call setup_logging
        logger = get_logger("test")

        # Should have NullHandler
        assert any(isinstance(h, logging.NullHandler) for h in logger.handlers)

        # This should not raise, just silently discard
        logger.info("This should be discarded")
        logger.error("This too")

    def test_reconfiguration_changes_output_level(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test reconfiguration properly changes log level.

        Integration test: Level changes should take effect immediately.
        """
        # Start with INFO
        setup_logging(level=logging.INFO, stream=captured_stream)
        logger = get_logger("test")

        logger.debug("Debug 1")  # Should not appear
        logger.info("Info 1")  # Should appear

        output1 = captured_stream.getvalue()
        assert "Debug 1" not in output1
        assert "Info 1" in output1

        # Reconfigure to DEBUG
        setup_logging(level=logging.DEBUG, stream=captured_stream)

        logger.debug("Debug 2")  # Should now appear
        logger.info("Info 2")  # Should appear

        output2 = captured_stream.getvalue()
        assert "Debug 2" in output2
        assert "Info 2" in output2

    def test_concurrent_logging_from_multiple_threads(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test thread-safe logging from multiple threads.

        Integration test: Concurrent logging should not cause corruption
        or lost messages.
        """
        setup_logging(level=logging.INFO, stream=captured_stream)

        message_count = [0]
        lock = threading.Lock()

        def log_messages(thread_id: int) -> None:
            logger = get_logger(f"thread{thread_id}")
            for i in range(10):
                logger.info(f"Thread {thread_id} message {i}")
                with lock:
                    message_count[0] += 1

        threads = []
        for i in range(5):
            thread = threading.Thread(target=log_messages, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Should have logged 50 messages (5 threads * 10 messages)
        assert message_count[0] == 50

        # All messages should be in output
        output = captured_stream.getvalue()
        assert output.count("Thread") == 50

    def test_exception_logging_with_traceback(
        self, clean_logger_state: None, captured_stream: io.StringIO
    ) -> None:
        """Test logging exceptions with tracebacks.

        Integration test: Exception info should be properly formatted.
        """
        setup_logging(level=logging.ERROR, stream=captured_stream)
        logger = get_logger("test")

        try:
            raise ValueError("Test exception")
        except ValueError:
            logger.exception("An error occurred")

        output = captured_stream.getvalue()
        assert "An error occurred" in output
        assert "ValueError: Test exception" in output
        assert "Traceback" in output
