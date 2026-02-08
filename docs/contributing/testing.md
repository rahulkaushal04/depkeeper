---
title: Testing
description: Testing guidelines for depkeeper
---

# Testing

This document describes how to run, write, and organize tests for **depkeeper**.
The goal of the test suite is to ensure correctness, prevent regressions, and support safe refactoring.

---

## Running Tests

### Run the Full Test Suite

```bash
pytest
```

Common options:

```bash
pytest -v                      # Verbose output
pytest --cov=depkeeper         # Run with coverage
pytest --cov=depkeeper --cov-report=html
```

---

### Run Specific Tests

```bash
pytest tests/unit/test_parser.py
pytest tests/unit/test_parser.py::test_parse_simple_requirement
pytest -k "parser"
pytest -m "unit"
```

---

### Useful Pytest Options

```bash
pytest -x          # Stop on first failure
pytest -l          # Show local variables on failure
pytest --ff        # Run failed tests first
pytest -n auto     # Run tests in parallel
```

---

## Test Organization

The test suite is structured by responsibility:

```
tests/
├── conftest.py        # Shared fixtures and configuration
├── unit/              # Unit tests
├── integration/       # Integration tests
└── e2e/               # End-to-end (CLI) tests
```

### Test Categories

| Category    | Purpose                              |
| ----------- | ------------------------------------ |
| Unit        | Test individual functions or classes |
| Integration | Test interactions between components |
| End-to-End  | Test CLI behavior and user workflows |

---

## Writing Tests

### Basic Unit Test

```python
from depkeeper.core.parser import RequirementsParser


def test_parse_simple_requirement():
    """Parser correctly handles a pinned version."""
    parser = RequirementsParser()

    result = parser.parse_line("requests==2.28.0", line_number=1)

    assert result.name == "requests"
    assert result.specs == [("==", "2.28.0")]
```

---

### Using Fixtures

Fixtures should be defined in `conftest.py` and reused where possible.

```python
import pytest
from pathlib import Path


@pytest.fixture
def sample_requirements_file(tmp_path: Path) -> Path:
    content = """\
requests>=2.28.0
flask==2.3.0
click>=8.0.0
"""
    file_path = tmp_path / "requirements.txt"
    file_path.write_text(content)
    return file_path
```

```python
def test_parse_file(parser, sample_requirements_file):
    requirements = parser.parse_file(sample_requirements_file)

    assert len(requirements) == 3
    assert requirements[0].name == "requests"
```

---

## Async Tests

Async code must be tested using `pytest.mark.asyncio`.

```python
import pytest


@pytest.mark.asyncio
async def test_fetch_package_data():
    from depkeeper.core import PyPIDataStore, VersionChecker
    from depkeeper.utils import HTTPClient

    async with HTTPClient() as http:
        store = PyPIDataStore(http)
        checker = VersionChecker(data_store=store)

        pkg = await checker.get_package_info("requests")

        assert pkg.name == "requests"
        assert pkg.latest_version is not None
```

---

## Mocking External Services

All network access must be mocked in tests.

```python
@pytest.mark.asyncio
async def test_checker_with_mock_pypi(httpx_mock):
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json={
            "info": {"name": "requests", "version": "2.31.0"},
            "releases": {
                "2.28.0": [{}],
                "2.31.0": [{}],
            },
        },
    )

    from depkeeper.core import PyPIDataStore, VersionChecker
    from depkeeper.utils import HTTPClient

    async with HTTPClient() as http:
        store = PyPIDataStore(http)
        checker = VersionChecker(data_store=store)

        pkg = await checker.get_package_info("requests", "2.28.0")

        assert pkg.latest_version == "2.31.0"
```

---

## Parametrized Tests

Use `pytest.mark.parametrize` for testing multiple input variations.

```python
import pytest


@pytest.mark.parametrize(
    "input_line,expected_name,expected_specs",
    [
        ("requests==2.28.0", "requests", [("==", "2.28.0")]),
        ("flask>=2.0,<3.0", "flask", [(">=", "2.0"), ("<", "3.0")]),
        ("click~=8.0", "click", [("~=", "8.0")]),
        ("numpy", "numpy", []),
    ],
)
def test_parse_various_formats(parser, input_line, expected_name, expected_specs):
    result = parser.parse_line(input_line, line_number=1)

    assert result.name == expected_name
    assert result.specs == expected_specs
```

---

## Testing Errors

Verify expected failures explicitly.

```python
import pytest
from depkeeper.exceptions import ParseError


def test_parser_raises_on_invalid_input(parser):
    with pytest.raises(ParseError) as exc:
        parser.parse_line("invalid@@@", line_number=1)

    assert "Invalid requirement" in str(exc.value)
    assert exc.value.line_number == 1
```

---

## Integration Tests

Integration tests verify component interaction.

```python
@pytest.mark.asyncio
async def test_full_check_workflow(sample_requirements_file, httpx_mock):
    httpx_mock.add_response(...)

    from depkeeper.core import RequirementsParser, VersionChecker, PyPIDataStore
    from depkeeper.utils import HTTPClient

    parser = RequirementsParser()
    requirements = parser.parse_file(sample_requirements_file)

    async with HTTPClient() as http:
        store = PyPIDataStore(http)
        checker = VersionChecker(data_store=store)
        packages = await checker.check_packages(requirements)

    assert len(packages) == len(requirements)
```

---

## CLI Tests

CLI behavior is tested using Click’s test runner.

```python
from click.testing import CliRunner
from depkeeper.cli import cli


def test_check_command_basic():
    runner = CliRunner()

    with runner.isolated_filesystem():
        with open("requirements.txt", "w") as f:
            f.write("requests==2.28.0\n")

        result = runner.invoke(cli, ["check"])

        assert result.exit_code == 0
```

---

## Test Markers

Define custom markers in `conftest.py`:

```python
def pytest_configure(config):
    config.addinivalue_line("markers", "slow: slow-running tests")
    config.addinivalue_line("markers", "network: requires network access")
```

Usage:

```python
@pytest.mark.slow
def test_large_file_parsing():
    ...
```

Run selectively:

```bash
pytest -m "not slow"
pytest -m "not network"
```

---

## Coverage

### Running Coverage

```bash
pytest --cov=depkeeper --cov-report=html
```

Open the report:

```bash
open htmlcov/index.html      # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html     # Windows
```

### Coverage Targets

- **Minimum**: 85%
- **Target**: 90%+
- **Critical paths**: 100%

Critical paths include:

- Requirement parsing
- Version comparison
- File I/O

---

## Testing Best Practices

### Recommended

- One assertion group per test
- Descriptive test names
- Shared fixtures for setup
- Mock all external dependencies
- Test edge cases and failures

### Avoid

- Testing implementation details
- Relying on execution order
- Hard-coded file paths
- Skipping cleanup
- Ignoring warnings

---

## Next Steps

- **[Code Style](code-style.md)** — Coding standards
- **[Development Setup](development-setup.md)** — Environment setup
- **[Release Process](release-process.md)** — Release workflow
