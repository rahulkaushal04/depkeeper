---
title: Quick Start
description: Get up and running with depkeeper in 5 minutes
---

# Quick Start

This guide gets you productive with depkeeper in under 5 minutes.

---

## Prerequisites

- Python 3.8+
- A `requirements.txt` file in your project

---

## Step 1: Install depkeeper

```bash
pip install depkeeper
```

Verify the installation:

```bash
depkeeper --version
```

---

## Step 2: Check for Updates

Navigate to your project directory and run:

```bash
depkeeper check
```

You'll see output like:

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

!!! info "Understanding the output"

    - **Current**: Your pinned/installed version
    - **Latest**: Newest version on PyPI
    - **Recommended**: Safe upgrade that respects major version boundaries
    - **Status**: Update type (major/minor/patch)

---

## Step 3: Preview Updates

Before making changes, preview what would be updated:

```bash
depkeeper update --dry-run
```

Output:

```
Checking requirements.txt...
Found 5 package(s)

Updates available:

Package       Current    →  Recommended  Type
─────────────────────────────────────────────
requests      2.28.0     →  2.32.0       minor
flask         2.0.0      →  2.3.3        patch
click         8.0.0      →  8.1.7        minor

ℹ 3 packages would be updated (dry run - no changes made)
```

---

## Step 4: Apply Updates

When you're ready to update:

```bash
depkeeper update
```

You'll be asked to confirm:

```
Apply 3 updates? [y/N]: y

✓ Successfully updated 3 packages
```

To skip the confirmation prompt:

```bash
depkeeper update -y
```

---

## Step 5: Create a Backup (Optional)

For extra safety, create a backup before updating:

```bash
depkeeper update --backup -y
```

This creates `requirements.txt.backup.<timestamp>` before making changes.

---

## Common Workflows

### Check Only Outdated Packages

```bash
depkeeper check --outdated-only
```

### Update Specific Packages

```bash
depkeeper update -p requests -p flask
```

### JSON Output for CI/CD

```bash
depkeeper check --format json
```

### Increase Verbosity

```bash
depkeeper -v check     # Info level
depkeeper -vv check    # Debug level
```

---

## Quick Reference

| Command | Description |
|---|---|
| `depkeeper check` | Check for available updates |
| `depkeeper check --outdated-only` | Show only outdated packages |
| `depkeeper check -f json` | Output as JSON |
| `depkeeper update` | Update all packages |
| `depkeeper update --dry-run` | Preview updates |
| `depkeeper update -y` | Update without confirmation |
| `depkeeper update --backup` | Create backup before updating |
| `depkeeper update -p PKG` | Update specific package(s) |

---

## Next Steps

- [Basic Usage](basic-usage.md) -- Learn more about checking and updating dependencies
- [Configuration](../guides/configuration.md) -- Customize depkeeper behavior
- [CI/CD Integration](../guides/ci-cd-integration.md) -- Automate dependency updates in your pipeline
