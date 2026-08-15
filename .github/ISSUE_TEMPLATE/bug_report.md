---
name: Bug Report
about: Report unexpected behavior or an error in depkeeper.
title: "[BUG] "
labels: ["bug"]
assignees: ""
---

<!--
A report we can reproduce gets fixed far faster than one we can't. See SUPPORT.md for the same
list with more context: https://github.com/rahulkaushal04/depkeeper/blob/main/SUPPORT.md
-->

## Summary

<!-- What's happening, in one or two sentences. -->

## Environment

- **depkeeper version:** (`depkeeper --version`)
- **Python version:** (`python --version` — this matters more than usual: depkeeper filters
  candidate versions against the interpreter *it* runs on, so a version mismatch is a common
  cause of "the recommendation looks wrong")
- **OS:**
- **Installed via:** pip / pipx / source

## Requirements file

<!-- The SMALLEST file that reproduces the issue. Trim it down before pasting — a 200-line file
     that happens to trigger the bug is much harder to act on than a 3-line one that isolates it. -->

```text
# paste the minimal requirements.txt snippet here
```

## Command

<!-- The exact command you ran. -->

```bash
depkeeper <command> <options>
```

## Expected behavior

<!-- What you expected to happen. -->

## Actual behavior

<!-- What actually happened. Paste the full error output or traceback below, not a screenshot. -->

```text
<output here>
```

## Diagnostic log

<!-- Re-run with -vv and attach the result; this is usually what actually gets the bug fixed. -->

```bash
depkeeper -vv <command> <options> 2> debug.log
```

<details>
<summary>debug.log</summary>

```text
<paste debug.log contents here>
```

</details>

## Additional context (optional)

<!-- Intermittent vs consistent? Worked in a previous version? Non-default configuration
     (depkeeper.toml / pyproject.toml)? A workaround you found? -->
