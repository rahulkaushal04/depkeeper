---
title: Exit Codes
description: depkeeper exit code reference for scripting and CI/CD
---

# Exit Codes

depkeeper uses meaningful exit codes for scripting and CI/CD integration. This page documents each exit code, its meaning, and how to handle it in automation scripts.

---

## Exit Code Reference

| Code | Name | Description |
|---|---|---|
| `0` | Success | Command completed successfully |
| `1` | Error | Application or runtime error |
| `2` | Usage Error | Invalid arguments or options |
| `130` | Interrupted | User cancelled (Ctrl+C) |

---

## Detailed Descriptions

### Exit Code 0: Success

The command completed without errors.

- **check** -- Requirements file was parsed and analyzed
- **update** -- Updates were applied successfully, or no updates were needed

!!! note
    The `check` command returns 0 even if outdated packages are found. The exit code indicates command success, not whether updates are available.

### Exit Code 1: Error

An application error occurred. Common causes:

- Requirements file not found
- Parse error in requirements file
- Network error (PyPI unreachable)
- File write error (during update)
- Invalid configuration

### Exit Code 2: Usage Error

Invalid command-line arguments were provided. Common causes:

- Unknown option
- Missing required argument
- Invalid option value

### Exit Code 130: Interrupted

The user cancelled the operation with Ctrl+C. This occurs when:

- The user presses Ctrl+C during an update confirmation prompt
- The user interrupts a long-running network operation

---

## Exit Code Behavior by Command

### check

| Scenario | Exit Code |
|---|---|
| All packages up to date | 0 |
| Outdated packages found | 0 |
| Parse error | 1 |
| Network error | 1 |
| Invalid arguments | 2 |
| Interrupted | 130 |

### update

| Scenario | Exit Code |
|---|---|
| Updates applied successfully | 0 |
| No updates needed | 0 |
| User declined updates | 0 |
| Parse error | 1 |
| Write error | 1 |
| Network error | 1 |
| Invalid arguments | 2 |
| Interrupted | 130 |

---

## Usage in Scripts

### Basic Error Handling (Bash)

```bash
#!/bin/bash
set -e

depkeeper check || {
    echo "depkeeper check failed"
    exit 1
}
```

### Detailed Exit Code Handling (Bash)

```bash
#!/bin/bash

depkeeper check
EXIT_CODE=$?

case $EXIT_CODE in
    0)
        echo "Check completed successfully"
        ;;
    1)
        echo "Error during check"
        exit 1
        ;;
    2)
        echo "Invalid arguments"
        exit 2
        ;;
    130)
        echo "Operation cancelled"
        exit 130
        ;;
    *)
        echo "Unknown exit code: $EXIT_CODE"
        exit $EXIT_CODE
        ;;
esac
```

### PowerShell

```powershell
depkeeper check
if ($LASTEXITCODE -eq 0) {
    Write-Host "Check completed successfully"
} else {
    Write-Host "Check failed with code: $LASTEXITCODE"
    exit $LASTEXITCODE
}
```

### CI/CD Pipeline

```bash
#!/bin/bash
set -e

# Check for updates (exit 0 even with outdated)
depkeeper check --format json > report.json

# Determine if updates exist
OUTDATED=$(jq '[.[] | select(.status == "outdated")] | length' report.json)

if [ "$OUTDATED" -gt 0 ]; then
    echo "Found $OUTDATED outdated packages"

    # Update with backup
    depkeeper update --backup -y || {
        echo "Update failed"
        exit 1
    }

    # Run tests
    pytest || {
        echo "Tests failed after update"
        exit 1
    }
fi
```

### GitHub Actions

```yaml
- name: Check dependencies
  id: check
  run: |
    depkeeper check --format json > report.json
  continue-on-error: true

- name: Handle check result
  if: steps.check.outcome == 'failure'
  run: |
    echo "::error::Dependency check failed"
    exit 1
```

---

## Strict Mode Pattern

For CI/CD where you want to fail if packages are outdated:

```bash
#!/bin/bash
set -e

# Check if any packages are outdated
OUTDATED=$(depkeeper check --outdated-only --format json | jq 'length')

if [ "$OUTDATED" -gt 0 ]; then
    echo "$OUTDATED packages are outdated"
    depkeeper check --outdated-only
    exit 1
fi

echo "All packages are up to date"
```

---

## See Also

- [CLI Commands](cli-commands.md) -- Command documentation
- [CI/CD Integration](../guides/ci-cd-integration.md) -- Pipeline examples
