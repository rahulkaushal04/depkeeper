---
title: Python API
description: Programmatic use of depkeeper's parser, data store, checker, analyzer, models and utilities
---

# Python API

depkeeper is primarily a CLI. Its internals are importable and documented here for tools that
need to embed dependency analysis.

> [!WARNING]
> **Stability**
>
> Only the CLI surface is covered by a compatibility guarantee in `0.1.x`. The Python API is
> documented but may change between minor versions. Pin the version if you depend on it.

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
from pathlib import Path

from depkeeper.core import DependencyAnalyzer, PyPIDataStore, VersionChecker
from depkeeper.core.sources import parse_targets
from depkeeper.utils import HTTPClient

async def analyse(path: str):
    requirements = parse_targets(Path(path))        # synchronous; any supported file type

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

Signatures use `Spec = Tuple[str, str]`, an `(operator, version)` pair such as `(">=", "2.0")`.

### RequirementsParser

`depkeeper.core.RequirementsParser()` is a stateful parser for pip-style requirements files. It
follows `-r` and `-c` includes.

| Member | Description |
|---|---|
| `parse_file(file_path, is_constraint_file=False) -> List[Requirement]` | Parse a file from disk. |
| `parse_string(requirements_content, source_file_path=None, is_constraint_file=False) -> List[Requirement]` | Parse requirements text. |
| `parse_line(line_text, line_number, source_file_path=None) -> Optional[Union[Requirement, List[Requirement]]]` | Parse one line. Returns `None` for blank and comment lines. |
| `get_constraints() -> Dict[str, Requirement]` | A copy of the constraints loaded via `-c`. |
| `reset() -> None` | Clear the include stack and constraints. |

### PyPIDataStore

`PyPIDataStore(http_client: HTTPClient, concurrent_limit: int = 10)` is an async-safe, per-process
cache of PyPI metadata. Share one instance.

| Member | Description |
|---|---|
| `await get_package_data(name) -> PyPIPackageData` | Fetch, or return cached, metadata. |
| `await prefetch_packages(names: List[str]) -> None` | Warm the cache concurrently. |
| `await get_version_dependencies(name, version) -> List[str]` | Base dependencies of one release. |
| `await get_version_digests(name, version) -> Optional[List[str]]` | Sorted, unique sha256 digests of a release's files. |
| `get_cached_package(name) -> Optional[PyPIPackageData]` | Cached data only; never fetches. |
| `get_versions(name) -> List[str]` | Cached stable versions, newest first. |
| `is_python_compatible(name, version, python_version) -> bool` | Compatibility check from cached metadata. |
| `get_current_python_version() -> str` | Static. The running interpreter as `major.minor.micro`. |

### PyPIPackageData

A dataclass snapshot of one package, shared by every caller. Treat it as read-only.

Fields: `name`, `latest_version`, `latest_requires_python`, `latest_dependencies`, `all_versions`,
`parsed_versions`, `python_requirements`, `releases`, `dependencies_cache`, `upload_times`,
`project_urls`.

| Method | Description |
|---|---|
| `release_links() -> Dict[str, str]` | Changelog, release-notes and homepage links from `project_urls`. |
| `get_versions_in_major(major: int) -> List[str]` | Stable versions sharing a major number. |
| `is_python_compatible(version, python_version) -> bool` | Whether a version supports a Python version. |
| `get_python_compatible_versions(python_version, major=None, include_prereleases=False) -> List[str]` | Stable versions compatible with a Python version. |

### VersionChecker

```python
VersionChecker(
    data_store: PyPIDataStore,
    infer_version_from_constraints: bool = True,
    target_python: Optional[str] = None,
    versioning: str = "auto",
    min_age: Optional[timedelta] = None,
    policies: Optional[Mapping[str, PackagePolicy]] = None,
    clock: Optional[Callable[[], datetime]] = None,
    allow_major: Iterable[str] = (),
    max_update: Optional[str] = None,
)
```

Computes recommendations without crossing a major version boundary.

| Member | Description |
|---|---|
| `from_config(data_store, config: DepKeeperConfig, **overrides) -> VersionChecker` | Classmethod. Build a checker from a loaded config. |
| `await get_package_info(name, current_version=None, constraints=None, series=None) -> Package` | Fetch metadata and compute a recommendation for one package. |
| `await check_packages(requirements: List[Requirement]) -> List[Package]` | Check many packages concurrently. |
| `extract_current_version(req: Requirement) -> Optional[str]` | Infer a "current" version from a requirement's specifiers. |
| `create_unavailable_package(name, current_version) -> Package` | A stub `Package` for when PyPI data is unavailable. |
| `restrict_versions(pkg_data, versions, current_version, scheme="semver") -> List[str]` | Apply hold/ignore, `max_update` and the cooldown. |
| `include_prereleases(name) -> bool` | Whether the per-package policy allows pre-releases. |
| `allows_major(name) -> bool` | Whether `allow_major` (the `--allow-major` names, `*`, or the package policy) lets this package cross its major. |

### DependencyAnalyzer

```python
DependencyAnalyzer(
    data_store: PyPIDataStore,
    concurrent_limit: int = 10,
    target_python: Optional[str] = None,
    checker: Optional[VersionChecker] = None,
)
```

Detects and resolves version conflicts within major version boundaries.

| Member | Description |
|---|---|
| `await resolve_and_annotate_conflicts(packages: List[Package]) -> ResolutionResult` | Resolve conflicts and update each `Package` in place. |
| `find_compatible_version(conflict_set, available_versions, min_version=None) -> Optional[str]` | The highest version satisfying a `ConflictSet`. |

### ResolutionResult

A dataclass with fields `resolved_versions: Dict[str, PackageResolution]`, `total_packages`,
`packages_with_conflicts`, `iterations_used` and `converged`.

| Method | Description |
|---|---|
| `get_changed_packages() -> List[PackageResolution]` | Packages whose resolved version differs from the original. |
| `get_conflicts() -> List[PackageResolution]` | Packages with at least one recorded conflict. |
| `summary() -> str` | A human-readable summary of the run. |

### PackageResolution

A dataclass with fields `name`, `original`, `resolved`, `status: ResolutionStatus`,
`conflicts: List[Conflict]` and `compatible_alternative`. Methods: `was_changed() -> bool` and
`has_conflicts() -> bool`.

### ResolutionStatus

An `Enum` with the members `KEPT_RECOMMENDED`, `UPGRADED`, `DOWNGRADED`, `KEPT_CURRENT` and
`CONSTRAINED`.

---

## Models

### Requirement

A dataclass for one requirement line.

Fields: `name`, `specs`, `extras`, `markers`, `url`, `editable`, `hashes`, `comment`,
`line_number`, `raw_line`, `source_file`, `constraint_specs`, `direct_reference`, `source_format`,
`span`, `approximate`, `series`.

| Method | Description |
|---|---|
| `to_string(*, include_hashes=True, include_comment=True) -> str` | The canonical `requirements.txt` form. |
| `update_version(new_version, *, pin=False, preserve_trailing_newline=True, allow_hash_removal=False) -> str` | The requirement string updated to a version. Does not write anything. |

### Package

A dataclass holding version and compatibility state for one package.

Fields: `name`, `current_version`, `latest_version`, `recommended_version`, `metadata`,
`conflicts`, `retained_specs`, `versioning`, `held`, `ignored`, `recommended_released`,
`current_released`, `latest_released`, `cooldown_skipped`, `conflict_held`, `major_available`,
`major_capped`.

Properties: `current`, `latest`, `recommended` (parsed versions), `requires_downgrade`,
`update_type`.

| Method | Description |
|---|---|
| `has_update() -> bool` | The recommended version is newer than the current one. |
| `has_conflicts() -> bool` | Conflicts were recorded. |
| `set_conflicts(conflicts, *, resolved_version=None) -> None` | Record conflicts and optionally override the recommendation. |
| `get_conflict_summary() -> List[str]` | One short summary per conflict. |
| `get_conflict_details() -> List[str]` | One detailed description per conflict. |
| `recommended_age_days(now=None) -> Optional[int]` | Whole days since the recommended version was uploaded. |
| `get_version_python_req(version_key) -> Optional[str]` | The `requires_python` specifier for one version slot. |
| `get_status_summary() -> Tuple[str, str, str, Optional[str]]` | The status used by line-based output. |
| `to_json() -> Dict[str, Any]` | A JSON-compatible dictionary. |
| `render_python_compatibility() -> str` | A multi-line cell for the table view. |
| `get_display_data() -> Dict[str, Any]` | Derived values for UI rendering. |

### Conflict

A dataclass with fields `source_package`, `target_package`, `required_spec`, `conflicting_version`
and `source_version`. Methods: `to_display_string() -> str`, `to_short_string() -> str` and
`to_json() -> Dict[str, Optional[str]]`.

### ConflictSet

A dataclass with fields `package_name` and `conflicts: List[Conflict]`.

| Method | Description |
|---|---|
| `add_conflict(conflict) -> None` | Append a conflict. |
| `has_conflicts() -> bool` | The set holds at least one conflict. |
| `get_max_compatible_version(available_versions) -> Optional[str]` | The highest version satisfying every conflict. |

---

## Configuration

From `depkeeper.config`.

| Name | Description |
|---|---|
| `DepKeeperConfig` | Dataclass of validated settings: `check_conflicts=True`, `strict_version_matching=False`, `fail_on="none"`, `ignore`, `python_version`, `min_age`, `versioning="auto"`, `packages`, `source_path`. `to_log_dict() -> Dict[str, Any]` returns it for debug logging. |
| `PackagePolicy` | Per-package policy dataclass: `max_update=None`, `hold=False`, `allow_prerelease=False`, `versioning=None`, `ignore=False`, `allow_major=False`. |
| `parse_duration(value: Union[str, int, float]) -> timedelta` | Parse a `min_age` value (`7`, `"12h"`, `"2w"`); raises `ValueError`. |
| `load_config(config_path: Optional[Path] = None) -> DepKeeperConfig` | Load and validate a configuration. |
| `discover_config_file(explicit_path: Optional[Path] = None) -> Optional[Path]` | Find the configuration file to load. |

---

## Utilities

### HTTP client

```python
HTTPClient(
    *,
    timeout: int = 30,
    max_retries: int = 3,
    rate_limit_delay: float = 0.0,
    verify_ssl: bool = True,
    user_agent: Optional[str] = None,
    max_concurrency: int = 10,
    total_timeout: float = 180.0,
    max_response_bytes: int = 20971520,
)
```

Asynchronous client with retries, rate limiting and concurrency control. Use it as an async
context manager.

| Method | Description |
|---|---|
| `await get(url, **kwargs) -> httpx.Response` | GET request. |
| `await post(url, **kwargs) -> httpx.Response` | POST request. |
| `await get_json(url, **kwargs) -> Dict[str, Any]` | Fetch a URL and decode a JSON object. |
| `await batch_get_json(urls, *, progress_callback=None) -> Dict[str, Dict[str, Any]]` | Fetch many JSON endpoints concurrently. |
| `await close() -> None` | Close the underlying client. |

### Version utilities

From `depkeeper.utils.version_utils`.

| Function | Description |
|---|---|
| `get_update_type(current_version, target_version, versioning="semver") -> str` | The update type between two versions. |
| `retained_specs(specs) -> List[Spec]` | Specifiers that survive a rewrite unchanged. |
| `rewrite_version_specs(specs, new_version) -> List[Spec]` | Rewrite a specifier set to target a version. |
| `specs_allow_version(specs, version) -> bool` | Whether a version satisfies every specifier. |
| `specs_to_string(specs) -> str` | Render specs as a PEP 440 specifier string. |
| `is_lower_bound(operator) -> bool` | Whether an operator constrains only the floor of a range. |

### Source adapters

From `depkeeper.core.sources`; they read `requirements*.txt`, `pyproject.toml` and `environment.yml` and are what the CLI uses.

| Function | Description |
|---|---|
| `parse_targets(path: Path) -> List[Requirement]` | Parse a file or a directory of supported files into one list (`Requirement.source_file`/`source_format` are set). |
| `resolve_targets(path: Path) -> List[Path]` | Expand a file or directory to the files to process. |
| `default_target(file: Optional[Path]) -> Path` | The CLI's default (`requirements.txt`, else the current directory). |
| `discover(directory) -> List[Path]` | Supported dependency files in a directory (not recursive). |
| `get_adapter(path) -> SourceAdapter` | The adapter for a file. |

`RequirementsParser` handles `requirements.txt` syntax only; use `parse_targets` for `pyproject.toml` and conda files.

### Name canonicalisation

`normalize_package_name(name: str) -> str` returns the canonical PEP 503 form of a distribution
name.

### Filesystem utilities

> [!WARNING]
> **Two backup layouts exist**
>
> `create_timestamped_backup` produces `<stem>.<timestamp>_<uuid8>.backup<suffix>` — this is
> what the CLI uses. `create_backup` produces `<name><suffix>.<timestamp>_<uuid8>.backup`, and
> `restore_backup`'s target inference only understands **that** layout. Restore a
> CLI-produced backup by copying it manually.

| Function | Description |
|---|---|
| `safe_read_file(file_path, *, max_size=10485760, encoding="utf-8-sig", newline=None) -> str` | Read a text file with a size limit. |
| `safe_write_file(file_path, content, *, create_backup=True, encoding="utf-8") -> Optional[Path]` | Write text with atomic replacement. |
| `create_timestamped_backup(file_path) -> Path` | Back up to `<stem>.<timestamp>_<uuid>.backup<suffix>`. |
| `create_backup(file_path) -> Path` | Back up a file with a timestamped name. |
| `restore_backup(backup_path, target_path=None) -> None` | Restore a file made by `create_backup`. |
| `find_requirements_files(directory=".", *, recursive=True) -> List[Path]` | Discover requirements files under a directory. |
| `validate_path(path, *, base_dir=None) -> Path` | Resolve a path, optionally confined to a base directory. |

### Console

Every helper accepts a `stderr` keyword. `print_error` defaults to `stderr=True`; the others
default to stdout. Commands emitting machine-readable payloads must pass `stderr=True` for all
status output.

| Function | Description |
|---|---|
| `print_success(message, *, prefix="[OK]", stderr=False) -> None` | Print a success message. |
| `print_warning(message, *, prefix="[WARNING]", stderr=False) -> None` | Print a warning. |
| `print_error(message, *, prefix="[ERROR]", stderr=True) -> None` | Print an error. |
| `print_table(data, *, headers=None, title=None, caption=None, column_styles=None, row_styler=None, show_row_lines=False, stderr=False) -> None` | Render a list of dicts as a Rich table. |
| `get_raw_console(*, stderr=False) -> Console` | The underlying Rich `Console`. |
| `reconfigure_console() -> None` | Discard the memoised stdout and stderr consoles. |
| `colorize_update_type(update_type) -> str` | Wrap an update-type label in Rich markup. |
| `confirm(message, *, default=False) -> bool` | Ask a yes/no question on stdout. |

### Logging

> [!WARNING]
> **`setup_logging` reconfigures the process**
>
> It clears handlers on the shared `depkeeper` logger, installs its own, and sets
> `propagate = False`. Embedding depkeeper means its records will not reach your root logger
> unless you reconfigure afterwards. Tests must snapshot and restore that logger.

| Function | Description |
|---|---|
| `setup_logging(*, level=20, verbose=False, stream=None) -> None` | Configure the `depkeeper` logger hierarchy. |
| `get_logger(name=None) -> logging.Logger` | A logger in the `depkeeper` namespace. |
| `disable_logging() -> None` | Silence all depkeeper logging and reset the configured flag. |
| `is_logging_configured() -> bool` | Whether `setup_logging` has run since the last reset. |

---

## Exceptions

From `depkeeper.exceptions`. All derive from `DepKeeperError`.

| Exception | Base | Constructor |
|---|---|---|
| `DepKeeperError` | `Exception` | `(message, details=None)` |
| `ParseError` | `DepKeeperError` | `(message, *, line_number=None, line_content=None, file_path=None)` |
| `ConfigError` | `DepKeeperError` | `(message, *, config_path=None, option=None)` |
| `FileOperationError` | `DepKeeperError` | `(message, *, file_path=None, operation=None, original_error=None)` |
| `NetworkError` | `DepKeeperError` | `(message, *, url=None, status_code=None, response_body=None)` |
| `PyPIError` | `NetworkError` | `(message, *, package_name=None, **kwargs)` |

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
