#!/usr/bin/env bash

# ================================================================
# depkeeper Development Environment Setup Script
# ================================================================
# This script sets up a complete development environment for depkeeper.
# It creates a virtual environment, installs dev dependencies,
# installs pre-commit hooks, and verifies the installation.
# ================================================================

set -e  # Exit immediately on error


# ================================================================
# Colors & Pretty Printing
# ================================================================
GREEN="\033[0;32m"
BLUE="\033[0;34m"
RED="\033[0;31m"
YELLOW="\033[1;33m"
NC="\033[0m" # Reset

info()    { echo -e "${BLUE}ℹ $1${NC}"; }
success() { echo -e "${GREEN}✓ $1${NC}"; }
warn()    { echo -e "${YELLOW}! $1${NC}"; }
error()   { echo -e "${RED}✗ $1${NC}" >&2; }


# ================================================================
# Header
# ================================================================
echo ""
echo -e "${BLUE}=========================================="
echo "depkeeper — Development Setup"
echo -e "==========================================${NC}"
echo ""


# ================================================================
# Detect usable Python executable
# ================================================================
info "Detecting Python..."

if command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON="python"
else
    error "Python 3.8+ not found. Please install Python."
    exit 1
fi

PY_VERSION="$($PYTHON -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"

# Compare versions safely
required="3.8"
if [[ "$(printf '%s\n' "$required" "$PY_VERSION" | sort -V | head -n1)" != "$required" ]]; then
    error "Python >= 3.8 required (found $PY_VERSION)"
    exit 1
fi

success "Using Python $PY_VERSION"


# ================================================================
# Virtual environment
# ================================================================
info "Creating virtual environment..."

if [[ ! -d venv ]]; then
    $PYTHON -m venv venv
    success "Virtual environment created"
else
    warn "Virtual environment already exists"
fi


# ================================================================
# Activate the environment
# ================================================================
info "Activating virtual environment..."

# shellcheck source=/dev/null
if ! source venv/bin/activate 2>/dev/null; then
    # Windows Git Bash fallback
    if ! source venv/Scripts/activate 2>/dev/null; then
        error "Failed to activate virtual environment"
        exit 1
    fi
fi

success "Virtual environment activated"


# ================================================================
# Upgrade pip & tooling
# ================================================================
info "Upgrading pip, setuptools, wheel..."
pip install --upgrade pip setuptools wheel --quiet
success "Toolchain upgraded"


# ================================================================
# Install depkeeper in dev mode
# ================================================================
info "Installing depkeeper (editable mode) with dev dependencies..."
pip install -e ".[dev]" --quiet
success "depkeeper installed"


# ================================================================
# Pre-commit hooks
# ================================================================
info "Installing pre-commit hooks..."
pre-commit install --hook-type pre-commit --hook-type commit-msg
success "Pre-commit hooks installed"


# ================================================================
# Run initial tests
# ================================================================
info "Running initial tests..."

if pytest -q --disable-warnings 2>/dev/null; then
    success "Initial tests passed"
else
    warn "No tests found or some tests failed (expected in early development phases)"
fi


# ================================================================
# Finish
# ================================================================
echo ""
echo -e "${GREEN}=========================================="
echo "Development environment setup complete!"
echo -e "==========================================${NC}"
echo ""

cat <<EOF
Next steps:

1. Activate the virtual environment:
   • macOS/Linux:  source venv/bin/activate
   • Windows:      venv\\Scripts\\activate

2. Useful commands:
   • make test        — Run tests
   • make typecheck   — Mypy type checking
   • make all         — Run all quality checks

3. Try depkeeper:
   • python -m depkeeper
   • depkeeper --help

Happy coding! 🎉
EOF

success "Setup completed successfully!"
