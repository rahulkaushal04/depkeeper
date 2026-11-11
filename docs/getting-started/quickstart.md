---
title: Quick Start
description: Run a check, read the plan, and apply a safe update in five commands
---

# Quick Start

This page walks through one complete cycle against a realistic requirements file. Every output
block on this page is real command output, not an illustration.

## 0. The sample project

```text
requests==2.28.0
flask>=2.0,<2.3
celery[redis]>=5.0,<6.0
click~=8.0
certifi
urllib3==1.26.0
```

This deliberately mixes the five requirement shapes depkeeper treats differently: an exact pin, a
bounded range, an extras + range, a compatible-release band, and an unversioned requirement.

---

## 1. Check (read-only)

```bash
depkeeper check
```

Real output (trimmed to the first columns; the live table also has a `Python Support` column and
an `N d old` age line under each recommendation):

```text
┏━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃   Status   ┃ Package  ┃ Current ┃   Latest   ┃ Recommended ┃ Update Type ┃ Conflicts ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ [OUTDATED] │ requests │ 2.28.0  │   2.34.2   │   2.34.2    │    minor    │ -         │
│ [OUTDATED] │ flask    │   2.0   │   3.1.3    │    2.2.5    │    minor    │ -         │
│ [OUTDATED] │ celery   │   5.0   │   5.7.0    │    5.7.0    │    minor    │ -         │
│ [OUTDATED] │ click    │   8.0   │   8.5.0    │    8.5.0    │    minor    │ -         │
│    [OK]    │ certifi  │    -    │ 2026.10.23 │      -      │      -      │ -         │
│ [OUTDATED] │ urllib3  │ 1.26.0  │   2.8.0    │   1.26.20   │    patch    │ -         │
└────────────┴──────────┴─────────┴────────────┴─────────────┴─────────────┴───────────┘
[WARNING] major available: urllib3 2.8.0 (use --allow-major urllib3)
[WARNING]
5 package(s) have updates available
```

(Versions change as PyPI does; the shape does not.) The `Resolution Summary` block is printed only
when conflict resolution changed something, found a conflict, or with `-v`.

Three results are worth understanding immediately:

- **`flask`: latest `3.1.3`, recommended `2.2.5`.** Your file says `<2.3`. depkeeper will not
  propose a version your own constraint forbids.
- **`urllib3`: latest `2.8.0`, recommended `1.26.20`.** `2.x` crosses a major boundary, so it is
  not proposed unless you opt in; the `major available` hint names the flag.
- **`certifi`: shown as `[OK]`.** It has no version specifier, so there is nothing to compare
  against. `update` will still add a pin for it — see the
  [known inconsistency](../reference/limitations.md#unversioned-requirements-report-as-ok).

`check` exits `0` when it completed, whether or not updates exist, unless you ask otherwise:
`--fail-on updates|minor|major` exits `3` when updates at that level exist, and exit `4` means a
package could not be looked up. See [Exit codes](../reference/exit-codes.md).

---

## 2. Preview the write

```bash
depkeeper update --dry-run
```

```text
[WARNING] major available: urllib3 2.8.0 (use --allow-major urllib3)
                             Update Plan (Dry Run)
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Package  ┃    Current    ┃ New Version ┃ Change ┃ Python Requires            ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ requests │    2.28.0     │   2.34.2    │ minor  │ >=3.10                     │
│ flask    │      2.0      │    2.2.5    │ minor  │ >=3.7                      │
│ celery   │      5.0      │    5.7.0    │ minor  │ >=3.10                     │
│ click    │      8.0      │    8.5.0    │ minor  │ >=3.10                     │
│ certifi  │ not specified │ 2026.10.23  │  new   │ >=3.7                      │
│ urllib3  │    1.26.0     │   1.26.20   │ patch  │ !=3.0.*,!=3.1.*,...        │
└──────────┴───────────────┴─────────────┴────────┴────────────────────────────┘
[WARNING]
Dry run mode - no changes applied
```

(Each `New Version` cell also carries an `N d old` age line; omitted here.)

`--dry-run` performs the entire pipeline — parse, fetch, recommend, resolve, render — and stops
immediately before the first byte is written. It is the authoritative preview: the plan shown is
produced by the same code path that writes the file.

---

## 3. Apply

```bash
depkeeper update --backup
```

You are prompted before anything is written:

```text
Update 6 packages? (y, n) [y]:
```

The prompt defaults to **yes**, because the plan table has already been displayed and you invoked
`update` explicitly. Answering `n` writes nothing, prints `Aborted. No changes were made.` and
exits `1`. Without a terminal and without `--yes` the command errors instead of guessing
(`Cannot ask for confirmation without a terminal`).

Result:

```text
requests==2.34.2
flask>=2.2.5,<2.3
celery[redis]>=5.7.0,<6.0
click~=8.5
certifi==2026.10.23
urllib3==1.26.20
```

`--backup` wrote a sibling copy named
`requirements.txt.20261106_191359_861179_35e36bf1.backup` before touching the original
(`[OK] Backup saved: <path>`).

---

## 4. Verify with pip

depkeeper only edits text. Ask pip's resolver before writing with `depkeeper update --verify` (a conflict aborts with
nothing written; skipped with a warning when pip is unavailable), or install the result to confirm it resolves:

```bash
python -m pip install -r requirements.txt
python -m pytest        # or your project's test command
```

> [!WARNING]
> **depkeeper is not a resolver substitute**
>
> depkeeper checks the packages *listed in your file* against each other. It does not build a
> complete transitive dependency graph, and it cannot see a conflict introduced by a package
> that is not in the file. `pip install` remains the authority. See
> [Conflict resolution → What is not checked](../concepts/conflict-resolution.md#what-is-not-checked).

---

## 5. Re-run (idempotency)

```bash
depkeeper update -y
```

```text
[WARNING] major available: urllib3 2.8.0 (use --allow-major urllib3)
[OK] All packages are up to date!
```

Rewrites converge. A target already covered by the declared floor is skipped, so
`click~=8.5` does not re-report `8.5.0` on every run. This property is what makes depkeeper safe
to run on a schedule — see [CI/CD integration](../guides/ci-cd-integration.md).

---

## Machine-readable output

For automation, use `--format json`. The payload owns stdout; every status message, warning and
error is diverted to stderr, so the stream stays parseable even with `-v`:

```bash
depkeeper -v check --format json | jq '[.[] | select(.status == "outdated")] | length'
```

```text
5
```

(`json` is the stable bare array; `--format json-v2` wraps it in a versioned envelope, and
`--format markdown` renders a PR-body report.)

The schema is documented in [JSON output](../reference/json-output.md).

---

## Next steps

| Goal | Page |
|---|---|
| Understand every column and status | [Basic usage](basic-usage.md) |
| Understand *why* a version was chosen | [Version recommendation](../concepts/version-recommendation.md) |
| Persist options across runs | [Configuration](../guides/configuration.md) |
| Run this in a pipeline | [CI/CD integration](../guides/ci-cd-integration.md) |
| Something went wrong | [Troubleshooting](../guides/troubleshooting.md) |
