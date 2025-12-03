import pytest
import logging

from depkeeper.utils.logger import get_logger


class TestGetLogger:
    """Tests for the get_logger function."""

    def test_get_root_logger_without_name(self):
        """Test getting the root depkeeper logger with no name parameter."""
        logger = get_logger()

        assert logger is not None
        assert isinstance(logger, logging.Logger)
        assert logger.name == "depkeeper"

    def test_get_root_logger_with_none(self):
        """Test getting the root depkeeper logger with None as name."""
        logger = get_logger(None)

        assert logger is not None
        assert isinstance(logger, logging.Logger)
        assert logger.name == "depkeeper"

    def test_get_root_logger_with_depkeeper_name(self):
        """Test getting the root logger with explicit 'depkeeper' name."""
        logger = get_logger("depkeeper")

        assert logger is not None
        assert isinstance(logger, logging.Logger)
        assert logger.name == "depkeeper"

    def test_get_submodule_logger(self):
        """Test getting a submodule logger."""
        logger = get_logger("parser")

        assert logger is not None
        assert isinstance(logger, logging.Logger)
        assert logger.name == "depkeeper.parser"

    def test_get_multiple_submodule_loggers(self):
        """Test getting multiple different submodule loggers."""
        parser_logger = get_logger("parser")
        resolver_logger = get_logger("resolver")
        updater_logger = get_logger("updater")

        assert parser_logger.name == "depkeeper.parser"
        assert resolver_logger.name == "depkeeper.resolver"
        assert updater_logger.name == "depkeeper.updater"

    def test_logger_hierarchy(self):
        """Test that submodule loggers maintain proper hierarchy."""
        root_logger = get_logger()
        sub_logger = get_logger("parser")

        # The parent of the submodule logger should be the root logger
        assert sub_logger.parent.name == "depkeeper"

    def test_same_logger_returned_on_multiple_calls(self):
        """Test that calling get_logger with same name returns the same instance."""
        logger1 = get_logger("parser")
        logger2 = get_logger("parser")

        # Python's logging module returns the same logger instance for the same name
        assert logger1 is logger2

    def test_null_handler_attached_when_no_handlers(self):
        """Test that NullHandler is attached when logger has no handlers."""
        # Create a logger with a unique name to ensure it's fresh
        test_logger_name = "test_unique_module_12345"
        logger = get_logger(test_logger_name)

        # Check that the logger or its parent has at least one handler
        has_handler = bool(logger.handlers) or bool(logger.parent.handlers)
        assert has_handler

    def test_logger_propagation(self):
        """Test that submodule loggers propagate to parent by default."""
        sub_logger = get_logger("parser")

        # By default, propagate should be True
        assert sub_logger.propagate is True

    def test_empty_string_name(self):
        """Test getting logger with empty string returns root logger."""
        logger = get_logger("")

        assert logger.name == "depkeeper"

    def test_nested_submodule_logger(self):
        """Test getting logger for nested submodule."""
        logger = get_logger("core.parser")

        assert logger.name == "depkeeper.core.parser"

    def test_logger_with_special_characters_in_name(self):
        """Test getting logger with special characters in name."""
        logger = get_logger("parser_v2")

        assert logger.name == "depkeeper.parser_v2"


class TestLoggerFunctionality:
    """Tests for logger functional behavior."""

    def test_logger_can_log_messages(self):
        """Test that logger can log messages without errors."""
        logger = get_logger("test_module")

        # These should not raise exceptions
        try:
            logger.debug("Debug message")
            logger.info("Info message")
            logger.warning("Warning message")
            logger.error("Error message")
            logger.critical("Critical message")
        except Exception as e:
            pytest.fail(f"Logger raised unexpected exception: {e}")

    def test_logger_level_inheritance(self):
        """Test that submodule logger inherits level from parent."""
        root_logger = get_logger()
        original_level = root_logger.level

        # Set a specific level on root logger
        root_logger.setLevel(logging.WARNING)

        sub_logger = get_logger("test_inheritance")

        # Sublogger should inherit effective level
        assert sub_logger.getEffectiveLevel() == logging.WARNING

        # Restore original level
        root_logger.setLevel(original_level)

    def test_multiple_get_logger_calls_dont_duplicate_handlers(self):
        """Test that multiple calls to get_logger don't create duplicate handlers."""
        unique_name = "test_unique_handlers_67890"

        logger1 = get_logger(unique_name)
        initial_handler_count = len(logger1.handlers)

        logger2 = get_logger(unique_name)
        logger3 = get_logger(unique_name)

        # Handler count should remain the same
        assert len(logger2.handlers) == initial_handler_count
        assert len(logger3.handlers) == initial_handler_count


class TestLoggerEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_logger_with_whitespace_name(self):
        """Test getting logger with whitespace in name."""
        logger = get_logger("module with spaces")

        assert logger.name == "depkeeper.module with spaces"

    def test_logger_with_dots_in_submodule_name(self):
        """Test that dots in name create proper hierarchy."""
        logger = get_logger("a.b.c")

        assert logger.name == "depkeeper.a.b.c"

    def test_logger_returns_logging_logger_type(self):
        """Test that returned object is proper logging.Logger type."""
        logger = get_logger("test")

        assert isinstance(logger, logging.Logger)
        assert hasattr(logger, "debug")
        assert hasattr(logger, "info")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")
        assert hasattr(logger, "critical")

    def test_logger_name_case_sensitivity(self):
        """Test that logger names are case-sensitive."""
        logger_lower = get_logger("parser")
        logger_upper = get_logger("PARSER")

        # These should be different loggers
        assert logger_lower.name == "depkeeper.parser"
        assert logger_upper.name == "depkeeper.PARSER"
        # Note: Python's logging may still return same instance due to name handling

    def test_logger_with_numeric_name(self):
        """Test getting logger with numeric string as name."""
        logger = get_logger("123")

        assert logger.name == "depkeeper.123"

    def test_very_long_logger_name(self):
        """Test getting logger with very long name."""
        long_name = "a" * 1000
        logger = get_logger(long_name)

        assert logger.name == f"depkeeper.{long_name}"
        assert isinstance(logger, logging.Logger)


class TestLoggerIntegration:
    """Integration tests for logger usage patterns."""

    def test_multiple_modules_can_have_independent_loggers(self):
        """Test that different modules can have independent logger configurations."""
        parser_logger = get_logger("parser")
        resolver_logger = get_logger("resolver")
        updater_logger = get_logger("updater")

        # All should be different logger instances
        assert parser_logger.name != resolver_logger.name
        assert resolver_logger.name != updater_logger.name
        assert parser_logger.name != updater_logger.name

    def test_logger_hierarchy_chain(self):
        """Test that logger hierarchy is properly maintained."""
        root = get_logger()
        level1 = get_logger("level1")
        level2 = get_logger("level1.level2")
        level3 = get_logger("level1.level2.level3")

        assert level1.parent.name == "depkeeper"
        assert level2.parent.name == "depkeeper.level1"
        assert level3.parent.name == "depkeeper.level1.level2"

    def test_logger_works_with_structured_logging(self):
        """Test that logger supports structured logging with extra parameter."""
        logger = get_logger("structured")

        try:
            logger.info(
                "Message with context", extra={"user_id": 123, "action": "parse"}
            )
        except Exception as e:
            pytest.fail(f"Structured logging raised exception: {e}")

    def test_logger_exception_logging(self):
        """Test that logger can log exceptions properly."""
        logger = get_logger("exceptions")

        try:
            raise ValueError("Test exception")
        except ValueError:
            # Should not raise an exception
            logger.exception("An error occurred")


class TestLoggerTypeAnnotations:
    """Tests for type annotations and return types."""

    def test_get_logger_returns_logger_type(self):
        """Test that get_logger returns proper Logger type."""
        logger = get_logger()

        assert type(logger).__name__ == "Logger"
        assert isinstance(logger, logging.Logger)

    def test_get_logger_with_optional_parameter(self):
        """Test that None parameter is handled correctly per type hint."""
        logger: logging.Logger = get_logger(None)

        assert isinstance(logger, logging.Logger)

    def test_get_logger_with_string_parameter(self):
        """Test that string parameter is handled correctly per type hint."""
        logger: logging.Logger = get_logger("test")

        assert isinstance(logger, logging.Logger)
