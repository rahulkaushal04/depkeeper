---
title: Contributing
description: How to contribute to depkeeper — orientation, workflow and standards
---

# Contributing

Contributions are welcome. This section documents the standards a change must meet before it can
be merged.

<div class="grid cards" markdown>

- :material-tools:{ .lg .middle } **[Development setup](development-setup.md)**

    ---

    Environment, tooling, verification commands and the change workflow.

- :material-format-align-left:{ .lg .middle } **[Code style](code-style.md)**

    ---

    Typing, docstrings, comments and naming conventions — all enforced.

- :material-test-tube:{ .lg .middle } **[Testing](testing.md)**

    ---

    Suite layout, shared fixtures, isolation traps and what must be tested.

- :material-puzzle:{ .lg .middle } **[Extending depkeeper](extending.md)**

    ---

    Where to add a flag, a format, a check or a parser, and the invariants you must not break.

- :material-tag:{ .lg .middle } **[Release process](release-process.md)**

    ---

    Versioning, changelog, build and publish steps.

</div>

---

## Before you start

Read [Core concepts](../concepts/index.md), in particular the
[system invariants](../concepts/index.md#non-negotiable-invariants). depkeeper's value is that its
guarantees hold; most rejected changes are rejected because they quietly weaken one.

---

## Ways to contribute

| Contribution | What to include |
|---|---|
| **Bug report** | Minimal reproducer requirements file, exact command, `depkeeper -vv … 2> debug.log`, `depkeeper --version`, `python --version`, expected vs actual. |
| **Bug fix** | A failing test first, then the fix. State which invariant was violated. |
| **Feature** | Open an issue describing the problem before writing code. Features that change what gets *written* need a design discussion. |
| **Documentation** | Verify claims against the implementation. Every behavioural statement in these docs is verified; keep it that way. |
| **Performance** | Include a before/after measurement and the workload used. |

Security issues must **not** be filed as public issues — follow the
[security policy](../community/security.md).

---

## Definition of done

A change is ready to merge when all of the following hold:

- [ ] `python -m pytest tests -q --no-cov` passes.
- [ ] `python -m mypy depkeeper --python-version 3.13` reports no new errors.
- [ ] `python -m compileall -q depkeeper` succeeds.
- [ ] `pre-commit run --all-files` passes.
- [ ] New behaviour has tests; fixed bugs have regression tests.
- [ ] Public API changes are reflected in the docstrings **and** in the affected
      documentation pages.
- [ ] No system invariant is weakened, or the change explicitly argues why the invariant should
      change.
- [ ] The changelog entry is added when the change is user-visible.

---

## Commit convention

Conventional Commits:

```text
feat(update): add --pin to replace declared ranges with exact pins
fix(parser): join backslash line continuations
docs(reference): document the JSON schema
test(analyzer): pin cumulative-conflict behaviour
refactor(core): extract the alternative search from the resolution loop
chore(deps): bump httpx floor
```

The scope is the module or subsystem. The body should state *why*, not what — the diff already
says what.

---

## Code of conduct

Participation is governed by the [Code of Conduct](../community/code-of-conduct.md).
