---
title: Code Style
description: Typing, docstrings, comments and naming conventions enforced in depkeeper
---

# Code Style

These conventions are enforced by review, by `mypy --strict`, and by the documentation build
(`mkdocs.yml` sets `docstring_style: google`).

---

## Typing

`mypy` runs in **strict** mode. Every function, including tests' production helpers, is annotated.

```python
from __future__ import annotations   # first import in every module

from typing import Dict, List, Optional, Sequence, Tuple
```

| Rule | Reason |
|---|---|
| `from __future__ import annotations` at the top of every module. | Postponed evaluation; keeps 3.8 compatibility while allowing modern syntax in annotations. |
| Use `typing` generics (`List[str]`, `Dict[str, int]`). | The package supports Python 3.8, where builtin generics are unavailable at runtime. |
| No bare `Any` in a public signature. | Strict mode allows it; reviewers do not. |
| `Optional[X]` rather than `X | None` in runtime positions. | 3.8 compatibility. |
| Public constants are `Final`. | See `constants.py`. |

The project baseline is exactly one known mypy error (`data_store.py`, `no-any-return`). A pull
request must not add a second.

---

## Docstrings

**Google style**, without exception. This is what `mkdocstrings` is configured to parse, so a
deviation degrades the generated [Python API](../reference/python-api.md) page.

```python
def rewrite_version_specs(specs: Sequence[Spec], new_version: str) -> List[Spec]:
    """Rewrite a specifier set so it targets *new_version*.

    Only the specifiers that describe the currently-selected version are
    changed. Upper bounds, exclusions and wildcard bands are preserved.

    Args:
        specs: The requirement's declared specifier pairs, in order.
        new_version: The version to move the requirement to.

    Returns:
        A new list of specifier pairs, with duplicates removed.

    Raises:
        ValueError: The preserved constraints exclude *new_version*.
    """
```

### Rules

| Rule | Detail |
|---|---|
| Summary on the **same line** as the opening `"""`. | PEP 257. Never open with a blank line. |
| Imperative mood for the summary. | "Return the …", not "Returns the …". |
| `Args:` documents **callable parameters only**. | |
| Dataclasses and NamedTuples document fields under `Attributes:`. | `merge_init_into_class: true` folds `__init__` into the class, so constructor arguments belong under the class's `Args:`. |
| `Raises:` lists every exception a caller can reasonably catch. | |
| American English throughout. | normalize, behavior, color, initialize, canonicalize. |

### Sphinx roles

Valid: `:class:`, `:func:`, `:meth:`, `:attr:`, `:exc:`, `:data:`.
Invalid: `:pymeth:`, `:pyattr:` — these do not resolve and have been removed from the codebase.

### Doctest examples

There is **no doctest runner** configured (`addopts` contains no `--doctest-modules`), so `>>>`
blocks are unverified prose.

- Keep them only on the **public** API, and only when you have actually executed them.
- Do not add them to private helpers.
- A wrong example is worse than no example: earlier revisions carried fabricated output such as
  `<Requirement requests>=2.25.0>`, which is not the real `__repr__`.

---

## Comments

Comments explain **why**, never what.

```python
# Staying put is deliberate: crossing into the next major would risk breaking
# changes the user did not ask for, so "no eligible version" means "no update".
recommended_version = current_version
```

```python
# ❌ Restates the code; adds nothing.
# Set the recommended version to the current version
recommended_version = current_version
```

Comment-worthy content: business rules, edge cases, architectural decisions, non-obvious ordering
requirements, and platform-specific workarounds. If a comment would restate the next line, delete
it.

Section banners are used to structure long modules:

```python
# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------
```

---

## Naming

| Kind | Convention | Example |
|---|---|---|
| Module | `snake_case` | `dependency_analyzer.py` |
| Class | `PascalCase` | `RequirementsParser` |
| Function / method | `snake_case` | `resolve_and_annotate_conflicts` |
| Private | leading underscore | `_find_cross_conflicts` |
| Constant | `UPPER_SNAKE_CASE` | `DEFAULT_TIMEOUT` |
| Module-private tunable | `_UPPER_SNAKE_CASE` | `_MAX_RESOLUTION_ITERATIONS` |
| Test function | `test_<behaviour>` | `test_major_boundary_is_never_crossed` |

Names should say what the value *means*, not what type it is: `retained_specs`, not `spec_list`.

---

## Structure

```python
"""One-line module summary.

Longer description: what this module owns and how it is meant to be used.
"""

from __future__ import annotations

# 1. standard library
import asyncio
from pathlib import Path

# 2. third party
import click
from packaging.version import parse

# 3. first party
from depkeeper.exceptions import DepKeeperError
from depkeeper.utils.logger import get_logger

logger = get_logger("module_name")

__all__ = ["PublicThing"]     # when the module has a curated public surface
```

Within a class, order members: public API first, then private helpers, then dunders. `mkdocs.yml`
sets `members_order: source`, so source order is what readers of the API page see.

---

## Error handling

| Rule | Detail |
|---|---|
| Raise a depkeeper exception, not a bare `Exception`. | Every one carries structured `details`. |
| Chain with `from exc`. | The original cause must survive. |
| Never swallow an exception silently. | Log at DEBUG at minimum, and say why in a comment. |
| Broad `except Exception` requires a comment. | The two existing cases are marked and justified. |
| Normalise filesystem errors to `FileOperationError`. | Callers handle one type. |
| Catch `NetworkError`, not `PyPIError`. | `PyPIError` is a subclass; the broader catch also covers timeouts and 5xx. |

---

## Logging

```python
logger.debug("Skipping %s: %s is already covered by '%s'", name, version, specs)
```

| Rule | Detail |
|---|---|
| Use `%s` placeholders, not f-strings. | Formatting is deferred until the record is emitted. |
| `logger = get_logger("<short name>")` at module level. | Bare names are prefixed with `depkeeper.`. |
| Never use `print()` or the console helpers for diagnostics. | `utils.console` is for user-facing output only. |
| Never log to stdout. | Log records go to stderr; stdout may carry a machine-readable payload. |

Level guidance:

| Level | Use for |
|---|---|
| `DEBUG` | Per-item decisions, cache behaviour, retries. |
| `INFO` | Phase progress and decisions a user might want to audit. |
| `WARNING` | Degraded behaviour the user should know about but which is not fatal. |
| `ERROR` | A failure that is being reported but not raised. |

---

## Async

| Rule | Detail |
|---|---|
| Network I/O is `async`. | All of it goes through `HTTPClient`. |
| Do not create an event loop in library code. | Commands own `asyncio.run`. |
| Share the `PyPIDataStore`. | This is what guarantees one fetch per package. |
| Bound concurrency with a semaphore, deduplicate with the in-flight map. | A semaphore alone cannot deduplicate. See [D2](../concepts/architecture.md#d2-request-coalescing-not-just-a-semaphore). |
| Use `asyncio.gather(..., return_exceptions=True)` for per-item work that must not abort the batch. | |

---

## Formatting

- 4-space indentation, no tabs.
- Target ~88 columns; do not reflow unrelated lines to satisfy it.
- LF line endings in the repository (enforced by pre-commit).
- One blank line between methods, two between top-level definitions.
- Trailing commas in multi-line literals and call sites.

---

## Anti-patterns

| Do not | Instead |
|---|---|
| Re-implement package-name normalisation. | `depkeeper.utils.naming.normalize_package_name`. |
| Re-implement version comparison or specifier evaluation. | Delegate to `packaging`. |
| Inline a magic number. | Add a named constant to `constants.py`. |
| Print from `core` or `models`. | Return data; let `commands` render it. |
| Perform I/O in a model. | Models are pure data plus behaviour. |
| Write a file directly. | Use `utils.filesystem.safe_write_file`. |
| Add a `>>>` example you have not run. | Omit it. |
