---
title: Best Practices
description: How to structure requirements files and update workflows so depkeeper produces good answers
---

# Best Practices

depkeeper's output quality is a direct function of how your requirements files are written. These
practices are derived from the behaviours documented in
[Version recommendation](../concepts/version-recommendation.md).

---

## Declare a floor on every requirement

```text
# Weak — no anchor, no boundary protection
certifi
requests

# Strong
certifi==2026.7.22
requests>=2.32,<3.0
```

A requirement with no specifier has no current version, therefore no major-version anchor.
depkeeper will propose the newest compatible release **across all majors** and `update` will pin
it. It also renders as `[OK]` in the table while still being changed by `update` — a genuine
surprise. Give every requirement at least a floor.

---

## Prefer bounded ranges to bare floors

```text
django>=4.2,<5.0     # ✅ intent is explicit and machine-checkable
django>=4.2          # ⚠️  relies solely on depkeeper's boundary rule
```

An explicit cap is enforced by `pip` as well as by depkeeper, and it survives if you later stop
using depkeeper. It also lets depkeeper cap the upgrade correctly when the boundary rule is not
enough — for example when a package uses calendar versioning.

---

## Understand what the floor means to depkeeper

depkeeper reads the floor as "the version you are on". Two consequences:

```text
django>=3.2,<5.0
```

- The major anchor is `3`, so depkeeper caps at the newest `3.x` — it will **not** move you to
  `4.2.x` even though your own range allows it.
- To take the major step, edit the floor yourself, then let depkeeper continue from there:

```text
django>=4.2,<5.0
```

Plan major upgrades deliberately. depkeeper is not the tool that performs them.

---

## Pin applications, range libraries

| Artefact | Style | Command |
|---|---|---|
| Deployable service / application | Exact pins | `depkeeper update --pin` |
| Library / SDK | Ranges | `depkeeper update` (default) |
| Development tooling | Ranges with caps | `depkeeper update` |

Pinning a library's dependencies forces the pins onto every consumer and makes co-installation
with other libraries almost impossible.

---

## Split by purpose, compose with `-r`

```text title="requirements/base.txt"
django>=4.2,<5.0
psycopg[binary]>=3.1,<4.0
```

```text title="requirements/dev.txt"
-r base.txt
pytest>=8.0,<9.0
mypy>=1.8,<2.0
```

```text title="requirements/prod.txt"
-r base.txt
gunicorn>=21.2,<22.0
```

depkeeper follows the includes, reports the union, and rewrites each file in place. Checking
`dev.txt` therefore also validates `base.txt` against the dev packages.

Remember that `depkeeper update requirements/dev.txt` will also modify `base.txt`. Use
`--dry-run` first if that is not what you intend.

---

## Comment the non-obvious constraints

```text
# Pinned: 4.x drops the legacy auth backend we still use (TICKET-1423)
django>=3.2,<4.0

# 2.x rewrote the connection pool; migration tracked in TICKET-1587
urllib3>=1.26.20,<2.0
```

Comments are preserved verbatim by the writer, so they survive every update. A cap without a
recorded reason becomes indistinguishable from an accidental one after six months.

---

## Always preview, then verify

```bash
depkeeper update --dry-run       # what would change
depkeeper update --backup        # apply
pip install -r requirements.txt  # does it resolve?
pytest                            # does it work?
git diff requirements.txt         # review before committing
```

The `pip install` step is mandatory in any automated workflow. depkeeper checks the packages you
declared against each other; it does not expand the transitive graph.

---

## Update incrementally, not in one batch

```bash
depkeeper update -p django -y && pytest
depkeeper update -p celery -y && pytest
```

A single commit that moves twenty packages makes bisecting a regression expensive. Package-scoped
updates keep the blast radius small and the git history meaningful.

---

## Review every downgrade

A `downgrade` / `[INCOMP]` row means the version you declared cannot be used — because another
package requires an older release, or because it is incompatible with the running interpreter.
depkeeper will rewrite the floor **downwards** to make the set consistent.

That is a legitimate repair, but it silently relaxes a constraint you chose. Investigate the
cause before accepting it; usually the better fix is to raise the *other* side:

```text
# depkeeper's fix: flask>=2.2.5,<3.0 (floor lowered)
# your better fix:
flask>=2.3,<3.0
werkzeug>=2.3.7,<3.0
```

---

## Handle hash-pinned files deliberately

Do not run plain `depkeeper update` against a `--require-hashes` file and hope for the best. The
supported sequence is:

```bash
depkeeper update --allow-hash-removal -y
pip-compile --generate-hashes requirements.in
```

`--allow-hash-removal` strips digests only from the lines it changes, producing a partially hashed
file that `pip --require-hashes` rejects. Regenerating hashes is not optional.

---

## Add `#egg=` to every direct reference

```text
# ✅ unambiguous
-e git+https://github.com/org/lib.git@v1.2.0#egg=lib
https://example.com/internal-1.0.tar.gz#egg=internal

# ⚠️ name is inferred from the last path segment, often wrongly
https://example.com/rich-13.7.1-py3-none-any.whl
```

depkeeper never updates direct references, but it does report them, and an inferred name pollutes
the report and the conflict analysis.

---

## Run depkeeper on your project's interpreter

```bash
# in the project's virtual environment
python -m pip install depkeeper

# or with pipx, pinning the interpreter
pipx install --python python3.12 depkeeper
```

Compatibility filtering uses the interpreter depkeeper runs on. A mismatch makes recommendations
silently conservative and is very hard to notice.

---

## Schedule, but gate on review

| Cadence | Action |
|---|---|
| Weekly | `check --format json` drift report published as a build artefact. |
| Weekly | Automated `update -y` pull request, verified by the full test suite. |
| Per release | `update --pin` for applications, followed by a full verification run. |
| Quarterly | Deliberate review of major upgrades, which depkeeper will never propose. |

Never merge an automated dependency pull request that has not run `pip install` and the test
suite.

---

## Anti-patterns

| Anti-pattern | Why it hurts |
|---|---|
| `depkeeper update -y` in a deploy pipeline, unreviewed | Applies downgrades and floor changes with no human in the loop. |
| Treating `check`'s exit code as a drift signal | It is always `0` on success. Parse the JSON. |
| Unpinned depkeeper in CI | Behaviour changes without a repository change. |
| Using `--pin` on a library | Forces pins onto every consumer. |
| Relying on `--backup` as version control | Backups accumulate, are never cleaned up, and carry no history. |
| Assuming depkeeper validates the full graph | It does not. `pip install` remains the authority. |
| Adding caps with no comment | Nobody, including you, will remember why. |
