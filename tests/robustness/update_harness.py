"""Offline harness driving the real ``update`` CLI against a table of releases."""

from __future__ import annotations

import re
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from unittest import mock

from click.testing import CliRunner

from depkeeper.cli import cli
from depkeeper.models import Package

Table = Dict[str, str]  # normalised name -> recommended version

_PIN = re.compile(r"(?:==|>=|~=)\s*([0-9][^,;\s]*)")


class _HTTP:
    def __init__(self, *a: Any, **k: Any) -> None:
        pass

    async def __aenter__(self) -> "_HTTP":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _Store:
    def __init__(self, *a: Any, **k: Any) -> None:
        pass

    async def prefetch_packages(self, names: List[str]) -> None:
        return None


def _checker(table: Table) -> Any:
    class _Checker:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        @classmethod
        def from_config(cls, store: Any, cfg: Any, **kw: Any) -> "_Checker":
            return cls()

        async def check_packages(self, reqs: Any) -> List[Package]:
            out = []
            for r in reqs:
                key = r.name.lower().replace("_", "-").replace(".", "-")
                rec = table.get(key)
                m = _PIN.search(",".join(f"{o}{v}" for o, v in r.specs))
                out.append(
                    Package(
                        name=r.name,
                        current_version=m.group(1) if m else None,
                        latest_version=rec,
                        recommended_version=rec,
                    )
                )
            return out

    return _Checker


class _Analyzer:
    def __init__(self, *a: Any, **k: Any) -> None:
        pass

    async def resolve_and_annotate_conflicts(self, packages: Any) -> None:
        return None


def runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        return CliRunner()


def invoke(
    table: Table,
    args: Sequence[str],
    *,
    input: Optional[str] = None,
    cwd: Optional[Path] = None,
) -> Any:
    """Run ``depkeeper <args>`` with PyPI replaced by *table*."""
    with ExitStack() as st:
        for name, repl in (
            ("HTTPClient", _HTTP),
            ("PyPIDataStore", _Store),
            ("VersionChecker", _checker(table)),
            ("DependencyAnalyzer", _Analyzer),
        ):
            st.enter_context(mock.patch(f"depkeeper.commands.update.{name}", repl))
        return runner().invoke(cli, list(args), input=input, catch_exceptions=True)


def snapshot(root: Path) -> Dict[str, Tuple[bytes, int]]:
    """Return ``{relative path: (bytes, mode)}`` for every regular file."""
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mode & 0o7777)
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.is_symlink()
    }


def strays(root: Path) -> List[str]:
    """Names of leftover temporary files under *root*."""
    return [p.name for p in root.rglob("*.tmp")]
