---
title: Python API
description: Programmatic use of depkeeper's parser, data store, checker, analyzer, models and utilities
---

# Python API

depkeeper is primarily a CLI. Its internals are importable and documented here for tools that
need to embed dependency analysis.

!!! warning "Stability"

    Only the CLI surface is covered by a compatibility guarantee in `0.1.x`. The Python API is
    documented but may change between minor versions. Pin the version if you depend on it.

---

## Design rules you must follow

| Rule | Reason |
|---|---|
| Everything network-facing is `async`. | All I/O is asyncio-based. Drive it with `asyncio.run`. |
| `HTTPClient` must be used as an async context manager. | The underlying `httpx.AsyncClient` is created lazily and bound to the running loop. |
| Construct **one** `PyPIDataStore` and share it. | This is what guarantees one HTTP request per package. |
| `VersionChecker` and `DependencyAnalyzer` require a data store. | Passing `None` raises `TypeError`; they have no independent HTTP path. |
| Canonicalise names with `normalize_package_name`. | Every cache, mapping and comparison in depkeeper is keyed on the PEP 503 form. |
| `DependencyAnalyzer` mutates its input. | `resolve_and_annotate_conflicts` updates each `Package` in place. |

---

## End-to-end example

```python
import asyncio

from depkeeper.core import (
    DependencyAnalyzer,
    PyPIDataStore,
    RequirementsParser,
    VersionChecker,
)
from depkeeper.utils import HTTPClient


async def analyse(path: str):
    parser = RequirementsParser()
    requirements = parser.parse_file(path)          # synchronous

    async with HTTPClient() as http:
        store = PyPIDataStore(http)                 # one store, shared
        await store.prefetch_packages([r.name for r in requirements])

        checker = VersionChecker(data_store=store)
        packages = await checker.check_packages(requirements)

        analyzer = DependencyAnalyzer(data_store=store)
        result = await analyzer.resolve_and_annotate_conflicts(packages)

    return packages, result


packages, result = asyncio.run(analyse("requirements.txt"))

for pkg in packages:
    if pkg.has_update():
        print(f"{pkg.name}: {pkg.current_version} -> {pkg.recommended_version}")

print(result.summary())
```

### Rendering an update without writing

```python
from depkeeper.core import RequirementsParser

parser = RequirementsParser()
req = parser.parse_line("celery[redis]>=5.0,<6.0  # queue", 1)

req.update_version("5.6.3")
# 'celery[redis]>=5.6.3,<6.0  # queue\n'

req.update_version("5.6.3", pin=True)
# 'celery[redis]==5.6.3  # queue\n'
```

### Overriding network limits

```python
from depkeeper.core import PyPIDataStore
from depkeeper.utils import HTTPClient

async with HTTPClient(timeout=10, max_retries=1, max_concurrency=4,
                      rate_limit_delay=0.25) as http:
    store = PyPIDataStore(http, concurrent_limit=4)
    ...
```

This is the only supported way to change timeouts, retry counts or concurrency — the CLI exposes
no flags for them.

---

## Package exports

```python
from depkeeper.core import (
    RequirementsParser, PyPIDataStore, PyPIPackageData,
    VersionChecker, DependencyAnalyzer, ResolutionResult,
)
from depkeeper.models import Package, Requirement, Conflict
from depkeeper.utils import (
    HTTPClient, get_logger, setup_logging,
    normalize_package_name, get_update_type,
    retained_specs, rewrite_version_specs, specs_allow_version, specs_to_string,
    safe_read_file, safe_write_file, create_timestamped_backup,
)
from depkeeper.exceptions import (
    DepKeeperError, ParseError, ConfigError, FileOperationError, NetworkError, PyPIError,
)
```

Importing from `depkeeper.core` and `depkeeper.utils` rather than from the concrete modules keeps
your code stable if the internal layout changes.

---

## Core

### RequirementsParser

::: depkeeper.core.parser.RequirementsParser
    options:
      heading_level: 4

### PyPIDataStore

::: depkeeper.core.data_store.PyPIDataStore
    options:
      heading_level: 4

### PyPIPackageData

::: depkeeper.core.data_store.PyPIPackageData
    options:
      heading_level: 4

### VersionChecker

::: depkeeper.core.checker.VersionChecker
    options:
      heading_level: 4

### DependencyAnalyzer

::: depkeeper.core.dependency_analyzer.DependencyAnalyzer
    options:
      heading_level: 4

### ResolutionResult

::: depkeeper.core.dependency_analyzer.ResolutionResult
    options:
      heading_level: 4

### PackageResolution

::: depkeeper.core.dependency_analyzer.PackageResolution
    options:
      heading_level: 4

### ResolutionStatus

::: depkeeper.core.dependency_analyzer.ResolutionStatus
    options:
      heading_level: 4

---

## Models

### Requirement

::: depkeeper.models.requirement.Requirement
    options:
      heading_level: 4

### Package

::: depkeeper.models.package.Package
    options:
      heading_level: 4

### Conflict

::: depkeeper.models.conflict.Conflict
    options:
      heading_level: 4

### ConflictSet

::: depkeeper.models.conflict.ConflictSet
    options:
      heading_level: 4

---

## Configuration

::: depkeeper.config.DepKeeperConfig
    options:
      heading_level: 3

::: depkeeper.config.load_config
    options:
      heading_level: 3

::: depkeeper.config.discover_config_file
    options:
      heading_level: 3

---

## Utilities

### HTTP client

::: depkeeper.utils.http.HTTPClient
    options:
      heading_level: 4

### Version utilities

::: depkeeper.utils.version_utils.get_update_type
    options:
      heading_level: 4

::: depkeeper.utils.version_utils.retained_specs
    options:
      heading_level: 4

::: depkeeper.utils.version_utils.rewrite_version_specs
    options:
      heading_level: 4

::: depkeeper.utils.version_utils.specs_allow_version
    options:
      heading_level: 4

::: depkeeper.utils.version_utils.specs_to_string
    options:
      heading_level: 4

::: depkeeper.utils.version_utils.is_lower_bound
    options:
      heading_level: 4

### Name canonicalisation

::: depkeeper.utils.naming.normalize_package_name
    options:
      heading_level: 4

### Filesystem utilities

!!! warning "Two backup layouts exist"

    `create_timestamped_backup` produces `<stem>.<timestamp>_<uuid8>.backup<suffix>` — this is
    what the CLI uses. `create_backup` produces `<name><suffix>.<timestamp>_<uuid8>.backup`, and
    `restore_backup`'s target inference only understands **that** layout. Restore a
    CLI-produced backup by copying it manually.

::: depkeeper.utils.filesystem.safe_read_file
    options:
      heading_level: 4

::: depkeeper.utils.filesystem.safe_write_file
    options:
      heading_level: 4

::: depkeeper.utils.filesystem.create_timestamped_backup
    options:
      heading_level: 4

::: depkeeper.utils.filesystem.create_backup
    options:
      heading_level: 4

::: depkeeper.utils.filesystem.restore_backup
    options:
      heading_level: 4

::: depkeeper.utils.filesystem.find_requirements_files
    options:
      heading_level: 4

::: depkeeper.utils.filesystem.validate_path
    options:
      heading_level: 4

### Console

Every helper accepts a `stderr` keyword. `print_error` defaults to `stderr=True`; the others
default to stdout. Commands emitting machine-readable payloads must pass `stderr=True` for all
status output.

::: depkeeper.utils.console.print_success
    options:
      heading_level: 4

::: depkeeper.utils.console.print_warning
    options:
      heading_level: 4

::: depkeeper.utils.console.print_error
    options:
      heading_level: 4

::: depkeeper.utils.console.print_table
    options:
      heading_level: 4

::: depkeeper.utils.console.get_raw_console
    options:
      heading_level: 4

::: depkeeper.utils.console.reconfigure_console
    options:
      heading_level: 4

::: depkeeper.utils.console.colorize_update_type
    options:
      heading_level: 4

::: depkeeper.utils.console.confirm
    options:
      heading_level: 4

### Logging

!!! warning "`setup_logging` reconfigures the process"

    It clears handlers on the shared `depkeeper` logger, installs its own, and sets
    `propagate = False`. Embedding depkeeper means its records will not reach your root logger
    unless you reconfigure afterwards. Tests must snapshot and restore that logger.

::: depkeeper.utils.logger.setup_logging
    options:
      heading_level: 4

::: depkeeper.utils.logger.get_logger
    options:
      heading_level: 4

::: depkeeper.utils.logger.disable_logging
    options:
      heading_level: 4

::: depkeeper.utils.logger.is_logging_configured
    options:
      heading_level: 4

---

## Exceptions

::: depkeeper.exceptions.DepKeeperError
    options:
      heading_level: 3

::: depkeeper.exceptions.ParseError
    options:
      heading_level: 3

::: depkeeper.exceptions.ConfigError
    options:
      heading_level: 3

::: depkeeper.exceptions.FileOperationError
    options:
      heading_level: 3

::: depkeeper.exceptions.NetworkError
    options:
      heading_level: 3

::: depkeeper.exceptions.PyPIError
    options:
      heading_level: 3

---

## Recipes

### Just the recommendation for one package

```python
import asyncio
from depkeeper.core import PyPIDataStore, VersionChecker
from depkeeper.utils import HTTPClient


async def recommend(name: str, current: str) -> str | None:
    async with HTTPClient() as http:
        checker = VersionChecker(data_store=PyPIDataStore(http))
        pkg = await checker.get_package_info(name, current)
        return pkg.recommended_version


print(asyncio.run(recommend("urllib3", "1.26.0")))   # '1.26.20'
```

### Detect conflicts without touching any file

```python
import asyncio
from depkeeper.core import DependencyAnalyzer, PyPIDataStore, VersionChecker
from depkeeper.models import Requirement
from depkeeper.utils import HTTPClient


async def conflicts(requirements: list[Requirement]):
    async with HTTPClient() as http:
        store = PyPIDataStore(http)
        packages = await VersionChecker(data_store=store).check_packages(requirements)
        result = await DependencyAnalyzer(data_store=store).resolve_and_annotate_conflicts(packages)
        return result.get_conflicts()
```

### Silence depkeeper's logging in an embedding application

```python
from depkeeper.utils import disable_logging

disable_logging()
```
