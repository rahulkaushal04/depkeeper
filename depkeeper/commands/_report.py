"""Shared helpers for ``check`` and ``update``.

Covers option parsing, target-Python resolution and the machine/Markdown
renderers (JSON envelope, PR-body).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any, Dict, List, Optional, Sequence, Tuple

import click
from rich.markup import escape
from packaging.specifiers import InvalidSpecifier, SpecifierSet

from depkeeper.config import DepKeeperConfig, parse_duration
from depkeeper.core import ResolutionResult
from depkeeper.core.data_store import PyPIDataStore
from depkeeper.models import Package, Requirement
from depkeeper.utils import get_logger, get_raw_console
from depkeeper.utils.naming import normalize_package_name
from depkeeper.utils.version_utils import get_update_type

logger = get_logger("commands.report")

#: ``schema_version`` of the ``--format json-v2`` envelope.
ENVELOPE_SCHEMA_VERSION = 2

_PY_RE = re.compile(r"\A[0-9]+\.[0-9]+\Z")


def python_version_option(
    _ctx: click.Context, _param: click.Parameter, value: Optional[str]
) -> Optional[str]:
    """Validate ``--python-version`` (``X.Y``)."""
    if value is not None and not _PY_RE.match(value.strip()):
        raise click.BadParameter(f"expected X.Y such as '3.9', got {value!r}")
    return value.strip() if value else None


def min_age_option(
    _ctx: click.Context, _param: click.Parameter, value: Optional[str]
) -> Optional[timedelta]:
    """Parse ``--min-age`` (``7d``, ``12h``, ``2w``, bare number = days)."""
    if value is None:
        return None
    try:
        return parse_duration(value)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc


def minimum_python(spec: str) -> Optional[str]:
    """Lowest ``X.Y`` a ``requires-python`` / conda pin allows.

    Rule: the oldest interpreter the project supports, so a candidate that
    works there works on every newer supported Python as well. A bare
    ``3.10`` (conda style) is taken literally. The result is the lowest
    ``X.Y`` for which *some* patch release is allowed (``>=3.8.5`` gives
    ``3.8``); a bare major (``python=3`` / ``==3.*``) names no minor, so
    gives ``None`` (running interpreter).
    """
    spec = spec.strip()
    if _PY_RE.match(spec):
        return spec
    if re.fullmatch(r"=*\s*\d+(\.\*)?", spec):
        return None
    try:
        sset = SpecifierSet(spec)
    except InvalidSpecifier:
        return None
    # An upper-bound-only spec (``<3.9``) names no lower bound to target.
    if not any(sp.operator in (">=", ">", "==", "~=") for sp in sset):
        return None
    for major, top in ((2, 8), (3, 40)):
        for minor in range(0, top):
            if sset.contains(f"{major}.{minor}.0", prereleases=True) or (
                sset.contains(f"{major}.{minor}.999", prereleases=True)
            ):
                # ``>=3.8.5`` still allows some 3.8.x, so step back one minor
                if (
                    ">=" in spec
                    and minor
                    and sset.contains(f"{major}.{minor - 1}.99", prereleases=True)
                ):
                    minor -= 1
                return f"{major}.{minor}"
    return None


def resolve_target_python(
    flag: Optional[str], cfg: Optional[DepKeeperConfig], target: Path
) -> Tuple[Optional[str], str]:
    """Pick the Python candidates must support and say who decided.

    Precedence: ``--python-version`` > config ``python_version`` > the
    file's own declaration (``requires_python`` of the source adapter; with
    several files the lowest minimum wins) > the running interpreter
    (returned as ``None``, which `VersionChecker` interprets that way).
    """
    if flag:
        return flag, "--python-version"
    if cfg is not None and cfg.python_version:
        return cfg.python_version, "config python_version"
    from depkeeper.core.sources import get_adapter, resolve_targets

    found: List[Tuple[Tuple[int, ...], str, str]] = []
    try:
        for f in resolve_targets(target):
            spec = get_adapter(f).requires_python(f)
            minimum = minimum_python(spec) if spec else None
            if minimum:
                found.append(
                    (tuple(int(x) for x in minimum.split(".")), minimum, f.name)
                )
    except Exception as exc:  # never let inference break the run
        logger.debug("Could not read requires_python: %s", exc)
    if found:
        _, minimum, name = min(found)
        return minimum, f"{name} requires-python"
    return None, "running interpreter"


@dataclass
class Row:
    """One package plus where it came from and its release links."""

    pkg: Package
    req: Optional[Requirement] = None
    links: Dict[str, str] = field(default_factory=dict)
    #: Version an ``update`` writes; ``None`` means ``pkg.recommended_version``.
    target: Optional[str] = None

    @property
    def new_version(self) -> Optional[str]:
        """Version this row moves to (explicit target, else the recommendation)."""
        return self.target or self.pkg.recommended_version

    @property
    def label(self) -> str:
        """Update label (calver aware) for the change this row represents."""
        return get_update_type(
            self.pkg.current_version, self.new_version, self.pkg.versioning
        )

    @property
    def is_direct(self) -> bool:
        """Return whether the requirement is a URL or editable install."""
        return bool(self.req and (self.req.url or self.req.editable))

    @property
    def failed(self) -> bool:
        """Return whether the PyPI lookup failed for a package that should be there."""
        # Conda names may legitimately be absent from PyPI: not a failure.
        return (
            not self.pkg.latest_version
            and not self.is_direct
            and not (self.req and self.req.approximate)
        )


def collect_links(
    data_store: PyPIDataStore, packages: Sequence[Package]
) -> Dict[str, Dict[str, str]]:
    """Return release links per package name from the (already warm) data store."""
    getter = getattr(data_store, "get_cached_package", None)
    out: Dict[str, Dict[str, str]] = {}
    if getter is None:
        return out
    for pkg in packages:
        data = getter(pkg.name)
        links_fn = getattr(data, "release_links", None)
        if callable(links_fn):
            found = links_fn()
            if isinstance(found, dict) and found:
                out[pkg.name] = found
    return out


def make_rows(
    requirements: Sequence[Requirement],
    packages: Sequence[Package],
    links: Optional[Dict[str, Dict[str, str]]] = None,
) -> List[Row]:
    """Return rows pairing packages with their requirement (positional) and links."""
    links = links or {}
    return [
        Row(
            p, requirements[i] if i < len(requirements) else None, links.get(p.name, {})
        )
        for i, p in enumerate(packages)
    ]


def display_path(source: Optional[str]) -> str:
    """Return *source* relative to the working directory when possible."""
    if not source:
        return "-"
    try:
        return os.path.relpath(source)
    except ValueError:  # different drive on Windows
        return source


def multi_file(rows: Sequence[Row]) -> bool:
    """Return whether the rows come from more than one source file."""
    return len({r.req.source_file for r in rows if r.req and r.req.source_file}) > 1


def source_cell(row: Row) -> str:
    """Return ``path:line`` (line omitted when unknown)."""
    if not row.req:
        return "-"
    line = f":{row.req.line_number}" if row.req.line_number else ""
    return f"{display_path(row.req.source_file)}{line}"


def age_text(pkg: Package) -> Optional[str]:
    """Return a sentence for the recommended version's age (``released 3 days ago``)."""
    days = pkg.recommended_age_days()
    if days is None:
        return None
    return (
        "released today"
        if days == 0
        else f"released {days} day{'s' if days != 1 else ''} ago"
    )


def age_short(pkg: Package) -> str:
    """Return a compact age for narrow tables (``12d``, ``today``, ``-``)."""
    days = pkg.recommended_age_days()
    return "-" if days is None else "today" if days == 0 else f"{days}d"


def policy_note(packages: Sequence[Package]) -> Optional[str]:
    """Return one line naming packages that policy held or ignored."""
    held = [p.name for p in packages if p.held]
    ignored = [p.name for p in packages if p.ignored]
    parts = []
    if held:
        parts.append(f"held by policy: {', '.join(held)}")
    if ignored:
        parts.append(f"ignored by policy: {', '.join(ignored)}")
    return "; ".join(parts) or None


def cooldown_note(packages: Sequence[Package]) -> Optional[str]:
    """Return one line naming versions withheld by the ``min_age`` cooldown."""
    items = [
        f"{p.name} ({p.cooldown_skipped} withheld)"
        for p in packages
        if p.cooldown_skipped
    ]
    return f"held back by min_age cooldown: {', '.join(items)}" if items else None


def major_note(packages: Sequence[Package]) -> Optional[str]:
    """Return one line naming majors that exist but were not applied."""
    items = [
        f"{p.name} {p.major_available} "
        + (
            "(blocked by max_update; raise --max-update)"
            if p.major_capped
            else f"(use --allow-major {p.name})"
        )
        for p in packages
        if p.major_available
    ]
    return f"major available: {'; '.join(items)}" if items else None


def allow_major_names(values: Sequence[str]) -> List[str]:
    """Normalise ``--allow-major`` values, keeping the ``*`` wildcard as is."""
    return sorted(
        {v.strip() if v.strip() == "*" else normalize_package_name(v) for v in values}
    )


def unknown_allow_major_note(
    names: Sequence[str], requirements: Sequence[Requirement]
) -> Optional[str]:
    """Return one warning for ``--allow-major`` names absent from the files."""
    known = {normalize_package_name(r.name) for r in requirements}
    unknown = [n for n in names if n != "*" and n not in known]
    if not unknown:
        return None
    return "; ".join(
        f"--allow-major {n}: not in the requirements file(s)" for n in unknown
    )


def clean_specifier(spec: Optional[str]) -> Optional[str]:
    """Drop empty clauses (``>=3.7,`` -> ``>=3.7``) from a specifier string."""
    if not spec:
        return spec
    return ",".join(c.strip() for c in spec.split(",") if c.strip()) or None


def attention_note(packages: Sequence[Package], failed: Sequence[str] = ()) -> str:
    """Return what still needs attention even though nothing is outdated.

    Empty when the packages are genuinely up to date, i.e. there are no
    unresolved conflicts, no package held back by a conflict and no failed
    lookups.
    """
    conflicted = [p.name for p in packages if p.has_conflicts()]
    held = [
        p.name for p in packages if p.conflict_held and p.name not in set(conflicted)
    ]
    parts = []
    if conflicted:
        parts.append(f"unresolved conflicts: {', '.join(conflicted)}")
    if held:
        parts.append(f"held back by conflicts: {', '.join(held)}")
    if failed:
        parts.append(f"could not be checked: {', '.join(failed)}")
    return "No updates available, but there are " + "; ".join(parts) if parts else ""


def package_json(row: Row) -> Dict[str, Any]:
    """Return ``Package.to_json()`` plus links/ignored (and file info).

    A package frozen by policy reports status ``held`` / ``ignored`` rather
    than ``latest``: it may well have a newer release.
    """
    entry = row.pkg.to_json()
    if entry["status"] == "latest" and (row.pkg.held or row.pkg.ignored):
        entry["status"] = "held" if row.pkg.held else "ignored"
    reqs = entry.get("python_requirements")
    if reqs:
        entry["python_requirements"] = {
            k: clean_specifier(v) or v for k, v in reqs.items()
        }
    if row.pkg.ignored:
        entry["ignored"] = True
    if row.links:
        entry["links"] = dict(row.links)
    return entry


def build_envelope(
    rows: Sequence[Row], python: Tuple[Optional[str], str]
) -> Dict[str, Any]:
    """Return the ``json-v2`` document (see docs/reference/cli-commands.md)."""
    packages: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    files: Dict[str, Dict[str, Any]] = {}
    by_type: Dict[str, int] = {}
    counts = {"outdated": 0, "up_to_date": 0, "held": 0, "ignored": 0, "conflicts": 0}

    for row in rows:
        pkg, req = row.pkg, row.req
        entry = package_json(row)
        entry["file"] = req.source_file if req else None
        entry["line"] = (req.line_number or None) if req else None
        entry["source_format"] = req.source_format if req else None
        entry["age_days"] = pkg.recommended_age_days()
        entry["held"] = pkg.held
        entry["ignored"] = pkg.ignored
        entry["versioning"] = pkg.versioning
        entry["update_type"] = entry.get("update_type")
        entry.setdefault("links", {})
        packages.append(entry)

        if req and req.source_file:
            f = files.setdefault(
                req.source_file,
                {"path": req.source_file, "format": req.source_format, "packages": 0},
            )
            f["packages"] += 1
        if row.failed:
            errors.append(
                {
                    "package": pkg.name,
                    "file": entry["file"],
                    "line": entry["line"],
                    "message": pkg.metadata.get(
                        "lookup_error", "not found on PyPI or network error"
                    ),
                }
            )
        if entry["status"] in ("outdated", "install", "downgrade"):
            counts["outdated"] += 1
            key = entry["update_type"] or entry["status"]
            by_type[key] = by_type.get(key, 0) + 1
        elif entry["status"] == "latest":
            counts["up_to_date"] += 1
        counts["held"] += pkg.held
        counts["ignored"] += pkg.ignored
        counts["conflicts"] += pkg.has_conflicts() or pkg.conflict_held

    return {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "summary": {
            "total": len(rows),
            "errors": len(errors),
            "by_update_type": by_type,
            **counts,
        },
        "python": {"version": python[0], "source": python[1]},
        "files": list(files.values()),
        "packages": packages,
        "errors": errors,
    }


_GROUP_ORDER = ["major", "year", "minor", "month", "patch", "new", "downgrade"]
_GROUP_TITLES = {
    "major": "Major updates",
    "year": "Year updates (calver)",
    "minor": "Minor updates",
    "month": "Month updates (calver)",
    "patch": "Patch updates",
    "new": "Newly pinned",
    "downgrade": "Downgrades (declared version unusable)",
}


def _cell(text: str) -> str:
    """Escape *text* for a Markdown table cell."""
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


_UNSAFE_URL_CHARS = re.compile(r"[\x00-\x20\x7f()<>\[\]|`\\\"]")


def _safe_url(url: str) -> Optional[str]:
    """Return *url* made safe for a Markdown link target, or ``None``.

    Only ``http(s)`` URLs survive (``javascript:`` / ``data:`` links would be
    clickable in a PR body); characters that could end the link or inject
    markup or HTML are percent-encoded.
    """
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    return _UNSAFE_URL_CHARS.sub(lambda m: f"%{ord(m.group()):02X}", url)


def _links_cell(row: Row) -> str:
    names = {
        "changelog": "changelog",
        "release_notes": "release notes",
        "homepage": "homepage",
    }
    parts = []
    for k in names:
        url = _safe_url(row.links[k]) if k in row.links else None
        if url:
            parts.append(f"[{names[k]}]({url})")
    parts.append(f"[PyPI](https://pypi.org/project/{row.pkg.name}/)")
    return " · ".join(parts)


def _table(header: Sequence[str], lines: List[List[str]]) -> List[str]:
    out = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(" --- " for _ in header) + "|",
    ]
    out += ["| " + " | ".join(_cell(c) for c in ln) + " |" for ln in lines]
    return out + [""]


def render_markdown(
    rows: Sequence[Row],
    *,
    title: str,
    python: Tuple[Optional[str], str],
    change_rows: Optional[Sequence[Row]] = None,
    skipped: Sequence[str] = (),
) -> str:
    """Render a PR-body / CI-summary Markdown report.

    Args:
        rows: Every checked package (for the held/conflict/failure sections).
        title: Heading of the report.
        python: Interpreter ``(version, source)`` the check targeted.
        change_rows: ``update`` only: the rows actually changed, each to
            ``row.new_version``; default derives changes from *rows*.
        skipped: Extra lines for the "Skipped" section (e.g. ``--max-update``).
    """
    multi = multi_file(rows)
    changes_only = change_rows is not None
    changes = (
        list(change_rows or [])
        if changes_only
        else [
            r
            for r in rows
            if (
                not (r.failed or r.pkg.held or r.pkg.ignored)
                and (
                    r.pkg.has_update()
                    or r.pkg.requires_downgrade
                    or (r.pkg.recommended_version and not r.pkg.current_version)
                )
            )
        ]
    )
    groups: Dict[str, List[Row]] = {}
    for r in changes:
        groups.setdefault(r.label, []).append(r)

    out = [f"## {title}", ""]
    total = len(rows)
    target = (
        f"target Python {python[0]} ({python[1]})"
        if python[0]
        else "target Python: running interpreter"
    )
    out.append(
        f"**{len(changes)}** of {total} package(s) "
        f"{'changed' if changes_only else 'have updates'} · {target}"
    )
    out.append("")

    header = [
        "Package",
        "Current",
        "Recommended" if not changes_only else "New",
        "Released",
        "Links",
    ]
    if multi:
        header.append("Source")
    for label in _GROUP_ORDER + sorted(set(groups) - set(_GROUP_ORDER)):
        if label not in groups:
            continue
        out.append(f"### {_GROUP_TITLES.get(label, label.capitalize() + ' updates')}")
        out.append("")
        lines = []
        for r in groups[label]:
            age = (
                age_text(r.pkg) if r.new_version == r.pkg.recommended_version else None
            )
            line = [
                f"`{r.pkg.name}`",
                r.pkg.current_version or "-",
                r.new_version or "-",
                (age or "-").replace("released ", ""),
                _links_cell(r),
            ]
            if multi:
                line.append(source_cell(r))
            lines.append(line)
        out += _table(header, lines)

    def bullets(heading: str, items: List[str]) -> None:
        if items:
            out.extend([f"### {heading}", ""] + [f"- {i}" for i in items] + [""])

    pkgs = [r.pkg for r in rows]
    bullets(
        "Held by policy",
        [f"`{p.name}` stays on {p.current_version}" for p in pkgs if p.held]
        + [f"`{p.name}` ignored" for p in pkgs if p.ignored],
    )
    bullets(
        "Cooldown",
        [
            f"`{p.name}`: {p.cooldown_skipped} withheld (younger than min_age)"
            for p in pkgs
            if p.cooldown_skipped
        ],
    )
    bullets(
        "Major updates available (not applied)",
        [f"`{p.name}`: {p.major_available}" for p in pkgs if p.major_available],
    )
    bullets(
        "Conflicts",
        [
            f"`{r.pkg.name}`: {c.to_display_string()}"
            for r in rows
            for c in r.pkg.conflicts
        ],
    )
    bullets("Skipped", list(skipped))
    bullets(
        "Lookup failures",
        [
            f"`{r.pkg.name}` could not be checked ({source_cell(r)})"
            for r in rows
            if r.failed
        ],
    )
    if (
        not changes
        and not any(p.held or p.ignored or p.conflicts or p.conflict_held for p in pkgs)
        and not any(r.failed for r in rows)
    ):
        out.extend(["All packages are up to date.", ""])
    return "\n".join(out).rstrip("\n") + "\n"


def display_resolution_summary(
    result: ResolutionResult, *, stderr: bool = False
) -> None:
    """Print a human-readable summary of the conflict resolution process.

    Args:
        result: The `ResolutionResult` from the dependency analyzer.
        stderr: Render to stderr instead of stdout, for formats whose payload
            owns stdout.

    Example::

        Resolution Summary:
        ==================================================
        Total packages: 15
        Packages with conflicts: 2
        Packages changed: 3
        Converged: Yes (5 iterations)

        Version changes:
          • flask: 3.0.0 → 2.3.3 (downgraded)
          • werkzeug: 3.0.1 → 2.3.7 (constrained)
    """
    console = get_raw_console(stderr=stderr)
    console.print("\n[bold]Resolution Summary:[/bold]")
    console.print("=" * 50)
    console.print(f"Total packages: {result.total_packages}")
    console.print(f"Packages with conflicts: {result.packages_with_conflicts}")

    changed = result.get_changed_packages()
    console.print(f"Packages changed: {len(changed)}")

    convergence_status = (
        f"Yes ({result.iterations_used} iterations)"
        if result.converged
        else f"No (stopped after {result.iterations_used} iterations)"
    )
    if result.converged and result.packages_with_conflicts:
        convergence_status += f"; {result.packages_with_conflicts} still in conflict"
    console.print(f"Converged: {convergence_status}")

    if changed:
        console.print("\n[bold]Version changes:[/bold]")
        for pkg_resolution in changed:
            console.print(
                f"  • {escape(str(pkg_resolution.name))}: "
                f"{escape(str(pkg_resolution.original))} → "
                f"{escape(str(pkg_resolution.resolved))} "
                f"({pkg_resolution.status.value})"
            )

    console.print("")
