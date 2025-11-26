"""
Custom exception classes for depkeeper.

All errors in the application inherit from `DepKeeperError`, which
provides consistent formatting, structured error details, and safe
string representations for CLI and logs.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# =============================================================================
# Base Error
# =============================================================================


class DepKeeperError(Exception):
    """Base exception for all depkeeper errors.

    Includes structured metadata (`details`) so the CLI, reporters,
    and logs can format consistent and actionable error messages.
    """

    __slots__ = ("message", "details")

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        self.message: str = message
        self.details: Dict[str, Any] = details or {}
        super().__init__(message)

    # Human-friendly output
    def __str__(self) -> str:
        if not self.details:
            return self.message
        formatted = ", ".join(f"{k}={v}" for k, v in self.details.items())
        return f"{self.message} ({formatted})"

    # Debug-friendly output
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(message={self.message!r}, details={self.details!r})"


# =============================================================================
# Helper Functions
# =============================================================================


def _add_if(details: Dict[str, Any], key: str, value: Any) -> None:
    """Add a field to `details` only if value is not None."""
    if value is not None:
        details[key] = value


def _truncate(text: str, length: int = 200) -> str:
    """Truncate overly long text for safer logging."""
    return text if len(text) <= length else text[:length] + "..."


# =============================================================================
# Parse Errors
# =============================================================================


class ParseError(DepKeeperError):
    """Raised when a requirements file cannot be parsed."""

    __slots__ = ("line_number", "line_content", "file_path")

    def __init__(
        self,
        message: str,
        line_number: Optional[int] = None,
        line_content: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> None:
        details: Dict[str, Any] = {}
        _add_if(details, "line", line_number)
        _add_if(details, "content", line_content)
        _add_if(details, "file", file_path)

        super().__init__(message, details)

        self.line_number = line_number
        self.line_content = line_content
        self.file_path = file_path


# =============================================================================
# Validation Errors
# =============================================================================


class ValidationError(DepKeeperError):
    """Raised when validation of fields or data structures fails."""

    __slots__ = ("field", "value")

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        value: Optional[Any] = None,
    ) -> None:
        details: Dict[str, Any] = {}
        _add_if(details, "field", field)
        _add_if(details, "value", value)

        super().__init__(message, details)

        self.field = field
        self.value = value


# =============================================================================
# Network & PyPI Errors
# =============================================================================


class NetworkError(DepKeeperError):
    """Raised when HTTP or networking operations fail."""

    __slots__ = ("url", "status_code", "response_body")

    def __init__(
        self,
        message: str,
        url: Optional[str] = None,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
    ) -> None:
        details: Dict[str, Any] = {}
        _add_if(details, "url", url)
        _add_if(details, "status_code", status_code)
        if response_body is not None:
            details["response"] = _truncate(response_body)

        super().__init__(message, details)

        self.url = url
        self.status_code = status_code
        self.response_body = response_body


class PyPIError(NetworkError):
    """Raised specifically for PyPI API failures."""

    __slots__ = ("package_name",)

    def __init__(
        self,
        message: str,
        package_name: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.package_name = package_name
        if package_name is not None:
            self.details["package"] = package_name


# =============================================================================
# Conflict Errors
# =============================================================================


class ConflictError(DepKeeperError):
    """Raised when dependency version conflicts are detected."""

    __slots__ = ("package_name", "constraints", "conflicting_packages")

    def __init__(
        self,
        message: str,
        package_name: Optional[str] = None,
        constraints: Optional[list[str]] = None,
        conflicting_packages: Optional[list[str]] = None,
    ) -> None:
        details: Dict[str, Any] = {}
        _add_if(details, "package", package_name)
        _add_if(details, "constraints", ", ".join(constraints) if constraints else None)
        _add_if(
            details,
            "conflicting_with",
            ", ".join(conflicting_packages) if conflicting_packages else None,
        )

        super().__init__(message, details)

        self.package_name = package_name
        self.constraints = constraints or []
        self.conflicting_packages = conflicting_packages or []


# =============================================================================
# Cache Errors
# =============================================================================


class CacheError(DepKeeperError):
    """Raised when cache read/write operations fail."""

    __slots__ = ("cache_key", "operation")

    def __init__(
        self,
        message: str,
        cache_key: Optional[str] = None,
        operation: Optional[str] = None,
    ) -> None:
        details: Dict[str, Any] = {}
        _add_if(details, "key", cache_key)
        _add_if(details, "operation", operation)

        super().__init__(message, details)

        self.cache_key = cache_key
        self.operation = operation


# =============================================================================
# File Operation Errors
# =============================================================================


class FileOperationError(DepKeeperError):
    """Raised when accessing or modifying files fails."""

    __slots__ = ("file_path", "operation", "original_error")

    def __init__(
        self,
        message: str,
        file_path: Optional[str] = None,
        operation: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ) -> None:
        details: Dict[str, Any] = {}
        _add_if(details, "path", file_path)
        _add_if(details, "operation", operation)
        _add_if(
            details, "original_error", str(original_error) if original_error else None
        )

        super().__init__(message, details)

        self.file_path = file_path
        self.operation = operation
        self.original_error = original_error


# =============================================================================
# Configuration Errors
# =============================================================================


class ConfigurationError(DepKeeperError):
    """Raised when depkeeper configuration files contain invalid values."""

    __slots__ = ("config_file", "config_key")

    def __init__(
        self,
        message: str,
        config_file: Optional[str] = None,
        config_key: Optional[str] = None,
    ) -> None:
        details: Dict[str, Any] = {}
        _add_if(details, "config_file", config_file)
        _add_if(details, "key", config_key)

        super().__init__(message, details)

        self.config_file = config_file
        self.config_key = config_key


# =============================================================================
# Security Errors
# =============================================================================


class SecurityVulnerabilityError(DepKeeperError):
    """Raised when known security vulnerabilities are detected."""

    __slots__ = ("package_name", "version", "cve_id", "severity")

    def __init__(
        self,
        message: str,
        package_name: Optional[str] = None,
        version: Optional[str] = None,
        cve_id: Optional[str] = None,
        severity: Optional[str] = None,
    ) -> None:
        details: Dict[str, Any] = {}
        _add_if(details, "package", package_name)
        _add_if(details, "version", version)
        _add_if(details, "cve", cve_id)
        _add_if(details, "severity", severity)

        super().__init__(message, details)

        self.package_name = package_name
        self.version = version
        self.cve_id = cve_id
        self.severity = severity
