---
title: Checking for Updates
description: Master the depkeeper check command
---

# Checking for Updates

The `check` command is your starting point for dependency management. It analyzes your requirements file and reports available updates without making any changes.

---

## Basic Usage

```bash
depkeeper check
```

This reads `requirements.txt` from the current directory and reports on all packages.

---

## Specifying a File

Check a specific requirements file:

```bash
depkeeper check requirements-dev.txt
depkeeper check path/to/requirements.txt
```

---

## Output Formats

### Table Format (Default)

Beautiful, human-readable output:

```bash
depkeeper check --format table
```

```
Checking requirements.txt...
Found 5 package(s)

Package       Current    Latest     Recommended  Status
─────────────────────────────────────────────────────────
requests      2.28.0     2.32.0     2.32.0       Outdated (minor)
flask         2.0.0      3.0.1      2.3.3        Outdated (patch)
click         8.0.0      8.1.7      8.1.7        Outdated (minor)
django        3.2.0      5.0.2      3.2.24       Outdated (patch)
pytest        7.4.0      8.0.0      7.4.4        Outdated (patch)

✓ Found 5 packages with available updates
```

**Columns explained:**

| Column | Description |
|---|---|
| **Package** | Normalized package name |
| **Current** | Version from your requirements file |
| **Latest** | Newest version on PyPI |
| **Recommended** | Safe upgrade (within major version) |
| **Status** | Update type and any issues |

### Simple Format

Compact, one-line-per-package output:

```bash
depkeeper check --format simple
```

```
requests: 2.28.0 -> 2.32.0 (minor)
flask: 2.0.0 -> 2.3.3 (patch)
click: 8.0.0 -> 8.1.7 (minor)
django: 3.2.0 -> 3.2.24 (patch)
pytest: 7.4.0 -> 7.4.4 (patch)
```

### JSON Format

Machine-readable output for CI/CD:

```bash
depkeeper check --format json
```

```json
[
  {
    "name": "requests",
    "current_version": "2.28.0",
    "latest_version": "2.32.0",
    "recommended_version": "2.32.0",
    "update_type": "minor",
    "has_conflicts": false,
    "conflicts": [],
    "python_compatible": true
  },
  {
    "name": "flask",
    "current_version": "2.0.0",
    "latest_version": "3.0.1",
    "recommended_version": "2.3.3",
    "update_type": "patch",
    "has_conflicts": false,
    "conflicts": [],
    "python_compatible": true
  }
]
```

---

## Filtering Results

### Outdated Packages Only

Show only packages that have available updates:

```bash
depkeeper check --outdated-only
```

This is useful when you have many dependencies and only want to see what needs attention.

---

## Conflict Detection

By default, depkeeper checks for dependency conflicts during version resolution.

### Understanding Conflicts

A conflict occurs when packages have incompatible version requirements:

```
Package       Current    Recommended  Status
───────────────────────────────────────────────
requests      2.28.0     2.31.0       Outdated (minor)
urllib3       1.26.0     1.26.18      Constrained

⚠ Conflicts detected:
  urllib3: constrained by requests (requires urllib3>=1.21.1,<2)
```

### How It Works

1. **Metadata Fetch**: depkeeper fetches dependency metadata from PyPI
2. **Graph Building**: Builds a dependency graph for all packages
3. **Conflict Detection**: Identifies version incompatibilities
4. **Resolution**: Adjusts recommendations to resolve conflicts

### Disabling Conflict Checking

For faster checks without resolution:

```bash
depkeeper check --no-check-conflicts
```

!!! warning
    Skipping conflict checking may result in recommendations that create broken environments.

---

## Version Matching

### Default Behavior

By default, depkeeper infers the current version from version specifiers:

```text
# These are treated as "current version = 2.0.0"
requests>=2.0.0
requests>=2.0.0,<3.0.0
```

### Strict Version Matching

Only consider exact pins (`==`) as the current version:

```bash
depkeeper check --strict-version-matching
```

With this option:

```text
requests>=2.0.0           # Current: Unknown
requests==2.28.0          # Current: 2.28.0
```

---

## Verbosity Levels

Increase output detail for debugging:

```bash
# Info level - shows more context
depkeeper -v check

# Debug level - shows HTTP requests, timing, etc.
depkeeper -vv check
```

---

## Color Output

Control colored output:

```bash
# Disable colors (for CI logs)
depkeeper --no-color check

# Force colors (default)
depkeeper --color check
```

Or via environment variable:

```bash
export DEPKEEPER_COLOR=false
depkeeper check
```

---

## Examples

### Daily Status Check

```bash
depkeeper check --outdated-only
```

### CI/CD Pipeline

```bash
# JSON output, check for issues
depkeeper check --format json > deps-report.json
```

### Quick Overview

```bash
depkeeper check --format simple --outdated-only
```

### Debugging Issues

```bash
depkeeper -vv check
```

---

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success (even if updates available) |
| `1` | Error (parse failure, network issue) |
| `2` | Usage error (invalid arguments) |

---

## Next Steps

- [Updating Dependencies](updating-dependencies.md) -- Apply the recommended updates
- [Dependency Resolution](dependency-resolution.md) -- Understand conflict handling
- [CLI Reference](../reference/cli-commands.md) -- Complete command documentation
