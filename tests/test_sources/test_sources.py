"""Source adapter layer: registry, discovery, requirements.txt adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Sequence

import pytest

from depkeeper.exceptions import DepKeeperError
from depkeeper.core.parser import RequirementsParser
from depkeeper.core.sources import (
    SourceAdapter,
    SourceUpdate,
    default_target,
    discover,
    get_adapter,
    parse_targets,
    resolve_targets,
)
from depkeeper.core.sources import registry
from depkeeper.core.sources.requirements_txt import RequirementsTxtAdapter


def test_get_adapter_requirements_and_fallback(tmp_path: Path) -> None:
    assert isinstance(
        get_adapter(tmp_path / "requirements-dev.txt"), RequirementsTxtAdapter
    )
    assert isinstance(get_adapter(tmp_path / "deps.in"), RequirementsTxtAdapter)
    assert isinstance(get_adapter(tmp_path / "weird.cfg"), RequirementsTxtAdapter)


def test_discover_orders_and_filters(tmp_path: Path) -> None:
    for n in (
        "requirements.txt",
        "requirements-dev.txt",
        "other.txt",
        "pyproject.toml",
    ):
        (tmp_path / n).write_text("a==1\n")
    (tmp_path / "requirements-dir.txt").mkdir()
    assert [p.name for p in discover(tmp_path)] == [
        "requirements-dev.txt",
        "requirements.txt",
    ]


def test_resolve_targets_file_dir_empty(tmp_path: Path) -> None:
    f = tmp_path / "r.txt"
    f.write_text("a==1\n")
    assert resolve_targets(f) == [f]
    with pytest.raises(DepKeeperError, match="No supported"):
        resolve_targets(tmp_path)


def test_parse_targets_combines_with_provenance(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("a==1.0\n")
    (tmp_path / "requirements-dev.txt").write_text("b==2.0\n")
    reqs = parse_targets(tmp_path)
    assert {r.name for r in reqs} == {"a", "b"}
    assert all(r.source_format == "requirements.txt" and r.source_file for r in reqs)


def test_parse_error_names_the_file(tmp_path: Path) -> None:
    f = tmp_path / "requirements.txt"
    f.write_text("-r missing.txt\n")
    with pytest.raises(DepKeeperError, match="Failed to parse"):
        parse_targets(f)


def test_default_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert default_target(Path("x.txt")) == Path("x.txt")
    assert default_target(None) == Path("requirements.txt")  # nothing found
    (tmp_path / "requirements-dev.txt").write_text("a==1\n")
    assert default_target(None) == Path(".")  # discovery fallback
    (tmp_path / "requirements.txt").write_text("a==1\n")
    assert default_target(None) == Path("requirements.txt")


TEXT = (
    "# header\r\n"
    "requests>=2.0,<3  # keep\r\n"
    "\r\n"
    "flask==1.0 \\\r\n"
    "    --hash=sha256:abc\r\n"
    "click>=7\r\n"
)


def _updates(text: str, versions: Dict[str, str]) -> List[SourceUpdate]:
    reqs = RequirementsParser().parse_string(text)
    return [(r, versions[r.name]) for r in reqs if r.name in versions]


def test_apply_updates_in_place_preserves_everything_else() -> None:
    out = RequirementsTxtAdapter().apply_updates(
        TEXT, _updates(TEXT, {"requests": "2.5.0", "click": "8.0.0"})
    )
    assert out == TEXT.replace("requests>=2.0,<3", "requests>=2.5.0,<3").replace(
        "click>=7", "click>=8.0.0"
    )


def test_apply_updates_noop_is_identical() -> None:
    assert RequirementsTxtAdapter().apply_updates(TEXT, []) == TEXT


def test_apply_updates_hash_refused_unless_allowed() -> None:
    ups = _updates(TEXT, {"flask": "2.0.0"})
    a = RequirementsTxtAdapter()
    with pytest.raises(DepKeeperError, match="x.txt:4"):
        a.apply_updates(TEXT, ups, path="x.txt")
    out = a.apply_updates(TEXT, ups, allow_hash_removal=True)
    assert "flask==2.0.0\r\n" in out and "--hash" not in out


def test_custom_adapter_registration(tmp_path: Path) -> None:
    class Toy(SourceAdapter):
        name = "toy"
        patterns = ("toy.cfg",)

        def can_handle(self, path: Path) -> bool:
            return path.name == "toy.cfg"

        def parse(self, path: Path) -> list:  # type: ignore[type-arg]
            from depkeeper.models import Requirement

            return [Requirement(name="zz", specs=[("==", "1")])]

        def apply_updates(
            self, original_text: str, updates: Sequence, **kw: object
        ) -> str:  # type: ignore[type-arg,override]
            return original_text.replace("1", updates[0][1])

    toy = Toy()
    registry.register(toy)
    try:
        (tmp_path / "toy.cfg").write_text("v=1")
        (tmp_path / "requirements.txt").write_text("a==1\n")
        assert [p.name for p in discover(tmp_path)] == ["requirements.txt", "toy.cfg"]
        assert get_adapter(tmp_path / "toy.cfg") is toy
        reqs = parse_targets(tmp_path)
        assert {r.source_format for r in reqs} == {"requirements.txt", "toy"}
        assert toy.requires_python(tmp_path / "toy.cfg") is None
    finally:
        registry._ADAPTERS.remove(toy)
