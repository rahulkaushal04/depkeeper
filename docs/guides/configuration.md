---
title: Configuration
description: Configure depkeeper behavior via CLI options and environment variables
---

# Configuration

depkeeper can be configured through CLI options, environment variables, and configuration files.

---

## Configuration Hierarchy

Configuration is applied in this order (later overrides earlier):

1. **Built-in defaults**
2. **Configuration file** (`depkeeper.toml` or `pyproject.toml`)
3. **Environment variables** (`DEPKEEPER_*`)
4. **CLI arguments**

---

## CLI Options

### Global Options

These options apply to all commands:

| Option | Description | Default |
|---|---|---|
| `-c, --config PATH` | Path to configuration file | Auto-detected |
| `-v, --verbose` | Increase verbosity (can repeat: `-v`, `-vv`) | Warning level |
| `--color / --no-color` | Enable/disable colored output | `--color` |
| `--version` | Show version and exit | -- |
| `-h, --help` | Show help and exit | -- |

### Command-Specific Options

See [CLI Reference](../reference/cli-commands.md) for complete option documentation per command.

---

## Environment Variables

All environment variables are prefixed with `DEPKEEPER_`:

| Variable | Description | Example |
|---|---|---|
| `DEPKEEPER_CONFIG` | Path to configuration file | `/path/to/config.toml` |
| `DEPKEEPER_COLOR` | Enable/disable colors | `true`, `false` |
| `DEPKEEPER_CACHE_DIR` | Cache directory path | `~/.cache/depkeeper` |
| `DEPKEEPER_LOG_LEVEL` | Logging level | `DEBUG`, `INFO`, `WARNING` |

### Examples

```bash
# Disable colors
export DEPKEEPER_COLOR=false
depkeeper check

# Set custom cache directory
export DEPKEEPER_CACHE_DIR=/tmp/depkeeper-cache
depkeeper check

# Enable debug logging
export DEPKEEPER_LOG_LEVEL=DEBUG
depkeeper check
```

### In CI/CD

```yaml
env:
  DEPKEEPER_COLOR: false
  DEPKEEPER_LOG_LEVEL: INFO

steps:
  - run: depkeeper check
```

---

## Configuration File

### File Locations

depkeeper looks for configuration in:

1. Path specified by `--config` or `DEPKEEPER_CONFIG`
2. `depkeeper.toml` in the current directory
3. `pyproject.toml` under `[tool.depkeeper]`

### depkeeper.toml Format

```toml
# depkeeper.toml

[depkeeper]
# Default update strategy
update_strategy = "minor"

# Enable conflict checking by default
check_conflicts = true

# Cache settings
cache_ttl = 3600  # seconds

# Number of concurrent PyPI requests
concurrent_requests = 10

[depkeeper.filters]
# Packages to exclude from updates
exclude = [
    "django",  # Pin major version manually
    "numpy",   # Requires specific testing
]

# Include pre-release versions
include_pre_release = false

[depkeeper.pypi]
# Custom PyPI index
index_url = "https://pypi.org/simple"

# Additional indexes
extra_index_urls = [
    "https://private.pypi.example.com/simple"
]

# Request timeout in seconds
timeout = 30
```

### pyproject.toml Format

```toml
# pyproject.toml

[tool.depkeeper]
update_strategy = "minor"
check_conflicts = true

[tool.depkeeper.filters]
exclude = ["django", "numpy"]
include_pre_release = false
```

---

## Configuration Options Reference

### General Options

| Option | Type | Default | Description |
|---|---|---|---|
| `update_strategy` | string | `"minor"` | Default update strategy |
| `check_conflicts` | bool | `true` | Enable dependency resolution |
| `strict_version_matching` | bool | `false` | Only consider exact pins |
| `cache_ttl` | int | `3600` | Cache TTL in seconds |
| `concurrent_requests` | int | `10` | Max concurrent PyPI requests |

### Filter Options

| Option | Type | Default | Description |
|---|---|---|---|
| `exclude` | list | `[]` | Packages to skip |
| `include_pre_release` | bool | `false` | Include alpha/beta versions |

### PyPI Options

| Option | Type | Default | Description |
|---|---|---|---|
| `index_url` | string | PyPI URL | Primary package index |
| `extra_index_urls` | list | `[]` | Additional indexes |
| `timeout` | int | `30` | Request timeout (seconds) |

---

## Update Strategies

Configure how depkeeper recommends updates:

| Strategy | Description | Risk Level |
|---|---|---|
| `patch` | Only patch updates (x.x.PATCH) | Lowest |
| `minor` | Minor + patch updates (x.MINOR.x) | Low |
| `major` | All updates including major | Higher |

```toml
[depkeeper]
update_strategy = "minor"  # Default: safe updates only
```

!!! note "Major Version Boundary"
    Even with `update_strategy = "major"`, depkeeper respects major version boundaries for safety. To cross a major version, update your requirements manually.

---

## Excluding Packages

Skip specific packages from updates:

```toml
[depkeeper.filters]
exclude = [
    "django",      # Pin manually
    "tensorflow",  # Requires GPU testing
    "numpy",       # Version-sensitive
]
```

Or via CLI:

```bash
# Update all except django
depkeeper update -p requests -p flask  # Only update specified packages
```

---

## Private Package Indexes

Configure custom PyPI indexes:

```toml
[depkeeper.pypi]
# Replace the default index
index_url = "https://private.pypi.example.com/simple"

# Or add additional indexes
extra_index_urls = [
    "https://private.pypi.example.com/simple",
    "https://another.index.com/simple",
]
```

---

## Example Configurations

### Conservative Production

```toml
# depkeeper.toml - Production-safe settings

[depkeeper]
update_strategy = "patch"
check_conflicts = true
strict_version_matching = true

[depkeeper.filters]
exclude = [
    "django",
    "celery",
    "redis",
]
include_pre_release = false
```

### Active Development

```toml
# depkeeper.toml - Development settings

[depkeeper]
update_strategy = "minor"
check_conflicts = true

[depkeeper.filters]
include_pre_release = false
```

### CI/CD Pipeline

```toml
# depkeeper.toml - CI/CD optimized

[depkeeper]
update_strategy = "minor"
check_conflicts = true
concurrent_requests = 20  # Faster in CI

[depkeeper.pypi]
timeout = 60  # Longer timeout for reliability
```

---

## Precedence Example

Given:

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

The effective configuration is:

- `check_conflicts = false` (CLI overrides file)
- `color = false` (from environment)

---

## Debugging Configuration

View effective configuration with verbose mode:

```bash
depkeeper -vv check 2>&1 | grep -i config
```

```
DEBUG: Config path: /project/depkeeper.toml
DEBUG: Loaded configuration: {'update_strategy': 'minor', ...}
DEBUG: Effective check_conflicts: True
```

---

## Next Steps

- [CLI Reference](../reference/cli-commands.md) -- Complete command documentation
- [Configuration Options](../reference/configuration-options.md) -- Full options reference
- [CI/CD Integration](ci-cd-integration.md) -- Use configuration in pipelines
