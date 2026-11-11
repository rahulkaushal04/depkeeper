---
title: Extending depkeeper
description: Where to add behaviour, and the invariants an extension must not break
---

# Extending depkeeper

A map for contributors who need to add capability rather than fix a defect. Read
[Architecture](../concepts/architecture.md) first.

---

## Rules that bind every extension

| Rule | Consequence if broken |
|---|---|
| A recommendation never crosses a major boundary when a current version is known, unless the package is opted in (`--allow-major` / `allow_major`). | The core safety promise is void. |
| A recommendation never violates the declared constraints (except under `--pin`). | depkeeper writes unsatisfiable lines. |
| `Package.recommended_version` equals the resolver's `resolved` value. | The report and the write disagree. |
| Names are compared only in PEP 503 canonical form. | Cross-package lookups silently miss. |
| `check` never writes. | A read-only command becomes dangerous. |
| Machine-readable formats emit only the payload on stdout. | Every downstream parser breaks. |
| `models` do no I/O; `core` does no printing. | The layering collapses and testing gets expensive. |

---

## Add a CLI flag

1. Add the `@click.option` to `commands/check.py` or `commands/update.py`.
2. Thread it through the `_check_async` / `_update_async` signature. Do not read globals.
3. If it should be persistable, add it to `DepKeeperConfig`, to `_parse_section`'s `known_top`
   set with type validation, and give the Click option `default=None` so "unset" is
   distinguishable from "explicitly false".
4. Document it in [CLI commands](../reference/cli-commands.md) and, if configurable, in
   [Configuration options](../reference/configuration-options.md).
5. Test the flag on, the flag off, and its interaction with the config file.

The precedence contract is `defaults < config file < CLI flag`. A flag that cannot express
"unset" cannot participate in it, so add a new boolean as a `--x/--no-x` pair with `default=None`.

## Add an output format

1. Add the value to the `--format` `click.Choice`.
2. Write a `_display_<name>(packages)` renderer in `commands/check.py`.
3. Decide whether it is human-readable. If it is machine-readable, it **must**:
   - be covered by `_status_stream_is_stderr` so all status output goes to stderr,
   - emit a valid document even for an empty result set,
   - avoid Rich markup interpretation (pass `markup=False`, or use the builtin `print`).
4. Derive state from `Package.get_display_data()` / `get_status_summary()`. Never recompute
   status in a renderer — that is how the table and simple ladders drifted apart.
5. Add stream-separation tests modelled on `tests/test_commands/test_check_output_streams.py`.

## Add a check or a rule

New per-package logic belongs in `core/checker.py`; new cross-package logic belongs in
`core/dependency_analyzer.py`.

- Filters go into the candidate-selection path, not into a post-hoc pass, so no later code path
  can reintroduce a rejected candidate.
- New tunables go into `constants.py` (public) or as a module-private `_UPPER_SNAKE_CASE` constant
  next to the algorithm that uses them.
- Anything that alters what is written needs boundary-case tests: empty candidate list, unparseable
  version, missing metadata, constraint-excluded target.

## Add a data source

All network access goes through `utils/http.py` and is cached by `core/data_store.py`.

- Add an accessor to `PyPIDataStore` and route it through `_coalesce` so it inherits per-key
  deduplication and cancellation safety.
- Do not cache failures at the data-store level; the checker legitimately retries after a
  swallowed prefetch error. Negative caching belongs to the consumer, as the analyzer does it.
- Normalise the cache key with `normalize_package_name`.

## Support another file format

Write a `SourceAdapter` subclass in `depkeeper/core/sources/` and register it in
`registry._register_builtins`. The step-by-step guide is the docstring at the top of
`depkeeper/core/sources/base.py`; `requirements_txt.py`, `pyproject_toml.py` and `conda_yaml.py`
are working examples.

- Edit in place: comments, order, quoting and line endings must survive byte for byte.
- Adapters never touch the disk when updating; the caller owns atomic writes, backups and rollback.
- Reuse `Requirement.update_version` / `rewrite_version_specs` so `--pin` and upper-bound
  preservation behave the same in every format.
- Test parse-then-update round trips under `tests/test_sources/`, including a no-op update that
  leaves bytes identical.

## Support a private index

Requires: making `PYPI_JSON_API` configurable, deciding how `--index-url` lines in a requirements
file interact with that configuration, and handling authentication — none of which exists today.
Design discussion first.

---

## Extension checklist

- [ ] Which layer owns this? (`commands` / `core` / `models` / `utils`)
- [ ] Does it preserve every invariant above?
- [ ] Are new tunables named constants?
- [ ] Is all network access routed through `HTTPClient` and cached by `PyPIDataStore`?
- [ ] Are names canonicalised?
- [ ] Do machine-readable outputs still own stdout exclusively?
- [ ] Are boundary cases tested (empty, unparseable, missing metadata, excluded target)?
- [ ] Are [CLI commands](../reference/cli-commands.md),
      [Error reference](../reference/errors.md) and the relevant concept page updated?
- [ ] Do all relative links in the docs still resolve?
