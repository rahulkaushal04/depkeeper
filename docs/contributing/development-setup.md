---
title: Development Setup
description: Set up your local development environment for depkeeper
---

# Development Setup

This guide walks you through setting up a local development environment for contributing to **depkeeper**.
It covers prerequisites, installation options, common workflows, and development tooling.

---

## Prerequisites

Ensure the following tools are installed on your system:

- **Python** ≥ 3.8
- **Git** for version control
- **Make** (optional) for development shortcuts

You can verify your Python version with:

```bash
python --version
```

---

## Installation

You can set up the project using either the automated setup scripts or manual steps.

### Option 1: Automated Setup (Recommended)

#### macOS / Linux

```bash
git clone https://github.com/rahulkaushal04/depkeeper.git
cd depkeeper
bash scripts/setup_dev.sh
```

#### Windows (PowerShell)

```powershell
git clone https://github.com/rahulkaushal04/depkeeper.git
cd depkeeper
.\scripts\setup_dev.ps1
```

These scripts create a virtual environment, install dependencies, and configure development tools.

---

### Option 2: Manual Setup

Use this approach if you prefer full control over the environment.

```bash
# Clone repository
git clone https://github.com/rahulkaushal04/depkeeper.git
cd depkeeper

# Create virtual environment
python -m venv venv

# Activate virtual environment
# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate

# Install dependencies in editable mode
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

---

## Verify Installation

After setup, ensure everything is working correctly:

```bash
# Verify CLI
python -m depkeeper --version

# Run test suite
pytest

# Run all linters and checks
pre-commit run --all-files
```

All commands should complete without errors.

---

## Development Workflow

### 1. Create a Branch

Use descriptive branch names to keep the repository organized:

| Change Type   | Prefix      | Example                      |
| ------------- | ----------- | ---------------------------- |
| Feature       | `feature/`  | `feature/add-lock-file`      |
| Bug fix       | `fix/`      | `fix/parse-error-handling`   |
| Documentation | `docs/`     | `docs/update-installation`   |
| Refactor      | `refactor/` | `refactor/simplify-parser`   |
| Tests         | `test/`     | `test/add-integration-tests` |

```bash
git checkout -b feature/my-feature
```

---

### 2. Implement Changes

- Follow the project’s [Code Style](code-style.md)
- Keep changes focused and minimal
- Add or update tests where applicable

---

### 3. Run Tests

```bash
# Full test suite
pytest

# With coverage
pytest --cov=depkeeper

# Specific test file
pytest tests/unit/test_parser.py

# Tests matching a pattern
pytest -k "test_parse"
```

---

### 4. Run Linters and Type Checks

```bash
# Run all checks
pre-commit run --all-files

# Individual tools
black .
isort .
mypy depkeeper
```

All checks must pass before submitting a pull request.

---

### 5. Commit Changes

Write clear, meaningful commit messages:

```bash
git add .
git commit -m "feat: add lock file generation

- Implement lock file writer
- Add hash verification
- Update documentation"
```

The project follows **Conventional Commits**:

| Prefix      | Purpose              |
| ----------- | -------------------- |
| `feat:`     | New feature          |
| `fix:`      | Bug fix              |
| `docs:`     | Documentation        |
| `style:`    | Formatting only      |
| `refactor:` | Internal refactoring |
| `test:`     | Tests                |
| `chore:`    | Maintenance tasks    |

---

### 6. Push and Open a Pull Request

```bash
git push origin feature/my-feature
```

Then open a Pull Request on GitHub with:

- A clear description of changes
- References to related issues (if any)
- Test results or validation notes

---

## Makefile Shortcuts

The `Makefile` provides commonly used development commands:

```bash
make install       # Install dependencies (dev mode)
make test          # Run tests
make coverage      # Run tests with coverage
make lint          # Run linters
make format        # Format code
make clean         # Remove build artifacts
make docs          # Build documentation
make docs-serve    # Serve documentation locally
```

---

## Environment Variables

The following variables are useful during development:

```bash
# Enable debug logging
export DEPKEEPER_LOG_LEVEL=DEBUG

# Disable colored output
export DEPKEEPER_COLOR=false
```

---

## IDE Configuration

### VS Code

Recommended extensions:

- Python
- Pylance
- Black Formatter
- isort
- Even Better TOML

Suggested `.vscode/settings.json`:

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/venv/bin/python",
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": ["tests"],
  "[python]": {
    "editor.formatOnSave": true,
    "editor.defaultFormatter": "ms-python.black-formatter"
  }
}
```

---

### PyCharm

1. Set project interpreter to `./venv/bin/python`
2. Mark `depkeeper` as _Sources Root_
3. Mark `tests` as _Test Sources Root_
4. Configure pytest as the test runner

---

## Troubleshooting

### Virtual Environment Issues

```bash
rm -rf venv
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

---

### Import Errors

Ensure the virtual environment is active:

```bash
which python
# Expected: path/to/depkeeper/venv/bin/python
```

---

### Pre-commit Failures

```bash
# Update hooks
pre-commit autoupdate

# Run a specific hook
pre-commit run black --all-files
```

---

## Next Steps

- **[Code Style](code-style.md)** — Coding standards and formatting
- **[Testing](testing.md)** — Writing and running tests
- **[Release Process](release-process.md)** — Versioning and releases
