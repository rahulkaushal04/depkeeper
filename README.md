# depkeeper

[![Tests](https://github.com/rahulkaushal04/depkeeper/actions/workflows/tests.yml/badge.svg)](https://github.com/rahulkaushal04/depkeeper/actions/workflows/tests.yml)
[![Coverage](https://codecov.io/gh/rahulkaushal04/depkeeper/branch/main/graph/badge.svg)](https://codecov.io/gh/rahulkaushal04/depkeeper)
[![PyPI](https://img.shields.io/pypi/v/depkeeper.svg)](https://pypi.org/project/depkeeper/)
[![Python versions](https://img.shields.io/pypi/pyversions/depkeeper.svg)](https://pypi.org/project/depkeeper/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-github.io-blue)](https://rahulkaushal04.github.io/depkeeper/)

**Safe, conflict-aware dependency updates for pip requirements files.**

depkeeper analyses `requirements.txt`-style files, computes a safe upgrade target for every
requirement, cross-validates those targets against each other, and rewrites the file in place —
without discarding the constraints you authored.

It is a single-purpose CLI. It does not manage virtual environments, install packages, replace
`pip`, or introduce a lock file format.

---

## Contents

- [Why depkeeper](#why-depkeeper) · [What it guarantees](#what-it-guarantees)
- [Install](#install) · [Quick start](#quick-start) · [Commands](#commands)
- [Configuration](#configuration) · [Common workflows](#common-workflows)
- [Architecture](#architecture) · [Limitations](#limitations)
- [Troubleshooting](#troubleshooting) · [Documentation](#documentation) · [Contributing](#contributing)

---

## Why depkeeper

`pip list --outdated` reports the **latest** version, which is frequently a major release that
will break your build. Lock-file tools solve this properly but require adopting a new workflow and
file format.

depkeeper fills the gap. It answers one question, precisely:

> What is the largest upgrade I can take for each requirement **without** crossing a major
> version, **without** breaking Python compatibility, **without** violating the constraints I
> declared, and **without** conflicting with the other packages in my file?

Then it applies the answer to the file you already have.

|  | pip | pip-tools | Poetry | depkeeper |
|---|---|---|---|---|
| Reports available updates | latest only | no | yes | yes, with a *safe* target |
| Enforces major-version boundaries | no | no | no | **yes** |
| Preserves your declared ranges on write | n/a | regenerates | rewrites | **yes** |
| Full transitive resolution | at install time | yes | yes | no — see [Limitations](#limitations) |
| Requires a new file format | no | `.in` files | `pyproject.toml` + lock | **no** |

---

## What it guarantees

These are enforced in code, not advisory:

| Guarantee | Meaning |
|---|---|
| **Major-version boundary** | A package on `1.x` is never moved to `2.x`. |
| **Python compatibility** | Releases whose `requires_python` excludes your interpreter are never proposed. |
| **Constraint preservation** | Upper bounds, exclusions and `~=` bands are preserved verbatim and never violated. |
| **No pre-releases** | Alpha/beta/rc versions are excluded from every candidate list. |
| **Atomic, reversible writes** | Multi-file updates are all-or-nothing, with rollback and optional backups. |
| **Hash integrity** | Updates that would strip `--hash` entries are refused unless explicitly allowed. |
| **Clean stdout** | `--format json` puts the payload on stdout and every diagnostic on stderr. |
| **Idempotency** | Re-running produces no change. Safe to run on a schedule. |

The trade-off is explicit: depkeeper is deliberately conservative. It will never propose the major
upgrade you eventually need.

---

## Install

```bash
python -m pip install depkeeper     # into the project's environment (recommended)
pipx install depkeeper              # isolated global tool
```

Requires **Python 3.8+**.

> [!IMPORTANT]
> depkeeper filters candidate versions against **the interpreter it runs on**, not your project's.
> Installing it on 3.8 while your service targets 3.12 makes recommendations silently
> conservative. Install it into the project environment, or use
> `pipx install --python python3.12 depkeeper`.

Verify:

```bash
depkeeper --version        # depkeeper 0.1.0
python -m depkeeper --help # equivalent module entry point
```

---

## Quick start

Given this file:

```text
requests==2.28.0
flask>=2.0,<2.3
celery[redis]>=5.0,<6.0
click~=8.0
certifi
urllib3==1.26.0
```

**1. Inspect (read-only, never writes):**

```console
$ depkeeper check
┏━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃   Status   ┃ Package  ┃ Current ┃  Latest   ┃ Recommended ┃ Update Type ┃ Conflicts ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ [OUTDATED] │ requests │ 2.28.0  │  2.34.2   │   2.34.2    │    minor    │ -         │
│ [OUTDATED] │ flask    │   2.0   │   3.1.3   │    2.2.5    │    minor    │ -         │
│ [OUTDATED] │ celery   │   5.0   │   5.6.3   │    5.6.3    │    minor    │ -         │
│ [OUTDATED] │ click    │   8.0   │   8.4.2   │    8.4.2    │    minor    │ -         │
│    [OK]    │ certifi  │    -    │ 2026.7.22 │      -      │      -      │ -         │
│ [OUTDATED] │ urllib3  │ 1.26.0  │   2.7.0   │   1.26.20   │    patch    │ -         │
└────────────┴──────────┴─────────┴───────────┴─────────────┴─────────────┴───────────┘
[WARNING] 5 package(s) have updates available
```

**2. Preview the exact write:**

```bash
depkeeper update --dry-run
```

**3. Apply:**

```console
$ depkeeper update --backup
Update 6 packages? (y, n) [y]: y
[OK] ✓ Successfully updated 6 package(s)
```

```text
requests==2.34.2
flask>=2.2.5,<2.3          # your <2.3 cap held — latest is 3.1.3
celery[redis]>=5.6.3,<6.0  # extra and upper bound preserved
click~=8.4                 # compatible-release form preserved
certifi==2026.7.22         # unversioned requirement gained a pin
urllib3==1.26.20           # major boundary held — latest is 2.7.0
```

**4. Verify — this step is not optional:**

```bash
python -m pip install -r requirements.txt && pytest
```

depkeeper validates the packages you declared against each other. It does not expand the
transitive graph, so `pip` remains the authority on whether the set installs.

---

## Commands

### `depkeeper check [FILE]`

Read-only analysis. Never modifies the filesystem. Exits `0` on success regardless of findings.

| Option | Description |
|---|---|
| `--outdated-only` | Show only packages with an update or a conflict |
| `-f`, `--format table\|simple\|json` | Output format (default `table`) |
| `--strict-version-matching` | Only a sole `==` pin counts as a current version |
| `--check-conflicts` / `--no-check-conflicts` | Cross-package conflict resolution (default on) |

### `depkeeper update [FILE]`

Applies recommended versions in place.

| Option | Description |
|---|---|
| `--dry-run` | Run the full pipeline, print the plan, write nothing |
| `-y`, `--yes` | Skip the confirmation prompt |
| `--backup` | Timestamped backup of **every** affected file before writing |
| `--pin` | Replace every specifier with an exact `==` pin |
| `--allow-hash-removal` | Permit updating `--hash`-pinned requirements (removes the digests) |
| `-p`, `--packages NAME` | Restrict to specific packages (repeatable) |
| `--strict-version-matching` | As above |
| `--check-conflicts` / `--no-check-conflicts` | As above |

### Global options

`-c/--config PATH` · `-v` / `-vv` (INFO / DEBUG, always on stderr) · `--color/--no-color` ·
`--version` · `-h/--help`

Global options must precede the subcommand: `depkeeper -v check`, not `depkeeper check -v`.

Full specification: **[CLI reference](https://rahulkaushal04.github.io/depkeeper/reference/cli-commands/)**.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success — **including** "updates are available" |
| `1` | Application error (parse, config, write, refused hash removal) |
| `2` | Usage error (unknown option, missing file) |
| `130` | Interrupted (`Ctrl+C`) |

Gate automation on the JSON payload, never on `check`'s exit code.

---

## Configuration

Two settings are persistable, in `depkeeper.toml` or `pyproject.toml`. Everything else is a
per-invocation flag, deliberately — options that change what gets *written* stay visible in the
command line.

```toml
# depkeeper.toml
[depkeeper]
check_conflicts = true            # cross-package conflict resolution
strict_version_matching = false   # treat only `==` as a current version
```

```toml
# pyproject.toml
[tool.depkeeper]
check_conflicts = true
strict_version_matching = false
```

Precedence: **defaults < config file < CLI flag**. Unknown keys and wrong types are hard errors.
Discovery is limited to the current working directory (not recursive).

Environment: `DEPKEEPER_CONFIG`, `DEPKEEPER_COLOR`, `NO_COLOR`, `CI`, plus `httpx`'s
`HTTPS_PROXY` / `SSL_CERT_FILE`.

---

## Common workflows

**Daily**

```bash
depkeeper check --outdated-only
depkeeper update --dry-run
depkeeper update --backup && pip install -r requirements.txt && pytest
```

**One package at a time** (keeps regressions bisectable)

```bash
depkeeper update -p django -y && pytest
```

**Application release — freeze to exact versions**

```bash
depkeeper update --pin --backup
```

**CI drift report** — stdout stays parseable even with `-v`

```bash
depkeeper -v check --format json --no-check-conflicts > report.json 2> depkeeper.log
jq '[.[] | select(.status == "outdated")] | length' report.json
```

**Multi-file projects** — `-r` includes are followed and rewritten

```bash
depkeeper update requirements/dev.txt --dry-run   # also writes base.txt
```

**Hash-pinned files** — depkeeper refuses these by default

```bash
depkeeper update --allow-hash-removal -y
pip-compile --generate-hashes requirements.in     # regenerate; not optional
```

More: **[User guide](https://rahulkaushal04.github.io/depkeeper/guides/)** ·
**[CI/CD integration](https://rahulkaushal04.github.io/depkeeper/guides/ci-cd-integration/)**

---

## Architecture

Synchronous CLI around an asynchronous core. No daemon, no persistent state, no cache directory.

```text
requirements.txt
      │
      ▼
RequirementsParser ──► PyPIDataStore ──► VersionChecker ──► DependencyAnalyzer ──┐
  (text → model)      (one HTTP call     (per-package      (cross-package         │
                       per package)       target version)   consistency)          │
                                                                                  ▼
                                                             renderer (table/simple/json)
                                                             writer (atomic, rollback-safe)
```

| Component | Responsibility |
|---|---|
| `core/parser.py` | Requirements text → `Requirement` objects, `-r`/`-c` resolution, provenance |
| `core/data_store.py` | PyPI metadata cache with per-key request coalescing |
| `core/checker.py` | Per-package recommendation under boundary, Python and constraint filters |
| `core/dependency_analyzer.py` | Iterative conflict resolution within major boundaries |
| `commands/` | User interaction, rendering, the write pipeline, exit codes |
| `utils/` | HTTP, console, logging, atomic filesystem, naming, version algebra |

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for the contributor-facing map, or the
**[architecture deep dive](https://rahulkaushal04.github.io/depkeeper/concepts/architecture/)**
for design decisions, concurrency model and error propagation.

---

## Limitations

Honest, verified, and documented in full at
**[Known limitations](https://rahulkaushal04.github.io/depkeeper/reference/limitations/)**.
The ones most likely to affect you:

- **Not a resolver.** The transitive graph is not expanded. Always `pip install` and test.
- **Only `pypi.org` is queried.** `--index-url` lines are parsed and ignored; private packages
  report as errors.
- **Calendar versions hit the major boundary.** `certifi 2023.x` never auto-bumps to `2024.x`.
- **Major upgrades are yours to make.** Raise the floor by hand, then let depkeeper continue.
- **Backslash line continuations are not parsed**, so default
  `pip-compile --generate-hashes` output is unreadable to depkeeper.
- **No runtime tuning.** Timeouts, retries and concurrency are constants; override them via the
  Python API if you must.

---

## Troubleshooting

Start here:

```bash
depkeeper -vv check --format json > report.json 2> debug.log
```

`debug.log` names the file parsed, the effective configuration, every HTTP retry and every
resolution decision.

| Symptom | Cause |
|---|---|
| Recommendation far below `Latest` | Your declared cap, the major boundary, a conflict, or `requires_python` |
| Recommendations differ between laptop and CI | Different Python versions running depkeeper |
| `✗ ERROR` rows | Package not on public PyPI, network/proxy failure, or TLS interception |
| `update` changed a package `check` showed as `✓ OK` | Unversioned requirement — it received a pin |
| A proposed **downgrade** | Declared version is unusable; review before accepting |

Full guide: **[Troubleshooting](https://rahulkaushal04.github.io/depkeeper/guides/troubleshooting/)**

---

## Documentation

Published at **[rahulkaushal04.github.io/depkeeper](https://rahulkaushal04.github.io/depkeeper/)**.

| Section | Contents |
|---|---|
| [Getting started](https://rahulkaushal04.github.io/depkeeper/getting-started/) | Install, quick start, reading the output |
| [Concepts](https://rahulkaushal04.github.io/depkeeper/concepts/) | Architecture, version recommendation, conflict resolution, parsing, write safety |
| [User guide](https://rahulkaushal04.github.io/depkeeper/guides/) | Checking, updating, configuration, CI/CD, operations, best practices, troubleshooting |
| [Reference](https://rahulkaushal04.github.io/depkeeper/reference/) | CLI, config, exit codes, file formats, JSON schema, errors, limitations, Python API |
| [Contributing](https://rahulkaushal04.github.io/depkeeper/contributing/) | Setup, code style, testing, extending, releases |

Repository documents: [ARCHITECTURE.md](ARCHITECTURE.md) ·
[CONTRIBUTING.md](CONTRIBUTING.md) · [CHANGELOG.md](CHANGELOG.md) ·
[SECURITY.md](SECURITY.md) · [SUPPORT.md](SUPPORT.md) ·
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

---

## Project status

Version **0.1.0**, classified `Development Status :: 3 - Alpha`.

The write path is defensive — atomic replacement, two-phase commit, rollback, optional backups —
and behaviour is documented and covered by tests across Linux, macOS and Windows on Python
3.8–3.12. Pin the version in automation: recommendation logic is a behavioural contract, and a
version bump can legitimately change an update plan.

---

## Contributing

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md), and read the
[system invariants](https://rahulkaushal04.github.io/depkeeper/concepts/#non-negotiable-invariants)
before changing anything in `core/`.

```bash
git clone https://github.com/rahulkaushal04/depkeeper.git
cd depkeeper
pip install -e ".[dev,docs]"
pre-commit install

python -m pytest tests -q --no-cov
python -m mypy depkeeper --python-version 3.13
```

Report vulnerabilities privately — see [SECURITY.md](SECURITY.md), never a public issue.

---

## License

[Apache License 2.0](LICENSE). Copyright 2025-2026 Rahul Kaushal.

Built with [Click](https://click.palletsprojects.com/),
[Rich](https://rich.readthedocs.io/), [httpx](https://www.python-httpx.org/) and
[packaging](https://packaging.pypa.io/) — the last of which is why depkeeper agrees with `pip`
about what a version means.
