"""Adapter registry and file discovery."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union

from depkeeper.exceptions import DepKeeperError, ParseError
from depkeeper.models import Requirement
from depkeeper.core.sources.base import SourceAdapter
from depkeeper.core.sources.requirements_txt import RequirementsTxtAdapter
from depkeeper.core.sources.pyproject_toml import PyprojectTomlAdapter
from depkeeper.core.sources.conda_yaml import CondaYamlAdapter

_ADAPTERS: List[SourceAdapter] = []

DEFAULT_FILE = "requirements.txt"


def register(adapter: SourceAdapter) -> None:
    """Add *adapter*; earlier registrations win in matching and discovery."""
    _ADAPTERS.append(adapter)


def get_adapter(path: Union[str, Path]) -> SourceAdapter:
    """Return the adapter for *path* (the fallback adapter if none claims it)."""
    p = Path(path)
    for a in _ADAPTERS:
        if not a.fallback and a.can_handle(p):
            return a
    for a in _ADAPTERS:
        if a.fallback:  # unknown file names are read as requirements
            return a
    raise DepKeeperError(f"Unsupported dependency file: {p}")


def discover(directory: Union[str, Path]) -> List[Path]:
    """Return supported dependency files in *directory*, in adapter order."""
    root = Path(directory)
    found: List[Path] = []
    for a in _ADAPTERS:
        for pattern in a.patterns:
            for p in sorted(root.glob(pattern)):
                if (
                    p.is_file()
                    and p not in found
                    and a.can_handle(p)
                    and a.has_dependencies(p)
                ):
                    found.append(p)
    return found


def default_target(file: Optional[Path]) -> Path:
    """Resolve the optional FILE argument.

    Without one, ``requirements.txt`` is used when present, otherwise the
    current directory (discovery).
    """
    if file is not None:
        return file
    default = Path(DEFAULT_FILE)
    if default.exists() or not discover("."):
        return default
    return Path(".")


def resolve_targets(path: Path) -> List[Path]:
    """Expand *path* (file or directory) to the files to process."""
    if not path.is_dir():
        return [path]
    files = discover(path)
    if not files:
        raise DepKeeperError(f"No supported dependency files found in {path}")
    return files


def parse_targets(path: Path) -> List[Requirement]:
    """Parse *path* (file or directory) into one combined requirement list."""
    reqs: List[Requirement] = []
    for f in resolve_targets(path):
        adapter = get_adapter(f)
        try:
            parsed = adapter.parse(f)
        except ParseError as e:
            raise DepKeeperError(f"Failed to parse {f}: {e}") from e
        for r in parsed:
            if r.source_file is None:
                r.source_file = str(f.resolve())
            r.source_format = r.source_format or adapter.name
        reqs.extend(parsed)
    return reqs


def _register_builtins() -> None:
    register(RequirementsTxtAdapter())
    register(PyprojectTomlAdapter())
    register(CondaYamlAdapter())


_register_builtins()
