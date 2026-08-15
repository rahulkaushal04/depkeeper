---
title: Configuration
description: Configuration files, discovery, environment variables and precedence
---

# Configuration

depkeeper reads two settings from a TOML file. Everything else is a command-line flag. This is
deliberate: options that change *what gets written* stay visible in the invocation.

---

## Supported settings

| Key | Type | Default | Effect |
|---|---|---|---|
| `check_conflicts` | boolean | `true` | Run cross-package conflict resolution. |
| `strict_version_matching` | boolean | `false` | Only a sole `==` specifier counts as a current version. |

There are no other keys. An unrecognised key is a **hard error**, not a warning — silently
ignoring a typo would leave you believing a setting is in effect when it is not:

```text
[ERROR] Unknown configuration keys: check_conflict (config_path=/path/bad.toml)
```

Exit code `1`. A non-boolean value is rejected the same way:

```text
[ERROR] check_conflicts must be a boolean, got str (config_path=..., option=check_conflicts)
```

---

## File formats

=== "depkeeper.toml"

    ```toml title="depkeeper.toml"
    [depkeeper]
    check_conflicts = true
    strict_version_matching = false
    ```

=== "pyproject.toml"

    ```toml title="pyproject.toml"
    [tool.depkeeper]
    check_conflicts = true
    strict_version_matching = false
    ```

Both are equivalent. Use `pyproject.toml` if the project already has one; use `depkeeper.toml`
to keep tool configuration separate.

---

## Discovery

In order, stopping at the first match:

1. The path given by `--config` / `-c`, or the `DEPKEEPER_CONFIG` environment variable.
2. `depkeeper.toml` in the **current working directory**.
3. `pyproject.toml` in the current working directory — **only if** it actually contains a
   `[tool.depkeeper]` table.
4. Built-in defaults.

Two consequences worth knowing:

- Discovery is **not** recursive. depkeeper does not walk up to the repository root. Running
  `depkeeper check` from a subdirectory will not find the config file at the top of the repo.
  Pass `--config` explicitly, or run from the directory holding the file.
- A `pyproject.toml` without a `[tool.depkeeper]` table is skipped rather than adopted, so a
  project that merely has one does not shadow the defaults.

An explicit `--config` path that does not exist is an error:

```text
[ERROR] Configuration file not found: missing.toml (config_path=missing.toml)
```

A config file that exists but has no depkeeper section is valid and yields the defaults.

---

## Precedence

```text
built-in defaults  <  config file  <  command-line flag
```

The flags participating in this chain are `--strict-version-matching` and
`--check-conflicts/--no-check-conflicts`. Both default to "unset" internally, so passing neither
means "use the config value"; passing either overrides it for that invocation.

```toml title="depkeeper.toml"
[depkeeper]
check_conflicts = false
```

```bash
depkeeper check                        # conflicts NOT checked  (file)
depkeeper check --check-conflicts      # conflicts checked      (flag wins)
```

!!! note "`--strict-version-matching` is a flag, not a toggle"

    There is no `--no-strict-version-matching`. If the config file sets it to `true`, you cannot
    turn it off for one invocation from the command line. Point `--config` at a different file, or
    change the file.

All other options — `--format`, `--outdated-only`, `--dry-run`, `--backup`, `--pin`,
`--allow-hash-removal`, `--packages` — are **not** configurable. They must be supplied per run.

---

## Environment variables

| Variable | Read by | Effect |
|---|---|---|
| `DEPKEEPER_CONFIG` | `--config` | Path to a configuration file. |
| `DEPKEEPER_COLOR` | `--color/--no-color` | Enables or disables colour. Click parses standard boolean spellings (`1`/`0`, `true`/`false`, `yes`/`no`). |
| `NO_COLOR` | `rich`, `click`, the logger | Any non-empty value disables colour. depkeeper also **sets or clears this variable itself** based on the resolved `--color` value, so downstream libraries honour the flag. |
| `CI` | the logger | Any non-empty value disables ANSI colour in log records, because build-log viewers render raw escape sequences. |

```bash
export DEPKEEPER_CONFIG=/etc/depkeeper/ci.toml
export NO_COLOR=1
depkeeper check
```

Colour is additionally probed **per stream**: a piped stdout does not disable colour on an
interactive stderr, which is what keeps `depkeeper check -f json | jq` readable and parseable at
the same time.

---

## Verbosity

Verbosity is a CLI-only setting; it cannot be configured in a file.

| Flag | Level | What appears on stderr |
|---|---|---|
| *(none)* | `WARNING` | Warnings and errors only. |
| `-v` | `INFO` | Phase progress, resolution decisions, adopted alternatives, backups created. |
| `-vv` | `DEBUG` | Per-package decisions, cache hits, HTTP retries, per-line rewrites. |

`-v` also causes `update` to print the Resolution Summary, and causes `check` to print status
output in machine-readable formats (still on stderr).

---

## Recommended configurations

=== "Application repository"

    ```toml title="pyproject.toml"
    [tool.depkeeper]
    check_conflicts = true
    strict_version_matching = false
    ```

    Plus the usual invocation:

    ```bash
    depkeeper update --pin --backup
    ```

=== "Library repository"

    ```toml title="pyproject.toml"
    [tool.depkeeper]
    check_conflicts = true
    strict_version_matching = false
    ```

    Never use `--pin` here; ranges are part of the library's contract.

=== "CI drift report"

    ```toml title="ci/depkeeper.toml"
    [depkeeper]
    check_conflicts = false      # faster, fewer PyPI requests
    ```

    ```bash
    depkeeper --config ci/depkeeper.toml check --format json
    ```

=== "Lockfile-style file of exact pins"

    ```toml title="depkeeper.toml"
    [depkeeper]
    strict_version_matching = true
    ```

    Only `==` pins are treated as current versions; anything else is reported as `install`.

---

## Inspecting the effective configuration

```bash
depkeeper -vv check 2>&1 | head -n 5
```

```text
DEBUG: depkeeper v0.1.0
DEBUG: Config path: /path/to/depkeeper.toml
DEBUG: Loaded configuration: {'check_conflicts': True, 'strict_version_matching': False}
DEBUG: Verbosity: 2 | Color: True
```

If `Config path` is `None`, no configuration file was discovered and the built-in defaults are in
effect — the most common cause is running from a directory other than the one containing the file.

---

## Encoding

Configuration files are decoded as `utf-8-sig`, so a file saved by a Windows editor with a byte
order mark parses correctly. TOML parsers otherwise reject a BOM as an invalid statement. A file
that is not valid UTF-8 raises:

```text
[ERROR] Configuration file depkeeper.toml is not valid UTF-8: <detail>
```

Invalid TOML raises `Invalid TOML in <file>: <detail>`.
