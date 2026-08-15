---
title: Configuration Options
description: Every configuration key, environment variable, discovery and validation rule
---

# Configuration Options

Task-oriented guidance is in [Configuration](../guides/configuration.md). This page is the
specification.

---

## Keys

### `check_conflicts`

| Property | Value |
|---|---|
| Type | boolean |
| Default | `true` |
| CLI override | `--check-conflicts` / `--no-check-conflicts` |
| Applies to | `check`, `update` |

Enables cross-package conflict resolution. When disabled, recommendations are computed per package
in isolation and may be mutually inconsistent; the Resolution Summary is not produced.

```toml
[depkeeper]
check_conflicts = true
```

### `strict_version_matching`

| Property | Value |
|---|---|
| Type | boolean |
| Default | `false` |
| CLI override | `--strict-version-matching` (no negative form) |
| Applies to | `check`, `update` |

When `true`, only a requirement whose **sole** specifier is `==` yields a current version. Ranges
such as `>=2.0` are treated as "no current version", which removes the major-version anchor and
changes the reported status to `install`.

```toml
[depkeeper]
strict_version_matching = false
```

### Unknown keys

Any other key is a hard error:

```text
[ERROR] Unknown configuration keys: check_conflict (config_path=/path/depkeeper.toml)
```

Exit code `1`. Keys are validated against the exact set `{check_conflicts,
strict_version_matching}`. Nested tables are not supported.

### Type validation

```text
[ERROR] check_conflicts must be a boolean, got str (config_path=..., option=check_conflicts)
```

TOML booleans only: `true` / `false`, unquoted.

---

## File formats

=== "depkeeper.toml"

    ```toml
    [depkeeper]
    check_conflicts = true
    strict_version_matching = false
    ```

=== "pyproject.toml"

    ```toml
    [tool.depkeeper]
    check_conflicts = true
    strict_version_matching = false
    ```

---

## Discovery

| Order | Source | Condition |
|---|---|---|
| 1 | `--config` / `-c`, or `DEPKEEPER_CONFIG` | Must exist and be a file, otherwise `ConfigError`. |
| 2 | `./depkeeper.toml` | Must exist in the **current working directory**. |
| 3 | `./pyproject.toml` | Adopted **only if** it contains a `[tool.depkeeper]` table. |
| 4 | Built-in defaults | Always. |

Notes:

- Discovery is not recursive; parent directories are not searched.
- A `pyproject.toml` whose parse fails during the `[tool.depkeeper]` probe is treated as "no
  depkeeper section" and skipped silently, so a malformed unrelated `pyproject.toml` cannot break
  a depkeeper run.
- A discovered file with an empty or absent depkeeper section is valid and yields the defaults,
  with `source_path` recorded.

### Encoding

Configuration files are read as bytes and decoded with `utf-8-sig`, so a leading byte order mark
is removed before parsing (TOML parsers reject a BOM as an invalid statement).

| Failure | Message |
|---|---|
| Not valid UTF-8 | `Configuration file <name> is not valid UTF-8: <detail>` |
| Invalid TOML | `Invalid TOML in <name>: <detail>` |
| Unreadable | `Cannot read configuration file <path>: <detail>` |

TOML parsing is always performed by `tomli`, a hard runtime dependency, so Python 3.8–3.10 and
3.11+ behave identically.

---

## Precedence

```text
built-in defaults  <  configuration file  <  command-line flag
```

Both `--strict-version-matching` and `--check-conflicts` default to an internal "unset" value, so
omitting them means "use the configuration value".

| Config | CLI | Effective |
|---|---|---|
| *(none)* | *(none)* | default |
| `check_conflicts = false` | *(none)* | `false` |
| `check_conflicts = false` | `--check-conflicts` | `true` |
| `check_conflicts = true` | `--no-check-conflicts` | `false` |
| `strict_version_matching = true` | *(none)* | `true` |
| `strict_version_matching = true` | *(no negative form exists)* | `true` |

---

## Environment variables

| Variable | Consumed by | Effect |
|---|---|---|
| `DEPKEEPER_CONFIG` | Click, as the default for `--config` | Path to a configuration file. |
| `DEPKEEPER_COLOR` | Click, as the default for `--color/--no-color` | Standard boolean spellings: `1`/`0`, `true`/`false`, `yes`/`no`. |
| `NO_COLOR` | `rich`, `click`, `depkeeper.utils.logger` | Any non-empty value disables colour. depkeeper **sets** it when `--no-color` is resolved and **clears** it when `--color` is resolved, so downstream libraries follow the flag. |
| `CI` | `depkeeper.utils.logger` | Any non-empty value disables ANSI colour in log records. |
| `HTTPS_PROXY` / `HTTP_PROXY` / `NO_PROXY` | `httpx` | Proxy configuration. |
| `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` | `httpx` / `certifi` | Custom CA bundle for TLS interception. |

Colour is probed **per stream**, so a piped stdout does not disable colour on an interactive
stderr.

---

## Values that are not configurable

The following are module constants in 0.1.0 and cannot be changed from a file, an environment
variable or a flag:

| Constant | Value | Module |
|---|---|---|
| Request timeout | 30 s | `depkeeper.constants.DEFAULT_TIMEOUT` |
| Retries per request | 3 | `depkeeper.constants.DEFAULT_MAX_RETRIES` |
| `429` retry budget | 5 | `HTTPClient._max_429_retries` |
| Maximum file size | 10 MB | `depkeeper.constants.MAX_FILE_SIZE` |
| HTTP concurrency | 10 | `HTTPClient.max_concurrency` |
| Data-store concurrency | 10 | `PyPIDataStore.concurrent_limit` |
| Resolution passes | 100 | `_MAX_RESOLUTION_ITERATIONS` |
| Source candidates per conflict | 50 | `_MAX_SOURCE_CANDIDATES` |
| Package index | `https://pypi.org/pypi/{package}/json` | `depkeeper.constants.PYPI_JSON_API` |
| Read / write encodings | `utf-8-sig` / `utf-8` | `depkeeper.constants` |

Programmatic users can override the HTTP and data-store limits by constructing those objects
directly — see [Python API](python-api.md).

---

## Inspecting the effective configuration

```bash
depkeeper -vv check 2>&1 | head -n 5
```

```text
DEBUG: depkeeper v0.1.0
DEBUG: Config path: /path/to/depkeeper.toml
DEBUG: Loaded configuration: {'check_conflicts': True, 'strict_version_matching': False}
DEBUG: Verbosity: 2 | Color: True
```

`Config path: None` means no file was discovered.
