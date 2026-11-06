"""Adapter for conda ``environment.yml`` files.

A narrow line-based reader (no YAML dependency) for the block-list subset conda
environments use: ``dependencies:`` items plus a nested ``- pip:`` list.

* ``pip:`` items are PEP 508 requirements and are checked against PyPI as usual.
* Conda-channel items are looked up on PyPI **by name only**; that is an
  approximation (``Requirement.approximate``) because conda and PyPI versions
  and packaging differ. Updates are written back in the original conda syntax.
* A fuzzy spec (``numpy=1.24``, ``pandas=2.0.*``) pins a *series*
  (``Requirement.series`` = significant components): it only updates when a
  newer series exists, and is rewritten at the same granularity (``=1.26``).
* ``python`` is never checked (see `requires_python`); items with build strings,
  ``|`` alternatives or well-known non-PyPI names are skipped.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import List, NamedTuple, Optional, Sequence, Tuple, Union

from depkeeper.exceptions import DepKeeperError, ParseError
from depkeeper.models import Requirement
from depkeeper.core.parser import RequirementsParser
from depkeeper.core.sources.base import SourceAdapter, SourceUpdate
from depkeeper.utils import get_logger
from depkeeper.utils.version_utils import rewrite_version_specs, specs_allow_version

logger = get_logger("sources.conda")

Spec = Tuple[str, str]

_DEPS_KEY = re.compile(r"^dependencies\s*:", re.M)
_ITEM_RE = re.compile(
    r"^(?:(?P<channel>\S+?)::)?(?P<name>[A-Za-z0-9][A-Za-z0-9_.\-]*)\s*(?P<spec>.*)$"
)
_PART_RE = re.compile(
    r"^(?P<op>===|==|=|~=|!=|>=|<=|>|<)?\s*(?P<ver>[0-9][A-Za-z0-9_.!+\-]*?)"
    r"(?P<wild>\.\*|\*)?$"
)
# conda name -> PyPI name where they differ commonly.
_PYPI_NAME = {"pytorch": "torch", "matplotlib-base": "matplotlib"}
# Conda-only packages (never on PyPI under that name); skipped quietly.
_NON_PYPI = {
    "pip", "mkl", "openssl", "ca-certificates", "certifi-conda", "zlib", "xz",
    "tk", "sqlite", "readline", "ncurses", "nodejs", "cudatoolkit", "cudnn",
    "pytorch-cuda", "r-base", "libffi", "bzip2", "intel-openmp", "blas",
}  # fmt: skip


# PyPI projects the ``lib*`` rule below would otherwise swallow.
_LIB_PYPI = {
    "librosa", "libsass", "libclang", "libcst", "libusb1", "libarchive-c",
    "libtmux", "libhoney", "libnacl", "libpysal", "libzim", "libsixel",
}  # fmt: skip


def _is_non_pypi(name: str) -> bool:
    """Whether *name* is a conda-only package that has no PyPI counterpart."""
    n = name.lower()
    return n in _NON_PYPI or (
        n not in _LIB_PYPI
        and (n.startswith(("lib", "_", "r-", "mkl", "cuda")) or n.endswith("-ng"))
    )


class _Item(NamedTuple):
    kind: str  # "conda" | "pip"
    line: int
    value: str
    start: int  # absolute offsets of the scalar text (quotes excluded)
    end: int


def _scalar(content: str, pos: int, line: int) -> Tuple[int, int]:
    """Return (start, end) of the YAML scalar beginning at *pos* in *content*."""
    if pos < len(content) and content[pos] in "\"'":
        close = content.find(content[pos], pos + 1)
        if close < 0:
            raise ParseError("Unterminated quoted item", line_number=line)
        return pos + 1, close
    m = re.search(r"\s+#", content[pos:])
    end = pos + m.start() if m else len(content)
    return pos, len(content[:end].rstrip())


def _scan(text: str) -> List[_Item]:
    """Find every dependency scalar; raise `ParseError` on unsupported shapes."""
    items: List[_Item] = []
    in_deps = in_pip = False
    base: Optional[int] = None
    offset = 0
    for lineno, raw in enumerate(io.StringIO(text, newline="").readlines(), 1):
        line_off, offset = offset, offset + len(raw)
        content = raw.rstrip("\r\n")
        stripped = content.strip()
        if not stripped or stripped.startswith("#") or stripped in ("---", "..."):
            continue
        indent = len(content) - len(content.lstrip(" "))
        if content[indent : indent + 1] == "\t":
            raise ParseError("Tabs are not allowed for indentation", line_number=lineno)
        is_item = stripped == "-" or stripped.startswith("- ")
        if indent == 0 and not is_item:  # top-level key
            key, _, rest = content.partition(":")
            in_deps, in_pip, base = key.strip() == "dependencies", False, None
            rest = re.sub(r"(^|\s)#.*$", "", rest).strip()
            if in_deps and rest and rest != "[]":
                raise ParseError(
                    "Only block-style 'dependencies:' lists are supported "
                    "(flow style '[a, b]' is not)",
                    line_number=lineno,
                    line_content=content,
                )
            continue
        if not in_deps:
            continue
        if not is_item:
            raise ParseError(
                "Expected a list item under 'dependencies:'",
                line_number=lineno,
                line_content=content,
            )
        if base is None:
            base = indent
        if in_pip and indent <= base:
            in_pip = False
        pos = indent + 1
        while pos < len(content) and content[pos] == " ":
            pos += 1
        if pos >= len(content) or content[pos] == "#":
            continue
        start, end = _scalar(content, pos, lineno)
        value = content[start:end]
        quoted = start > pos
        if not quoted and re.match(r"^pip\s*:", value):
            if value.partition(":")[2].strip():
                raise ParseError(
                    "Only block-style 'pip:' lists are supported",
                    line_number=lineno,
                    line_content=content,
                )
            in_pip = True
            continue
        if not quoted and re.search(r":(\s|$)", value) and not in_pip:
            logger.debug("Skipping non-list entry %r at line %d", value, lineno)
            continue
        if in_pip and indent <= base:
            continue
        kind = "pip" if in_pip else "conda"
        if kind == "pip" and value.startswith("-"):
            logger.debug("Skipping pip option %r at line %d", value, lineno)
            continue
        items.append(_Item(kind, lineno, value, line_off + start, line_off + end))
    return items


def _conda_specs(spec: str) -> Optional[Tuple[List[Spec], bool]]:
    """Translate a conda spec to ``(PEP 440 specs, fuzzy)``; None if unsupported.

    ``fuzzy`` marks ``=1.24`` / ``=1.24.*`` / ``1.24.*`` (a version prefix).
    """
    if not spec:
        return [], False
    if re.search(r"[|\[\]\s]", spec.replace(", ", ",")) or spec in ("*", "=*"):
        return None
    parts = spec.replace(", ", ",").split(",")
    out: List[Spec] = []
    fuzzy = False
    for part in parts:
        m = _PART_RE.match(part)
        if not m:
            return None  # includes build strings: ``=1.24=py311_0``
        op, ver, wild = m.group("op") or "", m.group("ver"), m.group("wild")
        if op in ("", "=") or (op == "==" and wild):
            if len(parts) > 1:
                return None
            fuzzy = True
            op = "=="
        elif wild:
            return None
        out.append((op, ver))
    return out, fuzzy


def _render(spec: str, new_version: str, pin: bool) -> str:
    """Return *spec* (conda syntax) retargeted at *new_version*."""
    parsed = _conda_specs(spec)
    if parsed is None:
        raise ValueError(f"unsupported conda spec {spec!r}")
    specs, fuzzy = parsed
    if not specs:  # unpinned: gain a pin
        return f"={new_version}"
    if pin:
        return f"=={new_version}"
    if fuzzy:
        m = _PART_RE.match(spec)
        assert m is not None
        n = len(m.group("ver").split("."))
        lead = re.match(r"\d+(\.\d+)*", new_version)
        trunc = ".".join((lead.group(0) if lead else new_version).split(".")[:n])
        return f"{m.group('op') or ''}{trunc}{m.group('wild') or ''}"
    new = rewrite_version_specs(specs, new_version)
    if not specs_allow_version(new, new_version):
        raise ValueError(f"constraint '{spec}' excludes {new_version}")
    sep = ", " if ", " in spec else ","
    return sep.join(f"{op}{v}" for op, v in new)


_PIP_HEAD = re.compile(r"\s*[A-Za-z0-9][A-Za-z0-9._-]*\s*(?:\[[^\]]*\])?")


def _pip_minimal(
    old: str, req: Requirement, new_version: str, pin: bool
) -> Optional[str]:
    """Rewrite only the specifier text of a ``pip:`` item (markers keep their spacing).

    None when the item has an unusual shape; the caller then re-renders it.
    """
    head = _PIP_HEAD.match(old)
    if not head or req.url or req.hashes or "@" in old:
        return None
    body, sep, marker = old[head.end() :].partition(";")
    specs = (
        [("==", new_version)] if pin else rewrite_version_specs(req.specs, new_version)
    )
    if not specs_allow_version(specs, new_version):
        raise ValueError(f"constraint '{body.strip()}' excludes {new_version}")
    lead = body[: len(body) - len(body.lstrip())]
    trail = body[len(body.rstrip()) :]
    return (
        old[: head.end()]
        + lead
        + ",".join(f"{o}{v}" for o, v in specs)
        + trail
        + sep
        + marker
    )


class CondaYamlAdapter(SourceAdapter):
    """``environment.yml`` / ``environment.yaml`` (conda dependencies + ``pip:``)."""

    name = "environment.yml"
    patterns = ("environment.yml", "environment.yaml")

    def can_handle(self, path: Path) -> bool:
        """Return True for ``environment.y[a]ml`` or YAML files with ``dependencies:``."""
        if path.name.lower() in self.patterns:
            return True
        if path.suffix.lower() not in (".yml", ".yaml"):
            return False
        try:
            return bool(_DEPS_KEY.search(path.read_bytes().decode("utf-8-sig")))
        except (OSError, UnicodeDecodeError):
            return False

    def _read(self, path: Path) -> str:
        try:
            return path.read_bytes().decode("utf-8-sig")
        except (OSError, UnicodeDecodeError) as e:
            raise ParseError(f"Cannot read file: {e}", file_path=str(path)) from e

    def parse(self, path: Path) -> List[Requirement]:
        """Parse conda and ``pip:`` dependencies with their text spans.

        Raises:
            ParseError: Unreadable file or an unsupported YAML shape.
        """
        text = self._read(path)
        items = _scan(text)
        parser = RequirementsParser()
        reqs: List[Requirement] = []
        for it in items:
            if it.kind == "pip":
                got = parser.parse_line(it.value, it.line, str(path))
                if isinstance(got, Requirement):
                    got.source_format, got.span, got.raw_line = (
                        self.name,
                        (it.start, it.end),
                        it.value,
                    )
                    got.line_number = it.line
                    reqs.append(got)
                continue
            m = _ITEM_RE.match(it.value)
            if not m:
                logger.warning(
                    "%s:%d: skipping unparsable dependency item %r",
                    path,
                    it.line,
                    it.value,
                )
                continue
            name = m.group("name")
            if name.lower() == "python" or _is_non_pypi(name):
                logger.debug("Skipping non-PyPI conda package %r", name)
                continue
            spec = m.group("spec").strip()
            parsed = _conda_specs(spec)
            if parsed is None:
                logger.debug("Skipping unsupported conda spec %r", it.value)
                continue
            start = it.start + (m.start("spec") if spec else m.end("name"))
            reqs.append(
                Requirement(
                    name=_PYPI_NAME.get(name.lower(), name),
                    specs=parsed[0],
                    line_number=it.line,
                    raw_line=it.value,
                    source_format="conda",
                    span=(start, start + len(spec)),
                    approximate=True,
                    series=len(parsed[0][0][1].split(".")) if parsed[1] else None,
                )
            )
        return reqs

    def requires_python(self, path: Path) -> Optional[str]:
        """PEP 440 specifier from the ``python`` dependency, else ``None``.

        ``python=3.10`` (fuzzy) becomes ``==3.10.*``; ``python>=3.9`` stays
        ``>=3.9``; unpinned, ``*`` or unsupported specs give ``None``.
        """
        try:
            items = _scan(self._read(path))
        except ParseError:
            return None
        for it in items:
            m = _ITEM_RE.match(it.value) if it.kind == "conda" else None
            if not m or m.group("name").lower() != "python":
                continue
            parsed = _conda_specs(m.group("spec").strip())
            if not parsed or not parsed[0]:
                return None
            specs, fuzzy = parsed
            return ",".join(f"{op}{v}.*" if fuzzy else f"{op}{v}" for op, v in specs)
        return None

    def apply_updates(
        self,
        original_text: str,
        updates: Sequence[SourceUpdate],
        *,
        pin: bool = False,
        allow_hash_removal: bool = False,
        path: Optional[Union[str, Path]] = None,
    ) -> str:
        """See `SourceAdapter.apply_updates`; edits are applied by character span."""
        label = str(path) if path is not None else "<environment.yml>"
        edits: List[Tuple[int, int, str]] = []
        for req, new_version in updates:
            if req.span is None:
                raise DepKeeperError(f"No source span for '{req.name}' in {label}")
            if req.url or req.direct_reference:
                continue  # direct references carry no version to rewrite
            start, end = req.span
            old = original_text[start:end]
            where = f"{label}:{req.line_number}"
            try:
                if req.source_format == "conda":
                    cur = _conda_specs(old)
                    if cur is None or cur[0] != list(req.specs):
                        raise ValueError("file changed since it was read")
                    new = _render(old, new_version, pin)
                else:
                    if old != req.raw_line:
                        raise ValueError("file changed since it was read")
                    new = _pip_minimal(
                        old, req, new_version, pin
                    ) or req.update_version(
                        new_version,
                        pin=pin,
                        preserve_trailing_newline=False,
                        allow_hash_removal=allow_hash_removal,
                    )
            except ValueError as exc:
                raise DepKeeperError(
                    f"Cannot update requirement at {where}: {exc}"
                ) from exc
            edits.append((start, end, new))
        out = original_text
        for start, end, new in sorted(edits, reverse=True):
            out = out[:start] + new + out[end:]
        return out
