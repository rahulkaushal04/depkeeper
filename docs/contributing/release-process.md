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

Add a dated section to `docs/community/changelog.md` following Keep a Changelog. Every
user-visible change belongs in it, grouped under `Added` / `Changed` / `Fixed` / `Removed` /
`Security`.

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

### 5. Tag

```bash
git commit -am "chore(release): 0.2.0"
git tag -a v0.2.0 -m "Release 0.2.0"
git push origin main --follow-tags
```

### 6. Build

```bash
python -m pip install --upgrade build twine
rm -rf dist build *.egg-info
python -m build
python -m twine check dist/*
```

`twine check` must report `PASSED` for both the sdist and the wheel.

### 7. Verify the artefact before publishing

```bash
python -m venv /tmp/verify && source /tmp/verify/bin/activate
pip install dist/depkeeper-0.2.0-py3-none-any.whl
depkeeper --version                     # must print 0.2.0
printf 'requests==2.28.0\n' > /tmp/r.txt
depkeeper check /tmp/r.txt --format json | jq -e 'length == 1'
deactivate
```

### 8. Publish

```bash
python -m twine upload --repository testpypi dist/*     # rehearse
python -m twine upload dist/*                           # publish
```

### 9. Publish the documentation

```bash
mkdocs gh-deploy --force
```

The site uses `mike` as its version provider, so a versioned deployment is possible:

```bash
mike deploy --push --update-aliases 0.2 latest
mike set-default --push latest
```

### 10. Announce

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
