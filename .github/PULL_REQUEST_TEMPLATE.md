# Pull Request

Thank you for contributing to depkeeper. Please fill in enough detail for a reviewer to understand
the change without reading the whole diff first.

## Summary

<!-- What does this PR do, in one or two sentences? -->

## Motivation

<!-- What problem does this solve? Link the issue if one exists: Closes #123 -->

## Changes

<!-- Bullet list of what was added, removed, fixed or changed. -->

-

## How to test this

<!-- Exact commands or steps a reviewer should run. -->

```bash
depkeeper <command> ...
```

<!-- If this touches the Python API (depkeeper.core, depkeeper.models), show the real import: -->

```python
from depkeeper.core import RequirementsParser
```

## Checklist

Definition of done, per [CONTRIBUTING.md](../CONTRIBUTING.md#pull-request-expectations):

- [ ] `python -m pytest tests -q --no-cov` passes
- [ ] `python -m mypy depkeeper --python-version 3.13` reports no new errors
- [ ] `python -m compileall -q depkeeper` succeeds
- [ ] `pre-commit run --all-files` passes
- [ ] `python -m mkdocs build --strict` passes (if `docs/` or public docstrings changed)
- [ ] New behaviour has tests; fixed bugs have a regression test that fails without the fix
- [ ] Documentation updated — see the table in [CONTRIBUTING.md](../CONTRIBUTING.md#documentation-expectations)
- [ ] `CHANGELOG.md` updated under **Unreleased** for any user-visible change
- [ ] No [invariant](../CONTRIBUTING.md#invariants-you-must-not-break) is weakened, or this PR
      argues explicitly why it should be

## Behavioural impact

<!--
Does this PR change what depkeeper recommends or writes for any existing requirements file?
If yes, this is at minimum a minor release (see CONTRIBUTING.md) — describe what changes and why.
If no, say so explicitly.
-->

## Related issues

<!-- Closes #, relates to # -->
