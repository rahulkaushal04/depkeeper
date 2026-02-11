---
title: Reference
description: Technical reference documentation for depkeeper
---

# Reference

Complete technical reference documentation for depkeeper. These pages provide detailed specifications for the CLI, Python API, configuration, file formats, and exit codes.

---

## Reference Sections

<div class="grid cards" markdown>

-   :material-console:{ .lg .middle } **[CLI Commands](cli-commands.md)**

    ---

    Complete command-line interface reference with all options and examples.

    [:octicons-arrow-right-24: View commands](cli-commands.md)

-   :material-api:{ .lg .middle } **[Python API](python-api.md)**

    ---

    Programmatic interface for integrating depkeeper into your tools.

    [:octicons-arrow-right-24: View API](python-api.md)

-   :material-cog:{ .lg .middle } **[Configuration Options](configuration-options.md)**

    ---

    All configuration options, environment variables, and defaults.

    [:octicons-arrow-right-24: View options](configuration-options.md)

-   :material-exit-run:{ .lg .middle } **[Exit Codes](exit-codes.md)**

    ---

    Exit code meanings for scripting and CI/CD integration.

    [:octicons-arrow-right-24: View codes](exit-codes.md)

-   :material-file-document:{ .lg .middle } **[File Formats](file-formats.md)**

    ---

    Supported file format specifications and syntax reference.

    [:octicons-arrow-right-24: View formats](file-formats.md)

</div>

---

## Quick Reference

### Most Common Commands

```bash
# Check for updates
depkeeper check

# Update all packages
depkeeper update

# Preview updates without applying
depkeeper update --dry-run

# Update with backup
depkeeper update --backup -y

# JSON output for CI
depkeeper check --format json
```

### Environment Variables

| Variable | Description |
|---|---|
| `DEPKEEPER_CONFIG` | Configuration file path |
| `DEPKEEPER_COLOR` | Enable/disable colors |

### Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Error |
| `2` | Usage error |
| `130` | Interrupted |

---

## Version Information

Current version: **0.1.0**

```bash
depkeeper --version
```

See the [Changelog](../community/changelog.md) for version history.
