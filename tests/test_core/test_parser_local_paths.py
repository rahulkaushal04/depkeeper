"""Local path requirements get an absolute ``file://`` URL even if the path is missing."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest import mock

from depkeeper.core.parser import RequirementsParser


def _unresolved(self: Path, strict: bool = False) -> Path:
    """Model ``Path.resolve`` on Windows with Python < 3.10: a missing path stays relative."""
    return self


def test_missing_relative_path_still_gets_an_absolute_file_url(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    parser = RequirementsParser()
    with mock.patch.object(Path, "resolve", _unresolved):
        (req,) = parser.parse_string("./does-not-exist-yet\n")
    assert req.url is not None and req.url.startswith("file:///")
    assert req.url.endswith("does-not-exist-yet")
