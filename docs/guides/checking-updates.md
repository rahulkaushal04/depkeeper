---
title: Checking for Updates
description: Using depkeeper check — filters, formats, streams, conflict analysis and automation
---

# Checking for Updates

`depkeeper check` is read-only. It parses a requirements file, queries PyPI, computes
recommendations, optionally resolves conflicts, and reports. It never modifies a file and never
installs anything.

```bash
depkeeper check [OPTIONS] [FILE]
```

`FILE` defaults to `requirements.txt` and must exist. See
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

!!! note "Exit code is not a signal"

    `check` exits `0` whenever it completed successfully, regardless of what it found. To gate a
    build on the result, parse the JSON payload. See
    [Exit codes](../reference/exit-codes.md#gating-on-results).

---

## Output formats

### `--format table` (default)

Full report for humans: eight columns plus the Resolution Summary. Column meanings are documented
in [Basic usage → The table format](../getting-started/basic-usage.md#the-table-format).

Status messages share stdout with the table in this format only.

### `--format simple`

One line per package plus indented detail lines. Suited to grep-based checks and log output.

```bash
depkeeper check --format simple | grep '^\[OUTDATED\]'
```

The arrow points at the **latest** version; when the recommendation differs it is appended in
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

---

## Output streams

| Format | stdout | stderr |
|---|---|---|
| `table` | report and status messages | log records |
| `simple` | package lines only | status messages, warnings, errors, log records |
| `json` | the JSON document only | status messages, warnings, errors, log records |

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

With resolution enabled and the `table` format (or any format with `-v`), a summary precedes the
report:

```text
Resolution Summary:
==================================================
Total packages: 2
Packages with conflicts: 1
Packages changed: 1
Converged: Yes (2 iterations)

Version changes:
  • flask: 2.3.3 → 2.2.5 (constrained)
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

Use strict mode when your file is a lockfile of exact pins and you want ranges ignored entirely.
Be aware that for **unbounded** ranges it removes the major-boundary protection.

---

## Working with multiple files

```bash
depkeeper check requirements/base.txt
depkeeper check requirements/dev.txt
depkeeper check requirements/prod.txt
```

There is no `--recursive` or directory mode. `-r` includes are followed automatically, so checking
a file that includes others reports the union of them in one table.

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
| `[ERROR]`, `Latest: error` | PyPI metadata unavailable — package does not exist, is private-index-only, or the network failed. | Verify the name; check connectivity; see [Troubleshooting](troubleshooting.md#pypi-errors). |
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
| Repeated runs | No persistent cache exists. Each invocation refetches everything. |

Typical timings are dominated by network latency, not by depkeeper. See
[Operations → Performance](operations.md#performance).

---

## Diagnostics

```bash
depkeeper -v check     # INFO: per-phase progress, resolution decisions
depkeeper -vv check    # DEBUG: per-package decisions, cache behaviour, HTTP retries
```

Log records always go to stderr, so verbosity never corrupts a piped payload.

```bash
depkeeper -vv check --format json > report.json 2> debug.log
```
