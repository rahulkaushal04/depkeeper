---
title: Updating Dependencies
description: Applying updates safely — previews, selection, pin mode, hashes, backups and recovery
---

# Updating Dependencies

`depkeeper update` applies the recommendations that `check` reports. It runs the same pipeline,
then filters, previews, confirms and writes.

```bash
depkeeper update [OPTIONS] [FILE]
```

Full option list: [CLI reference](../reference/cli-commands.md#update). Write mechanics:
[Write safety](../concepts/write-safety.md).

---

## The safe sequence

```bash
depkeeper update --dry-run     # 1. preview — writes nothing
depkeeper update --backup      # 2. apply, keeping a timestamped copy
pip install -r requirements.txt # 3. verify the environment resolves
pytest                          # 4. verify the code still works
git diff requirements.txt       # 5. review before committing
```

Steps 3 and 4 are not optional. depkeeper validates the packages you declared against each other;
it does not build the full transitive graph. `pip` is the authority on whether the set installs.

---

## Preview first

```bash
depkeeper update --dry-run
```

```text
                       Update Plan (Dry Run)
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
┃ Package  ┃    Current    ┃ New Version ┃ Change ┃ Python Requires ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
│ requests │    2.28.0     │   2.34.2    │ minor  │ >=3.10          │
│ certifi  │ not specified │  2026.7.22  │  new   │ >=3.7           │
│ urllib3  │    1.26.0     │   1.26.20   │ patch  │ !=3.0.*,...     │
└──────────┴───────────────┴─────────────┴────────┴─────────────────┘
[WARNING]
Dry run mode - no changes applied
```

`--dry-run` executes everything except the write, so the plan is produced by the same code that
would have written the file. `Current: not specified` marks a requirement that had no version
specifier and will receive a pin.

!!! warning "`Python Requires` can be stale after conflict resolution"

    The column shows the `requires_python` recorded for the recommendation that the **checker**
    produced. If the resolver subsequently moved the package to a different version, this column
    is not refreshed. Verify with `pip install` rather than relying on it. Tracked in
    [Known limitations](../reference/limitations.md#python-requires-can-be-stale-after-resolution).

---

## Confirmation

Unless `-y` is passed, you are prompted:

```text
Update 3 packages? (y, n) [y]:
```

- The default is **yes** — the plan has already been shown and you invoked `update` explicitly.
- Any input other than `y`/`n` causes Click to re-prompt.
- Declining writes nothing and exits `0`.
- `Ctrl+C` at the prompt exits `130`.

Use `-y` in automation; keep the prompt interactively.

---

## Selecting packages

```bash
depkeeper update -p flask
depkeeper update -p flask -p click -p requests
depkeeper update --packages Django            # matched canonically
```

Names are compared in PEP 503 canonical form, so `my_pkg`, `My.Pkg` and `my-pkg` all select the
same distribution. If no requirement matches, depkeeper prints
`[WARNING] No matching packages found: <names>` and exits `0` without writing.

Selection filters the package list **after** conflict resolution, so the versions applied are
still the mutually consistent ones. It does not re-resolve for the subset.

---

## Range preservation (default)

Only the floor of a requirement moves. Everything else you declared is preserved:

```text title="before"
requests==2.28.0
flask>=2.0,<2.3
celery[redis]>=5.0,<6.0
click~=8.0
certifi
urllib3==1.26.0
```

```text title="after: depkeeper update -y"
requests==2.34.2
flask>=2.2.5,<2.3
celery[redis]>=5.6.3,<6.0
click~=8.4
certifi==2026.7.22
urllib3==1.26.20
```

The rules are in [Version recommendation → Constraint preservation](../concepts/version-recommendation.md#constraint-preservation).
Two behaviours worth internalising:

- `>` is widened to `>=` so the selected version is itself installable.
- A cap-only requirement gains a floor: `<3.0` with target `2.32.3` becomes `<3.0,>=2.32.3`. The
  order is not normalised.

### Skipped targets

If the resolver proposes a version your own constraints exclude, the package is skipped with an
explanation rather than written as an unsatisfiable line:

```text
[WARNING] Skipping flask: 2.3.3 is excluded by the declared constraint '<2.3'
(use --pin to replace the constraint)
```

---

## Pin mode

```bash
depkeeper update --pin
```

Replaces the entire specifier set with an exact pin:

```text title="after: depkeeper update --pin -y"
requests==2.34.2
flask==2.2.5
celery[redis]==5.6.3
click==8.4.2
certifi==2026.7.22
urllib3==1.26.20
```

Extras, markers, hashes-policy and comments are unaffected; only version semantics change.

| Use `--pin` when | Avoid `--pin` when |
|---|---|
| The file describes a deployable application. | The file describes a library's dependencies. |
| You want reproducible installs from this file alone. | You rely on caps and exclusions as documentation of real incompatibilities. |
| The file is generated and regenerated wholesale. | The file is hand-maintained and reviewed. |

`--pin` also disables the declared-constraint check, because no declared constraint survives.

---

## Hashed requirements

Requirements carrying `--hash` entries are **refused by default**:

```text
[ERROR] Refusing to update requirement(s) with --hash entries: requests. Hashes are
version-specific and cannot be silently removed. Re-run with --allow-hash-removal to
proceed without hashes.
```

Exit code `1`. Nothing is written.

```bash
depkeeper update --allow-hash-removal
```

```text
[WARNING] Proceeding with --allow-hash-removal: hashes will be removed for requests
```

!!! danger "The result is a partially hashed file"

    Only the lines that changed lose their digests. `pip install --require-hashes` rejects a file
    in which *some* requirements have hashes and others do not, so the resulting file will not
    install in hash-checking mode.

    The supported workflow for hash-pinned files is:

    ```bash
    depkeeper update --allow-hash-removal -y
    pip-compile --generate-hashes requirements.in   # or: hashin <pkg>
    ```

Also note that `pip-compile --generate-hashes` output uses backslash line continuations by
default, which depkeeper's parser does not join. See
[Requirements parsing → Known gaps](../concepts/requirements-parsing.md#known-parsing-gaps).

---

## Direct references are never updated

Editable installs and URL/VCS/local-path requirements are skipped silently (logged at DEBUG):

```text
-e .
-e git+https://github.com/org/lib.git@v1.2.0#egg=lib
https://example.com/internal-1.0.tar.gz#egg=internal
./vendor/local-pkg
```

They are pinned to a source rather than a PyPI version; appending a specifier would produce an
uninstallable line. Update these by editing the ref or URL yourself.

---

## Multi-file updates

If your file uses `-r` includes, `update` writes **every** file that contains an updated
requirement:

```bash
depkeeper update main.txt -y
```

```text title="main.txt — directive untouched"
-r sub/base.txt
click~=8.4
```

```text title="sub/base.txt — rewritten"
requests==2.34.2
```

All affected files are rendered before any is written, and a failure part-way rolls back the files
already committed. `--backup` backs up every affected file. Preview with `--dry-run` when the
include graph is unfamiliar.

---

## Backups

```bash
depkeeper update --backup
```

Creates `requirements.<timestamp>_<uuid>.backup.txt` next to each affected file *before* any
write. If the update fails, depkeeper restores from these copies and reports:

```text
[ERROR] Error during update: <cause>
[OK] Restored original file(s) from backup
```

Backups are never cleaned up automatically. In a git repository, `git diff` and `git checkout` are
usually better tools; add `*.backup.*` to `.gitignore` if you use `--backup` anyway.

Restoring manually:

```bash
cp requirements.20260815_144129_853745_d54d785d.backup.txt requirements.txt
```

---

## Conflict-aware updates

With conflict checking enabled (the default), the versions written are the resolver's output, and
a warning precedes the plan when unresolved conflicts remain:

```text
[WARNING] 1 package(s) have unresolved conflicts — updates may cause issues
```

The plan can then legitimately contain a **downgrade**:

```text
│ flask    │   2.3   │    2.2.5    │ downgrade │
│ werkzeug │   2.2   │    2.2.3    │   patch   │
```

This rewrites `flask>=2.3,<3.0` to `flask>=2.2.5,<3.0` — the floor you declared is lowered. It is
intentional (the alternative is a set that does not install), but it should never pass unreviewed.
If you would rather fix it yourself, raise the other side's cap and re-run:

```text
flask>=2.3,<3.0
werkzeug>=2.3.7,<3.0
```

---

## Idempotency

Re-running `update` on an already-updated file is a no-op:

```text
[OK] All packages are up to date!
```

Targets that would produce a byte-identical line are skipped, so `click~=8.4` does not re-report
`8.4.2` forever. This makes `update` safe to run on a schedule.

---

## Failure modes

| Failure | Behaviour | Exit |
|---|---|---|
| File does not exist | Click usage error before depkeeper runs. | 2 |
| Parse error | Reported with line number and content; nothing written. | 1 |
| Hashed requirement without opt-in | Refused before any write. | 1 |
| Target excluded by declared constraints | That package is skipped with a warning; the rest proceed. | 0 |
| A file cannot be written | Committed files are rolled back; backups restored if present. | 1 |
| Network failure for one package | That package becomes an unavailable stub and is not updated; the run continues. | 0 |
| Total network failure | Every package becomes a stub; nothing to update. | 0 |
| `Ctrl+C` | Aborts. Files are either fully old or fully new. | 130 |

---

## Recovery

| You want to | Do |
|---|---|
| Undo an update, git-tracked | `git checkout -- requirements.txt` |
| Undo an update, `--backup` used | Copy the `.backup.` file back over the original. |
| Undo an update, neither | Re-derive: pin the previous versions manually. depkeeper keeps no history. |
| Verify what changed | `git diff requirements.txt` before installing. |
