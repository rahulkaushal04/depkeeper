---
title: Release Process
description: Versioning policy, release checklist, build and publish steps
---

# Release Process

For maintainers.

---

## Versioning

depkeeper follows [Semantic Versioning](https://semver.org/).

| Increment | When |
|---|---|
| **Major** | Backwards-incompatible change to the CLI surface or to file-rewrite semantics. |
| **Minor** | New commands, flags or output fields; a behavioural change that produces different (but still safe) recommendations. |
| **Patch** | Bug fixes and documentation that do not change recommendations. |

!!! warning "Recommendation logic is a behavioural contract"

    A change that makes the same requirements file produce a different update plan is at minimum
    a **minor** release, even if the diff looks like a bug fix. Consumers gate pipelines on this
    output.

While the project is `0.x`, the CLI surface is stable within a patch series; anything may change
between minor versions.

---

## Version sources

| Location | Content |
|---|---|
| `depkeeper/__version__.py` | `__version__` — the runtime source of truth, used by `--version` and the HTTP `User-Agent`. |
| `pyproject.toml` | `[project] version` — the packaging metadata. |

Both must be updated together. A mismatch means the published artefact reports the wrong version
to PyPI in its User-Agent.

---

## Release checklist

### 1. Verify

```bash
python -m pytest tests -q --no-cov
python -m mypy depkeeper --python-version 3.13
python -m compileall -q depkeeper
pre-commit run --all-files
mkdocs build --strict
```

All five must pass on a clean checkout of `main`.

### 2. Bump the version

```bash
# depkeeper/__version__.py
__version__ = "0.2.0"
```

```toml
# pyproject.toml
[project]
version = "0.2.0"
```

### 3. Update the changelog

Add a dated section to the root `CHANGELOG.md` — the canonical file, linked from `pyproject.toml`
and PyPI — following Keep a Changelog. Every user-visible change belongs in it, grouped under
`Added` / `Changed` / `Fixed` / `Removed` / `Security`. Mirror the same section into
`docs/community/changelog.md`; that copy may summarise rather than repeat verbatim, but must not
diverge in substance.

Call out behavioural changes explicitly, with a "how this affects you" note:

```markdown
### Changed

- Conflict resolution no longer adopts a compatible alternative for conflicts a later
  iteration resolved. **Impact:** some packages will now be updated that were previously
  held back at their current version.
```

### 4. Verify the documentation matches the release

Behavioural changes must already be reflected in:

- [CLI commands](../reference/cli-commands.md) — new or changed flags
- [Version recommendation](../concepts/version-recommendation.md) — changed selection logic
- [Conflict resolution](../concepts/conflict-resolution.md) — changed resolver behaviour
- [Error reference](../reference/errors.md) — new or changed messages
- [JSON output](../reference/json-output.md) — new fields
- [Known limitations](../reference/limitations.md) — entries fixed or added

### 5. Commit and push to `main`

```bash
git commit -am "chore(release): 0.2.0"
git push origin main
```

At this point PyPI has **not** been touched — publishing is triggered only by the tag in the
next step.

### 6. Build and verify locally, before tagging

Catch a packaging problem before it reaches CI, not after.

```bash
python -m pip install --upgrade build twine
rm -rf dist build *.egg-info
python -m build
python -m twine check dist/*                            # must report PASSED for both artefacts

python -m venv /tmp/verify && source /tmp/verify/bin/activate
pip install dist/depkeeper-0.2.0-py3-none-any.whl
depkeeper --version                                      # must print 0.2.0
printf 'requests==2.28.0\n' > /tmp/r.txt
depkeeper check /tmp/r.txt --format json | jq -e 'length == 1'
deactivate
rm -rf dist build *.egg-info /tmp/verify
```

### 7. Tag and push — this publishes to PyPI

```bash
git tag -a v0.2.0 -m "Release 0.2.0"
git push origin v0.2.0
```

Pushing a `v*` tag triggers
[`.github/workflows/publish.yml`](https://github.com/rahulkaushal04/depkeeper/blob/main/.github/workflows/publish.yml),
which:

1. Verifies the tag matches `__version__` in `depkeeper/__version__.py` **and** `version` in
   `pyproject.toml` — a mismatch fails the workflow before anything is built.
2. Builds the sdist and wheel and runs `twine check`.
3. Publishes to PyPI via [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC) —
   there is no long-lived API token in repository secrets.

Trusted Publishing requires a one-time setup on PyPI: on the `depkeeper` project's **Publishing**
settings page, add a trusted publisher for this repository, workflow file `publish.yml` and
environment `pypi`. Until that is configured, the `publish` job fails at the PyPI upload step —
build and verification still run, so the failure is isolated and nothing partial is published.

Watch the run under **Actions** and confirm the `pypi.org/project/depkeeper/` page shows the new
version before moving on.

### 8. Publish the documentation

`.github/workflows/docs.yml` deploys automatically on every push to `main` that touches
`docs/**` or `mkdocs.yml` — no manual step is required for the unversioned site. If you also want
a versioned snapshot (the site's `mike` version provider supports this, but the deploy workflow
does not invoke `mike` itself):

```bash
mike deploy --push --update-aliases 0.2 latest
mike set-default --push latest
```

### 9. Announce

Create a GitHub release from the tag, using the changelog section as the body. Link the
documentation for the new version.

---

## Post-release

- [ ] `pip install depkeeper==0.2.0` works from a clean environment.
- [ ] The documentation site shows the new version.
- [ ] The GitHub release exists and its notes match the changelog.
- [ ] Open a follow-up issue for anything deferred from this release.

---

## Yanking

If a release is discovered to corrupt files or to produce unsafe recommendations:

1. Yank it on PyPI (`pip` will stop resolving to it, existing pins keep working).
2. Publish a patch release with the fix.
3. Add a prominent note to the changelog explaining what was wrong and who is affected.
4. If the defect had security impact, follow the [security policy](../community/security.md).
