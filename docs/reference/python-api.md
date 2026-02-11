---
title: Python API
description: Programmatic interface for depkeeper
---

# Python API

Use depkeeper programmatically in your Python scripts and tools. This page documents the core modules, data models, and utility functions available for integration.

---

## Overview

**Core pipeline:**

| Step | Module | Input | Output |
|---|---|---|---|
| 1 | `RequirementsParser` | requirements file | `List[Requirement]` |
| 2 | `VersionChecker` | `List[Requirement]` | `List[Package]` |
| 3 | `DependencyAnalyzer` | `List[Package]` | `ResolutionResult` |
| 4 | Apply / Report | `ResolutionResult` | Updated file or report |

`PyPIDataStore` backs both `VersionChecker` and `DependencyAnalyzer`, and is itself backed by `HTTPClient`.

depkeeper provides a Python API for:

- Parsing `requirements.txt` files into structured `Requirement` objects
- Checking package versions against PyPI with strict major version boundaries
- Resolving dependency conflicts through iterative analysis
- Formatting and displaying results

All core modules share a single `PyPIDataStore` instance to ensure each package is fetched at most once per process.

---

## Quick Start

```python
import asyncio
from depkeeper.core import RequirementsParser, VersionChecker, PyPIDataStore
from depkeeper.utils import HTTPClient

async def check_requirements():
    # Parse requirements file
    parser = RequirementsParser()
    requirements = parser.parse_file("requirements.txt")

    # Check versions
    async with HTTPClient() as http:
        store = PyPIDataStore(http)
        checker = VersionChecker(data_store=store)
        packages = await checker.check_packages(requirements)

    # Report
    for pkg in packages:
        if pkg.has_update():
            print(f"{pkg.name}: {pkg.current_version} -> {pkg.recommended_version}")

asyncio.run(check_requirements())
```

---

## Core Modules

### RequirementsParser

Stateful parser for pip-style requirements files. Supports all PEP 440/508 syntax including version specifiers, extras, environment markers, include directives (`-r`), constraint files (`-c`), VCS URLs, editable installs, and hash verification.

The parser maintains internal state across multiple `parse_file` calls:

- **Include stack** -- tracks the chain of `-r` directives to detect circular dependencies
- **Constraint map** -- stores requirements loaded via `-c` directives

Call `reset()` to clear state before reusing the parser on an unrelated set of files.

```python
from depkeeper.core import RequirementsParser

parser = RequirementsParser()

# Parse from file
requirements = parser.parse_file("requirements.txt")

# Parse from string
content = """
requests>=2.28.0
flask==2.3.0
-r base.txt
"""
requirements = parser.parse_string(content, source_file_path="inline")

# Access constraint files loaded via -c
constraints = parser.get_constraints()

# Reset state before reusing
parser.reset()
```

#### Methods

::: depkeeper.core.RequirementsParser
    options:
      show_root_heading: false
      members:
        - parse_file
        - parse_string
        - parse_line
        - get_constraints
        - reset

---

### VersionChecker

Async package version checker with strict major version boundary enforcement. Recommendations never cross major version boundaries -- if the current version is `2.x.x`, the recommended version will always be `2.y.z`, never `3.0.0`.

All network I/O is delegated to `PyPIDataStore`, which guarantees that each unique package is fetched at most once.

```python
from depkeeper.core import VersionChecker, PyPIDataStore
from depkeeper.utils import HTTPClient

async def main():
    async with HTTPClient() as http:
        store = PyPIDataStore(http)
        checker = VersionChecker(data_store=store)

        # Check single package
        pkg = await checker.get_package_info("requests", current_version="2.28.0")
        print(f"Latest: {pkg.latest_version}")
        print(f"Recommended: {pkg.recommended_version}")

        # Check multiple packages concurrently
        packages = await checker.check_packages(requirements)
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `data_store` | `PyPIDataStore` | Required | Shared PyPI metadata cache |
| `infer_version_from_constraints` | `bool` | `True` | Infer current version from range constraints like `>=2.0` |

#### Methods

::: depkeeper.core.VersionChecker
    options:
      show_root_heading: false
      members:
        - get_package_info
        - check_packages
        - extract_current_version

---

### PyPIDataStore

Async-safe, per-process cache for PyPI package metadata. Each unique package name triggers at most one HTTP request to `/pypi/{pkg}/json`. A semaphore limits concurrent outbound fetches, and double-checked locking prevents duplicate requests when multiple coroutines request the same package simultaneously.

```python
from depkeeper.core import PyPIDataStore
from depkeeper.utils import HTTPClient

async def main():
    async with HTTPClient() as http:
        store = PyPIDataStore(http, concurrent_limit=10)

        # Fetch package data
        data = await store.get_package_data("requests")
        print(f"Latest: {data.latest_version}")
        print(f"All versions: {data.all_versions[:5]}")

        # Prefetch multiple packages concurrently
        await store.prefetch_packages(["flask", "click", "jinja2"])

        # Get cached data (no network call)
        cached = store.get_cached_package("flask")

        # Get dependencies for a specific version
        deps = await store.get_version_dependencies("flask", "2.3.0")
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `http_client` | `HTTPClient` | Required | Pre-configured async HTTP client |
| `concurrent_limit` | `int` | `10` | Maximum concurrent PyPI fetches |

#### Methods

::: depkeeper.core.PyPIDataStore
    options:
      show_root_heading: false
      members:
        - get_package_data
        - prefetch_packages
        - get_version_dependencies
        - get_cached_package
        - get_versions

---

### PyPIPackageData

Immutable-by-convention snapshot of one PyPI package, populated by `PyPIDataStore`. Contains version lists, Python compatibility data, and dependency caches.

#### Attributes

| Attribute | Type | Description |
|---|---|---|
| `name` | `str` | Normalized package name |
| `latest_version` | `Optional[str]` | Latest version on PyPI |
| `latest_requires_python` | `Optional[str]` | Python requirement for latest version |
| `latest_dependencies` | `List[str]` | Base dependencies of latest version |
| `all_versions` | `List[str]` | Stable versions, newest first |
| `parsed_versions` | `List[Tuple[str, Version]]` | Parsed version objects, descending |
| `python_requirements` | `Dict[str, Optional[str]]` | Version to `requires_python` mapping |
| `dependencies_cache` | `Dict[str, List[str]]` | Per-version dependency lists |

#### Methods

| Method | Returns | Description |
|---|---|---|
| `get_versions_in_major(major)` | `List[str]` | Stable versions sharing a given major number |
| `is_python_compatible(version, python_version)` | `bool` | Check if a package version supports a Python version |
| `get_python_compatible_versions(python_version, major=None)` | `List[str]` | Stable versions compatible with a Python version |

---

### DependencyAnalyzer

Resolves dependency conflicts with strict major version boundary enforcement. The analyzer builds a dependency graph, detects version conflicts, and iteratively adjusts recommendations until a conflict-free set is found or the iteration limit is reached.

```python
from depkeeper.core import DependencyAnalyzer, PyPIDataStore
from depkeeper.utils import HTTPClient

async def main():
    async with HTTPClient() as http:
        store = PyPIDataStore(http)
        analyzer = DependencyAnalyzer(data_store=store)

        # Resolve conflicts
        result = await analyzer.resolve_and_annotate_conflicts(packages)

        # Check results
        for name, resolution in result.resolved_versions.items():
            print(f"{name}: {resolution.original} -> {resolution.resolved}")
            print(f"  Status: {resolution.status}")

        # Summary
        print(result.summary())
```

#### Methods

::: depkeeper.core.DependencyAnalyzer
    options:
      show_root_heading: false
      members:
        - resolve_and_annotate_conflicts

---

### ResolutionResult

Complete result of dependency conflict resolution, returned by `DependencyAnalyzer.resolve_and_annotate_conflicts()`.

#### Attributes

| Attribute | Type | Description |
|---|---|---|
| `resolved_versions` | `Dict[str, PackageResolution]` | Package name to resolution details |
| `total_packages` | `int` | Total packages analyzed |
| `packages_with_conflicts` | `int` | Packages that have conflicts |
| `iterations_used` | `int` | Resolution iterations performed |
| `converged` | `bool` | Whether resolution reached a stable state |

#### Methods

| Method | Returns | Description |
|---|---|---|
| `get_changed_packages()` | `List[PackageResolution]` | Packages whose version was changed |
| `get_conflicts()` | `List[PackageResolution]` | Packages with unresolved conflicts |
| `summary()` | `str` | Human-readable resolution summary |

---

### PackageResolution

Resolution details for a single package within a `ResolutionResult`.

#### Attributes

| Attribute | Type | Description |
|---|---|---|
| `name` | `str` | Package name (normalized) |
| `original` | `Optional[str]` | Initially proposed version |
| `resolved` | `Optional[str]` | Final version after resolution |
| `status` | `ResolutionStatus` | Why this version was chosen |
| `conflicts` | `List[Conflict]` | Conflicts affecting this package |
| `compatible_alternative` | `Optional[str]` | Best alternative version, if any |

#### Resolution Statuses

| Status | Description |
|---|---|
| `KEPT_RECOMMENDED` | Original recommendation was conflict-free |
| `UPGRADED` | Successfully upgraded to a newer version |
| `DOWNGRADED` | Had to downgrade due to conflicts |
| `KEPT_CURRENT` | No safe upgrade found; stayed at current |
| `CONSTRAINED` | Version was constrained by another package |

---

## Models

### Requirement

Represents a single requirement line from a requirements file.

```python
from depkeeper.models import Requirement

req = Requirement(
    name="requests",
    specs=[(">=", "2.28.0"), ("<", "3.0.0")],
    extras=["security"],
    markers="python_version >= '3.8'",
)

# Convert to string
print(req.to_string())  # requests[security]>=2.28.0,<3.0.0; python_version >= '3.8'

# Update version (replaces all specifiers with ==new_version)
updated = req.update_version("2.31.0")
print(updated)  # requests[security]==2.31.0; python_version >= '3.8'
```

#### Attributes

| Attribute | Type | Description |
|---|---|---|
| `name` | `str` | Canonical package name |
| `specs` | `List[Tuple[str, str]]` | Version specifiers (operator, version) |
| `extras` | `List[str]` | Optional extras to install |
| `markers` | `Optional[str]` | Environment marker expression (PEP 508) |
| `url` | `Optional[str]` | Direct URL or VCS source |
| `editable` | `bool` | Whether this is an editable install (`-e`) |
| `hashes` | `List[str]` | Hash values for verification |
| `comment` | `Optional[str]` | Inline comment without the `#` prefix |
| `line_number` | `int` | Original line number in the source file |
| `raw_line` | `Optional[str]` | Original unmodified line text |

#### Methods

| Method | Returns | Description |
|---|---|---|
| `to_string(include_hashes=True, include_comment=True)` | `str` | Render canonical `requirements.txt` representation |
| `update_version(new_version)` | `str` | Return requirement string updated to a new version |

---

### Package

Represents a Python package with version state, update recommendations, and conflict tracking.

```python
from depkeeper.models import Package

pkg = Package(
    name="requests",
    current_version="2.28.0",
    latest_version="2.32.0",
    recommended_version="2.32.0",
)

# Check status
print(pkg.has_update())        # True
print(pkg.requires_downgrade)  # False
print(pkg.has_conflicts())     # False

# Serialization
print(pkg.to_json())
```

#### Attributes

| Attribute | Type | Description |
|---|---|---|
| `name` | `str` | Normalized package name (PEP 503) |
| `current_version` | `Optional[str]` | Currently installed or specified version |
| `latest_version` | `Optional[str]` | Latest version on PyPI (informational) |
| `recommended_version` | `Optional[str]` | Safe upgrade version within major boundary |
| `metadata` | `Dict[str, Any]` | Package metadata from PyPI |
| `conflicts` | `List[Conflict]` | Dependency conflicts affecting this package |

#### Properties and Methods

| Member | Type | Description |
|---|---|---|
| `current` | `Optional[Version]` | Parsed current version |
| `latest` | `Optional[Version]` | Parsed latest version |
| `recommended` | `Optional[Version]` | Parsed recommended version |
| `requires_downgrade` | `bool` | True if recommended version is lower than current |
| `has_update()` | `bool` | True if recommended version is newer than current |
| `has_conflicts()` | `bool` | True if dependency conflicts exist |
| `set_conflicts(conflicts, resolved_version=None)` | `None` | Set conflicts and optionally update recommended version |
| `get_conflict_summary()` | `List[str]` | Short, user-friendly conflict summaries |
| `get_conflict_details()` | `List[str]` | Detailed conflict descriptions |
| `get_status_summary()` | `Tuple[str, str, str, Optional[str]]` | Status, installed, latest, recommended |
| `to_json()` | `Dict[str, Any]` | JSON-safe package representation |

---

### Conflict

Represents a dependency conflict between two packages. This is a frozen dataclass (immutable after creation).

```python
from depkeeper.models import Conflict

conflict = Conflict(
    source_package="flask",
    target_package="werkzeug",
    required_spec=">=2.0,<3.0",
    conflicting_version="3.0.0",
    source_version="2.3.0",
)

print(conflict.to_display_string())
# flask==2.3.0 requires werkzeug>=2.0,<3.0
```

#### Attributes

| Attribute | Type | Description |
|---|---|---|
| `source_package` | `str` | Package declaring the dependency |
| `target_package` | `str` | Package being constrained |
| `required_spec` | `str` | Version specifier required by the source |
| `conflicting_version` | `str` | Version that violates the requirement |
| `source_version` | `Optional[str]` | Version of the source package |

#### Methods

| Method | Returns | Description |
|---|---|---|
| `to_display_string()` | `str` | Human-readable conflict description |
| `to_short_string()` | `str` | Compact conflict summary |
| `to_json()` | `Dict[str, Optional[str]]` | JSON-serializable representation |

---

### ConflictSet

Collection of conflicts affecting a single package. Provides utilities to find compatible versions.

#### Attributes

| Attribute | Type | Description |
|---|---|---|
| `package_name` | `str` | Name of the affected package |
| `conflicts` | `List[Conflict]` | Conflicts associated with this package |

#### Methods

| Method | Returns | Description |
|---|---|---|
| `add_conflict(conflict)` | `None` | Add a conflict to the set |
| `has_conflicts()` | `bool` | True if any conflicts exist |
| `get_max_compatible_version(available_versions)` | `Optional[str]` | Highest version compatible with all conflicts |

---

## Utilities

### HTTPClient

Async HTTP client with retry logic, rate limiting, concurrency control, and PyPI-specific error handling. Uses httpx with HTTP/2 support.

```python
from depkeeper.utils import HTTPClient

async def main():
    async with HTTPClient(timeout=30, max_retries=3) as http:
        # GET request
        response = await http.get("https://pypi.org/pypi/requests/json")

        # GET with JSON parsing
        data = await http.get_json("https://pypi.org/pypi/requests/json")

        # Batch concurrent JSON fetches
        results = await http.batch_get_json([
            "https://pypi.org/pypi/flask/json",
            "https://pypi.org/pypi/click/json",
        ])
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `timeout` | `int` | `30` | Request timeout in seconds |
| `max_retries` | `int` | `3` | Maximum retry attempts |
| `rate_limit_delay` | `float` | `0.0` | Minimum delay between requests |
| `verify_ssl` | `bool` | `True` | Verify SSL certificates |
| `user_agent` | `Optional[str]` | Auto-generated | Custom User-Agent header |
| `max_concurrency` | `int` | `10` | Maximum concurrent requests |

#### Methods

| Method | Returns | Description |
|---|---|---|
| `get(url)` | `httpx.Response` | GET request with retry logic |
| `post(url)` | `httpx.Response` | POST request with retry logic |
| `get_json(url)` | `Dict[str, Any]` | GET and parse JSON response |
| `batch_get_json(urls)` | `Dict[str, Dict[str, Any]]` | Concurrent JSON fetches |
| `close()` | `None` | Close the HTTP client |

---

### Console Utilities

User-facing output helpers built on the Rich library.

```python
from depkeeper.utils import (
    print_success,
    print_error,
    print_warning,
    print_table,
    confirm,
    get_raw_console,
)

# Status messages
print_success("Operation completed!")
print_error("Something went wrong")
print_warning("Proceed with caution")

# Rich table from list of dicts
print_table(
    data=[
        {"Name": "requests", "Version": "2.31.0"},
        {"Name": "flask", "Version": "2.3.3"},
    ],
    title="Packages",
)

# User confirmation prompt
if confirm("Apply 5 updates?", default=False):
    print("Applying...")

# Access underlying Rich Console
console = get_raw_console()
```

#### Functions

| Function | Parameters | Description |
|---|---|---|
| `print_success(message, prefix="[OK]")` | `str` | Print a styled success message |
| `print_error(message, prefix="[ERROR]")` | `str` | Print a styled error message |
| `print_warning(message, prefix="[WARNING]")` | `str` | Print a styled warning message |
| `print_table(data, headers=None, title=None, ...)` | `List[Dict]` | Render data as a Rich table |
| `confirm(message, default=False)` | `str, bool` | Prompt for yes/no confirmation |
| `get_raw_console()` | | Return the underlying Rich Console instance |
| `reconfigure_console()` | `None` | Reset the global console (useful after changing `NO_COLOR`) |
| `colorize_update_type(update_type)` | `str` | Return Rich-markup colored update type label |

---

### Filesystem Utilities

Safe file I/O helpers with backup, restore, and path validation support.

```python
from depkeeper.utils import (
    safe_read_file,
    safe_write_file,
    create_backup,
    restore_backup,
    create_timestamped_backup,
    find_requirements_files,
    validate_path,
)

# Read a file safely (with size limit)
content = safe_read_file("requirements.txt")

# Write with automatic backup
backup_path = safe_write_file("requirements.txt", new_content, create_backup=True)

# Find all requirements files in a directory
files = find_requirements_files(".", recursive=True)

# Validate a path stays within a base directory
resolved = validate_path("../requirements.txt", base_dir="/project")
```

#### Functions

| Function | Returns | Description |
|---|---|---|
| `safe_read_file(file_path, max_size=None, encoding="utf-8")` | `str` | Read a text file with optional size limit |
| `safe_write_file(file_path, content, create_backup=True)` | `Optional[Path]` | Atomic write with optional backup; returns backup path |
| `create_backup(file_path)` | `Path` | Create a timestamped backup of a file |
| `restore_backup(backup_path, target_path=None)` | `None` | Restore a file from a backup |
| `create_timestamped_backup(file_path)` | `Path` | Create a backup with `{stem}.{timestamp}.backup{suffix}` format |
| `find_requirements_files(directory=".", recursive=True)` | `List[Path]` | Find requirements files in a directory |
| `validate_path(path, base_dir=None)` | `Path` | Resolve and validate a path; raises `FileOperationError` if outside `base_dir` |

---

### Logging Utilities

Centralized logging setup for depkeeper.

```python
from depkeeper.utils import (
    get_logger,
    setup_logging,
    disable_logging,
    is_logging_configured,
)

# Get a named logger
logger = get_logger("my_module")
logger.info("Processing started")

# Configure logging level
setup_logging(verbosity=2)  # DEBUG level

# Check if logging has been configured
if not is_logging_configured():
    setup_logging(verbosity=0)

# Suppress all logging output
disable_logging()
```

#### Functions

| Function | Returns | Description |
|---|---|---|
| `get_logger(name=None)` | `logging.Logger` | Get a named logger under the `depkeeper` namespace |
| `setup_logging(verbosity=0)` | `None` | Configure logging level (0=WARNING, 1=INFO, 2=DEBUG) |
| `is_logging_configured()` | `bool` | Check if logging has already been set up |
| `disable_logging()` | `None` | Suppress all depkeeper log output |

---

### Version Utilities

Helpers for classifying version changes using PEP 440 parsing.

```python
from depkeeper.utils import get_update_type

get_update_type("1.0.0", "2.0.0")   # "major"
get_update_type("1.0.0", "1.1.0")   # "minor"
get_update_type("1.0.0", "1.0.1")   # "patch"
get_update_type(None, "1.0.0")       # "new"
get_update_type("1.0.0", "1.0.0")   # "same"
get_update_type("2.0.0", "1.0.0")   # "downgrade"
```

#### Functions

| Function | Returns | Description |
|---|---|---|
| `get_update_type(current_version, target_version)` | `str` | Classify the update type between two versions |

Return values: `"major"`, `"minor"`, `"patch"`, `"new"`, `"same"`, `"downgrade"`, `"update"`, `"unknown"`

---

### Exceptions

All exceptions inherit from `DepKeeperError` and support structured metadata via the `details` attribute.

**Exception hierarchy:**

- `DepKeeperError` (base)
    - `ParseError`
    - `NetworkError`
        - `PyPIError`
    - `FileOperationError`

| Exception | Description | Key Attributes |
|---|---|---|
| `DepKeeperError` | Base exception for all depkeeper errors | `message`, `details` |
| `ParseError` | Requirements file parsing failures | `line_number`, `line_content`, `file_path` |
| `NetworkError` | HTTP or network operation failures | `url`, `status_code`, `response_body` |
| `PyPIError` | PyPI API-specific failures | `package_name` (inherits `NetworkError`) |
| `FileOperationError` | File system operation failures | `file_path`, `operation`, `original_error` |

---

## Complete Example

```python
#!/usr/bin/env python3
"""Check and update dependencies programmatically."""

import asyncio

from depkeeper.core import (
    RequirementsParser,
    VersionChecker,
    DependencyAnalyzer,
    PyPIDataStore,
)
from depkeeper.utils import HTTPClient


async def analyze_requirements(file_path: str):
    """Analyze a requirements file and report on updates."""

    # Step 1: Parse requirements
    parser = RequirementsParser()
    requirements = parser.parse_file(file_path)
    print(f"Found {len(requirements)} packages\n")

    async with HTTPClient() as http:
        # Step 2: Create shared data store
        store = PyPIDataStore(http)

        # Step 3: Check versions
        checker = VersionChecker(data_store=store)
        packages = await checker.check_packages(requirements)

        # Step 4: Resolve conflicts
        analyzer = DependencyAnalyzer(data_store=store)
        result = await analyzer.resolve_and_annotate_conflicts(packages)

        # Step 5: Report results
        print(f"Converged: {result.converged} ({result.iterations_used} iterations)")
        print(f"Conflicts: {result.packages_with_conflicts}\n")

        for pkg in packages:
            if pkg.has_update():
                print(f"  {pkg.name}: {pkg.current_version} -> {pkg.recommended_version}")

    return packages


if __name__ == "__main__":
    asyncio.run(analyze_requirements("requirements.txt"))
```

---

## Configuration

### DepKeeperConfig

Dataclass representing a parsed and validated configuration file. All fields carry defaults, so an empty or missing configuration file produces a fully usable config object.

```python
from depkeeper.config import load_config, discover_config_file

# Auto-discover and load (depkeeper.toml or pyproject.toml)
config = load_config()

# Load from explicit path
config = load_config(Path("/project/depkeeper.toml"))

# Access values
print(config.check_conflicts)           # True
print(config.strict_version_matching)   # False
```

#### Functions

::: depkeeper.config
    options:
      show_root_heading: false
      members:
        - discover_config_file
        - load_config

#### Class

::: depkeeper.config.DepKeeperConfig
    options:
      show_root_heading: true
      members:
        - to_log_dict

#### Exception

::: depkeeper.config.ConfigError
    options:
      show_root_heading: true

---

## See Also

- [Getting Started](../getting-started/quickstart.md) -- Quick start guide
- [CLI Reference](cli-commands.md) -- Command-line interface
- [Configuration Guide](../guides/configuration.md) -- Configuration guide
- [Configuration Options](configuration-options.md) -- Full options reference
- [Contributing](../contributing/development-setup.md) -- Development guide
