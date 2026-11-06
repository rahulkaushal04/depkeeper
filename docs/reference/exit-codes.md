---
title: Exit Codes
description: Exit code semantics per command, with scripting patterns
---

# Exit Codes

| Code | Name | Meaning |
|---|---|---|
| `0` | Success | The command completed with nothing to report as a failure. |
| `1` | Error | An application error occurred, or `update` was declined / matched nothing; see stderr. |
| `2` | Usage error | Click rejected the command line before depkeeper ran. |
| `3` | Updates found | `check --fail-on` threshold met (`check` only). |
| `4` | Lookup failed | At least one package could not be looked up on PyPI (`check` and `update`; wins over `3` for `check`). |
| `130` | Interrupted | `Ctrl+C` (`128 + SIGINT`) or aborted prompt. |

Without `--fail-on`, `check` exits `0` even when updates exist. Direct references (editable, VCS,
URL, local path) are never looked up on PyPI and never cause `4`.

---

## `0` — Success

| Situation | Exit |
|---|---|
| `check`: everything up to date | `0` |
| `check`: outdated packages found, no `--fail-on` | `0` |
| `check`: unresolved conflicts found, no `--fail-on` | `0` |
| `update`: updates applied | `0` |
| `update`: nothing to update | `0` |
| `update`: `--dry-run` (and no lookup failed) | `0` |
| `update`: a package skipped because its target violates the declared constraints | `0` |
| `update --verify`: pip resolved the plan, or the check was skipped with a warning (pip missing, offline, source-only release) | `0` |
| `check`: no packages found in the file | `0` |

## `1` — Error

Also returned by `update` when you decline the confirmation prompt, when `--packages` matches nothing, or when `--verify` finds that the proposed set does not resolve.

Raised when a `DepKeeperError` (or any unexpected exception) reaches a command boundary. The
message is printed to **stderr** with an `[ERROR]` prefix.

| Cause | Example message |
|---|---|
| Parse failure | `Failed to parse requirements.txt: Invalid requirement syntax: ...` |
| Circular include | `Circular dependency detected: a.txt -> b.txt -> a.txt` |
| Configuration error | `Unknown configuration keys: check_conflict` |
| Refused hashed update | `Refusing to update requirement(s) with --hash entries: requests. ...` |
| `update --verify` conflict | `Proposed updates do not resolve (pip): ...` (also when no updates are found but the current set conflicts; nothing is written) |
| Unsatisfiable rewrite | `Cannot update requirement at requirements.txt:3: ...` |
| Write failure | `Failed to write /path/requirements.txt: ...` |
| File too large / unreadable | `File too large: 12000000 bytes (max 10485760)` |
| No terminal for the prompt | `Cannot ask for confirmation without a terminal. Re-run with --yes to apply or --dry-run to preview.` |
| Empty directory target | `No supported dependency files found in <dir>` |
| Unexpected exception | `Unexpected error: <detail>` (full traceback at `-vv`) |

## `3` — Updates found (`check` only)

`check --fail-on {updates,minor,major}` and an update at or above that level exists.

## `4` — Lookup failed

At least one non-ignored package could not be looked up on PyPI (not found, or network error).
For `update`, the file is still updated for the packages that were found, and the command then exits `4`. The stderr line is `N package(s) could not be checked on PyPI: <names>` (`update`) or `N package(s) could not be checked (not found on PyPI or network error): <names>` (`check`). Conda-only names that PyPI does not know are a warning, not a `4`.

## `2` — Usage error

Produced by Click, before any depkeeper code runs.

```text
Usage: depkeeper check [OPTIONS] [FILE]
Try 'depkeeper check --help' for help.

Error: Invalid value for '[FILE]': File 'nosuchfile.txt' does not exist.
```

```text
Error: No such option: --bogus
```

Also raised for a `--config` path that does not exist, an invalid `--format`, `--fail-on`, `--max-update` or `--python-version`/`--min-age` value, `update --refresh-hashes` together with `--allow-hash-removal`, and `update -f markdown` without `--yes` or `--dry-run`.

## `130` — Interrupted

`Ctrl+C` at any point, or Ctrl-D / abort at the confirmation prompt on a terminal (`Aborted.`). A warning is written to stderr:

```text
[WARNING] Operation cancelled by user
```

Files are left either fully old or fully new; see
[Write safety](../concepts/write-safety.md#what-still-requires-care).

---

## Gating on results

`check` reports through its payload (or `--fail-on`). The correct pattern separates *did depkeeper work* from
*what did it find*:

```bash
set -euo pipefail

if ! depkeeper check --format json > report.json 2> depkeeper.log; then
  echo "depkeeper failed:" >&2
  cat depkeeper.log >&2
  exit 1
fi

OUTDATED=$(jq '[.[] | select(.status == "outdated")] | length' report.json)
CONFLICTS=$(jq '[.[] | select(.conflicts)] | length' report.json)

if [ "$CONFLICTS" -gt 0 ]; then
  echo "$CONFLICTS package(s) have dependency conflicts" >&2
  exit 1
fi

echo "$OUTDATED package(s) behind"
```

### Explicit dispatch

```bash
depkeeper check
case $? in
  0)   echo "check completed" ;;
  3)   echo "updates available"; exit 3 ;;
  4)   echo "PyPI lookup failed"; exit 4 ;;
  1)   echo "application error"; exit 1 ;;
  2)   echo "usage error"; exit 2 ;;
  130) echo "cancelled"; exit 130 ;;
  *)   echo "unexpected exit code $?"; exit 1 ;;
esac
```

### PowerShell

```powershell
depkeeper check --format json > report.json
if ($LASTEXITCODE -ne 0) {
    Write-Error "depkeeper failed with code $LASTEXITCODE"
    exit $LASTEXITCODE
}
$report = Get-Content report.json | ConvertFrom-Json
$outdated = @($report | Where-Object { $_.status -eq 'outdated' }).Count
Write-Host "$outdated package(s) behind"
```

### Make

```make
.PHONY: deps-check
deps-check:
	@depkeeper check --format json > .deps.json
	@test "$$(jq '[.[] | select(.conflicts)] | length' .deps.json)" -eq 0 \
	  || { echo "dependency conflicts present"; exit 1; }
```

---

## Common mistakes

| Mistake | Consequence |
|---|---|
| Treating a `0` exit from `check` as "no updates". | Drift is never detected. |
| Piping stdout to a parser without checking the exit code. | A failed run produces no payload and the parser sees empty input. |
| Using `set -e` with `depkeeper check \| jq ...`. | The pipeline's exit status is `jq`'s. Use `set -o pipefail`, or capture to a file first. |
| Assuming `update` fails when it skips a package. | Skips are warnings, not errors; the command still exits `0`. |
| Expecting `--fail-on` to affect `update`. | It is a `check` option; `update` only exits `4` for lookup failures. |
| Piping `echo n \|` into `update` and expecting `0`. | Declining the prompt exits `1`. |
