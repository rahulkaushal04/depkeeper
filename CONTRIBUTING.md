# Contributing to depkeeper

Thank you for contributing. This document is the contract a change must satisfy before it can be
merged: environment, workflow, quality bar, review standards and release process.

- **New here?** Read [Orientation](#orientation) then [Development setup](#development-setup).
- **Changing `core/`?** Read [Invariants](#invariants-you-must-not-break) first.
- **Full narrative documentation:** <https://rahulkaushal04.github.io/depkeeper/contributing/>

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).
Security vulnerabilities must **not** be filed as public issues — see [SECURITY.md](SECURITY.md).

---

## Orientation

depkeeper rewrites files that are under version control and that feed deployments. Its value is
that its guarantees hold. Most rejected changes are rejected because they quietly weaken one.

Read, in order:

1. [ARCHITECTURE.md](ARCHITECTURE.md) — module map and where to make a change.
2. [Core concepts](https://rahulkaushal04.github.io/depkeeper/concepts/) — the model.
3. [Invariants](#invariants-you-must-not-break) — the rules.

---

## Ways to contribute

| Contribution | What it needs |
|---|---|
| **Bug report** | Minimal reproducer requirements file, exact command, `depkeeper -vv … 2> debug.log`, `depkeeper --version`, `python --version`, expected vs actual. |
| **Bug fix** | A failing test **first**, then the fix. State which invariant or documented behaviour was violated. |
| **Feature** | Open an issue describing the *problem* before writing code. Anything that changes what gets written needs a design discussion. |
| **Documentation** | Verify every claim against the implementation. See [Documentation expectations](#documentation-expectations). |
| **Performance** | A before/after measurement and the workload used. |

---

## Development setup

### Prerequisites

- Python **3.8+** to run; **3.11+ recommended** for development so `mypy` and the async test
  suite behave predictably.
- Git. `make` is optional.

### Install

```bash
git clone https://github.com/rahulkaushal04/depkeeper.git
cd depkeeper
git remote add upstream https://github.com/rahulkaushal04/depkeeper.git

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -e ".[dev,docs]"
pre-commit install
```

Scripted equivalents: `bash scripts/setup_dev.sh` (macOS/Linux),
`.\scripts\setup_dev.ps1` (Windows).

| Extra | Contents |
|---|---|
| `dev` | pytest (+cov, asyncio, mock, httpx), mypy, types-setuptools, pre-commit |
| `test` | the pytest stack only |
| `docs` | mkdocs, mkdocs-material, mkdocstrings[python], pymdown-extensions, mkdocs-minify-plugin |

Install `docs` whenever you touch `docs/` or any docstring rendered by `mkdocstrings`.

### Verify the environment

```bash
python -m depkeeper --version
python -m pytest tests -q --no-cov
```

---

## Repository layout

```text
depkeeper/            Package source
├── cli.py            Click group: global options, config load, logging
├── commands/         check.py (read-only), update.py (write pipeline)
├── core/             parser, data_store, checker, dependency_analyzer
├── models/           requirement, package, conflict — pure data, no I/O
├── utils/            http, console, logger, filesystem, naming, version_utils
├── config.py         TOML discovery, parsing, validation
├── constants.py      Every tunable literal
└── exceptions.py     Structured exception hierarchy

tests/
├── conftest.py       Autouse isolation fixtures + instant_sleep
├── support/          factories.py, pypi.py (fake PyPI), datasets.py
├── test_core/  test_models/  test_commands/  test_utils/
├── integration/      parse → check → resolve → write
└── test_config.py  test_context.py  test_main.py

docs/                 MkDocs site (see mkdocs.yml)
scripts/              Developer setup scripts
```

Tests mirror the package layout. A change to `core/parser.py` belongs in `tests/test_core/`.

---

## Branching strategy

Single long-lived branch, `main`, which is always releasable. CI also runs on `develop` if you
use it as an integration branch. All work happens on short-lived topic branches off `main`, merged
by pull request.

| Change type | Prefix | Example |
|---|---|---|
| Feature | `feature/` | `feature/private-index-support` |
| Bug fix | `fix/` | `fix/parser-line-continuations` |
| Documentation | `docs/` | `docs/json-schema` |
| Refactor | `refactor/` | `refactor/extract-resolution-loop` |
| Tests | `test/` | `test/analyzer-stall-cases` |
| Maintenance | `chore/` | `chore/bump-httpx-floor` |

```bash
git checkout main && git pull upstream main
git checkout -b fix/parser-line-continuations
```

Rebase onto `main` rather than merging `main` into your branch; keep the history linear and the
diff reviewable.

---

## Development workflow

### 1. Write a failing test first

Mandatory for bug fixes. The test must fail before your change and pass after it — that is the
only evidence the fix addresses the reported behaviour.

### 2. Implement

Respect the layering: `models` do no I/O, `core` does no printing, `commands` own all user
interaction and exit codes. New tunables go in `constants.py`, never inline.

### 3. Verify locally

These four commands are the contract. CI runs the equivalent across
Linux/macOS/Windows × Python 3.8–3.12.

```bash
python -m pytest tests -q --no-cov            # 1. tests
python -m mypy depkeeper --python-version 3.13 # 2. types
python -m compileall -q depkeeper              # 3. syntax
pre-commit run --all-files                     # 4. hygiene
```

Plus, if you touched `docs/` or public docstrings:

```bash
python -m mkdocs build --strict                # 5. docs
```

> [!NOTE]
> **Why `--python-version 3.13`:** `pyproject.toml` sets `python_version = "3.8"` for mypy, which
> current mypy releases refuse to analyse. The project baseline is a single known error in
> `data_store.py` (`no-any-return`); anything beyond that is yours.
>
> **Why `--no-cov`:** `addopts` enables coverage with term, HTML and XML reports on every run.
> That is what CI wants and what a fast edit–test loop does not.
>
> **Why `compileall`:** it catches edits that silently join two source lines — a real failure mode
> when patching by string replacement.

### 4. Commit

[Conventional Commits](https://www.conventionalcommits.org/). Scope is the module or subsystem.

```text
feat(update): add --pin to replace declared ranges with exact pins
fix(parser): join backslash line continuations
docs(reference): document the JSON output schema
test(analyzer): pin cumulative-conflict behaviour
refactor(core): extract the alternative search from the resolution loop
chore(deps): cap the docs toolchain below MkDocs 2.0
```

The body explains **why**; the diff already says what.

```bash
git commit -m "fix(parser): join backslash line continuations

pip-compile --generate-hashes wraps hashes onto continuation lines, which the
line-based parser treated as separate, invalid requirements.

Closes #123"
```

### 5. Open a pull request

```bash
git push origin fix/parser-line-continuations
```

Fill in the pull request template. Keep pull requests focused — one concern each. If you find an
unrelated defect, open an issue rather than widening the diff.

---

## Testing expectations

Full guide: <https://rahulkaushal04.github.io/depkeeper/contributing/testing/>

### Rules

- **No network access.** Use `tests.support.pypi.FakePyPIStore` / `store_for()`, or `pytest-httpx`
  for tests of `HTTPClient` itself. A test that reaches `pypi.org` will be rejected.
- **No real sleeping.** Use the `instant_sleep` fixture and assert on the backoff *schedule*, not
  on wall-clock time.
- **Use the shared infrastructure** in `tests/support/` (`make_requirement`, `make_package`,
  `FakePyPIStore`, `write_project`) instead of hand-rolling fixtures.
- **Name the behaviour**, not the function: `test_major_boundary_is_never_crossed`.
- `asyncio_mode = "auto"`, so `async def test_…` needs no decorator.
- Markers are strict; use only those declared in `pyproject.toml`.

### What each change must cover

| Change | Required tests |
|---|---|
| Bug fix | Regression test that fails before the fix |
| New CLI flag | With, without, and interaction with the config file |
| Recommendation logic | Major edge, Python-incompatible release, constraint-excluded candidate, empty candidate list |
| Resolver change | Convergence, stall, and cumulative-conflict behaviour |
| Writer change | Byte-level assertions: line endings, BOM, untouched lines, rollback |
| Parser change | A malformed input that must raise and a valid input that must not |
| New error/warning message | The message text — it is documented in the error reference |

### Known trap: logging isolation

`setup_logging` sets `propagate = False` on the shared `depkeeper` logger **process-wide**, so any
test that drives the CLI through `CliRunner` can blind `caplog` in every later module. The autouse
`_isolate_depkeeper_logger` fixture in `tests/conftest.py` handles this. Do not disable it, and do
not reintroduce module-local workarounds.

If a test passes alone but fails in the full suite, suspect cross-test state: the `depkeeper`
logger, the memoised Rich consoles, or an environment variable such as `NO_COLOR`.

### Coverage

```bash
python -m pytest --cov=depkeeper --cov-report=term-missing
```

There is no hard gate, but a pull request should not reduce coverage of the module it touches.
The weakest areas today are `commands/update.py` and `cli.py`.

---

## Code quality requirements

Full guide: <https://rahulkaushal04.github.io/depkeeper/contributing/code-style/>

| Area | Requirement |
|---|---|
| Typing | `mypy --strict`. `from __future__ import annotations` first. `typing` generics (`List[str]`), not builtin generics — Python 3.8 is supported. No bare `Any` in a public signature. |
| Docstrings | **Google style** (enforced by `mkdocs.yml`). Summary on the same line as `"""`. `Args:` for callables only; dataclasses document fields under `Attributes:`. American English. |
| Doctests | No doctest runner is configured, so `>>>` blocks are unverified. Add them only to public API, and only after actually running them. |
| Comments | Explain **why**. Delete any comment that restates the next line. |
| Errors | Raise a depkeeper exception, chain with `from exc`, never swallow silently. Catch `NetworkError`, not `PyPIError`. |
| Logging | `logger.debug("… %s", value)` — `%s` placeholders, never f-strings. Never `print()` for diagnostics. Never log to stdout. |
| Async | Network I/O is async and goes through `HTTPClient`. Library code never creates an event loop. |
| Formatting | 4 spaces, LF endings, trailing commas in multi-line literals, target ~88 columns. No automated formatter is configured; do not reflow unrelated lines. |

### Invariants you must not break

| Invariant | Why it matters |
|---|---|
| A recommendation never crosses a major boundary when a current version is known | The core safety promise |
| A recommendation never violates the declared constraints (except under `--pin`) | Otherwise depkeeper writes unsatisfiable lines |
| `Package.recommended_version` equals the resolver's `resolved` value | Otherwise the report and the write disagree |
| Package names are compared only in PEP 503 canonical form | Otherwise cross-package lookups silently miss |
| `check` never writes | A read-only command must stay read-only |
| Machine-readable formats emit only the payload on stdout | Otherwise every downstream parser breaks |
| A failed write leaves every affected file at its previous content | Data safety |

Changing one is not forbidden, but it must be argued explicitly in the pull request and reflected
in the documentation.

---

## Documentation expectations

Behavioural changes require documentation changes **in the same pull request**.

| Change | Update |
|---|---|
| New or changed flag | `docs/reference/cli-commands.md`, the relevant guide, README if user-facing |
| Recommendation logic | `docs/concepts/version-recommendation.md` |
| Resolver behaviour | `docs/concepts/conflict-resolution.md` |
| New error or warning text | `docs/reference/errors.md` |
| New JSON field | `docs/reference/json-output.md` |
| Fixed a documented limitation | `docs/reference/limitations.md` |
| Architecture change | `ARCHITECTURE.md` and `docs/concepts/architecture.md` |
| Anything user-visible | `CHANGELOG.md` under **Unreleased** |

Rules:

- Every behavioural claim must be verifiable. Run the command and paste the **real** output rather
  than composing an illustrative one.
- Cross-link rather than duplicate: concepts in `docs/concepts/`, exhaustive lists in
  `docs/reference/`, tasks in `docs/guides/`.
- API documentation is generated from docstrings — fix the docstring, not the page.
- `mkdocs.yml` sets `strict: true`, so a broken link or unresolved reference **fails the build**.

```bash
python -m mkdocs serve          # live preview
python -m mkdocs build --strict # what CI runs
```

---

## Pull request expectations

### Definition of done

- [ ] `python -m pytest tests -q --no-cov` passes
- [ ] `python -m mypy depkeeper --python-version 3.13` reports no new errors
- [ ] `python -m compileall -q depkeeper` succeeds
- [ ] `pre-commit run --all-files` passes
- [ ] `python -m mkdocs build --strict` passes (if docs or docstrings changed)
- [ ] New behaviour has tests; fixed bugs have regression tests
- [ ] Documentation updated per the table above
- [ ] `CHANGELOG.md` updated under **Unreleased** for user-visible changes
- [ ] No invariant weakened, or the change argues explicitly why it should be

### What reviewers check

1. **Correctness** — does it do what it claims, including at the boundaries?
2. **Invariants** — is any guarantee weakened, directly or as a side effect?
3. **Blast radius** — for write-path changes, what happens on failure, interruption or rollback?
4. **Tests** — would they actually fail if the change were reverted?
5. **Layering** — is the logic in the right module?
6. **Documentation** — will a user discover this behaviour without reading the source?
7. **Platform** — does it hold on Windows (paths, line endings, file locks)?

### Review process

- Reviews are best-effort and prompt; ping the thread if a pull request goes quiet.
- Address feedback with additional commits rather than force-pushing mid-review, so reviewers can
  see what changed. Squash before merge.
- All CI checks must be green. `Test Summary` is the aggregate required status.
- Maintainers merge; contributors do not need write access.

---

## Release process

Maintainers only. Full detail:
<https://rahulkaushal04.github.io/depkeeper/contributing/release-process/>

Summary:

1. All five verification commands pass on a clean `main`.
2. Bump the version in **both** `depkeeper/__version__.py` and `pyproject.toml`.
3. Move the `Unreleased` section of `CHANGELOG.md` into a dated release section.
4. `python -m build`, `twine check dist/*`, verify the wheel in a clean virtualenv — catch a
   packaging problem locally, before it reaches CI.
5. Tag `vX.Y.Z` and push the tag. This is the trigger: `.github/workflows/publish.yml` verifies
   the tag matches the bumped version, builds, publishes to PyPI via Trusted Publishing, and
   deploys the versioned docs with the `latest` alias pointed at the new release. Nothing is
   published by running commands locally.
6. Create the GitHub release from the tag using the changelog section.

> [!IMPORTANT]
> A change that makes the same requirements file produce a different update plan is **at minimum
> a minor release**, even when the diff looks like a bug fix. Consumers gate pipelines on that
> output.

---

## Getting help

- Usage questions — [open an issue](https://github.com/rahulkaushal04/depkeeper/issues/new)
- Defects — [Issues](https://github.com/rahulkaushal04/depkeeper/issues)
- Vulnerabilities — [SECURITY.md](SECURITY.md), never a public issue
- Everything else — [SUPPORT.md](SUPPORT.md)
