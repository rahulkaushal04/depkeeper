---
title: Security Policy
description: Supported versions, vulnerability reporting and depkeeper's security posture
---

# Security Policy

The canonical policy lives in
[`SECURITY.md`](https://github.com/rahulkaushal04/depkeeper/blob/main/SECURITY.md) in the
repository. This page summarises it and adds the operational security context for the tool; if
the two ever disagree, `SECURITY.md` governs.

---

## Supported versions

| Version | Supported |
|---|---|
| `0.1.x` | ✅ |
| `< 0.1` | ❌ |

depkeeper is in early development. Security patches are provided only for the latest `0.1.x`
release; upgrade rather than backport.

---

## Reporting a vulnerability

> [!CAUTION]
> **Do not open a public issue for a security vulnerability**
>

Use a private channel:

- The repository's **Security** tab → **Report a vulnerability**, or directly
  <https://github.com/rahulkaushal04/depkeeper/security/advisories/new>

### Include

1. **Description** — what the issue is.
2. **Impact** — what an attacker can achieve.
3. **Affected versions** — which versions you tested.
4. **Reproduction steps** — enough to verify it.
5. **Proof of concept** — if available.
6. **Suggested fix** — if you have one.

### What to expect

| Stage | Target |
|---|---|
| Acknowledge your report | 3 business days |
| Confirm or reject it | 10 business days |
| Fix for a confirmed critical issue | 30 days |
| Updates while we work | about every 2 weeks |

Coordinated disclosure is appreciated: we will work with you to verify, fix and disclose
responsibly.

---

## Scope

### In scope

- Parser, checker, resolver and writer logic, including malicious or malformed requirements files
- Unsafe file operations: path traversal, symlink handling, permission or ownership changes
- Any code execution triggered by analysed input
- Transport security: TLS verification, downgrade, SSRF, request handling
- Integrity controls, in particular `--hash` handling
- Denial of service reachable with a realistically sized input file

### Out of scope

- Vulnerabilities in third-party dependencies (report those upstream; tell us if depkeeper's usage
  makes them exploitable)
- Denial of service requiring extreme resources or an input beyond the 10 MB file limit or the 20 MB response cap
- Social engineering and physical access attacks
- Issues affecting unsupported versions
- Features depkeeper does not implement — for example private-index authentication, which does not
  exist (see [Limitations](../reference/limitations.md))

---

## Security posture

Context for reviewers assessing depkeeper for use in a controlled environment. Mechanisms are
described in [Operations → Security posture](../guides/operations.md#security-posture).

| Property | Behaviour |
|---|---|
| Code execution | depkeeper does not import or run the packages it analyses. The one exception is `update --verify`, which runs `pip install --dry-run --only-binary=:all:` in a subprocess (no shell); wheels only, so no build code runs. |
| Network destinations | `pypi.org` only, over TLS. Redirects must be https and land on the same host, `pypi.org` or `files.pythonhosted.org`. Response bodies over 20 MB are rejected. (`--verify` runs pip with your own pip index settings.) |
| Outbound data | Package **names**, as URL path segments. Versions, comments and file contents never leave the machine. |
| Credentials | depkeeper reads, stores and sends none. URL credentials in dependency files are redacted from error and `--verify` output. |
| Persisted state | No cache directory and no `$HOME` writes. |
| File writes | Only the requirements files reached from the file you named, plus optional backups beside them. |
| Input size limit | 10 MB per file. |
| Untrusted input handling | The parser performs no `eval` and no shell invocation. |
| Integrity controls | Updates that would strip `--hash` entries are refused unless `--allow-hash-removal` is passed explicitly. |
| Write integrity | Atomic replace with `fsync`, mode preservation, and rollback of a partially committed multi-file batch. |
| Path controls | `utils.filesystem.validate_path` exists to confine a resolved path to a base directory, but it is **not** applied to `-r`/`-c` include resolution or to `update`'s write targets — see the residual risk below. |

### Residual risks

| Risk | Detail | Mitigation |
|---|---|---|
| Write scope via `-r` includes | Include paths are resolved relative to the including file and may contain `../`, so a hostile requirements file can direct `update` writes outside the invocation directory. | Run `--dry-run` first; run in a container with only the project directory mounted; never run `update` unattended on untrusted input. |
| Metadata trust | Recommendations are derived from PyPI metadata. Compromised or malicious metadata influences which version is proposed. | depkeeper never installs; `pip` and your test suite remain the gate. |
| Partially hashed files | `--allow-hash-removal` degrades a `--require-hashes` file. | Regenerate hashes immediately afterwards. |
| No file locking | A concurrent edit between depkeeper's read and write is lost. | Do not run depkeeper concurrently with an editor on the same file. |

---

## Staying secure

- Pin the depkeeper version and upgrade deliberately.
- Keep dependencies current — `depkeeper check` on a schedule is the intended workflow.
- Run a vulnerability scanner (`pip-audit`, `safety`) alongside depkeeper; depkeeper reports
  version drift, not advisories.
- Review every update before merging, especially downgrades.
- Restrict write access in automation to the project directory.
