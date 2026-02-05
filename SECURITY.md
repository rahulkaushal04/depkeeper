# depkeeper Security Policy

We take the security of **depkeeper** seriously. This document outlines how we handle
vulnerability reports, which versions are supported, and how users can stay secure.

---

## 🔐 Supported Versions

We provide security patches only for the latest `0.1.x` series.

| Version   | Supported |
| --------- | --------- |
| **0.1.x** | ✔️ Yes    |
| **< 0.1** | ❌ No     |

As depkeeper is in early development, we strongly recommend upgrading to the **latest release** at all times.

---

## 🚨 Reporting a Vulnerability

**Do NOT create public GitHub issues for security vulnerabilities.**

To responsibly disclose a vulnerability, please use one of the following private channels:

- The repository’s **Security** tab → **Report a vulnerability**
- A **private GitHub Discussion** with the maintainers

We appreciate coordinated disclosure and will work with you to verify, fix, and publicly disclose issues responsibly.

### Include in Your Report

1. **Description** - Clear explanation of the issue
2. **Impact** - What an attacker could achieve
3. **Affected Versions** - Specific versions tested
4. **Reproduction Steps** - Required to verify the issue
5. **Proof of Concept (PoC)** - If available
6. **Potential Fix** - If you have thoughts or patches

Example format:

```

Subject: [SECURITY] Vulnerability in requirements parser

Description:
A crafted requirements.txt triggers arbitrary code execution …

Impact:
Remote code execution during dependency checks …

Affected Versions:
0.1.0 - 0.1.5

Reproduction:

1. Create file X
2. Run `depkeeper check`
3. Observe behavior

Proof of Concept:
[link or attachment]

Suggested Fix:
Sanitize inputs in parser and enforce safe evaluation rules.

```

---

## ⏱️ What to Expect

### Response Timeline

- **48 hours** → Initial acknowledgment
- **5 business days** → Validation decision
- **Every 5-7 days** → Status updates
- **Within 30 days** → Target resolution for critical vulnerabilities

### Our Process

1. Acknowledge receipt
2. Investigate & validate
3. Develop and test a fix
4. Coordinate disclosure with reporter
5. Publish a GitHub Security Advisory
6. Credit researcher (if desired)

---

## 📣 Security Advisory Process

When a vulnerability is fixed, we will:

- Publish a **GitHub Security Advisory**
- Release a **patched version**
- Update `CHANGELOG.md` with a `[SECURITY]` entry
- Announce the fix through GitHub Releases

Advisories are published at:
https://github.com/rahulkaushal04/depkeeper/security/advisories

---

## 🛡️ Scope of Security Reports

### In Scope

- Parser, resolver, updater logic
- Requirements file handling (malicious input)
- CLI command injection / unsafe shell execution
- Unsafe file operations or path traversal
- SSRF, MITM, insecure HTTP behavior
- Authentication issues with private indices
- Dependency chain vulnerabilities affecting depkeeper

### Out of Scope

- Vulnerabilities in **third-party dependencies**
- DoS requiring extreme resources
- Social engineering
- Physical access attacks
- Developer-only tooling issues
- Unsupported versions

---

## 🎖️ Researcher Recognition

While depkeeper currently has **no paid bug bounty program**, we do:

- Credit reporters in advisories
- Mention them in the changelog
- Add them to contributor acknowledgments
- Provide signed recommendation letters (if requested)

A bounty program may be introduced in the future.

---

## 🔒 Security Best Practices for depkeeper Users

### Safe Usage

- Always use the **latest version**
- Only run depkeeper on **trusted requirements files**
- Review suggested updates before applying
- Use **virtual environments**
- Avoid running as root unless necessary

### Example: Secure Configuration

```toml
# depkeeper.toml
[depkeeper]
verify_ssl = true
force_https = true
concurrent_requests = 10

[depkeeper.security]
check_security = true
fail_on_critical = true
require_hashes = false  # Recommended: true for maximum safety
```

### Private PyPI Indices

Use environment variables or credential managers:

```bash
export DEPKEEPER_PYPI_TOKEN=your_token_here
depkeeper update
```

Avoid hardcoding tokens or passwords.

---

## 🧰 Current Security Features

- ✔️ HTTPS-only communication
- ✔️ SSL certificate verification
- ✔️ Input validation & sanitization
- ✔️ Safe path handling
- ✔️ Atomic file writes & backups
- ✔️ Dry-run mode
- ✔️ Dependency hash verification support

### Planned

- 🔄 Vulnerability scanning
- 🔄 Lockfile w/ integrity
- 🔄 Package signature verification
- 🔄 SBOM generation
- 🔄 Suspicious update detection (supply-chain safety)

---

## 🔍 Known Security Considerations

### Requirements File Parsing

Mitigated by:

- The `packaging` library
- Avoidance of unsafe parsing operations
- Strict validation rules

### Network Requests

Mitigated by:

- HTTPS enforcement
- TLS verification
- Configurable indices
- Request throttling

### File System Access

Mitigated by:

- Path normalization
- Restricted write locations
- Automatic backup creation

---

## 📝 Vulnerability Disclosure Timeline

Typical flow:

| Day  | Action                           |
| ---- | -------------------------------- |
| 0    | Vulnerability privately reported |
| 1-5  | Triage & validation              |
| 5-30 | Fix development & testing        |
| ~30  | Public disclosure & advisory     |

Earlier disclosure may occur if:

- Active exploitation is observed
- Vulnerability is public elsewhere
- Issue is trivial to reproduce

---

## 📬 Contact & Reporting

- **Security concerns** → Use the repository’s **Security tab**
- **Private communication** → Start a private **GitHub Discussion**
- **Repository** → [https://github.com/rahulkaushal04/depkeeper](https://github.com/rahulkaushal04/depkeeper)

---

## 🙏 Acknowledgments

Thanks to all researchers who help keep depkeeper secure.
(Currently no reported vulnerabilities.)
