---
title: Configuration Options
description: Complete configuration reference for depkeeper
---

# Configuration Options

Complete reference for all depkeeper configuration options. depkeeper supports CLI arguments, environment variables, and configuration files with a clear precedence hierarchy.

---

## Configuration Precedence

When the same option is set in multiple places, the highest-priority source wins:

1. **CLI arguments** -- Highest priority
2. **Environment variables** -- `DEPKEEPER_*`
3. **Configuration files** -- `depkeeper.toml` or `pyproject.toml`
4. **Built-in defaults** -- Lowest priority

---

## CLI Options

### Global Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--config`, `-c` | Path | Auto-detect | Configuration file path |
| `--verbose`, `-v` | Flag | 0 | Verbosity level (repeat for more) |
| `--color` | Boolean | `true` | Enable colored output |
| `--no-color` | Boolean | `false` | Disable colored output |

### check Command Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--outdated-only` | Flag | `false` | Show only outdated packages |
| `--format`, `-f` | Choice | `table` | Output format: `table`, `simple`, `json` |
| `--strict-version-matching` | Flag | `false` | Only consider exact pins (`==`) |
| `--check-conflicts` | Flag | `true` | Enable conflict resolution |
| `--no-check-conflicts` | Flag | `false` | Disable conflict resolution |

### update Command Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--dry-run` | Flag | `false` | Preview without applying |
| `--yes`, `-y` | Flag | `false` | Skip confirmation |
| `--backup` | Flag | `false` | Create backup file |
| `--packages`, `-p` | String | All | Packages to update (repeatable) |
| `--strict-version-matching` | Flag | `false` | Only consider exact pins |
| `--check-conflicts` | Flag | `true` | Enable conflict resolution |

For full details on each command, see [CLI Commands](cli-commands.md).

---

## Environment Variables

All environment variables use the `DEPKEEPER_` prefix:

| Variable | Type | Default | Description |
|---|---|---|---|
| `DEPKEEPER_CONFIG` | Path | - | Configuration file path |
| `DEPKEEPER_COLOR` | Boolean | `true` | Enable/disable colors |
| `DEPKEEPER_CACHE_DIR` | Path | OS default | Cache directory |
| `DEPKEEPER_LOG_LEVEL` | String | `WARNING` | Logging level |
| `DEPKEEPER_TIMEOUT` | Integer | `30` | HTTP timeout (seconds) |

### Boolean Values

Boolean environment variables accept:

- **True**: `true`, `1`, `yes`, `on`
- **False**: `false`, `0`, `no`, `off`

### Standard Variables

depkeeper also respects the `NO_COLOR` environment variable as defined by the [no-color standard](https://no-color.org/). When set, colored output is disabled regardless of `DEPKEEPER_COLOR`.

### Examples

```bash
# Disable colors
export DEPKEEPER_COLOR=false

# Set custom cache directory
export DEPKEEPER_CACHE_DIR=/tmp/depkeeper

# Enable debug logging
export DEPKEEPER_LOG_LEVEL=DEBUG

# Increase timeout
export DEPKEEPER_TIMEOUT=60
```

---

## Configuration Files

### File Locations

depkeeper searches for configuration in this order:

1. Path from `--config` or `DEPKEEPER_CONFIG`
2. `depkeeper.toml` in the current directory
3. `pyproject.toml` under `[tool.depkeeper]`

### depkeeper.toml

```toml
# depkeeper.toml

[depkeeper]
# Update behavior
update_strategy = "minor"
check_conflicts = true
strict_version_matching = false

# Performance
cache_ttl = 3600
concurrent_requests = 10

# Filters
[depkeeper.filters]
exclude = ["django", "numpy"]
include_pre_release = false

# PyPI configuration
[depkeeper.pypi]
index_url = "https://pypi.org/simple"
extra_index_urls = []
timeout = 30
```

### pyproject.toml

```toml
# pyproject.toml

[tool.depkeeper]
update_strategy = "minor"
check_conflicts = true

[tool.depkeeper.filters]
exclude = ["django"]
```

---

## Configuration Reference

### General Options

| Option | Type | Default | Description |
|---|---|---|---|
| `update_strategy` | String | `"minor"` | Default update strategy |
| `check_conflicts` | Boolean | `true` | Enable dependency resolution |
| `strict_version_matching` | Boolean | `false` | Only use exact version pins |
| `cache_ttl` | Integer | `3600` | Cache TTL in seconds |
| `concurrent_requests` | Integer | `10` | Max concurrent HTTP requests |

### Update Strategies

| Value | Description | Example |
|---|---|---|
| `"patch"` | Bug fixes only | `2.28.0` to `2.28.1` |
| `"minor"` | Features and fixes | `2.28.0` to `2.29.0` |
| `"major"` | All updates | `2.28.0` to `3.0.0` |

!!! note
    Regardless of the strategy, depkeeper respects major version boundaries by default. Recommendations never cross major versions unless the strategy explicitly allows it.

### Filter Options

| Option | Type | Default | Description |
|---|---|---|---|
| `exclude` | List[String] | `[]` | Packages to skip |
| `include_pre_release` | Boolean | `false` | Include alpha/beta versions |

### PyPI Options

| Option | Type | Default | Description |
|---|---|---|---|
| `index_url` | String | `https://pypi.org/simple` | Primary package index |
| `extra_index_urls` | List[String] | `[]` | Additional indexes |
| `timeout` | Integer | `30` | Request timeout (seconds) |

---

## Precedence Example

Given the following configuration:

**depkeeper.toml:**

```toml
[depkeeper]
check_conflicts = true
```

**Environment:**

```bash
export DEPKEEPER_COLOR=false
```

**Command:**

```bash
depkeeper check --no-check-conflicts
```

**Effective configuration:**

| Option | Value | Source |
|---|---|---|
| `check_conflicts` | `false` | CLI wins |
| `color` | `false` | From environment |
| `update_strategy` | `"minor"` | Built-in default |

---

## Example Configurations

### Development Environment

```toml
# depkeeper.toml

[depkeeper]
update_strategy = "minor"
check_conflicts = true
cache_ttl = 3600

[depkeeper.filters]
include_pre_release = false
```

### Production / Conservative

```toml
# depkeeper.toml

[depkeeper]
update_strategy = "patch"
check_conflicts = true
strict_version_matching = true

[depkeeper.filters]
exclude = [
    "django",      # Manual major updates
    "celery",      # Requires testing
    "sqlalchemy",  # Version sensitive
]
```

### CI/CD Pipeline

```toml
# depkeeper.toml

[depkeeper]
update_strategy = "minor"
check_conflicts = true
concurrent_requests = 20

[depkeeper.pypi]
timeout = 60
```

### Private PyPI Index

```toml
# depkeeper.toml

[depkeeper.pypi]
index_url = "https://pypi.example.com/simple"
extra_index_urls = [
    "https://pypi.org/simple",
]
timeout = 30
```

---

## Validation

depkeeper validates configuration on startup. Invalid values result in clear error messages:

```bash
$ depkeeper check
Error: Invalid configuration: update_strategy must be one of: patch, minor, major
```

Use verbose mode to debug configuration loading:

```bash
depkeeper -vv check 2>&1 | grep config
```

---

## See Also

- [Configuration Guide](../guides/configuration.md) -- Practical configuration guide
- [CLI Commands](cli-commands.md) -- Command options reference
- [CI/CD Integration](../guides/ci-cd-integration.md) -- Pipeline configuration
