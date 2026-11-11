"""Adapter for ``pyproject.toml`` (PEP 621, PEP 735, build-system, Poetry).

``tomli`` validates the file and supplies ``requires-python``; a small
position-tracking scanner (`_Scanner`) then locates the string literals that
hold dependencies so edits replace only the specifier characters in the
original text (comments, quoting, layout and line endings survive).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple, Union

import tomli as tomllib

from depkeeper.exceptions import DepKeeperError, ParseError
from depkeeper.models import Requirement
from depkeeper.core.sources.base import SourceAdapter, SourceUpdate
from depkeeper.utils import safe_read_file
from depkeeper.utils.logger import get_logger
from depkeeper.utils.redact import redact
from depkeeper.utils.version_utils import rewrite_version_specs, specs_allow_version

logger = get_logger("sources.pyproject")

Spec = Tuple[str, str]


def _warn_escaped(text: str, node: "_Str", path: Path) -> None:
    # shortcut: escapes before the marker are not edited (spans would not map
    # to decoded text); loud skip until someone needs them.
    logger.warning(
        "%s:%d: skipping dependency string with backslash escapes in its "
        "name or version (not checked or updated)",
        path,
        _line_of(text, node.start),
    )


class _Str:
    """A TOML string literal: content span in the text (quotes excluded)."""

    __slots__ = ("start", "end", "escaped")

    def __init__(self, start: int, end: int, escaped: bool) -> None:
        self.start, self.end, self.escaped = start, end, escaped


class _Other:
    """A non-string scalar (number, bool, date): only its position is kept."""

    __slots__ = ("start",)

    def __init__(self, start: int) -> None:
        self.start = start


Node = Any  # _Str | List[Node] | Dict[str, Node] | None (other scalar)


class _Scanner:
    """Minimal TOML walker; input is already validated by tomli."""

    _BARE = re.compile(r"[A-Za-z0-9_-]+")

    def __init__(self, text: str) -> None:
        self.t = text
        self.i = 0

    def _skip(self, newlines: bool) -> None:
        t = self.t
        while self.i < len(t):
            c = t[self.i]
            if c == "#":
                while self.i < len(t) and t[self.i] != "\n":
                    self.i += 1
            elif c in " \t" or (newlines and c in "\r\n"):
                self.i += 1
            else:
                break

    def _string(self) -> _Str:
        t, q = self.t, self.t[self.i]
        triple = t.startswith(q * 3, self.i)
        self.i += 3 if triple else 1
        start, escaped = self.i, False
        while True:
            c = t[self.i]
            if q == '"' and c == "\\":
                escaped = True
                self.i += 2
            elif triple and t.startswith(q * 3, self.i):
                end = self.i
                # up to two extra quotes may directly precede the closer
                while t.startswith(q, end + 3):
                    end += 1
                self.i = end + 3
                return _Str(start, end, escaped)
            elif not triple and c == q:
                self.i += 1
                return _Str(start, self.i - 1, escaped)
            else:
                self.i += 1

    def _key(self) -> List[str]:
        parts: List[str] = []
        while True:
            self._skip(False)
            if self.t[self.i] in "\"'":
                s = self._string()
                parts.append(self.t[s.start : s.end])
            else:
                m = self._BARE.match(self.t, self.i)
                assert m
                parts.append(m.group())
                self.i = m.end()
            self._skip(False)
            if self.i < len(self.t) and self.t[self.i] == ".":
                self.i += 1
                continue
            return parts

    def _value(self) -> Node:
        t = self.t
        self._skip(False)
        c = t[self.i]
        if c in "\"'":
            return self._string()
        if c == "[":
            self.i += 1
            arr: List[Node] = []
            while True:
                self._skip(True)
                if t[self.i] == "]":
                    self.i += 1
                    return arr
                arr.append(self._value())
                self._skip(True)
                if t[self.i] == ",":
                    self.i += 1
        if c == "{":
            self.i += 1
            table: Dict[str, Node] = {}
            while True:
                self._skip(True)
                if t[self.i] == "}":
                    self.i += 1
                    return table
                self._assign(table)
                self._skip(True)
                if t[self.i] == ",":
                    self.i += 1
        begin = self.i
        while self.i < len(t) and t[self.i] not in ",]}#\r\n":
            self.i += 1
        return _Other(begin)

    def _assign(self, table: Dict[str, Node]) -> None:
        keys = self._key()
        self.i += 1  # '='
        for k in keys[:-1]:
            nxt = table.setdefault(k, {})
            table = nxt if isinstance(nxt, dict) else {}
        table[keys[-1]] = self._value()

    def scan(self) -> Dict[str, Node]:
        t = self.t
        root: Dict[str, Node] = {}
        cur = root
        while True:
            self._skip(True)
            if self.i >= len(t):
                return root
            if t[self.i] == "[":
                is_array = t.startswith("[[", self.i)
                self.i += 2 if is_array else 1
                keys = self._key()
                self.i += 2 if is_array else 1
                cur = root
                for n, k in enumerate(keys):
                    nxt = cur.setdefault(
                        k, {} if n < len(keys) - 1 or not is_array else []
                    )
                    if isinstance(nxt, list):
                        if n == len(keys) - 1:
                            nxt.append({})
                        nxt = nxt[-1] if nxt else {}
                    cur = nxt if isinstance(nxt, dict) else {}
            else:
                self._assign(cur)


_HEAD = re.compile(
    r"\s*(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*"
    r"(?:\[(?P<extras>[^\]]*)\])?\s*"
)
_SPEC = re.compile(r"(===|==|!=|~=|<=|>=|<|>)\s*([^\s,()]+)")
_JUNK = re.compile(r"[\s,()]*")
_CARET_TILDE = re.compile(r"^(\s*)([\^~])(?!=)(\s*)([^\s,]+)(\s*)$")
_LOOSE_SECTION = re.compile(
    r"^\s*\[+\s*(project|dependency-groups|build-system|tool\.poetry)\b", re.M
)


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _parse_specs(text: str) -> Optional[List[Spec]]:
    """Specifier pairs from *text*, or None when it holds anything else."""
    specs = [(m.group(1), m.group(2)) for m in _SPEC.finditer(text)]
    return specs if _JUNK.fullmatch(_SPEC.sub("", text)) else None


def _release(version: str) -> Optional[List[int]]:
    parts = version.split(".")
    ok = all(p.isascii() and p.isdigit() for p in parts)  # not "²" / "١"
    return [int(p) for p in parts] if ok else None


def _caret_tilde_specs(op: str, version: str) -> Optional[List[Spec]]:
    """Equivalent PEP 440 range for a Poetry ``^``/``~`` constraint."""
    rel = _release(version)
    if rel is None:
        return None
    if op == "~":
        upper = [rel[0] + 1] if len(rel) == 1 else [rel[0], rel[1] + 1]
    else:
        k = next((n for n, p in enumerate(rel) if p), len(rel) - 1)
        upper = rel[:k] + [rel[k] + 1]
    return [(">=", version), ("<", ".".join(map(str, upper)))]


def _poetry_specs(text: str) -> Optional[List[Spec]]:
    s = text.strip()
    if not s or s == "*" or "||" in s:
        return None
    m = _CARET_TILDE.match(s)
    if m:
        return _caret_tilde_specs(m.group(2), m.group(4))
    if "^" in s or re.search(r"~(?!=)", s):
        return None
    specs: List[Spec] = []
    for part in s.split(","):
        part = part.strip()
        got = _parse_specs(part)
        if got:
            specs.extend(got)
        elif re.fullmatch(r"[0-9][^\s,]*", part):
            specs.append(("==", part))
        else:
            return None
    return specs


class PyprojectTomlAdapter(SourceAdapter):
    """Dependencies in ``pyproject.toml``; edits are in-place and minimal."""

    name = "pyproject"
    patterns = ("pyproject.toml",)

    def can_handle(self, path: Path) -> bool:
        """Return True for a ``pyproject.toml`` (valid, or clearly meant to be)."""
        if path.name.lower() != "pyproject.toml":
            return False
        try:
            text = safe_read_file(path, encoding="utf-8-sig", newline="")
        except Exception:
            return False
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return True  # broken file: parse() reports it, not the requirements parser
        return True  # any valid pyproject.toml is ours, even without dependencies

    def has_dependencies(self, path: Path) -> bool:
        """Return True when the file has a dependency-bearing section."""
        try:
            text = safe_read_file(path, encoding="utf-8-sig", newline="")
            return self._has_sections(tomllib.loads(text))
        except tomllib.TOMLDecodeError:
            return bool(_LOOSE_SECTION.search(text))  # broken: parse() reports it
        except Exception:
            return False

    @staticmethod
    def _has_sections(data: Dict[str, Any]) -> bool:
        project = data.get("project", {})
        poetry = data.get("tool", {}).get("poetry", {})
        return any(
            (
                "dependencies" in project,
                "optional-dependencies" in project,
                "dependency-groups" in data,
                "requires" in data.get("build-system", {}),
                "dependencies" in poetry,
                "dev-dependencies" in poetry,
                "group" in poetry,
                bool(PyprojectTomlAdapter._tool_lists(data)),
            )
        )

    def _load(self, path: Path) -> Tuple[str, Dict[str, Any]]:
        text = safe_read_file(path, encoding="utf-8-sig", newline="")
        try:
            return text, tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            m = re.search(r"line ([0-9]+)", str(exc))
            raise ParseError(
                f"Invalid TOML: {exc}",
                line_number=int(m.group(1)) if m else None,
                file_path=str(path),
            ) from exc

    def requires_python(self, path: Path) -> Optional[str]:
        """Return the declared Python range as a PEP 440 specifier, or None.

        ``project.requires-python`` wins; otherwise Poetry's
        ``tool.poetry.dependencies.python`` (caret/tilde translated).
        """
        try:
            data = self._load(path)[1]
        except (ParseError, DepKeeperError):
            return None
        value = data.get("project", {}).get("requires-python")
        if isinstance(value, str):
            return value
        py = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        py = py.get("python") if isinstance(py, dict) else None
        if isinstance(py, dict):
            py = py.get("version")
        specs = _poetry_specs(py) if isinstance(py, str) else None
        return ",".join(op + v for op, v in specs) if specs else None

    def parse(self, path: Path) -> List[Requirement]:
        """Parse PEP 508 and Poetry dependencies with their text spans.

        Raises:
            ParseError: Invalid TOML, or dependencies are not arrays of strings.
        """
        text, _ = self._load(path)
        try:
            tree = _Scanner(text).scan()
        except (IndexError, AssertionError, ValueError) as exc:
            raise ParseError(f"Cannot locate dependencies: {exc}", file_path=str(path))
        src = str(path.resolve())
        reqs: List[Requirement] = []
        for node in self._pep508_nodes(tree, text, path):
            req = self._pep508(text, node, path)
            if req:
                reqs.append(req)
            elif not node.escaped and not text[node.start : node.end].startswith("-"):
                logger.warning(
                    "%s:%d: skipping invalid requirement %r",
                    path,
                    _line_of(text, node.start),
                    redact(text[node.start : node.end]),
                )
        for name, node in self._poetry_nodes(tree):
            req = self._poetry(text, name, node, path)
            if req:
                reqs.append(req)
        for r in reqs:
            r.source_file, r.source_format = src, self.name
        return reqs

    @staticmethod
    def _table(node: Node, *keys: str) -> Node:
        for k in keys:
            if not isinstance(node, dict):
                return None
            node = node.get(k)
        return node

    def _pep508_nodes(
        self, tree: Dict[str, Node], text: str, path: Path
    ) -> Iterator[_Str]:
        lists: List[Node] = [
            self._table(tree, "project", "dependencies"),
            self._table(tree, "build-system", "requires"),
        ]
        for tbl in (
            self._table(tree, "project", "optional-dependencies"),
            self._table(tree, "dependency-groups"),
        ):
            if isinstance(tbl, dict):
                lists.extend(tbl.values())
        lists.extend(self._tool_lists(tree))
        for lst in lists:
            if isinstance(lst, (_Str, _Other, dict)):
                raise ParseError(
                    "Dependencies must be an array of strings",
                    line_number=_line_of(text, lst.start)
                    if hasattr(lst, "start")
                    else None,
                    file_path=str(path),
                )
            for n in lst if isinstance(lst, list) else ():
                if isinstance(n, _Str):
                    yield n
                elif isinstance(n, _Other):  # {include-group = ...} tables are fine
                    logger.warning(
                        "%s:%d: skipping non-string dependency entry",
                        path,
                        _line_of(text, n.start),
                    )

    @classmethod
    def _tool_lists(cls, root: Dict[str, Any]) -> List[Node]:
        """PEP 508 lists of uv, PDM and Hatch (``root`` is a node tree or tomli data)."""
        out: List[Node] = [cls._table(root, "tool", "uv", "dev-dependencies")]
        pdm = cls._table(root, "tool", "pdm", "dev-dependencies")
        if isinstance(pdm, dict):
            out.extend(pdm.values())
        envs = cls._table(root, "tool", "hatch", "envs")
        for env in envs.values() if isinstance(envs, dict) else ():
            out += [cls._table(env, k) for k in ("dependencies", "extra-dependencies")]
        return [lst for lst in out if lst is not None]

    def _poetry_nodes(self, tree: Dict[str, Node]) -> Iterator[Tuple[str, Node]]:
        poetry = self._table(tree, "tool", "poetry")
        tables: List[Node] = [
            self._table(poetry, "dependencies"),
            self._table(poetry, "dev-dependencies"),
        ]
        groups = self._table(poetry, "group")
        if isinstance(groups, dict):
            tables.extend(self._table(g, "dependencies") for g in groups.values())
        for tbl in tables:
            if isinstance(tbl, dict):
                yield from tbl.items()

    def _pep508(self, text: str, node: _Str, path: Path) -> Optional[Requirement]:
        s = text[node.start : node.end]
        decoded = None
        if node.escaped:
            # Escapes after the ';' (typically \" in markers) leave the name and
            # specifier text identical to the source, so those stay editable.
            cut = s.find(";")
            if cut < 0 or "\\" in s[:cut]:
                _warn_escaped(text, node, path)
                return None
            quote = 3 if text.startswith('"""', node.start - 3) else 1
            decoded = tomllib.loads(
                "v = " + text[node.start - quote : node.end + quote]
            )["v"]
            s = s[:cut]
        head = _HEAD.match(s)
        if not head:
            return None
        name_end = node.start + len(s[: head.end()].rstrip())
        extras = [
            e.strip() for e in (head.group("extras") or "").split(",") if e.strip()
        ]
        rest, rest_at = s[head.end() :], node.start + head.end()
        line = _line_of(text, node.start)
        req = Requirement(
            name=head.group("name"),
            extras=extras,
            line_number=line,
            raw_line=(decoded or s).strip(),
        )
        if rest.startswith("@"):
            url, _, marker = rest[1:].strip().partition(" ;")
            req.url, req.direct_reference = url.strip(), True
            req.markers = req.markers or marker.strip() or None
            return req
        body, _, marker = rest.partition(";")
        req.markers = marker.strip() or None
        stripped = body.strip()
        inner = (
            stripped[1:-1]
            if stripped.startswith("(") and stripped.endswith(")")
            else stripped
        )
        if decoded is not None:
            req.markers = decoded.partition(";")[2].strip() or None
        specs = _parse_specs(inner)
        if specs is None:
            logger.debug(
                "Skipping unparsable requirement %r at line %d", redact(s), line
            )
            return None
        req.specs = specs
        if inner.strip():
            start = rest_at + body.index(inner.strip())
            req.span = (start, start + len(inner.strip()))
        else:
            req.span = (name_end, name_end)
        return req

    def _poetry(
        self, text: str, name: str, node: Node, path: Path
    ) -> Optional[Requirement]:
        if isinstance(node, dict):
            if any(k in node for k in ("git", "path", "url", "file")):
                logger.debug("Skipping non-PyPI Poetry dependency %s", name)
                return None
            node = node.get("version")
        if name.lower() == "python":
            return None
        if isinstance(node, _Str) and node.escaped:
            _warn_escaped(text, node, path)
            return None
        if not isinstance(node, _Str):
            logger.debug("Skipping Poetry dependency %s", name)
            return None
        specs = _poetry_specs(text[node.start : node.end])
        if specs is None:
            logger.debug("Skipping Poetry dependency %s: unsupported constraint", name)
            return None
        return Requirement(
            name=name,
            specs=specs,
            line_number=_line_of(text, node.start),
            raw_line=text[node.start : node.end],
            span=(node.start, node.end),
        )

    def apply_updates(
        self,
        original_text: str,
        updates: Sequence[SourceUpdate],
        *,
        pin: bool = False,
        allow_hash_removal: bool = False,
        path: Optional[Union[str, Path]] = None,
    ) -> str:
        """See `SourceAdapter.apply_updates`; the result is re-validated as TOML."""
        label = str(path) if path is not None else "<pyproject.toml>"
        edits: Dict[Tuple[int, int], str] = {}
        for req, new in updates:
            if req.url:
                continue  # direct references carry no version to rewrite
            if req.span is None:
                raise DepKeeperError(
                    f"Cannot update {req.name} in {label}: no location"
                )
            start, end = req.span
            seg = original_text[start:end]
            got = _parse_specs(seg)
            if got is None:
                got = _poetry_specs(seg)
            if got != list(req.specs):
                raise DepKeeperError(
                    f"Cannot update {req.name} at {label}:{req.line_number}: "
                    "the file changed since it was read"
                )
            try:
                edits[(start, end)] = self._render(
                    original_text[start:end], req, new, pin
                )
            except ValueError as exc:
                raise DepKeeperError(
                    f"Cannot update requirement at {label}:{req.line_number}: {exc}"
                ) from exc
        out, last = [], 0
        for (start, end), repl in sorted(edits.items()):
            if start < last:
                raise DepKeeperError(f"Overlapping updates in {label}")
            out += [original_text[last:start], repl]
            last = end
        out.append(original_text[last:])
        result = "".join(out)
        try:
            tomllib.loads(result)
        except tomllib.TOMLDecodeError as exc:
            raise DepKeeperError(f"Update would produce invalid TOML in {label}: {exc}")
        return result

    @staticmethod
    def _render(segment: str, req: Requirement, new: str, pin: bool) -> str:
        m = _CARET_TILDE.match(segment)
        if m and not pin:  # keep ^/~ style: only the base version moves
            return f"{m.group(1)}{m.group(2)}{m.group(3)}{new}{m.group(5)}"
        specs: List[Spec] = (
            [("==", new)] if pin else rewrite_version_specs(req.specs, new)
        )
        if not specs_allow_version(specs, new):
            raise ValueError(
                f"the declared constraint '{segment.strip()}' excludes {new}; "
                "relax it or use --pin"
            )
        if re.match(r"\s*[0-9]", segment) and specs == [("==", new)]:
            return new  # Poetry's bare "1.2.3" means "=="
        sep = ", " if ", " in segment else ","
        return sep.join(f"{op}{v}" for op, v in specs)
