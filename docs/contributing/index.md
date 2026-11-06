---
title: Contributing
description: How to contribute to depkeeper — orientation, workflow and standards
---

# Contributing

Contributions are welcome. This section documents the standards a change must meet before it can
be merged.

- **[Development setup](development-setup.md)** — Environment, tooling, verification commands and the change workflow.
- **[Code style](code-style.md)** — Typing, docstrings, comments and naming conventions — all enforced.
- **[Testing](testing.md)** — Suite layout, shared fixtures, isolation traps and what must be tested.
- **[Extending depkeeper](extending.md)** — Where to add a flag, a format, a check or a parser, and the invariants you must not break.
- **[Release process](release-process.md)** — Versioning, changelog, build and publish steps.

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
- [ ] `python -m ruff format --check depkeeper tests` and `python -m ruff check --select E9,F depkeeper tests` are clean.
- [ ] `pre-commit run --all-files` passes.
- [ ] New behaviour has tests; fixed bugs have regression tests.
- [ ] Public API changes are reflected in the docstrings **and** in the affected
      documentation pages.
- [ ] No system invariant is weakened, or the change explicitly argues why the invariant should
      change.
- [ ] The changelog entry is added when the change is user-visible.

---

## Commit convention

Short, imperative subject lines with no required prefix:

```text
Fix duplicate-requirement resolution
Add --allow-major for opt-in major upgrades
Document the JSON schema
```

Squash-merged PRs end with the PR number. The body should state *why*, not what — the diff already
says what.

---

## Code of conduct

Participation is governed by the [Code of Conduct](../community/code-of-conduct.md).
