---
title: Home
description: Modern, intelligent Python dependency management for requirements.txt files
---

# depkeeper

<div class="hero" markdown>

**Modern, intelligent Python dependency management for `requirements.txt` files.**

Keep your dependencies up-to-date and conflict-free — without switching from pip.

[:material-download: Install](getting-started/installation.md){ .md-button .md-button--primary }
[:material-book-open-variant: Get Started](getting-started/quickstart.md){ .md-button }
[:material-github: GitHub](https://github.com/rahulkaushal04/depkeeper){ .md-button }

</div>

---

## Why depkeeper?

Managing Python dependencies shouldn't be painful. While `pip` is simple and Poetry is powerful, depkeeper bridges the gap — giving you **smart automation** without abandoning your existing workflow.

<div class="grid cards" markdown>

- :material-lightning-bolt:{ .lg .middle } **Smart Updates**

  ***

  Automatically discover available updates with intelligent recommendations that respect semantic versioning boundaries.

- :material-shield-check:{ .lg .middle } **Safe by Default**

  ***

  Never accidentally cross major version boundaries. depkeeper keeps your environment stable while staying current.

- :material-vector-triangle:{ .lg .middle } **Conflict Resolution**

  ***

  Detect and resolve dependency conflicts before they break your builds.

- :material-rocket-launch:{ .lg .middle } **Fast & Concurrent**

  ***

  Async PyPI queries maximize performance. Check hundreds of packages in seconds.

- :material-format-list-bulleted:{ .lg .middle } **Multiple Formats**

  ***

  Output as beautiful tables, simple text, or JSON for seamless CI/CD integration.

- :material-puzzle:{ .lg .middle } **Pip Compatible**

  ***

  Works alongside pip, not instead of it. No need to change your workflow.

</div>

---

## Quick Example

```bash
# Check for available updates
$ depkeeper check

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

```bash
# Update all packages safely
$ depkeeper update

Updating requirements.txt...

Package       Current    →  Recommended  Type
─────────────────────────────────────────────
requests      2.28.0     →  2.32.0       minor
flask         2.0.0      →  2.3.3        patch
click         8.0.0      →  8.1.7        minor

Apply 3 updates? [y/N]: y

✓ Successfully updated 3 packages
```

---

## Feature Comparison

| Feature                  | pip | Poetry | depkeeper |
| ------------------------ | --- | ------ | --------- |
| Simple workflow          | ✅  | ⚠️     | ✅        |
| Dependency resolution    | ❌  | ✅     | ✅        |
| Update recommendations   | ❌  | ⚠️     | ✅        |
| Major version boundaries | ❌  | ❌     | ✅        |
| Conflict detection       | ❌  | ✅     | ✅        |
| CI/CD friendly           | ✅  | ✅     | ✅        |
| requirements.txt support | ✅  | ❌     | ✅        |
| No lock-in               | ✅  | ❌     | ✅        |

---

## Installation

=== "pip"

    ```bash
    pip install depkeeper
    ```

=== "pipx (isolated)"

    ```bash
    pipx install depkeeper
    ```

=== "From source"

    ```bash
    git clone https://github.com/rahulkaushal04/depkeeper.git
    cd depkeeper
    pip install -e .
    ```

---

## What's Next?

<div class="grid cards" markdown>

- :material-play-circle:{ .lg .middle } **[Quick Start](getting-started/quickstart.md)**

  ***

  Get up and running in 5 minutes with the essentials.

- :material-school:{ .lg .middle } **[User Guide](guides/index.md)**

  ***

  Deep dive into all features and workflows.

- :material-api:{ .lg .middle } **[API Reference](reference/python-api.md)**

  ***

  Integrate depkeeper programmatically.

- :material-account-group:{ .lg .middle } **[Contributing](contributing/index.md)**

  ***

  Help make depkeeper even better.

</div>

---

## Acknowledgments

Built with amazing open source libraries:

- [Click](https://click.palletsprojects.com/) — CLI framework
- [Rich](https://rich.readthedocs.io/) — Beautiful terminal formatting
- [httpx](https://www.python-httpx.org/) — Async HTTP client
- [packaging](https://packaging.pypa.io/) — PEP 440/508 compliance

Inspired by [pip-tools](https://pip-tools.readthedocs.io/), [Poetry](https://python-poetry.org/), and [Dependabot](https://github.com/dependabot).

---

<div class="footer-cta" markdown>

**Ready to simplify your dependency management?**

[:material-download: Get Started](getting-started/installation.md){ .md-button .md-button--primary }

</div>
