# Contributing to depkeeper

Thank you for your interest in contributing to **depkeeper**!
We welcome all contributions — whether they are bug fixes, new features, documentation improvements, or ideas.

This guide helps you get started quickly and ensures a smooth development process.

---

## 📜 Code of Conduct

Participation in this project requires adherence to our
👉 [Code of Conduct](./CODE_OF_CONDUCT.md)

If you experience or witness unacceptable behavior, please report it via
**GitHub Discussions** or the repository’s **Security** tab. All reports will
be handled confidentially and with respect.

---

## 🚀 Getting Started

### 1. Fork and Clone

```bash
git clone https://github.com/rahulkaushal04/depkeeper.git
cd depkeeper
git remote add upstream https://github.com/rahulkaushal04/depkeeper.git
```

### 2. Set Up Your Environment

#### Quick Setup (Recommended)

**macOS / Linux**

```bash
bash scripts/setup_dev.sh
```

**Windows (PowerShell)**

```powershell
.\scripts\setup_dev.ps1
```

#### Manual Setup

```bash
python -m venv venv
source venv/bin/activate    # macOS / Linux
venv\Scripts\activate       # Windows

pip install -e ".[dev]"
pre-commit install
```

Verify installation:

```bash
pytest
python -m depkeeper --help
```

---

## 📁 Project Structure

```
depkeeper/
├── depkeeper/        # Source code
│   ├── core/         # Dependency parsing, resolution, updating
│   ├── analyzers/    # Health, security, compatibility checks
│   ├── strategies/   # Update strategies
│   ├── utils/         # Config, cache, logger, helpers
│   └── cli.py        # CLI entrypoint
├── tests/            # Test suite
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── docs/             # Documentation
└── scripts/          # Dev tools and automation
```

---

## 🔧 Development Workflow

### 1. Create a Branch

Use one of the following prefixes:

| Type        | Prefix      |
| ----------- | ----------- |
| New Feature | `feature/`  |
| Bug Fix     | `fix/`      |
| Docs        | `docs/`     |
| Refactoring | `refactor/` |
| Tests       | `test/`     |

Example:

```bash
git checkout -b feature/upgrade-detection
```

---

### 2. Make Code Changes

Please ensure:

- Code is readable and follows depkeeper style
- All public functions/classes include type hints
- All new behavior includes tests
- Documentation is updated when necessary

---

### 3. Run Tests

```bash
pytest
pytest --cov=depkeeper
```

Useful patterns:

```bash
pytest tests/unit/
pytest tests/integration/
pytest tests/e2e/
pytest tests/unit/test_parser.py::test_specific_case
```

---

### 4. Check Code Quality

Run everything:

```bash
make all
```

Or individually:

```bash
make typecheck    # mypy
```

---

### 5. Commit

Use conventional commit prefixes:

```text
feat: add version conflict analyzer
fix: incorrect parsing of specifiers with spaces
docs: improve contribution guidelines
refactor: optimize cache layer
test: add CLI tests for update-strategy
```

Commit:

```bash
git add .
git commit -m "feat: add security vulnerability scanning"
```

---

### 6. Push & Open a Pull Request

```bash
git push origin your-branch
```

Then open a PR via GitHub.
Follow the Pull Request Template and ensure all checks pass.

---

## 🧪 Testing Guidelines

### Writing Good Tests

- Follow Arrange → Act → Assert pattern
- Use descriptive test names (`test_parse_range_specifiers`)
- Test happy paths + edge cases
- Prefer small, focused tests

Example:

```python
def test_parse_requirement_with_range():
    parser = RequirementsParser()
    req = parser.parse_line("requests>=2,<3", 1)

    assert req.name == "requests"
    assert (">=", "2") in req.specs
    assert ("<", "3") in req.specs
```

---

## 🧹 Code Style Guidelines

### Python Style

- Follows PEP 8
- Max line length: **100**
- String quotes: **double quotes**
- Use type hints everywhere
- Prefer dataclasses where appropriate

### Docstrings

Use Google-style docstrings:

```python
def update_packages(reqs: list[Requirement]) -> UpdateResult:
    """Update packages to the newest versions.

    Args:
        reqs: List of parsed requirement objects.

    Returns:
        UpdateResult describing the changes.
    """
```

---

## 📦 Submitting Changes

Before opening a PR:

- [ ] Tests added or updated
- [ ] Docs updated
- [ ] CHANGELOG updated (under **Unreleased**)
- [ ] Code formatted (`make format`)
- [ ] Linting passes (`make lint`)
- [ ] Type check passes (`make typecheck`)
- [ ] All CI checks are green

Reviews will be provided as quickly as possible.

---

## 🐛 Reporting Issues

Before creating an issue:

- Search existing issues
- Try with the latest version of depkeeper
- Include minimal reproducible examples

Use templates:

- **Bug Report**
- **Feature Request**

Please provide:

- Steps to reproduce
- Expected vs actual behavior
- Environment info (OS, Python version, depkeeper version)
- Relevant logs, screenshots, or requirement files

---

## 🌐 Community & Support

- GitHub Discussions
- Security reports via the **Security** tab in this repository
- Documentation: [https://docs.depkeeper.dev](https://docs.depkeeper.dev) (coming soon)

Thank you for helping make **depkeeper** better! 🚀
