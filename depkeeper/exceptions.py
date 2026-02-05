"""
Custom exception hierarchy for depkeeper.

This module defines structured exception types used across depkeeper.
All exceptions inherit from :class:`DepKeeperError` and support optional
structured metadata via the ``details`` attribute to improve diagnostics
and logging.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional


class DepKeeperError(Exception):
    """Base exception for all depkeeper errors.

    All depkeeper-specific exceptions should inherit from this class.
    It supports structured metadata via ``details`` for richer error
    reporting and debugging.

    Args:
        message: Human-readable error message.
        details: Optional structured metadata describing the error.
    """

    __slots__ = ("message", "details")

    def __init__(
        self,
        message: str,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.message: str = message
        # Internally normalize to a mutable dict
        self.details: MutableMapping[str, Any] = dict(details) if details else {}
        super().__init__(message)

    def __str__(self) -> str:
        if not self.details:
            return self.message
        formatted = ", ".join(f"{k}={v}" for k, v in self.details.items())
        return f"{self.message} ({formatted})"

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, details={dict(self.details)!r})"
        )


def _add_if(details: MutableMapping[str, Any], key: str, value: Any) -> None:
    """Add a key to ``details`` only if ``value`` is not ``None``."""
    if value is not None:
        details[key] = value


def _truncate(text: str, max_length: int = 200) -> str:
    """Truncate long text for safe logging or error reporting."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


class ParseError(DepKeeperError):
    """Raised when a requirements file cannot be parsed.

    Args:
        message: Error description.
        line_number: Line number where parsing failed.
        line_content: Raw content of the problematic line.
        file_path: Path to the file being parsed.
    """

    __slots__ = ("line_number", "line_content", "file_path")

    def __init__(
        self,
        message: str,
        *,
        line_number: Optional[int] = None,
        line_content: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> None:
        details: MutableMapping[str, Any] = {}
        _add_if(details, "line", line_number)
        _add_if(details, "content", line_content)
        _add_if(details, "file", file_path)

        super().__init__(message, details)

        self.line_number = line_number
        self.line_content = line_content
        self.file_path = file_path


class NetworkError(DepKeeperError):
    """Raised when HTTP or network operations fail.

    Args:
        message: Error description.
        url: URL being accessed.
        status_code: HTTP status code, if available.
        response_body: Raw response body, truncated for safety.
    """

    __slots__ = ("url", "status_code", "response_body")

    def __init__(
        self,
        message: str,
        *,
        url: Optional[str] = None,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
    ) -> None:
        details: MutableMapping[str, Any] = {}
        _add_if(details, "url", url)
        _add_if(details, "status_code", status_code)

        if response_body is not None:
            details["response"] = _truncate(response_body)

        super().__init__(message, details)

        self.url = url
        self.status_code = status_code
        self.response_body = response_body


class PyPIError(NetworkError):
    """Raised for failures related to the PyPI API.

    Args:
        message: Error description.
        package_name: Name of the package involved.
        **kwargs: Additional arguments forwarded to ``NetworkError``.
    """

    __slots__ = ("package_name",)

    def __init__(
        self,
        message: str,
        *,
        package_name: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)

        self.package_name = package_name
        if package_name is not None:
            self.details["package"] = package_name


class FileOperationError(DepKeeperError):
    """Raised when file system operations fail.

    Args:
        message: Error description.
        file_path: Path to the file involved.
        operation: Operation being performed (read/write/delete).
        original_error: Original exception that triggered this error.
    """

    __slots__ = ("file_path", "operation", "original_error")

    def __init__(
        self,
        message: str,
        *,
        file_path: Optional[str] = None,
        operation: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ) -> None:
        details: MutableMapping[str, Any] = {}
        _add_if(details, "path", file_path)
        _add_if(details, "operation", operation)
        _add_if(
            details,
            "original_error",
            str(original_error) if original_error else None,
        )

        super().__init__(message, details)

        self.file_path = file_path
        self.operation = operation
        self.original_error = original_error
