---
title: CLI Commands
description: Complete command-line interface reference for depkeeper
---

# CLI Commands

Complete reference for all depkeeper command-line options. depkeeper provides two main commands -- `check` and `update` -- along with global options that apply to both.

---

## Command Overview

| Command | Steps |
|---|---|
| `depkeeper check` | Parse file &#8594; Query PyPI &#8594; Resolve conflicts &#8594; Display report |
| `depkeeper update` | Parse file &#8594; Query PyPI &#8594; Resolve conflicts &#8594; Apply updates |

Both commands share global options described below.

---

## Global Options

These options are available for all commands:

```bash
depkeeper [OPTIONS] COMMAND [ARGS]...
```

| Option | Short | Description |
|---|---|---|
| `--config PATH` | `-c` | Path to configuration file |
| `--verbose` | `-v` | Increase verbosity (repeat for more: `-v`, `-vv`) |
| `--color / --no-color` | | Enable/disable colored output |
| `--version` | | Show version and exit |
| `--help` | `-h` | Show help message |

### Verbosity Levels

| Level | Flag | Logging |
|---|---|---|
| Default | (none) | WARNING |
| Verbose | `-v` | INFO |
| Debug | `-vv` | DEBUG |

### Examples

```bash
# Use specific config file
depkeeper -c /path/to/config.toml check

# Verbose output
depkeeper -v check
depkeeper -vv check  # Debug level

# Disable colors
depkeeper --no-color check

# Show version
depkeeper --version
```

---

## check

Check for available updates in a requirements file.

### Synopsis

```bash
depkeeper check [OPTIONS] [FILE]
```

### Arguments

| Argument | Description | Default |
|---|---|---|
| `FILE` | Path to requirements file | `requirements.txt` |

### Options

| Option | Short | Description | Default |
|---|---|---|---|
| `--outdated-only` | | Show only packages with available updates | `False` |
| `--format` | `-f` | Output format: `table`, `simple`, `json` | `table` |
| `--strict-version-matching` | | Only consider exact version pins (`==`) | `False` |
| `--check-conflicts / --no-check-conflicts` | | Enable/disable dependency conflict resolution | `True` |

!!! tip "Configuration File Fallback"

    `--strict-version-matching` and `--check-conflicts` fall back to values from your `depkeeper.toml` or `pyproject.toml` when not provided on the command line. See [Configuration](../guides/configuration.md) for details.

### How It Works

1. **Parse** -- Read and parse the requirements file (PEP 440/508 compliant)
2. **Query PyPI** -- Fetch latest version metadata concurrently via async HTTP
3. **Recommend** -- Compute safe upgrade targets within major version boundaries
4. **Resolve** -- Cross-validate recommendations and resolve dependency conflicts
5. **Report** -- Display results in the requested format

### Output Formats

#### Table (default)

Human-readable table with colors:

```bash
depkeeper check --format table
```

```
Package       Current    Latest     Recommended  Status
─────────────────────────────────────────────────────────
requests      2.28.0     2.32.0     2.32.0       Outdated (minor)
flask         2.0.0      3.0.1      2.3.3        Outdated (patch)
```

#### Simple

One line per package:

```bash
depkeeper check --format simple
```

```
requests: 2.28.0 -> 2.32.0 (minor)
flask: 2.0.0 -> 2.3.3 (patch)
```

#### JSON

Machine-readable JSON:

```bash
depkeeper check --format json
```

```json
[
  {
    "name": "requests",
    "status": "outdated",
    "versions": {
      "current": "2.28.0",
      "latest": "2.32.0",
      "recommended": "2.32.0"
    },
    "update_type": "minor"
  }
]
```

### Examples

```bash
# Basic check
depkeeper check

# Check specific file
depkeeper check requirements-dev.txt

# Show only outdated
depkeeper check --outdated-only

# JSON output for CI
depkeeper check --format json > report.json

# Disable conflict checking (faster)
depkeeper check --no-check-conflicts

# Strict mode: only exact pins
depkeeper check --strict-version-matching
```

---

## update

Update packages to newer versions within safe major version boundaries.

### Synopsis

```bash
depkeeper update [OPTIONS] [FILE]
```

### Arguments

| Argument | Description | Default |
|---|---|---|
| `FILE` | Path to requirements file | `requirements.txt` |

### Options

| Option | Short | Description | Default |
|---|---|---|---|
| `--dry-run` | | Preview changes without applying | `False` |
| `--yes` | `-y` | Skip confirmation prompt | `False` |
| `--backup` | | Create backup before updating | `False` |
| `--packages` | `-p` | Update only specific packages (repeatable) | All |
| `--strict-version-matching` | | Only consider exact version pins | `False` |
| `--check-conflicts / --no-check-conflicts` | | Enable/disable conflict resolution | `True` |

!!! tip "Configuration File Fallback"

    `--strict-version-matching` and `--check-conflicts` fall back to values from your `depkeeper.toml` or `pyproject.toml` when not provided on the command line. See [Configuration](../guides/configuration.md) for details.

### Update Process

1. **Parse** -- Read the requirements file
2. **Check** -- Query PyPI for available versions
3. **Resolve** -- Check for dependency conflicts (if enabled)
4. **Preview** -- Show proposed changes
5. **Confirm** -- Ask for user confirmation (unless `-y`)
6. **Backup** -- Create backup (if `--backup`)
7. **Apply** -- Update the requirements file
8. **Report** -- Show summary of changes

### Backup Files

When `--backup` is used, a timestamped backup is created:

```
requirements.txt.backup.20260208-143022
```

Format: `{filename}.backup.{YYYYMMDD}-{HHMMSS}`

### Examples

```bash
# Basic update (with confirmation)
depkeeper update

# Preview changes
depkeeper update --dry-run

# Update without confirmation
depkeeper update -y

# Create backup before updating
depkeeper update --backup

# Update specific packages only
depkeeper update -p requests -p flask

# Combine options
depkeeper update --backup -y -p requests

# Update specific file
depkeeper update requirements-dev.txt --backup -y

# Disable conflict checking
depkeeper update --no-check-conflicts -y
```

---

## Command Chaining

depkeeper commands can be chained in scripts:

```bash
#!/bin/bash
set -e

# Check first
if depkeeper check --outdated-only --format simple | grep -q .; then
    echo "Updates available"

    # Preview
    depkeeper update --dry-run

    # Apply with backup
    depkeeper update --backup -y

    # Verify
    pip install -r requirements.txt
    pytest
fi
```

---

## Environment Variables

Commands respect these environment variables:

| Variable | Affects |
|---|---|
| `DEPKEEPER_CONFIG` | `--config` option |
| `DEPKEEPER_COLOR` | `--color` option |
| `NO_COLOR` | Disables colors ([standard](https://no-color.org/)) |

---

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Application error |
| `2` | Usage/argument error |
| `130` | Interrupted (Ctrl+C) |

See [Exit Codes](exit-codes.md) for detailed descriptions and scripting examples.

---

## See Also

- [Quick Start](../getting-started/quickstart.md) -- Getting started guide
- [Configuration](../guides/configuration.md) -- Configuration options
- [CI/CD Integration](../guides/ci-cd-integration.md) -- Pipeline integration
- [Exit Codes](exit-codes.md) -- Exit code reference
