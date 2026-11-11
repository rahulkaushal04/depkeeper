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
| `FILE` | existing file or directory | `requirements.txt`, else the supported files found in the current directory | Must exist (a missing path exits `2`). A directory is scanned for `requirements*.txt`, `pyproject.toml` and `environment.yml`/`environment.yaml` (not recursively); no supported file is an error (exit `1`). |

### Options

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--outdated-only` | — | flag | off | Show only packages that have an update **or** a recorded conflict. |
| `--format` | `-f` | `table` \| `simple` \| `json` \| `json-v2` \| `markdown` | `table` | Output format. Case-insensitive. |
| `--python-version` | — | `X.Y` | see [Target Python](#target-python) | Python version recommendations must support. |
| `--min-age` | — | duration (`7d`, `12h`, `2w`; bare number = days) | config `min_age` | Do not recommend versions released more recently than this. |
| `--allow-major` | — | `PKG`, repeatable (`'*'` = all) | none | Let this package cross its current major. Your own upper bounds still apply (`django>=3.2,<5.0` moves to the newest `4.x`, never `5.x`). A name that is not in the file warns. See [Opt-in major upgrades](#opt-in-major-upgrades). |
| `--strict-version-matching / --no-strict-version-matching` | — | flag pair | config, then `false` | Only a sole `==` specifier counts as a current version. |
| `--check-conflicts / --no-check-conflicts` | — | flag pair | config, then `true` | Enable cross-package conflict resolution. |
| `--fail-on` | — | `none` \| `updates` \| `minor` \| `major` | config, then `none` | Exit `3` when updates at that level are found (`updates` = any update, conflict or downgrade; `minor` = minor or major; `major` = major only). |
| `--ignore PKG` | — | repeatable | config `ignore`, plus flags | Skip a package entirely (name-normalised). Ignored packages do not take part in conflict analysis. |

### Behaviour

1. Parse the file, following `-r` includes and loading `-c` constraints.
2. Prefetch PyPI metadata for every unique package.
3. Compute a recommendation per package.
4. Optionally resolve cross-package conflicts.
5. Filter if `--outdated-only`.
6. Render.

Exits `0` on success unless `--fail-on` trips (`3`) or a package could not be looked up (`4`). A lookup failure (unknown package, network error) is reported on stderr (`N package(s) could not be checked: ...`) and in JSON as `"status": "no-update"` with an `error` field; it is never reported as "up to date", even with `--outdated-only`. See [Exit codes](exit-codes.md).

### Output streams

| Format | stdout | stderr |
|---|---|---|
| `table` | report and status messages | log records |
| `simple` | package lines only | status messages, warnings, errors, log records |
| `json` | the JSON document only | status messages, warnings, errors, log records |
| `json-v2` | the JSON envelope only | status messages, warnings, errors, log records |
| `markdown` | the Markdown report only | status messages, warnings, errors, log records |

`--format json` always emits a document — `[]` when there is nothing to report — including on the
"no packages found" and "nothing to display" paths.

### Target Python

Candidates must support one Python version, chosen by the first rule that applies:

1. `--python-version X.Y`
2. config `python_version`
3. the source file's own declaration: `requires-python` in `pyproject.toml` or the `python` pin in a conda
   `environment.yml`. The **lowest** minor version the specifier allows is used (`>=3.9,<3.13` gives `3.9`,
   `>3.8` gives `3.9`, `>=3.8.5` gives `3.8`; a bare major such as conda `python=3` names no minor and is ignored), so a recommendation works on every Python the project supports. With several files the
   lowest minimum across them wins.
4. the running interpreter

`-v` logs which rule decided (`Target Python: 3.9 (from pyproject.toml requires-python)`).

### Opt-in major upgrades

By default depkeeper never recommends a version in a higher major than the current one. A newer major
that your declared range allows is reported instead, as `major available: django 4.2.16 (use --allow-major django)`
in the notices, in a `Major updates available (not applied)` section of `--format markdown`, and as an
optional `major_available` key in `json` and `json-v2`.

`--allow-major django` (repeatable; `--allow-major '*'` for every package) or `allow_major = true` in
`[depkeeper.packages.django]` lets that package cross its major. The newest version that satisfies your
own specifiers, the target Python and the `min_age` cooldown is chosen, so `django>=3.2,<5.0` moves to the
newest `4.x`; releases beyond your own upper bound are never applied. Bounds implied by `~=` count too:
`click~=7.0` means `>=7.0,<8.0`, so `click` stays on `7.x` (no recommendation and no `major available` hint for `8.x`). A `==` pin
is not a cap: it is moved with the version. `--max-update minor` (or the
`max_update` policy) still wins: the best version within the cap is chosen and the major stays in
`major_available`, reported as `blocked by max_update`. `hold` and `ignore` also win.
`--fail-on major` trips on a proposed major, not on `major_available`. `update` prints
`N major upgrade(s) applied: <names>. Run --verify and your tests.` when it applies one.

### Release age and policy markers

Where PyPI upload dates are known, `simple` prints `released N days ago`, `table` adds `12d old` under the
recommended version and `markdown`/`json-v2` carry `age_days`. A version withheld by the `min_age` cooldown
is shown as `<version> held` in the table, `cooldown: <version> withheld` in `simple`, and in a
`held back by min_age cooldown` notice.

A package frozen by per-package policy (`hold`) is shown as `[HELD]` and one with `ignore = true` as
`[IGNORED]`. Calver packages use the labels `year`, `month` and `patch`; for `--fail-on` and
`update --max-update` a calver `year` or `month` change counts as `minor` by design (`gating_type`
maps `year` to `minor`), so `--fail-on major` never trips on a calver year bump; use `--fail-on minor`
or `updates`. Per-package `max_update` in the config ranks `year` as `major`.

With more than one source file (a directory, `-r` includes) `table` adds a *Source* column and `simple` a
`Source:` line (`path:line`, plus the file format).

### `--format json-v2`

`--format json` keeps its bare array (stable; it only gains the optional keys `links` and `ignored`).
`--format json-v2` is a versioned envelope:

```json
{
  "schema_version": 2,
  "summary": {"total": 3, "outdated": 1, "up_to_date": 1, "held": 1, "ignored": 0,
              "conflicts": 0, "errors": 0, "by_update_type": {"minor": 1}},
  "python": {"version": "3.9", "source": "pyproject.toml requires-python"},
  "files": [{"path": "/abs/requirements.txt", "format": "requirements.txt", "packages": 3}],
  "packages": [{
    "name": "requests", "status": "outdated", "update_type": "minor", "versioning": "semver",
    "versions": {"current": "2.28.0", "latest": "2.32.0", "recommended": "2.32.0"},
    "file": "/abs/requirements.txt", "line": 1, "source_format": "requirements.txt",
    "released": "2024-05-20T00:00:00+00:00", "age_days": 12,
    "held": false, "ignored": false,
    "links": {"changelog": "https://...", "homepage": "https://..."}
  }],
  "errors": [{"package": "ghost", "file": "/abs/requirements.txt", "line": 4, "message": "..."}]
}
```

Each `packages[]` entry is the bare-array entry plus `file`, `line`, `source_format`, `age_days`, `held`,
`ignored`, `versioning`, `update_type` (`null` when no update) and `links`. `links` may hold `changelog`,
`release_notes` and `homepage` (http/https URLs from PyPI `project_urls`). `python.version` is `null` for the
running interpreter. Consumers must ignore unknown keys; `schema_version` is bumped on breaking changes.

### `--format markdown`

A PR-body / CI-summary report: a summary line, tables grouped by update type (major, minor, patch, calver
`year`/`month`, newly pinned, downgrades) with current and recommended version, release age and
changelog/PyPI links, then *Held by policy*, *Cooldown*, *Conflicts* and *Lookup failures* lists
(`file:line` for multi-file runs). Example: `depkeeper check -f markdown >> "$GITHUB_STEP_SUMMARY"`.

> [!NOTE]
> **Output safety.** Anything that comes from outside (PyPI metadata, file names, error text) is printed literally: Rich markup, hyperlinks and terminal control characters (escape sequences, carriage returns, bidi overrides) are neutralised in every terminal format, and the Markdown report escapes Markdown and HTML syntax. `json`/`json-v2` values are not altered; they are JSON-escaped.

### Examples

```bash
depkeeper check
depkeeper check --min-age 7d --python-version 3.9
depkeeper check --format json-v2 | jq '.summary'
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
| `FILE` | existing file or directory | `requirements.txt`, else the supported files found in the current directory | Must exist. Files reached through `-r` includes (or found in a directory) are also written. |

### Options

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--dry-run` | — | flag | off | Run the full pipeline and print the plan; write nothing. |
| `--yes` | `-y` | flag | off | Skip the confirmation prompt. |
| `--backup` | — | flag | off | Create a timestamped backup of **every** affected file before writing. |
| `--pin` | — | flag | off | Replace every specifier with `==<version>` instead of preserving the declared range. Also required to add a pin to a bare (unpinned) name in `pyproject.toml` (build-system, Poetry, optional dependencies) or `environment.yml`; without it those entries are left unchanged. `requirements.txt` always pins bare names. |
| `--allow-hash-removal` | — | flag | off | Permit updating requirements that carry `--hash` entries, removing those hashes. |
| `--refresh-hashes` | — | flag | off | Regenerate `--hash=sha256:…` lines for the new version from PyPI file digests (every distributable file, sorted, de-duplicated, same layout as the file). Refuses the run, writing nothing, if digests cannot be fetched. Mutually exclusive with `--allow-hash-removal` (exit `2`). `--dry-run` shows what would be refreshed. Only requirements.txt files. |
| `--verify` | — | flag | off | Before writing, ask pip's resolver (`pip install --dry-run`) whether the proposed set resolves; on conflict print it and exit `1` with nothing written. Verifies for the run's target Python (see below). Skipped with a warning when it cannot be judged. |
| `--format` | `-f` | `table` \| `markdown` | `table` | `markdown` prints a PR body of what changed (or would change with `--dry-run`) on stdout; status goes to stderr. Needs `--yes` or `--dry-run` (no prompt). |
| `--python-version` | — | `X.Y` | see `check` | Same rule as `check` ([Target Python](#target-python)). |
| `--min-age` | — | duration | config `min_age` | Do not update to versions released more recently than this. |
| `--allow-major` | — | `PKG`, repeatable (`'*'` = all) | none | Let this package cross its current major, within your declared bounds. `--max-update` still caps it. See [Opt-in major upgrades](#opt-in-major-upgrades). |
| `--ignore` | — | string, repeatable | config `ignore`, plus flags | Never update this package (name-normalised). |
| `--max-update` | — | `patch` \| `minor` \| `major` | none | Largest update level to apply: the newest release within the cap is chosen (`patch` stays on the current minor). Updates above the cap are listed in a warning. |
| `--packages` | `-p` | string, repeatable | all | Restrict the update to these packages. Matched in PEP 503 canonical form. |
| `--strict-version-matching` | — | flag (no negative form) | config, then `false` | Only a sole `==` specifier counts as a current version. |
| `--check-conflicts / --no-check-conflicts` | — | flag pair | config, then `true` | Enable cross-package conflict resolution. |

### Behaviour

1. Parse, prefetch, recommend, resolve — identical to `check`.
2. Filter by `--packages` if given.
3. Determine which requirements need a change.
4. Refuse hashed requirements unless `--refresh-hashes` or `--allow-hash-removal`.
5. Print the update plan; with `--verify`, check the plan with pip's resolver.
6. Stop here if `--dry-run`.
7. Prompt unless `-y`.
8. Create backups if `--backup`.
9. Render all affected files in memory, then commit each atomically, rolling back on failure.

### What `--verify` checks

`--verify` runs `pip install --dry-run --ignore-installed --only-binary=:all: --report` over the whole final plan (also with `--packages`): updated and unchanged requirements plus every `-c` constraint, including constraints on packages that are not listed in the file. Direct URL and editable requirements are left out, and the success line says how many. It resolves for the run's target Python (`--python-version`, config, `requires-python`, else the running interpreter) by passing pip `--python-version X.Y`, so a release that needs a newer Python is rejected. Requirements whose environment marker is false for the target Python (for example `tomli; python_version < "3.11"` on 3.12) are dropped before pip sees them and counted as "skipped by markers"; if nothing is left, the check is skipped rather than reported as passing. Markers on transitive dependencies are evaluated by pip on the interpreter running it. The requirement count is pip's whole install set, transitive dependencies included. Success prints, for example:

```text
--verify: pip 24.0 resolved 14 requirements for Python 3.9 (linux-x86_64); 2 constraints applied
```

| Outcome | Result |
|---|---|
| Resolved | continue |
| Resolver conflict | exit `1`, conflicts listed, nothing written |
| Version or package not on the index | exit `1` |
| Release exists but needs a newer Python than the target | exit `1`, message names the target Python |
| Release exists only as a source distribution (the requirement itself or a transitive dependency, pinned or a range) | warning naming the package, continue: depkeeper never builds it, so it cannot judge it |
| pip missing or older than 22.2, offline, timeout (120 s, the whole pip process tree is killed) | warning, continue |
| Target differs from pip's own Python and pip is older than 23.3 | warning, continue; upgrade pip or run depkeeper with the target Python |

pip 22.2 is the floor; 23.3 is needed to verify for a Python other than the one running pip. pip's own index settings (`PIP_INDEX_URL`, ...) are honoured and URL credentials and token-like query values are redacted from output. Ctrl-C stops pip and its child processes immediately.

### Confirmation prompt

```text
Update 3 packages? (y, n) [y]:
```

Defaults to yes. Invalid input re-prompts. Declining writes nothing and exits `1`. With no terminal on stdin (and no `--yes`/`--dry-run`) the prompt cannot be asked and the command fails with exit `1` (`Cannot ask for confirmation without a terminal`); Ctrl-C / Ctrl-D at a real prompt exits `130`.

### Which requirements are updated

| Condition | Updated? |
|---|---|
| Recommended version is higher than current | Yes |
| No current version (unversioned requirement) | Yes — a pin is added |
| A downgrade is required | Yes |
| Direct reference (URL / VCS / local path) or `-e` editable | Never |
| Target excluded by the declared constraints (without `--pin`) | No — skipped with a warning |
| Rewrite would produce a byte-identical line | No — skipped, ensuring convergence |
| Package has `--hash` entries and neither `--refresh-hashes` nor `--allow-hash-removal` is given | No — the whole command fails |
| conda prefix spec that already covers the target (`numpy=1.24` vs 1.24.5) | No — the rewrite would be a no-op |

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
depkeeper update --refresh-hashes -y              # hashed lines get new sha256 hashes
depkeeper update --allow-hash-removal -y          # drop hashes instead
depkeeper update --verify -y                      # abort if pip cannot resolve the result
depkeeper update requirements/dev.txt --dry-run   # also writes files it includes
```

---

## Option precedence

```text
built-in default  <  configuration file  <  command-line flag
```

`--strict-version-matching`, `--check-conflicts`, `--fail-on`, `--python-version`, `--min-age` and `--ignore` (merged with the config list) participate. Every other option is
per-invocation.

`check --no-strict-version-matching` overrides `strict_version_matching = true` from a config file; `update` has no negative form.

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success. For `check` without `--fail-on`, includes "updates were found". For `update`, includes "nothing to do". |
| `1` | Application error: parse failure, config error, write failure, refused hashed update, unexpected exception. For `update`, also: prompt declined, `--packages` matched nothing, or `--verify` found a conflict. |
| `2` | Usage error from Click: unknown option, bad argument value, missing file, `--refresh-hashes` with `--allow-hash-removal`, `update -f markdown` without `--yes`/`--dry-run`. |
| `3` | `check --fail-on`: updates at or above the chosen level were found. |
| `4` | `check` / `update`: at least one package could not be looked up on PyPI (wins over `3`). Direct references (editable/VCS/URL) are exempt. |
| `130` | Interrupted with `Ctrl+C`, or aborted prompt (EOF). |

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

## `pyproject.toml` support

When `FILE` is (or a directory contains) a `pyproject.toml` with dependency sections, `check` and
`update` read these entries:

- `[project].dependencies`, `[project.optional-dependencies].*`
- PEP 735 `[dependency-groups].*` (`{include-group = ...}` entries are ignored)
- `[build-system].requires`
- Poetry `[tool.poetry.dependencies]`, `dev-dependencies` and `group.*.dependencies`: plain
  (`"1.2.3"`, `"==1.2.3"`, `">=1,<2"`), `^`/`~` and `{version = "..."}` forms. `python`, git, path
  and URL dependencies, `*`, list-valued entries and `||` constraints are skipped. See [File formats](file-formats.md#pyprojecttoml).

Updates replace only the version specifier characters in place: comments, quoting, layout and line
endings are untouched. Poetry `^1.2` / `~1.2` keep their style (`^1.5.0`); `--pin` writes `==`.
`requires-python` is taken from `[project].requires-python`. Invalid TOML exits with a parse error
naming the line.

---

## Not available in 1.x

There is no command or flag for: initialising a config file, adding or removing a requirement,
scanning for security advisories, generating a lock file, selecting a package index, tuning
timeouts or concurrency, or discovering requirements files recursively. See [Known limitations](limitations.md).
