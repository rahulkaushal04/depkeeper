# Changelog

All notable changes to depkeeper are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> [!IMPORTANT]
> **Recommendation logic is a behavioural contract.** A change that makes the same requirements
> file produce a different update plan is at minimum a **minor** release, even when it looks like
> a bug fix — consumers gate pipelines on that output. Such entries are marked **Impact** so you
> know what to re-verify before upgrading.

Sections used: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.

---

## [Unreleased]

### Added

- **Opt-in major upgrades.** `--allow-major PKG` (repeatable, `'*'` for all) on `check` and `update`, and `allow_major = true` in `[depkeeper.packages.<name>]`, let a package cross its current major. Your own upper bounds, `--max-update`/`max_update`, Python compatibility, the `min_age` cooldown, `hold` and `ignore` still apply, and a name that is not in the file warns. A newer major that was not applied is reported as `major available` (notice, a Markdown section, and an optional `major_available` key in `json`/`json-v2`). `update` warns when it applies (or, with `--dry-run`, would apply) a major. `--max-update` is applied before the candidate is chosen, so the best in-cap version still wins and the capped major is shown as blocked by `--max-update`. Without the opt-in, recommendations are unchanged.
- **New input formats.** `check` and `update` now read `pyproject.toml` (PEP 621, PEP 735 dependency groups, `build-system.requires`, Poetry) and conda `environment.yml` (`dependencies:` and `pip:` lists). Edits are made in place, so comments and formatting survive. Conda-channel packages are matched on PyPI by name only and are approximate. Pass a directory to check every supported file in one report; reports show a source column when several files are checked.
- **Calendar versioning.** Packages such as `2024.8.30` are detected automatically (or set with the `versioning` option). Calver has no major boundary. Updates are labelled `year`, `month` or `patch`. For `--fail-on` and `--max-update`, `year` and `month` count as `minor`.
- **Per-package policy** in config (`[depkeeper.packages.<name>]`): `max_update`, `hold`, `allow_prerelease`, `versioning`, `ignore`. Output marks affected packages `[HELD]` or `[IGNORED]`.
- `--python-version X.Y` on `check` and `update`. Target Python is taken from the flag, then config `python_version`, then the file's `requires-python` or conda `python=` pin (lowest supported minor), then the running interpreter. The source is logged at `-v`.
- `--min-age DURATION` on `check` and `update` (config `min_age`): do not recommend versions released more recently than this. The newest older version is used instead, never one below the current version. Output shows release age and any versions withheld.
- `check --fail-on {none,updates,minor,major}` (config `fail_on`): exit `3` when the threshold is met.
- `check --ignore PKG` and `update --ignore PKG` (repeatable; config `ignore`).
- `update --max-update {patch,minor,major}`: skip larger updates and report how many were skipped.
- `update --refresh-hashes`: rewrite `--hash=sha256:` lines of hashed requirements for the new version from PyPI file digests, keeping the file's layout. Nothing is written if digests are unavailable. Cannot be combined with `--allow-hash-removal` (exit `2`).
- `update --verify`: ask pip's resolver (dry run, wheels only) whether the proposed set installs together before writing. A conflict exits `1`. A missing or old pip is a warning. The current set is also checked when no updates are found.
- `--no-strict-version-matching`.
- **Output formats:** `--format markdown` for `check` and `update` (PR body or CI summary, with changelog and PyPI links) and `--format json-v2` for `check` (versioned envelope with file, line, format, age, held/ignored and links). `--format json` keeps its bare array and gains optional `links` and `ignored` fields.
- `update` prints backup paths and previews hashed requirements under `--dry-run`.
- Configuration discovery now walks up from the working directory to the repository root (`.git`). Without a `.git` it stops at `$HOME`.

### Changed

- **Impact (`--verify`):** `update --verify` now resolves for the target Python (`--python-version`, config, `requires-python`, else the running interpreter) by passing pip `--python-version`, so a release that needs a newer Python is rejected. Verifying for a Python other than the one running pip needs pip 23.3; with an older pip it is skipped with a warning. A release that exists only as a source distribution is skipped with a warning (it is never built) instead of failing; a version that does not exist on the index still fails. A timeout now kills the whole pip process tree. Success prints what was verified (pip version, Python, platform, requirement and constraint counts).
- **Impact (exit codes):** `check` exits `4`, and reports on stderr, when any package lookup failed. It no longer prints "All packages are up to date!" in that case, also under `--outdated-only`. Editable, VCS and URL requirements do not trigger it.
- **Impact (exit codes):** `update` exits `4` when a package could not be looked up. It exits `1` when the confirmation prompt is declined or `--packages` matches nothing (previously `0`). Scripts that pipe `n` must adapt.
- **Impact (recommendations):** conflict resolution now follows `min_age`, the pre-release rule and per-package `hold`, `ignore` and `max_update` when it picks or backports a version, so a fresh backport can no longer bypass the cooldown. Plans for conflicting sets may differ when a cooldown or policy is set. `released`, `age_days` and withheld-version output follow the version actually recommended.
- **Impact (writes):** bare (unpinned) names in `pyproject.toml` and `environment.yml` are no longer pinned by `update` unless `--pin` is given. `requirements.txt` behaviour is unchanged.
- Conda packages missing from PyPI are a warning, not a lookup failure. `update` no longer lists conda prefix specs (`numpy=1.24`) whose rewrite would change nothing.
- `update` honours the config `ignore` list. An ignored package never causes exit `4`.
- An explicit `-c` file without a `[depkeeper]` table is now an error.
- `Ctrl-D` or an aborted prompt exits `130` with "Aborted."
- Table output: one short Python requirement per row, no exclusion lists, minimum column widths. The resolution summary is shown only when something changed or conflicted, or with `-v`.
- `DependencyAnalyzer` accepts `target_python` and `checker`.

### Fixed

- **`update --verify` is more trustworthy.** Source-only packages are now skipped with a warning naming the package, also for range specs (`docopt>=0.6`) and transitive dependencies, instead of blocking with exit `1`. Environment markers are evaluated for the target Python before pip runs (inapplicable lines are counted as "skipped by markers"; an all-excluded plan is skipped, not passed). A release that needs a newer Python is no longer reported as missing. The platform in the summary comes from pip. Constraints on packages not listed in the file and requirements outside `--packages` are now part of the verified plan. Credentials in query strings are redacted, and Ctrl-C kills pip's process tree at once. Impact: some plans that previously exited `1` now continue with a warning, and plans that previously passed on a host-evaluated marker may now be reported as conflicts.
- **Opt-in major upgrades:** the upper bound implied by a compatible-release spec is honoured. `click~=7.0` (`>=7.0,<8.0`) is no longer moved to `8.x` by `--allow-major`, and `major available` no longer advertises an `8.x` the declared range forbids. Only the major boundary is enforced (`~=1.4.2` is held below `2`). Recommendations without the opt-in are unchanged.
- **Parser:** comment lines ending in a backslash no longer swallow the next requirement. Added `-rfile`, `--requirement=file` and `-c=file` forms, backslash continuations (pip-compile `--hash` files) and `name @ url` round-trip. Repeated constraints are merged and no longer leak into rewritten files. Extras order is deterministic. `#egg=` names are validated.
- **`pyproject.toml` and conda:** a `pyproject.toml` without dependency tables reports "No packages found" (exit 0) instead of "Invalid requirement syntax"; directory mode skips it. A wrong-typed `dependencies = "x"` is a clear parse error. Malformed or non-string entries are skipped with a `file:line` warning. Conda `pip:` items keep marker spacing. `python=3` and `>=3.8.5` give sensible target Pythons.
- **PyPI data:** yanked-only releases are never recommended. Failed dependency lookups are not cached. Dependencies whose environment markers do not apply are ignored. Malformed payloads raise `PyPIError`. A release with no upload date still passes the cooldown, with a warning logged once per package.
- **Resolution:** a package PyPI could not serve no longer reports a recommendation. Conflict searches honour Python compatibility and the requirement's own bounds. The revert fallback rescans for conflicts. `--python-version` and `requires-python` now reach conflict resolution. `--format json-v2` counts and flags (`conflict_held`) packages held back by conflict resolution.
- **Write safety:** `update` aborts if a file changed on disk since it was read, and `pyproject.toml` and conda edits refuse to apply when the text at a span changed since parsing. A Ctrl-C between files of a multi-file commit rolls back, and backups are never restored over rolled-back files. Atomic writes clean up temp files on Ctrl-C and refuse read-only targets. The second file read honours the 10 MB cap. `update --allow-hash-removal` removes `--hash` continuation lines together with the pin. `--refresh-hashes` keeps an own-line comment after a trailing `\`, and warns when non-sha256 hashes are replaced.
- `update` without a terminal and without `--yes` gives a clear message instead of a traceback.
- **HTTP client:** the failure memo expires after 30 s and is keyed on query parameters. Failed requests are not retried again within a run.
- **`min_age`:** overflowing values (`inf`, `1e30`, `99999999999d`) and non-ASCII digits are a usage or config error, not a traceback. Units are case-insensitive (`7D`).
- `NO_COLOR` set by the user is no longer deleted when `--color` is left at its default.
- Configuration discovery without a `.git` no longer walks above `$HOME`.
- `--format markdown` summary line no longer loses its package count.
- `update --verify`: reports a missing or source-only distribution as a failure instead of a network skip, keeps pip index and credential settings (only variables that would change resolution are removed), and accepts constraints.

### Security

- HTTP client: responses are capped at 20 MB, each request has a total deadline, and redirects are followed only over https to PyPI hosts.
- `update --verify` never builds source distributions (`--only-binary=:all:`), so no build hook of a new release runs.
- Credentials in index URLs are redacted from parse errors and from `--verify` output, including passwords containing `/`.

---

## [0.1.1] - 2026-08-15

### Changed

- **Impact:** Duplicate declarations of the same package — for example the same distribution
  pulled in via two `-r` includes with different constraints — are now resolved independently
  instead of collapsing to one shared recommendation. A name-level adjustment made during
  conflict resolution only reaches a given declaration's `recommended_version` when a real
  conflict was recorded for that declaration.
- **Impact:** PEP 440 wildcard version bands (`pkg==2.*`) are now parsed leniently, resolving to
  their release-prefix floor. A wildcard-pinned requirement now participates correctly in
  major-boundary and update-availability checks instead of being treated as unparseable.
- `depkeeper check`'s table output changed its status badges from Unicode symbols (`✓`, `⬆`,
  `⚠`, `✗`) to bracketed text labels (`[OK]`, `[OUTDATED]`, `[CONFLICT]`, `[INCOMP]`,
  `[ERROR]`), so the table renders identically regardless of terminal font, and matches
  `--format simple`'s existing label style. Scripts that pattern-match on the old symbols must
  be updated; scripts that already match on `--format json` or `--format simple` are unaffected.
- `tomli` is now used unconditionally for TOML parsing on every supported Python version,
  rather than preferring the standard-library `tomllib` on 3.11+. Configuration parsing behaves
  identically across Python 3.8–3.12.
- A configuration file carrying a leading byte-order mark is now decoded correctly instead of
  failing TOML parsing.

### Fixed

- A `Retry-After` header on a `429` response is now clamped to a maximum of 120 seconds, and
  both the delay-seconds and HTTP-date header forms are parsed correctly, so a misconfigured or
  slow-to-recover upstream cannot stall a run indefinitely.
- The interactive confirmation prompt's `[y/N]` / `[Y/n]` suffix is no longer swallowed by Rich
  markup interpretation.
- `_find_updates` no longer risks pairing a requirement with an unrelated package when the
  parsed requirements and checked packages lists fall out of step; the mismatch is now logged
  and the affected entries are skipped.

---

## [0.1.0]

Initial public release.

### Added — commands

- `depkeeper check [FILE]` — read-only analysis. Options: `--outdated-only`,
  `-f/--format table|simple|json`, `--strict-version-matching`,
  `--check-conflicts/--no-check-conflicts`.
- `depkeeper update [FILE]` — in-place rewriting. Options: `--dry-run`, `-y/--yes`, `--backup`,
  `--pin`, `--allow-hash-removal`, `-p/--packages`, `--strict-version-matching`,
  `--check-conflicts/--no-check-conflicts`.
- Global options `-c/--config`, `-v/--verbose` (repeatable), `--color/--no-color`, `--version`,
  `-h/--help`, with `DEPKEEPER_CONFIG` and `DEPKEEPER_COLOR` environment variables.
- Both `depkeeper` and `python -m depkeeper` entry points.
- Exit codes: `0` success, `1` application error, `2` usage error, `130` interrupted.

### Added — version recommendation

- **Major-version boundary enforcement.** A recommendation never crosses a major version when a
  current version is known — applied at candidate-selection time in three independent places, so
  no code path can circumvent it.
- **Python compatibility filtering** using each release's `requires_python`, evaluated against the
  interpreter running depkeeper. Absent or unparseable metadata is treated as compatible, matching
  pip.
- **Pre-release exclusion** from every candidate list.
- **Current-version inference** from range specifiers (`>=`, `>`, `~=`), disabled by
  `--strict-version-matching`.
- **Constraint preservation.** Only the floor of a requirement is rewritten; upper bounds,
  exclusions and wildcard bands are preserved verbatim and fed back into candidate selection, so
  an unsatisfiable line can never be produced. `>` is widened to `>=`; `~=` keeps the author's
  precision.
- `--pin` to opt into exact `==` pins instead.
- **Convergence.** A target already covered by the declared floor is skipped, making repeated runs
  idempotent.

### Added — conflict resolution

- Iterative cross-package resolution bounded at 100 passes, with two boundary-respecting
  strategies (step the source back; constrain the target) and a "revert both" fallback.
- `ResolutionResult` reporting per-package `original → resolved`, resolution status, cumulative
  conflict records, iteration count and convergence.
- **Invariant:** `Package.recommended_version` always equals the resolver's `resolved` value, so
  the version reported is the version written.
- Advisory compatible alternatives, adopted only where a conflict is still live, computed from a
  single pre-adoption snapshot so the outcome is order-independent.
- Graceful degradation when PyPI metadata is unavailable, with a per-run negative cache that
  prevents retry storms across resolution passes.

### Added — parsing

- PEP 440/508 requirements, extras, environment markers and inline comments.
- `-r`/`--requirement` includes with cycle detection and **per-requirement provenance**, so the
  correct file is rewritten in multi-file projects.
- `-c`/`--constraint` constraint files.
- `-e`/`--editable`, VCS URLs (`git+`, `hg+`, `bzr+`, `svn+`), HTTP(S) URLs, `file://` URIs and
  local paths — reported, never updated.
- `--hash=X` and `--hash X` forms.
- Recognition and skipping of pip global options (`--index-url`, `-i`, `--extra-index-url`,
  `--find-links`, `-f`, `--trusted-host`, `--no-binary`, `--only-binary`, `--use-feature`,
  `--pre`, `--prefer-binary`).
- UTF-8 byte-order-mark handling on read and write.
- Deterministic, source-faithful specifier ordering.

### Added — write safety

- **Two-phase commit.** All affected files are rendered in memory before any is written, with
  rollback of committed files if a later write fails.
- **Atomic replacement** via temporary file, `fsync` and `os.replace`, with file-mode
  preservation, symlink following, directory `fsync` on POSIX, and bounded retries for transient
  Windows lock errors.
- **Byte-preserving output.** Each rewritten line re-attaches its own terminator, so CRLF stays
  CRLF, LF stays LF, and a missing final newline is not added.
- Timestamped backups of every affected file with `--backup`, restored automatically on failure.

### Added — output

- Rich table, line-based simple, and JSON output formats.
- **Stream separation.** Machine-readable formats reserve stdout exclusively for the payload; all
  status messages, warnings and errors go to stderr, so `depkeeper -v check -f json | jq` is
  correct.
- `--format json` always emits a document, including `[]` for an empty result set.
- Per-stream colour detection: a piped stdout does not disable colour on an interactive stderr.

### Added — configuration

- `depkeeper.toml` (`[depkeeper]`) and `pyproject.toml` (`[tool.depkeeper]`) support for
  `check_conflicts` and `strict_version_matching`.
- Strict validation: unknown keys and wrong value types are errors, not warnings.
- Precedence: defaults < configuration file < command-line flag.
- `utf-8-sig` decoding so BOM-carrying configuration files parse.

### Added — performance and reliability

- Shared `PyPIDataStore` guaranteeing at most one PyPI request per package per process, with
  per-key request coalescing and cancellation-safe waiters.
- Async HTTP with HTTP/2, bounded concurrency, exponential backoff with jitter, and separate
  `429` handling that honours `Retry-After`.
- Structured exception hierarchy carrying diagnostic metadata.

### Security

- **Hashed requirements are refused by default.** Updating a `--hash`-pinned requirement requires
  the explicit `--allow-hash-removal` opt-in, preventing silent integrity regressions.
- depkeeper never imports, installs, builds or executes the packages it analyses; it reads JSON
  metadata only.
- HTTPS-only communication with certificate verification always enabled.
- 10 MB input file size limit; path-confinement helper for externally supplied paths.

### Known limitations

Documented in full at
<https://github.com/rahulkaushal04/depkeeper/blob/main/docs/reference/limitations.md>. Most significant:

- Not a substitute for pip's resolver — the transitive dependency graph is not expanded.
- Only `pypi.org` is queried; `--index-url` directives are parsed and ignored.
- Backslash line continuations are not joined, so default `pip-compile --generate-hashes` output
  cannot be parsed.
- `--allow-hash-removal` yields a partially hashed file that `pip --require-hashes` rejects.
- Compatibility filtering uses depkeeper's own interpreter, with no override flag.
- Calendar-versioned packages hit the major-version boundary (`2023.x` never bumps to `2024.x`).

---

[Unreleased]: https://github.com/rahulkaushal04/depkeeper/compare/v0.1.1...main
[0.1.1]: https://github.com/rahulkaushal04/depkeeper/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/rahulkaushal04/depkeeper/releases/tag/v0.1.0
