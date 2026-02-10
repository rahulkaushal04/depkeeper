---
title: Installation
description: Install depkeeper for Python dependency management
---

# Installation

depkeeper can be installed using several methods. Choose the one that best fits your workflow.

---

## Requirements

- **Python**: 3.8 or higher
- **Operating System**: Windows, macOS, or Linux

---

## Installation Methods

### pip (Recommended)

The simplest way to install depkeeper is via pip:

```bash
pip install depkeeper
```

To install with specific version:

```bash
pip install depkeeper==0.1.0
```

### pipx (Isolated Environment)

For CLI tools, [pipx](https://pypa.github.io/pipx/) installs packages in isolated environments:

```bash
# Install pipx if you haven't
pip install pipx
pipx ensurepath

# Install depkeeper
pipx install depkeeper
```

!!! tip "Why pipx?"
    pipx is ideal for CLI tools like depkeeper because it:

    - Isolates dependencies from your global environment
    - Automatically creates and manages virtual environments
    - Makes the `depkeeper` command available globally

### From Source

For development or to get the latest features:

```bash
# Clone the repository
git clone https://github.com/rahulkaushal04/depkeeper.git
cd depkeeper

# Install in development mode
pip install -e .

# Or with development dependencies
pip install -e ".[dev]"
```

### Using Poetry

If your project uses Poetry:

```bash
poetry add depkeeper
```

### Using uv

For the fast [uv](https://github.com/astral-sh/uv) package manager:

```bash
uv pip install depkeeper
```

---

## Verify Installation

After installation, verify that depkeeper is working:

```bash
# Check version
depkeeper --version
# depkeeper 0.1.0

# View available commands
depkeeper --help
```

Expected output:

```
Usage: depkeeper [OPTIONS] COMMAND [ARGS]...

  depkeeper -- modern dependency management for requirements.txt files.

  Available commands:
    depkeeper check              Check for available updates
    depkeeper update             Update packages to newer versions

  Examples:
    depkeeper check
    depkeeper update
    depkeeper -v check

  Use ``depkeeper COMMAND --help`` for command-specific options.

Options:
  -c, --config PATH       Path to configuration file.
  -v, --verbose           Increase verbosity (can be repeated: -v, -vv).
  --color / --no-color    Enable or disable colored output.
  --version               Show the version and exit.
  -h, --help              Show this message and exit.

Commands:
  check   Check for available updates in requirements file.
  update  Update packages to newer versions.
```

---

## Upgrading

To upgrade to the latest version:

=== "pip"

    ```bash
    pip install --upgrade depkeeper
    ```

=== "pipx"

    ```bash
    pipx upgrade depkeeper
    ```

---

## Uninstalling

To remove depkeeper:

=== "pip"

    ```bash
    pip uninstall depkeeper
    ```

=== "pipx"

    ```bash
    pipx uninstall depkeeper
    ```

---

## Troubleshooting

### Command Not Found

If `depkeeper` is not found after installation:

1. **Check pip installation location**:
   ```bash
   pip show depkeeper
   ```

2. **Ensure pip's bin directory is in PATH**:

    === "Linux/macOS"

        ```bash
        export PATH="$HOME/.local/bin:$PATH"
        ```

    === "Windows"

        Add `%USERPROFILE%\AppData\Local\Programs\Python\Python3X\Scripts` to your PATH.

3. **Try running as a module**:

   ```bash
   python -m depkeeper --version
   ```

### Permission Errors

If you encounter permission errors:

```bash
# Use --user flag
pip install --user depkeeper

# Or use a virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows
pip install depkeeper
```

### SSL Certificate Errors

If you're behind a corporate proxy:

```bash
pip install --trusted-host pypi.org --trusted-host pypi.python.org depkeeper
```

---

## Next Steps

- [:material-play-circle: Quick Start](quickstart.md) -- Your first depkeeper commands
- [:material-book-open-variant: Basic Usage](basic-usage.md) -- Learn the fundamentals
