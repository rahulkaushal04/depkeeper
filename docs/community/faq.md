---
title: Frequently Asked Questions
description: Common questions about depkeeper installation, usage, configuration, and troubleshooting
---

# Frequently Asked Questions

This page answers common questions about depkeeper. If your question is not covered here, check the [Troubleshooting Guide](../guides/troubleshooting.md) or open an issue on [GitHub](https://github.com/rahulkaushal04/depkeeper/issues).

---

## General

### What is depkeeper?

depkeeper is a modern Python dependency management tool that helps you keep your `requirements.txt` files up-to-date and conflict-free. It analyzes your dependencies, checks for available updates, resolves conflicts, and applies safe upgrades.

### How is depkeeper different from pip-tools?

depkeeper focuses on intelligent update checking and dependency conflict resolution, while pip-tools focuses on compiling and syncing dependencies.

| Feature | depkeeper | pip-tools |
|---|---|---|
| Update checking | Yes, built-in | Manual |
| Dependency conflict resolution | Yes, automatic | No |
| Safe major version boundaries | Yes, enforced | No |
| Multiple output formats | Yes (table, simple, JSON) | No |
| Dry-run mode | Yes | Yes |

### How is depkeeper different from poetry?

depkeeper is designed for projects using `requirements.txt`, while poetry uses `pyproject.toml`. depkeeper is non-invasive and works alongside pip without changing your existing workflow or project structure.

### Is depkeeper free?

Yes. depkeeper is open source and free to use under the [Apache License 2.0](license.md).

---

## Installation

### What Python version do I need?

depkeeper requires Python 3.8 or later. It supports Python 3.8, 3.9, 3.10, 3.11, and 3.12.

### Can I install depkeeper globally?

Yes, but we recommend using pipx for global installation to avoid polluting your system Python:

```bash
pipx install depkeeper
```

### Does depkeeper work on Windows?

Yes. depkeeper works on Windows, macOS, and Linux.

---

## Usage

### How do I check for updates?

Use the `check` command to scan your requirements file for available updates:

```bash
depkeeper check
```

You can target a specific file and show only outdated packages:

```bash
depkeeper check requirements.txt --outdated-only
```

### How do I update dependencies?

Use the `update` command. Preview changes first with `--dry-run`, then apply:

```bash
depkeeper update --dry-run
depkeeper update
```

### Can I update specific packages?

Yes. Use the `-p` flag to select individual packages:

```bash
depkeeper update -p flask -p click
```

### How does depkeeper handle major version boundaries?

depkeeper never crosses major version boundaries when recommending updates. If your current version is `1.2.3`, depkeeper will recommend up to the latest `1.x.x` release, but will not suggest `2.0.0`. This protects you from breaking changes.

### What output formats are available?

The `check` command supports three output formats:

| Format | Flag | Description |
|---|---|---|
| Table | `--format table` | Rich formatted table (default) |
| Simple | `--format simple` | Plain text output |
| JSON | `--format json` | Machine-readable JSON |

### Does depkeeper resolve dependency conflicts?

Yes. When `--check-conflicts` is enabled (the default), depkeeper builds a dependency graph, detects version conflicts between packages, and iteratively adjusts recommendations until a conflict-free set is found.

---

## Security

### Is it safe to run depkeeper update?

Yes. depkeeper never crosses major version boundaries, supports `--dry-run` to preview changes, and offers `--backup` to create timestamped backups before writing. For more details, see the [Security Policy](security.md).

---

## Configuration

### Where should I put my config file?

You can pass a configuration file path directly with the `--config` flag or set the `DEPKEEPER_CONFIG` environment variable:

```bash
depkeeper check --config path/to/config.toml
```

### Can I control colored output?

Yes. Use `--no-color` to disable colored terminal output, or set the `DEPKEEPER_COLOR` environment variable:

```bash
depkeeper check --no-color
```

### What verbosity levels are available?

Use `-v` for verbose output and `-vv` for maximum detail:

```bash
depkeeper check -v
depkeeper check -vv
```

---

## Troubleshooting

### Why am I getting parsing errors?

Ensure your `requirements.txt` follows PEP 508 format. Common issues include:

- Invalid characters in package names
- Malformed version specifiers (e.g., missing operators)
- Incorrect URL syntax for VCS dependencies

depkeeper supports all standard PEP 440/508 formats including extras, environment markers, include directives, constraint files, VCS URLs, editable installs, and hash verification.

### Why is depkeeper slow?

depkeeper uses concurrent async HTTP requests to query PyPI, so it is generally fast. If you experience slowness:

- Check your network connection
- Reduce request volume if you are being rate-limited by PyPI
- Consider using a private PyPI mirror for large dependency sets

### Where can I report bugs?

Open an issue on [GitHub](https://github.com/rahulkaushal04/depkeeper/issues). Include your OS, Python version, depkeeper version, and steps to reproduce the problem.

---

## Contributing

### How can I contribute?

See the [Contributing Guide](../contributing/index.md) for setup instructions, testing, and pull request guidelines.
