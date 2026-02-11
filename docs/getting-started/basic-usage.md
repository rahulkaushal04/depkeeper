---
title: Basic Usage
description: Learn the fundamentals of using depkeeper for dependency management
---

# Basic Usage

This guide covers the fundamental concepts and workflows for using depkeeper effectively.

---

## Understanding Requirements Files

depkeeper works with standard `requirements.txt` files that pip understands. It supports:

```text
# Basic version pinning
requests==2.31.0
flask>=2.0.0,<3.0.0

# With extras
celery[redis]==5.3.0

# Environment markers
pywin32==306; sys_platform == 'win32'

# Include other files
-r base.txt
-c constraints.txt

# VCS URLs
git+https://github.com/user/repo.git@v1.0.0#egg=mypackage

# Editable installs
-e ./local-package
```

---

## The `check` Command

The `check` command analyzes your requirements file and reports available updates.

### Basic Check

```bash
depkeeper check
```

By default, this reads `requirements.txt` in the current directory.

### Check a Specific File

```bash
depkeeper check requirements-dev.txt
depkeeper check path/to/requirements.txt
```

### Output Formats

=== "Table (default)"

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

=== "Simple"

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

=== "JSON"

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

### Filter to Outdated Only

Show only packages that need updates:

```bash
depkeeper check --outdated-only
```

---

## The `update` Command

The `update` command applies safe version updates to your requirements file.

### Basic Update

```bash
depkeeper update
```

This:

1. Checks all packages for updates
2. Shows a preview of changes
3. Asks for confirmation
4. Updates `requirements.txt`

### Preview Mode (Dry Run)

See what would change without modifying files:

```bash
depkeeper update --dry-run
```

### Skip Confirmation

Auto-approve updates (useful for CI/CD):

```bash
depkeeper update --yes
# or
depkeeper update -y
```

### Create Backup

Create a timestamped backup before updating:

```bash
depkeeper update --backup
```

This creates `requirements.txt.backup.20260208-143022` (with current timestamp).

### Update Specific Packages

Update only selected packages:

```bash
# Single package
depkeeper update -p requests

# Multiple packages
depkeeper update -p requests -p flask -p click
```

---

## Version Boundary Safety

A key feature of depkeeper is **major version boundary protection**.

### What This Means

depkeeper **never** recommends crossing a major version boundary automatically:

| Current | Latest | Recommended | Reason |
|---|---|---|---|
| `2.28.0` | `2.32.0` | `2.32.0` | Same major (2.x) ✓ |
| `2.0.0` | `3.0.1` | `2.3.3` | Stays on 2.x, avoids 3.x breaking changes |
| `1.2.3` | `2.0.0` | `1.9.9` | Stays on 1.x |

### Why This Matters

Major version updates often include:

- Breaking API changes
- Removed functionality
- Changed behavior
- Incompatible dependencies

By staying within the same major version, depkeeper keeps your environment stable while still getting bug fixes and security patches.

!!! tip "Intentional Major Upgrades"

    When you're ready to upgrade to a new major version, update your `requirements.txt` manually and test thoroughly.

---

## Conflict Detection

depkeeper automatically detects dependency conflicts.

### How It Works

When checking or updating, depkeeper:

1. Fetches dependency metadata from PyPI
2. Builds a dependency graph
3. Identifies version conflicts
4. Adjusts recommendations to resolve conflicts

### Example

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

### Disabling Conflict Checking

For faster checks without resolution:

```bash
depkeeper check --no-check-conflicts
depkeeper update --no-check-conflicts
```

!!! warning
    Disabling conflict checking may result in broken environments.

---

## Working with Multiple Files

### Multiple Requirements Files

Check or update different files:

```bash
depkeeper check requirements.txt
depkeeper check requirements-dev.txt
depkeeper check requirements-test.txt
```

### Included Files

If your requirements file uses `-r` includes:

```text
# requirements-dev.txt
-r requirements.txt
pytest>=7.0.0
black>=23.0.0
```

depkeeper follows include directives and processes all referenced files.

### Constraint Files

Constraint files (`-c`) are also supported:

```text
# requirements.txt
-c constraints.txt
requests
flask
```

---

## Exit Codes

depkeeper uses meaningful exit codes:

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Error (parse failure, network issue, etc.) |
| `2` | Usage error (invalid arguments) |
| `130` | Interrupted by user (Ctrl+C) |

Useful for CI/CD scripts:

```bash
depkeeper check --format json || echo "Check failed"
```

---

## Next Steps

- [Checking Updates](../guides/checking-updates.md) -- Deep dive into the check command
- [Updating Dependencies](../guides/updating-dependencies.md) -- Advanced update workflows
- [Dependency Resolution](../guides/dependency-resolution.md) -- Understand conflict detection
