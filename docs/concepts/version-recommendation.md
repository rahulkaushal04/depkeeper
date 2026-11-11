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
| Retained specs | The requirement's upper bounds, exclusions and wildcard bands, plus the bound implied by `~=` and any `-c` constraint specs. |
| Series | Conda fuzzy specs only (`numpy=1.24`): the number of significant components. |
| Release history | `releases` from the PyPI JSON API (upload times included). |
| `requires_python` per release | Taken from the first uploaded file of each release that declares it. |
| Target Python | `--python-version`, else config `python_version`, else the file's `requires-python` / conda `python` pin (lowest supported minor), else the running interpreter. |
| Policy | Global `versioning`, `min_age`, `--allow-major`, `--max-update`, and per-package `[depkeeper.packages.<name>]` (`hold`, `ignore`, `max_update`, `allow_prerelease`, `allow_major`, `versioning`). |

## Output

A `Package` carrying `current_version`, `latest_version`, `recommended_version`, the detected
`versioning` scheme, a `metadata` mapping holding `requires_python` for the current, latest and
recommended releases, and hints (`major_available`, `cooldown_skipped`, `held`, `ignored`).

---

## Step 1 — Infer the current version

```text
if any specifier is a non-wildcard "==" or "===":   → that version   (even next to "!=")
elif --strict-version-matching:                       → None
else: first specifier whose operator is >=, > or ~=   → that version
else:                                                 → None
```

| Requirement | Inferred | Note |
|---|---|---|
| `requests==2.28.0` | `2.28.0` | |
| `requests==2.28.0,!=2.28.1` | `2.28.0` | An exact pin anchors the version even alongside `!=`. |
| `requests==2.*` | *(none)* | A wildcard is a band, not a pin. |
| `flask>=2.0,<2.3` | `2.0` | First floor operator wins. |
| `click~=8.0` | `8.0` | |
| `django<5.0` | *(none)* | Cap only. |
| `certifi` | *(none)* | |

Reading `>=2.0` as "currently on 2.0" is a deliberate approximation. It is what anchors the major
boundary for ranged requirements, and it is why `django>=3.2,<5.0` is capped at the newest `3.x`
rather than moving to `4.x`.

> [!WARNING]
> **Consequence of inference**
>
> `django>=3.2,<5.0` **will not** be upgraded to `4.2.x` by default, even though your own range
> permits it. depkeeper treats the floor as the installed version and the major boundary as
> absolute unless you opt in. Either pass `--allow-major django` (the `<5.0` still applies), or
> edit the floor by hand: `django>=4.2,<5.0`.

## Step 2 — Build the candidate list

Candidates are drawn from the `releases` map of the PyPI JSON API and filtered, in order:

1. **Phantom and yanked releases removed.** A release with no files, or whose files are *all*
   yanked, is skipped (a release with at least one unyanked file is kept).
2. **Non-PEP 440 tags removed.** Anything `packaging` cannot parse is skipped silently.
3. **Pre-releases removed**, unless that package's policy sets `allow_prerelease`.
4. **Major-version filter.** When a current version is known and the scheme is semver, only
   releases sharing its major component survive — unless the package is opted in to majors
   (see [below](#the-major-version-boundary)). Calver packages have no major filter.
5. **Python compatibility filter.** Releases whose `requires_python` excludes the target Python
   are dropped.
6. **Declared-constraint filter.** Releases rejected by the retained specs, the `~=`-implied
   major bound or `-c` constraint specs are dropped.
7. **`max_update` cap.** A per-package `max_update` and the run-wide `--max-update` (the stricter
   wins) drop upgrades larger than the cap for every package, before a candidate is chosen, so
   `requests==2.25.0 --max-update patch` gets `2.25.1` rather than nothing. Calver `year`/`month`
   rank as `minor`.
8. **Series filter** (conda fuzzy specs and `~=` lines). Only versions in a *newer series*
   survive: with `numpy=1.24` (series 2) `1.24.9` is not an update but `1.25.0` is. The same
   holds for a compatible-release line, at the precision it is written: `PyYAML~=5.4` already
   allows `5.4.1` and the line cannot say more, so `5.4.1` is not an update (`check` and
   `update` agree, `--fail-on updates` stays green), while `~=5.4.0` moves to `~=5.4.1` and
   `~=5.3` moves to `~=5.4` when 5.4.x exists. `--pin` still writes the newest release in the
   series (`==5.4.1`). Plain floors (`>=`, `>`) move at full precision; `==` pins, wildcard
   bands, ranges and `!=` are unaffected.
9. **Cooldown** (`min_age`). Applied last, while choosing; see [Release cooldown](#release-cooldown-min_age).

The list is sorted descending, so the recommendation is simply the first survivor.

## Step 3 — Choose

| Situation | Result |
|---|---|
| Package has `hold` or `ignore` policy | The current version is kept (nothing is proposed). |
| Candidates remain after all filters | The highest candidate (after the cooldown). |
| No candidate | **Stay on the current version.** A `WARNING` names the Python version and constraints. For a conda series spec the stay is silent. |
| Current version is not PEP 440 parseable | `recommended_version` is `None`; a warning is logged. If no major component can be read, the package stays put. |
| No current version | Highest compatible stable release across **all** majors (there is no anchor to hold), still subject to Python, constraints and cooldown. |
| PyPI metadata unavailable | An *unavailable stub* — see [below](#unavailable-packages). |

---

## The major version boundary

**By default a recommendation never crosses a major version boundary when a current version is
known.** The boundary is applied at candidate-selection time in the checker and in the resolver's
search strategies, so no code path can circumvent it for a package that has not opted in.

```text
urllib3==1.26.0     latest 2.8.0     → recommended 1.26.20   (major available: 2.8.0)
flask>=2.0,<2.3     latest 3.1.3     → recommended 2.2.5
requests==2.28.0    latest 2.34.2    → recommended 2.34.2   (same major, so full upgrade)
```

When a higher major exists that you could opt in to, depkeeper says so:
`major available: urllib3 2.8.0 (use --allow-major urllib3)`.

### Opting in to majors

Opt in per package with `--allow-major PKG` (repeatable; `'*'` for all) or `allow_major = true`
under `[depkeeper.packages.<name>]`. Opting in removes **only depkeeper's own boundary**. Every
other rule still applies:

- your declared upper bounds (`<6`, `!=`, wildcard bands) and any `-c` constraint caps,
- the major bound implied by `~=` (`click~=8.0` means `>=8.0,<9`, so it stays on 8.x),
- `--max-update` and the package's `max_update` (these apply to every package, opted in or not),
- target-Python compatibility, yanked/pre-release exclusion and the `min_age` cooldown.

The conflict resolver's searches are unbounded for opted-in packages too, so it can reach the same
versions the checker may recommend. When a cap is what holds an opted-in package back, the note reads
`major available: PKG X (blocked by max_update; raise --max-update)`. `update` warns
`N major upgrade(s) applied` after applying one; run `--verify` and your tests.

### Calendar versions

`versioning = "auto"` (the default) picks **calver** when:

- the current version (or, with none, the newest release) leads with a plausible 4-digit year,
  `1990` through *this year + 1* (`2024.8.30`); or
- the **most recent** stable releases look like dates. Starting from the newest, depkeeper reads
  releases (pre-, post- and dev-releases and unparsable versions are skipped) until it has seen at
  least 8 spanning two distinct first components, looking back at most 40. Every one must have either a
  4-digit first component (1990 through *this year + 1*) or a two-digit first component 18 through
  *this year + 1* with a second component 0-12 (black `24.2.0`, pip `23.0`, packaging `24.0`, attrs
  `24.1`). Older history is ignored, so pip's `1.x`-`10.x` era does not matter.

A lone `23.1.0` is never guessed to be calver, and a project with fewer than 8 recent releases or a
single first component stays semver (virtualenv `20.x`, setuptools, pytest and cryptography are semver).
**Known limit:** a semver project whose major reaches 18 or more while its minors stay at 12 or below
looks like calver; set `versioning = "semver"` for it. Override per package with `versioning = "calver"`
or `"semver"` (or globally in config). Calver packages have no major boundary: updates cross the
leading year and are labelled `year`, `month` or `patch`.

```text
certifi==2023.7.22  → certifi==2026.10.23   (update type: year)
```

For `--fail-on` / `--max-update`, `year` and `month` count as `minor`. See
[Known limitations](../reference/limitations.md#calendar-versioning-heuristics).

### Rationale

Crossing a major version is, by SemVer convention, permission to break the caller. A tool that
edits your requirements file unattended must not make that decision for you. depkeeper's default
contract is "the largest upgrade that carries no *declared* breaking-change risk"; you widen it
explicitly, per package.

---

## Python compatibility filtering

Each candidate's `requires_python` specifier is evaluated against the target Python. The target
is resolved by precedence:

1. `--python-version X.Y`
2. config `python_version`
3. the file's own declaration: `project.requires-python` of `pyproject.toml`, or the conda
   `python` pin. depkeeper takes the **lowest supported minor** (`>=3.8.5` gives `3.8`), so a
   candidate that works there works on every newer supported Python. With several files the
   lowest minimum wins. A bare major or upper-bound-only spec names no target.
4. the running interpreter, as `major.minor.micro`.

`requirements.txt` carries no declaration, so it falls through to the running interpreter unless
you pass a flag or set config.

| Case | Behaviour |
|---|---|
| `requires_python` absent | Treated as compatible. This matches pip. |
| `requires_python` unparseable | Treated as compatible. Malformed upstream metadata must not exclude an installable release. |
| Specifier excludes the target | Candidate dropped. |

### Requirements with a Python marker

A line whose own environment marker is built only from `python_version` / `python_full_version`
is evaluated for the target Python. When the marker is **false** (`requests==2.25.0 ;
python_version<"3.9"` with target 3.12) the line does not apply there: it is never changed, never
part of the conflict analysis, and is reported as `not applicable for target Python 3.12` (status
`not-applicable`, table label `[N/A]`, simple label `[NOT-APPLICABLE]`, a Markdown section, and
`status: "not-applicable"` plus `target_python` in `json`/`json-v2`). It does not count as an
update, so `--fail-on` ignores it. When the marker is **true** the normal Python filter applies.
Markers that also use the platform, an extra or any other variable cannot be judged for a Python
alone and are treated as applicable, as are lines without a marker. To maintain the line for a
different Python, run depkeeper with that `--python-version`.

> [!CAUTION]
> **The fallback is depkeeper's own interpreter**
>
> If depkeeper runs on Python 3.8 and your service targets 3.12 and nothing declares that, every
> release that dropped 3.8 is invisible and recommendations will lag. Pass
> `--python-version 3.12`, set `python_version` in config, or install depkeeper into the project
> environment.

### Metadata source caveat

`requires_python` is read from the **first uploaded file of a release that declares it**. In
practice releases are uniform; where they are not, the value shown in the `Python Support` column
may not describe every artefact of that release.

---

## Release cooldown (`min_age`)

`--min-age 7d` (units `d`, `h`, `w`; a bare number is days) or config `min_age` withholds versions
uploaded less than that long ago. depkeeper picks the newest *older* eligible version instead and
shows the withheld one under the `Recommended` cell. It never falls back to a version below the
current one (the package simply stays), and a release with no upload date is treated as old (a
warning is logged once per package). The cooldown also applies to opt-in majors and to versions
the conflict resolver picks.

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
celery[redis]>=5.0,<6.0    → celery[redis]>=5.7.0,<6.0
click~=8.0                 → click~=8.5
certifi                    → certifi==2026.10.23
```

### Retained specs feed back into selection

The retained specs are forwarded into the checker, together with the major bound implied by `~=` (PEP 440: `~=7.0` is `>=7.0,<8`; only the major level is added) and any `-c` constraint specs (which are never rewritten), so a version your file forbids is never
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
Without this, `click~=8.5` would report `8.5.0` as an available update on every run forever,
because `~=` keeps the author's two-component precision. This is what makes repeated runs
idempotent.

### `--pin` overrides all of it

`--pin` replaces the entire specifier set with `==<version>`:

```text
celery[redis]>=5.0,<6.0    → celery[redis]==5.7.0
flask>=2.0,<2.3            → flask==2.2.5
```

Extras, markers and comments survive; version semantics do not. Use it for deployable
applications; avoid it for libraries. See
[Updating dependencies → Pin mode](../guides/updating-dependencies.md#pin-mode).

---

## Pre-releases

Pre-releases are excluded from every candidate list by default. There is no `--pre` flag; a
package can opt in with `allow_prerelease = true` under `[depkeeper.packages.<name>]`.

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
| `year` / `month` / `patch` | Calver packages: first, second, or later differing component. |
| `update` | Release segments identical — a pre-release promotion or metadata-only change. |
| `unknown` | Either version is not PEP 440 parseable, or both are `None`. |

Missing components are padded with zeros, so `2` and `2.0.0` compare equal.

> [!NOTE]
> **`major` can appear in output**
>
> Classification is independent of the boundary rule. A `major` update type appears for a
> package opted in with `--allow-major`, or when a package with no current version gets its first
> pin. Without an opt-in it is never an automatically proposed upgrade.

---

## Unavailable packages

When PyPI metadata cannot be fetched — a 404, an unexpected status, a timeout, or an exhausted
`429` budget — the checker returns an **unavailable stub** rather than dropping the package or
failing the run:

```python
Package(name=..., current_version=<inferred>, latest_version=None, recommended_version=None)
```

Rendering (with or without conflict checking):

| Format | Result |
|---|---|
| table | `[ERROR]` row, `Latest` = `error` |
| simple | `[NO-UPDATE]` line, then `[ERROR] N package(s) could not be checked ...` |
| json | `"status": "no-update"` plus `"error": "Package information unavailable"` |

`check` exits `4` when at least one package (other than direct URL/editable requirements, which
are never on PyPI) could not be looked up; `update` still applies the rest and also exits `4`.
A lookup failure is never reported as "up to date". The resolver does not give a stub a
recommendation, and no update is ever proposed for it.
