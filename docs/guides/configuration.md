---
title: Configuration
description: Configure depkeeper behavior via CLI options, environment variables, and configuration files
---

# Configuration

depkeeper can be configured through CLI options, environment variables, and configuration files. When a CLI flag is not explicitly provided, depkeeper reads the value from the configuration file. If no configuration file is found, built-in defaults apply.

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

### Examples

```bash
# Disable colors
export DEPKEEPER_COLOR=false
depkeeper check
```

### In CI/CD

```yaml
env:
  DEPKEEPER_COLOR: false

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
# Enable conflict checking by default
check_conflicts = true

# Only consider exact version pins (==)
strict_version_matching = false
```

### pyproject.toml Format

```toml
# pyproject.toml

[tool.depkeeper]
check_conflicts = true
strict_version_matching = false
```

---

## Configuration Options Reference

| Option | Type | Default | Description |
|---|---|---|---|
| `check_conflicts` | bool | `true` | Enable dependency conflict resolution |
| `strict_version_matching` | bool | `false` | Only consider exact version pins (`==`) |

---

## Excluding Packages

Use the `--packages` / `-p` CLI option to update only specific packages:

```bash
# Update only specific packages
depkeeper update -p requests -p flask
```

---

## Example Configurations

### Conservative Production

```toml
# depkeeper.toml - Production-safe settings

[depkeeper]
check_conflicts = true
strict_version_matching = true
```

### Active Development

```toml
# depkeeper.toml - Development settings

[depkeeper]
check_conflicts = true
strict_version_matching = false
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
DEBUG: Loaded configuration: {'check_conflicts': True, 'strict_version_matching': False}
DEBUG: Effective check_conflicts: True
```

---

## Next Steps

- [CLI Reference](../reference/cli-commands.md) -- Complete command documentation
- [Configuration Options](../reference/configuration-options.md) -- Full options reference
- [CI/CD Integration](ci-cd-integration.md) -- Use configuration in pipelines
