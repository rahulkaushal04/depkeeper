---
title: FAQ
description: Frequently asked questions about depkeeper's behaviour and scope
---

# Frequently Asked Questions

---

## Scope and positioning

### What is depkeeper for?

Answering one question well: *what is the largest upgrade I can take for each requirement without
crossing a major version (unless I opt in), without breaking Python compatibility, without violating the constraints
I declared, and without conflicting with the other packages in my file?* It then rewrites the file
with those answers.

### How is it different from `pip list --outdated`?

`pip` reports the **latest** version. depkeeper reports the **safe** version, and can apply it.
`pip` also reports on the installed environment; depkeeper reads a dependency file (`requirements*.txt`, `pyproject.toml`, conda `environment.yml`) and needs
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
| Rewrites your dependency file in place | no | regenerates | n/a | yes |

### Does it replace `pip`?

No. `pip install` remains the authority on whether a set of requirements resolves. Always install
and test after an update.

### Does it scan for vulnerabilities?

No. Use `pip-audit` or `safety` alongside it.

---

## Behaviour

### Why won't it upgrade past a major version?

That is the default safety rule. Crossing a major version is, by convention, permission to break the
caller — not a decision an unattended tool should make. See
[the boundary rule](../concepts/version-recommendation.md#the-major-version-boundary).

### How do I take a major upgrade?

Opt in per package with `--allow-major PKG` (repeatable, `'*'` for all) or `allow_major = true` under `[depkeeper.packages.<name>]`. Your own upper bounds, `--max-update`, Python compatibility and `min_age` still apply. Without the opt-in, a newer major is reported as `major available`. Or edit the floor yourself and let depkeeper continue from there:

```text
django>=3.2,<5.0    →    django>=4.2,<5.0
```

Then run `depkeeper update`, install, and test.

### Why is the recommendation lower than `Latest`?

One of four reasons, in order of likelihood:

1. Your own declared cap or exclusion (`<`, `!=`, `==x.*`, or the bound implied by `~=`).
2. The major boundary (without `--allow-major`), anchored on the version inferred from your file.
3. A conflict with another package in the file.
4. `requires_python` of newer releases excludes the target Python.
5. `--min-age`, `--max-update` or a per-package `hold`.

`depkeeper -vv check` names the reason.

### Why does `certifi` never update?

Normally it does: calendar versioning is detected and `certifi 2023.7.22` updates across years
(labelled `year`). If a package is misdetected set `versioning = "calver"` for it. See
[Limitations](../reference/limitations.md#calendar-versioning-heuristics).

### Why did it propose a downgrade?

Either the version you declared is incompatible with the running interpreter, or another package
in your file requires an older release. Review it — this rewrites your floor downwards. See
[Downgrades](../concepts/conflict-resolution.md#downgrades).

### Why did it change a package that `check` showed as `[OK]`?

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

Different target Python. It comes from `--python-version`, then config `python_version`, then the file's `requires-python`, then the interpreter running depkeeper. Set one of the first three to get the same answer everywhere.

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

`check` exits `0` whether or not updates exist, unless you pass `--fail-on` (exit `3` when the threshold is met). Exit `4` means a package lookup failed. See
[Exit codes](../reference/exit-codes.md).

### Can I pipe the JSON with verbose logging on?

Yes. In machine-readable formats every diagnostic goes to stderr:

```bash
depkeeper -vv check --format json | jq .
```

### Does it work with multiple requirements files?

Yes. `-r` includes are followed (checking a file reports the union, and updating it rewrites every included file that contains an updated requirement), and passing a directory checks every supported file in it. Directory discovery is not recursive.

### Can I point it at a private index?

No. depkeeper always queries `pypi.org`; `--index-url` lines are parsed and ignored (`update --verify` runs pip, which uses your own pip index settings). Private
packages report as `[ERROR]`.

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

Never, with one exception: `update --verify` runs `pip install --dry-run --only-binary=:all:` in a subprocess, so no package is built or installed and no build code runs. Otherwise it reads JSON metadata only.

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

3.8 and later. The interpreter you install depkeeper on is the default target Python; override it with `--python-version`.

### Is it production-ready?

It is in the `0.1.x` series, classified beta. The write path is defensive (atomic writes, rollback, backups)
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
