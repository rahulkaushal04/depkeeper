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
    Package       Current    Latest     Recommended  Status
    ─────────────────────────────────────────────────────────
    requests      2.28.0     2.32.0     2.32.0       Outdated (minor)
    flask         2.0.0      3.0.1      2.3.3        Outdated (patch)
    ```

=== "Simple"

    ```bash
    depkeeper check --format simple
    ```

    ```
    requests: 2.28.0 -> 2.32.0 (minor)
    flask: 2.0.0 -> 2.3.3 (patch)
    ```

=== "JSON"

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
        "has_conflicts": false
      }
    ]
    ```

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
Package       Current    Recommended  Status
───────────────────────────────────────────────
requests      2.28.0     2.31.0       Outdated
urllib3       1.26.0     1.26.18      Constrained

ℹ urllib3 constrained by requests (requires urllib3<2.0)
```

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
