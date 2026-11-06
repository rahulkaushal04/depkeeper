---
title: Basic Usage
description: Reading depkeeper output — statuses, columns, update types and the output formats
---

# Basic Usage

This page explains how to read what depkeeper reports. It is the reference for interpreting a
run; the mechanics of each command live in [Checking for updates](../guides/checking-updates.md)
and [Updating dependencies](../guides/updating-dependencies.md).

---

## The two commands

| Command | Reads | Writes | Network | Default file |
|---|---|---|---|---|
| `depkeeper check` | dependency file(s) | nothing | PyPI JSON API | `requirements.txt` |
| `depkeeper update` | dependency file(s) | dependency file(s), optional backups | PyPI JSON API | `requirements.txt` |

Both accept an optional `FILE` argument: a requirements file, `pyproject.toml`, conda `environment.yml`, or a
directory (supported files in it are discovered and reported together). Without one, `requirements.txt` is
used when present. A path that does not exist is rejected by Click with exit code `2`.

```bash
depkeeper check requirements-dev.txt
depkeeper update requirements/prod.txt
```

---

## Version vocabulary

Four version slots appear throughout the output. Confusing them is the single most common source
of misread reports.

| Term | Meaning |
|---|---|
| **Current** | The version depkeeper inferred from your file. For `pkg==1.2.3` it is `1.2.3`. For `pkg>=1.2` it is `1.2` (see [inference](#current-version-inference)). For `pkg` with no specifier it is unknown. |
| **Latest** | `info.version` from PyPI. **Informational only.** depkeeper never applies it merely because it is newest. |
| **Recommended** | The version depkeeper would write. It is the output of the recommendation algorithm *and* of conflict resolution. This is the authoritative value. |
| **Update type** | The classification of `current → recommended`: `major`, `minor`, `patch`, `new`, `same`, `downgrade`, `update`, `unknown`; calver packages use `year`, `month`, `patch`. |

The invariant after a run with conflict checking enabled is that the recommended version shown in
the report is exactly the version `update` writes. See
[Conflict resolution → Result invariant](../concepts/conflict-resolution.md#result-invariant).

### Current-version inference

depkeeper reads a *range* as a statement about where you are today:

| Requirement | Inferred current | Rule |
|---|---|---|
| `requests==2.28.0` | `2.28.0` | A non-wildcard `==` / `===` is an exact pin, even next to `!=`. |
| `flask>=2.0,<2.3` | `2.0` | Otherwise the first `>=`, `>` or `~=` specifier wins. |
| `click~=8.0` | `8.0` | Same rule; `~=` counts as a floor. |
| `django<5.0` | *(none)* | No floor operator, so nothing is inferred. |
| `certifi` | *(none)* | No specifiers at all. |

This matters because the inferred current version establishes the **major boundary**.
`django>=3.2,<5.0` anchors to major `3`, so depkeeper caps it at the newest `3.x` even though
`4.x` satisfies the declared range. `--allow-major django` lifts depkeeper's own boundary; your
`<5.0` still applies.

Pass `--strict-version-matching` to disable inference: only an exact `==` pin counts as a current
version. Everything else is then treated as "not installed", which changes both the status and
the boundary. See [Strict version matching](../guides/checking-updates.md#strict-version-matching).

---

## Statuses

### Table format statuses

| Badge | Meaning | Written by `update`? |
|---|---|---|
| `[OK]` | No update available *or* no current version to compare against. | Only in the second case (a pin is added). |
| `[OUTDATED]` | A safe upgrade exists. | Yes. |
| `[CONFLICT]` | Conflicts blocked every candidate; no upgrade is possible. | No. |
| `[INCOMP]` | A **downgrade** is required: the declared version is unusable (Python-incompatible, or forced down by another package). | Yes — this rewrites the floor *downwards*. |
| `[ERROR]` | PyPI metadata could not be retrieved (`check` then exits `4`). | No. |
| `[HELD]` / `[IGNORED]` | A per-package `hold` / `ignore` policy froze it. | No. |

`[INCOMP]` deliberately outranks `[CONFLICT]`: a required downgrade means the version you
declared cannot be used at all, which you must see first.

### JSON / simple statuses

The machine formats use a different, finer-grained ladder:

| Status | Condition |
|---|---|
| `no-update` | No recommended version — metadata unavailable. Accompanied by an `error` field (with or without conflict checking). |
| `install` | No current version, but a recommendation exists (a pin will be added). |
| `downgrade` | Recommended is lower than current. |
| `outdated` | Recommended is higher than current. |
| `latest` | Recommended equals current. |

> [!WARNING]
> **The two ladders disagree for unversioned requirements**
>
> `certifi` with no specifier renders as `[OK]` in the table but as `install` in JSON and
> simple output. The table's up-to-date branch is also its fallback branch. Treat the machine
> formats as authoritative. Tracked in [Known limitations](../reference/limitations.md#unversioned-requirements-report-as-ok).

---

## The table format

`--format table` (the default) renders a Rich table with these columns (plus `Source` when several files are reported):

| Column | Content |
|---|---|
| `Status` | The badge from the table above. |
| `Package` | PEP 503 canonical name (lower-cased, `_` and `.` folded to `-`). |
| `Current` | Inferred current version, or `-`. |
| `Latest` | PyPI `info.version`, or `error`. |
| `Recommended` | Shown **only when it differs from current**; otherwise `-`. Under it: the release age (`175d old`) and, with `min_age`, any newer version the cooldown withheld. |
| `Update Type` | `major` / `minor` / `patch` / `year` / `month` / `downgrade` / `blocked` / `-`. |
| `Conflicts` | One line per conflict: `⚠ <source> needs <specifier>`. |
| `Python Support` | One `requires_python` value: the recommended release's (or the current one's when no update), else latest's, with `!=` exclusions hidden. |

A blank `Recommended` cell means "same as current" — it is suppressed to reduce noise, not
because no recommendation exists.

The **Resolution Summary** (totals, convergence, per-package version changes) is printed before the table only when conflict
checking changed something or found a conflict, or with `-v`. A `major available: PKG X (use --allow-major PKG)` warning follows
the table when a higher major exists but was not taken.

---

## The simple format

`--format simple` emits one status line per package plus indented detail lines. Rich markup is
disabled for these lines, because a label such as `[OUTDATED]` would otherwise be interpreted as
a style tag and swallowed.

```text
[OUTDATED]   requests             2.28.0     → 2.34.2
       released 175 days ago
       Python: installed: >=3.7, <4, latest: >=3.10, recommended: >=3.10
[OUTDATED]   flask                2.0        → 3.1.3      (recommended: 2.2.5)
       released 1283 days ago
       Python: latest: >=3.9, recommended: >=3.7
[INSTALL]    certifi              none       → 2026.10.23
       Python: latest: >=3.7
```

The arrow points at **latest**, not at the recommendation. When the two differ — because a major
boundary, a declared cap or a conflict capped the upgrade — the recommendation is appended in
parentheses. Conflicts appear as additional indented `⚠ Conflict:` lines; held/ignored packages show `[HELD]` / `[IGNORED]`.

---

## The JSON format

`--format json-v2` prints a versioned envelope and `--format markdown` a PR-body report; both follow the stream rules below.
`--format json` prints a JSON array to stdout and nothing else. An empty result set still emits
`[]`, so a consumer such as `jq` never receives empty input.

```json
[
  {
    "name": "flask",
    "status": "outdated",
    "versions": {
      "current": "2.0",
      "latest": "3.1.3",
      "recommended": "2.2.5"
    },
    "update_type": "minor",
    "python_requirements": {
      "latest": ">=3.9",
      "recommended": ">=3.7"
    }
  }
]
```

Only `name` and `status` are guaranteed present. Every other key is omitted when empty. The full
schema, including the `conflicts` and `error` members, is in
[JSON output](../reference/json-output.md).

---

## Output streams

This distinction matters for any scripted use:

| Format | stdout | stderr |
|---|---|---|
| `table` | report **and** status messages | log records |
| `simple` | package lines only | status messages, warnings, errors, log records |
| `json`, `json-v2`, `markdown` | the payload only | status messages, warnings, errors, resolution summary, log records |

Consequently this is safe, even with verbose logging:

```bash
depkeeper -vv check --format json | jq .
```

and this discards the diagnostics:

```bash
depkeeper check --format json 2>/dev/null | jq .
```

Errors always go to stderr regardless of format.

---

## Common first-run surprises

| Observation | Explanation |
|---|---|
| "It won't upgrade past 1.x." | Major boundary. This is the core safety rule, not a bug. [Details](../concepts/version-recommendation.md#the-major-version-boundary). |
| "Latest is 3.1.3 but it recommends 2.2.5." | Your own `<2.3` cap, or a conflict, or the major boundary. Check the `Conflicts` column and your declared range. |
| "`update` changed a package `check` showed as OK." | Unversioned requirements report `OK` but receive a pin. See above. |
| "I want the next major." | Opt in per package: `--allow-major PKG` (repeatable, `*` for all) or `allow_major = true` in `[depkeeper.packages.PKG]`. |
| "It proposed a *downgrade*." | Either the declared version is Python-incompatible on your interpreter, or another package in the file requires an older release. [Details](../concepts/conflict-resolution.md#downgrades). |
| "Nothing happened, exit code 0." | `check` exits `0` unless you pass `--fail-on updates\|minor\|major` (exit `3`); exit `4` means a lookup failed. [Exit codes](../reference/exit-codes.md). |
