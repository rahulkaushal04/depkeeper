# Changelog

All notable changes to depkeeper are listed here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Impact** marks a change that can alter an update plan, an exit code or written output. Check
your CI and scripts for these before upgrading.

---

## [Unreleased]

---

## [1.0.0] - 2026-11-11

First stable release. It adds `pyproject.toml` and conda support, opt-in major upgrades, calendar versions,
per-package policy and `--verify`, and hardens parsing, writes and networking.

### Added

- **More file types:** `pyproject.toml` (project dependencies, optional extras, dependency groups, build requirements, Poetry, uv/PDM/Hatch dev dependencies) and conda `environment.yml`. Pass a directory to check every supported file at once. Edits change only the version text, so comments and formatting stay. Conda packages are matched to PyPI by name, so results are approximate.
- **Opt-in major upgrades:** `--allow-major PKG` (repeatable, `'*'` for all) or `allow_major = true` per package. Your own upper bounds, including the one implied by `~=`, still apply. A newer major that was not applied shows as "major available".
- **Calendar versions** (`2024.8.30`, `24.1`) are detected automatically. Updates are labelled `year`, `month` or `patch`. Override with `versioning = "calver"` or `"semver"`.
- **Per-package policy** in config: `max_update`, `hold`, `ignore`, `allow_prerelease`, `allow_major`, `versioning`.
- `--python-version X.Y` picks the target Python. Order: flag, config `python_version`, the file's `requires-python` (or Poetry `python`, conda `python=`), then the running Python.
- `--min-age 7d` skips releases newer than the given age.
- `check --fail-on {none,updates,minor,major}` exits `3` when the threshold is met.
- `--ignore PKG` on `check` and `update`. `update --max-update {patch,minor,major}` caps the update size.
- `update --refresh-hashes` rewrites `--hash` lines for the new version from PyPI digests.
- `update --verify` asks pip's resolver, for the target Python, whether the plan installs together before writing. A conflict exits `1`.
- `--format markdown` (`check`, `update`) and `--format json-v2` (`check`). `check --no-strict-version-matching`.
- Config is found by walking up to the repository root (`.git`), or to `$HOME` without one.

### Changed

- **Impact:** `check` and `update` exit `4` when a PyPI lookup fails, and no longer print "All packages are up to date!" in that case.
- **Impact:** declining the update prompt, or `-p` matching nothing, exits `1` (was `0`).
- **Impact:** `update` no longer pins unversioned names in `pyproject.toml` and `environment.yml` unless `--pin` is given. `requirements.txt` is unchanged.
- **Impact:** `--max-update` now caps the chosen version for every package. `requests==2.25.0 --max-update patch` gets `2.25.1`.
- **Impact:** a line whose own Python marker is false for the target Python (`python_version<"3.9"` on 3.12) is left unchanged and reported as "not applicable".
- **Impact:** calendar-version detection looks at recent releases, so `pip`, `packaging` and `attrs` are now treated as calver and can move across years.
- **Impact:** conflict resolution follows `min_age` and per-package policy, no longer flips between two states, and no longer depends on file order. Plans for conflicting files can differ.
- **Impact:** `~=X.Y` lines no longer show "outdated" forever after `update`. A newer release inside the series the line can express is not an update.
- Backups are named `<name>.<timestamp>_<uuid>.backup`. The old name matched `requirements*.txt`, so a later directory run could rewrite the backup.
- Minimum versions raised: `packaging>=26.2`, `rich>=14.3.4`, `tomli>=2.5.0`, and `setuptools>=75.3.4` to build.
- Table output is shorter: one Python requirement per row, and the resolution summary shows only when something changed or conflicted.

### Fixed

- **Writes:**
  - `update` aborts if a file changed since it was read.
  - Ctrl-C between files rolls back every file already written.
  - `update` could edit the wrong line when a file contained form feeds or Unicode line separators.
  - `update` now changes only the version text and keeps the name's spelling, extras, marker, quotes and comment.
  - Duplicate packages across files are updated consistently.
  - `update --pin` works when the version does not change.
  - `update` without a terminal and without `--yes` gives a clear message, not a traceback.
  - Ctrl-C or Ctrl-D at the confirmation prompt prints "Aborted." and exits `130`, instead of "Unexpected error".
- **Parsing:**
  - Backslash continuations (pip-compile `--hash` files), `-rfile`, `-c=file`, `-e.`, quoted `-r` paths, `ftp://` and `git+file://` URLs and markers on URL lines are read correctly.
  - Comment lines ending in `\` no longer swallow the next requirement.
  - Editable, VCS and URL requirements are never looked up on PyPI.
  - A Poetry `python` constraint now sets the target Python.
  - Non-ASCII digits no longer crash version parsing.
  - A local path requirement that does not exist yet no longer crashes on Windows with Python 3.8 or 3.9.
  - Conda packages such as `cuda-python` and `librosa` are no longer skipped as conda-only.
- **Recommendations:**
  - Yanked-only releases are never recommended.
  - Dependency markers are evaluated for the target Python.
  - A package PyPI could not serve gets no recommendation.
  - A package already up to date no longer shows its own version as withheld by `--min-age`.
  - One malformed specifier no longer switches off the others.
  - A lower bound that is not a real release is read as the lowest real release above it.
- **Conflicts:**
  - Each conflict is shown once, against the final recommendation.
  - A held or ignored package is never lowered to satisfy another.
  - A failed dependency lookup is reported as "Conflict check incomplete", never as "no conflicts".
- **Network:**
  - With the network down, 7 packages take about 1.5 s (was about 111 s).
  - The circuit breaker is per host.
  - Oversized, truncated or malformed responses give clear errors.
  - Closing the output early (`| head -1`) exits `141` quietly.
- **`--verify`:**
  - Source-only packages are skipped with a warning instead of blocking.
  - A release that needs a newer Python than the one running pip is no longer reported as missing.
  - Constraints and `-p` selections are included in the checked plan.
  - Ctrl-C stops pip at once.
- **Output:**
  - `--format simple` no longer wraps lines.
  - A broken `[depkeeper]` config value is an error, not a crash.
  - `NO_COLOR` is respected.
  - Messages that start with a newline keep their label on the text line.

### Security

- Text from PyPI, file names and error messages can no longer inject Rich markup, hyperlinks, terminal control sequences or invisible Unicode characters (bidi, zero-width, tag) into output. Markdown reports drop non-http(s) links and escape cell text.
- Credentials in URLs, query strings and requirement lines are masked in errors, logs and `--verify` output by one shared redaction. pip option lines are never logged.
- `--verify` never builds source distributions, and refuses requirement strings that carry pip options such as `--index-url` or `-r`.
- HTTP: responses are capped at 64 MB, requests have a total deadline, and redirects are followed only over https to PyPI hosts.

---

## [0.1.1] - 2026-08-15

### Changed

- **Impact:** duplicate declarations of one package (for example from two `-r` includes) are resolved separately instead of sharing one recommendation.
- **Impact:** wildcard bands (`pkg==2.*`) now take part in major-boundary and update checks.
- **Impact:** `check` table badges changed from symbols to text: `[OK]`, `[OUTDATED]`, `[CONFLICT]`, `[INCOMP]`, `[ERROR]`. `--format json` and `simple` are unchanged.
- `tomli` is used for TOML on every Python version. Config files with a byte-order mark now parse.

### Fixed

- `Retry-After` on a `429` is capped at 120 s and both header forms are parsed.
- The `[y/N]` prompt suffix is no longer swallowed by Rich markup.
- `update` no longer pairs a requirement with an unrelated package when the lists fall out of step. The entry is logged and skipped.

---

## [0.1.0]

First public release.

### Added

- `depkeeper check` (read-only) and `depkeeper update` (in-place). Options include `--dry-run`, `-y`, `--backup`, `--pin`, `-p`, `--allow-hash-removal`, `--outdated-only`, `-f table|simple|json`, `--check-conflicts`, `--strict-version-matching`.
- Global `-c/--config`, `-v`, `--color/--no-color`, `--version`. Exit codes `0`, `1`, `2`, `130`.
- **Safe recommendations:** never crosses a major version, respects each release's `requires_python`, skips pre-releases, keeps your upper bounds and exclusions, and only moves the floor.
- **Conflict resolution** across packages: iterative, boundary-respecting, with a "revert both" fallback and advisory alternatives.
- **Parsing:** extras, markers, `-r` includes with per-file provenance, `-c` constraints, editable, VCS and URL requirements (reported, never changed), `--hash`, and byte-order marks.
- **Safe writes:** all files are rendered first, written atomically, and rolled back if a later write fails. CRLF, LF and file mode are preserved. `--backup` keeps copies.
- **Output:** table, simple and JSON, with JSON on stdout and everything else on stderr.
- **Config:** `depkeeper.toml` or `[tool.depkeeper]` with strict validation.
- **Performance:** one PyPI request per package, async HTTP/2, bounded concurrency, backoff and `Retry-After`.

### Security

- Updating a hashed requirement is refused unless you pass `--allow-hash-removal`.
- depkeeper never installs, builds or runs the packages it reads. It only reads PyPI metadata over verified HTTPS.
- 10 MB limit on input files.

---

[Unreleased]: https://github.com/rahulkaushal04/depkeeper/compare/v1.0.0...main
[1.0.0]: https://github.com/rahulkaushal04/depkeeper/compare/v0.1.1...v1.0.0
[0.1.1]: https://github.com/rahulkaushal04/depkeeper/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/rahulkaushal04/depkeeper/releases/tag/v0.1.0
