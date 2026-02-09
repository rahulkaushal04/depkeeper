---
title: Release Process
description: How depkeeper releases are made
---

# Release Process

How depkeeper releases are created and published.

---

## Overview

depkeeper follows [Semantic Versioning](https://semver.org/):

- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes (backward compatible)

---

## Version Numbering

### Current Version

The version is defined in `depkeeper/__version__.py`:

```python
__version__ = "0.1.0"
```

### Version Format

| Component | Required | Description |
|-----------|----------|-------------|
| MAJOR | Yes | Breaking changes |
| MINOR | Yes | New features (backward compatible) |
| PATCH | Yes | Bug fixes (backward compatible) |
| PRERELEASE | Optional | Alpha, beta, or release candidate (e.g., `-alpha.1`, `-rc.1`) |
| BUILD | Optional | Build metadata (e.g., `+20260209`) |

Examples:

- `0.1.0` - Initial development release
- `1.0.0` - First stable release
- `1.2.3` - Stable release
- `2.0.0-alpha.1` - Pre-release
- `2.0.0-rc.1` - Release candidate

---

## Release Checklist

### 1. Prepare the Release

Verify these requirements:

- [ ] All tests passing on main branch
- [ ] Documentation updated
- [ ] CHANGELOG.md updated
- [ ] Version number bumped

### 2. Update Version

Edit `depkeeper/__version__.py`:

```python
__version__ = "0.2.0"  # New version
```

### 3. Update CHANGELOG

Add a new section to `CHANGELOG.md`:

```markdown
## [0.2.0] - 2026-02-08

### Added
- New feature X
- Support for Y

### Changed
- Improved Z performance

### Fixed
- Bug in parser (#123)

### Security
- Updated httpx to fix CVE-XXXX
```

### 4. Create Release Commit

Commit the version changes:

```bash
git add depkeeper/__version__.py CHANGELOG.md
git commit -m "release: v0.2.0"
```

### 5. Tag the Release

Create and push the version tag:

```bash
git tag -a v0.2.0 -m "Release v0.2.0"
git push origin main --tags
```

### 6. Build and Publish

Build and upload to PyPI:

```bash
# Clean previous builds
rm -rf dist/

# Build
python -m build

# Upload to PyPI
python -m twine upload dist/*
```

### 7. Create GitHub Release

Publish the release on GitHub:

1. Go to [Releases](https://github.com/rahulkaushal04/depkeeper/releases)
2. Click "Draft a new release"
3. Select the tag
4. Copy changelog entries to description
5. Attach built distributions
6. Publish release

---

## CHANGELOG Format

Follow the [Keep a Changelog](https://keepachangelog.com/) format:

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Feature in development

## [0.2.0] - 2026-02-08

### Added
- Lock file generation
- Health scoring

### Changed
- Improved dependency resolution

### Fixed
- Parser edge case (#123)

## [0.1.0] - 2026-01-15

### Added
- Initial release
- Check command
- Update command
```

### Change Categories

| Category | Description |
|----------|-------------|
| Added | New features |
| Changed | Changes in existing functionality |
| Deprecated | Soon-to-be removed features |
| Removed | Removed features |
| Fixed | Bug fixes |
| Security | Security fixes |

---

## Hotfix Process

Apply urgent fixes to released versions:

1. Create hotfix branch from tag:
   ```bash
   git checkout -b hotfix/0.1.1 v0.1.0
   ```

2. Apply fix and commit

3. Bump patch version:
   ```python
   __version__ = "0.1.1"
   ```

4. Update CHANGELOG

5. Tag and release:
   ```bash
   git tag -a v0.1.1 -m "Hotfix v0.1.1"
   git push origin v0.1.1
   ```

6. Merge back to main:
   ```bash
   git checkout main
   git merge hotfix/0.1.1
   ```

---

## PyPI Publishing

### Manual Publishing

```bash
# Build
python -m build

# Check package
twine check dist/*

# Upload to TestPyPI first
twine upload --repository testpypi dist/*

# Test installation
pip install --index-url https://test.pypi.org/simple/ depkeeper

# Upload to PyPI
twine upload dist/*
```

### PyPI Token

Store your PyPI token securely as GitHub secret `PYPI_TOKEN`.

Generate tokens at: https://pypi.org/manage/account/token/

---

## Post-Release

Complete these tasks after releasing:

1. **Announce** - Post on social media and mailing lists
2. **Monitor** - Watch for issue reports
3. **Document** - Update any outdated documentation
4. **Plan** - Start planning the next release

---

## Emergency Rollback

Handle critical issues in releases:

1. **Yank from PyPI** - Hide the problematic release:
   ```bash
   pip install twine
   twine upload --skip-existing dist/*
   # Use PyPI web interface to yank
   ```

2. **Notify users** - Update GitHub release notes

3. **Fix and re-release** - Follow hotfix process

---

## See Also

- [Development Setup](development-setup.md) -- Set up your development environment
- [Testing](testing.md) -- Learn testing guidelines
- [Code Style](code-style.md) -- Follow coding standards
