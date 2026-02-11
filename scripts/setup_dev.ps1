# ================================================================
# depkeeper Development Environment Setup Script (Windows)
# ================================================================
# This script sets up a complete development environment for depkeeper.
# It creates a virtual environment, installs dev dependencies,
# installs pre-commit hooks, and verifies the installation.
#
# Usage: .\setup_dev.ps1
# Note:  You may need to run first (once, as admin):
#        Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
# ================================================================

$ErrorActionPreference = "Stop"


# ================================================================
# Navigate to project root
# ================================================================
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$PROJECT_ROOT = Split-Path -Parent $SCRIPT_DIR

Push-Location $PROJECT_ROOT


# ================================================================
# Colors & Pretty Printing
# ================================================================
function Info    { param($msg) Write-Host "i $msg" -ForegroundColor Cyan }
function Success { param($msg) Write-Host "v $msg" -ForegroundColor Green }
function Warn    { param($msg) Write-Host "! $msg" -ForegroundColor Yellow }
function Err     { param($msg) Write-Host "x $msg" -ForegroundColor Red }


# ================================================================
# Header
# ================================================================
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "depkeeper - Development Setup"            -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""


# ================================================================
# Detect usable Python executable
# ================================================================
Info "Detecting Python..."

$PYTHON = $null

foreach ($candidate in @("python", "python3")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $PYTHON = $candidate
        break
    }
}

if (-not $PYTHON) {
    Err "Python 3.8+ not found. Please install Python from https://python.org"
    exit 1
}

$PY_VERSION = & $PYTHON --version 2>&1 | ForEach-Object { $_ -replace 'Python ', '' }

$parts = $PY_VERSION -split '\.'
$major = [int]$parts[0]
$minor = [int]$parts[1]

if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 8)) {
    $msg = "Python >= 3.8 required (found $PY_VERSION)"
    Err $msg
    exit 1
}

Success "Using Python $PY_VERSION"


# ================================================================
# Virtual environment
# ================================================================
Info "Creating virtual environment..."

if (-not (Test-Path ".venv")) {
    & $PYTHON -m venv .venv
    Success "Virtual environment created"
} else {
    Warn "Virtual environment already exists - skipping creation"
}


# ================================================================
# Activate the environment
# ================================================================
Info "Activating virtual environment..."

$activateScript = ".venv\Scripts\Activate.ps1"

if (-not (Test-Path $activateScript)) {
    Err "Activation script not found: $activateScript"
    exit 1
}

& $activateScript
Success "Virtual environment activated"


# ================================================================
# Upgrade pip & tooling
# ================================================================
Info "Upgrading pip, setuptools, wheel..."
pip install --upgrade pip setuptools wheel --quiet
Success "Toolchain upgraded"


# ================================================================
# Install depkeeper in dev mode
# ================================================================
Info "Installing depkeeper (editable mode) with dev dependencies..."
pip install -e '.[dev]' --quiet
Success "depkeeper installed"


# ================================================================
# Pre-commit hooks
# ================================================================
Info "Installing pre-commit hooks..."
pre-commit install --hook-type pre-commit --hook-type commit-msg
Success "Pre-commit hooks installed"


# ================================================================
# Run initial tests
# ================================================================
Info "Running initial tests..."

pytest -q --disable-warnings 2>$null
if ($LASTEXITCODE -eq 0) {
    Success "Initial tests passed"
} else {
    Warn "No tests found or some tests failed (expected in early development phases)"
}


# ================================================================
# Finish
# ================================================================
Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "Development environment setup complete!"   -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""

Write-Host @"
Next steps:

1. Activate the virtual environment:
   > .venv\Scripts\Activate.ps1

   If you get an execution policy error, run once as admin:
   > Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

2. Useful commands:
   > make test        -- Run tests
   > make typecheck   -- Mypy type checking
   > make all         -- Run all quality checks

3. Try depkeeper:
   > python -m depkeeper
   > depkeeper --help

Happy coding!
"@

Success "Setup completed successfully!"

Pop-Location
