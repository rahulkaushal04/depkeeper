"""Pluggable dependency-file adapters (see `base` for the extension guide)."""

from __future__ import annotations

from depkeeper.core.sources.base import SourceAdapter, SourceUpdate
from depkeeper.core.sources.registry import (
    default_target,
    discover,
    get_adapter,
    parse_targets,
    register,
    resolve_targets,
)

__all__ = [
    "SourceAdapter",
    "SourceUpdate",
    "default_target",
    "discover",
    "get_adapter",
    "parse_targets",
    "register",
    "resolve_targets",
]
