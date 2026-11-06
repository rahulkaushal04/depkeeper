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
depkeeper update --backup      # 2. apply, keeping a timestamped copy (add --verify to have pip check first)
pip install -r requirements.txt # 3. verify the environment resolves
pytest                          # 4. verify the code still works
git diff requirements.txt       # 5. review before committing
```

Steps 3 and 4 are not optional. depkeeper validates the packages you declared against each other;
it does not build the full transitive graph. `pip` is the authority on whether the set installs;
`--verify` (below) asks it before anything is written.

---

## Preview first

```bash
depkeeper update --dry-run
```

```text
[WARNING] major available: urllib3 2.8.0 (use --allow-major urllib3)
                      Update Plan (Dry Run)
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
┃ Package  ┃    Current    ┃ New Version ┃ Change ┃ Python Requires ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
│ requests │    2.28.0     │   2.34.2    │ minor  │ >=3.10          │
│          │               │  175d old   │        │                 │
│ flask    │      2.0      │    2.2.5    │ minor  │ >=3.7           │
│          │               │  1283d old  │        │                 │
│ certifi  │ not specified │ 2026.10.23  │  new   │ >=3.7           │
│          │               │   14d old   │        │                 │
│ urllib3  │    1.26.0     │   1.26.20   │ patch  │ !=3.0.*,...     │
│          │               │  798d old   │        │                 │
└──────────┴───────────────┴─────────────┴────────┴─────────────────┘
[WARNING]
Dry run mode - no changes applied
```

(Rows trimmed. The `Python Requires` cell for `urllib3` is long in a real run.)

`--dry-run` executes everything except the write, so the plan is produced by the same code that
would have written the file. `Current: not specified` marks a requirement that had no version
specifier and will receive a pin.

---

## Confirmation

Unless `-y` is passed, you are prompted:

```text
Update 6 packages? (y, n) [y]:
```

- The default is **yes** — the plan has already been shown and you invoked `update` explicitly.
- Any input other than `y`/`n` causes Click to re-prompt.
- Declining prints `[WARNING] Aborted. No changes were made.`, writes nothing and exits `1`.
- `Ctrl+C` at the prompt exits `130`.
- With no terminal (CI), the prompt fails with
  `Cannot ask for confirmation without a terminal. Re-run with --yes to apply or --dry-run to preview.`

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
`[WARNING] No matching packages found: <names>` and exits `1` without writing.

Selection filters the package list **after** conflict resolution, so the versions applied are
still the mutually consistent ones. It does not re-resolve for the subset.

Other selectors: `--ignore PKG` (repeatable) never updates a package, and `--max-update
{patch,minor,major}` skips updates larger than that level (`--max-update minor` skips major bumps).
Per-package `hold`, `ignore` and `max_update` policies in the config apply as well.

---

## Range preservation (default)

Only the floor of a requirement moves. Everything else you declared is preserved:

```text
requests==2.28.0
flask>=2.0,<2.3
celery[redis]>=5.0,<6.0
click~=8.0
certifi
urllib3==1.26.0
```

```text
requests==2.34.2
flask>=2.2.5,<2.3
celery[redis]>=5.7.0,<6.0
click~=8.5
certifi==2026.10.23
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

```text
requests==2.34.2
flask==2.2.5
celery[redis]==5.7.0
click==8.5.0
certifi==2026.10.23
urllib3==1.26.20
```

Extras, markers and comments are unaffected; only version semantics change.

| Use `--pin` when | Avoid `--pin` when |
|---|---|
| The file describes a deployable application. | The file describes a library's dependencies. |
| You want reproducible installs from this file alone. | You rely on caps and exclusions as documentation of real incompatibilities. |
| The file is generated and regenerated wholesale. | The file is hand-maintained and reviewed. |

`--pin` also disables the declared-constraint check, because no declared constraint survives. In
`pyproject.toml` and `environment.yml`, bare names (no version) are only pinned when `--pin` is
given; `requirements.txt` always pins them.

---

## Hashed requirements

Requirements carrying `--hash` entries are **refused by default**:

```text
[ERROR] Refusing to update requirement(s) with --hash entries: requests. Hashes are
version-specific and cannot be silently removed. Re-run with --refresh-hashes to regenerate
them, or --allow-hash-removal to proceed without hashes.
```

Exit code `1`. Nothing is written (a `--dry-run` only warns).

### `--refresh-hashes` (recommended)

```bash
depkeeper update --refresh-hashes -y
```

For each hashed requirement that is updated, depkeeper fetches the new version's file digests from
PyPI and rewrites the `--hash=sha256:` lines in the same layout (`requirements.txt` files only):

```text
requests==2.34.2 \
    --hash=sha256:2a0d60c1...78e0 \
    --hash=sha256:f288924c...b9ed
```

If digests cannot be fetched the run fails with `Cannot refresh hashes: no PyPI file digests
available for <pkg>==<version>. Nothing was written.` Existing non-sha256 hashes are replaced.
`--refresh-hashes` and `--allow-hash-removal` are mutually exclusive (usage error, exit `2`).
Hashes come from PyPI, so they are only as trustworthy as your trust in the files PyPI serves.

### `--allow-hash-removal`

```bash
depkeeper update --allow-hash-removal
```

```text
[WARNING] Proceeding with --allow-hash-removal: hashes will be removed for requests
```

> [!CAUTION]
> **The result is a partially hashed file**
>
> Only the lines that changed lose their digests. `pip install --require-hashes` rejects a file
> in which *some* requirements have hashes and others do not, so the resulting file will not
> install in hash-checking mode.
>
> Prefer `--refresh-hashes`. If you remove hashes, regenerate them afterwards:
>
> ```bash
> depkeeper update --allow-hash-removal -y
> pip-compile --generate-hashes requirements.in   # or: hashin <pkg>
> ```

---

## Verifying the plan with pip

```bash
depkeeper update --verify --dry-run
```

```text
[OK] --verify: pip 26.2 resolved 27 requirements for Python 3.15 (darwin-arm64)
```

`--verify` runs `pip install --dry-run` over the whole final plan (updated and unchanged
requirements plus `-c` constraints) before anything is written. Nothing is installed and
source distributions are never built. It resolves for the run's target Python (`--python-version`,
config, `requires-python`, else the running interpreter). On a conflict nothing is written and the
exit code is `1`:

```text
[ERROR] Proposed updates do not resolve (pip):
[ERROR]   Cannot install flask==3.1.3 and werkzeug==2.3.8
[ERROR] Aborting: no changes were made.
```

It also fails when the current set already conflicts and no updates are proposed. If pip is
missing, older than 22.2, offline, or the release only exists as a source distribution, it warns
(`--verify skipped: ...`) and continues. pip honours its own index settings (`PIP_INDEX_URL`), so
this is the one step that can see a private index.

---

## Major upgrades, cooldown and Python target

- Majors are opt-in. `--allow-major PKG` (repeatable, `'*'` for all, or `allow_major = true` in
  the config) lets a package cross its major within your own upper bounds. `update` then warns
  `N major upgrade(s) applied: <names>. Run --verify and your tests.` Combine with `--max-update
  minor` to cap it.
- `--min-age 7d` skips versions released within that window.
- `--python-version X.Y` picks the Python that candidates must support; by default the file's
  `requires-python` (or a conda `python` pin) is used, else the running interpreter.

---

## PR-ready output

```bash
depkeeper update --dry-run --format markdown          # what would change, on stdout
depkeeper update -y --format markdown > pr-body.md    # what changed
```

`--format markdown` needs `--yes` or `--dry-run`; status messages go to stderr so stdout stays a
clean document.

---

## Other file types

`update` also edits `pyproject.toml` (`[project]`, optional dependencies, dependency groups,
`[build-system]`, Poetry tables) and conda `environment.yml`, changing only the version text and
keeping comments and layout. `FILE` can be a directory. Dependencies without a version in those
files are left alone unless `--pin` is given.

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

```text
-r sub/base.txt
click~=8.4
```

```text
requests==2.34.2
```

All affected files are rendered before any is written, and a failure part-way rolls back the files
already committed. A file edited by someone else while depkeeper ran is not overwritten. `--backup`
backs up every affected file. Preview with `--dry-run` when the
include graph is unfamiliar.

---

## Backups

```bash
depkeeper update --backup
```

Creates `requirements.txt.<timestamp>_<uuid>.backup` next to each affected file *before* any
write:

```text
[OK] Backup saved: /path/to/requirements.txt.20261106_191436_642846_64aff599.backup
```

If a write fails, files already written are restored from the content depkeeper read (not from the
backups) and depkeeper prints `Original file(s) are saved at: <backup paths>`. Backups are never cleaned up automatically. In a git repository, `git diff` and `git checkout` are
usually better tools; add `*.backup` to `.gitignore` if you use `--backup` anyway.

Restoring manually:

```bash
cp requirements.txt.20261106_191436_642846_64aff599.backup requirements.txt
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
| Hashed requirement without `--refresh-hashes` / `--allow-hash-removal` | Refused before any write. | 1 |
| `--verify` finds a conflict | Nothing written. | 1 |
| Prompt declined, or `--packages` matches nothing | Nothing written. | 1 |
| Target excluded by declared constraints | That package is skipped with a warning; the rest proceed. | 0 |
| A file cannot be written | Committed files are rolled back; backups restored if present. | 1 |
| Network failure or unknown package | That package is reported (`N package(s) could not be checked on PyPI`) and not updated; the rest are updated. | 4 |
| Total network failure | Every package is reported; nothing to update. | 4 |
| `--refresh-hashes` and `--allow-hash-removal` together | Usage error. | 2 |
| `Ctrl+C` | Aborts. Files are either fully old or fully new. | 130 |

---

## Recovery

| You want to | Do |
|---|---|
| Undo an update, git-tracked | `git checkout -- requirements.txt` |
| Undo an update, `--backup` used | Copy the `.backup.` file back over the original. |
| Undo an update, neither | Re-derive: pin the previous versions manually. depkeeper keeps no history. |
| Verify what changed | `git diff requirements.txt` before installing. |
