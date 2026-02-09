---
title: Best Practices
description: Recommended practices for using depkeeper effectively in Python projects
---

# Best Practices

This guide covers recommended practices for using depkeeper effectively in your Python projects.

---

## Dependency Management

### Pin Your Dependencies

Always pin exact versions in production:

```text
# Good -- predictable builds
requests==2.31.0
flask==3.0.0

# Avoid in production -- unpredictable
requests>=2.28.0
flask
```

### Use Semantic Version Constraints

For libraries and development, use flexible constraints:

```text
# Allow patch updates (bug fixes)
requests~=2.31.0   # >=2.31.0, <2.32.0

# Allow minor updates (features)
requests>=2.31.0,<3.0.0
```

### Separate Dependency Files

Organize dependencies by purpose:

```text
requirements.txt          # Core production dependencies
requirements-dev.txt      # Development tools (pytest, black)
requirements-docs.txt     # Documentation (mkdocs, sphinx)
requirements-test.txt     # Test-specific packages
```

---

## Update Workflow

### Regular Update Schedule

1. **Weekly** -- Check for updates with `depkeeper check`
2. **Monthly** -- Apply patch updates
3. **Quarterly** -- Evaluate minor/major updates

### Pre-Update Checklist

```bash
# 1. Ensure tests pass before updating
pytest

# 2. Check available updates
depkeeper check --outdated-only

# 3. Preview changes (dry run)
depkeeper update --dry-run

# 4. Apply updates with backup
depkeeper update --backup -y

# 5. Run tests again
pytest

# 6. Commit changes
git commit -am "chore: update dependencies"
```

### Handle Breaking Changes

For major version updates:

1. Read the changelog thoroughly
2. Update one package at a time
3. Test after each update
4. Document any migration steps

---

## Security

### Keep Dependencies Up to Date

Regular updates are your best defense against known vulnerabilities:

```bash
# Check for outdated packages weekly
depkeeper check --outdated-only

# Use pip-audit or safety alongside depkeeper for vulnerability scanning
pip-audit
```

### Address Vulnerabilities Promptly

- **Critical/High** -- Fix within 24-48 hours
- **Medium** -- Fix within 1 week
- **Low** -- Fix within 1 month

### Keep Dependencies Minimal

Fewer dependencies mean a smaller attack surface:

- Review unused packages periodically
- Prefer standard library when possible
- Choose well-maintained packages

---

## CI/CD Integration

### Fail Early

```yaml
# .github/workflows/deps.yml
- name: Check for outdated dependencies
  run: depkeeper check --outdated-only --format json
```

### Automated Updates

Use Dependabot or Renovate alongside depkeeper for automated PRs. depkeeper works well as the update engine within CI pipelines:

```bash
# Automated update with backup
depkeeper update --backup -y
```

### Pin Versions for Reproducibility

Use exact version pins in production and let depkeeper manage the update process:

```text
# requirements.txt -- pinned for reproducibility
requests==2.31.0
flask==3.0.0
click==8.1.7
```

---

## Code Review

### Dependency Change Reviews

When reviewing dependency updates:

1. Check the version diff (patch/minor/major)
2. Review the changelog
3. Verify security implications
4. Ensure tests pass

### PR Description Template

```markdown
## Dependency Updates

- `requests`: 2.28.0 → 2.31.0 (minor)
- `flask`: 2.3.0 → 2.3.3 (patch)

### Changelog Summary
- requests: Added retry improvements, fixed SSL issue
- flask: Security patch for XSS vulnerability

### Testing
- [x] Unit tests pass
- [x] Integration tests pass
- [x] Manual testing completed
```

---

## See Also

- [Troubleshooting](troubleshooting.md) -- Common issues and solutions
- [Configuration](configuration.md) -- Customize depkeeper behavior
- [CI/CD Integration](ci-cd-integration.md) -- Automate dependency management
