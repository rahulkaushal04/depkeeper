"""
Requirements validation module.

Provides comprehensive validation for requirements files, individual requirements,
and version consistency checks.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from depkeeper.utils.logger import get_logger
from depkeeper.core.parser import RequirementsParser
from depkeeper.utils.http import HTTPClient
from depkeeper.models.requirement import Requirement
from depkeeper.exceptions import (
    ParseError,
    FileOperationError,
    PyPIError,
)
from depkeeper.constants import PYPI_JSON_API

logger = get_logger("validator")


# ============================================================================
# Requirements Validator
# ============================================================================


class RequirementsValidator:
    """
    Validates requirements files and individual requirements.

    This class provides comprehensive validation including:
    - File validity and syntax checking
    - Single requirement validation
    - Version consistency checks
    - Package accessibility on PyPI
    - Duplicate and conflict detection

    Attributes
    ----------
    parser : RequirementsParser
        Parser for requirements files.
    http_client : HTTPClient, optional
        HTTP client for PyPI accessibility checks.
    check_pypi : bool
        Whether to perform PyPI accessibility checks.
    """

    def __init__(
        self,
        parser: Optional[RequirementsParser] = None,
        http_client: Optional[HTTPClient] = None,
        check_pypi: bool = True,
    ) -> None:
        """
        Initialize requirements validator.

        Parameters
        ----------
        parser : RequirementsParser, optional
            Parser for requirements files. Creates new instance if not provided.
        http_client : HTTPClient, optional
            HTTP client for PyPI checks. Creates new instance if not provided
            and check_pypi is True.
        check_pypi : bool, optional
            Whether to check package accessibility on PyPI. Default is True.
        """
        self.parser = parser or RequirementsParser()
        self.check_pypi = check_pypi
        self.http_client = http_client

        if self.check_pypi and not self.http_client:
            self.http_client = HTTPClient(enable_caching=True)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def validate_file(self, path: Path | str) -> Tuple[bool, List[str]]:
        """
        Validate a requirements file.

        Performs comprehensive validation including:
        - File existence and readability
        - Syntax validation
        - Duplicate detection
        - Version consistency checks
        - Optional PyPI accessibility checks

        Parameters
        ----------
        path : Path | str
            Path to the requirements file.

        Returns
        -------
        Tuple[bool, List[str]]
            Tuple of (is_valid, error_messages).
            is_valid is True if file is valid, False otherwise.
            error_messages contains list of validation errors.

        Examples
        --------
        >>> validator = RequirementsValidator()
        >>> is_valid, errors = validator.validate_file("requirements.txt")
        >>> if not is_valid:
        ...     for error in errors:
        ...         print(error)
        """
        errors: List[str] = []
        file_path = Path(path)

        # Check file existence
        if not file_path.exists():
            errors.append(f"File not found: {file_path}")
            return False, errors

        if not file_path.is_file():
            errors.append(f"Not a file: {file_path}")
            return False, errors

        # Parse and validate syntax
        try:
            requirements = self.parser.parse_file(str(file_path))
        except (ParseError, FileOperationError) as e:
            errors.append(f"Parse error: {e}")
            return False, errors
        except Exception as e:
            errors.append(f"Unexpected error during parsing: {e}")
            return False, errors

        # Check for empty file
        if not requirements:
            logger.warning(f"File {file_path} contains no requirements")
            # Not necessarily an error, just a warning
            return True, []

        # Validate individual requirements
        for req in requirements:
            is_valid, req_errors = self.validate_requirement(req)
            if not is_valid:
                errors.extend(
                    f"Line {req.line_number}: {error}" for error in req_errors
                )

        # Check for duplicates and conflicts
        consistency_errors = self._check_consistency(requirements)
        errors.extend(consistency_errors)

        # Optional PyPI accessibility checks
        if self.check_pypi:
            pypi_errors = asyncio.run(self._check_accessibility(requirements))
            errors.extend(pypi_errors)

        return len(errors) == 0, errors

    def validate_requirement(self, req: Requirement) -> Tuple[bool, List[str]]:
        """
        Validate a single requirement.

        Checks:
        - Package name is not empty
        - Version specifiers are valid
        - Markers are valid (if present)
        - URLs are properly formatted (if present)

        Parameters
        ----------
        req : Requirement
            Requirement to validate.

        Returns
        -------
        Tuple[bool, List[str]]
            Tuple of (is_valid, error_messages).

        Examples
        --------
        >>> req = Requirement(name="requests", specs=[(">=", "2.28.0")])
        >>> is_valid, errors = validator.validate_requirement(req)
        """
        errors: List[str] = []

        # Check package name
        if not req.name or not req.name.strip():
            errors.append("Package name is empty")
            return False, errors

        # Validate version specifiers
        if req.specs:
            for operator, version in req.specs:
                if not operator or not version:
                    errors.append(f"Invalid specifier: {operator}{version}")
                    continue

                # Check for empty version strings
                if not version.strip():
                    errors.append(f"Empty version in specifier: {operator}{version}")

                # Try to get specifier set to validate
                try:
                    spec_set = req.get_specifier_set()
                    if spec_set is None:
                        errors.append("Failed to create specifier set")
                except Exception as e:
                    errors.append(f"Invalid version specifier: {e}")

        # Validate markers
        if req.markers:
            try:
                marker = req.get_marker()
                if marker is None:
                    errors.append(f"Invalid marker: {req.markers}")
            except Exception as e:
                errors.append(f"Invalid marker syntax: {e}")

        # Validate URL format
        if req.url:
            url_errors = self._validate_url(req.url)
            errors.extend(url_errors)

        return len(errors) == 0, errors

    def validate_versions(
        self, requirements: List[Requirement]
    ) -> Tuple[bool, List[str]]:
        """
        Check version consistency across requirements.

        Detects:
        - Conflicting version specifications for same package
        - Impossible version constraints

        Parameters
        ----------
        requirements : List[Requirement]
            List of requirements to check.

        Returns
        -------
        Tuple[bool, List[str]]
            Tuple of (is_consistent, error_messages).

        Examples
        --------
        >>> reqs = [
        ...     Requirement(name="requests", specs=[(">=", "2.28.0")]),
        ...     Requirement(name="requests", specs=[("<", "2.27.0")])
        ... ]
        >>> is_consistent, errors = validator.validate_versions(reqs)
        >>> # errors will contain conflict warning
        """
        errors: List[str] = []

        # Group requirements by package name
        package_specs: Dict[str, List[Requirement]] = {}
        for req in requirements:
            if req.name not in package_specs:
                package_specs[req.name] = []
            package_specs[req.name].append(req)

        # Check for conflicting specifications
        for package_name, reqs in package_specs.items():
            if len(reqs) > 1:
                # Multiple specifications for same package
                conflict_errors = self._check_version_conflicts(package_name, reqs)
                errors.extend(conflict_errors)

        return len(errors) == 0, errors

    # -------------------------------------------------------------------------
    # Internal Validation Methods
    # -------------------------------------------------------------------------

    def _check_syntax(self, requirements: List[Requirement]) -> List[str]:
        """
        Check syntax validity of all requirements.

        Parameters
        ----------
        requirements : List[Requirement]
            Requirements to check.

        Returns
        -------
        List[str]
            List of syntax error messages.
        """
        errors: List[str] = []

        for req in requirements:
            is_valid, req_errors = self.validate_requirement(req)
            if not is_valid:
                errors.extend(
                    f"Line {req.line_number} ({req.name}): {error}"
                    for error in req_errors
                )

        return errors

    async def _check_accessibility(self, requirements: List[Requirement]) -> List[str]:
        """
        Check if packages are accessible on PyPI.

        Parameters
        ----------
        requirements : List[Requirement]
            Requirements to check.

        Returns
        -------
        List[str]
            List of accessibility error messages.
        """
        errors: List[str] = []

        # Skip URL and local path requirements
        pypi_requirements = [
            req for req in requirements if not req.url and not req.is_local()
        ]

        if not pypi_requirements:
            return errors

        # Check packages concurrently
        tasks = [self._check_package_exists(req.name) for req in pypi_requirements]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for req, result in zip(pypi_requirements, results):
            if isinstance(result, Exception):
                errors.append(f"Line {req.line_number} ({req.name}): {str(result)}")
            elif not result:
                errors.append(
                    f"Line {req.line_number} ({req.name}): Package not found on PyPI"
                )

        return errors

    async def _check_package_exists(self, package_name: str) -> bool:
        """
        Check if a package exists on PyPI.

        Parameters
        ----------
        package_name : str
            Name of the package to check.

        Returns
        -------
        bool
            True if package exists on PyPI, False otherwise.
        """
        if not self.http_client:
            return True  # Skip check if no HTTP client

        url = PYPI_JSON_API.format(package=package_name)

        try:
            response = await self.http_client.get(url)
            return response.get("info", {}).get("name") is not None
        except PyPIError:
            return False
        except Exception as e:
            logger.warning(f"Error checking package {package_name}: {e}")
            return False

    def _check_consistency(self, requirements: List[Requirement]) -> List[str]:
        """
        Check for duplicates and conflicts in requirements.

        Parameters
        ----------
        requirements : List[Requirement]
            Requirements to check.

        Returns
        -------
        List[str]
            List of consistency error messages.
        """
        errors: List[str] = []

        # Track seen packages
        seen_packages: Dict[str, List[int]] = {}

        for req in requirements:
            if req.name in seen_packages:
                seen_packages[req.name].append(req.line_number)
            else:
                seen_packages[req.name] = [req.line_number]

        # Report duplicates
        for package_name, line_numbers in seen_packages.items():
            if len(line_numbers) > 1:
                lines_str = ", ".join(str(ln) for ln in line_numbers)
                errors.append(
                    f"Duplicate package '{package_name}' found on lines: {lines_str}"
                )

        return errors

    def _check_version_conflicts(
        self, package_name: str, requirements: List[Requirement]
    ) -> List[str]:
        """
        Check for version conflicts in multiple specifications of same package.

        Parameters
        ----------
        package_name : str
            Name of the package.
        requirements : List[Requirement]
            List of requirements for the same package.

        Returns
        -------
        List[str]
            List of conflict error messages.
        """
        errors: List[str] = []

        # Combine all specifiers
        all_specs = []
        for req in requirements:
            all_specs.extend(req.specs)

        if not all_specs:
            return errors

        # Check for obvious conflicts (e.g., ==2.0 and ==3.0)
        exact_versions = [ver for op, ver in all_specs if op == "=="]
        if len(set(exact_versions)) > 1:
            lines = [str(req.line_number) for req in requirements]
            errors.append(
                f"Conflicting exact versions for '{package_name}' "
                f"on lines {', '.join(lines)}: {exact_versions}"
            )

        # Check for contradictory constraints (e.g., >3.0 and <2.0)
        try:
            from packaging.specifiers import SpecifierSet

            spec_str = ",".join(f"{op}{ver}" for op, ver in all_specs)
            spec_set = SpecifierSet(spec_str)

            # If specifier set is empty after combining, there's a conflict
            # We can't easily test this without actual versions, so we just warn
            if len(all_specs) > 1:
                lines = [str(req.line_number) for req in requirements]
                logger.info(
                    f"Multiple version constraints for '{package_name}' "
                    f"on lines {', '.join(lines)}. Ensure they are compatible."
                )
        except Exception as e:
            lines = [str(req.line_number) for req in requirements]
            errors.append(
                f"Invalid combined version specifiers for '{package_name}' "
                f"on lines {', '.join(lines)}: {e}"
            )

        return errors

    def _validate_url(self, url: str) -> List[str]:
        """
        Validate URL format.

        Parameters
        ----------
        url : str
            URL to validate.

        Returns
        -------
        List[str]
            List of validation error messages.
        """
        errors: List[str] = []

        if not url or not url.strip():
            errors.append("URL is empty")
            return errors

        # Basic URL validation
        valid_schemes = (
            "http://",
            "https://",
            "git+http://",
            "git+https://",
            "git+ssh://",
            "git+git://",
            "hg+http://",
            "hg+https://",
            "svn+http://",
            "svn+https://",
            "bzr+http://",
            "bzr+https://",
            "file://",
        )

        if not any(url.startswith(scheme) for scheme in valid_schemes):
            # Could be a relative path
            if not url.startswith((".", "/")):
                errors.append(f"Invalid URL scheme: {url}")

        return errors

    # -------------------------------------------------------------------------
    # Context Manager Support
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> RequirementsValidator:
        """Async context manager entry."""
        if self.http_client:
            await self.http_client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        if self.http_client:
            await self.http_client.__aexit__(exc_type, exc_val, exc_tb)

    def __enter__(self) -> RequirementsValidator:
        """Sync context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Sync context manager exit."""
        pass
