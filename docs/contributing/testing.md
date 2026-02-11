---
title: Testing
description: Comprehensive testing guidelines for depkeeper contributors
---

# Testing

Comprehensive testing guidelines for depkeeper contributors.
This guide covers running tests locally, writing test cases, and maintaining code quality.

!!! abstract "Goals of the Test Suite"

    - **Correctness** - Ensure features work as intended
    - **Regression Prevention** - Catch bugs before they ship
    - **Safe Refactoring** - Confidently improve code structure
    - **Documentation** - Tests serve as executable specifications

---

## Quick Start

=== "Basic Commands"

    ```bash
    # Run all tests
    pytest

    # Run with verbose output
    pytest -v

    # Run with coverage report
    pytest --cov=depkeeper --cov-report=html
    ```

=== "Targeted Testing"

    ```bash
    # Run specific test file
    pytest tests/unit/test_parser.py

    # Run specific test function
    pytest tests/unit/test_parser.py::test_parse_simple_requirement

    # Run tests matching a pattern
    pytest -k "parser"

    # Run tests by marker
    pytest -m "unit"
    ```

=== "Development Mode"

    ```bash
    # Stop on first failure
    pytest -x

    # Show local variables on failure
    pytest -l

    # Run failed tests first
    pytest --ff

    # Watch mode (requires pytest-watch)
    ptw -- -x
    ```

---

## Test Organization

The test suite is organized by scope and responsibility:

```
tests/
├── conftest.py           # Shared fixtures and pytest configuration
├── fixtures/             # Test data files
│   ├── requirements/     # Sample requirements.txt files
│   └── responses/        # Mock API response data
├── unit/                 # Unit tests (fast, isolated)
│   ├── core/             # Core module tests
│   ├── models/           # Data model tests
│   └── utils/            # Utility function tests
├── integration/          # Integration tests (component interaction)
└── e2e/                  # End-to-end tests (CLI workflows)
```

### Test Categories

| Category        | Scope                 | Speed        | Dependencies     |
| --------------- | --------------------- | ------------ | ---------------- |
| **Unit**        | Single function/class | Fast (<1ms)  | Fully mocked     |
| **Integration** | Multiple components   | Medium (<1s) | Partially mocked |
| **End-to-End**  | Full CLI workflow     | Slow (<10s)  | Minimal mocking  |

!!! tip "Test Distribution Rule"

    Follow the testing pyramid: approximately 70% unit, 20% integration, 10% end-to-end tests.

---

## Writing Tests

### Anatomy of a Good Test

Every test should follow the **Arrange-Act-Assert** pattern:

```python title="tests/unit/core/test_parser.py" hl_lines="6 9 12-13"
from depkeeper.core.parser import RequirementsParser


def test_parse_simple_requirement():
    """Parser correctly handles a pinned version."""
    # Arrange: Set up test data and dependencies
    parser = RequirementsParser()

    # Act: Execute the code under test
    result = parser.parse_line("requests==2.28.0", line_number=1)

    # Assert: Verify the expected outcome
    assert result.name == "requests"
    assert result.specs == [("==", "2.28.0")]
```

!!! info "Test Naming Convention"

    Use descriptive names: `test_<what>_<condition>_<expected>`. For example:

    - `test_parse_line_with_extras_returns_extras_list`
    - `test_checker_network_timeout_raises_timeout_error`

### Using Fixtures

Fixtures provide reusable test setup. Define them in `conftest.py`:

=== "conftest.py"

    ```python title="tests/conftest.py"
    import pytest
    from pathlib import Path
    from depkeeper.core.parser import RequirementsParser


    @pytest.fixture
    def parser() -> RequirementsParser:
        """Provide a fresh parser instance."""
        return RequirementsParser()


    @pytest.fixture
    def sample_requirements_file(tmp_path: Path) -> Path:
        """Create a temporary requirements file with common packages."""
        content = """\
    # Production dependencies
    requests>=2.28.0
    flask==2.3.0
    click>=8.0.0

    # Development tools
    pytest>=7.0.0
    """
        file_path = tmp_path / "requirements.txt"
        file_path.write_text(content)
        return file_path


    @pytest.fixture
    def complex_requirements_file(tmp_path: Path) -> Path:
        """Create a requirements file with advanced syntax."""
        content = """\
    requests[security,socks]>=2.28.0,<3.0
    Django>=4.0; python_version >= '3.10'
    -e git+https://github.com/user/repo.git@main#egg=package
    ./local-package
    """
        file_path = tmp_path / "requirements.txt"
        file_path.write_text(content)
        return file_path
    ```

=== "Using Fixtures"

    ```python title="tests/unit/core/test_parser.py"
    def test_parse_file_counts_packages(parser, sample_requirements_file):
        """Parser extracts all package requirements from file."""
        requirements = parser.parse_file(sample_requirements_file)

        # Should find 4 packages (comments excluded)
        assert len(requirements) == 4
        assert requirements[0].name == "requests"


    def test_parse_complex_syntax(parser, complex_requirements_file):
        """Parser handles advanced requirement syntax."""
        requirements = parser.parse_file(complex_requirements_file)

        # Check extras are parsed
        assert "security" in requirements[0].extras
        assert "socks" in requirements[0].extras

        # Check environment markers
        assert requirements[1].markers is not None
    ```

### Fixture Scopes

Choose the right scope to balance isolation and performance:

```python title="tests/conftest.py"
import pytest


@pytest.fixture(scope="function")  # Default: fresh for each test
def parser():
    return RequirementsParser()


@pytest.fixture(scope="module")  # Shared within a test file
def mock_pypi_responses():
    return load_json_fixtures("responses/pypi/")


@pytest.fixture(scope="session")  # Shared across entire test run
def docker_services():
    # Expensive setup like containers
    yield start_services()
    cleanup_services()
```

!!! warning "Fixture Scope Gotchas"

    - Avoid mutating module or session scoped fixtures
    - Use function scope when tests modify fixture state
    - Session-scoped fixtures must be thread-safe for parallel tests

---

## Async Testing

depkeeper uses async I/O for network operations. Test async code with pytest-asyncio:

```python title="tests/unit/core/test_checker.py" hl_lines="4"
import pytest


@pytest.mark.asyncio
async def test_fetch_package_info():
    """VersionChecker retrieves package data from PyPI."""
    from depkeeper.core import PyPIDataStore, VersionChecker
    from depkeeper.utils import HTTPClient

    async with HTTPClient() as http:
        store = PyPIDataStore(http)
        checker = VersionChecker(data_store=store)

        pkg = await checker.get_package_info("requests")

        assert pkg.name == "requests"
        assert pkg.latest_version is not None
```

### Async Fixtures

```python title="tests/conftest.py"
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def http_client():
    """Provide an async HTTP client with automatic cleanup."""
    from depkeeper.utils import HTTPClient

    async with HTTPClient() as client:
        yield client


@pytest_asyncio.fixture
async def checker(http_client):
    """Provide a configured VersionChecker."""
    from depkeeper.core import PyPIDataStore, VersionChecker

    store = PyPIDataStore(http_client)
    return VersionChecker(data_store=store)
```

---

## Mocking External Services

!!! danger "Golden Rule"

    Never make real network calls in tests. All external services must be mocked.

### Mocking HTTP Requests

Use pytest-httpx to mock HTTP responses:

=== "Basic Mock"

    ```python title="tests/unit/core/test_checker.py"
    import pytest


    @pytest.mark.asyncio
    async def test_checker_returns_latest_version(httpx_mock):
        """VersionChecker identifies the latest available version."""
        # Arrange: Mock PyPI response
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json={
                "info": {"name": "requests", "version": "2.31.0"},
                "releases": {
                    "2.28.0": [{"upload_time": "2023-01-01"}],
                    "2.31.0": [{"upload_time": "2023-06-15"}],
                },
            },
        )

        # Act
        from depkeeper.core import PyPIDataStore, VersionChecker
        from depkeeper.utils import HTTPClient

        async with HTTPClient() as http:
            store = PyPIDataStore(http)
            checker = VersionChecker(data_store=store)
            pkg = await checker.get_package_info("requests", "2.28.0")

        # Assert
        assert pkg.latest_version == "2.31.0"
        assert pkg.current_version == "2.28.0"
        assert pkg.update_available is True
    ```

=== "Multiple Requests"

    ```python title="tests/integration/test_batch_check.py"
    import pytest


    @pytest.mark.asyncio
    async def test_batch_check_multiple_packages(httpx_mock):
        """Checker efficiently handles multiple package queries."""
        # Mock responses for multiple packages
        packages = ["requests", "flask", "click"]
        for pkg in packages:
            httpx_mock.add_response(
                url=f"https://pypi.org/pypi/{pkg}/json",
                json={
                    "info": {"name": pkg, "version": "1.0.0"},
                    "releases": {"1.0.0": [{}]},
                },
            )

        # ... test implementation
    ```

=== "Error Responses"

    ```python title="tests/unit/core/test_checker_errors.py"
    import pytest
    import httpx


    @pytest.mark.asyncio
    async def test_checker_handles_not_found(httpx_mock):
        """VersionChecker gracefully handles missing packages."""
        httpx_mock.add_response(
            url="https://pypi.org/pypi/nonexistent-pkg/json",
            status_code=404,
        )

        from depkeeper.core import PyPIDataStore, VersionChecker
        from depkeeper.utils import HTTPClient
        from depkeeper.exceptions import PackageNotFoundError

        async with HTTPClient() as http:
            store = PyPIDataStore(http)
            checker = VersionChecker(data_store=store)

            with pytest.raises(PackageNotFoundError) as exc:
                await checker.get_package_info("nonexistent-pkg")

            assert "nonexistent-pkg" in str(exc.value)


    @pytest.mark.asyncio
    async def test_checker_handles_timeout(httpx_mock):
        """VersionChecker handles network timeouts gracefully."""
        httpx_mock.add_exception(
            httpx.TimeoutException("Connection timed out")
        )

        # ... test implementation
    ```

### Using Mock Fixtures

For complex mock setups, create reusable fixtures:

```python title="tests/conftest.py"
import pytest
import json
from pathlib import Path
from typing import List, Optional


@pytest.fixture
def mock_pypi_package(httpx_mock):
    """Factory fixture to mock PyPI package responses."""

    def _mock(name: str, versions: List[str], latest: Optional[str] = None):
        latest = latest or versions[-1]
        httpx_mock.add_response(
            url=f"https://pypi.org/pypi/{name}/json",
            json={
                "info": {"name": name, "version": latest},
                "releases": {v: [{}] for v in versions},
            },
        )

    return _mock


# Usage in tests:
@pytest.mark.asyncio
async def test_with_mock_factory(mock_pypi_package, checker):
    mock_pypi_package("requests", ["2.28.0", "2.29.0", "2.31.0"])

    pkg = await checker.get_package_info("requests")
    assert pkg.latest_version == "2.31.0"
```

---

## Parametrized Tests

Use pytest.mark.parametrize to test multiple scenarios without code duplication:

=== "Basic Parametrization"

    ```python title="tests/unit/core/test_parser.py"
    import pytest


    @pytest.mark.parametrize(
        "input_line,expected_name,expected_specs",
        [
            ("requests==2.28.0", "requests", [("==", "2.28.0")]),
            ("flask>=2.0,<3.0", "flask", [(">=", "2.0"), ("<", "3.0")]),
            ("click~=8.0", "click", [("~=", "8.0")]),
            ("numpy", "numpy", []),
            ("Django>=4.0", "django", [(">=", "4.0")]),  # Normalized
        ],
        ids=[
            "pinned-version",
            "version-range",
            "compatible-release",
            "no-version",
            "case-normalization",
        ],
    )
    def test_parse_version_specifiers(parser, input_line, expected_name, expected_specs):
        """Parser correctly handles various version specifier formats."""
        result = parser.parse_line(input_line, line_number=1)

        assert result.name == expected_name
        assert result.specs == expected_specs
    ```

=== "Multiple Parameters"

    ```python title="tests/unit/utils/test_version_utils.py"
    import pytest
    from depkeeper.utils.version_utils import get_update_type


    @pytest.mark.parametrize("current,target,expected", [
        # Major version changes
        ("1.0.0", "2.0.0", "major"),
        ("1.9.9", "2.0.0", "major"),
        # Minor version changes
        ("1.0.0", "1.1.0", "minor"),
        ("1.0.5", "1.2.0", "minor"),
        # Patch version changes
        ("1.0.0", "1.0.1", "patch"),
        ("1.2.3", "1.2.5", "patch"),
        # Edge cases
        ("1.0.0", "1.0.0", "same"),
        ("2.0.0", "1.0.0", "downgrade"),
        (None, "1.0.0", "new"),
    ])
    def test_get_update_type(current, target, expected):
        """get_update_type correctly classifies version changes."""
        result = get_update_type(current, target)
        assert result == expected
    ```

=== "Fixture Parametrization"

    ```python title="tests/conftest.py"
    import pytest


    @pytest.fixture(params=[
        "requirements.txt",
        "requirements-dev.txt",
        "requirements/base.txt",
    ])
    def requirements_filename(request):
        """Test with various requirements file naming conventions."""
        return request.param
    ```

---

## Testing Errors & Exceptions

Verify error handling with explicit assertions:

```python title="tests/unit/core/test_parser_errors.py"
import pytest
from depkeeper.exceptions import ParseError, InvalidVersionError


class TestParserErrors:
    """Tests for parser error handling."""

    def test_invalid_syntax_raises_parse_error(self, parser):
        """Parser raises ParseError with line info for invalid syntax."""
        with pytest.raises(ParseError) as exc_info:
            parser.parse_line("invalid@@@", line_number=42)

        error = exc_info.value
        assert "Invalid requirement" in str(error)
        assert error.line_number == 42
        assert error.line_content == "invalid@@@"

    def test_invalid_version_provides_context(self, parser):
        """ParseError includes helpful context for invalid versions."""
        with pytest.raises(InvalidVersionError) as exc_info:
            parser.parse_line("requests==not.a.version", line_number=1)

        assert "not.a.version" in str(exc_info.value)
        assert exc_info.value.package_name == "requests"

    @pytest.mark.parametrize("invalid_line", [
        "===invalid",
        "package==",
        "@@@",
        "git+invalid-url",
    ])
    def test_various_invalid_inputs(self, parser, invalid_line):
        """Parser handles various invalid inputs gracefully."""
        with pytest.raises(ParseError):
            parser.parse_line(invalid_line, line_number=1)
```

!!! tip "Testing Exception Hierarchy"

    Use pytest.raises(YourBaseError) to catch any exception in your custom hierarchy,
    or be specific to ensure the exact exception type is raised. Avoid catching BaseException
    as it includes SystemExit and KeyboardInterrupt.

---

## Integration Tests

Integration tests verify component interactions:

```python title="tests/integration/test_check_workflow.py"
import pytest


@pytest.mark.asyncio
class TestCheckWorkflow:
    """Integration tests for the check command workflow."""

    async def test_full_check_workflow(
        self,
        sample_requirements_file,
        httpx_mock,
        mock_pypi_package,
    ):
        """Check workflow parses, queries, and reports correctly."""
        # Arrange
        mock_pypi_package("requests", ["2.28.0", "2.31.0"])
        mock_pypi_package("flask", ["2.3.0"])
        mock_pypi_package("click", ["8.0.0", "8.1.0"])
        mock_pypi_package("pytest", ["7.0.0", "7.4.0"])

        from depkeeper.core import RequirementsParser, VersionChecker, PyPIDataStore
        from depkeeper.utils import HTTPClient

        # Act
        parser = RequirementsParser()
        requirements = parser.parse_file(sample_requirements_file)

        async with HTTPClient() as http:
            store = PyPIDataStore(http)
            checker = VersionChecker(data_store=store)
            packages = await checker.check_packages(requirements)

        # Assert
        assert len(packages) == len(requirements)
        outdated = [p for p in packages if p.update_available]
        assert len(outdated) == 3  # requests, click, pytest

    async def test_workflow_handles_partial_failures(
        self,
        sample_requirements_file,
        httpx_mock,
    ):
        """Workflow continues checking even if some packages fail."""
        # Mock one success, one failure
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json={"info": {"name": "requests", "version": "2.31.0"}, "releases": {}},
        )
        httpx_mock.add_response(
            url="https://pypi.org/pypi/flask/json",
            status_code=500,
        )
        # ... remaining mocks

        from depkeeper.core import RequirementsParser, VersionChecker, PyPIDataStore
        from depkeeper.utils import HTTPClient

        parser = RequirementsParser()
        requirements = parser.parse_file(sample_requirements_file)

        async with HTTPClient() as http:
            store = PyPIDataStore(http)
            checker = VersionChecker(data_store=store)
            result = await checker.check_packages(requirements)

        # Should still return results for successful packages
        assert any(p.name == "requests" for p in result.packages)
        assert any(e.name == "flask" for e in result.errors)
```

---

## CLI End-to-End Tests

Test CLI behavior using Click's test runner:

=== "Basic CLI Tests"

    ```python title="tests/e2e/test_cli.py"
    import pytest
    from click.testing import CliRunner
    from depkeeper.cli import cli


    class TestCheckCommand:
        """E2E tests for the check command."""

        @pytest.fixture
        def runner(self):
            return CliRunner()

        def test_check_shows_outdated_packages(self, runner, httpx_mock):
            """Check command displays outdated packages."""
            with runner.isolated_filesystem():
                # Create requirements file
                with open("requirements.txt", "w") as f:
                    f.write("requests==2.28.0\n")

                # Mock PyPI
                # Note: May need to configure httpx_mock for CLI tests

                result = runner.invoke(cli, ["check"])

                assert result.exit_code == 0
                assert "requests" in result.output

        def test_check_returns_success_with_outdated(self, runner):
            """Check returns exit code 0 even when updates are available."""
            with runner.isolated_filesystem():
                with open("requirements.txt", "w") as f:
                    f.write("requests==2.28.0\n")

                result = runner.invoke(cli, ["check"])

                # Exit code 0 indicates successful execution
                assert result.exit_code == 0

        def test_check_missing_file_shows_error(self, runner):
            """Check command shows helpful error for missing file."""
            with runner.isolated_filesystem():
                result = runner.invoke(cli, ["check"])

                assert result.exit_code != 0
                assert "requirements.txt" in result.output
                assert "not found" in result.output.lower()
    ```

=== "Testing Output Formats"

    ```python title="tests/e2e/test_cli_output.py"
    import json
    import pytest
    from click.testing import CliRunner
    from depkeeper.cli import cli


    class TestOutputFormats:
        """Tests for different output format options."""

        @pytest.fixture
        def runner(self):
            return CliRunner()

        def test_json_output_is_valid(self, runner):
            """JSON output is valid and parseable."""
            with runner.isolated_filesystem():
                with open("requirements.txt", "w") as f:
                    f.write("requests==2.28.0\n")

                result = runner.invoke(cli, ["check", "--format", "json"])

                # Should be valid JSON
                data = json.loads(result.output)
                assert isinstance(data, list)
                assert all("name" in pkg for pkg in data)

        def test_quiet_mode_minimal_output(self, runner):
            """Quiet mode produces minimal output."""
            with runner.isolated_filesystem():
                with open("requirements.txt", "w") as f:
                    f.write("requests==2.28.0\n")

                result = runner.invoke(cli, ["check", "-q"])

                # Should have minimal output
                lines = [l for l in result.output.strip().split("\n") if l]
                assert len(lines) <= 5

        def test_verbose_shows_debug_info(self, runner):
            """Verbose mode includes debug information."""
            with runner.isolated_filesystem():
                with open("requirements.txt", "w") as f:
                    f.write("requests==2.28.0\n")

                result = runner.invoke(cli, ["check", "-v"])

                # Should include extra info
                assert "Parsing" in result.output or "Checking" in result.output
    ```

=== "Interactive Tests"

    ```python title="tests/e2e/test_cli_interactive.py"
    import pytest
    from click.testing import CliRunner
    from depkeeper.cli import cli


    class TestInteractiveCommands:
        """Tests for commands requiring user input."""

        @pytest.fixture
        def runner(self):
            return CliRunner(mix_stderr=False)

        def test_update_prompts_for_confirmation(self, runner):
            """Update command asks for confirmation by default."""
            with runner.isolated_filesystem():
                with open("requirements.txt", "w") as f:
                    f.write("requests==2.28.0\n")

                # Simulate user typing 'n' for no
                result = runner.invoke(cli, ["update"], input="n\n")

                assert "Proceed?" in result.output or "Continue?" in result.output
                assert "Aborted" in result.output or "Cancelled" in result.output

        def test_update_yes_flag_skips_prompt(self, runner):
            """Update --yes flag bypasses confirmation."""
            with runner.isolated_filesystem():
                with open("requirements.txt", "w") as f:
                    f.write("requests==2.28.0\n")

                result = runner.invoke(cli, ["update", "--yes", "--dry-run"])

                # Should not ask for confirmation
                assert "Proceed?" not in result.output
    ```

---

## Test Markers

Use markers to categorize and selectively run tests:

```python title="tests/conftest.py"
import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests (fast, isolated)")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "e2e: End-to-end CLI tests")
    config.addinivalue_line("markers", "slow: Slow-running tests")
    config.addinivalue_line("markers", "network: Requires network access")
```

```python title="tests/unit/test_parser.py"
import pytest


@pytest.mark.unit
class TestParser:
    """Unit tests for RequirementsParser."""

    def test_parse_simple(self, parser):
        ...


@pytest.mark.slow
def test_parse_large_file(parser, large_requirements_file):
    """Test parsing a file with 1000+ requirements."""
    ...
```

### Running Tests by Marker

```bash
# Run only unit tests
pytest -m "unit"

# Skip slow tests
pytest -m "not slow"

# Run integration tests only
pytest -m "integration"

# Combine markers
pytest -m "unit and not slow"
```

---

## Code Coverage

### Running Coverage

=== "Command Line"

    ```bash
    # Run with coverage
    pytest --cov=depkeeper

    # Generate HTML report
    pytest --cov=depkeeper --cov-report=html

    # Generate XML for CI tools
    pytest --cov=depkeeper --cov-report=xml

    # Fail if coverage below threshold
    pytest --cov=depkeeper --cov-fail-under=85
    ```

=== "Opening Reports"

    ```bash
    # macOS
    open htmlcov/index.html

    # Linux
    xdg-open htmlcov/index.html

    # Windows
    start htmlcov/index.html
    ```

### Coverage Configuration

```toml title="pyproject.toml"
[tool.coverage.run]
source = ["depkeeper"]
omit = [
    "*/tests/*",
    "*/__pycache__/*",
    "*/site-packages/*",
]

[tool.coverage.report]
precision = 2
show_missing = true
skip_covered = false

exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
    "@abstractmethod",
    "@abc.abstractmethod",
]

[tool.coverage.html]
directory = "htmlcov"

[tool.coverage.xml]
output = "coverage.xml"
```

### Coverage Targets

| Scope              | Minimum | Target |
| ------------------ | ------- | ------ |
| **Overall**        | 85%     | 90%+   |
| **Critical Paths** | 95%     | 100%   |
| **New Code**       | 90%     | 95%    |

!!! info "Critical Paths Requiring 100% Coverage"

    - `core/parser.py` - Requirement parsing
    - `core/checker.py` - Version checking
    - `core/data_store.py` - PyPI data retrieval
    - `core/dependency_analyzer.py` - Dependency resolution
    - `commands/update.py` - File modification and updates

---

## Best Practices

### Do

- Write one assertion group per test - Tests should verify one behavior
- Use descriptive test names - Names should explain what is being tested
- Use fixtures - Avoid duplicating setup code
- Mock external services - Tests should be deterministic
- Test edge cases - Empty inputs, large files, special characters
- Test error paths - Verify errors are handled gracefully
- Keep tests fast - Unit tests should run in milliseconds
- Use parametrize - Reduce duplication for similar tests

### Avoid

- Testing implementation details - Test behavior, not internals
- Relying on test order - Tests should be independent
- Hard-coded paths - Use tmp_path fixture
- Skipping cleanup - Use fixtures with proper teardown
- Ignoring warnings - Treat warnings as errors in CI
- Flaky tests - Fix or mark tests that intermittently fail
- Overly complex fixtures - Keep fixtures simple and focused

---

## Troubleshooting

??? question "Tests pass locally but fail in CI"

    **Common causes and solutions:**

    - **Path handling differences**
        - *Cause:* Hardcoded paths like `C:\Users\...` or `/home/user/...` fail on other OS
        - *Solution:* Always use `pathlib.Path` and `tmp_path` fixture:
        ```python
        from pathlib import Path

        # Bad - OS-specific
        path = "/home/user/file.txt"

        # Good - OS-agnostic
        path = Path("file.txt")
        path = tmp_path / "file.txt"
        ```

    - **Line ending differences**
        - *Cause:* Windows uses CRLF (`\r\n`), Unix uses LF (`\n`)
        - *Solution:* Open files with explicit newline handling:
        ```python
        with open(file_path, "w", newline="\n") as f:
            f.write(content)
        ```

    - **Missing dependencies**
        - *Cause:* Dev dependencies not installed in CI
        - *Solution:* Ensure `pip install -e ".[dev]"` is in CI config

    - **Async timing issues**
        - *Cause:* Race conditions or timeouts differ across environments
        - *Solution:* Use deterministic mocks instead of real delays

??? question "Coverage is lower in CI than locally"

    **Common causes and solutions:**

    - **Different Python versions**
        - *Cause:* Branch coverage differs between Python versions
        - *Solution:* Pin Python version in CI to match local development

    - **Missing test files**
        - *Cause:* Test discovery not finding all files
        - *Solution:* Verify `pytest.ini` or `pyproject.toml` has correct `testpaths`

    - **Inconsistent coverage config**
        - *Cause:* Different `pyproject.toml` settings
        - *Solution:* Commit `pyproject.toml` and ensure same config everywhere

    - **Parallel test execution**
        - *Cause:* `pytest-xdist` can affect coverage collection
        - *Solution:* Use `--cov-append` with parallel tests

??? question "Tests are slow"

    **Common causes and solutions:**

    - **Real network calls**
        - *Cause:* Tests hitting actual APIs instead of mocks
        - *Solution:* Mock all external services with `httpx_mock` or `responses`

    - **Excessive fixture scope**
        - *Cause:* Using `function` scope when `module` or `session` would work
        - *Solution:* Use broader scopes for expensive, immutable fixtures

    - **No parallelization**
        - *Cause:* Tests running sequentially
        - *Solution:* Install `pytest-xdist` and run `pytest -n auto`

    - **Finding slow tests**
        - Run `pytest --durations=10` to identify the slowest tests
        - Consider marking slow tests with `@pytest.mark.slow` and skipping in dev

??? question "httpx_mock not working in CLI tests"

    **Cause:** Click's `CliRunner` runs in an isolated environment that doesn't share the same event loop or mock context.

    **Solutions:**

    - **Use dependency injection**
        - Pass mock clients through the CLI context or environment variables

    - **Set up mocks inside isolated filesystem**
        ```python
        def test_cli_with_mock(runner, httpx_mock):
            with runner.isolated_filesystem():
                httpx_mock.add_response(url="...", json={...})
                result = runner.invoke(cli, ["check"])
        ```

    - **Use subprocess for true E2E**
        - For full integration tests, run CLI as subprocess with mocked server

??? question "Import errors or module not found"

    **Common causes and solutions:**

    - **Package not installed in editable mode**
        - *Cause:* Running tests without installing the package
        - *Solution:* Run `pip install -e .` before testing

    - **Circular imports**
        - *Cause:* Test imports triggering circular dependencies
        - *Solution:* Import inside test functions or use `TYPE_CHECKING`

    - **Python path issues**
        - *Cause:* Working directory not in Python path
        - *Solution:* Run pytest from project root or configure `pythonpath` in `pyproject.toml`

??? question "Fixtures not found"

    **Common causes and solutions:**

    - **Wrong conftest.py location**
        - *Cause:* Fixture defined in wrong `conftest.py` or not at all
        - *Solution:* Place shared fixtures in `tests/conftest.py`

    - **Scope mismatch**
        - *Cause:* Session-scoped fixture depending on function-scoped fixture
        - *Solution:* Ensure fixture scope hierarchy is correct

    - **Missing fixture import**
        - *Cause:* Fixture from plugin not available
        - *Solution:* Install required plugins: `pytest-httpx`, `pytest-asyncio`

---

## Next Steps

- [Code Style](code-style.md) -- Follow coding standards and formatting requirements
- [Development Setup](development-setup.md) -- Set up your local development environment
- [Release Process](release-process.md) -- Understand how releases are planned and published
