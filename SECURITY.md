# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| `1.x` | Yes (latest release only) |
| `< 1.0` | No |

Fixes ship in the latest `1.x` release. We do not backport. Please upgrade.

---

## Report a vulnerability

> [!WARNING]
> Do **not** open a public issue for a security problem.

Report it privately: go to the repository **Security** tab and choose **Report a vulnerability**,
or use
<https://github.com/rahulkaushal04/depkeeper/security/advisories/new>.

Please include:

1. What the problem is
2. The impact (what an attacker can do)
3. Versions you tested
4. Steps to reproduce, and a proof of concept if you have one
5. A suggested fix, if you have one

### What to expect

These are targets, not guarantees. depkeeper is maintained by volunteers.

| Stage | Target |
|---|---|
| Acknowledge your report | 3 business days |
| Confirm or reject it | 10 business days |
| Fix for a confirmed critical issue | 30 days |
| Updates while we work | about every 2 weeks |

After a fix we publish a GitHub Security Advisory, release a patched version, add a `Security`
entry to [CHANGELOG.md](CHANGELOG.md), and credit you if you want.

### Safe harbour

If you act in good faith, test only against your own files and machines, do not harm others, and
give us reasonable time to fix the issue before disclosing it, we will not take legal action
against you.

---

## Scope

**In scope**

- Parsing bugs triggered by malicious or malformed dependency files
- Unsafe file handling: path traversal, symlinks, permissions, partial writes
- Code execution caused by analysed input
- Network handling: TLS, redirects, SSRF, response handling
- Hash handling (`--hash`) that silently weakens integrity
- Denial of service from a normally sized input file

**Out of scope**

- Bugs in third-party dependencies (report upstream, but tell us if depkeeper makes them exploitable)
- Denial of service that needs huge inputs or extreme resources
- Social engineering and physical access
- Unsupported versions
- Features depkeeper does not have, such as private-index authentication
  ([limitations](https://github.com/rahulkaushal04/depkeeper/blob/main/docs/reference/limitations.md))

---

## Security design

Facts about the current code:

| Property | Behaviour |
|---|---|
| Writes | Atomic: temp file, then replace. Multi-file updates roll back if a later write fails. |
| Network | depkeeper's own requests go to `https://pypi.org` only. Redirects must stay on HTTPS and on the same host or a PyPI host (`pypi.org`, `files.pythonhosted.org`), at most 5 hops. `update --verify` runs pip, which uses your own pip index settings. |
| Response size | Bodies over 64 MB are rejected. |
| Input size | Dependency files over 10 MB are rejected. |
| Credentials | URL credentials (`user:pass@`) are redacted in error output and in `--verify` output. |
| Code execution | depkeeper does not import or run the packages it analyses. The one exception is `update --verify`. |
| `--verify` | Runs `pip install --dry-run --only-binary=:all:` in a subprocess (no shell). Because only wheels are allowed, pip never builds a source distribution or runs a package's build code. |
| Hashes | Updates that would remove `--hash` entries are refused unless you pass `--allow-hash-removal`. |

### Known limits

- Include paths (`-r`, `-c`) are not confined to the project directory. Run `--dry-run` first on files you do not trust.
- There is no file locking. Do not edit a file while depkeeper updates it.
- Recommendations come from PyPI metadata. depkeeper never installs, so keep `pip` and your tests as the gate.

### Tips for users

- Pin depkeeper in automation and keep it current.
- Review the diff from `update`, then install and test.
- Run in a virtual environment, not as root.
- Use `pip-audit` or `safety` too. depkeeper reports version drift, not advisories.
