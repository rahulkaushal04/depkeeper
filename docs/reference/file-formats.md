---
title: File Formats
description: Accepted requirements-file syntax, encoding rules and rewrite semantics
---

# File Formats

depkeeper reads and writes **pip requirements files** (`requirements*.txt`), **`pyproject.toml`**
(`[project]` / optional / PEP 735 dependency groups and Poetry tables) and conda **`environment.yml`**
(including its `pip:` list). It does not read `Pipfile`, `poetry.lock`, `setup.py` or `setup.cfg`.
The rest of this page describes requirements-file syntax. In `pyproject.toml`, dependency strings
containing backslash escapes before the environment marker are skipped with a warning naming `file:line`; see [pyproject.toml](#pyprojecttoml) below. In `environment.yml`,
fuzzy specs such as `numpy=1.24` pin a series and update only to a newer series (`numpy=1.26`).

Behavioural background: [Requirements parsing](../concepts/requirements-parsing.md).

---

## File selection

`FILE` defaults to `requirements.txt`; when that is absent and the current directory holds other
supported files, the directory is scanned. A directory argument is scanned the same way (not
recursively) for `requirements*.txt`, `pyproject.toml` and `environment.yml`/`environment.yaml` that
contain dependencies. Any other `*.txt` / `*.in` name given explicitly is read as a
requirements file. The separate `find_requirements_files` helper in the [Python API](python-api.md) (recursive by default) uses these patterns from `constants.py`:

| Category | Patterns |
|---|---|
| requirements | `requirements.txt`, `requirements-*.txt`, `requirements/*.txt` |
| constraints | `constraints.txt`, `constraints-*.txt` |
| backup | `*.backup` |

---|---|
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

Extras and PEP 508 environment markers are captured and preserved. Markers are **not** evaluated
(except by `update --verify`, which drops requirements whose marker is false for the target Python):
depkeeper reports every requirement in the file regardless of whether its marker matches.

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

Parsed and reported; **never updated**. Always add `#egg=<name>` — without it the name is inferred from the URL's last
path segment (with a warning) and is usually wrong, and a URL with no inferable name raises `ParseError`.

### Hashes

```text
requests==2.31.0 --hash=sha256:abcdef...
requests==2.31.0 --hash sha256:abcdef...
```

Both separators are accepted. Hashed requirements are refused by `update` unless
`--refresh-hashes` (regenerate sha256 hashes from PyPI) or `--allow-hash-removal` (drop them) is passed.

Backslash line continuations (the default output of `pip-compile --generate-hashes`) are joined
before parsing:

```text
requests==2.31.0 \
    --hash=sha256:aaa... \
    --hash=sha256:bbb...
```

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

Any other option line raises `ParseError` (`Invalid requirement syntax: ...`).

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

```text
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

```text
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

```text
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

> [!NOTE]
> **Inline comments can become stale**
>
> The comment above still says "capped: 2.3 needs a newer werkzeug" after the version moved.
> depkeeper preserves comments verbatim; it does not interpret or update them.

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

## `pyproject.toml`

Parsed with `tomli`; edits replace only the specifier characters inside the original text, so
comments, quoting, layout and line endings survive (the result is re-validated as TOML).

| Section | Read |
|---|---|
| `[project].dependencies`, `[project.optional-dependencies].*` | Yes (PEP 508 strings) |
| `[dependency-groups].*` (PEP 735) | Yes; `{include-group = ...}` entries are skipped with a warning |
| `[build-system].requires` | Yes |
| `[tool.uv].dev-dependencies`, `[tool.pdm.dev-dependencies].*`, `[tool.hatch.envs.*]` `dependencies`/`extra-dependencies` | Yes (PEP 508 strings) |
| `[tool.poetry.dependencies]`, `dev-dependencies`, `group.*.dependencies` | Yes: `"1.2.3"`, `"==1.2.3"`, `">=1,<2"`, `"^1.2"`, `"~1.2"`, `{version = "..."}` |
| Poetry `*`, `||` constraints, git/path/url/file tables, list-of-table values | Skipped |
| `[project].requires-python` | Used as the target Python (lowest minor), never updated |
| `[tool.poetry.dependencies].python` | Same, translated to a PEP 440 range (`^3.9` is `>=3.9,<4`, `~3.9` is `>=3.9,<3.10`); used only when `[project].requires-python` is absent; never updated; a `python` key in a group is ignored |

Poetry `^` / `~` keep their style (`^1.2` → `^1.5.0`); `--pin` writes `==`. A bare name (no specifier) is
only pinned with `--pin`. Dependency strings with backslash escapes in the name or version part are skipped with a warning;
escapes in the marker (for example `\"` in `python_version < \"3.9\"`) are fine.

---

## conda `environment.yml`

`environment.yml` / `environment.yaml` files are read by a small built-in line reader (no YAML
dependency) that supports block-style `dependencies:` lists and a nested `- pip:` list.

> [!WARNING]
> **Conda results are approximate**
>
> Packages under `pip:` are checked against PyPI exactly like `requirements.txt` entries.
> Conda-channel packages are looked up on **PyPI by name only**. Conda and PyPI can disagree on
> names, versions and release timing, so treat these recommendations as hints and verify them
> with `conda search` before changing an environment. They are flagged `approximate`.

| Entry | Handling |
|---|---|
| `numpy=1.24`, `numpy=1.24.*`, `numpy 1.24.*` | Checked; rewritten as `numpy=1.26` / `numpy=1.26.*` (precision and style kept) |
| `numpy>=1.24,<2`, `numpy==1.24.1` | Checked; rewritten with the usual upper-bound preservation |
| `conda-forge::numpy=1.24` | Channel prefix kept |
| `numpy=1.24=py311_0` (build string), `a=1\|2`, `a=*` | Skipped, left untouched |
| `python=3.11` | Never updated; used as the file's Python constraint |
| Known conda-only names (`pip`, `mkl`, `openssl`, `ca-certificates`, `zlib`, `xz`, `tk`, `sqlite`, `readline`, `ncurses`, `libffi`, `libgomp`, `libxml2`, `cudatoolkit`, `cudnn`, `nccl`, `pytorch-cuda`, `r-base` and similar) and conda-only families (`lib*-ng`, `libgcc*`, `libstdcxx*`, `libgfortran*`, `liblapack`/`libblas`, `_*` helpers, `r-*`, CUDA components such as `cuda-nvcc`, `cuda-runtime`, `cuda-version`) | Skipped quietly (not PyPI packages) |
| Any other name, e.g. `cuda-python`, `libvirt-python`, `mkl-service`, `librosa`, `samtools` | Looked up on PyPI by name; if PyPI has no such project, one warning lists it as not found and the entry is left unchanged |

Flow-style lists (`dependencies: [a, b]`) are rejected with a parse error. Edits are in place;
comments, quoting, indentation and line endings are preserved.

---

## Backup files

`--backup` writes `<stem>.<timestamp>_<uuid8>.backup<suffix>` beside each affected file:

```text
requirements.txt.20260815_144129_853745_d54d785d.backup
```

The original suffix stays last so the file remains recognisable by extension. depkeeper never
deletes backups. Add `*.backup` to `.gitignore` if you use the flag in a repository.

> [!NOTE]
> **A second, different backup layout exists**
>
> The programmatic helper `create_backup()` uses `<name><suffix>.<timestamp>_<uuid8>.backup`,
> and `restore_backup()`'s target inference only understands **that** layout. The CLI uses
> `create_timestamped_backup()`, so CLI-produced backups must be restored by copying them
> manually. See [Python API](python-api.md#filesystem-utilities).