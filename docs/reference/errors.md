---
title: Error Reference
description: Exception hierarchy and a catalogue of user-visible messages
---

# Error Reference

## Exception hierarchy

```text
Exception
└── DepKeeperError                  message + structured `details`
    ├── ParseError                  line_number, line_content, file_path
    ├── ConfigError                 config_path, option
    ├── FileOperationError          file_path, operation, original_error
    └── NetworkError                url, status_code, response_body
        └── PyPIError               package_name
```

Every depkeeper exception carries a `details` mapping that is appended to `str(exc)` as
`key=value` pairs:

```text
[ERROR] Unknown configuration keys: check_conflict (config_path=/path/depkeeper.toml)
```

`PyPIError` subclasses `NetworkError`, so a single `except NetworkError` handler covers 404s,
timeouts, `429` exhaustion and 5xx. Long response bodies are truncated to 200 characters before
being recorded.

All exception classes use `__slots__` and are importable from `depkeeper.exceptions`.

---

## `ParseError`

Raised by the parser. Attributes: `line_number`, `line_content`, `file_path`.

| Message | Cause | Fix |
|---|---|---|
| `Invalid requirement syntax: <packaging detail>` | The line is not valid PEP 508. | Correct the line. Note that backslash continuations are not joined. |
| `Invalid version specifier: empty version in '<op>'` | A specifier parsed with no version. | Supply a version. |
| `Circular dependency detected: a.txt -> b.txt -> a.txt` | `-r` include cycle. | Break the cycle. |
| `Failed to process include directive: <detail>` | The included file is missing or invalid. | The message names the including line; fix the referenced file. |
| `Failed to process constraint directive: <detail>` | Same, for `-c`. | Fix the constraint file. |
| `URL requirements must include '#egg=<name>' or an inferable package name.` | A direct URL with no usable name. | Add `#egg=<name>`. |

Surfaced by the CLI as `Failed to parse <file>: <detail>` with exit code `1`.

---

## `ConfigError`

Raised during configuration discovery, decoding, parsing and validation. Attributes:
`config_path`, `option`.

| Message | Cause |
|---|---|
| `Configuration file not found: <path>` | An explicit `--config` path does not exist. |
| `Cannot read configuration file <path>: <detail>` | Permission or I/O error. |
| `Configuration file <name> is not valid UTF-8: <detail>` | Wrong encoding. |
| `Invalid TOML in <name>: <detail>` | Syntax error. |
| `Unknown configuration keys: <keys>` | A key outside `{check_conflicts, strict_version_matching}`. |
| `<option> must be a boolean, got <type>` | Wrong value type. |

Exit code `1`. Raised before any command runs.

---

## `FileOperationError`

Raised by the filesystem layer. Attributes: `file_path`, `operation`
(`read` / `write` / `backup` / `restore` / `validate`), `original_error`.

| Message | Cause |
|---|---|
| `File not found: <path>` | Missing input. |
| `Not a file: <path>` | A directory or special file was supplied. |
| `File too large: <n> bytes (max 10485760)` | Exceeds the 10 MB guard. |
| `Failed to read file: <detail>` | Decode or I/O failure. |
| `Atomic write failed: <detail>` | The temporary file could not be written or renamed. The temporary file is removed and the target left untouched. |
| `Failed to create backup: <detail>` | `--backup` could not copy a file. |
| `Failed to restore backup: <detail>` | A restore failed. |
| `Path outside allowed base directory: <path>` | `validate_path` traversal guard (programmatic use). |

---

## `NetworkError` and `PyPIError`

| Message | Class | Retried? |
|---|---|---|
| `Package '<name>' not found on PyPI` | `PyPIError` | No — a 404 will not change. |
| `PyPI returned status <code> for '<name>'` | `PyPIError` | No. |
| `Resource not found: <url>` | `PyPIError` | No. |
| `HTTP <4xx> error for <url>` | `NetworkError` | No — client errors are not retried. |
| `Rate limit exceeded after 5 retries` | `NetworkError` | The `429` budget was exhausted. `Retry-After` was honoured. |
| `Request failed after 4 attempts: <url>` | `NetworkError` | Yes — timeouts, network errors and 5xx were retried with backoff. |
| `Invalid JSON response from <url>` | `NetworkError` | No. |

### How network failures are absorbed

Network errors for an individual package rarely reach the user as an error:

| Layer | Behaviour |
|---|---|
| `VersionChecker.get_package_info` | Catches `NetworkError`, logs `Package '<name>' unavailable; creating stub` at WARNING, returns an unavailable stub. |
| `VersionChecker.check_packages` | Any exception from a per-package task is caught and replaced with a stub. |
| `PyPIDataStore.prefetch_packages` | Per-package failures are swallowed; the checker retries afterwards. |
| `DependencyAnalyzer._get_package_data_or_none` | Catches `NetworkError`, logs once at WARNING, negatively caches the name for the run, and returns `None` so the "revert both to current" fallback applies. |
| `PyPIDataStore._fetch_version_dependencies` | Any exception is logged at DEBUG and an empty dependency list is returned. |

The consequence: a run completes and reports, even with total network failure. Every package
simply becomes an `[ERROR]` row.

---

## Command-level errors

Raised as plain `DepKeeperError` by the command layer.

| Message | Command | Cause |
|---|---|---|
| `Failed to parse <file>: <detail>` | both | A `ParseError` reached the command. |
| `Refusing to update requirement(s) with --hash entries: <names>. Hashes are version-specific and cannot be silently removed. Re-run with --allow-hash-removal to proceed without hashes.` | `update` | Pre-flight hash guard. |
| `Refusing to update hashed requirement at <file>:<line>. Re-run with --allow-hash-removal to proceed without hashes.` | `update` | Per-line hash guard during rendering. |
| `Cannot update requirement at <file>:<line>: <detail>` | `update` | `Requirement.update_version` refused to produce an unsatisfiable line. |
| `Failed to read <path>: <detail>` | `update` | A file could not be read during rendering. |
| `Failed to write <path>: <detail>` | `update` | A commit failed; earlier commits in the batch were rolled back. |
| `Failed to apply updates: <detail>` | `update` | The outer wrapper. Backups, if taken, have been restored. |
| `Unexpected error: <detail>` | both | Any non-depkeeper exception. Full traceback at `-vv`. |

---

## Warnings (not errors)

These are printed to stderr and do **not** change the exit code.

| Message | Meaning |
|---|---|
| `Package '<name>' unavailable; creating stub` | PyPI metadata could not be fetched. |
| `PyPI metadata for '<name>' is unavailable (<detail>); conflict resolution will skip this package` | The analyzer negatively cached the package. |
| `Skipping <pkg>: <version> is excluded by the declared constraint '<specs>' (use --pin to replace the constraint)` | The resolver proposed a version your file forbids. |
| `Proceeding with --allow-hash-removal: hashes will be removed for <names>` | Integrity opt-out acknowledged. |
| `<n> package(s) have unresolved conflicts — updates may cause issues` | Review the plan before applying. |
| `No compatible version found for A ↔ B within major boundaries; reverting both` | Neither strategy succeeded; no change proposed for either package. |
| `Conflict resolution stalled after <n> iteration(s)` | A pass changed nothing; the loop stopped early. |
| `Conflict resolution did not converge within 100 iterations` | The iteration budget was exhausted. |
| `<pkg>: no eligible version found in major <n> (Python <v>, constraints '<specs>'), staying on <version>` | Every candidate was eliminated by a filter. |
| `Line <n>: URL without '#egg=' - inferred name '<name>'` | The inferred name may be wrong. |
| `Line <n>: Include directive missing file path` | A malformed `-r` line was skipped. |
| `No matching packages found: <names>` | `--packages` matched nothing. |
| `No packages found in requirements file` | The file parsed to zero requirements. |
| `Operation cancelled by user` | `Ctrl+C`. |

---

## Handling errors programmatically

```python
from depkeeper.exceptions import (
    DepKeeperError, ParseError, ConfigError, FileOperationError, NetworkError, PyPIError,
)

try:
    requirements = parser.parse_file("requirements.txt")
except ParseError as exc:
    print(f"{exc.file_path}:{exc.line_number}: {exc.message}")
    print(f"  {exc.line_content}")
except FileOperationError as exc:
    print(f"{exc.operation} failed on {exc.file_path}: {exc.original_error}")
except DepKeeperError as exc:
    print(exc.message, dict(exc.details))
```

```python
try:
    data = await store.get_package_data("requests")
except PyPIError as exc:          # 404 / unexpected status
    print(exc.package_name, exc.status_code)
except NetworkError as exc:       # timeout, 429 exhaustion, 5xx
    print(exc.url, exc.status_code)
```

Catch `NetworkError` rather than `PyPIError` unless you specifically need the package-name
attribute — the broader class is what the rest of the codebase catches.
