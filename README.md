# depkeeper

[![Tests](https://github.com/rahulkaushal04/depkeeper/workflows/Tests/badge.svg)](https://github.com/rahulkaushal04/depkeeper/actions)
[![Coverage](https://codecov.io/gh/rahulkaushal04/depkeeper/branch/main/graph/badge.svg)](https://codecov.io/gh/rahulkaushal04/depkeeper)
[![PyPI version](https://badge.fury.io/py/depkeeper.svg)](https://badge.fury.io/py/depkeeper)
[![Python versions](https://img.shields.io/pypi/pyversions/depkeeper.svg)](https://pypi.org/project/depkeeper/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Modern, intelligent Python dependency management for `requirements.txt` files.
Keep your dependencies up-to-date and conflict-free — without switching from pip.

---

## Features

- **Smart Version Checking** — discover available package updates with intelligent recommendations
- **Dependency Conflict Resolution** — detect and resolve version conflicts automatically
- **Safe Updates** — never cross major version boundaries to prevent breaking changes
- **Fast & Concurrent** — async PyPI queries for maximum performance
- **Beautiful CLI** — rich terminal UI with colors & status indicators
- **Multiple Output Formats** — table, simple text, or JSON for CI/CD integration
- **Full Requirements Parsing** — PEP 440/508 compliant with support for `-r`, `-c`, VCS URLs, and more
- **Flexible** — works alongside pip, not instead of it

### Coming Soon

- **Security Scanning** — detect known vulnerabilities
- **Lock File Generation** — create reproducible environments
- **Health Scoring** — measure package quality & maintainability
- **Format Conversion** — import/export between `requirements.txt`, `pyproject.toml`, Pipfile, and more

---

## Quick Start

### Installation

```bash
pip install depkeeper
```

### Basic Usage

```bash
# Check for available updates
depkeeper check

# Check and show only outdated packages
depkeeper check --outdated-only

# Output as JSON (for CI/CD pipelines)
depkeeper check --format json

# Update all packages to safe versions (within major version)
depkeeper update

# Preview updates without applying
depkeeper update --dry-run

# Update specific packages only
depkeeper update -p flask -p requests

# Create backup before updating and skip confirmation
depkeeper update --backup -y
```

---

## Commands

### `depkeeper check`

Analyze your `requirements.txt` file to identify packages with available updates.

```bash
depkeeper check [FILE] [OPTIONS]

Options:
  --outdated-only           Show only packages with available updates
  -f, --format [table|simple|json]
                            Output format (default: table)
  --strict-version-matching Only use exact version pins
  --check-conflicts         Check for dependency conflicts (default: enabled)
```

### `depkeeper update`

Update packages to their safe recommended versions (within major version boundaries).

```bash
depkeeper update [FILE] [OPTIONS]

Options:
  --dry-run                 Preview changes without applying
  -y, --yes                 Skip confirmation prompt
  --backup                  Create backup file before updating
  -p, --packages TEXT       Update only specific packages (repeatable)
  --strict-version-matching Only use exact version pins
  --check-conflicts         Check for conflicts (default: enabled)
```

---

## Documentation

Full documentation will be available soon at **[https://rahulkaushal04.github.io/depkeeper/](https://rahulkaushal04.github.io/depkeeper/)**

---

## Why depkeeper?

Depkeeper bridges the gap between pip’s simplicity and Poetry’s sophistication:

| pip                         | poetry          | depkeeper                           |
| --------------------------- | --------------- | ----------------------------------- |
| simple                      | powerful        | simple + powerful                   |
| minimal tooling             | strict workflow | flexible workflow                   |
| limited dependency checking | strong resolver | strong resolver + update automation |
| no conflict detection       | automatic       | automatic with safe boundaries      |

**Focus on code — let depkeeper handle dependency hygiene.**

---

## Contributing

We welcome contributions of all kinds!
Please see our **[Contributing Guide](CONTRIBUTING.md)** for details.

### Development Setup

```bash
# Clone the repository
git clone https://github.com/rahulkaushal04/depkeeper.git
cd depkeeper

# Run setup script
bash scripts/setup_dev.sh

# Or manually:
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e ".[dev]"
pre-commit install
```

---

## License

This project is licensed under the **Apache-2.0 License** — see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- Built with amazing libraries like **Click**, **Rich**, and **httpx**
- Inspired by tools such as **pip-tools**, **Poetry**, and **Dependabot**

---

## Support

- GitHub Discussions: [https://github.com/rahulkaushal04/depkeeper/discussions](https://github.com/rahulkaushal04/depkeeper/discussions)
- Issues: [https://github.com/rahulkaushal04/depkeeper/issues](https://github.com/rahulkaushal04/depkeeper/issues)

---
