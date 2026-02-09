---
title: User Guide
description: In-depth guides for depkeeper features and workflows
---

# User Guide

Comprehensive guides covering all depkeeper features and common workflows.

---

## Guides

<div class="grid cards" markdown>

-   :material-magnify:{ .lg .middle } **[Checking for Updates](checking-updates.md)**

    ---

    Master the `check` command with all its options and output formats.

    [:octicons-arrow-right-24: Learn more](checking-updates.md)

-   :material-update:{ .lg .middle } **[Updating Dependencies](updating-dependencies.md)**

    ---

    Safely update packages with backups, dry runs, and selective updates.

    [:octicons-arrow-right-24: Learn more](updating-dependencies.md)

-   :material-vector-triangle:{ .lg .middle } **[Dependency Resolution](dependency-resolution.md)**

    ---

    Understand how depkeeper detects and resolves conflicts.

    [:octicons-arrow-right-24: Learn more](dependency-resolution.md)

-   :material-pipe:{ .lg .middle } **[CI/CD Integration](ci-cd-integration.md)**

    ---

    Automate dependency checks in GitHub Actions, GitLab CI, and more.

    [:octicons-arrow-right-24: Learn more](ci-cd-integration.md)

-   :material-cog:{ .lg .middle } **[Configuration](configuration.md)**

    ---

    Customize depkeeper behavior via CLI options and environment variables.

    [:octicons-arrow-right-24: Learn more](configuration.md)

-   :material-star:{ .lg .middle } **[Best Practices](best-practices.md)**

    ---

    Recommended practices for dependency management and update workflows.

    [:octicons-arrow-right-24: Learn more](best-practices.md)

-   :material-wrench:{ .lg .middle } **[Troubleshooting](troubleshooting.md)**

    ---

    Common issues and their solutions when using depkeeper.

    [:octicons-arrow-right-24: Learn more](troubleshooting.md)

</div>

---

## Common Workflows

### Daily Development

```bash
# Morning: Check what's outdated
depkeeper check --outdated-only

# When ready: Update safely
depkeeper update --backup -y
```

### Before Release

```bash
# Full check with conflict resolution
depkeeper check

# Preview updates
depkeeper update --dry-run

# Apply after review
depkeeper update -y
```

### CI/CD Pipeline

```bash
# Exit non-zero if outdated (for CI notifications)
depkeeper check --format json --outdated-only

# Automated update with backup
depkeeper update --backup -y
```

---

## Best Practices

!!! tip "Version Pinning"

    Always pin your direct dependencies to specific versions for reproducible builds:
    ```text
    requests==2.31.0
    flask==2.3.3
    ```

!!! tip "Regular Updates"

    Check for updates weekly or integrate into your CI/CD pipeline for automated notifications.

!!! tip "Test After Updates"

    Always run your test suite after updating dependencies:
    ```bash
    depkeeper update -y && pytest
    ```

!!! warning "Major Versions"

    depkeeper won't cross major version boundaries automatically. When you're ready for a major upgrade, update manually and test thoroughly.
