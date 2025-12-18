"""Custom exception classes for depkeeper.

All errors in the application inherit from DepKeeperError, which provides
consistent formatting, structured error details, and safe string
representations for CLI and logs.

Currently Used Exceptions
-------------------------
- DepKeeperError: Base exception for all depkeeper errors
- ParseError: Requirements file parsing failures
- NetworkError: HTTP/networking operation failures
- PyPIError: PyPI API-specific failures
- FileOperationError: File access/modification failures
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# =============================================================================
# Base Error
# =============================================================================


class DepKeeperError(Exception):
    """Base exception for all depkeeper errors.

    All custom exceptions in depkeeper inherit from this base class, providing
    consistent error handling and structured error information throughout the
    application. The class includes a details dictionary for storing additional
    context that can be used by CLI, logging, and error reporting systems.

    Parameters
    ----------
    message : str
        Human-readable error message describing what went wrong.
    details : dict, optional
        Additional structured information about the error. Common keys include
        file paths, line numbers, package names, URLs, etc. Default is None
        (empty dict).

    Attributes
    ----------
    message : str
        The error message.
    details : dict
        Structured error metadata.

    Examples
    --------
    Basic error with message only:

        >>> raise DepKeeperError("Operation failed")
        Traceback (most recent call last):
            ...
        DepKeeperError: Operation failed

    Error with additional details:

        >>> raise DepKeeperError(
        ...     "Failed to parse file",
        ...     details={"file": "requirements.txt", "line": 42}
        ... )
        Traceback (most recent call last):
            ...
        DepKeeperError: Failed to parse file (file=requirements.txt, line=42)

    Catching and inspecting errors:

        >>> try:
        ...     raise DepKeeperError("Error", details={"code": 123})
        ... except DepKeeperError as e:
        ...     print(e.message)
        ...     print(e.details)
        Error
        {'code': 123}

    Notes
    -----
    The __str__ method formats the error for user display, including details
    in parentheses. The __repr__ method provides a detailed representation
    suitable for debugging and logging.

    All depkeeper exceptions use __slots__ for memory efficiency and to
    prevent accidental attribute assignment.

    See Also
    --------
    ParseError : Requirements file parsing errors
    NetworkError : HTTP/networking errors
    PyPIError : PyPI API-specific errors
    FileOperationError : File I/O errors
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
    """Add a field to details dict only if value is not None.

    Helper function for conditionally populating error details dictionaries.
    Prevents cluttering error details with None values, making error messages
    cleaner and more readable.

    Parameters
    ----------
    details : dict
        Dictionary to add the field to (modified in-place).
    key : str
        Key name for the field.
    value : Any
        Value to add. Only added if not None.

    Returns
    -------
    None
        Dictionary is modified in-place.

    Examples
    --------
    >>> details = {}
    >>> _add_if(details, "name", "package")
    >>> _add_if(details, "version", None)
    >>> print(details)
    {'name': 'package'}
    """
    if value is not None:
        details[key] = value


def _truncate(text: str, length: int = 200) -> str:
    """Truncate overly long text for safer logging and error messages.

    Limits text length to prevent overwhelming log files and error outputs
    with very long strings (e.g., large HTTP response bodies). Adds ellipsis
    to indicate truncation.

    Parameters
    ----------
    text : str
        Text to potentially truncate.
    length : int, optional
        Maximum length before truncation. Default is 200 characters.

    Returns
    -------
    str
        Original text if under limit, or truncated text with "..." appended.

    Examples
    --------
    >>> _truncate("short text")
    'short text'

    >>> _truncate("a" * 250)
    'aaaaaaa...aaaa...'

    >>> _truncate("a" * 50, length=10)
    'aaaaaaaaaa...'
    """
    return text if len(text) <= length else text[:length] + "..."


# =============================================================================
# Parse Errors
# =============================================================================


class ParseError(DepKeeperError):
    """Raised when a requirements file cannot be parsed.

    This exception indicates that depkeeper encountered invalid syntax or
    unsupported constructs while parsing a requirements.txt file or related
    dependency specification file.

    Parameters
    ----------
    message : str
        Description of the parsing error.
    line_number : int, optional
        Line number where the error occurred (1-indexed). Default is None.
    line_content : str, optional
        Content of the problematic line. Default is None.
    file_path : str, optional
        Path to the file being parsed. Default is None.

    Attributes
    ----------
    message : str
        Error description.
    line_number : int or None
        Line number of error.
    line_content : str or None
        Problematic line text.
    file_path : str or None
        File path.
    details : dict
        Contains 'line', 'content', and 'file' keys if provided.

    Examples
    --------
    Basic parse error:

        >>> raise ParseError("Invalid version specifier")

    Error with line information:

        >>> raise ParseError(
        ...     "Invalid package name",
        ...     line_number=10,
        ...     line_content="123invalid==1.0.0",
        ...     file_path="requirements.txt"
        ... )

    Catching and handling:

        >>> try:
        ...     parser.parse_file("requirements.txt")
        ... except ParseError as e:
        ...     print(f"Error on line {e.line_number}: {e.message}")
        ...     print(f"Content: {e.line_content}")

    See Also
    --------
    depkeeper.core.parser.RequirementsParser : Main parsing implementation
    """

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
# Network & PyPI Errors
# =============================================================================


class NetworkError(DepKeeperError):
    """Raised when HTTP or networking operations fail.

    This exception covers all network-related failures including connection
    errors, timeouts, DNS failures, SSL issues, and HTTP errors (4xx/5xx
    status codes except 404 which raises PyPIError).

    Parameters
    ----------
    message : str
        Description of the network error.
    url : str, optional
        URL that was being accessed when the error occurred. Default is None.
    status_code : int, optional
        HTTP status code if applicable (e.g., 500, 503). Default is None.
    response_body : str, optional
        Response body from the server. Will be truncated to 200 chars in
        details. Default is None.

    Attributes
    ----------
    message : str
        Error description.
    url : str or None
        Target URL.
    status_code : int or None
        HTTP status code.
    response_body : str or None
        Full response body.
    details : dict
        Contains 'url', 'status_code', and 'response' (truncated) if provided.

    Examples
    --------
    Connection timeout:

        >>> raise NetworkError(
        ...     "Connection timeout",
        ...     url="https://pypi.org/pypi/requests/json"
        ... )

    HTTP error with status:

        >>> raise NetworkError(
        ...     "Server error",
        ...     url="https://pypi.org/pypi/package/json",
        ...     status_code=503,
        ...     response_body="Service temporarily unavailable"
        ... )

    Catching network errors:

        >>> try:
        ...     await client.get("https://pypi.org/...")
        ... except NetworkError as e:
        ...     print(f"Failed to fetch {e.url}: {e.status_code}")

    See Also
    --------
    PyPIError : Subclass for PyPI-specific errors (404s)
    depkeeper.utils.http.HTTPClient : HTTP client implementation
    """

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
    """Raised specifically for PyPI API failures.

    A specialized NetworkError for PyPI-specific failures, primarily used for
    404 Not Found errors when a package doesn't exist on PyPI. Inherits all
    NetworkError functionality with additional package name context.

    Parameters
    ----------
    message : str
        Description of the PyPI error.
    package_name : str, optional
        Name of the package that caused the error. Default is None.
    **kwargs : Any
        Additional arguments passed to NetworkError (url, status_code,
        response_body).

    Attributes
    ----------
    message : str
        Error description.
    package_name : str or None
        Package name.
    url : str or None
        PyPI API URL (inherited from NetworkError).
    status_code : int or None
        HTTP status code (inherited from NetworkError).
    response_body : str or None
        Response body (inherited from NetworkError).
    details : dict
        Contains 'package' plus inherited NetworkError details.

    Examples
    --------
    Package not found:

        >>> raise PyPIError(
        ...     "Package not found",
        ...     package_name="nonexistent-package",
        ...     url="https://pypi.org/pypi/nonexistent-package/json",
        ...     status_code=404
        ... )

    Handling PyPI errors:

        >>> try:
        ...     package_info = await checker.check_package("invalid")
        ... except PyPIError as e:
        ...     print(f"Package '{e.package_name}' not found on PyPI")

    See Also
    --------
    NetworkError : Parent class for all network errors
    depkeeper.core.checker.VersionChecker : Uses PyPIError for missing packages
    """

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
# File Operation Errors
# =============================================================================


class FileOperationError(DepKeeperError):
    """Raised when accessing or modifying files fails.

    This exception covers all file system operations including reading,
    writing, creating, deleting, and permission errors. Commonly raised
    when requirements files can't be accessed or backup operations fail.

    Parameters
    ----------
    message : str
        Description of the file operation error.
    file_path : str, optional
        Path to the file involved in the error. Default is None.
    operation : str, optional
        Type of operation that failed (e.g., 'read', 'write', 'delete').
        Default is None.
    original_error : Exception, optional
        Original exception that caused this error (e.g., IOError,
        PermissionError). Will be converted to string in details.
        Default is None.

    Attributes
    ----------
    message : str
        Error description.
    file_path : str or None
        File path.
    operation : str or None
        Operation type.
    original_error : Exception or None
        Original exception.
    details : dict
        Contains 'path', 'operation', and 'original_error' (as string)
        if provided.

    Examples
    --------
    File not found:

        >>> raise FileOperationError(
        ...     "File does not exist",
        ...     file_path="requirements.txt",
        ...     operation="read"
        ... )

    Permission denied with original error:

        >>> try:
        ...     with open("/protected/file.txt", "w") as f:
        ...         f.write("data")
        ... except PermissionError as e:
        ...     raise FileOperationError(
        ...         "Cannot write to file",
        ...         file_path="/protected/file.txt",
        ...         operation="write",
        ...         original_error=e
        ...     )

    Handling file errors:

        >>> try:
        ...     parser.parse_file("requirements.txt")
        ... except FileOperationError as e:
        ...     print(f"Failed to {e.operation} {e.file_path}")
        ...     if e.original_error:
        ...         print(f"Reason: {e.original_error}")

    See Also
    --------
    depkeeper.utils.filesystem : File operation utilities
    depkeeper.core.parser.RequirementsParser : File parsing operations
    """

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
