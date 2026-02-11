---
title: Configuration Options
description: Complete configuration reference for depkeeper
---

# Configuration Options

Complete reference for all depkeeper configuration options. depkeeper supports CLI arguments, environment variables, and configuration files with a clear precedence hierarchy. Configuration file values serve as defaults that CLI arguments override.

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
check_conflicts = true
strict_version_matching = false
```

### pyproject.toml

```toml
# pyproject.toml

[tool.depkeeper]
check_conflicts = true
strict_version_matching = false
```

---

## Configuration File Reference

These options can be set in the ``[depkeeper]`` table of ``depkeeper.toml`` or the ``[tool.depkeeper]`` table of ``pyproject.toml``.

| Option | Type | Default | Description |
|---|---|---|---|
| `check_conflicts` | Boolean | `true` | Enable dependency conflict resolution |
| `strict_version_matching` | Boolean | `false` | Only use exact version pins (`==`) |

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

---

## Example Configurations

### Development Environment

```toml
# depkeeper.toml

[depkeeper]
check_conflicts = true
```

### Production / Conservative

```toml
# depkeeper.toml

[depkeeper]
check_conflicts = true
strict_version_matching = true
```

---

## Validation

depkeeper validates configuration on startup. Invalid values result in clear error messages:

```bash
$ depkeeper check
Error: Invalid configuration: check_conflicts must be a boolean, got str
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
