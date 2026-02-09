---
title: Security Policy
description: How to report security vulnerabilities in depkeeper and what to expect
---

# Security Policy

We take the security of depkeeper seriously. This page explains how to report vulnerabilities, what our response process looks like, and what security features depkeeper provides.

---

## Supported Versions

We provide security patches only for the latest release series.

| Version | Supported |
|---|---|
| 0.1.x | Yes |
| < 0.1 | No |

As depkeeper is in early development, we strongly recommend upgrading to the latest release at all times.

---

## Reporting a Vulnerability

**Do not create public GitHub issues for security vulnerabilities.**

To responsibly disclose a vulnerability, use one of the following private channels:

- The repository's **Security** tab -- [Report a vulnerability](https://github.com/rahulkaushal04/depkeeper/security/advisories/new)
- A **private GitHub Discussion** with the maintainers

We appreciate coordinated disclosure and will work with you to verify, fix, and publicly disclose issues responsibly.

### What to Include in Your Report

1. **Description** -- Clear explanation of the issue
2. **Impact** -- What an attacker could achieve
3. **Affected Versions** -- Specific versions you tested against
4. **Reproduction Steps** -- Required for us to verify the issue
5. **Proof of Concept** -- If available
6. **Potential Fix** -- If you have thoughts or patches

---

## Response Timeline

After you submit a report, here is what to expect:

| Timeframe | Action |
|---|---|
| 48 hours | Initial acknowledgment |
| 5 business days | Validation decision |
| Every 5-7 days | Status updates |
| Within 30 days | Target resolution for critical vulnerabilities |

---

## Security Advisory Process

When a vulnerability is fixed, we will:

- Publish a **GitHub Security Advisory**
- Release a **patched version**
- Update the [Changelog](changelog.md) with a security entry
- Announce the fix through GitHub Releases

Published advisories are available at [github.com/rahulkaushal04/depkeeper/security/advisories](https://github.com/rahulkaushal04/depkeeper/security/advisories).

---

## Scope

### In Scope

The following areas are within the scope of security reports:

- Parser, resolver, and updater logic
- Requirements file handling (malicious input)
- CLI command injection or unsafe shell execution
- Unsafe file operations or path traversal
- SSRF, MITM, or insecure HTTP behavior
- Authentication issues with private PyPI indices
- Dependency chain vulnerabilities affecting depkeeper itself

### Out of Scope

The following are outside the scope of security reports:

- Vulnerabilities in third-party dependencies (report to those projects directly)
- Denial of service requiring extreme resources
- Social engineering attacks
- Physical access attacks
- Issues in unsupported versions

---

## Current Security Features

depkeeper includes the following security measures:

- HTTPS-only communication with PyPI
- SSL certificate verification
- Input validation and sanitization in the requirements parser
- Safe path handling to prevent directory traversal
- Atomic file writes with backup support
- Dry-run mode for previewing changes before applying

### Planned Security Features

The following features are planned for future releases:

- Vulnerability scanning against known advisory databases
- Lock file generation with integrity verification
- Package signature verification
- SBOM (Software Bill of Materials) generation

---

## Best Practices for Users

For safe day-to-day usage of depkeeper:

- Always use the **latest version** of depkeeper
- Only run depkeeper on **trusted requirements files**
- Preview changes with `--dry-run` before applying updates
- Use the `--backup` flag to create backups before updating

---

## Researcher Recognition

While depkeeper does not currently have a paid bug bounty program, we recognize security researchers by:

- Crediting reporters in security advisories
- Mentioning them in the changelog
- Adding them to contributor acknowledgments
