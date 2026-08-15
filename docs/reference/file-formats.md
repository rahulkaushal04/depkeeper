---
title: File Formats
description: Accepted requirements-file syntax, encoding rules and rewrite semantics
---

# File Formats

depkeeper reads and writes **pip requirements files** only. It does not read `Pipfile`,
`poetry.lock`, `pyproject.toml` dependency tables, `setup.py`, `setup.cfg` or `environment.yml`.

Behavioural background: [Requirements parsing](../concepts/requirements-parsing.md).

---

## File selection

`FILE` is an explicit argument, defaulting to `requirements.txt`. There is no automatic
discovery in the CLI — the glob patterns below exist in `constants.py` and are used only by the
`find_requirements_files` helper in the [Python API](python-api.md).

| Category | Patterns |
|---|---|
| requirements | `requirements.txt`, `requirements-*.txt`, `requirements/*.txt` |
| constraints | `constraints.txt`, `constraints-*.txt` |
| backup | `*.backup` |

---

## Line syntax

### Standard requirements

```text
requests
requests>=2.25.0
requests==2.31.0
requests>=2.25.0,<3.0.0
requests!=2.30.0,>=2.25.0
requests~=2.31.0
requests[security,socks]>=2.25.0
requests>=2.25.0; python_version >= "3.8"
requests>=2.25.0  # inline comment
```

| Operator | Supported | Classification on rewrite |
|---|---|---|
| `==` | ✅ | Exact pin — repinned (unless it is a wildcard). |
| `===` | ✅ | Exact pin — repinned. |
| `>=` | ✅ | Floor — rewritten. |
| `>` | ✅ | Floor — rewritten and **widened to `>=`**. |
| `~=` | ✅ | Floor — rewritten, keeping the author's precision. |
| `<`, `<=` | ✅ | Retained verbatim. |
| `!=` | ✅ | Retained verbatim. |
| `==2.*` | ✅ | Retained verbatim. |

Extras and PEP 508 environment markers are captured and preserved. Markers are **not** evaluated:
depkeeper reports every requirement in the file regardless of whether its marker matches the
current environment.

### Comments and blank lines

```text
# Full-line comment
requests>=2.25.0  # inline comment

# blank lines above and below are preserved
```

Both are preserved byte-for-byte by the writer. `#` inside a URL fragment is not treated as a
comment.

### Include directives

```text
-r requirements/base.txt
--requirement requirements/base.txt
```

Recursively parsed and flattened. Relative paths resolve against the **directory of the including
file**. Cycles raise `ParseError`. `update` rewrites the included file, not the directive.

### Constraint directives

```text
-c constraints.txt
--constraint constraints.txt
```

Parsed into an internal constraint map and applied to matching requirements. Constraint files are
never returned as requirements and are never rewritten.

### Editable installs

```text
-e .
-e ./local-package
--editable git+https://github.com/org/repo.git#egg=repo
```

Parsed and reported; **never updated**.

### Direct references

```text
git+https://github.com/org/repo.git@v1.0.0#egg=repo
git+ssh://git@github.com/org/repo.git#egg=repo
hg+https://…  bzr+https://…  svn+https://…
https://example.com/pkg-1.0.tar.gz#egg=pkg
file:///abs/path/pkg-1.0.whl#egg=pkg
./local/package
../sibling/package
/absolute/path/package
C:\absolute\path\package
```

Parsed and reported; **never updated**. Always add `#egg=<name>` — inference from the URL's last
path segment is unreliable, and a URL with no inferable name raises `ParseError`.

### Hashes

```text
requests==2.31.0 --hash=sha256:abcdef...
requests==2.31.0 --hash sha256:abcdef...
```

Both separators are accepted. Hashed requirements are refused by `update` unless
`--allow-hash-removal` is passed.

!!! warning "Line continuations are not supported"

    ```text
    requests==2.31.0 \
        --hash=sha256:aaa... \
        --hash=sha256:bbb...
    ```

    depkeeper does not join backslash continuations, so this — the default output of
    `pip-compile --generate-hashes` — fails to parse. Use the single-line form.

### pip global options

Recognised and skipped:

```text
--index-url https://pypi.org/simple
-i https://pypi.org/simple
--extra-index-url https://internal.example.com/simple
--find-links ./wheels
-f ./wheels
--trusted-host internal.example.com
--no-binary :all:
--only-binary :all:
--use-feature 2020-resolver
--pre
--prefer-binary
```

These are preserved in the file and **have no effect on depkeeper**. In particular, index options
do not redirect depkeeper's queries; it always uses `pypi.org`.

Any other option line raises `ParseError`.

---

## Encoding

| Aspect | Behaviour |
|---|---|
| Read encoding | `utf-8-sig` — plain UTF-8 plus BOM removal. |
| Write encoding | `utf-8`, or `utf-8-sig` when the file originally carried a BOM. |
| Non-UTF-8 input | `FileOperationError`. |
| Maximum size | 10 MB. |

## Line endings

Preserved exactly. Each rewritten line re-attaches its own terminator, so LF stays LF, CRLF stays
CRLF, a mixed file keeps its mixture, and a file without a trailing newline does not gain one.

---

## Rewrite semantics

Given:

```text title="requirements.txt"
# Web stack
requests==2.28.0
flask>=2.0,<2.3          # capped: 2.3 needs a newer werkzeug
celery[redis]>=5.0,<6.0
click~=8.0
certifi
urllib3==1.26.0

-e ./local-lib
git+https://github.com/org/tool.git@v1.0#egg=tool
```

`depkeeper update -y` produces:

```text title="requirements.txt (after)"
# Web stack
requests==2.34.2
flask>=2.2.5,<2.3          # capped: 2.3 needs a newer werkzeug
celery[redis]>=5.6.3,<6.0
click~=8.4
certifi==2026.7.22
urllib3==1.26.20

-e ./local-lib
git+https://github.com/org/tool.git@v1.0#egg=tool
```

`depkeeper update --pin -y` produces:

```text title="requirements.txt (after, --pin)"
# Web stack
requests==2.34.2
flask==2.2.5          # capped: 2.3 needs a newer werkzeug
celery[redis]==5.6.3
click==8.4.2
certifi==2026.7.22
urllib3==1.26.20

-e ./local-lib
git+https://github.com/org/tool.git@v1.0#egg=tool
```

Preserved in both cases: comments (including inline ones), blank lines, ordering, extras, markers,
directives, direct references, encoding and line endings.

!!! note "Inline comments can become stale"

    The comment above still says "capped: 2.3 needs a newer werkzeug" after the version moved.
    depkeeper preserves comments verbatim; it does not interpret or update them.

### Edge cases

| Input | Target | Output | Note |
|---|---|---|---|
| `pkg` | `1.2.3` | `pkg==1.2.3` | A requirement with no specifiers gains an exact pin. |
| `pkg<3.0` | `2.32.3` | `pkg<3.0,>=2.32.3` | A cap-only requirement gains a floor; order is not normalised. |
| `pkg>2.0` | `2.5.0` | `pkg>=2.5.0` | `>` is widened to `>=`. |
| `pkg~=2.0` | `2.3.3` | `pkg~=2.3` | The author's precision is kept. |
| `pkg~=2.0` | `2.0.30` | *(unchanged)* | Already covered by the declared floor; skipped for convergence. |
| `pkg==2.*` | `2.9.0` | `pkg==2.*,>=2.9.0` | A wildcard band is retained, and a floor is added. |
| `-e .` | any | *(unchanged)* | Editable installs are never updated. |

---

## Backup files

`--backup` writes `<stem>.<timestamp>_<uuid8>.backup<suffix>` beside each affected file:

```text
requirements.20260815_144129_853745_d54d785d.backup.txt
```

The original suffix stays last so the file remains recognisable by extension. depkeeper never
deletes backups. Add `*.backup.*` to `.gitignore` if you use the flag in a repository.

!!! note "A second, different backup layout exists"

    The programmatic helper `create_backup()` uses `<name><suffix>.<timestamp>_<uuid8>.backup`,
    and `restore_backup()`'s target inference only understands **that** layout. The CLI uses
    `create_timestamped_backup()`, so CLI-produced backups must be restored by copying them
    manually. See [Python API](python-api.md#filesystem-utilities).
