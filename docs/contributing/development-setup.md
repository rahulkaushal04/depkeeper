---
title: Development Setup
description: Set up your local development environment for depkeeper
---

# Development Setup

Set up a local development environment for contributing to depkeeper.
This guide covers prerequisites, installation, workflows, and tooling configuration.

---

## Prerequisites

Install the following tools:

- **Python** ≥ 3.8
- **Git** for version control
- **Make** (optional) for development shortcuts

Verify your Python version:

```bash
python --version
```

---

## Installation

Choose between automated setup scripts or manual installation steps.

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

Manual setup provides full control over each installation step.

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

Confirm the installation succeeded:

```bash
# Verify CLI
python -m depkeeper --version

# Run test suite
pytest

# Run all linters and checks
pre-commit run --all-files
```

Each command should complete without errors.

---

## Development Workflow

### 1. Create a Branch

Use descriptive branch names with appropriate prefixes:

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

Run the test suite to verify your changes:

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

Ensure code quality standards are met:

```bash
# Run all checks
pre-commit run --all-files

# Individual tools
black .
mypy depkeeper
```

All checks must pass before opening a pull request.

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

Push your branch and create a pull request:

```bash
git push origin feature/my-feature
```

Include in your pull request:

- Clear description of changes
- References to related issues
- Test results or validation notes

---

## Makefile Shortcuts

Use these shortcuts for common development tasks:

```bash
make install       # Install depkeeper in production mode
make install-dev   # Install with dev dependencies and pre-commit hooks
make test          # Run tests with coverage reports
make typecheck     # Run mypy static type checks
make all           # Run typecheck and test together
make clean         # Remove cache and build artifacts
make docs          # Build documentation
make docs-serve    # Serve documentation locally
```

---

## Environment Variables

Configure these variables for development:

```bash
# Enable debug logging
export DEPKEEPER_LOG_LEVEL=DEBUG

# Disable colored output
export DEPKEEPER_COLOR=false
```

---

## IDE Configuration

### VS Code

Install these recommended extensions:

- Python
- Pylance
- Black Formatter
- Even Better TOML

Add this configuration to `.vscode/settings.json`:

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

Configure your PyCharm environment:

1. Set project interpreter to `./venv/bin/python`
2. Mark `depkeeper` as Sources Root
3. Mark `tests` as Test Sources Root
4. Configure pytest as the test runner

---

## Troubleshooting

### Virtual Environment Issues

Recreate the virtual environment:

```bash
rm -rf venv
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

---

### Import Errors

Verify the virtual environment is active:

```bash
which python
# Expected: path/to/depkeeper/venv/bin/python
```

---

### Pre-commit Failures

Update hooks or run them individually:

```bash
# Update hooks
pre-commit autoupdate

# Run a specific hook
pre-commit run black --all-files
```

---

## Next Steps

- [Code Style](code-style.md) -- Learn coding standards and formatting requirements
- [Testing](testing.md) -- Understand testing practices and guidelines
- [Release Process](release-process.md) -- Review versioning and release procedures
