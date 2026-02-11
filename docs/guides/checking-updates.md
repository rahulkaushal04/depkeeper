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
                                    Dependency Status

  Status       Package    Current   Latest   Recommended   Update Type   Conflicts   Python Support

  ✓ OK         django      3.2.0     5.0.2        -             -           -        Current: >=3.8
                                                                                     Latest: >=3.10

  ⬆ OUTDATED   requests    2.28.0    2.32.0     2.32.0        minor         -        Current: >=3.7
                                                                                     Latest: >=3.8

  ⬆ OUTDATED   flask       2.0.0     3.0.1      2.3.3         patch         -        Current: >=3.7
                                                                                     Latest: >=3.8

[WARNING] 2 package(s) have updates available
```

**Columns explained:**

| Column | Description |
|---|---|
| **Status** | Whether the package is up to date (`OK`) or `OUTDATED` |
| **Package** | Normalized package name |
| **Current** | Version from your requirements file |
| **Latest** | Newest version on PyPI |
| **Recommended** | Safe upgrade (within major version), or `-` if already up to date |
| **Update Type** | Severity of the update (`patch`, `minor`, or `major`) |
| **Conflicts** | Any dependency conflicts detected |
| **Python Support** | Required Python version for the current and latest releases |

### Simple Format

Compact, one-line-per-package output:

```bash
depkeeper check --format simple
```

```
 requests             2.28.0     → 2.32.0     (recommended: 2.32.0)
       Python: installed: >=3.7, latest: >=3.8
 flask                2.0.0      → 3.0.1      (recommended: 2.3.3)
       Python: installed: >=3.7, latest: >=3.8, recommended: >=3.7
 celery               5.3.0      → 5.3.6
       Python: installed: >=3.8, latest: >=3.8
```

Each line shows the package name, installed version, latest version, and a recommended version when it differs from the latest. The indented Python line shows the required Python version for each relevant release.

### JSON Format

Machine-readable output for CI/CD:

```bash
depkeeper check --format json
```

```json
[
  {
    "name": "requests",
    "status": "latest",
    "versions": {
      "current": "2.32.5",
      "latest": "2.32.5",
      "recommended": "2.32.5"
    },
    "python_requirements": {
      "current": ">=3.9",
      "latest": ">=3.9",
      "recommended": ">=3.9"
    }
  },
  {
    "name": "polars",
    "status": "outdated",
    "versions": {
      "current": "1.37.1",
      "latest": "1.38.1",
      "recommended": "1.38.1"
    },
    "update_type": "minor",
    "python_requirements": {
      "current": ">=3.10",
      "latest": ">=3.10",
      "recommended": ">=3.10"
    }
  },
  {
    "name": "setuptools",
    "status": "latest",
    "versions": {
      "current": "80.10.2",
      "latest": "82.0.0",
      "recommended": "80.10.2"
    },
    "python_requirements": {
      "current": ">=3.9",
      "latest": ">=3.9",
      "recommended": ">=3.9"
    }
  }
]
```

Each object includes the package `name`, its `status` (`latest` or `outdated`), a `versions` block with `current`, `latest`, and `recommended` versions, and a `python_requirements` block showing the required Python version for each release. Outdated packages also include an `update_type` field (`patch`, `minor`, or `major`).

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
                                         Dependency Status

  Status       Package           Current   Latest   Recommended   Update Type   Conflicts                        Python Support

  ⬆ OUTDATED   pytest-asyncio     0.3.0     1.3.0     0.23.8        minor         -                             Latest: >=3.10
                                                                                                                Recommended: >=3.8

  ⬆ OUTDATED   pytest             7.0.2     9.0.2     7.4.4         minor    pytest-asyncio needs >= 7.0.0,<9      Latest: >=3.10
                                                                                                                Recommended: >=3.7

[WARNING] 2 package(s) have updates available
```

In this example, `pytest` is constrained by `pytest-asyncio` which requires `pytest>=8.2,<9`. depkeeper detects this conflict and adjusts the recommended version of `pytest` to stay within safe boundaries.

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
