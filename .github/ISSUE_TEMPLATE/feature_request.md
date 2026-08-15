---
name: Feature Request
about: Suggest a new idea or enhancement for depkeeper
title: "[FEATURE] "
labels: ["enhancement"]
assignees: ""
---

## Summary

<!-- A short, clear description of the feature. -->

## Problem

<!-- What's currently difficult, missing or inefficient? Concrete example beats abstract description. -->

## Proposed solution

<!-- How should depkeeper behave after this is implemented? -->

### CLI example

```bash
depkeeper <command> --flag
```

### Python API example (optional)

<!-- Only if this touches the programmatic surface (depkeeper.core, depkeeper.models). -->

```python
from depkeeper.core import RequirementsParser
```

## Alternatives considered

<!-- Other approaches you considered, and why this one is better. Skip if there weren't any. -->

## Scope check

Per [CONTRIBUTING.md](../../CONTRIBUTING.md#ways-to-contribute), anything that changes what
depkeeper *writes* needs a design discussion before code — this issue is that discussion. Does
this change what gets recommended or written for an existing requirements file? If so, say what
changes and why it's still within a
[non-negotiable invariant](https://rahulkaushal04.github.io/depkeeper/concepts/#non-negotiable-invariants).

## Contribution interest

- [ ] I can submit a PR for this
- [ ] I can help test it
- [ ] I'm requesting this for someone else to implement

## Related issues

<!-- Link related feature requests, bugs or prior discussion. -->
