---
title: JSON Output
description: Schema for depkeeper check --format json
---

# JSON Output

`depkeeper check --format json` writes a JSON array to stdout and nothing else. Every diagnostic
— status messages, warnings, errors and log records — goes to stderr, so the payload stays
parseable at any verbosity.

```bash
depkeeper -vv check --format json | jq .
```

An empty result set still emits a document:

```json
[]
```

This is guaranteed on all early-return paths, including "no packages found in the requirements
file" and "nothing to display after filtering".

---

## Top level

An array of package objects, in the order the requirements appear in the file (with `-r` includes
flattened in place).

---

## Package object

| Field | Type | Always present | Description |
|---|---|---|---|
| `name` | string | ✅ | PEP 503 canonical package name. |
| `status` | string | ✅ | See [status values](#status-values). |
| `versions` | object | — | Present when at least one version slot is known. |
| `versions.current` | string | — | Version inferred from the requirement. |
| `versions.latest` | string | — | PyPI `info.version`. Absent when metadata could not be fetched. |
| `versions.recommended` | string | — | The version `update` would apply. |
| `update_type` | string | — | Present only when `status` is `outdated` or `downgrade`. |
| `python_requirements` | object | — | `requires_python` per version slot. |
| `python_requirements.current` | string | — | For the current version. |
| `python_requirements.latest` | string | — | For the latest version. |
| `python_requirements.recommended` | string | — | For the recommended version. |
| `conflicts` | array | — | Present only when conflicts were recorded. |
| `error` | string | — | Present only when `status` is `no-update`. Always `"Package information unavailable"`. |

**Only `name` and `status` are guaranteed.** Treat every other key as optional; use `//` defaults
in `jq` and `.get()` in Python.

### Status values

| Value | Condition |
|---|---|
| `no-update` | No recommended version — PyPI metadata was unavailable. Accompanied by `error`. |
| `install` | No current version, but a recommendation exists. `update` will add a pin. |
| `downgrade` | Recommended is lower than current. |
| `outdated` | Recommended is higher than current. |
| `latest` | Recommended equals current. |

### `update_type` values

`major`, `minor`, `patch`, `new`, `same`, `downgrade`, `update`, `unknown`. Semantics:
[Update-type classification](../concepts/version-recommendation.md#update-type-classification).

---

## Conflict object

| Field | Type | Description |
|---|---|---|
| `source_package` | string | The package that declares the requirement. |
| `source_version` | string \| null | The version of the source package that declares it. |
| `target_package` | string | The constrained package (the object this conflict is attached to). |
| `required_spec` | string | The specifier the source requires, e.g. `">=2.3.7"`. |
| `conflicting_version` | string | The version of the target that violated the specifier when the conflict was recorded. |

!!! warning "Conflicts are cumulative"

    The array holds every conflict recorded during resolution, **including ones a later pass
    resolved**. It is an audit trail, not a list of live problems. The value in
    `versions.recommended` is always the final, applied decision.

---

## Complete example

```json
[
  {
    "name": "requests",
    "status": "outdated",
    "versions": {
      "current": "2.28.0",
      "latest": "2.34.2",
      "recommended": "2.34.2"
    },
    "update_type": "minor",
    "python_requirements": {
      "current": ">=3.7, <4",
      "latest": ">=3.10",
      "recommended": ">=3.10"
    }
  },
  {
    "name": "flask",
    "status": "outdated",
    "versions": {
      "current": "2.0",
      "latest": "3.1.3",
      "recommended": "2.2.5"
    },
    "update_type": "minor",
    "python_requirements": {
      "latest": ">=3.9",
      "recommended": ">=3.7"
    }
  },
  {
    "name": "certifi",
    "status": "install",
    "versions": {
      "latest": "2026.7.22",
      "recommended": "2026.7.22"
    },
    "python_requirements": {
      "latest": ">=3.7",
      "recommended": ">=3.7"
    }
  },
  {
    "name": "werkzeug",
    "status": "outdated",
    "versions": {
      "current": "2.2",
      "latest": "3.1.8",
      "recommended": "2.2.3"
    },
    "update_type": "patch",
    "conflicts": [
      {
        "source_package": "flask",
        "source_version": "2.3.3",
        "target_package": "werkzeug",
        "required_spec": ">=2.3.7",
        "conflicting_version": "2.3.7"
      }
    ]
  },
  {
    "name": "depkeeper-does-not-exist-xyz123",
    "status": "no-update",
    "versions": {
      "current": "1.0.0"
    },
    "error": "Package information unavailable"
  }
]
```

---

## Behaviour that affects consumers

### Unreachable packages look up to date

With conflict checking enabled (the default), the resolver seeds its update set with
`recommended_version or current_version`. An unavailable stub therefore acquires a recommendation
equal to its current version and serialises as:

```json
{ "name": "…", "status": "latest", "versions": { "current": "1.0.0", "recommended": "1.0.0" } }
```

— with no `error` field. To detect unreachable packages reliably:

```bash
depkeeper check --format json --no-check-conflicts | jq -r '.[] | select(.error) | .name'
```

Tracked in [Known limitations](limitations.md#unavailable-packages-look-up-to-date-in-json).

### `latest` may be absent while `recommended` is present

When metadata is unavailable, `versions.latest` is omitted. Do not assume the key exists.

### `versions.recommended` may be lower than `versions.latest`

That is the normal case, not an anomaly: the major boundary, a declared cap, a Python requirement
or a conflict capped the upgrade.

### Names are canonical

`Flask`, `flask` and `FLASK` all serialise as `flask`; `zope.interface` becomes
`zope-interface`. Match on the canonical form.

---

## Recipes

```bash
# Packages that are behind
jq -r '.[] | select(.status == "outdated") | .name'

# Proposed changes as a markdown list
jq -r '.[] | select(.status == "outdated")
        | "- `\(.name)` \(.versions.current // "-") → \(.versions.recommended) (\(.update_type))"'

# Anything blocked or degraded
jq -r '.[] | select(.status == "downgrade" or .status == "no-update" or .conflicts) | .name'

# Count by status
jq 'group_by(.status) | map({status: .[0].status, count: length})'

# Fail a build if any package is capped below latest
jq -e '[.[] | select(.status=="outdated" and .versions.recommended != .versions.latest)] | length == 0'

# CSV
jq -r '.[] | [.name, .versions.current // "", .versions.recommended // "", .status] | @csv'
```

```python
import json, subprocess

result = subprocess.run(
    ["depkeeper", "check", "--format", "json"],
    capture_output=True, text=True, check=True,
)
packages = json.loads(result.stdout)

for pkg in packages:
    if pkg["status"] != "outdated":
        continue
    versions = pkg.get("versions", {})
    print(f"{pkg['name']}: {versions.get('current', '-')} -> {versions['recommended']}")
```

---

## Stability

The schema is additive within `0.1.x`: new optional keys may appear; existing keys will not change
type or meaning. Consumers should ignore unknown keys.
