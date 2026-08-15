---
title: User Guide
description: Task-oriented guides for operating depkeeper
---

# User Guide

Task-oriented documentation. For the model behind these tasks, see
[Core Concepts](../concepts/index.md); for exhaustive flag lists, see
[Reference](../reference/index.md).

<div class="grid cards" markdown>

- :material-magnify:{ .lg .middle } **[Checking for updates](checking-updates.md)**

    ---

    The read-only report: filters, formats, streams and how to consume them.

- :material-update:{ .lg .middle } **[Updating dependencies](updating-dependencies.md)**

    ---

    Applying changes safely: previews, selection, pin mode, hashes, backups.

- :material-cog:{ .lg .middle } **[Configuration](configuration.md)**

    ---

    Config files, environment variables and the precedence rules between them.

- :material-pipe:{ .lg .middle } **[CI/CD integration](ci-cd-integration.md)**

    ---

    Gating builds, opening update pull requests, and scheduled drift reports.

- :material-server:{ .lg .middle } **[Operations](operations.md)**

    ---

    Networking, caching, performance, security posture and diagnostics.

- :material-star:{ .lg .middle } **[Best practices](best-practices.md)**

    ---

    How to structure requirements files so depkeeper produces good answers.

- :material-wrench:{ .lg .middle } **[Troubleshooting](troubleshooting.md)**

    ---

    Symptom-indexed diagnosis and recovery.

</div>

---

## Workflow cheat sheet

=== "Daily development"

    ```bash
    depkeeper check --outdated-only     # what moved?
    depkeeper update --dry-run          # what would change?
    depkeeper update --backup           # apply, keeping a copy
    pip install -r requirements.txt && pytest
    ```

=== "Reviewing a single package"

    ```bash
    depkeeper check --format json | jq '.[] | select(.name == "django")'
    depkeeper update -p django --dry-run
    ```

=== "CI drift report"

    ```bash
    depkeeper check --format json --no-check-conflicts > report.json
    jq '[.[] | select(.status == "outdated")] | length' report.json
    ```

=== "Release preparation"

    ```bash
    depkeeper update --pin --backup     # freeze to exact versions
    pip install -r requirements.txt
    pytest
    git diff requirements.txt
    ```

=== "Multi-file project"

    ```bash
    depkeeper update requirements/base.txt --dry-run   # follows -r includes
    depkeeper check requirements/dev.txt
    ```
