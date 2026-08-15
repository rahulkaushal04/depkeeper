"""Tests for the requirements update writer (``_apply_updates``).

Primary purpose: guard against regression C1 — requirements pulled in via
``-r`` includes retain the *included* file's line numbers, so matching on
line number alone rewrites unrelated lines in the parent file, destroying the
``-r`` directive and corrupting the dependency graph.
"""

from __future__ import annotations

import codecs
import sys
from pathlib import Path
from typing import List, Tuple
from unittest.mock import patch

import pytest

from depkeeper.commands import update as update_module
from depkeeper.commands.update import (
    _apply_updates,
    _resolve_affected_files,
)
from depkeeper.core.parser import RequirementsParser
from depkeeper.exceptions import DepKeeperError, FileOperationError
from depkeeper.models import Package, Requirement


def _update_tuple(
    req: Requirement, new_version: str
) -> Tuple[Requirement, Package, str]:
    pkg = Package(
        name=req.name,
        current_version=req.specs[0][1] if req.specs else None,
        recommended_version=new_version,
    )
    return (req, pkg, new_version)


def test_update_simple_flat_file(tmp_path: Path) -> None:
    """Baseline: a single flat file updates in place, preserving other lines."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text(
        "click==8.0.0\n# keep me\nrich==13.0.0\n", encoding="utf-8"
    )

    reqs = RequirementsParser().parse_file(req_file)
    click = next(r for r in reqs if r.name == "click")

    _apply_updates(req_file, reqs, [_update_tuple(click, "8.1.7")])

    assert req_file.read_text(encoding="utf-8") == (
        "click==8.1.7\n# keep me\nrich==13.0.0\n"
    )


def test_include_directive_not_overwritten(tmp_path: Path) -> None:
    """C1 regression: updating an included package must not clobber the parent.

    Reproduces the exact audit scenario:
      requirements.txt -> ``-r base.txt`` / ``# comment`` / ``rich==13.0.0``
      base.txt         -> ``click==8.0.0``
    Updating ``click`` must rewrite base.txt only and leave the ``-r`` intact.
    """
    base = tmp_path / "base.txt"
    base.write_text("click==8.0.0\n", encoding="utf-8")

    root = tmp_path / "requirements.txt"
    root.write_text(
        "-r base.txt\n# comment line\nrich==13.0.0\n", encoding="utf-8"
    )

    reqs = RequirementsParser().parse_file(root)
    click = next(r for r in reqs if r.name == "click")

    _apply_updates(root, reqs, [_update_tuple(click, "8.1.7")])

    # The parent file is untouched — the -r directive survives.
    assert root.read_text(encoding="utf-8") == (
        "-r base.txt\n# comment line\nrich==13.0.0\n"
    )
    # The included file received the update.
    assert base.read_text(encoding="utf-8") == "click==8.1.7\n"


def test_updates_span_parent_and_included_file(tmp_path: Path) -> None:
    """Updates targeting both files each land in the correct file."""
    base = tmp_path / "base.txt"
    base.write_text("click==8.0.0\n", encoding="utf-8")

    root = tmp_path / "requirements.txt"
    root.write_text("-r base.txt\nrich==13.0.0\n", encoding="utf-8")

    reqs = RequirementsParser().parse_file(root)
    click = next(r for r in reqs if r.name == "click")
    rich = next(r for r in reqs if r.name == "rich")

    _apply_updates(
        root,
        reqs,
        [_update_tuple(click, "8.1.7"), _update_tuple(rich, "13.7.0")],
    )

    assert base.read_text(encoding="utf-8") == "click==8.1.7\n"
    assert root.read_text(encoding="utf-8") == "-r base.txt\nrich==13.7.0\n"


def test_resolve_affected_files_includes_all_touched_files(tmp_path: Path) -> None:
    """Backups must cover both the parent and any included files updated."""
    base = tmp_path / "base.txt"
    base.write_text("click==8.0.0\n", encoding="utf-8")

    root = tmp_path / "requirements.txt"
    root.write_text("-r base.txt\nrich==13.0.0\n", encoding="utf-8")

    reqs = RequirementsParser().parse_file(root)
    click = next(r for r in reqs if r.name == "click")
    rich = next(r for r in reqs if r.name == "rich")

    affected = _resolve_affected_files(
        root, [_update_tuple(click, "8.1.7"), _update_tuple(rich, "13.7.0")]
    )

    assert affected == {base.resolve(), root.resolve()}


def test_only_files_with_updates_are_written(tmp_path: Path) -> None:
    """An included file with no pending update is left byte-for-byte intact."""
    base = tmp_path / "base.txt"
    original_base = "click==8.0.0\n"
    base.write_text(original_base, encoding="utf-8")

    root = tmp_path / "requirements.txt"
    root.write_text("-r base.txt\nrich==13.0.0\n", encoding="utf-8")

    reqs = RequirementsParser().parse_file(root)
    rich = next(r for r in reqs if r.name == "rich")

    affected = _resolve_affected_files(root, [_update_tuple(rich, "13.7.0")])

    assert affected == {root.resolve()}

    _apply_updates(root, reqs, [_update_tuple(rich, "13.7.0")])

    assert base.read_text(encoding="utf-8") == original_base
    assert root.read_text(encoding="utf-8") == "-r base.txt\nrich==13.7.0\n"


def test_missing_provenance_falls_back_to_primary_file(tmp_path: Path) -> None:
    """Requirements without source_file are written to the primary file."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("click==8.0.0\n", encoding="utf-8")

    # Simulate a requirement built without provenance (e.g. via parse_string).
    req = Requirement(
        name="click", specs=[("==", "8.0.0")], line_number=1, source_file=None
    )

    _apply_updates(req_file, [req], [_update_tuple(req, "8.1.7")])

    assert req_file.read_text(encoding="utf-8") == "click==8.1.7\n"


def test_hashed_requirement_update_refused_by_default(tmp_path: Path) -> None:
    """C3 regression: updates must not silently strip --hash pins by default."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text(
        "requests==2.28.0 --hash=sha256:abc123\n", encoding="utf-8"
    )

    reqs = RequirementsParser().parse_file(req_file)
    requests_req = next(r for r in reqs if r.name == "requests")

    with pytest.raises(DepKeeperError, match="--allow-hash-removal"):
        _apply_updates(req_file, reqs, [_update_tuple(requests_req, "2.31.0")])

    # File remains unchanged when the update is rejected.
    assert req_file.read_text(encoding="utf-8") == (
        "requests==2.28.0 --hash=sha256:abc123\n"
    )


def test_hashed_requirement_update_allowed_with_opt_in(tmp_path: Path) -> None:
    """Explicit opt-in permits update and removes stale hash pins."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text(
        "requests==2.28.0 --hash=sha256:abc123\n", encoding="utf-8"
    )

    reqs = RequirementsParser().parse_file(req_file)
    requests_req = next(r for r in reqs if r.name == "requests")

    _apply_updates(
        req_file,
        reqs,
        [_update_tuple(requests_req, "2.31.0")],
        allow_hash_removal=True,
    )

    assert req_file.read_text(encoding="utf-8") == "requests==2.31.0\n"


def test_bom_preserved_when_first_line_updated(tmp_path: Path) -> None:
    """M3 regression: rewriting line 1 must keep the file's UTF-8 BOM."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_bytes("click==8.0.0\nrich==13.0.0\n".encode("utf-8-sig"))

    reqs = RequirementsParser().parse_file(req_file)
    click = next(r for r in reqs if r.name == "click")

    _apply_updates(req_file, reqs, [_update_tuple(click, "8.1.7")])

    assert req_file.read_bytes().startswith(codecs.BOM_UTF8)
    assert req_file.read_text(encoding="utf-8-sig") == (
        "click==8.1.7\nrich==13.0.0\n"
    )


def test_bom_preserved_when_later_line_updated(tmp_path: Path) -> None:
    """A BOM must not be duplicated or dropped when line 1 is untouched."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_bytes("click==8.0.0\nrich==13.0.0\n".encode("utf-8-sig"))

    reqs = RequirementsParser().parse_file(req_file)
    rich = next(r for r in reqs if r.name == "rich")

    _apply_updates(req_file, reqs, [_update_tuple(rich, "13.7.0")])

    raw = req_file.read_bytes()
    assert raw.startswith(codecs.BOM_UTF8)
    assert not raw[len(codecs.BOM_UTF8):].startswith(codecs.BOM_UTF8)
    assert req_file.read_text(encoding="utf-8-sig") == (
        "click==8.0.0\nrich==13.7.0\n"
    )


def test_bom_not_added_to_plain_utf8_file(tmp_path: Path) -> None:
    """Files without a BOM must never gain one."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_bytes("click==8.0.0\n".encode("utf-8"))

    reqs = RequirementsParser().parse_file(req_file)
    click = next(r for r in reqs if r.name == "click")

    _apply_updates(req_file, reqs, [_update_tuple(click, "8.1.7")])

    assert not req_file.read_bytes().startswith(codecs.BOM_UTF8)
    assert req_file.read_text(encoding="utf-8") == "click==8.1.7\n"


def test_bom_preserved_across_included_files(tmp_path: Path) -> None:
    """Each affected file keeps its own encoding signature independently."""
    base = tmp_path / "base.txt"
    base.write_bytes("click==8.0.0\n".encode("utf-8-sig"))

    root = tmp_path / "requirements.txt"
    root.write_bytes("-r base.txt\nrich==13.0.0\n".encode("utf-8"))

    reqs = RequirementsParser().parse_file(root)
    click = next(r for r in reqs if r.name == "click")
    rich = next(r for r in reqs if r.name == "rich")

    _apply_updates(
        root,
        reqs,
        [_update_tuple(click, "8.1.7"), _update_tuple(rich, "13.7.0")],
    )

    assert base.read_bytes().startswith(codecs.BOM_UTF8)
    assert base.read_text(encoding="utf-8-sig") == "click==8.1.7\n"
    assert not root.read_bytes().startswith(codecs.BOM_UTF8)
    assert root.read_text(encoding="utf-8") == "-r base.txt\nrich==13.7.0\n"


# ---------------------------------------------------------------------------
# M5 — declared version ranges must survive an update
# ---------------------------------------------------------------------------


def test_range_upper_bound_is_preserved(tmp_path: Path) -> None:
    """M5 regression: ``celery[redis]>=5.0,<6.0`` must keep its ``<6.0`` cap."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("celery[redis]>=5.0,<6.0\n", encoding="utf-8")

    reqs = RequirementsParser().parse_file(req_file)
    celery = next(r for r in reqs if r.name == "celery")

    _apply_updates(req_file, reqs, [_update_tuple(celery, "5.5.3")])

    assert req_file.read_text(encoding="utf-8") == "celery[redis]>=5.5.3,<6.0\n"


def test_exclusions_markers_and_comments_survive(tmp_path: Path) -> None:
    """A full-featured range line keeps every declared element."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text(
        'django[bcrypt]>=3.2,<5.0,!=4.0 ; python_version >= "3.8"  '
        "# Avoid Django 4.0\n",
        encoding="utf-8",
    )

    reqs = RequirementsParser().parse_file(req_file)
    django = next(r for r in reqs if r.name == "django")

    _apply_updates(req_file, reqs, [_update_tuple(django, "4.2.11")])

    assert req_file.read_text(encoding="utf-8") == (
        'django[bcrypt]>=4.2.11,<5.0,!=4.0 ; python_version >= "3.8"  '
        "# Avoid Django 4.0\n"
    )


def test_compatible_release_keeps_its_shape(tmp_path: Path) -> None:
    """``~=`` stays a compatible-release specifier at the author's precision."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("flask~=2.0\n", encoding="utf-8")

    reqs = RequirementsParser().parse_file(req_file)
    flask = next(r for r in reqs if r.name == "flask")

    _apply_updates(req_file, reqs, [_update_tuple(flask, "2.3.3")])

    assert req_file.read_text(encoding="utf-8") == "flask~=2.3\n"


def test_exact_pin_is_still_repinned(tmp_path: Path) -> None:
    """Guard: application-style ``==`` pins keep behaving as before."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("urllib3==1.26.0\n", encoding="utf-8")

    reqs = RequirementsParser().parse_file(req_file)
    urllib3 = next(r for r in reqs if r.name == "urllib3")

    _apply_updates(req_file, reqs, [_update_tuple(urllib3, "1.26.18")])

    assert req_file.read_text(encoding="utf-8") == "urllib3==1.26.18\n"


def test_pin_mode_collapses_range(tmp_path: Path) -> None:
    """``--pin`` opts into the hard-pin behaviour explicitly."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("celery[redis]>=5.0,<6.0\n", encoding="utf-8")

    reqs = RequirementsParser().parse_file(req_file)
    celery = next(r for r in reqs if r.name == "celery")

    _apply_updates(req_file, reqs, [_update_tuple(celery, "5.5.3")], pin=True)

    assert req_file.read_text(encoding="utf-8") == "celery[redis]==5.5.3\n"


def test_unsatisfiable_target_is_rejected(tmp_path: Path) -> None:
    """The writer refuses to emit a self-contradictory requirement line."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("flask>=2.0,<2.3\n", encoding="utf-8")

    reqs = RequirementsParser().parse_file(req_file)
    flask = next(r for r in reqs if r.name == "flask")

    with pytest.raises(DepKeeperError, match="excludes that version"):
        _apply_updates(req_file, reqs, [_update_tuple(flask, "2.3.3")])

    assert req_file.read_text(encoding="utf-8") == "flask>=2.0,<2.3\n"


def test_update_is_idempotent(tmp_path: Path) -> None:
    """Re-parsing and re-applying the same target must not churn the file."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("celery>=5.0,<6.0,!=5.2.0\n", encoding="utf-8")

    for _ in range(2):
        reqs = RequirementsParser().parse_file(req_file)
        celery = next(r for r in reqs if r.name == "celery")
        _apply_updates(req_file, reqs, [_update_tuple(celery, "5.5.3")])

    assert req_file.read_text(encoding="utf-8") == "celery>=5.5.3,<6.0,!=5.2.0\n"


# ---------------------------------------------------------------------------
# M7 — writes must be atomic, all-or-nothing, and byte-faithful
# ---------------------------------------------------------------------------


def test_write_failure_leaves_original_file_intact(tmp_path: Path) -> None:
    """M7 regression: a failed write must not truncate the requirements file.

    The previous implementation used ``open(file, "w")`` + ``writelines()``,
    so any failure between truncation and flush destroyed the file.
    """
    req_file = tmp_path / "requirements.txt"
    req_file.write_bytes(b"click==8.0.0\n# keep me\nrich==13.0.0\n")

    reqs = RequirementsParser().parse_file(req_file)
    click = next(r for r in reqs if r.name == "click")

    with patch.object(Path, "replace", side_effect=OSError("ENOSPC")):
        with pytest.raises(DepKeeperError, match="Failed to write"):
            _apply_updates(req_file, reqs, [_update_tuple(click, "8.1.7")])

    assert req_file.read_bytes() == b"click==8.0.0\n# keep me\nrich==13.0.0\n"


def test_no_temp_files_left_behind(tmp_path: Path) -> None:
    """The atomic write must clean up after itself."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("click==8.0.0\n", encoding="utf-8")

    reqs = RequirementsParser().parse_file(req_file)
    click = next(r for r in reqs if r.name == "click")

    _apply_updates(req_file, reqs, [_update_tuple(click, "8.1.7")])

    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_multi_file_write_failure_rolls_back(tmp_path: Path) -> None:
    """A partial multi-file update must be rolled back, not left half-applied."""
    base = tmp_path / "base.txt"
    base.write_bytes(b"click==8.0.0\n")

    root = tmp_path / "requirements.txt"
    root.write_bytes(b"-r base.txt\nrich==13.0.0\n")

    reqs = RequirementsParser().parse_file(root)
    click = next(r for r in reqs if r.name == "click")
    rich = next(r for r in reqs if r.name == "rich")

    real_write = update_module.safe_write_file
    calls: List[Path] = []

    def flaky_write(file_path, content, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(Path(file_path))
        # Fail on the second file, after the first has already been committed.
        if len(calls) == 2:
            raise FileOperationError(
                "simulated failure",
                file_path=str(file_path),
                operation="write",
            )
        return real_write(file_path, content, **kwargs)

    with patch.object(update_module, "safe_write_file", side_effect=flaky_write):
        with pytest.raises(DepKeeperError, match="Failed to write"):
            _apply_updates(
                root,
                reqs,
                [_update_tuple(click, "8.1.7"), _update_tuple(rich, "13.7.0")],
            )

    # Both files are back to their original content.
    assert base.read_bytes() == b"click==8.0.0\n"
    assert root.read_bytes() == b"-r base.txt\nrich==13.0.0\n"


def test_nothing_written_when_one_line_is_rejected(tmp_path: Path) -> None:
    """Rendering is all-or-nothing: a rejected line aborts before any write."""
    base = tmp_path / "base.txt"
    base.write_bytes(b"click==8.0.0\n")

    root = tmp_path / "requirements.txt"
    root.write_bytes(b"-r base.txt\nflask>=2.0,<2.3\n")

    reqs = RequirementsParser().parse_file(root)
    click = next(r for r in reqs if r.name == "click")
    flask = next(r for r in reqs if r.name == "flask")

    with pytest.raises(DepKeeperError, match="excludes that version"):
        _apply_updates(
            root,
            reqs,
            [_update_tuple(click, "8.1.7"), _update_tuple(flask, "2.3.3")],
        )

    # The valid update in base.txt must not have been committed either.
    assert base.read_bytes() == b"click==8.0.0\n"
    assert root.read_bytes() == b"-r base.txt\nflask>=2.0,<2.3\n"


def test_crlf_line_endings_preserved(tmp_path: Path) -> None:
    """m8 regression: a CRLF file stays CRLF on every platform."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_bytes(b"click==8.0.0\r\n# keep me\r\nrich==13.0.0\r\n")

    reqs = RequirementsParser().parse_file(req_file)
    click = next(r for r in reqs if r.name == "click")

    _apply_updates(req_file, reqs, [_update_tuple(click, "8.1.7")])

    assert req_file.read_bytes() == b"click==8.1.7\r\n# keep me\r\nrich==13.0.0\r\n"


def test_lf_line_endings_preserved(tmp_path: Path) -> None:
    """m8 regression: an LF file must not be converted to CRLF on Windows."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_bytes(b"click==8.0.0\n# keep me\nrich==13.0.0\n")

    reqs = RequirementsParser().parse_file(req_file)
    click = next(r for r in reqs if r.name == "click")

    _apply_updates(req_file, reqs, [_update_tuple(click, "8.1.7")])

    assert req_file.read_bytes() == b"click==8.1.7\n# keep me\nrich==13.0.0\n"


def test_missing_trailing_newline_is_not_added(tmp_path: Path) -> None:
    """A file whose last line has no terminator keeps that shape."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_bytes(b"click==8.0.0")

    reqs = RequirementsParser().parse_file(req_file)
    click = next(r for r in reqs if r.name == "click")

    _apply_updates(req_file, reqs, [_update_tuple(click, "8.1.7")])

    assert req_file.read_bytes() == b"click==8.1.7"


def test_bom_and_crlf_preserved_together(tmp_path: Path) -> None:
    """A Windows-authored (BOM + CRLF) file survives byte-for-byte."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_bytes(
        codecs.BOM_UTF8 + b"click==8.0.0\r\nrich==13.0.0\r\n"
    )

    reqs = RequirementsParser().parse_file(req_file)
    click = next(r for r in reqs if r.name == "click")

    _apply_updates(req_file, reqs, [_update_tuple(click, "8.1.7")])

    assert req_file.read_bytes() == (
        codecs.BOM_UTF8 + b"click==8.1.7\r\nrich==13.0.0\r\n"
    )


def test_writes_go_through_the_atomic_helper(tmp_path: Path) -> None:
    """The writer must not bypass ``safe_write_file``."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("click==8.0.0\n", encoding="utf-8")

    reqs = RequirementsParser().parse_file(req_file)
    click = next(r for r in reqs if r.name == "click")

    with patch.object(
        update_module, "safe_write_file", wraps=update_module.safe_write_file
    ) as spy:
        _apply_updates(req_file, reqs, [_update_tuple(click, "8.1.7")])

    assert spy.call_count == 1
    assert spy.call_args.kwargs["create_backup"] is False
    assert req_file.read_text(encoding="utf-8") == "click==8.1.7\n"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes only")
def test_file_permissions_preserved(tmp_path: Path) -> None:
    """m6 regression: an update must not tighten the file's mode to 0600."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("click==8.0.0\n", encoding="utf-8")
    req_file.chmod(0o644)

    reqs = RequirementsParser().parse_file(req_file)
    click = next(r for r in reqs if r.name == "click")

    _apply_updates(req_file, reqs, [_update_tuple(click, "8.1.7")])

    assert (req_file.stat().st_mode & 0o777) == 0o644
