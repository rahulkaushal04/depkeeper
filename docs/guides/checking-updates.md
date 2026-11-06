---
title: Checking for Updates
description: Using depkeeper check — filters, formats, gating, streams, conflict analysis and automation
---

# Checking for Updates

`depkeeper check` is read-only. It parses a requirements file, queries PyPI, computes
recommendations, optionally resolves conflicts, and reports. It never modifies a file and never
installs anything.

```bash
depkeeper check [OPTIONS] [FILE]
```

`FILE` is a requirements file, a `pyproject.toml`, a conda `environment.yml`, or a directory (every
supported file in it is checked). Without it, `requirements.txt` is used when present, otherwise
the supported files in the current directory. See
[CLI reference](../reference/cli-commands.md#check) for the exhaustive option list.

---

## Basic use

```bash
depkeeper check                        # requirements.txt
depkeeper check requirements-dev.txt   # a specific file
depkeeper check requirements/base.txt  # follows -r includes into other files
depkeeper check --outdated-only        # suppress up-to-date rows
```

`--outdated-only` keeps packages that have an update **or** a recorded conflict. When everything
is current it prints `[OK] All packages are up to date!`.

> [!NOTE]
> **Exit codes**
>
> `check` exits `0` when it completed, even if updates exist. Use `--fail-on` to turn updates into
> exit `3`: `updates` (any update, conflict or downgrade), `minor` (minor or major) or `major`
> (major only); the default is `none`. Exit `4` means at least one package could not be looked up
> on PyPI and wins over `3`. Both can be set once as `fail_on` in the config file. See
> [Exit codes](../reference/exit-codes.md#gating-on-results).

```bash
depkeeper check --fail-on major --format json > report.json   # exit 3 if a major update is proposed
```

---

## Output formats

### `--format table` (default)

Full report for humans: eight columns (Status, Package, Current, Latest, Recommended, Update
Type, Conflicts, Python Support), plus a Source column when several files are read. The release
age appears under the recommended version. The Resolution Summary is printed when something
changed or conflicted, or with `-v`. Column meanings are documented
in [Basic usage → The table format](../getting-started/basic-usage.md#the-table-format).

Status messages share stdout with the table in this format only.

### `--format simple`

One line per package plus indented detail lines. Suited to grep-based checks and log output.

```bash
depkeeper check --format simple | grep '^\[OUTDATED\]'
```

Each package also shows its release age, its Python requirements and, for several files, a
`Source:` line. The arrow points at the **latest** version; when the recommendation differs it is appended in
parentheses. Do not parse the arrow target as the version depkeeper would apply.

### `--format json`

The format for automation. A JSON array on stdout, always a valid document, even when empty
(`[]`). Full schema: [JSON output](../reference/json-output.md).

```bash
# How many packages are behind?
depkeeper check --format json | jq '[.[] | select(.status == "outdated")] | length'

# Which packages have conflicts?
depkeeper check --format json | jq -r '.[] | select(.conflicts) | .name'

# Which packages could not be reached?
depkeeper check --format json --no-check-conflicts \
  | jq -r '.[] | select(.error) | .name'

# Flat CSV for a spreadsheet
depkeeper check --format json \
  | jq -r '.[] | [.name, .versions.current // "", .versions.recommended // "", .status] | @csv'
```

### `--format json-v2` and `--format markdown`

`json-v2` is a versioned envelope (`schema_version`, `summary`, `python`, `files`, `packages`,
`errors`) for tools that want totals and the file and line of each package:

```bash
depkeeper check --format json-v2 | jq '.summary'
```

`markdown` is a ready-made PR body or CI summary: tables grouped by update type with release age
and changelog links, then held, cooldown, conflict and lookup-failure lists.

```bash
depkeeper check --format markdown >> "$GITHUB_STEP_SUMMARY"
```

The bare-array `json` format is kept stable; prefer `json-v2` for new tooling.

---

## Output streams

| Format | stdout | stderr |
|---|---|---|
| `table` | report and status messages | log records |
| `simple` | package lines only | status messages, warnings, errors, log records |
| `json`, `json-v2`, `markdown` | the document only | status messages, warnings, errors, log records |

This holds with verbosity enabled, which is the point of the design:

```bash
depkeeper -vv check --format json | jq .        # payload is still valid
depkeeper check --format json 2>/dev/null | jq . # discard diagnostics
depkeeper check --format json 2> check.log | jq . # keep them for later
```

---

## Conflict analysis

Enabled by default. It cross-validates the proposed versions against each package's
`requires_dist` and adjusts them until the set is self-consistent. The mechanics are documented in
[Conflict resolution](../concepts/conflict-resolution.md).

```bash
depkeeper check                        # with resolution (default)
depkeeper check --no-check-conflicts   # skip it — faster, fewer requests
```

With resolution enabled, a summary precedes the report when the resolver changed something or
found a conflict, or always with `-v` (on stderr for the non-table formats). For
`flask>=2.3,<3.0` plus `werkzeug>=2.0,<2.3`:

```text
Resolution Summary:
==================================================
Total packages: 2
Packages with conflicts: 1
Packages changed: 2
Converged: No (stopped after 2 iterations)

Version changes:
  • flask: 2.3.3 → 2.3 (kept_current)
  • werkzeug: 2.2.3 → 2.0 (kept_current)
```

| Line | Interpretation |
|---|---|
| `Packages with conflicts` | Packages with **any** conflict recorded during the run, including ones later resolved. It is an audit count, not a live-problem count. |
| `Packages changed` | Packages whose final version differs from the checker's initial proposal. |
| `Converged: Yes (N iterations)` | The update set became conflict-free after N passes. |
| `Converged: No (stopped after N)` | Resolution stalled or hit the 100-pass limit. The current set is reported as-is; review it manually. |

Disabling resolution changes what is reported: recommendations are then per-package only, and
`update` would apply versions that may conflict with each other.

---

## Strict version matching

```bash
depkeeper check --strict-version-matching
```

Only a sole `==` specifier counts as a current version. Ranges are treated as "no current
version", which changes two things at once:

- there is no major-version anchor, so candidates are drawn from **all** majors;
- the status becomes `install` rather than `outdated`.

```text
# flask>=2.0,<2.3   — default mode
[OUTDATED]   flask                2.0        → 3.1.3      (recommended: 2.2.5)

# flask>=2.0,<2.3   — with --strict-version-matching
[INSTALL]    flask                none       → 3.1.3      (recommended: 2.2.5)
```

Here the declared `<2.3` cap still holds, so the recommendation is unchanged. It would differ for
a requirement such as `django>=3.2` with no cap: default mode anchors to major `3`, strict mode
allows any major.

`check` also accepts `--no-strict-version-matching` to override `strict_version_matching = true` in
the config. Use strict mode when your file is a lockfile of exact pins and you want ranges ignored entirely.
Be aware that for **unbounded** ranges it removes the major-boundary protection.

---

## Major upgrades are opt-in

By default depkeeper never recommends a version in a higher major than the current one. A newer
major that your declared range allows is reported instead:

```text
[WARNING] major available: urllib3 2.8.0 (use --allow-major urllib3)
```

`--allow-major PKG` (repeatable; `'*'` for every package, or `allow_major = true` in the package's
policy) lets that package cross its major, still bounded by your own upper bounds. With
`django>=3.2,<5.0` it moves to the newest `4.x`, never `5.x`. A name that is not in the file warns.

```bash
depkeeper check --allow-major django
```

## Release age, cooldown and target Python

- `--min-age 7d` (also `12h`, `2w`; a bare number is days; config `min_age`) withholds versions
  released more recently; the withheld version is reported as held back by the cooldown.
- `--python-version X.Y` sets the Python that candidates must support. Without it: config
  `python_version`, then the file's own `requires-python` or conda `python` pin (the lowest
  supported minor), then the interpreter running depkeeper. `-v` logs which rule decided.

---

## Working with multiple files

```bash
depkeeper check requirements/base.txt
depkeeper check requirements/dev.txt
depkeeper check requirements/prod.txt
```

`-r` includes are followed automatically, so checking a file that includes others reports the
union of them in one table. Passing a directory checks every supported file in it
(`requirements*.txt`, `pyproject.toml`, `environment.yml`/`.yaml`) and adds a Source column.
There is no recursive mode.

```bash
# Check every requirements file in a project
for f in requirements*.txt requirements/*.txt; do
  echo "== $f"
  depkeeper check "$f" --format simple
done
```

---

## Interpreting difficult rows

| Row | Meaning | Action |
|---|---|---|
| `[ERROR]`, `Latest: error` (`[NO-UPDATE]` in `simple`, `"status": "no-update"` with an `error` field in JSON) | PyPI metadata unavailable — package does not exist, is private-index-only, or the network failed. `check` also exits `4`, even with `--outdated-only`. | Verify the name; check connectivity; see [Troubleshooting](troubleshooting.md#pypi-errors). |
| `[HELD]`, `[IGNORED]` | A per-package `hold` or `ignore` policy froze the package. | Edit `[depkeeper.packages.<name>]` if unintended. |
| `[CONFLICT]`, `Update Type: blocked` | Conflicts eliminated every candidate version. | Read the `Conflicts` column and relax the offending constraint yourself. |
| `[INCOMP]`, `Update Type: downgrade` | The declared version is unusable and a lower version is proposed. | Investigate before applying — this rewrites your floor downwards. |
| `[OK]` with an empty `Current` | The requirement has no version specifier. | `update` will add a pin. See [Limitations](../reference/limitations.md#unversioned-requirements-report-as-ok). |
| Recommendation far below `Latest` | Major boundary, a declared cap, a Python requirement, or a conflict. | Compare `Latest` with your declared range and the `Conflicts` column. |

---

## Performance

| Lever | Effect |
|---|---|
| `--no-check-conflicts` | Removes the entire resolution phase — usually the dominant cost. |
| Smaller files | One HTTP request per unique package; `-r` includes count toward the total. |
| Repeated runs | There is no persistent cache. Each invocation refetches everything. |

Typical timings are dominated by network latency, not by depkeeper. See
[Operations → Performance](operations.md#performance).

---

## Diagnostics

```bash
depkeeper -v check     # INFO: per-phase progress, resolution decisions
depkeeper -vv check    # DEBUG: per-package decisions, HTTP retries
```

Log records always go to stderr, so verbosity never corrupts a piped payload.

```bash
depkeeper -vv check --format json > report.json 2> debug.log
```
