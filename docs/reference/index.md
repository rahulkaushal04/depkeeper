---
title: Reference
description: Exhaustive specifications for the CLI, configuration, formats, errors and Python API
---

# Reference

Specification-grade documentation. These pages state what is true, without tutorial framing.

- **[CLI commands](cli-commands.md)** — Every command, argument, flag, default and precedence rule.
- **[Configuration options](configuration-options.md)** — Config keys, environment variables, discovery and validation rules.
- **[Exit codes](exit-codes.md)** — Exit code semantics per command and scripting patterns.
- **[File formats](file-formats.md)** — Accepted requirements-file syntax, encodings and rewrite rules.
- **[JSON output](json-output.md)** — The `--format json` and `json-v2` schemas, field by field.
- **[Error reference](errors.md)** — Exception hierarchy and a catalogue of user-visible messages.
- **[Known limitations](limitations.md)** — Behaviours that are surprising, constrained or not yet implemented.
- **[Python API](python-api.md)** — Programmatic use: classes, functions and signatures.

---

## Quick reference

```bash
# Global
depkeeper [-c PATH] [-v|-vv] [--color|--no-color] [--version] [-h] COMMAND

# Read-only
depkeeper check [FILE] [--outdated-only] [-f table|simple|json|json-v2|markdown]
                       [--strict-version-matching|--no-strict-version-matching]
                       [--check-conflicts|--no-check-conflicts]
                       [--fail-on none|updates|minor|major] [--ignore PKG]...
                       [--python-version X.Y] [--min-age DURATION] [--allow-major PKG]...

# Write
depkeeper update [FILE] [--dry-run] [-y] [--backup] [--pin] [--verify]
                        [--allow-hash-removal | --refresh-hashes] [-p NAME]... [--ignore PKG]...
                        [--max-update patch|minor|major] [-f table|markdown]
                        [--python-version X.Y] [--min-age DURATION] [--allow-major PKG]...
                        [--strict-version-matching]
                        [--check-conflicts|--no-check-conflicts]
```

| Constant | Value |
|---|---|
| Default file | `requirements.txt` |
| Default format | `table` |
| Conflict checking | enabled |
| Strict version matching | disabled |
| Request timeout | 30 s |
| Retries | 3 (4 attempts) |
| Max file size | 10 MB |
| Concurrent requests | 10 |
| Resolution passes | 100 |
| Exit codes | `0` success · `1` error · `2` usage · `3` `--fail-on` tripped · `4` PyPI lookup failed · `130` interrupted |
