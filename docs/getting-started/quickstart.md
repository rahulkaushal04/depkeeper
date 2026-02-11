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
Resolution Summary:
==================================================
Total packages: 5
Packages with conflicts: 0
Packages changed: 0
Converged: Yes (1 iterations)

                                    Dependency Status

  Status       Package    Current   Latest   Recommended   Update Type   Conflicts   Python Support

  ✓ OK         django      3.2.0     5.0.2        -             -           -        Current: >=3.8
                                                                                     Latest: >=3.10

  ⬆ OUTDATED   requests    2.28.0    2.32.0     2.32.0        minor         -        Current: >=3.7
                                                                                     Latest: >=3.8

  ⬆ OUTDATED   flask       2.0.0     3.0.1      2.3.3         patch         -        Current: >=3.7
                                                                                     Latest: >=3.8

  ⬆ OUTDATED   click       8.0.0     8.1.7      8.1.7         minor         -        Current: >=3.7
                                                                                     Latest: >=3.7

  ⬆ OUTDATED   pytest      7.4.0     8.0.0      7.4.4         patch         -        Current: >=3.7
                                                                                     Latest: >=3.8

[WARNING] 4 package(s) have updates available
```

!!! info "Understanding the output"

    - **Status**: Whether the package is up to date (`✓ OK`) or has updates (`⬆ OUTDATED`)
    - **Current**: Your pinned/installed version
    - **Latest**: Newest version available on PyPI
    - **Recommended**: Safe upgrade that respects major version boundaries
    - **Update Type**: Severity of the update (major/minor/patch)
    - **Conflicts**: Any dependency conflicts detected
    - **Python Support**: Python version requirements for current, latest, and recommended versions

---

## Step 3: Preview Updates

Before making changes, preview what would be updated:

```bash
depkeeper update --dry-run
```

Output:

```
                       Update Plan (Dry Run)

  Package    Current   New Version   Change   Python Requires

  requests    2.28.0       2.32.0    minor    >=3.8
  flask       2.0.0        2.3.3     patch    >=3.8
  click       8.0.0        8.1.7     minor    >=3.7

[WARNING] Dry run mode - no changes applied
```

---

## Step 4: Apply Updates

When you're ready to update:

```bash
depkeeper update
```

You'll see the update plan and be asked to confirm:

```
                          Update Plan

  Package    Current   New Version   Change   Python Requires

  requests    2.28.0       2.32.0    minor    >=3.8
  flask       2.0.0        2.3.3     patch    >=3.8
  click       8.0.0        8.1.7     minor    >=3.7

Update 3 packages? (y, n) [y]: y

[OK] ✓ Successfully updated 3 package(s)
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

```
Command                            Description
─────────────────────────────────────────────────────────────────
depkeeper check                    Check for available updates
depkeeper check --outdated-only    Show only outdated packages
depkeeper check -f json            Output as JSON
depkeeper update                   Update all packages
depkeeper update --dry-run         Preview updates without changes
depkeeper update -y                Update without confirmation
depkeeper update --backup          Create backup before updating
depkeeper update -p PKG            Update specific package(s)
```

---

## Next Steps

- [Basic Usage](basic-usage.md) -- Learn more about checking and updating dependencies
- [Configuration](../guides/configuration.md) -- Customize depkeeper behavior
- [CI/CD Integration](../guides/ci-cd-integration.md) -- Automate dependency updates in your pipeline
