---
title: Development Setup
description: Local environment, tooling, verification commands and the change workflow
---

# Development Setup

## Prerequisites

| Tool | Requirement |
|---|---|
| Python | ≥ 3.8 to run; **3.11+ recommended** for development so `mypy` behaves predictably. CI covers 3.8 to 3.12. |
| Git | Any recent version. |
| Make | Optional; the `Makefile` targets are conveniences over plain commands. |

---

## Setup

**Scripted**

```bash
git clone https://github.com/rahulkaushal04/depkeeper.git
cd depkeeper

bash scripts/setup_dev.sh          # macOS / Linux (creates .venv, installs [dev], hooks, runs pytest)
.\scripts\setup_dev.ps1            # Windows PowerShell
```

**Manual**

```bash
git clone https://github.com/rahulkaushal04/depkeeper.git
cd depkeeper

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
pre-commit install
```

**Make**

```bash
make install-dev                   # editable install + dev extras + pre-commit hooks
```

### Dependency extras

| Extra | Contents |
|---|---|
| `dev` | pytest, pytest-cov, pytest-asyncio, pytest-mock, pytest-httpx, mypy, ruff, types-setuptools, pre-commit |
| `test` | the pytest stack only |

---

## Verification commands

These commands are the contract. Run all of them before opening a pull request.

```bash
# 1. Tests — fast, no coverage instrumentation
python -m pytest tests -q --no-cov

# 2. Types — pin the analysis version; pyproject declares 3.8, which modern mypy rejects
python -m mypy depkeeper --python-version 3.13

# 3. Syntax — catches edits that silently join two source lines
python -m compileall -q depkeeper

# 4. Format and lint — exactly what CI checks
python -m ruff format --check depkeeper tests
python -m ruff check --select E9,F depkeeper tests

# 5. Hooks — file hygiene (whitespace, line endings, YAML/TOML/JSON syntax)
pre-commit run --all-files
```

> [!NOTE]
> **Why `--python-version 3.13`**
>
> `pyproject.toml` sets `python_version = "3.8"` for mypy, which current mypy releases warn about.
> Pass the flag explicitly. The baseline is zero errors.

> [!NOTE]
> **Why `--no-cov`**
>
> `addopts` in `pyproject.toml` enables coverage with term, HTML and XML reports on every run.
> That is what CI wants and what a fast edit-test loop does not. `--no-cov` skips it.

Coverage when you do want it:

```bash
python -m pytest --cov=depkeeper --cov-report=term-missing
make test        # term + html + xml
```

---

## Change workflow

### 1. Branch

| Type | Prefix | Example |
|---|---|---|
| Feature | `feature/` | `feature/private-index-support` |
| Fix | `fix/` | `fix/parser-line-continuations` |
| Docs | `docs/` | `docs/json-schema` |
| Refactor | `refactor/` | `refactor/extract-resolution-loop` |
| Tests | `test/` | `test/analyzer-stall-cases` |

```bash
git checkout -b fix/parser-line-continuations
```

### 2. Write a failing test first

For a bug fix this is mandatory. The test must fail before the fix and pass after it; that is the
only evidence that the fix addresses the reported behaviour.

### 3. Implement

- Respect the [layering rules](../concepts/architecture.md#layering-rules): `models` perform no
  I/O, `core` prints nothing, `commands` own all user interaction.
- Do not weaken a [system invariant](../concepts/index.md#non-negotiable-invariants) without an
  explicit argument in the pull request.
- Add new tunables to `constants.py`, never inline.

### 4. Verify

Run all the verification commands above.

### 5. Update documentation

Behavioural changes require documentation changes in the same pull request. The pages most often
affected:

| Change | Pages |
|---|---|
| New or changed flag | [CLI commands](../reference/cli-commands.md), the relevant guide |
| Changed recommendation logic | [Version recommendation](../concepts/version-recommendation.md) |
| Changed resolver behaviour | [Conflict resolution](../concepts/conflict-resolution.md) |
| New error or warning message | [Error reference](../reference/errors.md) |
| Fixed a documented limitation | [Known limitations](../reference/limitations.md) |
| New JSON field | [JSON output](../reference/json-output.md) |

### 6. Commit and open a pull request

```bash
git commit -m "Join backslash line continuations

pip-compile --generate-hashes wraps hashes onto continuation lines, which
the line-based parser treated as separate requirements.

Closes #123"
git push origin fix/parser-line-continuations
```

---

## Makefile targets

| Target | Command it runs |
|---|---|
| `make install` | `pip install -e .` |
| `make install-dev` | `pip install -e ".[dev]"` + `pre-commit install` |
| `make test` | `pytest` with term, HTML and XML coverage |
| `make typecheck` | `mypy depkeeper` |
| `make all` | `typecheck` then `test` |
| `make clean` | Removes build, cache and coverage artefacts |

The Makefile targets assume a POSIX shell. On Windows, run the underlying commands directly.

---

## Working on the documentation

The docs are plain Markdown under `docs/` and render directly on GitHub. Preview them in any
Markdown viewer, and check that relative links still resolve before pushing.

Documentation conventions:

- Every behavioural claim must be verifiable against the implementation. Run the command and paste
  the real output rather than composing an illustrative one.
- Cross-link rather than duplicate. Concepts live in `concepts/`, exhaustive lists in `reference/`,
  tasks in `guides/`.
- Prefer tables to prose for enumerable facts.
- Use GitHub-flavoured Markdown only: GitHub alerts (`> [!NOTE]`) for callouts, and plain headings
  instead of tabs or cards.

---

## Repository layout

```text
depkeeper/          Package source (see the architecture module map)
tests/              Test suite, mirroring the package layout
  support/          Shared factories, fake PyPI, dataset builders
  integration/      Multi-component workflow tests
docs/               This documentation
scripts/            Developer setup scripts (setup_dev.sh, setup_dev.ps1)
assets/             Logo and diagrams
.github/            Workflows (tests.yml, publish.yml), issue forms, PR template
pyproject.toml      Packaging, mypy, pytest and coverage configuration
Makefile            Development shortcuts
.pre-commit-config.yaml
```

---

## Pre-commit hooks

Hooks (file hygiene only; ruff and mypy are not hooks):

- `trailing-whitespace`, `end-of-file-fixer`
- `mixed-line-ending --fix=lf` — the repository itself is LF-only, so diffs stay meaningful (this
  is independent of depkeeper's runtime behaviour, which preserves whatever a target file uses)
- `check-yaml`
- `check-json`, `check-toml`, `check-ast`
- `check-added-large-files --maxkb=1000`
- `check-case-conflict`, `check-merge-conflict`

```bash
pre-commit run --all-files
pre-commit run --files depkeeper/core/parser.py
```

---

## Troubleshooting the environment

| Symptom | Fix |
|---|---|
| `mypy: Python 3.8 is not supported` (warning) | Pass `--python-version 3.13`. |
| Tests are slow | Use `--no-cov`; coverage reporting is on by default. |
| `caplog` captures nothing in a new test module | `setup_logging` sets `propagate = False` process-wide. See [Testing → Logging isolation](testing.md#logging-isolation). |
| Console colour leaks between tests | Use the `_isolate_console` fixture; `reconfigure_console()` clears the memoised consoles. |
