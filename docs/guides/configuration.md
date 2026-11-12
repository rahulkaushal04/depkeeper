---
title: Configuration
description: Configuration files, discovery, environment variables and precedence
---

# Configuration

depkeeper reads settings from a TOML file. Options that decide *what gets written* to disk
(`--pin`, `--backup`, `--refresh-hashes`, `--verify`, `--dry-run`, `--packages`, `--format`) are
deliberately flags only, so they stay visible in the invocation.

---

## Supported settings

| Key | Type | Default | CLI flag | Effect |
|---|---|---|---|---|
| `check_conflicts` | boolean | `true` | `--check-conflicts/--no-check-conflicts` | Run cross-package conflict resolution. |
| `strict_version_matching` | boolean | `false` | `--strict-version-matching` (`check` also has `--no-strict-version-matching`) | Only a sole `==` specifier counts as a current version. |
| `fail_on` | `"none"` \| `"updates"` \| `"minor"` \| `"major"` | `"none"` | `check --fail-on` | `check` exits `3` when updates at that level exist. |
| `ignore` | list of strings | `[]` | `--ignore PKG` (adds to the list) | Packages that are skipped entirely. |
| `python_version` | string `"X.Y"` | unset | `--python-version` | Python that candidate versions must support. |
| `min_age` | duration (`"7d"`, `"12h"`, `"2w"`; a bare number is days) | unset | `--min-age` | Do not recommend versions released more recently than this. |
| `versioning` | `"auto"` \| `"semver"` \| `"calver"` | `"auto"` | none | How version change types are classified. |
| `packages` | table of per-package tables | none | none | Per-package policy, below. |

Per-package policy lives in `[depkeeper.packages.<name>]` (`[tool.depkeeper.packages.<name>]` in
`pyproject.toml`). Names are normalised (`My_Pkg` and `my-pkg` are the same entry).

| Key | Type | Effect |
|---|---|---|
| `hold` | boolean | Keep the package at its current version (`[HELD]`). |
| `ignore` | boolean | Skip the package (`[IGNORED]`). |
| `max_update` | `"patch"` \| `"minor"` \| `"major"` | Largest update level allowed. A cap only: it never lets a package cross a major. |
| `allow_major` | boolean | Same as `--allow-major <name>`: may cross its current major, still bounded by your own upper bounds. |
| `allow_prerelease` | boolean | Consider pre-releases as candidates. |
| `versioning` | `"auto"` \| `"semver"` \| `"calver"` | Override the global mode for this package. |

Any other key, at either level, is a **hard error**, not a warning, because a silently ignored typo
would leave you believing a setting is in effect:

```text
[ERROR] Unknown configuration keys: check_conflict (config_path=/path/bad.toml)
```

Exit code `1`. A wrong value type is rejected the same way, for example
`check_conflicts must be a boolean, got str`, `fail_on must be one of none, updates, minor, major, got 'x'`
or `python_version must look like '3.9', got '3'`.

---

## File formats

**depkeeper.toml**

```toml
[depkeeper]
check_conflicts = true
strict_version_matching = false
fail_on = "minor"
ignore = ["django"]
python_version = "3.9"
min_age = "7d"

[depkeeper.packages.django]
max_update = "minor"
allow_major = true

[depkeeper.packages.pytz]
versioning = "calver"
hold = true
```

**pyproject.toml**

```toml
[tool.depkeeper]
fail_on = "updates"
min_age = 7

[tool.depkeeper.packages.numpy]
ignore = true
```

Both are equivalent. Use `pyproject.toml` if the project already has one; use `depkeeper.toml` to
keep tool configuration separate. A `[packages.x]` table outside the `depkeeper` table is not read.

---

## Discovery

In order, stopping at the first match:

1. The path given by `--config` / `-c`, or the `DEPKEEPER_CONFIG` environment variable. It must be
   an existing file.
2. `depkeeper.toml` in the current directory, then each parent directory.
3. `pyproject.toml` in the same directories, **only if** it contains a `[tool.depkeeper]` table.
4. Built-in defaults.

The upward search stops at the first directory containing `.git` (the repository root). Without a
`.git`, it never goes above your home directory. So running from a subdirectory of a repository
finds the config at the repository root.

- A `pyproject.toml` without a `[tool.depkeeper]` table is skipped, so a project that merely has one
  does not shadow the defaults.
- A discovered file with an empty depkeeper section is valid and yields the defaults.
- An explicit `--config` file that lacks its table is an error
  (`Configuration file pyproject.toml has no [tool.depkeeper] table`).
- `--config` with a missing path is rejected by the CLI (exit `2`, `File 'missing.toml' does not exist.`).

---

## Precedence

```text
built-in defaults  <  config file  <  command-line flag
```

The settings with a CLI flag in the table above take part. `--ignore` is merged with the config
`ignore` list rather than replacing it. Flags that default to "unset" internally mean "use the
config value" when omitted.

```toml
[depkeeper]
check_conflicts = false
```

```bash
depkeeper check                        # conflicts NOT checked  (file)
depkeeper check --check-conflicts      # conflicts checked      (flag wins)
```

> [!NOTE]
> **`update --strict-version-matching` has no negative form**
>
> `check` accepts `--no-strict-version-matching`; `update` does not. If the config sets it to
> `true`, point `update` at a different file with `--config`, or change the file.

---

## Environment variables

| Variable | Read by | Effect |
|---|---|---|
| `DEPKEEPER_CONFIG` | `--config` | Path to a configuration file. |
| `DEPKEEPER_COLOR` | `--color/--no-color` | Enables or disables colour (`1`/`0`, `true`/`false`, `yes`/`no`). |
| `NO_COLOR` | `rich`, `click`, the logger | Any non-empty value disables colour. depkeeper also **sets or clears this variable itself** when `--color`/`--no-color` is given, so downstream libraries honour the flag. |
| `CI` | the logger | Any non-empty value disables ANSI colour in log records. |
| `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY`, `SSL_CERT_FILE` | `httpx` | Proxy and CA bundle for PyPI requests. |

```bash
export DEPKEEPER_CONFIG=/etc/depkeeper/ci.toml
export NO_COLOR=1
depkeeper check
```

Colour is probed **per stream**: a piped stdout does not disable colour on an interactive stderr,
which keeps `depkeeper check -f json | jq` readable and parseable at the same time.

---

## Verbosity

Verbosity is CLI-only; it cannot be set in a file. `-v` must come before the subcommand
(`depkeeper -v check`).

| Flag | Level | What appears on stderr |
|---|---|---|
| *(none)* | `WARNING` | Warnings and errors only. |
| `-v` | `INFO` | Phase progress, which Python was targeted, the resolution summary, backups. |
| `-vv` | `DEBUG` | Per-package decisions, HTTP retries, per-line rewrites, effective configuration. |

---

## Recommended configurations

**Application repository** (run `depkeeper update --pin --backup`)

```toml
[tool.depkeeper]
check_conflicts = true
python_version = "3.12"
min_age = "7d"          # let new releases settle for a week
```

**Library repository** (never use `--pin`; ranges are part of the contract; the file's
`requires-python` already sets the target Python)

```toml
[tool.depkeeper]
check_conflicts = true
```

**CI gate**

```toml
[depkeeper]
fail_on = "major"        # `check` exits 3 when a major update is proposed
check_conflicts = false  # faster, fewer PyPI requests
```

```bash
depkeeper --config ci/depkeeper.toml check --format json
```

**Lockfile-style file of exact pins**

```toml
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
DEBUG: Logging initialized at DEBUG level
DEBUG: Found depkeeper.toml: /path/to/depkeeper.toml
INFO: Loading configuration from /path/to/depkeeper.toml
DEBUG: Loaded configuration: {'check_conflicts': True, 'strict_version_matching': False, 'fail_on': 'minor', 'ignore': ['django'], 'python_version': '3.9', 'min_age': '7 days, 0:00:00', 'packages': ['django', 'pytz']}
DEBUG: depkeeper v1.0.1
```

`Config path: None` in the later debug lines means no configuration file was discovered and the
built-in defaults are in effect.

---

## Encoding

Configuration files are decoded as `utf-8-sig`, so a byte order mark from a Windows editor is
accepted. A file that is not valid UTF-8 raises
`Configuration file depkeeper.toml is not valid UTF-8: <detail>`; invalid TOML raises
`Invalid TOML in depkeeper.toml: <detail>`.
