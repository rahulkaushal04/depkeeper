# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| `0.1.x` | Yes |
| `< 0.1` | No |

depkeeper is in early development. Security patches are provided only for the latest `0.1.x`
release; upgrade rather than expect a backport.

---

## Reporting a vulnerability

> [!WARNING]
> **Do not open a public GitHub issue for a security vulnerability.**

Use a private channel:

- The repository's **Security** tab → **Report a vulnerability**
  (<https://github.com/rahulkaushal04/depkeeper/security/advisories/new>)
- A **private GitHub Discussion** with the maintainers

### What to include

1. **Description** — what the issue is.
2. **Impact** — what an attacker can achieve.
3. **Affected versions** — which versions you tested.
4. **Reproduction steps** — enough for us to verify it.
5. **Proof of concept** — if available.
6. **Suggested fix** — if you have one.

```text
Subject: [SECURITY] Path traversal via -r include directive

Description:
A requirements file containing `-r ../../../etc/example.txt` causes `depkeeper update`
to write outside the invocation directory.

Impact:
Arbitrary file modification with the privileges of the invoking user.

Affected Versions:
0.1.0

Reproduction:
1. Create requirements.txt containing the directive above
2. Run `depkeeper update -y`
3. Observe the write outside the project directory

Suggested Fix:
Confine include resolution with utils.filesystem.validate_path.
```

### What to expect

| Stage | Target |
|---|---|
| Initial acknowledgement | 48 hours |
| Validation decision | 5 business days |
| Status updates | every 5–7 days |
| Resolution for critical issues | within 30 days |

Our process: acknowledge → investigate and validate → develop and test a fix → coordinate
disclosure with you → publish a GitHub Security Advisory → credit you, if you wish.

When a vulnerability is fixed we publish an advisory at
<https://github.com/rahulkaushal04/depkeeper/security/advisories>, ship a patched release, record
a `Security` entry in [CHANGELOG.md](CHANGELOG.md), and announce it in the GitHub release notes.

---

## Scope

### In scope

- Parser, checker, resolver and writer logic, including malicious or malformed requirements files
- Unsafe file operations: path traversal, symlink handling, permission or ownership changes
- Any code execution triggered by analysed input
- Transport security: TLS verification, downgrade, SSRF, request handling
- Integrity controls, in particular the `--hash` handling described below
- Denial of service reachable with a realistically sized input file

### Out of scope

- Vulnerabilities in third-party dependencies (report those upstream; tell us if depkeeper's usage
  makes them exploitable)
- Denial of service requiring extreme resources or an input beyond the 10 MB file limit
- Social engineering and physical access attacks
- Issues affecting unsupported versions
- Features depkeeper does not implement — for example private-index authentication, which does not
  exist (see [Limitations](https://rahulkaushal04.github.io/depkeeper/reference/limitations/))

---

## Security model

Context for reviewers assessing depkeeper for use in a controlled environment. Mechanisms are
documented at <https://rahulkaushal04.github.io/depkeeper/guides/operations/#security-posture>.

| Property | Behaviour |
|---|---|
| Code execution | depkeeper **never** imports, installs, builds or executes the packages it analyses. It reads JSON metadata only. |
| Network destinations | `https://pypi.org` only, with certificate verification always enabled. There is no flag to disable verification. |
| Outbound data | Package **names**, as URL path segments. Versions, comments and file contents never leave the machine. |
| Credentials | None are read, stored or transmitted. depkeeper has no authentication support. |
| Persisted state | None outside the working directory. No cache directory, no writes to `$HOME`. |
| File writes | Only the requirements files reached from the file you named, plus optional backups beside them. |
| Write integrity | Atomic replace with `fsync`, file-mode preservation, and rollback of a partially committed multi-file batch. |
| Input limits | 10 MB per file. |
| Parsing safety | No `eval`, no shell invocation, no dynamic import of analysed content. Version and specifier handling is delegated to `packaging`. |
| Hash integrity | Updates that would strip `--hash` entries are **refused** unless `--allow-hash-removal` is passed explicitly. |
| Path controls | `utils.filesystem.validate_path` can confine a resolved path to a base directory. |

### Known residual risks

| Risk | Detail | Mitigation |
|---|---|---|
| **Write scope via `-r` includes** | Include paths resolve relative to the including file and may contain `../`, so a hostile requirements file can direct `update` writes outside the invocation directory. | Run `--dry-run` first. Run in a container with only the project directory mounted. Never run `update` unattended on untrusted input. |
| **Partially hashed files** | `--allow-hash-removal` strips digests only from changed lines, producing a file that `pip --require-hashes` rejects. | Regenerate hashes immediately: `pip-compile --generate-hashes`. |
| **Metadata trust** | Recommendations derive from PyPI metadata; compromised metadata influences which version is proposed. | depkeeper never installs — `pip` and your test suite remain the gate. |
| **No file locking** | depkeeper reads once and writes once; a concurrent edit between those points is lost. | Do not run depkeeper concurrently with an editor on the same file. |

---

## Guidance for users

- Run the latest release, and pin the version in automation.
- Treat `depkeeper update` as a code change: review the diff, then `pip install -r` and run tests.
- Prefer `--dry-run` on any file you did not write.
- Run inside a virtual environment; do not run as root.
- Restrict write access in automation to the project directory.
- Run a vulnerability scanner (`pip-audit`, `safety`) alongside depkeeper — depkeeper reports
  version drift, not advisories.

---

## Recognition

depkeeper has no paid bug bounty programme. We credit reporters in the advisory and the changelog,
and are glad to provide a written acknowledgement of the contribution on request.

No vulnerabilities have been reported to date.
