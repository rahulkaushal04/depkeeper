---
title: Known Limitations
description: Documented behaviours that are surprising, constrained or not yet implemented in 0.1.x
---

# Known Limitations

Every entry here is verified against the 0.1.x implementation. They are documented rather than
hidden, because each one has bitten someone and each has a workaround.

---

## Scope

### depkeeper is not a dependency resolver

It cross-validates the packages **you declared** against each other, using the direct
`requires_dist` of the proposed versions. It does not expand the transitive graph. A plan that
looks clean can still fail `pip install`. `update --verify` asks pip's resolver about the final plan (including transitive dependencies) before anything is written, but it is skipped with a warning when pip is missing/older than 22.2, offline, or the release is source-only, and it never builds sdists.

Transitive conflicts and conflicts through extras are therefore **not detected** by `check` or by
the update plan. For example, `celery[redis]` 5.7.0 together with `redis==4.6.0` passes `check`,
but `update --verify` aborts because `kombu[redis]` (pulled in by the extra) is incompatible with
that `redis`. `update --verify` is the safeguard.

**Workaround:** use `update --verify`, and always run `pip install -r requirements.txt` and your test suite after an update.
In automated pipelines this step is mandatory.

### Only `pypi.org` is queried

`--index-url`, `--extra-index-url`, `-i` and `--find-links` lines are recognised and ignored.
Packages published only to a private index cannot be looked up: they are reported as `no-update` / `could not be checked` and make the run exit `4`.

**Workaround:** none in 0.1.x. Split private packages into a separate file that you do not run
depkeeper against, or use `--ignore` / the `ignore` config key for them.

### Supported file formats

`requirements*.txt`, `pyproject.toml` (PEP 621, PEP 735, build-system, Poetry) and conda
`environment.yml`. Not supported: `Pipfile`, `poetry.lock`, `setup.py`, `setup.cfg`.

### No security advisory scanning

depkeeper reports version drift, not vulnerabilities. Use `pip-audit` or `safety` alongside it.

---

## Version selection

### Calendar versioning heuristics

Calver packages (such as `certifi 2023.7.22`) are detected automatically and updated across years;
the change is labelled `year`. Detection is heuristic (it reads the latest releases, so a semver project whose major reaches 18+
with minors of 12 or less can look like calver): force it with `versioning = "calver"` (or
`"semver"`) per package. A calver `year` counts as `minor` for gating (`--fail-on`, `--max-update`).

**Workaround:** leave date-versioned packages unversioned so there is no anchor, or bump the pin
by hand.

### Major upgrades are opt-in

`django>=3.2,<5.0` anchors on major `3`, so depkeeper stays on the newest `3.x` even though your
range permits `4.x`. The newer major is reported as `major available`, never applied by default.

**Workaround:** opt in per package with `--allow-major django` (or `allow_major = true` in the package
policy). depkeeper then moves to the newest `4.x`; your own upper bound (`<5.0`) is never violated, and
`--max-update` still caps the result. Run `update --verify` and your tests afterwards.

### Target Python defaults to the running interpreter

Without `--python-version`, a `python_version` config key, or a `requires-python` /
conda `python=` declaration in the file, compatibility filtering uses the interpreter
**depkeeper runs on**.

**Fix:** pass `--python-version 3.9` (or set `python_version`), or install depkeeper into the
project's environment.

### Pre-releases are opt-in per package

Pre-releases are excluded from candidate lists and from the reported `latest` by default. There is no global `--pre` flag, and a `--pre` line in the requirements file has no effect on depkeeper. To consider pre-releases for one package, set `allow_prerelease = true` in `[depkeeper.packages.<name>]`. Releases whose files are all yanked on PyPI are never recommended.

### `requires_python` is read from one file per release

The value is taken from the first uploaded file of a release that declares it. A release whose
wheels and sdist disagree may be evaluated against either.

---

## Reporting inconsistencies

### Unversioned requirements report as `OK`

A requirement with no specifier has no current version, so `has_update()` is false and the table
renderer falls through to its up-to-date branch: `[OK]`. The machine formats correctly report
`install`, and `update` **does** add a pin.

**Workaround:** trust `--format json` / `--format simple`; give every requirement at least a
floor.

### Conflict lists are cumulative

`conflicts` (JSON), the `Conflicts` column and `packages_with_conflicts` include conflicts that a
later resolution pass resolved. They are an audit trail, not a list of live problems.

The applied version is always correct — the [result invariant](../concepts/conflict-resolution.md#result-invariant)
guarantees it. Only the annotation is historical.

### The simple format's arrow points at `latest`

`[OUTDATED] flask 2.0 → 3.1.3 (recommended: 2.2.5)` — the arrow target is not the version that
will be written. The parenthesised recommendation is.

---

## Update behaviour

### Conflict resolution can lower a declared floor

To make a set self-consistent, the resolver can constrain a package below the floor you wrote:
`flask>=2.3,<3.0` becomes `flask>=2.2.5,<3.0`. The retained cap is still honoured, and the change
is visible in the plan as a `downgrade`, but it does relax a constraint you chose.

**Workaround:** review downgrades; prefer fixing the other side of the conflict.

### `--allow-hash-removal` produces a partially hashed file

Only the lines that change lose their digests. `pip install --require-hashes` rejects a file in
which some requirements have hashes and others do not.

**Workaround:** regenerate hashes afterwards with `pip-compile --generate-hashes` or `hashin`.

### Hashes are only refreshed on request

Backslash-continued files (`pip-compile --generate-hashes`) are parsed. Updating a hashed
requirement is refused unless you pass `--refresh-hashes` (regenerate sha256 hashes for the new
version) or `--allow-hash-removal` (drop them).

### URL package-name inference is unreliable

Without `#egg=`, the name is taken from the URL's last path segment. A bare wheel URL yields a
name such as `rich-13-7-1-py3-none-any-whl`.

**Workaround:** always add `#egg=<name>`.

### Direct references are never updated

VCS, URL, local-path and editable requirements are reported but never modified — they are pinned
to a source, not to a PyPI version.

### `update` writes files you did not name

`-r` includes are followed and rewritten. `--backup` covers them; `--dry-run` reveals them.

### A cap-only requirement gains an unnormalised floor

`pkg<3.0` with target `2.32.3` becomes `pkg<3.0,>=2.32.3`. The specifier order is source order,
not canonical order.

### Inline comments are preserved but never updated

A comment explaining a cap survives verbatim and can become misleading after the version moves.

---

## Operational

### No persistent cache

Every invocation refetches all metadata. There is no cache directory, TTL or offline mode.

### No runtime tuning

Timeouts, retry counts, concurrency limits, the resolution iteration budget and the candidate
budget are module constants. They cannot be changed from the CLI, a config file or an environment
variable.

**Workaround:** use the [Python API](python-api.md) and construct `HTTPClient` /
`PyPIDataStore` yourself.

### Conflict check can be partial

When PyPI is partly unreachable, a package's dependency metadata may be missing during conflict
resolution. depkeeper reports this (`Conflict check incomplete: ...` on stderr,
`summary.conflict_check_complete: false` in `json-v2`) but still prints the recommendations it
could compute. The HTTP client's circuit breaker is per host: 3 consecutive connection failures
to `pypi.org` stop requests to it for 30 s, then one probe decides whether to resume.

### No file locking

depkeeper reads once and writes once. If a file changes between those points the run fails
(`<path> was modified while depkeeper was running`) rather than overwriting it, but there is no lock
against writers in the same instant.

### A failure mid-way through a multi-file commit

Each file is replaced atomically and a failed or Ctrl-C-interrupted batch restores the files already
written. If a restore itself fails depkeeper reports `Could not restore <path>`; use `--backup` for
multi-file updates.

### Discovery is not recursive

`depkeeper.toml` / `pyproject.toml` are looked for in the current directory and then in parent
directories up to the repository root (the first directory containing `.git`; without a `.git`, never above your home directory).

**Workaround:** pass `--config`, or run from the directory containing the file.

### `update --strict-version-matching` has no negative form

If a configuration file enables `strict_version_matching`, `update` cannot disable it for one invocation (`check` has `--no-strict-version-matching`).

**Workaround:** point `--config` at a different file.

### `DependencyAnalyzer(concurrent_limit=...)` is inert

The parameter constructs a semaphore that is not currently used; all I/O goes through the data
store's own limit. Treat it as reserved.

---

## Reporting

If a limitation here blocks you, or you find one that is not listed, open an issue at
[github.com/rahulkaushal04/depkeeper/issues](https://github.com/rahulkaushal04/depkeeper/issues)
with a minimal reproducer and the output of `depkeeper -vv <command>`.
