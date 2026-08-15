---
title: Installation
description: Install depkeeper with pip or pipx, verify the install, and understand its runtime dependencies
---

# Installation

## Prerequisites

| Item | Requirement | Notes |
|---|---|---|
| Python | ≥ 3.8 | Declared as `requires-python = ">=3.8"`. |
| OS | Linux, macOS, Windows | Path handling, atomic writes and byte-order-mark handling are tested on all three. |
| Network | HTTPS to `pypi.org` | Required at runtime, not only at install time. |

!!! warning "The interpreter matters"

    depkeeper filters candidate versions using the `requires_python` metadata of each release,
    compared against **the interpreter depkeeper itself is running on** — not the interpreter of
    your project's virtual environment.

    If you install depkeeper globally on Python 3.8 but your service targets Python 3.12,
    depkeeper will refuse versions that dropped 3.8 support even though your project could use
    them. Install it *into the environment whose requirements file you are managing*, or use a
    `pipx` install whose Python matches. See
    [Version recommendation](../concepts/version-recommendation.md#python-compatibility-filtering).

---

## Install

=== "pip (project environment — recommended)"

    ```bash
    python -m pip install depkeeper
    ```

    Installing into the project's own virtual environment guarantees the interpreter used for
    compatibility filtering matches the project's target interpreter.

=== "pipx (isolated global tool)"

    ```bash
    pipx install depkeeper

    # Pin the interpreter to match your projects
    pipx install --python python3.12 depkeeper
    ```

    Use `pipx` when you manage many projects that all target the same Python version.

=== "From source"

    ```bash
    git clone https://github.com/rahulkaushal04/depkeeper.git
    cd depkeeper
    python -m pip install -e .
    ```

    For a full contributor setup (dev extras, pre-commit, test tooling), follow
    [Development setup](../contributing/development-setup.md).

=== "CI (ephemeral)"

    ```bash
    python -m pip install --no-cache-dir depkeeper==0.1.1
    ```

    Pin the version in CI. depkeeper is still `0.x`, so an unpinned install can change
    recommendation behaviour between pipeline runs.

---

## Runtime dependencies

These are installed automatically. They are listed here because they determine depkeeper's
behaviour in ways that matter operationally.

| Package | Minimum | Why it is required |
|---|---|---|
| `click` | 8.1.8 | CLI parsing, `--help`, usage errors (exit code 2), confirmation prompt. |
| `packaging` | 23.2 | Every version comparison, specifier evaluation and PEP 503 name normalisation. depkeeper delegates all of these so it agrees with pip. |
| `httpx[http2]` | 0.24.1 | Async HTTP with HTTP/2 to the PyPI JSON API. |
| `rich` | 13.9.4 | Table and status rendering, colour detection. |
| `tomli` | 2.4.0 | TOML parsing for `depkeeper.toml` / `pyproject.toml`. A hard dependency on **all** Python versions, so 3.8–3.10 and 3.11+ parse configuration identically. |

Optional extras: `depkeeper[dev]`, `depkeeper[test]`, `depkeeper[docs]`. See
[Development setup](../contributing/development-setup.md).

---

## Verify the installation

```bash
depkeeper --version
# depkeeper 0.1.1

depkeeper --help
python -m depkeeper --version   # equivalent module entry point
```

Both entry points are supported:

- `depkeeper` — console script declared as `depkeeper.cli:main`.
- `python -m depkeeper` — module entry point that imports and delegates to the same function.
  Use this when the script directory is not on `PATH`.

A functional smoke test that requires no project files:

```bash
printf 'requests==2.28.0\n' > /tmp/req.txt
depkeeper check /tmp/req.txt --format json
```

A JSON array on stdout confirms parsing, network access and rendering all work.

---

## Upgrading

```bash
python -m pip install --upgrade depkeeper
pipx upgrade depkeeper
```

Before upgrading in an automated pipeline, read the [changelog](../community/changelog.md).
Recommendation logic changes are behavioural changes: the same requirements file can produce a
different update plan after an upgrade. Pipelines that gate on `depkeeper check --format json`
output should pin the version and upgrade deliberately.

---

## Uninstalling

```bash
python -m pip uninstall depkeeper
pipx uninstall depkeeper
```

depkeeper stores no state outside the working directory. It writes nothing to `$HOME`, creates no
cache directory, and its in-memory PyPI cache lives only for the duration of a single command.
The only artefacts it can leave behind are the backup files created by `update --backup`
(see [Updating dependencies](../guides/updating-dependencies.md#backups)).

---

## Troubleshooting the install

| Symptom | Cause | Fix |
|---|---|---|
| `depkeeper: command not found` | Script directory not on `PATH`. | Use `python -m depkeeper`, or add the interpreter's `Scripts`/`bin` directory to `PATH`. |
| `ERROR: Package 'depkeeper' requires a different Python` | Interpreter older than 3.8. | Install on 3.8+. |
| SSL errors on first run | Corporate TLS interception. | See [Operations → TLS and proxies](../guides/operations.md#tls-and-proxies). |
| Recommendations look too conservative | depkeeper is running on an older interpreter than your project targets. | Reinstall into the project environment, or `pipx install --python`. |

Further symptoms are indexed in [Troubleshooting](../guides/troubleshooting.md).
