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
| `name` | string | ✅ | Package name as normalised by the parser (PEP 503 form, e.g. `zope-interface`). |
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
| `versioning` | string | — | `calver` (only written when not `semver`). |
| `held` | boolean | — | `true` when the `hold` policy froze the package. |
| `ignored` | boolean | — | `true` when the `ignore` policy applies. |
| `released` | string | — | ISO 8601 upload time of the recommended version. |
| `age_days` | integer | — | Whole days since `released`. |
| `cooldown_skipped` | string | — | Newest version withheld by the `min_age` cooldown. |
| `major_available` | string | — | Newest eligible version in a higher major, not applied (see `--allow-major`). |
| `conflict_held` | boolean | — | `true` when conflict resolution held the package back. |
| `links` | object | — | `changelog`, `release_notes`, `homepage` (http/https URLs from PyPI `project_urls`). |
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

`major`, `minor`, `patch`, `new`, `same`, `downgrade`, `update`, `unknown`, and for calver packages `year` and `month`. Semantics:
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

> [!WARNING]
> **Conflicts are cumulative**
>
> The array holds every conflict recorded during resolution, **including ones a later pass
> resolved**. It is an audit trail, not a list of live problems. The value in
> `versions.recommended` is always the final, applied decision.

---

## Complete example

Captured from `depkeeper check -f json` on a file with `requests==2.28.0`, `django>=3.2,<5.0`,
`click~=7.0` and an unknown package (excerpt; `flask` omitted):

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
    "released": "2026-05-14T19:25:26.443000+00:00",
    "age_days": 175,
    "python_requirements": {
      "current": ">=3.7, <4",
      "latest": ">=3.10",
      "recommended": ">=3.10"
    },
    "links": {
      "homepage": "https://github.com/psf/requests"
    }
  },
  {
    "name": "django",
    "status": "outdated",
    "versions": {
      "current": "3.2",
      "latest": "6.1.3",
      "recommended": "3.2.25"
    },
    "update_type": "patch",
    "released": "2024-03-04T08:56:47.529440+00:00",
    "age_days": 977,
    "major_available": "4.2.30",
    "python_requirements": {
      "current": ">=3.6",
      "latest": ">=3.12",
      "recommended": ">=3.6"
    },
    "links": {
      "release_notes": "https://docs.djangoproject.com/en/stable/releases/",
      "homepage": "https://www.djangoproject.com/"
    }
  },
  {
    "name": "click",
    "status": "outdated",
    "versions": {
      "current": "7.0",
      "latest": "8.5.0",
      "recommended": "7.1.2"
    },
    "update_type": "minor",
    "released": "2020-04-27T20:22:42.629571+00:00",
    "age_days": 2383,
    "conflict_held": true,
    "python_requirements": {
      "current": ">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*",
      "latest": ">=3.10",
      "recommended": ">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*"
    },
    "links": {
      "changelog": "https://click.palletsprojects.com/page/changes/",
      "homepage": "https://github.com/pallets/click/"
    }
  },
  {
    "name": "ghost-pkg-xyz-404",
    "status": "no-update",
    "versions": {
      "current": "1.0"
    },
    "error": "Package information unavailable"
  }
]
```

---

## Behaviour that affects consumers

### Unreachable packages are reported as errors

A package PyPI cannot supply (unknown name, network failure) serialises as `"status": "no-update"`
with `"error": "Package information unavailable"`, with or without conflict checking, and the
process exits `4`. Direct references (URL/VCS/editable) are never looked up and are exempt.

### `latest` may be absent while `recommended` is present

When metadata is unavailable, `versions.latest` is omitted. Do not assume the key exists.

### `versions.recommended` may be lower than `versions.latest`

That is the normal case, not an anomaly: the major boundary, a declared cap, a Python requirement
or a conflict capped the upgrade.

### Names are canonical

`Flask`, `flask` and `FLASK` all serialise as `flask`; `zope.interface` becomes
`zope-interface`. Match on the normalised form.

---

## `--format json-v2`

A versioned envelope with the same package entries plus `file`, `line`, `source_format`, `age_days`,
`held`, `ignored`, `versioning`, `update_type` (`null` when none) and `links` on every entry. Top-level keys:
`schema_version` (`2`), `summary` (`total`, `errors`, `by_update_type`, `outdated`, `up_to_date`, `held`,
`ignored`, `conflicts`), `python` (`version`, `source`; `version` is `null` for the running interpreter),
`files[]` (`path`, `format`, `packages`), `packages[]` and `errors[]` (`package`, `file`, `line`,
`message`). Real output for a file with an unknown package:

```json
{
  "schema_version": 2,
  "summary": {"total": 5, "errors": 1, "by_update_type": {"minor": 2, "patch": 2},
              "outdated": 4, "up_to_date": 0, "held": 0, "ignored": 0, "conflicts": 1},
  "python": {"version": null, "source": "running interpreter"},
  "files": [{"path": "/abs/requirements.txt", "format": "requirements.txt", "packages": 5}],
  "packages": ["..."],
  "errors": [{"package": "ghost-pkg-xyz-404", "file": "/abs/requirements.txt", "line": 5,
              "message": "not found on PyPI or network error"}]
}
```

See also [`check` options](cli-commands.md#--format-json-v2).

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

The bare array is additive within `0.1.x`: new optional keys may appear; existing keys will not change
type or meaning. Consumers should ignore unknown keys.
