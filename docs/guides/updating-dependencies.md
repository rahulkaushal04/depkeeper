---
title: Updating Dependencies
description: Safely update packages with depkeeper
---

# Updating Dependencies

The `update` command applies version updates to your requirements file with safety guardrails.

---

## Basic Usage

```bash
depkeeper update
```

This:

1. Analyzes your `requirements.txt`
2. Calculates safe version recommendations
3. Shows a preview of proposed changes
4. Asks for confirmation
5. Updates the file

---

## Preview Mode (Dry Run)

See what would change without modifying any files:

```bash
depkeeper update --dry-run
```

```
Update Plan (Dry Run)

  Package    Current   New Version   Change   Python Requires

  requests    2.28.0      2.32.0      minor   >=3.8
  flask       2.0.0       2.3.3       patch   >=3.7
  click       8.0.0       8.1.7       minor   >=3.7
```

**Columns explained:**

| Column | Description |
|---|---|
| **Package** | Normalized package name |
| **Current** | Version from your requirements file |
| **New Version** | The safe recommended version to update to |
| **Change** | Severity of the update (`patch`, `minor`, or `major`) |
| **Python Requires** | Required Python version for the new version |

!!! tip "Best Practice"
    Always run `--dry-run` first to review changes before applying them.

---

## Skip Confirmation

For automated workflows, skip the interactive prompt:

```bash
depkeeper update --yes
# or
depkeeper update -y
```

---

## Create Backups

Create a timestamped backup before making changes:

```bash
depkeeper update --backup
```

This creates a backup file like:

```
requirements.txt.backup.20260208-143022
```

Combine with `-y` for automated workflows:

```bash
depkeeper update --backup -y
```

---

## Update Specific Packages

Update only selected packages:

```bash
# Single package
depkeeper update -p requests

# Multiple packages
depkeeper update -p requests -p flask -p click
```

Packages not specified are left unchanged.

---

## Specifying a File

Update a specific requirements file:

```bash
depkeeper update requirements-dev.txt
depkeeper update path/to/requirements.txt
```

---

## Understanding Update Types

depkeeper classifies updates by semantic versioning impact:

| Type | Description | Example | Risk |
|---|---|---|---|
| **Patch** | Bug fixes only | `2.28.0` → `2.28.1` | Low |
| **Minor** | New features, backward compatible | `2.28.0` → `2.29.0` | Medium |
| **Major** | Breaking changes | `2.0.0` → `3.0.0` | High |

### Major Version Boundary

depkeeper **never** recommends crossing major version boundaries:

```
Package       Current    Latest     Recommended
───────────────────────────────────────────────
flask         2.0.0      3.0.1      2.3.3        # Stays on 2.x
django        3.2.0      5.0.2      3.2.24       # Stays on 3.x
```

This prevents unexpected breaking changes.

---

## Conflict Resolution

When updating, depkeeper automatically resolves conflicts. Constrained packages show the dependency that restricts them in the check output, and the update plan reflects the safe resolved version:

```
Update Plan (Dry Run)

  Package          Current   New Version   Change   Python Requires

  pytest-asyncio    0.3.0      0.23.8       minor   >=3.8
  pytest            7.0.2      7.4.4        minor   >=3.7
```

In this example, `pytest` is constrained by `pytest-asyncio` and depkeeper adjusts both recommendations to stay within compatible boundaries.

### Disable Conflict Checking

For faster updates without resolution:

```bash
depkeeper update --no-check-conflicts
```

!!! warning
    This may create dependency conflicts that break your environment.

---

## Version Matching Options

### Strict Version Matching

Only update packages with exact version pins:

```bash
depkeeper update --strict-version-matching
```

With this option:

- `requests==2.28.0` -- Will be updated
- `requests>=2.0.0` -- Will be skipped (no exact version)

---

## Complete Workflow Examples

### Conservative Daily Update

```bash
# Check what's outdated
depkeeper check --outdated-only

# Preview changes
depkeeper update --dry-run

# Apply with backup
depkeeper update --backup -y

# Run tests to verify
pytest
```

### Update Single Package

```bash
# Preview the update
depkeeper update -p requests --dry-run

# Apply it
depkeeper update -p requests -y
```

### Batch Update with Review

```bash
# Preview all changes
depkeeper update --dry-run

# If everything looks good
depkeeper update --backup

# Confirm interactively
Apply 5 updates? [y/N]: y
```

### Automated CI Pipeline

```bash
#!/bin/bash
set -e

# Backup and update
depkeeper update --backup -y

# Only proceed if tests pass
pytest

# Commit changes if successful
git add requirements.txt
git commit -m "chore: update dependencies"
```

---

## File Modifications

### What Gets Updated

```text
# Before
requests==2.28.0
flask==2.0.0
click>=8.0.0

# After
requests==2.32.0
flask==2.3.3
click==8.1.7
```

depkeeper updates the version specifier to `==new_version`.

### Preserved Elements

- Comments are preserved
- Line order is maintained
- Other specifiers (extras, markers) are kept
- Unupdated packages remain unchanged

---

## Verbosity

Get more detail about the update process:

```bash
# Info level
depkeeper -v update

# Debug level (shows HTTP requests, timing)
depkeeper -vv update
```

---

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Error (parse failure, write error) |
| `2` | Usage error (invalid arguments) |
| `130` | Cancelled by user |

---

## Next Steps

- [Dependency Resolution](dependency-resolution.md) -- Understand conflict handling
- [CI/CD Integration](ci-cd-integration.md) -- Automate updates
- [CLI Reference](../reference/cli-commands.md) -- Complete command documentation
