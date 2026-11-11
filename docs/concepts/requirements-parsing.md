---
title: Requirements Parsing
description: What the parser accepts, how directives are resolved, and what it cannot represent
---

# Requirements Parsing

`RequirementsParser` turns pip-style text into `Requirement` objects. It is deliberately
pip-shaped: line-based, directive-aware, and tolerant of the things pip tolerates.

It is the engine of the `requirements.txt` source adapter (which also takes `*.txt` and `*.in`
files). `pyproject.toml` and conda `environment.yml` files are read by their own adapters in
`depkeeper/core/sources/`; they reuse this parser for individual PEP 508 strings, and everything
below about `-r`, `-c`, hashes and line endings applies to requirements files.

---

## Supported line types

| Line | Handling |
|---|---|
| `requests>=2.25.0` | PEP 508 requirement. Delegated to `packaging`. |
| `pkg[extra1,extra2]>=1.0` | Extras captured; preserved on rewrite. |
| `pkg>=1.0; python_version >= "3.9"` | Marker captured as a string; preserved on rewrite. |
| `-r other.txt` / `-rother.txt` / `-r=other.txt` / `--requirement other.txt` / `--requirement=other.txt` | Recursively parsed; results flattened into the list. |
| `-c constraints.txt` / `--constraint ...` (same spellings as `-r`) | Parsed into the constraint map; **not** returned as requirements. |
| `-e .` / `--editable git+https://...` | Editable requirement. Never updated. |
| `git+https://host/repo.git#egg=name` | Direct VCS reference. Never updated. |
| `https://host/pkg-1.0.tar.gz` | Direct URL reference. Never updated. |
| `./local/pkg`, `/abs/path`, `C:\path` | Local path, resolved to a `file://` URI. Never updated. |
| `pkg==1.0 --hash=sha256:...` | Hashes captured. Both `--hash=X` and `--hash X` forms, on one line or on `\` continuation lines. |
| `pkg==1.0 \` + next line | Backslash continuations are joined before parsing, as pip does. An odd number of trailing backslashes continues; a comment line never continues. |
| `pkg==1.0  # comment` | Inline comment captured and preserved. |
| `# comment`, blank line | Ignored, and preserved verbatim on rewrite. |
| `--index-url`, `-i`, `--extra-index-url`, `--find-links`, `-f`, `--trusted-host`, `--no-binary`, `--only-binary`, `--use-feature`, `--pre`, `--prefer-binary` | Recognised pip global options. Skipped, not an error. **They do not change depkeeper's behaviour.** |

Anything else raises `ParseError` with the line number, the line content and the file path. Credentials embedded in URLs (`user:pass@`) are masked as `***@` in those messages.

---

## Include directives (`-r`)

```text
-r requirements/base.txt
click~=8.0
```

- Relative paths resolve against the **directory of the including file**, matching pip.
- Requirements from the included file are flattened into a single result list.
- Circular includes are detected before reading and raise `ParseError` with the full chain:
  `Circular dependency detected: a.txt -> b.txt -> a.txt`.
- A directive with no path logs a warning and is skipped.
- Errors inside the included file are re-raised as a `ParseError` that names the *including*
  line, so the diagnostic points at the directive you can fix.

### Provenance and multi-file writes

Each `Requirement` records the absolute path of the file it came from in `source_file`. This is
what allows `update` to rewrite the correct file:

```bash
depkeeper update main.txt -y
```

```text
-r sub/base.txt
click~=8.4
```

```text
requests==2.34.2
```

Without provenance, line 1 of `sub/base.txt` would have been matched against line 1 of `main.txt`
and the `-r` directive itself would have been overwritten. `source_file` is excluded from
`Requirement` equality — it is provenance, not identity.

> [!WARNING]
> **`update` writes every included file**
>
> Running `depkeeper update main.txt` can modify files you did not name on the command line.
> `--backup` backs up **all** affected files, not only the primary one. Preview with
> `--dry-run` when the include graph is unfamiliar.

---

## Constraint directives (`-c`)

`-c constraints.txt` parses the referenced file with `is_constraint_file=True`. Its requirements
are stored in an internal map keyed by package name and applied to matching requirements during
parsing (recorded in `Requirement.constraint_specs`); they are never returned as requirements of
their own, and constraint files are never rewritten. Constraint specs bind recommendations like
any other upper bound: a version a `-c` file forbids is never proposed.

---

## Direct references

A requirement with a URL — VCS, HTTP(S), `file://`, or a local path — is parsed, reported, and
then **always skipped by `update`**. There is no PyPI version to move to, and appending a
specifier to a URL produces an uninstallable line such as
`-e git+https://...#egg=pkg==9.9.9`. `Requirement.to_string()` therefore omits specifiers whenever
a URL is present.

Editable installs (`-e`) are skipped for the same reason.

### Package-name inference

The name comes from the `#egg=` fragment when present; it must be a plain project name
(`../bad` is rejected with `Invalid '#egg=' name`). Otherwise:

- **Local paths**: the basename, with `.tar.gz`, `.tar.bz2`, `.zip` or `.whl` stripped.
- **URLs**: the last path segment, which is unreliable. A bare wheel URL such as
  `https://host/rich-13.7.1-py3-none-any.whl` yields the name `rich-13-7-1-py3-none-any-whl`.
  A `WARNING` is logged naming the inferred value.
- If nothing can be inferred from a URL, `ParseError` is raised:
  `URL requirements must include '#egg=<name>' or an inferable package name.`

**Always add an explicit `#egg=<name>` fragment** to direct URL requirements.

---

## Hashes

Both forms are recognised by one regular expression, so extraction and removal can never
disagree:

```text
pkg==1.0 --hash=sha256:abc...
pkg==1.0 --hash sha256:abc...
```

Hashed requirements are **refused by `update` by default**:

```text
[ERROR] Refusing to update requirement(s) with --hash entries: six. Hashes are version-specific
and cannot be silently removed. Re-run with --refresh-hashes to regenerate them, or
--allow-hash-removal to proceed without hashes.
```

Exit code `1`; nothing is written. Two ways forward:

- `--refresh-hashes` fetches the new version's `sha256` digests from PyPI and rewrites the hash
  lines in the original layout (single-line or `\` continuations). If a package has no digests,
  depkeeper refuses and writes nothing. Only `sha256` is written; other hash types are replaced
  with a warning. It cannot be combined with `--allow-hash-removal` (usage error, exit `2`).
- `--allow-hash-removal` strips the digests **only from the lines being updated**. The result is
  a partially hashed file, which `pip install --require-hashes` rejects outright; regenerate
  hashes afterwards with `pip-compile --generate-hashes` or `hashin`.

See
[Updating dependencies → Hashed requirements](../guides/updating-dependencies.md#hashed-requirements).

---

## Encoding and byte order marks

- Files are read as `utf-8-sig`, which decodes plain UTF-8 identically to `utf-8` but also strips
  a leading byte order mark. Windows editors (Notepad, PowerShell `Set-Content`) write BOMs, and
  an unstripped BOM corrupts the first token of line 1 — `str.strip()` does not remove it.
- `parse_string` strips a leading BOM defensively, for content that did not come from
  `safe_read_file`; the writer strips it before editing and re-adds it on write.
- On write, a file that carried a BOM is re-encoded with `utf-8-sig` so the signature survives;
  everything else is written as plain `utf-8`.
- A file that is not valid UTF-8 raises `FileOperationError` on read.

## Line endings

Files are read for rewriting with `newline=""`, and each rewritten line is re-joined with **its
own** terminator. A CRLF file stays CRLF, an LF file stays LF, a mixed file keeps its mixture, and
a missing final newline is not added. depkeeper never normalises line endings, so it produces no
whitespace-only diffs.

---

## Specifier ordering

`packaging.SpecifierSet` is backed by a frozenset, so iteration order is not stable across
processes. The parser sorts specifiers by their position in the source line, so `specs` is both
deterministic and source-faithful. Without this, preserved ranges would churn between runs.

---

## Limits and rejections

| Guard | Value | Behaviour |
|---|---|---|
| Maximum file size | 10 MB | `FileOperationError: File too large` |
| Non-file path | — | `FileOperationError: Not a file` |
| Missing file | — | `FileOperationError: File not found` (via CLI: Click rejects it first with exit 2) |
| Empty version in a specifier | — | `ParseError: Invalid version specifier` |
| Invalid PEP 508 syntax | — | `ParseError: Invalid requirement syntax: <packaging message>` |

Example of a real parse failure:

```text
[ERROR] Failed to parse broken.txt: Invalid requirement syntax: Expected end or semicolon
(after name and no valid version specifier)
    this is !!! not a requirement
         ^ (line=2, content=this is !!! not a requirement, file=/path/broken.txt)
```

---

## Known parsing gaps

| Gap | Impact |
|---|---|
| URL name inference is unreliable | Add `#egg=`. |
| Unknown pip options raise `ParseError` | Only the options listed above are recognised; others (for example `--no-index`) fail the parse. |
| `--index-url` is parsed and ignored | depkeeper always queries `pypi.org`. Packages that exist only on a private index become `[ERROR]` rows. |

All of these are tracked in [Known limitations](../reference/limitations.md).

---

## Parser state

`RequirementsParser` is stateful: it maintains the include stack (for cycle detection) and the
constraint map. Both persist across `parse_file` calls on the same instance. Call `reset()` before
reusing a parser on an unrelated set of files, or construct a new one — which is what both CLI
commands do.
