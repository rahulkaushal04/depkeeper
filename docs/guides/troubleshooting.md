---
title: Troubleshooting
description: Common issues and solutions when using depkeeper
---

# Troubleshooting

Common issues and their solutions when using depkeeper.

---

## Installation Issues

### pip install fails

**Error**: `Could not find a version that satisfies the requirement`

**Solution**:
```bash
# Upgrade pip first
pip install --upgrade pip

# Try installing again
pip install depkeeper
```

### Command not found

**Error**: `depkeeper: command not found`

**Solution**:
```bash
# Ensure pip scripts are in PATH
# For Unix/macOS:
export PATH="$HOME/.local/bin:$PATH"

# For Windows (PowerShell):
$env:PATH += ";$env:APPDATA\Python\Scripts"

# Or run as a module:
python -m depkeeper --help
```

---

## Parsing Errors

### Invalid requirements file

**Error**: `ParseError: Invalid requirement at line X`

**Common causes:**

- Missing version specifier
- Invalid characters in package name
- Malformed URL

**Solution**:
```bash
# Validate your requirements file
pip install -r requirements.txt --dry-run

# Fix the problematic line and try again
```

### Encoding issues

**Error**: `UnicodeDecodeError: 'utf-8' codec can't decode`

**Solution**:
```bash
# Convert file to UTF-8
# On Unix/macOS:
iconv -f ISO-8859-1 -t UTF-8 requirements.txt > requirements_utf8.txt

# On Windows (PowerShell):
Get-Content requirements.txt | Set-Content -Encoding UTF8 requirements_utf8.txt
```

---

## Network Issues

### Connection timeout

**Error**: `ConnectionError: Connection to pypi.org timed out`

**Solutions**:
```bash
# Configure timeout via depkeeper.toml
# [depkeeper.pypi]
# timeout = 60

# Use a mirror via configuration file
# [depkeeper.pypi]
# index_url = "https://pypi.tuna.tsinghua.edu.cn/simple"

# Check network connectivity
ping pypi.org
```

### SSL certificate errors

**Error**: `SSLError: certificate verify failed`

**Solutions**:
```bash
# Update certificates
pip install --upgrade certifi

# For corporate proxies, configure CA bundle
export REQUESTS_CA_BUNDLE=/path/to/ca-bundle.crt
```

### Behind a proxy

**Solution**:
```bash
# Set proxy environment variables
export HTTP_PROXY=http://proxy.example.com:8080
export HTTPS_PROXY=http://proxy.example.com:8080

# Or configure in pip
pip config set global.proxy http://proxy.example.com:8080
```

---

## Dependency Resolution

### Conflict detected

**Error**: `ConflictError: package-a requires package-b<2.0, but package-c requires package-b>=2.0`

**Solutions:**

1. **Check current state**:
```bash
depkeeper check --format json
pip list
```

2. **Find the conflict source**:
```bash
pip show package-a package-c
```

3. **Try updating related packages**:
```bash
depkeeper update -p package-a -p package-c
```

4. **Use constraints**:
```text
# Add constraint to requirements.txt
package-b>=1.5,<2.0  # Find common version
```

5. **As last resort, pin the conflicting package**:
```text
# requirements.txt
package-b==1.9.0  # Known working version
```

### Circular dependencies

**Warning**: `Circular dependency detected: A -> B -> A`

**Solution**:
This is usually not an issue, but if causing problems:

```bash
# Install in specific order
pip install package-b
pip install package-a
```

---

## Update Issues

### Update fails with rollback

**Error**: `UpdateError: Failed to update requirements, changes rolled back`

**Common causes:**

- Write permission denied
- File locked by another process
- Disk full

**Solutions**:
```bash
# Check file permissions
ls -la requirements.txt

# Close editors that might lock the file
# Try with elevated permissions if needed
sudo depkeeper update
```

### Pre-release versions appearing

**Issue**: Unwanted alpha/beta versions suggested

depkeeper excludes pre-releases by default. To explicitly configure this, add the following to your configuration file:

```toml
# depkeeper.toml
[depkeeper.filters]
include_pre_release = false
```

---

## Output Issues

### Garbled output / No colors

**Issue**: Terminal output appears broken

**Solutions**:
```bash
# Force no colors
depkeeper --no-color check

# Or set environment variable
export DEPKEEPER_COLOR=false
```

### JSON output invalid

**Issue**: JSON output mixed with status messages

**Solution**:
```bash
# Redirect stderr to get clean JSON output
depkeeper check --format json 2>/dev/null
```

---

## Cache Issues

### Stale data

**Issue**: depkeeper showing old versions

**Solution**:
```bash
# Remove cache directory manually
# Unix/macOS:
rm -rf ~/.cache/depkeeper

# Windows (PowerShell):
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\depkeeper\cache"

# Or set a custom cache directory
export DEPKEEPER_CACHE_DIR=/tmp/depkeeper-cache
```

### Cache corruption

**Error**: `CacheError: Failed to read cache`

**Solution**:
```bash
# Remove cache directory
# Unix/macOS:
rm -rf ~/.cache/depkeeper

# Windows:
rmdir /s /q %LOCALAPPDATA%\depkeeper\cache
```

---

## Getting Help

If you're still having issues:

1. **Check the version**:
```bash
depkeeper --version
```

2. **Run with verbose output**:
```bash
depkeeper -vv check
```

3. **Search existing issues**:
   [GitHub Issues](https://github.com/rahulkaushal04/depkeeper/issues)

4. **Report a bug** -- include:
   - depkeeper version
   - Python version (`python --version`)
   - Operating system
   - Full error message with verbose output
   - Minimal requirements.txt to reproduce

```bash
# Gather system info
depkeeper --version
python --version
pip --version
uname -a  # or systeminfo on Windows
```

---

## See Also

- [Installation](../getting-started/installation.md) -- Installation troubleshooting
- [Configuration](configuration.md) -- Configure depkeeper behavior
- [CLI Reference](../reference/cli-commands.md) -- Complete command documentation
