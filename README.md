# depkeeper 🛡️🐍

[![Tests](https://github.com/rahulkaushal04/depkeeper/workflows/Tests/badge.svg)](https://github.com/rahulkaushal04/depkeeper/actions)
[![Coverage](https://codecov.io/gh/rahulkaushal04/depkeeper/branch/main/graph/badge.svg)](https://codecov.io/gh/rahulkaushal04/depkeeper)
[![PyPI version](https://badge.fury.io/py/depkeeper.svg)](https://badge.fury.io/py/depkeeper)
[![Python versions](https://img.shields.io/pypi/pyversions/depkeeper.svg)](https://pypi.org/project/depkeeper/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Modern, intelligent Python dependency management for `requirements.txt` files.
Keep your dependencies up-to-date, secure, and conflict-free — without switching from pip.

---

## ✨ Features

- 🔍 **Smart Version Checking** — discover available package updates automatically
- 🛡️ **Security Scanning** — detect known vulnerabilities via advisories
- 🔒 **Lock File Generation** — create reproducible environments
- 📊 **Health Scoring** — measure package quality & maintainability
- 🧠 **Dependency Resolution** — detect and resolve version conflicts
- 🎯 **Update Strategies** — conservative, moderate, or aggressive upgrade modes
- 🔄 **Format Conversion** — import/export: `requirements.txt`, `pyproject.toml`, Pipfile, Poetry, Conda
- ⚡ **Fast & Concurrent** — async operations for maximum performance
- 🎨 **Beautiful CLI** — rich terminal UI with progress bars & status indicators
- 🤝 **Flexible** — works with pip instead of replacing it

---

## 🚀 Quick Start

### Installation

```bash
pip install depkeeper
```

### Basic Usage

```bash
# Check for available updates
depkeeper check

# Update dependencies (safe, patch-level updates by default)
depkeeper update

# Run security audit
depkeeper audit

# Generate lock file
depkeeper lock

# Show dependency tree
depkeeper tree
```

---

## 📚 Documentation

Full documentation will be available soon at **[https://docs.depkeeper.dev](https://docs.depkeeper.dev)**

---

## 💡 Why depkeeper?

Depkeeper bridges the gap between pip’s simplicity and Poetry’s sophistication:

| pip                         | poetry          | depkeeper                           |
| --------------------------- | --------------- | ----------------------------------- |
| simple                      | powerful        | simple + powerful                   |
| minimal tooling             | strict workflow | flexible workflow                   |
| limited dependency checking | strong resolver | strong resolver + update automation |

**Focus on code — let depkeeper handle dependency hygiene.**

---

## 🤝 Contributing

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

## 📄 License

This project is licensed under the **Apache-2.0 License** — see the [LICENSE](LICENSE) file for details.

---

## 🙌 Acknowledgments

- Built with amazing libraries like **Click**, **Rich**, and **httpx**
- Inspired by tools such as **pip-tools**, **Poetry**, and **Dependabot**

---

## ❤️ Support

- 💬 GitHub Discussions: [https://github.com/rahulkaushal04/depkeeper/discussions](https://github.com/rahulkaushal04/depkeeper/discussions)
- 🐞 Issues: [https://github.com/rahulkaushal04/depkeeper/issues](https://github.com/rahulkaushal04/depkeeper/issues)

---

**Made with ❤️ by the depkeeper team**
