## Summary

<!-- What does this change, and why? -->

Closes #

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation / tooling only
- [ ] Breaking change (describe below)

## How was this tested?

<!-- Commands run, or tests added. -->

## Checklist

See [CONTRIBUTING.md](../CONTRIBUTING.md#pull-request-checklist).

- [ ] Tests added or updated (bug fixes include a regression test)
- [ ] `python -m pytest tests -q --no-cov` passes
- [ ] `python -m mypy depkeeper --python-version 3.13` reports no new errors
- [ ] `ruff format depkeeper tests` and `ruff check --select E9,F depkeeper tests` are clean
- [ ] Docs updated if behavior or public API changed
- [ ] `CHANGELOG.md` updated under **Unreleased**
- [ ] Code stays compatible with Python 3.8
- [ ] No change to what depkeeper recommends or writes, or it is described below

## Breaking changes / behavior notes

<!-- "None", or what changes for existing users and their requirements files. -->
