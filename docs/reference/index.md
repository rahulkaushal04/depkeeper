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
- **[JSON output](json-output.md)** — The `--format json` schema, field by field.
- **[Error reference](errors.md)** — Exception hierarchy and a catalogue of user-visible messages.
- **[Known limitations](limitations.md)** — Behaviours that are surprising, constrained or not yet implemented.
- **[Python API](python-api.md)** — Generated API documentation for programmatic use.

---

## Quick reference

```bash
# Global
depkeeper [-c PATH] [-v|-vv] [--color|--no-color] [--version] [-h] COMMAND

# Read-only
depkeeper check [FILE] [--outdated-only] [-f table|simple|json]
                       [--strict-version-matching]
                       [--check-conflicts|--no-check-conflicts]

# Write
depkeeper update [FILE] [--dry-run] [-y] [--backup] [--pin]
                        [--allow-hash-removal] [-p NAME]...
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
| Exit codes | `0` success · `1` error · `2` usage · `130` interrupted |
