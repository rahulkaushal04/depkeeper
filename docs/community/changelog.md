---
title: Changelog
description: Version history and behavioural changes for depkeeper
---

# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). depkeeper follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

!!! note "Recommendation logic is a behavioural contract"

    A change that makes the same requirements file produce a different update plan is at minimum
    a minor release. Entries that alter recommendations are marked **Impact** so consumers gating
    pipelines on the output know what to re-verify.

---

## Unreleased

### Planned

- Security advisory scanning against a vulnerability database
- Configurable package index for private repositories
- A flag to override the target Python version used for compatibility filtering
- Joining backslash line continuations in the parser

---

## 0.1.0

Initial release.

### Added — commands

- `depkeeper check [FILE]` — read-only analysis with `--outdated-only`,
  `--format table|simple|json`, `--strict-version-matching` and
  `--check-conflicts/--no-check-conflicts`.
- `depkeeper update [FILE]` — in-place rewriting with `--dry-run`, `--yes`, `--backup`, `--pin`,
  `--allow-hash-removal`, `--packages/-p`, `--strict-version-matching` and
  `--check-conflicts/--no-check-conflicts`.
- Global options `--config/-c`, `--verbose/-v`, `--color/--no-color`, `--version`, `--help`, with
  the `DEPKEEPER_CONFIG` and `DEPKEEPER_COLOR` environment variables.
- Both `depkeeper` and `python -m depkeeper` entry points.

### Added — version recommendation

- Strict major-version boundary enforcement: a recommendation never crosses a major version when
  a current version is known.
- Python compatibility filtering using each release's `requires_python`, evaluated against the
  interpreter running depkeeper.
- Pre-release exclusion.
- Current-version inference from range specifiers (`>=`, `>`, `~=`), disabled by
  `--strict-version-matching`.
- Constraint preservation: only the floor of a requirement is rewritten; upper bounds, exclusions
  and wildcard bands are preserved verbatim and are fed back into candidate selection so an
  unsatisfiable line can never be produced.
- `--pin` to opt into exact `==` pins.
- Convergence: a target already covered by the declared floor is skipped, making repeated runs
  idempotent.

### Added — conflict resolution

- Iterative cross-package resolution bounded at 100 passes, with two boundary-respecting
  strategies (step the source back; constrain the target) and a "revert both" fallback.
- `ResolutionResult` with per-package `original → resolved` details, statuses, cumulative conflict
  records and convergence statistics.
- Invariant: `Package.recommended_version` always equals the resolver's `resolved` value, so the
  version reported is the version written.
- Advisory compatible alternatives, adopted only where a conflict is still live.
- Graceful degradation when PyPI metadata is unavailable, with a per-run negative cache to prevent
  retry storms.

### Added — parsing

- PEP 440/508 requirements, extras, environment markers and inline comments.
- `-r`/`--requirement` includes with cycle detection and per-requirement provenance, so the
  correct file is rewritten.
- `-c`/`--constraint` constraint files.
- `-e`/`--editable`, VCS URLs, HTTP(S) URLs, `file://` URIs and local paths — reported, never
  updated.
- `--hash=X` and `--hash X` forms.
- Recognition and skipping of pip global options (`--index-url`, `-i`, `--extra-index-url`,
  `--find-links`, `-f`, `--trusted-host`, `--no-binary`, `--only-binary`, `--use-feature`,
  `--pre`, `--prefer-binary`).
- UTF-8 byte-order-mark handling on read and write.
- Deterministic, source-faithful specifier ordering.

### Added — write safety

- Two-phase commit: all affected files are rendered in memory before any is written, with
  rollback of committed files if a later write fails.
- Atomic replacement via temporary file, `fsync` and `os.replace`, with mode preservation,
  symlink following, directory `fsync` on POSIX and bounded retries for transient Windows lock
  errors.
- Byte-preserving line endings and per-line terminators.
- Timestamped backups of every affected file with `--backup`, restored automatically on failure.
- Hashed requirements refused by default to prevent silent integrity regressions.

### Added — output

- Rich table, line-based simple and JSON output formats.
- Stream separation: machine-readable formats keep stdout exclusively for the payload, with all
  status output, warnings and errors on stderr, so `depkeeper -v check -f json | jq` works.
- `--format json` always emits a document, `[]` included.
- Per-stream colour detection.

### Added — configuration

- `depkeeper.toml` (`[depkeeper]`) and `pyproject.toml` (`[tool.depkeeper]`) support for
  `check_conflicts` and `strict_version_matching`.
- Strict validation: unknown keys and wrong types are errors.
- Precedence: defaults < configuration file < command-line flag.

### Added — performance and reliability

- Shared `PyPIDataStore` guaranteeing at most one PyPI request per package per process, with
  per-key request coalescing and cancellation-safe waiters.
- Async HTTP with HTTP/2, bounded concurrency, exponential backoff with jitter, and separate
  `429` handling that honours `Retry-After`.
- Structured exception hierarchy with diagnostic metadata.

### Known limitations

Documented in [Known limitations](../reference/limitations.md). The most significant:

- Not a substitute for `pip`'s resolver — the transitive graph is not expanded.
- Only `pypi.org` is queried.
- Backslash line continuations are not parsed.
- `--allow-hash-removal` yields a partially hashed file.
- Compatibility filtering uses depkeeper's own interpreter, with no override.
