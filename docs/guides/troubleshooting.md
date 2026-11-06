---
title: Troubleshooting
description: Symptom-indexed diagnosis and recovery for depkeeper
---

# Troubleshooting

Each entry states the symptom, the mechanism behind it, and the fix. Start with
[First response](#first-response) if you do not yet know which category you are in.

---

## First response

```bash
depkeeper --version                       # is it the version you think?
python --version                          # is this the interpreter you intend?
depkeeper -vv check --format json > report.json 2> debug.log
```

`debug.log` names the file being parsed, the configuration in effect, every HTTP retry, and every
resolution decision. Most questions are answered by its first twenty lines:

```text
INFO: Target Python: running interpreter (from running interpreter)
DEBUG: depkeeper v0.1.1
DEBUG: Config path: None
DEBUG: Verbosity: 2 | Color: True
```

---

## Installation and invocation

### `depkeeper: command not found`

The console script directory is not on `PATH`.

```bash
python -m depkeeper --version          # always works if the package is importable
python -m pip show depkeeper           # confirm it is installed in this interpreter
```

Add the interpreter's `bin`/`Scripts` directory to `PATH`, or use `pipx`.

### `Error: No such option: --bogus` (exit 2)

A usage error from Click, raised before depkeeper runs. Check the spelling against
[CLI reference](../reference/cli-commands.md).

### `Error: Invalid value for '[FILE]': File 'x.txt' does not exist.` (exit 2)

Click validates the argument before depkeeper starts. Verify the path and your working
directory. Without `FILE`, depkeeper uses `requirements.txt` in the **current directory**, or else
the supported files (`requirements*.txt`, `pyproject.toml`, `environment.yml`) found there. A
directory is accepted and checked as a whole.

---

## Parsing

### `Failed to parse <file>: Invalid requirement syntax: ...`

```text
[ERROR] Failed to parse bad2.txt: Invalid requirement syntax: Expected semicolon
(after name with no version specifier) or end
    this is !!! not
         ^ (line=2, content=this is !!! not, file=/path/bad2.txt)
```

The message names the line number, the line content and the file. Common causes:

| Cause | Fix |
|---|---|
| A typo or free text on a requirement line | Correct or comment out the line. |
| A pip option depkeeper does not recognise | Only the options listed in [Requirements parsing](../concepts/requirements-parsing.md#supported-line-types) are skipped. Remove or comment the line. |
| A URL with no `#egg=` and no inferable name | Add `#egg=<name>`. |

### `Circular dependency detected: a.txt -> b.txt -> a.txt`

Two requirements files include each other via `-r`. The message prints the full chain. Break the
cycle; use a shared `base.txt` that neither includes back.

### `File too large: <n> bytes (max 10485760)`

A 10 MB guard. A legitimate requirements file is never this large — check that you passed the
right file.

### The first package on line 1 is not recognised

Almost always a byte order mark written by a Windows editor. depkeeper handles this
automatically (`utf-8-sig` on read, BOM preserved on write).

### Windows line endings changed after an update

They do not. depkeeper re-attaches each line's original terminator and never normalises. If your
diff shows whole-file line-ending churn, another tool (an editor, `git` `autocrlf`) did it.

---

## PyPI errors

### `[ERROR]` rows / `Package information unavailable`

The metadata fetch failed. In order of likelihood:

| Cause | Diagnosis | Fix |
|---|---|---|
| The package is not on public PyPI | `curl -sI https://pypi.org/pypi/<name>/json` | depkeeper only queries `pypi.org`; there is no private-index support. Private-index packages always fail. |
| Typo in the package name | Compare with the PyPI project page. | Correct the name. |
| No egress / proxy blocking | `curl https://pypi.org/pypi/requests/json` | Set `HTTPS_PROXY`. |
| TLS interception without a trusted CA | `-vv` shows SSL errors | Set `SSL_CERT_FILE` to the corporate CA bundle. |
| Rate limiting | `-vv` shows `Rate limited (429)` | See below. |

The run continues regardless: a single unreachable package never aborts the report. It is
reported on stderr as `N package(s) could not be checked (not found on PyPI or network error): ...`
and `check` exits `4` (`update` also exits `4` after updating the others). A failure is never
reported as up to date. Direct references (URL, VCS, editable) are not looked up and never cause `4`.

### `Rate limit exceeded after 5 retries`

Too many requests from one egress IP. depkeeper honours `Retry-After` (capped at 120 s) and retries up to 5 times.

- Use `--no-check-conflicts` — the resolution phase is the dominant request source.
- Stagger scheduled jobs across repositories.
- Split very large requirements files.

### `Request failed after 4 attempts: <url>`

Timeouts or network errors exhausted the retry budget (3 retries + the initial attempt, backoff
≈ 1 s / 2 s / 4 s). Check connectivity and proxy configuration. Timeout and retry counts are not
configurable from the CLI. A single request is also capped at 180 s in total
(`Request timed out after 180s`).

### How do I find unreachable packages in JSON?

They have `"status": "no-update"` and an `error` field (`Package information unavailable`):

```bash
depkeeper check --format json 2>/dev/null | jq -r '.[] | select(.error) | .name'
```

---

## Configuration

### My configuration file is ignored

```bash
depkeeper -vv check 2>&1 | grep 'Config path'
```

If it prints `Config path: None`, discovery found nothing. depkeeper looks in the current directory
and each parent up to the repository root (the first directory with `.git`; without one, up to your
home directory). Either run inside the repository or pass `--config path/to/depkeeper.toml`.

A `pyproject.toml` without a `[tool.depkeeper]` table is deliberately skipped.

### `Unknown configuration keys: <key>`

The valid keys are `check_conflicts`, `strict_version_matching`, `fail_on`, `ignore`,
`python_version`, `min_age`, `versioning` and `packages` (see [Configuration](configuration.md)). The
error is intentional: a silently ignored typo would leave you believing a setting is active.

### `check_conflicts must be a boolean, got str`

Use TOML booleans, not strings: `check_conflicts = true`, not `"true"`.

### `Configuration file <file> is not valid UTF-8`

Re-save the file as UTF-8. A BOM is fine; other encodings are not.

### A CLI flag does not override the config file

It does — except that `update --strict-version-matching` has no negative form (`check` has
`--no-strict-version-matching`). Use a different `--config` file for `update`.

---

## Recommendations that look wrong

### "It won't upgrade past 1.x"

The major-version boundary, working as designed. depkeeper reports it as
`major available: <pkg> <version> (use --allow-major <pkg>)`. Pass `--allow-major <pkg>` (or set
`allow_major = true` for it) to cross the major within your own upper bounds, or edit the floor
yourself. See
[the boundary rule](../concepts/version-recommendation.md#the-major-version-boundary).

### "The recommendation is well below `Latest`"

Check, in this order:

1. Your own declared cap or exclusion (`<`, `!=`, `==x.*`). It is enforced.
2. The major boundary, anchored on the inferred current version.
3. The `Conflicts` column — another package may be constraining it.
4. `requires_python` of the newer releases versus the target Python (`--python-version`, config,
   the file's `requires-python`, else the interpreter depkeeper runs on).
5. `--min-age` / `min_age`, which withholds recently released versions (reported as held back).

```bash
depkeeper -vv check 2>&1 | grep -i "no eligible version"
```

That WARNING names the major, the Python version and the constraints that eliminated every
candidate.

### "Recommendations differ between my laptop and CI"

Different target Python. Unless you pass `--python-version`, set `python_version`, or the file
declares `requires-python`, filtering uses **depkeeper's own** interpreter. Set one of those so
both agree (`-v` logs `Target Python: ...`).

### "A date-versioned package never updates"

Calver is detected automatically; if depkeeper treats the package as semver, set
`versioning = "calver"` in `[depkeeper.packages.<name>]`. See
[Limitations](../reference/limitations.md#calendar-versioning-heuristics).

### "It proposed a downgrade"

Either the declared version is Python-incompatible on the running interpreter, or another package
in the file requires an older release. Read the `Conflicts` column and
[Conflict resolution → Downgrades](../concepts/conflict-resolution.md#downgrades). Prefer fixing
the other side of the conflict yourself.

### "`update` changed a package that `check` showed as OK"

An unversioned requirement. The table's up-to-date branch doubles as its fallback branch, so it
renders `[OK]`; the machine formats correctly report `install`. See
[Limitations](../reference/limitations.md#unversioned-requirements-report-as-ok).

### "A package is skipped with no update"

```text
[WARNING] Skipping flask: 2.3.3 is excluded by the declared constraint '<2.3'
(use --pin to replace the constraint)
```

The resolver proposed a version your own constraint forbids. Either relax the constraint or use
`--pin`.

---

## Conflict resolution

### `Converged: No (stopped after N iterations)`

The resolver stalled or exhausted its 100-pass budget. The current update set is still reported
and applied. Review it manually. Common with mutually impossible constraints — resolve one side by
hand and re-run.

### `No compatible version found for A ↔ B within major boundaries; reverting both`

No version of either package, within their current majors, satisfies the other. Both revert to
their current versions — no change is proposed. Fixing this requires a major upgrade, which
depkeeper will not perform.

### A conflict is shown that no longer applies

Conflict lists are cumulative across resolution passes by design: they are the audit trail of
everything considered, not the set of live problems. `packages_with_conflicts` counts the same
way. The **applied** version is always correct; only the conflict annotation is historical.

### Conflicts are not detected at all

| Cause | Note |
|---|---|
| The dependency is not in your requirements file | Only declared packages are cross-validated. |
| The dependency is conditional on an extra | `; extra == "..."` entries are stripped. |
| `--no-check-conflicts` or `check_conflicts = false` | Resolution is disabled. |
| It is a transitive conflict | depkeeper does not expand the graph. `pip install` will find it. |

---

## Update failures

### `Refusing to update requirement(s) with --hash entries`

Intentional. Hashes are version-specific; removing them silently degrades integrity. Pass
`--refresh-hashes` to regenerate them from PyPI (or `--allow-hash-removal` and regenerate them
yourself). See
[Hashed requirements](updating-dependencies.md#hashed-requirements).

### `Failed to write <path>`

The two-phase writer rolls back the files it had already committed; `--backup` copies are kept
beside the originals. Check:

- file or directory permissions,
- available disk space,
- whether the file is open in a locking editor (Windows),
- whether the path is on a filesystem where `os.replace` is not atomic.

### `Could not restore <path>`

A rollback failed. The original content is still in the backup file if `--backup` was used, or in
version control. Restore manually.

### `Cannot update requirement at <file>:<line>: ...`

The writer refused to render an unsatisfiable line. Nothing was written. The message names the
constraint that excludes the target.

### `Proposed updates do not resolve (pip):` (exit 1)

`--verify` found that pip cannot install the proposed set. Nothing was written. Fix the listed
conflict (usually by relaxing or raising a bound), or drop a package with `--ignore`. A
`--verify skipped: ...` warning means pip was missing, older than 22.2, offline, or the release is
source-only; the update proceeds unverified.

### `Cannot ask for confirmation without a terminal`

`update` prompts unless `-y`. Re-run with `--yes` to apply or `--dry-run` to preview.

### `Cannot refresh hashes: no PyPI file digests available for ...`

`--refresh-hashes` could not get digests for the new version; nothing was written. Retry, or use
`--allow-hash-removal`.

### Exit code 3 or 4 from `check`

`3`: `--fail-on` (or `fail_on`) found updates at that level. `4`: at least one package could not be
looked up on PyPI (wins over `3`). See [Exit codes](../reference/exit-codes.md).

### The update touched files I did not name

`-r` includes. `depkeeper update main.txt` writes every file containing an updated requirement.
Preview with `--dry-run`; `--backup` covers all affected files.

---

## Output and automation

### JSON output is not parseable

Diagnostics go to stderr for the machine-readable formats (`json`, `json-v2`, `markdown`), so:

```bash
depkeeper check --format json 2>/dev/null | jq .
```

An empty result set still emits `[]`, so `jq` never receives empty input.

### A status label such as `[OUTDATED]` is missing from simple output

Rich would interpret `[OUTDATED]` as a style tag. Markup is disabled for those lines, so the label
is emitted literally.

### The table is unreadable / wrapped

Widen the terminal, or use `--format simple` or `--format json`. Column widths are computed from
the terminal width by Rich.

### ANSI escape codes in captured logs

```bash
export NO_COLOR=1
```

depkeeper also disables colour automatically when `CI` is set or when the stream is not a TTY.

---

## Reporting a bug

Include:

1. `depkeeper --version` and `python --version`.
2. The requirements file, minimised to the smallest reproducer.
3. The exact command line.
4. `depkeeper -vv <command> ... 2> debug.log` — attach `debug.log`.
5. What you expected and what happened.

Open the issue at
[github.com/rahulkaushal04/depkeeper/issues](https://github.com/rahulkaushal04/depkeeper/issues).
For security issues, follow the [security policy](../community/security.md) instead.
