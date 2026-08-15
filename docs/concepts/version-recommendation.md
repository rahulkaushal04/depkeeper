---
title: Version Recommendation
description: How depkeeper chooses the target version for a single package
---

# Version Recommendation

This page describes what `VersionChecker` does for **one** package, in isolation. Cross-package
adjustment happens afterwards and is described in [Conflict resolution](conflict-resolution.md).

---

## Inputs

| Input | Source |
|---|---|
| Package name | The parsed requirement, canonicalised per PEP 503. |
| Current version | Inferred from the requirement's specifiers (see below). |
| Retained specs | The requirement's upper bounds, exclusions and wildcard bands. |
| Release history | `releases` from the PyPI JSON API. |
| `requires_python` per release | Taken from the first uploaded file of each release that declares it. |
| Running Python version | `sys.version_info` of the interpreter executing depkeeper. |

## Output

A `Package` carrying `current_version`, `latest_version`, `recommended_version` and a `metadata`
mapping holding `requires_python` for the current, latest and recommended releases.

---

## Step 1 — Infer the current version

```text
if exactly one specifier and it is "==":   → that version
elif --strict-version-matching:            → None
else: first specifier whose operator is >=, > or ~=  → that version
else:                                      → None
```

| Requirement | Inferred | Note |
|---|---|---|
| `requests==2.28.0` | `2.28.0` | |
| `requests==2.28.0,!=2.28.1` | *(none)* | Not a *sole* `==` specifier, and no floor operator. |
| `flask>=2.0,<2.3` | `2.0` | First floor operator wins. |
| `click~=8.0` | `8.0` | |
| `django<5.0` | *(none)* | Cap only. |
| `certifi` | *(none)* | |

Reading `>=2.0` as "currently on 2.0" is a deliberate approximation. It is what anchors the major
boundary for ranged requirements, and it is why `django>=3.2,<5.0` is capped at the newest `3.x`
rather than moving to `4.x`.

!!! warning "Consequence of inference"

    `django>=3.2,<5.0` **will not** be upgraded to `4.2.x`, even though your own range permits it.
    depkeeper treats the floor as the installed version and the major boundary as absolute. To
    move across the boundary, edit the floor by hand:
    `django>=4.2,<5.0`, then re-run depkeeper.

## Step 2 — Build the candidate list

Candidates are drawn from `releases` and filtered, in order:

1. **Phantom releases removed.** A release with no uploaded files is skipped (yanked-empty or
   reserved versions).
2. **Non-PEP 440 tags removed.** Anything `packaging` cannot parse is skipped silently.
3. **Pre-releases removed.** `is_prerelease` candidates never appear.
4. **Major-version filter.** When a current version is known, only releases sharing its major
   component survive.
5. **Python compatibility filter.** Releases whose `requires_python` excludes the running
   interpreter are dropped.
6. **Declared-constraint filter.** Releases rejected by the requirement's retained specs are
   dropped.

The list is sorted descending, so the recommendation is simply element 0.

## Step 3 — Choose

| Situation | Result |
|---|---|
| Candidates remain after all filters | The highest candidate. |
| No candidate in the current major | **Stay on the current version.** A `WARNING` is logged naming the major, the Python version and the constraints. |
| Current version is not PEP 440 parseable | `recommended_version` is `None`; a warning is logged. |
| No current version | Highest compatible stable release across **all** majors (there is no anchor to hold). |
| PyPI metadata unavailable | An *unavailable stub* — see [below](#unavailable-packages). |

---

## The major version boundary

**A recommendation never crosses a major version boundary when a current version is known.**

This is invariant 1 of the system. It is applied at candidate-selection time in the checker and
in both of the resolver's search strategies, so no code path can circumvent it.

```text
urllib3==1.26.0     latest 2.7.0     → recommended 1.26.20
flask>=2.0,<2.3     latest 3.1.3     → recommended 2.2.5
requests==2.28.0    latest 2.34.2    → recommended 2.34.2   (same major, so full upgrade)
```

### It applies to calendar versions too

The rule is purely positional: it compares `release[0]`. For a package versioned `2023.7.22`, the
"major" is `2023`, so depkeeper will never move it to a `2024.x` release.

```text
certifi==2023.7.22  latest 2026.7.22 → recommended 2023.11.17
```

This is usually *not* what you want for date-versioned packages such as `certifi`, `pytz` or
`tzdata`. Handle those by editing the pin manually, or by leaving them unversioned so depkeeper
picks the newest compatible release. Tracked in
[Known limitations](../reference/limitations.md#calendar-versioning-hits-the-major-boundary).

### Rationale

Crossing a major version is, by SemVer convention, permission to break the caller. A tool that
edits your requirements file unattended must not make that decision. depkeeper's contract is
"the largest upgrade that carries no *declared* breaking-change risk".

---

## Python compatibility filtering

Each candidate's `requires_python` specifier is evaluated against
`f"{major}.{minor}.{micro}"` of the interpreter running depkeeper.

| Case | Behaviour |
|---|---|
| `requires_python` absent | Treated as compatible. This matches pip. |
| `requires_python` unparseable | Treated as compatible. Malformed upstream metadata must not exclude an installable release. |
| Specifier excludes the interpreter | Candidate dropped. |

!!! danger "The interpreter is depkeeper's, not your project's"

    If depkeeper runs on Python 3.8 and your service targets 3.12, every release that dropped 3.8
    support is invisible to depkeeper, and recommendations will silently lag. Install depkeeper
    into the environment whose requirements file it manages, or use
    `pipx install --python python3.12 depkeeper`. There is no flag to override the target
    interpreter in 0.1.x — see [Limitations](../reference/limitations.md#no-target-python-override).

### Metadata source caveat

`requires_python` is read from the **first uploaded file of a release that declares it**. Releases
whose wheels disagree with their sdist are read from whichever file appears first in the API
response. In practice releases are uniform; where they are not, the value shown in the
`Python Support` column may not describe every artefact of that release.

---

## Constraint preservation

A rewrite moves only the **floor** of a requirement. Everything else you wrote is a deliberate
compatibility statement and is copied verbatim.

| Operator | Classification | On rewrite |
|---|---|---|
| `>=` | floor | rewritten to `>=<new>` |
| `>` | floor | **widened** to `>=<new>` so the selected version is itself installable |
| `~=` | floor | rewritten keeping the author's precision (`~=2.0` + `2.3.3` → `~=2.3`) |
| `==` (non-wildcard) | exact pin | repinned to `==<new>` |
| `===` | exact pin | repinned |
| `<`, `<=` | retained | copied verbatim |
| `!=` | retained | copied verbatim |
| `==2.*` (wildcard) | retained | copied verbatim |

Worked examples, all verified:

```text
requests==2.28.0           → requests==2.34.2
flask>=2.0,<2.3            → flask>=2.2.5,<2.3
celery[redis]>=5.0,<6.0    → celery[redis]>=5.6.3,<6.0
click~=8.0                 → click~=8.4
certifi                    → certifi==2026.7.22
```

### Retained specs feed back into selection

The retained specs are forwarded into the checker, so a version your file forbids is never
proposed in the first place. `flask>=2.0,<2.3` is capped at `2.2.5`; depkeeper does not propose
`2.3.3` and then discover at write time that it is unsatisfiable.

There are two remaining guards, because the conflict resolver can still propose a version the
checker filtered:

- `_find_updates` skips a target excluded by the retained specs and prints
  `Skipping <pkg>: <version> is excluded by the declared constraint '<specs>' (use --pin to replace the constraint)`.
- `Requirement.update_version` raises `ValueError` (surfaced as a `DepKeeperError`) if it is ever
  asked to write an unsatisfiable line.

### Convergence

A target already covered by the declared floor produces a byte-identical line and is skipped.
Without this, `click~=8.4` would report `8.4.2` as an available update on every run forever,
because `~=` keeps the author's two-component precision. This is what makes repeated runs
idempotent.

### `--pin` overrides all of it

`--pin` replaces the entire specifier set with `==<version>`:

```text
celery[redis]>=5.0,<6.0    → celery[redis]==5.6.3
flask>=2.0,<2.3            → flask==2.2.5
```

Extras, markers and comments survive; version semantics do not. Use it for deployable
applications; avoid it for libraries. See
[Updating dependencies → Pin mode](../guides/updating-dependencies.md#pin-mode).

---

## Pre-releases

Pre-releases are excluded unconditionally from every candidate list. There is no
`--pre` flag.

A consequence: if your file pins a pre-release (`pkg==2.0.0rc1`), depkeeper anchors the major
boundary to `2` and recommends the highest **stable** `2.x`, which is a legitimate upgrade path.
If no stable `2.x` exists, the package stays where it is.

A `--pre` line inside the requirements file is recognised as a pip global option and ignored — it
does not change depkeeper's behaviour.

---

## Update-type classification

`current → target` is classified for display and for the JSON `update_type` field:

| Result | Condition |
|---|---|
| `new` | No current version. |
| `same` | Versions compare equal. |
| `downgrade` | Target is lower. |
| `major` / `minor` / `patch` | First differing component of the `(major, minor, patch)` triple. |
| `update` | Release segments identical — a pre-release promotion or metadata-only change. |
| `unknown` | Either version is not PEP 440 parseable, or both are `None`. |

Missing components are padded with zeros, so `2` and `2.0.0` compare equal.

!!! note "`major` can appear in output"

    Classification is independent of the boundary rule. A `major` update type appears when a
    *downgrade* crosses a major, or when a package with no current version gets its first pin.
    It never appears as an automatically proposed upgrade.

---

## Unavailable packages

When PyPI metadata cannot be fetched — a 404, an unexpected status, a timeout, or an exhausted
`429` budget — the checker returns an **unavailable stub** rather than dropping the package or
failing the run:

```python
Package(name=..., current_version=<inferred>, latest_version=None, recommended_version=None)
```

Rendering:

| Format | Result |
|---|---|
| table | `[ERROR]` row, `Latest` = `error` |
| json, `--no-check-conflicts` | `"status": "no-update"` plus `"error": "Package information unavailable"` |
| json, conflict checking enabled (default) | `"status": "latest"` with `recommended` equal to `current` |

The last row is a real inconsistency: the resolver initialises its update set from
`recommended_version or current_version`, so a stub acquires a recommendation equal to its current
version and is no longer distinguishable from an up-to-date package in JSON. If your automation
must detect unreachable packages, run with `--no-check-conflicts`, or key on the `error` field
rather than the status. Tracked in
[Known limitations](../reference/limitations.md#unavailable-packages-look-up-to-date-in-json).

No update is ever proposed for a stub: `recommended_version` equals `current_version`, so
`has_update()` is false.
