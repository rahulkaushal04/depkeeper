---
title: Code Style
description: Coding standards and style guidelines for depkeeper
---

# Code Style

This document defines the coding standards and conventions used in **depkeeper**.
Following these guidelines ensures consistency, readability, and maintainability across the codebase.

---

## Guiding Principles

- Code should be **clear, explicit, and predictable**
- Prefer **readability over cleverness**
- Follow established **Python community standards**
- Automate formatting and checks wherever possible

---

## Standards Overview

depkeeper follows modern Python best practices:

| Area           | Tool / Standard    |
| -------------- | ------------------ |
| Style Guide    | PEP 8              |
| Formatting     | Black              |
| Type Checking  | mypy (strict mode) |
| Automation     | pre-commit         |
| Python Version | 3.8+               |

---

## Automated Tooling

### Code Formatting (Black)

Black enforces a consistent, opinionated code format.

```bash
# Format all files
black .

# Check formatting without modifying files
black --check .
```

---

### Static Type Checking (mypy)

mypy is used in **strict mode** to enforce strong typing.

```bash
mypy depkeeper
```

All new code must:

- Be fully type-annotated
- Pass mypy without errors

---

### Pre-commit Hooks

All formatting and checks are enforced automatically before commits.

```bash
# Install hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

---

## Python Style Guidelines

### Imports

```python
from __future__ import annotations

# Standard library
import asyncio
from pathlib import Path
from typing import Dict, List, Optional

# Third-party
import click
from packaging.version import Version

# Local
from depkeeper.models import Package
from depkeeper.utils.logger import get_logger
```

**Rules**

- Use `from __future__ import annotations`
- Group imports manually: standard library → third-party → local
- Use absolute imports
- Avoid wildcard imports

---

## Type Annotations (Python 3.8)

All new code must use **Python 3.8–compatible typing**.

```python
from typing import Optional

def get_package(
    name: str,
    version: Optional[str] = None,
) -> Package:
    ...
```

Collections:

```python
from typing import Dict, List

def process_items(items: List[str]) -> Dict[str, int]:
    ...
```

Union types:

```python
from typing import Union

def normalize(value: Union[str, int]) -> str:
    ...
```

Structured data:

```python
from typing import TypedDict

class PackageInfo(TypedDict):
    name: str
    version: str
    dependencies: List[str]
```

---

## Docstrings

Use **Google-style docstrings** for all public modules, classes, and functions.

```python
def check_package(name: str) -> Package:
    """Check a package for available updates.

    Args:
        name: Package name.

    Returns:
        Package with version recommendations.

    Raises:
        PyPIError: If package metadata cannot be retrieved.
    """
```

---

## Classes and Data Models

Use `@dataclass` for data-centric classes.

```python
from dataclasses import dataclass

@dataclass
class Package:
    """Represents a Python package."""

    name: str
    current_version: Optional[str] = None
    recommended_version: Optional[str] = None

    def __post_init__(self) -> None:
        self.name = self.name.lower().replace("_", "-")
```

---

## Asynchronous Code

Use async APIs for all I/O-bound operations.

```python
async def fetch_package(name: str) -> Dict[str, str]:
    async with HTTPClient() as client:
        return await client.get(name)
```

For concurrency:

```python
results = await asyncio.gather(*tasks, return_exceptions=True)
```

---

## Error Handling

- Use **custom exception types**
- Never suppress exceptions
- Preserve original traceback context

```python
from depkeeper.exceptions import ParseError

try:
    parse_line(line)
except ValueError as exc:
    raise ParseError(f"Invalid requirement: {line}") from exc
```

---

## Constants

Define all constants in `constants.py`.

```python
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
```

Avoid inline magic values.

---

## Naming Conventions

| Element  | Convention            | Example              |
| -------- | --------------------- | -------------------- |
| Module   | snake_case            | `version_checker.py` |
| Class    | PascalCase            | `VersionChecker`     |
| Function | snake_case            | `check_package()`    |
| Variable | snake_case            | `current_version`    |
| Constant | UPPER_SNAKE           | `MAX_RETRIES`        |
| Private  | `_leading_underscore` | `_parse()`           |

---

## Code Organization

Recommended module layout:

```python
"""Module description."""

from __future__ import annotations

# Imports
...

logger = get_logger(__name__)

__all__ = ["PublicClass"]

class PublicClass:
    ...

def public_function() -> None:
    ...

def _private_helper() -> None:
    ...
```

---

## Function Design

- Keep functions **under ~50 lines**
- One responsibility per function
- Extract complex logic into helpers
- Prefer explicit flow over implicit behavior

---

## CLI Code Style

Click-based commands should remain explicit and readable.

```python
@click.command()
@click.argument("file", type=Path)
@click.option("--dry-run", is_flag=True)
def check(file: Path, dry_run: bool) -> None:
    """Check dependencies for updates."""
```

---

## Testing Style

Refer to **[Testing](testing.md)** for details.

```python
def test_parser_handles_extras():
    ...
```

Best practices:

- Clear, descriptive test names
- Reusable fixtures
- Parametrized tests for variations

---

## Logging

Use structured logging with appropriate severity.

```python
logger.debug("Fetching metadata for %s", name)
logger.info("Processed %d packages", count)
logger.warning("Using fallback version")
logger.error("Failed to parse input")
```

---

## Anti-Patterns

❌ **Avoid**

```python
def func(items=[]):  # Mutable default
    ...

except:  # Bare except
    ...

from module import *  # Wildcard import
```

✅ **Preferred**

```python
from typing import Optional, List

def func(items: Optional[List[str]] = None):
    items = items or []

except ValueError as exc:
    ...

from module import specific_function
```

---

## Next Steps

- **[Testing](testing.md)** — Testing practices
- **[Development Setup](development-setup.md)** — Environment setup
