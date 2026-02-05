# ==========================================================
# depkeeper — Development Makefile
# ==========================================================

# Auto-detect Python & venv
PYTHON ?= python3
PIP ?= $(PYTHON) -m pip

VENV ?= venv
ACTIVATE = . $(VENV)/bin/activate

# Colors
GREEN  := \033[0;32m
BLUE   := \033[0;34m
RESET  := \033[0m

# Default target
.DEFAULT_GOAL := help


# ==========================================================
# Help
# ==========================================================

.PHONY: help
help:
	@echo ""
	@echo "$(BLUE)depkeeper - Development Commands$(RESET)"
	@echo ""
	@echo "$(GREEN)Available targets:$(RESET)"
	@echo "  install          Install package in production mode"
	@echo "  install-dev      Install package with dev dependencies"
	@echo "  test             Run tests with coverage"
	@echo "  typecheck        Run mypy static type checks"
	@echo "  docs             Build mkdocs documentation"
	@echo "  clean            Remove cache and build artifacts"
	@echo "  all              Run typecheck and test"
	@echo ""


# ==========================================================
# Installation
# ==========================================================

.PHONY: install
install:
	$(PIP) install -e .
	@echo "$(GREEN)✓ Installed depkeeper (prod mode)$(RESET)"

.PHONY: install-dev
install-dev:
	$(PIP) install -e ".[dev]"
	pre-commit install
	@echo "$(GREEN)✓ Installed depkeeper (dev mode)$(RESET)"


# ==========================================================
# Code Quality
# ==========================================================

.PHONY: typecheck
typecheck:
	mypy depkeeper
	@echo "$(GREEN)✓ Type checking passed$(RESET)"


# ==========================================================
# Testing
# ==========================================================

.PHONY: test
test:
	pytest --cov=depkeeper \
	       --cov-report=term-missing \
	       --cov-report=html \
	       --cov-report=xml
	@echo "$(GREEN)✓ Tests ran successfully$(RESET)"


# ==========================================================
# Documentation
# ==========================================================

.PHONY: docs
docs:
	cd docs && mkdocs build
	@echo "$(GREEN)✓ Documentation built$(RESET)"


# ==========================================================
# Cleanup
# ==========================================================

.PHONY: clean
clean:
	rm -rf build/ dist/ *.egg-info
	rm -rf .pytest_cache/ .mypy_cache/
	rm -rf htmlcov/ .coverage coverage.xml
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	@echo "$(GREEN)✓ Clean completed$(RESET)"


# ==========================================================
# Run all quality checks
# ==========================================================

.PHONY: all
all: typecheck test
	@echo "$(GREEN)✓ All checks passed successfully!$(RESET)"
