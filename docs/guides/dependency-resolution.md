---
title: Dependency Resolution
description: Understanding how depkeeper detects and resolves conflicts
---

# Dependency Resolution

depkeeper automatically detects and resolves dependency conflicts to ensure your environment stays working.

---

## What Are Dependency Conflicts?

A **dependency conflict** occurs when two packages require incompatible versions of the same dependency.

### Example

```text
# Your requirements.txt
requests==2.31.0
boto3==1.34.0
```

Both packages depend on `urllib3`:

- `requests` requires `urllib3>=1.21.1,<3`
- `boto3` (via `botocore`) requires `urllib3>=1.25.4,!=2.2.0,<3`

These are compatible. But consider:

```text
package-a requires foo>=2.0.0
package-b requires foo<2.0.0
```

This is a **conflict** -- no version of `foo` satisfies both requirements.

---

## How depkeeper Resolves Conflicts

### Resolution Algorithm

1. **Fetch Metadata**: Download dependency information from PyPI
2. **Build Graph**: Create a dependency graph of all packages
3. **Identify Conflicts**: Find version incompatibilities
4. **Adjust Recommendations**: Use downgrading or constraining to resolve

### Resolution Strategies

| Status | Meaning |
|---|---|
| `KEPT_RECOMMENDED` | Original recommendation was conflict-free |
| `UPGRADED` | Successfully upgraded to a newer version |
| `DOWNGRADED` | Had to use an older version due to conflicts |
| `CONSTRAINED` | Version was limited by another package |
| `KEPT_CURRENT` | No safe upgrade found; stayed at current |

---

## Viewing Conflict Information

### In Check Output

```bash
depkeeper check
```

```
Package       Current    Recommended  Status
───────────────────────────────────────────────
requests      2.28.0     2.31.0       Outdated (minor)
urllib3       1.26.0     1.26.18      Constrained

⚠ Dependency Constraints:
  urllib3 constrained by:
    - requests (requires urllib3>=1.21.1,<2)
```

### In JSON Output

```bash
depkeeper check --format json
```

```json
{
  "name": "urllib3",
  "current_version": "1.26.0",
  "recommended_version": "1.26.18",
  "has_conflicts": false,
  "conflicts": [],
  "constrained_by": ["requests"]
}
```

---

## Major Version Boundaries

depkeeper enforces **strict major version boundaries** during resolution.

### Why?

Major versions often include:

- Breaking API changes
- Removed functionality
- Incompatible dependencies

### How It Works

```text
Package       Current    Latest     Recommended
─────────────────────────────────────────────
flask         2.0.0      3.0.1      2.3.3
```

Even though `flask 3.0.1` is available, depkeeper recommends `2.3.3` because:

1. Your current version is `2.0.0` (major version 2)
2. Latest in major version 2 is `2.3.3`
3. `3.0.1` would cross the major version boundary

### Intentional Major Upgrades

When you're ready for a major upgrade:

1. Update your requirements file manually:
   ```text
   flask>=3.0.0
   ```

2. Run depkeeper to resolve dependencies:
   ```bash
   depkeeper update
   ```

3. Test thoroughly

---

## Conflict Scenarios

### Scenario 1: Transitive Conflict

```text
# Your requirements
requests==2.31.0
some-package==1.0.0  # requires urllib3>=2.0.0
```

`requests` requires `urllib3<3` but works with 2.x. `some-package` requires `urllib3>=2.0.0`.

**Resolution**: Update `urllib3` to `2.x` to satisfy both.

### Scenario 2: Irreconcilable Conflict

```text
package-a requires foo>=2.0.0,<3.0.0
package-b requires foo>=3.0.0
```

No version of `foo` can satisfy both.

**Resolution**: depkeeper reports the conflict and keeps the current version or suggests alternatives.

### Scenario 3: Diamond Dependency

```
    A
   / \
  B   C
   \ /
    D (different versions required)
```

`A` depends on `B` and `C`, which both depend on `D` but require different versions.

**Resolution**: depkeeper finds a version of `D` that satisfies both or reports if impossible.

---

## Controlling Conflict Resolution

### Enable/Disable

```bash
# Enabled by default
depkeeper check --check-conflicts
depkeeper update --check-conflicts

# Disable for faster but potentially unsafe checks
depkeeper check --no-check-conflicts
depkeeper update --no-check-conflicts
```

### When to Disable

- Quick status checks
- When you know your environment is compatible
- Performance-critical CI pipelines (but use carefully)

!!! danger "Warning"
    Disabling conflict checking may result in recommendations that break your environment.

---

## Resolution Details

### Verbose Output

For detailed resolution information:

```bash
depkeeper -vv check
```

```
DEBUG: Fetching metadata for requests...
DEBUG: Fetching metadata for urllib3...
DEBUG: Building dependency graph...
DEBUG: Checking constraints for urllib3:
  - requests requires: urllib3>=1.21.1,<3
DEBUG: Finding compatible version for urllib3 within 1.x...
DEBUG: Selected urllib3==1.26.18 (satisfies all constraints)
```

### Resolution Result

In JSON output, each package includes resolution details:

```json
{
  "name": "urllib3",
  "resolution_status": "CONSTRAINED",
  "resolution_reason": "Version constrained by requests dependency",
  "constraints": [
    {
      "package": "requests",
      "specifier": ">=1.21.1,<3"
    }
  ]
}
```

---

## Troubleshooting

### "No compatible version found"

This means no version satisfies all constraints.

**Solutions:**

1. Check if packages are compatible at all
2. Consider updating one package manually
3. Look for alternative packages

### "Circular dependency detected"

Packages depend on each other in a cycle.

**Solutions:**

1. This is usually handled automatically
2. If issues persist, check package documentation

### Resolution takes too long

**Solutions:**

1. Use `--no-check-conflicts` for quick checks
2. Reduce the number of packages being checked
3. Check network connectivity (PyPI fetches)

---

## Best Practices

!!! tip "Pin Direct Dependencies"
    Pin your direct dependencies to specific versions. Let depkeeper handle the resolution.

!!! tip "Regular Updates"
    Update frequently to avoid large version jumps that create conflicts.

!!! tip "Test After Updates"
    Always run your test suite after updates to catch compatibility issues.

!!! tip "Review Constraints"
    When a package is constrained, review if the constraining package can be updated first.

---

## Next Steps

- [CI/CD Integration](ci-cd-integration.md) -- Automate dependency management
- [CLI Reference](../reference/cli-commands.md) -- Complete command documentation
- [Configuration](configuration.md) -- Customize behavior
