---
title: Quick Start
description: Run a check, read the plan, and apply a safe update in five commands
---

# Quick Start

This page walks through one complete cycle against a realistic requirements file. Every output
block on this page is real command output, not an illustration.

## 0. The sample project

```text title="requirements.txt"
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

```text
Resolution Summary:
==================================================
Total packages: 6
Packages with conflicts: 0
Packages changed: 0
Converged: Yes (1 iterations)

                       Dependency Status
┏━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃   Status   ┃ Package  ┃ Current ┃  Latest   ┃ Recommended ┃ Update Type ┃ Conflicts ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ ⬆ OUTDATED │ requests │ 2.28.0  │  2.34.2   │   2.34.2    │    minor    │ -         │
│ ⬆ OUTDATED │ flask    │   2.0   │   3.1.3   │    2.2.5    │    minor    │ -         │
│ ⬆ OUTDATED │ celery   │   5.0   │   5.6.3   │    5.6.3    │    minor    │ -         │
│ ⬆ OUTDATED │ click    │   8.0   │   8.4.2   │    8.4.2    │    minor    │ -         │
│    ✓ OK    │ certifi  │    -    │ 2026.7.22 │      -      │      -      │ -         │
│ ⬆ OUTDATED │ urllib3  │ 1.26.0  │   2.7.0   │   1.26.20   │    patch    │ -         │
└────────────┴──────────┴─────────┴───────────┴─────────────┴─────────────┴───────────┘
[WARNING]
5 package(s) have updates available
```

!!! note "The real table has a `Python Support` column"

    It is omitted here for width. The full column set is documented in
    [Reading the output](basic-usage.md#the-table-format).

Three results are worth understanding immediately:

- **`flask`: latest `3.1.3`, recommended `2.2.5`.** Your file says `<2.3`. depkeeper will not
  propose a version your own constraint forbids.
- **`urllib3`: latest `2.7.0`, recommended `1.26.20`.** `2.x` is a major boundary crossing and is
  never proposed automatically.
- **`certifi`: shown as `✓ OK`.** It has no version specifier, so there is nothing to compare
  against. `update` will still add a pin for it — see the
  [known inconsistency](../reference/limitations.md#unversioned-requirements-report-as-ok).

`check` always exits `0` when it completed successfully, whether or not updates exist. See
[Exit codes](../reference/exit-codes.md).

---

## 2. Preview the write

```bash
depkeeper update --dry-run
```

```text
                       Update Plan (Dry Run)
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
┃ Package  ┃    Current    ┃ New Version ┃ Change ┃ Python Requires ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
│ requests │    2.28.0     │   2.34.2    │ minor  │ >=3.10          │
│ flask    │      2.0      │    2.2.5    │ minor  │ >=3.7           │
│ celery   │      5.0      │    5.6.3    │ minor  │ >=3.9           │
│ click    │      8.0      │    8.4.2    │ minor  │ >=3.10          │
│ certifi  │ not specified │  2026.7.22  │  new   │ >=3.7           │
│ urllib3  │    1.26.0     │   1.26.20   │ patch  │ !=3.0.*,...     │
└──────────┴───────────────┴─────────────┴────────┴─────────────────┘
[WARNING]
Dry run mode - no changes applied
```

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
`update` explicitly. Press `n` to abort; nothing is written and the command exits `0`.

Result:

```text title="requirements.txt (after)"
requests==2.34.2
flask>=2.2.5,<2.3
celery[redis]>=5.6.3,<6.0
click~=8.4
certifi==2026.7.22
urllib3==1.26.20
```

`--backup` wrote a sibling copy named
`requirements.20260815_144129_853745_d54d785d.backup.txt` before touching the original.

---

## 4. Verify with pip

depkeeper only edits text. Install the result to confirm the environment resolves:

```bash
python -m pip install -r requirements.txt
python -m pytest        # or your project's test command
```

!!! warning "depkeeper is not a resolver substitute"

    depkeeper checks the packages *listed in your file* against each other. It does not build a
    complete transitive dependency graph, and it cannot see a conflict introduced by a package
    that is not in the file. `pip install` remains the authority. See
    [Conflict resolution → What is not checked](../concepts/conflict-resolution.md#what-is-not-checked).

---

## 5. Re-run (idempotency)

```bash
depkeeper update -y
```

```text
[OK] All packages are up to date!
```

Rewrites converge. A target already covered by the declared floor is skipped, so
`click~=8.4` does not re-report `8.4.2` on every run. This property is what makes depkeeper safe
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
