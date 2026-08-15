---
title: FAQ
description: Frequently asked questions about depkeeper's behaviour and scope
---

# Frequently Asked Questions

---

## Scope and positioning

### What is depkeeper for?

Answering one question well: *what is the largest upgrade I can take for each requirement without
crossing a major version, without breaking Python compatibility, without violating the constraints
I declared, and without conflicting with the other packages in my file?* It then rewrites the file
with those answers.

### How is it different from `pip list --outdated`?

`pip` reports the **latest** version. depkeeper reports the **safe** version, and can apply it.
`pip` also reports on the installed environment; depkeeper reads a requirements file and needs
nothing installed.

### How is it different from Poetry or pip-tools?

Those tools own the dependency workflow and introduce a lock file. depkeeper edits the files you
already have and adds no new format. The trade-off is that it does not perform full resolution.

| | pip | pip-tools | Poetry | depkeeper |
|---|---|---|---|---|
| Reports available updates | latest only | no | yes | yes, with a safe target |
| Enforces major-version boundaries | no | no | no | yes |
| Full transitive resolution | yes (at install) | yes | yes | no |
| Requires a new file format | no | `.in` files | `pyproject.toml` + lock | no |
| Rewrites `requirements.txt` in place | no | regenerates | n/a | yes |

### Does it replace `pip`?

No. `pip install` remains the authority on whether a set of requirements resolves. Always install
and test after an update.

### Does it scan for vulnerabilities?

No. Use `pip-audit` or `safety` alongside it.

---

## Behaviour

### Why won't it upgrade past a major version?

That is the core safety rule. Crossing a major version is, by convention, permission to break the
caller — not a decision an unattended tool should make. See
[the boundary rule](../concepts/version-recommendation.md#the-major-version-boundary).

### How do I take a major upgrade?

Edit the floor yourself and let depkeeper continue from there:

```text
django>=3.2,<5.0    →    django>=4.2,<5.0
```

Then run `depkeeper update`, install, and test.

### Why is the recommendation lower than `Latest`?

One of four reasons, in order of likelihood:

1. Your own declared cap or exclusion (`<`, `!=`, `==x.*`).
2. The major boundary, anchored on the version inferred from your file.
3. A conflict with another package in the file.
4. `requires_python` of newer releases excludes the interpreter depkeeper is running on.

`depkeeper -vv check` names the reason.

### Why does `certifi` never update?

Calendar versioning. `2023.7.22` has "major" `2023`, so `2024.x` is a boundary crossing. Either
leave the requirement unversioned or bump it manually. See
[Limitations](../reference/limitations.md#calendar-versioning-hits-the-major-boundary).

### Why did it propose a downgrade?

Either the version you declared is incompatible with the running interpreter, or another package
in your file requires an older release. Review it — this rewrites your floor downwards. See
[Downgrades](../concepts/conflict-resolution.md#downgrades).

### Why did it change a package that `check` showed as `✓ OK`?

The requirement had no version specifier, so there was nothing to compare against and the table
fell through to its up-to-date branch. `update` correctly adds a pin. The JSON and simple formats
report it as `install`. See
[Limitations](../reference/limitations.md#unversioned-requirements-report-as-ok).

### Will it destroy my version ranges?

No. By default only the floor moves: `celery>=5.0,<6.0` becomes `celery>=5.6.3,<6.0`. Upper
bounds, exclusions and `~=` bands are preserved verbatim. Use `--pin` if you *want* exact pins.

### Does it preserve comments and formatting?

Yes. Comments (including inline ones), blank lines, ordering, extras, markers, directives, line
endings and byte order marks are all preserved. Only the version specifier on updated lines
changes.

Note that a comment explaining a cap is preserved verbatim and can become stale — depkeeper does
not interpret comments.

### Is running it twice safe?

Yes. A target that would produce a byte-identical line is skipped, so a second run reports
`All packages are up to date!`.

### Why are the recommendations different in CI than on my laptop?

Different Python versions running depkeeper. Compatibility filtering uses **depkeeper's own**
interpreter. Pin the CI Python to your project's target.

---

## Usage

### How do I preview changes?

```bash
depkeeper update --dry-run
```

It runs the full pipeline and stops before the first byte is written, so the plan is authoritative.

### How do I update a single package?

```bash
depkeeper update -p django
```

Names are matched in PEP 503 canonical form, so `My_Pkg` and `my-pkg` are the same.

### How do I use it in a script?

```bash
depkeeper check --format json > report.json
jq '[.[] | select(.status == "outdated")] | length' report.json
```

Do not gate on the exit code — `check` exits `0` whether or not updates exist. See
[Exit codes](../reference/exit-codes.md).

### Can I pipe the JSON with verbose logging on?

Yes. In machine-readable formats every diagnostic goes to stderr:

```bash
depkeeper -vv check --format json | jq .
```

### Does it work with multiple requirements files?

Yes, via `-r` includes: checking a file reports the union, and updating it rewrites every included
file that contains an updated requirement. There is no directory or recursive mode.

### Can I point it at a private index?

No. depkeeper always queries `pypi.org`; `--index-url` lines are parsed and ignored. Private
packages report as `✗ ERROR`.

### Can I change the timeout or concurrency?

Not from the CLI. Use the [Python API](../reference/python-api.md) and construct `HTTPClient` /
`PyPIDataStore` yourself.

### Does it work with hash-pinned files?

It refuses them by default. `--allow-hash-removal` proceeds but produces a partially hashed file
that `pip --require-hashes` rejects, so regenerate hashes afterwards. See
[Hashed requirements](../guides/updating-dependencies.md#hashed-requirements).

---

## Operations

### Does it need network access?

Yes. Every run queries the PyPI JSON API. There is no offline mode and no persistent cache.

### Does it send my code or my file contents anywhere?

No. Only package **names** appear, as URL path segments in requests to `pypi.org`. Versions,
comments and file contents never leave the machine.

### Does it execute or install the packages it analyses?

Never. It reads JSON metadata only.

### Is it safe to run against an untrusted repository?

With care. `update` writes to every file reachable through `-r` includes, and include paths can
contain `../`. Run `--dry-run` first, or run in a container with only the project directory
mounted.

### How do I make it faster?

`--no-check-conflicts` removes the resolution phase, which is the dominant cost. Runtime is
otherwise dominated by network latency.

### Why do I get `429 Rate limit exceeded`?

Too many requests from one egress IP — usually many CI jobs sharing it. Stagger schedules and use
`--no-check-conflicts` for reports.

---

## Project

### What Python versions are supported?

3.8 and later. Note that the interpreter you install depkeeper on affects its recommendations.

### Is it production-ready?

It is `0.1.0`, classified alpha. The write path is defensive (atomic writes, rollback, backups)
and the behaviour is documented and tested, but pin the version and review changes before
merging.

### Is it free?

Yes, under the [Apache License 2.0](license.md).

### How do I report a bug?

[Open an issue](https://github.com/rahulkaushal04/depkeeper/issues) with a minimal reproducer and
`depkeeper -vv … 2> debug.log`. For security issues, follow the [security policy](security.md)
instead.

### How do I contribute?

See [Contributing](../contributing/index.md). Start with the
[system invariants](../concepts/index.md#non-negotiable-invariants).
