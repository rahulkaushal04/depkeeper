---
title: File Formats
description: Supported file format specifications for depkeeper
---

# File Formats

Reference for all file formats supported by depkeeper. This page covers the requirements file syntax, configuration file formats, and backup file conventions.

---

## requirements.txt

The standard pip requirements format (PEP 508). This is the primary file format depkeeper reads and updates.

### Version Specifiers

| Operator | Meaning | Example |
|---|---|---|
| `==` | Exact version | `requests==2.31.0` |
| `>=` | Minimum version | `requests>=2.28.0` |
| `<=` | Maximum version | `requests<=3.0.0` |
| `>` | Greater than | `requests>2.27.0` |
| `<` | Less than | `requests<3.0.0` |
| `!=` | Not equal | `requests!=2.29.0` |
| `~=` | Compatible release | `requests~=2.31.0` |

### Compatible Release (`~=`)

The `~=` operator allows patch updates but not minor/major:

```ini
# Equivalent to >=2.31.0, ==2.31.*
requests~=2.31.0

# Equivalent to >=2.31, ==2.*
requests~=2.31
```

### Basic Syntax

```ini
# Package with exact version
requests==2.31.0

# Package with version constraints
flask>=2.0.0,<3.0.0

# Package without version (latest)
click

# Combined constraints
requests>=2.28.0,<3.0.0,!=2.29.0
```

### Extras

Install optional dependencies:

```ini
# Single extra
requests[security]==2.31.0

# Multiple extras
package[extra1,extra2]==1.0.0
```

### Environment Markers

Conditional installations based on environment:

```ini
# Python version
dataclasses==0.6; python_version < "3.7"

# Platform
pywin32==305; sys_platform == "win32"

# Implementation
uvloop>=0.18.0; implementation_name == "cpython"

# Combined
package==1.0.0; python_version >= "3.8" and sys_platform != "win32"
```

### URL and VCS Requirements

```ini
# Git repository
git+https://github.com/user/project.git

# Specific branch
git+https://github.com/user/project.git@main

# Specific tag
git+https://github.com/user/project.git@v1.0.0

# Specific commit
git+https://github.com/user/project.git@abc123

# With package name
project @ git+https://github.com/user/project.git@v1.0.0
```

depkeeper supports `git+`, `bzr+`, `hg+`, `svn+`, `https://`, `http://`, and `file://` URL schemes.

### Editable Installs

```ini
# Local package in development
-e .

# Local package at path
-e /path/to/package

# Local package with extras
-e .[dev,test]
```

### Include and Constraint Directives

```ini
# Include another requirements file
-r requirements-base.txt
--requirement requirements-base.txt

# Constraints file (version limits, not installs)
-c constraints.txt
--constraint constraints.txt
```

depkeeper follows include chains and detects circular dependencies. Constraints loaded via `-c` are applied to matching package names during parsing.

### Hash Verification

```ini
requests==2.31.0 \
    --hash=sha256:942c5a758f98d790eaed1a29cb6eefc7ffb0d1cf7af05c3d2791656dbd6ad1e1
```

### Comments and Blank Lines

```ini
# This is a comment
requests==2.31.0  # Inline comment

# Blank lines are ignored

flask==3.0.0
```

---

## depkeeper.toml

Project configuration file for depkeeper settings.

```toml
[depkeeper]
check_conflicts = true
strict_version_matching = false
```

For the full list of options and their descriptions, see [Configuration Options](configuration-options.md).

---

## pyproject.toml Integration

depkeeper reads configuration from `pyproject.toml` under the `[tool.depkeeper]` section:

```toml
[project]
name = "my-project"
version = "1.0.0"
dependencies = [
    "requests>=2.28.0",
    "flask>=2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "black>=23.0.0",
]

[tool.depkeeper]
check_conflicts = true
strict_version_matching = false
```

---

## Backup Files

When `--backup` is used with the `update` command, depkeeper creates a timestamped backup:

```
requirements.txt.backup.20260208-143022
```

Format: `{filename}.backup.{YYYYMMDD}-{HHMMSS}`

Backup files are plain copies of the original requirements file. They can be restored by renaming or copying them back to the original filename.

---

## See Also

- [CLI Commands](cli-commands.md) -- Working with files via CLI
- [Configuration Options](configuration-options.md) -- Full configuration reference
- [Python API](python-api.md) -- Programmatic file handling
