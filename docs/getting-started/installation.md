---
title: Installation
description: Install depkeeper with pip or pipx, verify the install, and understand its runtime dependencies
---

# Installation

## Prerequisites

| Item | Requirement | Notes |
|---|---|---|
| Python | ≥ 3.8 | Declared as `requires-python = ">=3.8"`. |
| OS | Linux, macOS, Windows | Path handling, atomic writes and byte-order-mark handling are covered for all three. |
| Network | HTTPS to `pypi.org` | Required at runtime, not only at install time. |

> [!NOTE]
> **Which Python is targeted**
>
> depkeeper filters candidate versions using the `requires_python` metadata of each release.
> The target Python is, in order: `--python-version X.Y`, config `python_version`, the
> `requires-python` declared by the file being checked (`pyproject.toml`, or the conda `python`
> pin; the lowest supported minor is used), and finally the interpreter depkeeper itself runs on.
>
> A plain `requirements.txt` declares nothing, so there the running interpreter is used. If
> depkeeper runs on Python 3.8 but your service targets 3.12, pass `--python-version 3.12` (or set
> `python_version` in config). See
> [Version recommendation](../concepts/version-recommendation.md#python-compatibility-filtering).

---

## Install

**pip (project environment — recommended)**

```bash
python -m pip install depkeeper
```

Installing into the project's own virtual environment makes the fallback interpreter match the
project's. `--python-version` overrides it either way.

**pipx (isolated global tool)**

```bash
pipx install depkeeper

# Optionally pick the interpreter pipx uses
pipx install --python python3.12 depkeeper
```

Use `pipx` for a global tool; pass `--python-version` per project when targets differ.

**From source**

```bash
git clone https://github.com/rahulkaushal04/depkeeper.git
cd depkeeper
python -m pip install -e .
```

For a full contributor setup (dev extras, pre-commit, test tooling), follow
[Development setup](../contributing/development-setup.md).

**CI (ephemeral)**

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
| `tomli` | 2.4.0 | TOML parsing for `depkeeper.toml` / `pyproject.toml` (config and the `pyproject.toml` source adapter). A hard dependency on **all** Python versions, so 3.8–3.10 and 3.11+ behave identically. |

Optional extras: `depkeeper[dev]` and `depkeeper[test]` (both for contributors). See
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

A JSON array on stdout confirms parsing, network access and rendering all work. (`check` exits `4` if a package could not be looked up.)

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
| Recommendations look too conservative | The target Python is older than your project's (e.g. a `requires-python` floor, or an old running interpreter), or the major boundary is holding. | Pass `--python-version X.Y`; use `--allow-major PKG` for majors. |

Further symptoms are indexed in [Troubleshooting](../guides/troubleshooting.md).
