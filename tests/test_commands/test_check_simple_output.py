"""Regression tests for simple-format rendering in ``check`` command."""

from __future__ import annotations

import io

from rich.console import Console

from depkeeper.commands.check import _display_simple
from depkeeper.models import Conflict, Package


def _capture_simple_output(packages: list[Package]) -> str:
    """Render simple output into an in-memory buffer and return it."""
    buffer = io.StringIO()
    console = Console(file=buffer, no_color=True, highlight=False)

    # Patch the module-level accessor imported by depkeeper.commands.check.
    from depkeeper.commands import check as check_module

    original_get_console = check_module.get_raw_console
    check_module.get_raw_console = lambda: console
    try:
        _display_simple(packages)
    finally:
        check_module.get_raw_console = original_get_console

    return buffer.getvalue()


def test_display_simple_preserves_status_labels_verbatim() -> None:
    """M4 regression: status labels must not be swallowed by Rich markup."""
    packages = [
        Package(name="pkg-no-update", current_version="1.0.0"),
        Package(name="pkg-install", latest_version="2.0.0", recommended_version="2.0.0"),
        Package(
            name="pkg-downgrade",
            current_version="3.0.0",
            latest_version="4.0.0",
            recommended_version="2.9.0",
        ),
        Package(
            name="pkg-outdated",
            current_version="1.0.0",
            latest_version="2.0.0",
            recommended_version="2.0.0",
        ),
        Package(
            name="pkg-latest",
            current_version="2.0.0",
            latest_version="2.0.0",
            recommended_version="2.0.0",
        ),
    ]

    output = _capture_simple_output(packages)

    assert "[NO-UPDATE]" in output
    assert "[INSTALL]" in output
    assert "[DOWNGRADE]" in output
    assert "[OUTDATED]" in output
    assert "[LATEST]" in output


def test_display_simple_disables_markup_for_conflict_lines() -> None:
    """Conflict details containing bracketed text should remain literal."""
    pkg = Package(
        name="target",
        current_version="1.0.0",
        latest_version="1.1.0",
        recommended_version="1.1.0",
        conflicts=[
            Conflict(
                source_package="builder[src]",
                source_version="2.0.0",
                target_package="target",
                required_spec=">=2.0.0",
                conflicting_version="1.1.0",
            )
        ],
    )

    output = _capture_simple_output([pkg])

    assert "builder[src]==2.0.0 requires target>=2.0.0" in output
