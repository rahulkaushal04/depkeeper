---
title: Changelog
description: Version history and release notes for depkeeper
---

# Changelog

All notable changes to depkeeper are documented on this page. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## Unreleased

### Planned

- Security vulnerability scanning against known advisory databases
- Lock file generation with integrity verification
- Health scoring for packages

---

## 0.1.0 -- 2026-02-10

Initial release of depkeeper.

### Check Command

- Analyze `requirements.txt` for available updates
- Table, simple, and JSON output formats via `--format`
- Filter to show only outdated packages with `--outdated-only`
- Strict version matching mode with `--strict-version-matching`
- Dependency conflict detection with `--check-conflicts`

### Update Command

- Apply safe version updates to `requirements.txt`
- Dry-run mode for previewing changes with `--dry-run`
- Backup creation before updates with `--backup`
- Selective package updates with `-p` flag
- Confirmation prompt (skip with `-y`)
- Conflict resolution during updates

### Dependency Resolution

- Build dependency graph from PyPI metadata
- Identify version conflicts between packages
- Iterative version adjustment to resolve conflicts
- Strict major version boundary enforcement -- updates never cross major versions

### Requirements Parser

Full PEP 440/508 compliance with support for:

- Version specifiers: `==`, `>=`, `<=`, `>`, `<`, `~=`, `!=`
- Extras: `package[extra1,extra2]`
- Environment markers: `; python_version >= '3.8'`
- Include directives: `-r requirements.txt`
- Constraint files: `-c constraints.txt`
- VCS URLs: `git+https://github.com/user/repo.git`
- Editable installs: `-e .`
- Hash verification: `--hash=sha256:...`

### Performance

- Async concurrent PyPI queries via httpx with HTTP/2 support
- Shared data store to minimize redundant API calls

### CLI Experience

- Rich terminal formatting with colors via the Rich library
- Progress indicators for long-running operations
- Multiple output formats (table, simple, JSON)
- Configurable verbosity levels (`-v`, `-vv`)
- Colored output toggle with `--color` / `--no-color`

### Technical Details

- Minimum Python version: 3.8
- Core dependencies: Click, Rich, httpx, packaging
- Full type hints with mypy strict mode
- 85%+ test coverage

---

## Version History

| Version | Date | Highlights |
|---|---|---|
| 0.1.0 | 2026-02-10 | Initial release with check, update, and conflict resolution |

---

## Upgrade Notes

### Upgrading to 0.1.0

This is the initial release. Install with:

```bash
pip install depkeeper
```
