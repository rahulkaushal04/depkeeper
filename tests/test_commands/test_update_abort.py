"""Ctrl-D or Ctrl-C at the confirmation prompt is an abort, not an unexpected error."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import click

from depkeeper.cli import cli
from depkeeper.models import Package
from tests.test_commands.test_check_output_streams import (
    _FakeDataStore,
    _FakeHTTPClient,
    _fake_analyzer,
    _fake_checker,
    _isolated_console,  # noqa: F401  (autouse fixture)
    _make_runner,
)


def _raise_abort(count: int) -> bool:
    raise click.Abort()


def test_abort_at_prompt_reaches_the_top_level_handler(tmp_path: Path) -> None:
    req = tmp_path / "requirements.txt"
    req.write_bytes(b"a==1.0.0\n")
    pkg = Package(
        name="a",
        current_version="1.0.0",
        latest_version="1.0.1",
        recommended_version="1.0.1",
    )
    with ExitStack() as stack:
        stack.enter_context(
            mock.patch("depkeeper.commands.update.HTTPClient", _FakeHTTPClient)
        )
        stack.enter_context(
            mock.patch("depkeeper.commands.update.PyPIDataStore", _FakeDataStore)
        )
        stack.enter_context(
            mock.patch("depkeeper.commands.update.VersionChecker", _fake_checker([pkg]))
        )
        stack.enter_context(
            mock.patch(
                "depkeeper.commands.update.DependencyAnalyzer", _fake_analyzer(None)
            )
        )
        stack.enter_context(
            mock.patch("depkeeper.commands.update._confirm_update", _raise_abort)
        )
        result = _make_runner().invoke(cli, ["update", str(req)], standalone_mode=False)

    assert isinstance(result.exception, click.Abort), result.output
    assert "Unexpected error" not in result.output + (result.stderr or "")
    assert req.read_bytes() == b"a==1.0.0\n"
