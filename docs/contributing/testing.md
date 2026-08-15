---
title: Testing
description: Suite layout, shared infrastructure, isolation traps and testing standards
---

# Testing

```bash
python -m pytest tests -q --no-cov        # fast loop
python -m pytest --cov=depkeeper          # with coverage (also the default via addopts)
make test                                  # term + HTML + XML coverage, as CI runs it
```

The suite is fast by design: no test performs real network I/O, and no test sleeps for real.

---

## Layout

```text
tests/
├── conftest.py                     autouse isolation fixtures + instant_sleep
├── support/                        shared test infrastructure (importable as tests.support.*)
│   ├── factories.py                make_requirement / make_package / make_conflict / specs
│   ├── pypi.py                     ECOSYSTEM, FakePyPIStore, package_data, store_for
│   └── datasets.py                 realistic requirements corpora + write_project
├── test_core/                      parser, checker, data store, dependency analyzer
├── test_models/                    Requirement, Package, Conflict
├── test_commands/                  check and update command behaviour
├── test_utils/                     http, console, logger, filesystem, naming, version utils
├── integration/                    parse → check → resolve → write workflows
├── test_config.py                  configuration discovery, parsing, validation
├── test_context.py                 CLI context object
└── test_main.py                    entry points and exit codes
```

`tests/__init__.py` places the repository root on `sys.path`, so `tests.support.*` imports work
without installation tricks.

---

## Shared infrastructure

Use these instead of hand-rolling fixtures. They exist because the suite previously took ~80
seconds and 67% coverage; the current shape is ~10 seconds and ~88%.

### `tests.support.factories`

```python
from tests.support.factories import make_requirement, make_package, make_conflict, specs

req = make_requirement("flask", specs=specs(">=2.0", "<2.3"))
pkg = make_package("flask", current="2.0", latest="3.1.3", recommended="2.2.5")
```

### `tests.support.pypi`

`ECOSYSTEM` holds **real** PyPI release histories and `requires_dist` metadata, so tests exercise
realistic version ladders rather than invented ones.

```python
from tests.support.pypi import FakePyPIStore, package_data, pypi_json_payload, store_for

store = store_for("flask", "werkzeug")     # real dependency metadata enabled
store = FakePyPIStore()                    # dependencies disabled by default
```

`FakePyPIStore(use_real_dependencies=False)` is the default because most tests do not need the
dependency graph and it keeps them fast. `store_for()` enables it.

### `tests.support.datasets`

Realistic requirements corpora and `write_project()` for building a temporary project tree with
`-r` includes.

### `instant_sleep`

Records the delays passed to `asyncio.sleep` and never actually waits. Assert on the **backoff
schedule**, not on wall-clock time:

```python
async def test_retries_use_exponential_backoff(instant_sleep):
    ...
    assert instant_sleep.delays == pytest.approx([1.0, 2.0, 4.0], abs=0.3)
```

Roughly 50 seconds of real backoff sleeps were removed from `test_http.py` this way.

Also pass `verify_ssl=False` when constructing a fake `HTTPClient`: building a real `SSLContext`
costs ~0.3 s per test.

---

## Isolation

`tests/conftest.py` provides two autouse fixtures. Do not disable them.

### Logging isolation

`setup_logging` sets `propagate = False` on the shared `depkeeper` logger **for the whole
process**. Any test that invokes the CLI through `CliRunner` therefore blinds `caplog` in every
test module that runs afterwards. This has broken the suite before — tests passed in isolation and
failed in a full run.

The autouse `_isolate_depkeeper_logger` fixture snapshots and restores the logger's handlers,
level and `propagate` flag around every test. With it in place, module-local guards are no longer
needed.

### Console isolation

`_isolate_console` clears the memoised per-stream Rich consoles between tests. Colour support is
probed once when a console is first built, so without this a redirected stream in one test leaks
into the next.

---

## Writing tests

### Naming

Test names state the **behaviour**, not the function under test:

```python
def test_major_boundary_is_never_crossed(): ...
def test_declared_upper_bound_caps_the_recommendation(): ...
def test_hashed_requirement_is_refused_without_opt_in(): ...
```

### Structure

Arrange / act / assert, with the phases visually separated. One behaviour per test.

### Async

`asyncio_mode = "auto"`, so an `async def test_...` needs no decorator.

```python
async def test_package_is_fetched_once(instant_sleep):
    store = FakePyPIStore()
    await asyncio.gather(*(store.get_package_data("flask") for _ in range(5)))
    assert store.fetch_count("flask") == 1
```

### Never hit the network

Use `FakePyPIStore`, or `pytest-httpx` for tests of `HTTPClient` itself. A test that reaches
`pypi.org` will be rejected.

### Markers

Declared in `pyproject.toml` with `--strict-markers`, so an undeclared marker is an error:
`unit`, `slow`, `integration`, `e2e`, `network`, `asyncio`.

---

## What must be tested

| Change | Required tests |
|---|---|
| Bug fix | A regression test that fails before the fix. |
| New CLI flag | Behaviour with the flag, without it, and its interaction with the config file. |
| Recommendation logic | Boundary cases: major edge, Python-incompatible release, constraint-excluded candidate, empty candidate list. |
| Resolver change | Convergence, stall, and the cumulative-conflict behaviour. |
| Writer change | Byte-level assertions: line endings, BOM, untouched lines, rollback. |
| Parser change | A malformed input that must raise, and a valid input that must not. |
| New error message | The message text, since it is documented in [Error reference](../reference/errors.md). |

---

## Production behaviours pinned by tests

These are **intentional** and are asserted by the suite. Do not "fix" a test that contradicts one
without changing the documentation and the invariant it rests on.

| Behaviour | Note |
|---|---|
| The major boundary applies to calendar versions. | `certifi 2023.7.22` never auto-bumps to `2024.x`. |
| `extract_current_version` reads `>=X` as "currently on X". | So `django>=3.2,<5.0` only reaches `3.2.x`. |
| A cap-only spec gains an appended floor. | `<3.0` + `2.32.3` → `<3.0,>=2.32.3`; order is not normalised. |
| `~=2.0` + `2.0.30` is a no-op; `~=2.0` + `2.3.3` → `~=2.3`. | The author's precision is preserved. |
| An unavailable stub ends with `recommended_version == current_version`. | `latest_version` stays `None`. |
| A `429` retry also consumes an outer `max_retries` slot. | The budgets are not independent. |

## Known gaps pinned by tests

Asserted as *current* behaviour so a change is deliberate, and documented in
[Known limitations](../reference/limitations.md):

- Backslash line continuations are not joined
  (`test_parser.py::test_line_continuations_are_not_joined`).
- URL name inference is unreliable
  (`test_inference_from_an_archive_url_is_unreliable`).
- `--allow-hash-removal` yields a partially hashed lockfile that `pip --require-hashes` rejects —
  asserted in `tests/integration/test_update_workflow.py`.

`confirm(default=False)`'s `[y/N]` suffix used to be swallowed by Rich markup; the fix
(`markup=False`) is pinned by a regression test,
`test_console.py::test_the_prompt_advertises_a_default_of_no`, not an `xfail`.

---

## Coverage

Configured in `pyproject.toml`: source `depkeeper`, tests and caches omitted, HTML to `htmlcov/`,
XML to `coverage.xml`.

```bash
python -m pytest --cov=depkeeper --cov-report=term-missing
python -m pytest --cov=depkeeper --cov-report=html && open htmlcov/index.html
```

There is no hard coverage gate, but a pull request should not reduce coverage of the module it
touches. The weakest areas today are `commands/update.py` (CLI orchestration, preview, confirm)
and `cli.py`.

---

## Debugging a failure

```bash
python -m pytest tests/test_core/test_parser.py -q --no-cov      # one module
python -m pytest -k "boundary" --no-cov                          # by name
python -m pytest -x --no-cov                                     # stop at the first failure
python -m pytest --lf --no-cov                                   # last failed
python -m pytest -q --no-cov -p no:randomly                      # if ordering is suspected
python -m pytest --tb=long --no-cov                              # full tracebacks
```

If a test passes alone but fails in the full suite, suspect cross-test state: the `depkeeper`
logger, the memoised consoles, or an environment variable such as `NO_COLOR`.
