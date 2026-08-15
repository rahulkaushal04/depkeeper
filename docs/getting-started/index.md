---
title: Getting Started
description: Install depkeeper, run your first check, and understand what it reports
---

# Getting Started

This section takes you from an empty shell to a rewritten requirements file, and explains what
depkeeper decided along the way.

Read it in order:

1. **[Installation](installation.md)** — supported platforms, install methods, verification.
2. **[Quick Start](quickstart.md)** — the shortest path to a safe update.
3. **[Basic Usage](basic-usage.md)** — reading the output, and the decisions behind each column.

Once you are comfortable, continue to [Core Concepts](../concepts/index.md) for the model
depkeeper uses internally, or to the [User Guide](../guides/index.md) for task-oriented workflows.

---

## Prerequisites

| Requirement | Detail |
|---|---|
| Python | 3.8 or later. depkeeper filters candidate versions against **the interpreter it runs under**. |
| Network | Outbound HTTPS to `pypi.org`. depkeeper has no offline mode; see [Operations](../guides/operations.md#network-requirements). |
| Input file | A pip-style requirements file. `requirements.txt` is the default argument. |

depkeeper never installs, uninstalls or imports the packages it analyses. It reads metadata from
the PyPI JSON API only, so it is safe to run against a file describing an environment you do not
have installed.

---

## The 60-second version

```bash
pip install depkeeper           # or: pipx install depkeeper
depkeeper check                 # read-only report
depkeeper update --dry-run      # show exactly what would be written
depkeeper update --backup       # write it, keeping a timestamped copy
```

`check` never modifies anything. `update` prompts before writing unless you pass `-y`.

---

## What depkeeper decides for you

Before running it against a real project, understand the four rules that shape every
recommendation. All four are enforced, not advisory:

| Rule | Effect | Reference |
|---|---|---|
| Major boundary | A package on `1.x` is never moved to `2.x`. | [Version recommendation](../concepts/version-recommendation.md#the-major-version-boundary) |
| Python compatibility | Versions whose `requires_python` excludes your interpreter are skipped. | [Version recommendation](../concepts/version-recommendation.md#python-compatibility-filtering) |
| Declared constraints | Upper bounds and exclusions you wrote are preserved and are never violated. | [Version recommendation](../concepts/version-recommendation.md#constraint-preservation) |
| No pre-releases | Alpha/beta/rc versions are excluded from every candidate list. | [Version recommendation](../concepts/version-recommendation.md#pre-releases) |

If any of these produce an unwanted result, that is a configuration or workflow question, not a
bug. [Best practices](../guides/best-practices.md) covers how to work with them.
