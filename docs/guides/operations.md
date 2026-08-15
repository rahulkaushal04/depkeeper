---
title: Operations
description: Networking, retries, caching, performance, security posture, logging and diagnostics
---

# Operations

Everything an operator needs to run depkeeper predictably in a controlled environment.

---

## Network requirements

| Item | Value |
|---|---|
| Endpoint | `https://pypi.org/pypi/{package}/json` and `https://pypi.org/pypi/{package}/{version}/json` |
| Protocol | HTTPS, HTTP/2 enabled, redirects followed |
| User-Agent | `depkeeper/{version} (https://github.com/rahulkaushal04/depkeeper)` |
| Timeout | 30 s per request |
| Authentication | None. Only public PyPI metadata is read. |
| Outbound data | The package **names** in your requirements file, as URL path segments. Nothing else leaves the machine. |

depkeeper has **no offline mode**. With no egress, every package becomes an unavailable stub and
the report contains only `[ERROR]` rows.

### Only pypi.org is queried

`--index-url`, `--extra-index-url`, `-i` and `--find-links` lines in a requirements file are
recognised and **ignored**. Packages published only to a private index will always report as
unavailable. There is no configuration to point depkeeper at another index in 0.1.x. See
[Limitations](../reference/limitations.md#only-pypiorg-is-queried).

### TLS and proxies

depkeeper uses `httpx`, which honours the standard environment variables:

```bash
export HTTPS_PROXY=http://proxy.internal:3128
export SSL_CERT_FILE=/etc/ssl/certs/corporate-ca.pem   # or REQUESTS_CA_BUNDLE
```

Certificate verification is enabled and there is no CLI flag to disable it. If your environment
performs TLS interception, install the corporate CA into the trust store or point
`SSL_CERT_FILE` at it. Symptoms of a missing CA are `NetworkError` for every package.

---

## Retry and backoff policy

Defined in exactly one place, `HTTPClient._request_with_retry`.

| Response | Behaviour |
|---|---|
| `2xx` | Returned. |
| `404` | `PyPIError` immediately. **Not retried** — the answer will not change. |
| Other `4xx` | `NetworkError` immediately. Not retried. |
| `429` | Sleeps for `Retry-After` seconds (default 1) and retries, up to 5 times. |
| `5xx` | Retried with exponential backoff. |
| Timeout | Retried with exponential backoff. |
| Connection/network error | Retried with exponential backoff. |

- Backoff schedule: `2**attempt + jitter(0.0–0.3)` seconds — approximately 1 s, 2 s, 4 s.
- Retry budget: `DEFAULT_MAX_RETRIES = 3`, so **4 attempts** total per request.
- A `429` retry also consumes one of the outer attempts; the two budgets are not independent.
- Exhausting the budget raises
  `NetworkError: Request failed after 4 attempts: <url>`.

Worst case per package with total failure: roughly 4 × 30 s of timeout plus ~7 s of backoff.
Requests for distinct packages proceed concurrently, so a whole-file failure is not the sum of
these.

### Rate limiting

`HTTPClient` supports a minimum inter-request delay (`rate_limit_delay`), implemented by
reserving the next slot under a lock before sleeping, so concurrent callers queue into distinct
slots. **The CLI constructs the client with the delay disabled (`0.0`)**; the parameter is
available only to programmatic users. Concurrency, not pacing, is what bounds the CLI's request
rate.

---

## Caching

depkeeper's cache is **per process and in memory only**.

| Cache | Key | Lifetime |
|---|---|---|
| Package metadata | canonical package name | one command invocation |
| Per-version dependencies | `name==version` | one command invocation |
| Analyzer negative cache | canonical name of an unreachable package | one command invocation |

There is no cache directory, no TTL and no cross-run reuse. Two consecutive `depkeeper check`
runs issue the same requests. This is a deliberate correctness-over-speed choice: a stale cache
produces a wrong recommendation, which is worse than a slow one.

Within a run, each package is fetched **at most once**, guaranteed by per-key request coalescing
rather than by a semaphore alone. Concurrent callers for the same package await the same task; a
cancelled waiter neither cancels the shared fetch nor strands the others.

Failures are never cached at the data-store level, so a transient error remains recoverable
within the same run. The analyzer keeps its own negative cache to avoid a retry storm across up
to 100 resolution passes.

---

## Performance

### Cost model

| Phase | Requests |
|---|---|
| Prefetch | 1 per unique package |
| Version check | 0 (served from the prefetch cache) |
| Conflict scan | 1 per `(package, proposed version)` not already cached |
| Resolution search | up to 50 per conflict, cached thereafter |

Runtime is dominated by network round-trips, bounded by 10 concurrent connections. depkeeper's
own computation is negligible for realistic file sizes.

### Levers

| Lever | Effect |
|---|---|
| `--no-check-conflicts` | Removes the entire resolution phase. Usually the largest single win. |
| `--packages` | Does **not** reduce requests — filtering happens after resolution. |
| Smaller files | Fewer packages, fewer requests. `-r` includes count toward the total. |
| Splitting one large file | Only helps if you also stop checking the parts you do not need. |

### Tuning and limits

All limits are module constants and are **not** configurable at runtime in 0.1.x:

| Constant | Value | Module |
|---|---|---|
| `DEFAULT_TIMEOUT` | 30 s | `constants` |
| `DEFAULT_MAX_RETRIES` | 3 | `constants` |
| `MAX_FILE_SIZE` | 10 MB | `constants` |
| `HTTPClient.max_concurrency` | 10 | `utils.http` |
| `PyPIDataStore.concurrent_limit` | 10 | `core.data_store` |
| `_MAX_RESOLUTION_ITERATIONS` | 100 | `core.dependency_analyzer` |
| `_MAX_SOURCE_CANDIDATES` | 50 | `core.dependency_analyzer` |
| `HTTPClient._max_429_retries` | 5 | `utils.http` |

Programmatic users can override the HTTP and data-store limits by constructing those objects
themselves — see [Python API](../reference/python-api.md).

---

## Security posture

| Property | Behaviour |
|---|---|
| Code execution | depkeeper **never imports, installs, builds or executes** the packages it analyses. It reads JSON metadata only. |
| Credentials | None are read, stored or transmitted. |
| Network destination | `pypi.org` only, over TLS with verification enabled. |
| Data exfiltration surface | Package names appear in request URLs. Versions, comments and file contents do not leave the machine. |
| File writes | Only the requirements files reached from the file you named, plus optional backups beside them. |
| Path traversal | `validate_path` can confine a resolved path to a base directory; used for externally supplied values. |
| Symlinks | The write path follows symlinks and replaces the **target**, not the link. |
| File modes | Preserved across an atomic replace (`shutil.copymode`); temporary files are created `0600`. |
| Hash integrity | Updates that would strip `--hash` entries are refused unless `--allow-hash-removal` is passed explicitly. |
| Input size limit | 10 MB per file, to bound memory on hostile or accidental input. |
| Untrusted input | The parser is the only component that consumes untrusted text. It performs no `eval`, no shell invocation and no path writes. |

!!! warning "Running depkeeper on an untrusted repository"

    `update` writes to every file reachable through `-r` includes, and include paths are resolved
    relative to the including file — including `../` segments. A hostile requirements file can
    therefore direct writes outside the directory you invoked depkeeper in. Run `--dry-run` first,
    or run in a container with only the project directory mounted.

Vulnerability reporting: [Security policy](../community/security.md).

---

## Logging and diagnostics

### Levels

| Invocation | Level | Content |
|---|---|---|
| *(default)* | `WARNING` | Unavailable packages, unresolved conflicts, stalled resolution, skipped targets, rate limiting. |
| `-v` | `INFO` | Phase progress, per-package resolution decisions, adopted alternatives, backups created, rollbacks. |
| `-vv` | `DEBUG` | Cache behaviour, per-candidate decisions, HTTP retries, per-line rewrites, effective configuration. |

All log records go to **stderr**. Format: `LEVELNAME: message`. ANSI colour is applied only when
stderr is a TTY and neither `NO_COLOR` nor `CI` is set.

### Capturing a diagnostic bundle

```bash
depkeeper -vv check --format json > report.json 2> depkeeper-debug.log
```

Attach both files to a bug report, together with the requirements file, `depkeeper --version` and
`python --version`.

### Logger hierarchy

Loggers live under the `depkeeper` namespace (`depkeeper.parser`, `depkeeper.http`,
`depkeeper.data_store`, `depkeeper.dependency_analyzer`, `depkeeper.commands.update`, …).

!!! note "`setup_logging` reconfigures the process"

    It clears handlers on the `depkeeper` logger, installs its own, and sets `propagate = False`.
    Embedding depkeeper in a larger application means its log records will **not** reach your root
    logger unless you reconfigure that logger afterwards. Test suites must snapshot and restore
    the logger's handlers, level and `propagate` flag — see [Testing](../contributing/testing.md#logging-isolation).

---

## Health checks

A minimal liveness check for an environment that will run depkeeper:

```bash
printf 'requests==2.28.0\n' > /tmp/dk-probe.txt
depkeeper check /tmp/dk-probe.txt --format json --no-check-conflicts | jq -e 'length == 1'
```

Exit code `0` confirms: the binary runs, the parser works, egress to PyPI works, TLS verifies, and
JSON rendering is intact.

---

## Deployment recommendations

| Recommendation | Reason |
|---|---|
| Pin the depkeeper version everywhere. | Recommendation logic is behaviour; an upgrade can change verdicts. |
| Run on the interpreter your project targets. | Compatibility filtering uses depkeeper's own interpreter. |
| Set `NO_COLOR=1` in non-interactive contexts. | Removes ANSI from captured logs. |
| Redirect stderr to a file in automation. | Keeps stdout parseable and preserves diagnostics for failures. |
| Use `--no-check-conflicts` for pure reports. | Substantially fewer PyPI requests. |
| Always run `pip install` + tests after an automated `update`. | depkeeper does not resolve the transitive graph. |
| Never grant write access to more than the project directory. | `-r` includes can direct writes elsewhere. |
| Stagger scheduled jobs across repositories. | Avoids `429` from a shared egress IP. |
