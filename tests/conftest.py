"""
Shared pytest fixtures and configuration for the depkeeper test suite.

Fixtures defined here are automatically discovered by pytest and made available
to *all* tests across the project, without explicit imports.

These fixtures provide:
  • Standardized temporary directory handling
  • Access to the repository root
  • Preconfigured test file locations
  • A reliable foundation for file-system-heavy tests (parser, updater, lockfile, etc.)
"""

from __future__ import annotations

import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# File system fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """
    Provide an isolated temporary directory for tests.

    This wraps pytest's built-in `tmp_path` to give depkeeper a uniform
    naming convention across all internal tests. All files created inside
    this directory are automatically cleaned up after each test.

    Returns:
        Path: A temporary directory unique to the current test.
    """
    return tmp_path
