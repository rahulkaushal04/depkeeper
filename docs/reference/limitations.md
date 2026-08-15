---
title: Known Limitations
description: Documented behaviours that are surprising, constrained or not yet implemented in 0.1.0
---

# Known Limitations

Every entry here is verified against the 0.1.0 implementation. They are documented rather than
hidden, because each one has bitten someone and each has a workaround.

---

## Scope

### depkeeper is not a dependency resolver

It cross-validates the packages **you declared** against each other, using the direct
`requires_dist` of the proposed versions. It does not expand the transitive graph. A plan that
looks clean can still fail `pip install`.

**Workaround:** always run `pip install -r requirements.txt` and your test suite after an update.
In automated pipelines this step is mandatory.

### Only `pypi.org` is queried

`--index-url`, `--extra-index-url`, `-i` and `--find-links` lines are recognised and ignored.
Packages published only to a private index always report as `✗ ERROR`.

**Workaround:** none in 0.1.0. Split private packages into a separate file that you do not run
depkeeper against, or accept the error rows.

### Only pip requirements files are supported

No `pyproject.toml` dependency tables, `Pipfile`, `poetry.lock`, `setup.py` or `setup.cfg`. The
parser is intentionally monolithic and pip-shaped; there is no format plugin system.

### No security advisory scanning

depkeeper reports version drift, not vulnerabilities. Use `pip-audit` or `safety` alongside it.

---

## Version selection

### Calendar versioning hits the major boundary

The boundary rule compares `release[0]`, so for `certifi 2023.7.22` the "major" is `2023` and
`2024.x` is a boundary crossing that will never be proposed.

**Workaround:** leave date-versioned packages unversioned so there is no anchor, or bump the pin
by hand.

### An inferred floor caps the upgrade inside your own range

`django>=3.2,<5.0` anchors on major `3`, so depkeeper caps at the newest `3.x` even though your
range permits `4.x`.

**Workaround:** raise the floor yourself (`django>=4.2,<5.0`) and let depkeeper continue from
there. Major upgrades are a deliberate human decision.

### No target-Python override

Compatibility filtering uses the interpreter **depkeeper runs on**, not the interpreter your
project targets. There is no flag to change this.

**Workaround:** install depkeeper into the project's environment, or
`pipx install --python python3.12 depkeeper`.

### No pre-release support

Pre-releases are excluded from every candidate list, and there is no `--pre` flag. A `--pre` line
in the requirements file has no effect on depkeeper.

### `requires_python` is read from one file per release

The value is taken from the first uploaded file of a release that declares it. A release whose
wheels and sdist disagree may be evaluated against either.

---

## Reporting inconsistencies

### Unversioned requirements report as `OK`

A requirement with no specifier has no current version, so `has_update()` is false and the table
renderer falls through to its up-to-date branch: `✓ OK`. The machine formats correctly report
`install`, and `update` **does** add a pin.

**Workaround:** trust `--format json` / `--format simple`; give every requirement at least a
floor.

### Unavailable packages look up to date in JSON

With conflict checking enabled (the default), the resolver seeds its update set with
`recommended_version or current_version`, so an unavailable stub acquires a recommendation equal
to its current version and serialises as `"status": "latest"` with no `error` field.

**Workaround:** detect unreachable packages with `--no-check-conflicts`, which yields
`"status": "no-update"` plus `"error": "Package information unavailable"`, or key on the `error`
field.

### Conflict lists are cumulative

`conflicts` (JSON), the `Conflicts` column and `packages_with_conflicts` include conflicts that a
later resolution pass resolved. They are an audit trail, not a list of live problems.

The applied version is always correct — the [result invariant](../concepts/conflict-resolution.md#result-invariant)
guarantees it. Only the annotation is historical.

### `Python Requires` can be stale after resolution

The update plan's `Python Requires` column shows the `requires_python` recorded for the version
the **checker** proposed. If the resolver subsequently moved the package, the column is not
refreshed.

**Workaround:** verify with `pip install`.

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

### Backslash line continuations are not joined

The default output of `pip-compile --generate-hashes` wraps hashes onto continuation lines and is
therefore unparseable.

**Workaround:** use single-line hash form, or do not run depkeeper against generated hash files.

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

### No file locking

depkeeper reads once and writes once. A concurrent edit between those points is lost.

### `Ctrl+C` during a multi-file commit skips rollback

Each individual file is atomic, but a batch interrupted between commits is not rolled back.

**Workaround:** use `--backup` for multi-file updates.

### Discovery is not recursive

`depkeeper.toml` / `pyproject.toml` are looked for in the current working directory only; parent
directories are not searched.

**Workaround:** pass `--config`, or run from the directory containing the file.

### `--strict-version-matching` has no negative form

If a configuration file enables it, it cannot be disabled for a single invocation.

**Workaround:** point `--config` at a different file.

### `DependencyAnalyzer(concurrent_limit=...)` is inert

The parameter constructs a semaphore that is not currently used; all I/O goes through the data
store's own limit. Treat it as reserved.

---

## Reporting

If a limitation here blocks you, or you find one that is not listed, open an issue at
[github.com/rahulkaushal04/depkeeper/issues](https://github.com/rahulkaushal04/depkeeper/issues)
with a minimal reproducer and the output of `depkeeper -vv <command>`.
