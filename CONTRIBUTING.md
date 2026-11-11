# Contributing to depkeeper

Thanks for helping. This page tells you how to set up, change code, and get a pull request merged.

By taking part, you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
Found a security bug? Do **not** open a public issue. See [SECURITY.md](SECURITY.md).

Longer guides live in the [contributing docs](https://github.com/rahulkaushal04/depkeeper/blob/main/docs/contributing/index.md).

---

## Quick start

You need Python 3.8 or newer.

```bash
git clone https://github.com/rahulkaushal04/depkeeper.git && cd depkeeper
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pre-commit install
pytest
```

Or run `./scripts/setup_dev.sh` (Windows: `scripts/setup_dev.ps1`). It does the same steps.

`make install-dev` also works, but it installs into whatever Python is active.

---

## Daily commands

| Task | Command |
|---|---|
| Run tests (with coverage) | `pytest` |
| Run one test | `pytest tests/test_core/test_parser.py -k name --no-cov` |
| Type check (strict) | `mypy depkeeper --python-version 3.13` |
| Lint (as CI runs it) | `ruff check --select E9,F depkeeper tests` |
| Format | `ruff format depkeeper tests` |
| Pre-commit hooks | `pre-commit run --all-files` |

`ruff` is part of the `dev` extra. Its settings (Python 3.8 target,
line length 88) are in `pyproject.toml`. CI checks `ruff format --check` and the `E9,F` lint rules only; do not run bare `ruff check .`, which also scans `docs/` and applies newer default rules. The pre-commit hooks are file hygiene only (no ruff or mypy).

mypy warns that `python_version = "3.8"` is unsupported by current releases; `--python-version 3.13` silences that.

CI runs the tests on Python 3.8 to 3.12 on Linux, macOS and Windows.

---

## Project map

| Path | What it holds |
|---|---|
| `depkeeper/cli.py` | Click group, global options, config loading |
| `depkeeper/commands/` | `check` (read-only), `update` (writes files) and `_report.py` (shared rendering) |
| `depkeeper/core/` | Parser, PyPI data store, version checker, conflict analyzer, `verify.py` |
| `depkeeper/core/sources/` | One adapter per file format (see below) |
| `depkeeper/models/` | `Requirement`, `Package`, conflict types. No I/O. |
| `depkeeper/utils/` | HTTP, filesystem, console, logging, name and version helpers |
| `tests/` | Mirrors the package layout; shared helpers in `tests/support/` |
| `docs/` | User and contributor guides (Markdown) |
| `assets/` | Logo and diagrams |
| `scripts/` | Developer setup scripts |

Layers only point one way: `commands` to `core` to `models` to `utils`.
See [ARCHITECTURE.md](ARCHITECTURE.md) for the full map.

### Adding support for a new file format

Write a `SourceAdapter` in `depkeeper/core/sources/`, then register it in `registry.py`.
The step-by-step guide is the docstring at the top of
[`depkeeper/core/sources/base.py`](depkeeper/core/sources/base.py). Existing adapters
(`requirements_txt.py`, `pyproject_toml.py`, `conda_yaml.py`) are good examples.

Two rules matter most:

- Edit files in place. Comments, order, quoting and line endings must survive byte for byte.
- Adapters never touch the disk when updating. The caller handles atomic writes, backups and rollback.

---

## Workflow

1. Open or find an issue. For a new feature, agree on the problem before you write code.
2. Branch from `main`.
3. Write a failing test, then the fix or feature.
4. Run the checks in the PR checklist below.
5. Open a pull request using the template. Link the issue (`Closes #123`).

Commits and PR titles are short, imperative sentences, for example
`Fix duplicate-requirement resolution`. Squash-merged PRs end with the PR number. There is no
required prefix.

---

## Python 3.8 compatibility

The code must run on Python 3.8. Check these before you push:

- Start modules with `from __future__ import annotations`.
- No `X | Y` in anything evaluated at runtime (casts, `isinstance`, aliases). Use `Optional[X]` and `Union[X, Y]`.
- No `list[int]`, `dict[str, int]` at runtime. Use `List[int]`, `Dict[str, int]` from `typing`.
- No parenthesised multi-item `with (a as x, b as y):`. Use nested `with` statements.
- No `match` statements, no `str.removeprefix` / `removesuffix`, no `zip(strict=True)`.

CI will catch most of these, but only if the 3.8 job runs. Do not ignore a red 3.8 build.

---

## Code style

- Format with `ruff format`, lint with `ruff check`. Line length is 88.
- Full type hints on every function. `mypy --strict` must pass.
- Google-style docstrings on public code (`Args:`, `Returns:`, `Raises:`).
- Comments explain **why**, not what.
- Keep one source of truth. Package names go through `utils/naming.py`. Tunable numbers live in `constants.py`.
- No network or disk I/O in `models/`.

---

## Writing tests

- Tests mirror the package: `tests/test_core/`, `tests/test_commands/`, `tests/test_sources/`, `tests/test_models/`, `tests/test_utils/`. End-to-end flows go in `tests/integration/`.
- Name files `test_*.py`, classes `Test*`, functions `test_*`.
- Async tests need no decorator (`asyncio_mode = "auto"`).
- Never hit the real PyPI. Use `pytest-httpx`, and build fake PyPI data with the helpers in `tests/support/` (`pypi.py`, `factories.py`, `datasets.py`). Shared fixtures are in `tests/conftest.py`. Tests that need the real PyPI are marked `network` and skip when it is unreachable.
- A bug fix needs a regression test that fails without the fix.
- A new adapter needs parse-then-update round trips, including a no-op update that leaves bytes identical.

---

## Good first issues

Look for issues labelled `good first issue`. Good starting points:

- Docs fixes. Check each claim against the code.
- Extra test cases for parser edge cases (odd whitespace, comments, line endings).
- Clearer error messages.

If no issue fits, open one and say what you plan to do. Small, focused PRs get reviewed faster.

---

## Documentation and changelog

- Change a flag, config key, exit code or output? Update the matching page under `docs/reference/`. Docs are plain Markdown; relative links must resolve.
- Add a line under **Unreleased** in [CHANGELOG.md](CHANGELOG.md). It follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Use the sections `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`, each at most once under Unreleased.
- **Behaviour contract:** if the same requirements file now produces a different update plan, that is at least a minor release, even if it looks like a bug fix. Mark the entry **Impact** and say what changes.

---

## Pull request checklist

This matches the [PR template](.github/PULL_REQUEST_TEMPLATE.md).

- [ ] `pytest` passes
- [ ] `mypy depkeeper --python-version 3.13` is clean
- [ ] `ruff format --check depkeeper tests` and `ruff check --select E9,F depkeeper tests` are clean
- [ ] `pre-commit run --all-files` passes
- [ ] Docs updated if behaviour changed (`docs/` is plain Markdown; links must resolve)
- [ ] New behaviour has tests; bug fixes have a regression test
- [ ] Docs and `CHANGELOG.md` are updated
- [ ] The PR says whether it changes any update plan

---

## Releases

Maintainers cut releases. The steps (version files, changelog, tag, publish) are in the
[release process](https://github.com/rahulkaushal04/depkeeper/blob/main/docs/contributing/release-process.md).
Contributors only need to keep `CHANGELOG.md` current.

---

## Need help?

See [SUPPORT.md](SUPPORT.md).
