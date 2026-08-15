---
title: CLI Commands
description: Complete command-line specification for depkeeper
---

# CLI Commands

```text
depkeeper [GLOBAL OPTIONS] COMMAND [COMMAND OPTIONS] [FILE]
```

Two entry points are installed and behave identically:

| Entry point | Use |
|---|---|
| `depkeeper` | Console script (`depkeeper.cli:main`). |
| `python -m depkeeper` | Module entry point. Use when the script directory is not on `PATH`. |

---

## Global options

| Option | Short | Env var | Default | Description |
|---|---|---|---|---|
| `--config PATH` | `-c` | `DEPKEEPER_CONFIG` | auto-discovered | Path to a configuration file. Must exist and be a file. |
| `--verbose` | `-v` | — | `0` | Repeatable. `-v` → INFO, `-vv` (or more) → DEBUG. |
| `--color / --no-color` | — | `DEPKEEPER_COLOR` | `--color` | Enable or disable coloured output. Also sets/clears `NO_COLOR` in the environment for downstream libraries. |
| `--version` | — | — | — | Print `depkeeper <version>` and exit. |
| `--help` | `-h` | — | — | Show help and exit. |

Global options must appear **before** the subcommand:

```bash
depkeeper -v check          # ✅
depkeeper check -v          # ❌ Error: No such option: -v
```

### Verbosity

| Flag | Level | Emitted on stderr |
|---|---|---|
| *(none)* | `WARNING` | Warnings and errors. |
| `-v` | `INFO` | Phase progress, resolution decisions, backups, rollbacks. Also enables the Resolution Summary for `update`, and status output for machine-readable `check` formats. |
| `-vv`+ | `DEBUG` | Cache behaviour, per-candidate decisions, HTTP retries, per-line rewrites, effective configuration. |

---

## `check`

Analyse a requirements file and report available updates. **Never writes to the filesystem.**

```text
depkeeper check [OPTIONS] [FILE]
```

### Arguments

| Argument | Type | Default | Notes |
|---|---|---|---|
| `FILE` | existing file path | `requirements.txt` | Must exist and must not be a directory. Validated by Click; a bad value exits `2`. |

### Options

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--outdated-only` | — | flag | off | Show only packages that have an update **or** a recorded conflict. |
| `--format` | `-f` | `table` \| `simple` \| `json` | `table` | Output format. Case-insensitive. |
| `--strict-version-matching` | — | flag | config, then `false` | Only a sole `==` specifier counts as a current version. |
| `--check-conflicts / --no-check-conflicts` | — | flag pair | config, then `true` | Enable cross-package conflict resolution. |

### Behaviour

1. Parse the file, following `-r` includes and loading `-c` constraints.
2. Prefetch PyPI metadata for every unique package.
3. Compute a recommendation per package.
4. Optionally resolve cross-package conflicts.
5. Filter if `--outdated-only`.
6. Render.

Exits `0` on success regardless of findings; `1` on error. See [Exit codes](exit-codes.md).

### Output streams

| Format | stdout | stderr |
|---|---|---|
| `table` | report and status messages | log records |
| `simple` | package lines only | status messages, warnings, errors, log records |
| `json` | the JSON document only | status messages, warnings, errors, log records |

`--format json` always emits a document — `[]` when there is nothing to report — including on the
"no packages found" and "nothing to display" paths.

### Examples

```bash
depkeeper check
depkeeper check requirements-dev.txt
depkeeper check --outdated-only
depkeeper check --format json > report.json
depkeeper check --no-check-conflicts              # faster, fewer PyPI requests
depkeeper check --strict-version-matching
depkeeper -v check --format json | jq 'length'    # status output stays on stderr
```

---

## `update`

Apply recommended versions to a requirements file.

```text
depkeeper update [OPTIONS] [FILE]
```

### Arguments

| Argument | Type | Default | Notes |
|---|---|---|---|
| `FILE` | existing file path | `requirements.txt` | Must exist. Files reached through `-r` includes are also written. |

### Options

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--dry-run` | — | flag | off | Run the full pipeline and print the plan; write nothing. |
| `--yes` | `-y` | flag | off | Skip the confirmation prompt. |
| `--backup` | — | flag | off | Create a timestamped backup of **every** affected file before writing. |
| `--pin` | — | flag | off | Replace every specifier with `==<version>` instead of preserving the declared range. |
| `--allow-hash-removal` | — | flag | off | Permit updating requirements that carry `--hash` entries, removing those hashes. |
| `--packages` | `-p` | string, repeatable | all | Restrict the update to these packages. Matched in PEP 503 canonical form. |
| `--strict-version-matching` | — | flag | config, then `false` | Only a sole `==` specifier counts as a current version. |
| `--check-conflicts / --no-check-conflicts` | — | flag pair | config, then `true` | Enable cross-package conflict resolution. |

### Behaviour

1. Parse, prefetch, recommend, resolve — identical to `check`.
2. Filter by `--packages` if given.
3. Determine which requirements need a change.
4. Refuse hashed requirements unless `--allow-hash-removal`.
5. Print the update plan.
6. Stop here if `--dry-run`.
7. Prompt unless `-y`.
8. Create backups if `--backup`.
9. Render all affected files in memory, then commit each atomically, rolling back on failure.

### Confirmation prompt

```text
Update 3 packages? (y, n) [y]:
```

Defaults to yes. Invalid input re-prompts. Declining writes nothing and exits `0`.

### Which requirements are updated

| Condition | Updated? |
|---|---|
| Recommended version is higher than current | Yes |
| No current version (unversioned requirement) | Yes — a pin is added |
| A downgrade is required | Yes |
| Direct reference (URL / VCS / local path) or `-e` editable | Never |
| Target excluded by the declared constraints (without `--pin`) | No — skipped with a warning |
| Rewrite would produce a byte-identical line | No — skipped, ensuring convergence |
| Package has `--hash` entries and `--allow-hash-removal` is absent | No — the whole command fails |

### Rewrite semantics

Without `--pin`, only the floor moves:

```text
requests==2.28.0           → requests==2.34.2
flask>=2.0,<2.3            → flask>=2.2.5,<2.3
celery[redis]>=5.0,<6.0    → celery[redis]>=5.6.3,<6.0
click~=8.0                 → click~=8.4
certifi                    → certifi==2026.7.22
```

With `--pin`:

```text
celery[redis]>=5.0,<6.0    → celery[redis]==5.6.3
```

Comments, blank lines, directives, extras, markers, line endings and encoding are preserved. See
[Write safety](../concepts/write-safety.md).

### Examples

```bash
depkeeper update --dry-run
depkeeper update --backup
depkeeper update -y                               # non-interactive
depkeeper update -p flask -p click
depkeeper update --pin --backup                   # lockfile-style
depkeeper update --allow-hash-removal -y          # then regenerate hashes
depkeeper update requirements/dev.txt --dry-run   # also writes files it includes
```

---

## Option precedence

```text
built-in default  <  configuration file  <  command-line flag
```

Only `--strict-version-matching` and `--check-conflicts` participate. Every other option is
per-invocation.

!!! note "No negative form for `--strict-version-matching`"

    If a configuration file sets it to `true`, it cannot be disabled from the command line. Use a
    different `--config` file.

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success. For `check`, includes "updates were found". For `update`, includes "user declined" and "nothing to do". |
| `1` | Application error: parse failure, config error, write failure, refused hashed update, unexpected exception. |
| `2` | Usage error from Click: unknown option, bad argument value, missing file. |
| `130` | Interrupted with `Ctrl+C`. |

Detail and scripting patterns: [Exit codes](exit-codes.md).

---

## Environment variables

| Variable | Effect |
|---|---|
| `DEPKEEPER_CONFIG` | Default value for `--config`. |
| `DEPKEEPER_COLOR` | Default value for `--color/--no-color`. |
| `NO_COLOR` | Any non-empty value disables colour. depkeeper also sets or clears it to match the resolved flag. |
| `CI` | Any non-empty value disables ANSI colour in log records. |
| `HTTPS_PROXY`, `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE` | Honoured by `httpx`. See [Operations](../guides/operations.md#tls-and-proxies). |

---

## Not available in 0.1.0

There is no command or flag for: initialising a config file, adding or removing a requirement,
scanning for security advisories, generating a lock file, selecting a package index, overriding
the target Python version, tuning timeouts or concurrency, or discovering requirements files
recursively. See [Known limitations](limitations.md).
