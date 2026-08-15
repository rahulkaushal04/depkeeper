---
title: Home
description: depkeeper — safe, conflict-aware dependency updates for pip requirements files
---

# depkeeper

depkeeper analyses `requirements.txt`-style files, computes a **safe upgrade target** for every
requirement, cross-validates those targets against each other, and rewrites the file in place
without discarding the constraints you authored.

It is a single-purpose CLI. It does not manage virtual environments, does not install packages,
does not replace `pip`, and does not introduce a lock file format.

[Install](getting-started/installation.md){ .md-button .md-button--primary }
[Quick Start](getting-started/quickstart.md){ .md-button }
[Architecture](concepts/architecture.md){ .md-button }

---

## What it does

| Capability | Summary |
|---|---|
| Update discovery | Queries the PyPI JSON API concurrently for every requirement and reports the latest and the **recommended** version. |
| Major-version safety | A recommendation never crosses a major version boundary. `1.2.3` can become `1.9.9`, never `2.0.0`. |
| Python compatibility | Candidate versions whose `requires_python` excludes the running interpreter are discarded. |
| Constraint preservation | `celery>=5.0,<6.0` becomes `celery>=5.6.3,<6.0`. Upper bounds, exclusions and `~=` bands survive the rewrite. |
| Conflict resolution | Cross-validates proposed versions against each package's `requires_dist` metadata and iteratively adjusts until the set is self-consistent. |
| Safe writes | Every file is rendered in memory, written atomically, and rolled back as a unit if any write fails. |
| Machine-readable output | `--format json` emits a document on stdout and diverts every diagnostic to stderr, so the output is pipeable. |

---

## Why it exists

`pip` has no opinion about *which* newer version you should move to. `pip list --outdated`
reports the latest release, which is frequently a major version that will break your build.
Lock-file tools solve this by owning the whole dependency workflow, which is a large migration
for an existing project.

depkeeper occupies the gap:

- It reads and writes the files you already have.
- It answers "what is the largest upgrade I can take **without** a major version bump, that my
  interpreter supports, that my declared constraints permit, and that does not conflict with my
  other pinned packages?"
- It leaves resolution of everything else to `pip`.

The trade-off is explicit: depkeeper is deliberately conservative. It will not propose the
major upgrade you eventually need. See [Known limitations](reference/limitations.md).

---

## Verified example

Given this `requirements.txt`:

```text title="requirements.txt"
requests==2.28.0
flask>=2.0,<2.3
celery[redis]>=5.0,<6.0
click~=8.0
certifi
urllib3==1.26.0
```

`depkeeper update -y` produces:

```text title="requirements.txt (after)" hl_lines="2 3 4"
requests==2.34.2
flask>=2.2.5,<2.3
celery[redis]>=5.6.3,<6.0
click~=8.4
certifi==2026.7.22
urllib3==1.26.20
```

Note what did **not** happen:

- `flask` did not reach `3.1.3` — the declared `<2.3` cap holds.
- `urllib3` did not reach `2.7.0` — that is a major boundary crossing.
- `celery`'s `[redis]` extra, its `<6.0` cap and `click`'s compatible-release form were preserved.
- Running the command a second time reports `All packages are up to date!` — the rewrite converges.

---

## Where to go next

<div class="grid cards" markdown>

- :material-download:{ .lg .middle } **[Install](getting-started/installation.md)**

    ---

    Requirements, install methods, and verification.

- :material-play-circle:{ .lg .middle } **[Quick Start](getting-started/quickstart.md)**

    ---

    The five commands that cover most day-to-day use.

- :material-sitemap:{ .lg .middle } **[Architecture](concepts/architecture.md)**

    ---

    Module responsibilities, data flow, and design decisions.

- :material-console:{ .lg .middle } **[CLI reference](reference/cli-commands.md)**

    ---

    Every flag, its default, and its precedence.

- :material-vector-triangle:{ .lg .middle } **[Conflict resolution](concepts/conflict-resolution.md)**

    ---

    The resolution loop, its guarantees, and its failure modes.

- :material-wrench:{ .lg .middle } **[Troubleshooting](guides/troubleshooting.md)**

    ---

    Symptom-indexed diagnosis for the errors you will actually hit.

</div>

---

## Project status

depkeeper is at version **0.1.0** and is classified `Development Status :: 3 - Alpha`.

- Supported Python: **3.8+**. The interpreter running depkeeper is also the interpreter it
  filters candidate versions against — see [Python compatibility](concepts/version-recommendation.md#python-compatibility-filtering).
- Supported input: pip requirements files only. See [File formats](reference/file-formats.md).
- Public API stability: the CLI surface is stable within `0.1.x`. The Python API is documented
  but not yet covered by a compatibility guarantee — see [Python API](reference/python-api.md).
- License: [Apache-2.0](community/license.md).
