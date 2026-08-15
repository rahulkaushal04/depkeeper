# Architecture

Contributor-facing map of the codebase: what each module owns, how a request flows through it,
and where to make a given change.

This document is optimised for navigating the source. For the design rationale, concurrency model
and algorithm detail, see the
[architecture deep dive](https://rahulkaushal04.github.io/depkeeper/concepts/architecture/).

---

## Shape of the system

depkeeper is a synchronous CLI wrapped around an asynchronous core. Each command builds an event
loop with `asyncio.run`, performs all network I/O inside it, then returns to synchronous code to
render output or write files.

There is no daemon, no persistent state, no cache directory and no configuration outside the
working directory. A process starts cold and exits cold.

```text
                    ┌──────────────────────────────────────────────┐
   requirements.txt │  cli.py — global options, config, logging    │
        │           └───────────────────┬──────────────────────────┘
        │                               │
        ▼                               ▼
┌───────────────────┐        ┌─────────────────────┐
│ RequirementsParser│        │ commands/check.py   │  read-only
│ core/parser.py    │        │ commands/update.py  │  writes
└─────────┬─────────┘        └──────────┬──────────┘
          │ List[Requirement]           │
          ▼                             ▼
┌───────────────────┐        ┌─────────────────────┐
│ PyPIDataStore     │◄───────┤ VersionChecker      │  per-package target
│ core/data_store.py│        │ core/checker.py     │
└─────────┬─────────┘        └──────────┬──────────┘
          │ cached metadata             │ List[Package]
          │                             ▼
          │              ┌──────────────────────────┐
          └─────────────►│ DependencyAnalyzer       │  cross-package consistency
                         │ core/dependency_analyzer │
                         └──────────┬───────────────┘
                                    │ ResolutionResult
                       ┌────────────┴────────────┐
                       ▼                         ▼
              renderer (table/            writer (two-phase,
              simple/json)                atomic, rollback)
```

---

## Module responsibilities

| Module | Owns | Must not |
|---|---|---|
| `cli.py` | Click group, global options, config loading, logging setup, top-level exit codes | Contain business logic |
| `commands/check.py` | Read-only pipeline, three renderers, stream separation | Write to the filesystem |
| `commands/update.py` | Filtering, update plan, confirmation, two-phase commit, rollback | Recompute recommendations |
| `core/parser.py` | Text → `Requirement`, `-r`/`-c` directives, provenance, BOM handling | Perform network I/O |
| `core/data_store.py` | PyPI metadata cache, request coalescing, concurrency limit | Cache failures |
| `core/checker.py` | Per-package recommendation under boundary/Python/constraint filters | Know about other packages |
| `core/dependency_analyzer.py` | Iterative cross-package resolution, conflict records | Cross a major boundary |
| `models/` | Data + behaviour: version state, status ladder, serialisation, line rendering | Do any I/O |
| `utils/http.py` | Retries, backoff, rate limiting, 429 handling | Know about PyPI schemas |
| `utils/filesystem.py` | Atomic writes, backups, path confinement | Know about requirements syntax |
| `utils/console.py` | Per-stream Rich consoles, tables, prompts | Emit diagnostics (that is `logger`) |
| `utils/naming.py` | PEP 503 canonicalisation — **the** single source of truth | Be reimplemented anywhere else |
| `config.py` | TOML discovery, parsing, strict validation | Read CLI state |
| `constants.py` | Every tunable literal | Contain logic |

### Layering

```text
commands  →  core  →  models  →  utils
    └──────────────────────────────┘
```

Dependencies point rightwards only. `utils` depends on nothing inside depkeeper except
`constants`, `exceptions` and other `utils`.

---

## Request flow

Both commands share stages 1–4.

| # | Stage | Component | Notes |
|---|---|---|---|
| 1 | Parse | `RequirementsParser` | Follows `-r` includes, loads `-c` constraints, records provenance per requirement |
| 2 | Prefetch | `PyPIDataStore.prefetch_packages` | One concurrent burst; one HTTP request per unique package |
| 3 | Recommend | `VersionChecker.check_packages` | Per-package target; served from the prefetch cache |
| 4 | Resolve | `DependencyAnalyzer.resolve_and_annotate_conflicts` | Optional (`--check-conflicts`); mutates `Package` objects in place |
| 5a | Render | `commands/check.py` | `table` / `simple` / `json` |
| 5b | Write | `commands/update.py` | Render all files in memory → commit atomically → roll back on failure |

---

## Key design decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | One `PyPIDataStore`, shared by checker and analyzer | Guarantees one HTTP request per package; makes the analyzer's ≤100 passes nearly free; both components see a consistent snapshot |
| D2 | Per-key in-flight map, not only a semaphore | A semaphore admits *N* coroutines, so "check cache then fetch" inside it is not mutually exclusive. Waiters await the same task via `asyncio.shield` and consume no slot |
| D3 | Major boundary applied at candidate-selection time | Applied in three independent places, so no code path — including the resolver's rescue paths — can produce a cross-major recommendation |
| D4 | Split specifiers into *floor* and *retained* | Only the floor is rewritten; retained specs are fed forward into candidate selection so an unsatisfiable line is never even proposed |
| D5 | Status computed in the model, not the renderer | `get_display_data()` / `get_status_summary()` keep renderers from disagreeing |
| D6 | One Rich `Console` **per stream** | Keeps stdout exclusively for machine-readable payloads; `print_error` defaults to stderr |
| D7 | `Requirement.source_file` provenance | A requirement from `-r included.txt` keeps the included file's line numbers; matching on line number alone would corrupt the parent file |
| D8 | Two-phase commit for multi-file writes | All files render before any is written; a later failure rolls back earlier commits |

Failures are never cached at the data-store level, because `prefetch_packages` swallows errors and
the checker legitimately retries afterwards. Negative caching belongs to the consumer — the
analyzer keeps a per-run set of unreachable names to avoid a retry storm across resolution passes.

---

## Data model

| Type | Represents | Notable fields |
|---|---|---|
| `Requirement` | One line of a requirements file | `specs`, `extras`, `markers`, `url`, `editable`, `hashes`, `comment`, `line_number`, `source_file` (excluded from equality — provenance, not identity) |
| `Package` | A requirement enriched with PyPI metadata and decisions | `current_version`, `latest_version`, `recommended_version`, `conflicts`, `metadata` |
| `Conflict` | One violated dependency requirement | `source_package`, `source_version`, `target_package`, `required_spec`, `conflicting_version` — frozen, so it can be deduplicated |
| `ResolutionResult` | The outcome of resolution | `resolved_versions`, `iterations_used`, `converged`, `packages_with_conflicts` |

**Invariant:** `Package.recommended_version == ResolutionResult.resolved_versions[name].resolved`.
`ResolutionResult` is the single source of truth; the version reported is the version written.

---

## Concurrency and limits

All limits are module constants and are **not** configurable at runtime.

| Bound | Value | Location |
|---|---|---|
| HTTP connections in flight | 10 | `HTTPClient(max_concurrency=…)` |
| Distinct PyPI fetches in flight | 10 | `PyPIDataStore(concurrent_limit=…)` |
| Request timeout | 30 s | `constants.DEFAULT_TIMEOUT` |
| Retries per request | 3 (4 attempts) | `constants.DEFAULT_MAX_RETRIES` |
| `429` retries | 5, honouring `Retry-After` | `HTTPClient._max_429_retries` |
| Resolution passes | 100 | `_MAX_RESOLUTION_ITERATIONS` |
| Source candidates per conflict | 50 | `_MAX_SOURCE_CANDIDATES` |
| Maximum input file size | 10 MB | `constants.MAX_FILE_SIZE` |

The pipeline is single-threaded. Locks in `utils/console.py` and `utils/logger.py` protect
memoised singletons against concurrent first use, not concurrent commands.

`DependencyAnalyzer(concurrent_limit=…)` constructs a semaphore that is currently unused — all its
I/O goes through the data store's limit. Treat the parameter as reserved.

---

## Error propagation

```text
DepKeeperError                    message + structured `details`
├── ParseError                    line_number, line_content, file_path
├── ConfigError                   config_path, option
├── FileOperationError            file_path, operation, original_error
└── NetworkError                  url, status_code, response_body
    └── PyPIError                 package_name
```

- `PyPIError` subclasses `NetworkError`, so one `except NetworkError` covers 404s, timeouts,
  `429` exhaustion and 5xx. Catch the broader class.
- Per-package network failures are **absorbed**: the checker returns an *unavailable stub*, the
  analyzer negatively caches the name, and the run completes. One dead package never aborts a
  report.
- Everything else surfaces at the command boundary, prints via `print_error` (stderr), exits `1`.

---

## Operational characteristics

| Concern | Behaviour |
|---|---|
| **Reliability** | Atomic replace (temp → `fsync` → `os.replace`), mode preservation, symlink following, bounded retries for transient Windows lock errors, two-phase commit with rollback, optional backups. |
| **Scalability** | Cost is one HTTP request per unique package, plus one per `(package, version)` pair during conflict scanning. Bounded at 10 concurrent connections; runtime is network-dominated. `--no-check-conflicts` removes the dominant cost. |
| **Caching** | In-memory, per process. No TTL, no cross-run reuse, no offline mode — correctness over speed, since a stale cache produces a wrong recommendation. |
| **Security** | Never imports, installs, builds or executes analysed packages. HTTPS to `pypi.org` only, verification always on. Outbound data is package names in URLs. See [SECURITY.md](SECURITY.md). |
| **Observability** | Structured exceptions with `details`; `-v`/`-vv` to INFO/DEBUG; all records on stderr under the `depkeeper` logger namespace. |
| **Idempotency** | A rewrite that would produce a byte-identical line is skipped, so repeated runs converge. |

---

## Deliberate omissions

| Not present | Rationale |
|---|---|
| Persistent cache | A stale cache produces wrong recommendations |
| Lock file | depkeeper does not own the environment; `--pin` gives lockfile semantics in place |
| Transitive graph resolution | depkeeper validates what you declared; `pip` resolves |
| Parser plugin system | The parser is intentionally monolithic and pip-shaped |
| Private index support | Only `pypi.org` is queried; `--index-url` lines are parsed and ignored |

Full list with workarounds:
[Known limitations](https://rahulkaushal04.github.io/depkeeper/reference/limitations/).

---

## Where to make a change

| Goal | Start at | Also read |
|---|---|---|
| Add a CLI flag | `commands/check.py` or `commands/update.py` | [Extending](https://rahulkaushal04.github.io/depkeeper/contributing/extending/) |
| Add an output format | `commands/check.py` renderers | D5, D6 above |
| Change which version is chosen | `core/checker.py` | [Version recommendation](https://rahulkaushal04.github.io/depkeeper/concepts/version-recommendation/) |
| Change conflict behaviour | `core/dependency_analyzer.py` | [Conflict resolution](https://rahulkaushal04.github.io/depkeeper/concepts/conflict-resolution/) |
| Accept new requirements syntax | `core/parser.py`, `constants.py` | [Requirements parsing](https://rahulkaushal04.github.io/depkeeper/concepts/requirements-parsing/) |
| Change how files are written | `commands/update.py`, `utils/filesystem.py` | [Write safety](https://rahulkaushal04.github.io/depkeeper/concepts/write-safety/) |
| Add a config key | `config.py`, `constants.py` | [Configuration options](https://rahulkaushal04.github.io/depkeeper/reference/configuration-options/) |
| Change network behaviour | `utils/http.py` | [Operations](https://rahulkaushal04.github.io/depkeeper/guides/operations/) |

Before changing anything under `core/`, read the
[invariants](CONTRIBUTING.md#invariants-you-must-not-break).
