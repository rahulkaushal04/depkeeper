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

### Planned

- Security advisory scanning against a vulnerability database
- Configurable package index for private repositories
- A flag to override the target Python version used for compatibility filtering
- Backslash line-continuation support in the parser

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
<https://rahulkaushal04.github.io/depkeeper/reference/limitations/>. Most significant:

- Not a substitute for pip's resolver — the transitive dependency graph is not expanded.
- Only `pypi.org` is queried; `--index-url` directives are parsed and ignored.
- Backslash line continuations are not joined, so default `pip-compile --generate-hashes` output
  cannot be parsed.
- `--allow-hash-removal` yields a partially hashed file that `pip --require-hashes` rejects.
- Compatibility filtering uses depkeeper's own interpreter, with no override flag.
- Calendar-versioned packages hit the major-version boundary (`2023.x` never bumps to `2024.x`).

---

[Unreleased]: https://github.com/rahulkaushal04/depkeeper/compare/v0.1.0...main
[0.1.0]: https://github.com/rahulkaushal04/depkeeper/releases/tag/v0.1.0
