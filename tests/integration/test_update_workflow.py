"""End-to-end ``check`` → ``update`` workflows against realistic projects.

Each test drives the pipeline exactly as the ``update`` command does::

    parse file -> check versions -> resolve conflicts -> select updates -> write

and then asserts on the resulting file contents. Package metadata comes from
:data:`tests.support.pypi.ECOSYSTEM`, so the version arithmetic is performed
against release histories that really exist.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from depkeeper.commands.update import (
    _apply_updates,
    _find_updates,
    _resolve_affected_files,
)
from depkeeper.core.checker import VersionChecker
from depkeeper.core.dependency_analyzer import DependencyAnalyzer
from depkeeper.core.parser import RequirementsParser
from depkeeper.exceptions import DepKeeperError
from depkeeper.models import Package, Requirement
from tests.support import datasets
from tests.support.pypi import FakePyPIStore, package_data, store_for

Update = Tuple[Requirement, Package, str]


# ---------------------------------------------------------------------------
# Pipeline driver
# ---------------------------------------------------------------------------


async def run_update(
    path: Path,
    store: FakePyPIStore,
    *,
    resolve_conflicts: bool = True,
    pin: bool = False,
    allow_hash_removal: bool = False,
    apply: bool = True,
) -> Tuple[List[Package], List[Update]]:
    """Run the full update pipeline over *path* and optionally write the result.

    Args:
        path: Requirements file to process.
        store: In-memory PyPI metadata source.
        resolve_conflicts: Run the dependency analyzer, as ``update`` does
            unless ``check_conflicts`` is disabled.
        pin: Collapse ranges to exact pins (``--pin``).
        allow_hash_removal: Permit rewriting hash-pinned lines.
        apply: Write the selected updates back to disk.

    Returns:
        The checked packages and the updates that were selected.
    """
    requirements = RequirementsParser().parse_file(path)
    packages = await VersionChecker(data_store=store).check_packages(requirements)

    if resolve_conflicts:
        await DependencyAnalyzer(data_store=store).resolve_and_annotate_conflicts(
            packages
        )

    updates = _find_updates(packages, requirements, pin=pin)

    if apply and updates:
        _apply_updates(
            path,
            requirements,
            updates,
            allow_hash_removal=allow_hash_removal,
            pin=pin,
        )

    return packages, updates


def applied_versions(updates: List[Update]) -> Dict[str, str]:
    """Map package name to the version that was written."""
    return {req.name: version for req, _pkg, version in updates}


# ---------------------------------------------------------------------------
# Pinned application file
# ---------------------------------------------------------------------------


class TestPinnedApplicationUpgrade:
    """The common case: a pip-compile style file of exact pins."""

    @pytest.fixture
    def project(self, tmp_path: Path) -> Path:
        path = tmp_path / "requirements.txt"
        path.write_text(datasets.PINNED_APPLICATION, encoding="utf-8")
        return path

    @pytest.fixture
    def store(self) -> FakePyPIStore:
        return store_for("requests", "urllib3", "certifi", "idna")

    async def test_pins_advance_within_their_major_and_nothing_else_moves(
        self, project: Path, store: FakePyPIStore
    ) -> None:
        """Comments, ordering and untouched lines must survive byte-for-byte.

        Two lines deliberately do *not* move, and both matter:

        - ``urllib3`` is on 1.26.18 while 2.2.2 exists. Crossing a major
          boundary is never done implicitly, because 2.x removed APIs.
        - ``certifi`` uses calendar versioning, so 2023.7.22 -> 2024.7.4 is a
          *major* change by PEP 440 arithmetic and is held back by the same
          rule. This is a real and frequently surprising consequence of the
          major-boundary policy, so it is pinned here rather than left to be
          rediscovered.
        """
        await run_update(project, store)

        assert project.read_text(encoding="utf-8") == (
            "# Runtime dependencies for the payments service.\n"
            "# Regenerate with: pip-compile requirements.in\n"
            "\n"
            "certifi==2023.7.22\n"
            "charset-normalizer==3.3.2\n"
            "idna==3.7\n"
            "requests==2.32.3\n"
            "urllib3==1.26.18\n"
        )

    async def test_a_package_missing_from_the_index_does_not_block_the_others(
        self, project: Path, store: FakePyPIStore
    ) -> None:
        """``charset-normalizer`` is deliberately absent from the fake index,
        standing in for a private or yanked distribution. It must degrade to an
        unavailable stub — no known latest, recommendation held at the declared
        version — while every other pin still advances.
        """
        packages, updates = await run_update(project, store)

        stub = next(p for p in packages if p.name == "charset-normalizer")
        assert stub.latest_version is None
        assert stub.recommended_version == "3.3.2"
        assert stub.has_update() is False
        assert "charset-normalizer" not in applied_versions(updates)
        assert applied_versions(updates)["requests"] == "2.32.3"

    async def test_a_second_run_finds_nothing_to_do(
        self, project: Path, store: FakePyPIStore
    ) -> None:
        """Convergence: re-running must not churn the file.

        A non-converging rewrite produces a diff on every CI run, which trains
        reviewers to ignore dependency changes entirely.
        """
        await run_update(project, store)
        after_first = project.read_text(encoding="utf-8")

        _packages, updates = await run_update(project, store)

        assert updates == []
        assert project.read_text(encoding="utf-8") == after_first


# ---------------------------------------------------------------------------
# Library file with declared ranges
# ---------------------------------------------------------------------------


class TestLibraryRangePreservation:
    """Regression M5, end to end: a library's compatibility contract survives."""

    @pytest.fixture
    def project(self, tmp_path: Path) -> Path:
        path = tmp_path / "requirements.txt"
        path.write_text(datasets.LIBRARY_RANGES, encoding="utf-8")
        return path

    @pytest.fixture
    def store(self) -> FakePyPIStore:
        return store_for("flask", "requests", "celery", "sqlalchemy", "django")

    async def test_only_the_floor_moves_and_every_cap_survives(
        self, project: Path, store: FakePyPIStore
    ) -> None:
        """Each line exercises a different retained construct.

        - ``flask>=2.2,<3.0`` keeps its cap, so 3.0.3 is never proposed.
        - ``celery[redis]>=5.0,<6.0`` keeps both the extra and the cap.
        - ``sqlalchemy~=2.0`` already admits 2.0.30, so the line is left alone
          rather than being narrowed to ``~=2.0.30``.
        - ``django>=3.2,<5.0,!=4.0.*`` keeps the cap, the exclusion and the
          explanatory comment. Its floor only reaches 3.2.25 because the
          declared ``>=3.2`` is read as "currently on 3.2", and depkeeper does
          not cross the 3.x -> 4.x boundary on its own.
        """
        await run_update(project, store)

        assert project.read_text(encoding="utf-8") == (
            "# Library dependencies. Keep these as ranges - pinning here would force\n"
            "# every downstream application onto our exact versions.\n"
            "\n"
            "flask>=2.3.3,<3.0\n"
            "requests>=2.32.3,<3\n"
            "celery[redis]>=5.4.0,<6.0\n"
            "sqlalchemy~=2.0\n"
            "django>=3.2.25,<5.0,!=4.0.*  "
            "# 4.0.x is EOL and has an open CVE\n"
        )

    async def test_pin_mode_collapses_every_range(
        self, project: Path, store: FakePyPIStore
    ) -> None:
        """``--pin`` is destructive by design, and must therefore be explicit."""
        await run_update(project, store, pin=True)

        content = project.read_text(encoding="utf-8")

        assert "flask==2.3.3" in content
        assert "celery[redis]==5.4.0" in content
        assert "sqlalchemy==2.0.30" in content
        assert "<3.0" not in content
        assert "!=4.0.*" not in content

    async def test_the_checker_never_proposes_a_version_the_file_forbids(
        self, project: Path, store: FakePyPIStore
    ) -> None:
        """The recommendation itself is capped, not merely filtered later.

        If the checker proposed 3.0.3 for ``flask>=2.2,<3.0``, the summary shown
        to the user would advertise an upgrade the writer then silently refuses.
        """
        packages, _updates = await run_update(project, store, apply=False)

        flask = next(p for p in packages if p.name == "flask")
        assert flask.latest_version == "3.0.3"
        assert flask.recommended_version == "2.3.3"


# ---------------------------------------------------------------------------
# Layered multi-file project
# ---------------------------------------------------------------------------


class TestLayeredProjectRouting:
    """Regression C1, end to end: each update lands in the file that declared it."""

    @pytest.fixture
    def project(self, tmp_path: Path) -> Dict[str, Path]:
        return datasets.write_project(tmp_path, datasets.LAYERED_PROJECT)

    @pytest.fixture
    def store(self) -> FakePyPIStore:
        return FakePyPIStore(
            {
                "requests": package_data("requests"),
                "urllib3": package_data("urllib3"),
                "flask": package_data("flask"),
                "gunicorn": package_data("gunicorn", ["21.2.0", "22.0.0", "23.0.0"]),
            }
        )

    async def test_updates_are_written_to_the_declaring_file(
        self, project: Dict[str, Path], store: FakePyPIStore
    ) -> None:
        """``requests`` is declared in base.txt but reached through prod.txt.

        Matching on line number alone would rewrite prod.txt line 1 — the ``-r``
        directive — and silently detach base.txt from the dependency graph.

        ``gunicorn==22.0.0`` stays put: 23.0.0 exists but is a major bump, which
        doubles as proof that the routing logic does not force a write.
        """
        await run_update(project["requirements/prod.txt"], store)

        assert project["requirements/base.txt"].read_text(encoding="utf-8") == (
            "# Shared by every environment.\n"
            "requests>=2.32.3\n"
            "urllib3>=1.26.18,<2.0  # 2.x drops the retry kwargs we rely on\n"
        )
        assert project["requirements/prod.txt"].read_text(encoding="utf-8") == (
            "-r base.txt\n"
            "-c ../constraints.txt\n"
            "\n"
            "gunicorn==22.0.0\n"
            "flask>=2.3.3,<3.0\n"
        )

    async def test_the_constraints_file_is_never_rewritten(
        self, project: Dict[str, Path], store: FakePyPIStore
    ) -> None:
        """A ``-c`` file caps transitive dependencies. Treating its entries as
        updatable requirements would turn every cap into a direct dependency
        and defeat the file's purpose.
        """
        before = project["constraints.txt"].read_bytes()

        await run_update(project["requirements/prod.txt"], store)

        assert project["constraints.txt"].read_bytes() == before

    async def test_only_files_with_pending_updates_are_touched(
        self, project: Dict[str, Path], store: FakePyPIStore
    ) -> None:
        """Backups and writes are scoped to the files that actually change."""
        requirements = RequirementsParser().parse_file(
            project["requirements/prod.txt"]
        )
        packages = await VersionChecker(data_store=store).check_packages(requirements)
        updates = _find_updates(packages, requirements)

        affected = _resolve_affected_files(project["requirements/prod.txt"], updates)

        assert affected == {
            project["requirements/base.txt"].resolve(),
            project["requirements/prod.txt"].resolve(),
        }

    async def test_the_editable_checkout_is_never_selected_for_update(
        self, project: Dict[str, Path], store: FakePyPIStore
    ) -> None:
        """Regression C2: dev.txt carries ``-e ../packages/internal-sdk``.

        A direct reference has no PyPI version, so appending one would emit an
        uninstallable line. It must be skipped, and dev.txt left untouched.
        """
        before = project["requirements/dev.txt"].read_bytes()

        _packages, updates = await run_update(project["requirements/dev.txt"], store)

        assert "internal-sdk" not in applied_versions(updates)
        assert project["requirements/dev.txt"].read_bytes() == before


# ---------------------------------------------------------------------------
# Conflict-driven resolution
# ---------------------------------------------------------------------------


class TestConflictDrivenResolution:
    """The version reported to the user must be the version written to disk.

    Regression M10: the resolver's decision was overwritten by an independent
    "compatible alternative" search, so ``check`` advertised one version and
    ``update`` wrote another.
    """

    @pytest.fixture
    def store(self) -> FakePyPIStore:
        # Real edge: Flask 2.3.3 requires Werkzeug>=2.3.7, while 2.2.5 is
        # satisfied by the older Werkzeug the file pins.
        return store_for("flask", "werkzeug", "jinja2", "click")

    async def test_a_capped_dependency_holds_its_dependant_back(
        self, tmp_path: Path, store: FakePyPIStore
    ) -> None:
        """An internal plugin caps Werkzeug below what the newest Flask needs.

        Flask must therefore stop at the release whose own requirement the
        capped Werkzeug still satisfies, rather than being upgraded into a
        broken combination.
        """
        path = tmp_path / "requirements.txt"
        path.write_text(
            "flask>=2.0\nwerkzeug>=2.0,<2.3  # capped by acme-auth\n",
            encoding="utf-8",
        )

        packages, updates = await run_update(path, store)

        werkzeug = next(p for p in packages if p.name == "werkzeug")
        assert werkzeug.recommended_version == "2.2.3"
        assert applied_versions(updates)["werkzeug"] == "2.2.3"
        assert path.read_text(encoding="utf-8") == (
            "flask>=2.2.5\nwerkzeug>=2.2.3,<2.3  # capped by acme-auth\n"
        )

    async def test_the_written_version_matches_the_reported_resolution(
        self, tmp_path: Path, store: FakePyPIStore
    ) -> None:
        """The M10 invariant, asserted across the whole pipeline."""
        path = tmp_path / "requirements.txt"
        path.write_text("flask==2.0.0\nwerkzeug==2.0.3\n", encoding="utf-8")

        requirements = RequirementsParser().parse_file(path)
        packages = await VersionChecker(data_store=store).check_packages(requirements)
        result = await DependencyAnalyzer(
            data_store=store
        ).resolve_and_annotate_conflicts(packages)
        updates = _find_updates(packages, requirements, pin=True)

        written = applied_versions(updates)
        for name, version in written.items():
            assert version == result.resolved_versions[name].resolved

    async def test_resolution_can_be_skipped(
        self, tmp_path: Path, store: FakePyPIStore
    ) -> None:
        """Without conflict checking, each package advances independently.

        This is the ``--no-check-conflicts`` behaviour, kept under test so the
        flag's cost is visible: Werkzeug is capped by the file itself here, and
        nothing else holds Flask back.
        """
        path = tmp_path / "requirements.txt"
        path.write_text("flask>=2.0\nwerkzeug>=2.0,<2.3\n", encoding="utf-8")

        _packages, updates = await run_update(path, store, resolve_conflicts=False)

        assert applied_versions(updates)["flask"] == "2.3.3"
        assert applied_versions(updates)["werkzeug"] == "2.2.3"


# ---------------------------------------------------------------------------
# Duplicate declarations of the same distribution
# ---------------------------------------------------------------------------


class TestDuplicateDeclarationIsolation:
    """The same distribution declared twice via separate ``-r`` includes,
    each with its own constraint, must be resolved independently -- with
    conflict resolution enabled (the default).
    """

    @pytest.fixture
    def store(self) -> FakePyPIStore:
        return store_for("click")

    async def _project(self, tmp_path: Path, include_order: str) -> Path:
        (tmp_path / "base.txt").write_text("click==8.0.4\n", encoding="utf-8")
        (tmp_path / "dev.txt").write_text(
            "click>=8.0.4,<8.1.5\n", encoding="utf-8"
        )
        path = tmp_path / "requirements.txt"
        path.write_text(include_order, encoding="utf-8")
        return path

    async def test_the_unbounded_declaration_is_not_capped_by_the_others_bound(
        self, tmp_path: Path, store: FakePyPIStore
    ) -> None:
        """``base.txt`` has no upper bound and must reach click's true
        highest 8.x release (8.1.7 in the fixture history), not the ceiling
        ``dev.txt`` happens to declare for itself."""
        path = await self._project(tmp_path, "-r base.txt\n-r dev.txt\n")

        await run_update(path, store)

        assert (tmp_path / "base.txt").read_text(encoding="utf-8") == "click==8.1.7\n"
        assert (tmp_path / "dev.txt").read_text(encoding="utf-8") == (
            "click>=8.1.3,<8.1.5\n"
        )

    async def test_the_bounded_declaration_still_gets_its_own_safe_update(
        self, tmp_path: Path, store: FakePyPIStore
    ) -> None:
        """Reversing the include order must not change either outcome, and
        ``dev.txt`` must not be starved of its own legitimate update by a
        target contaminated from ``base.txt``."""
        path = await self._project(tmp_path, "-r dev.txt\n-r base.txt\n")

        await run_update(path, store)

        assert (tmp_path / "base.txt").read_text(encoding="utf-8") == "click==8.1.7\n"
        assert (tmp_path / "dev.txt").read_text(encoding="utf-8") == (
            "click>=8.1.3,<8.1.5\n"
        )


# ---------------------------------------------------------------------------
# Hash-pinned lockfiles
# ---------------------------------------------------------------------------


class TestHashPinnedLockfile:
    """Regression C3: a lockfile's integrity guarantees are not dropped silently."""

    @pytest.fixture
    def project(self, tmp_path: Path) -> Path:
        path = tmp_path / "requirements.txt"
        path.write_text(datasets.HASHED_LOCKFILE, encoding="utf-8")
        return path

    @pytest.fixture
    def store(self) -> FakePyPIStore:
        return store_for("requests", "urllib3", "certifi")

    async def test_updates_are_refused_without_an_explicit_opt_in(
        self, project: Path, store: FakePyPIStore
    ) -> None:
        """Rewriting the version while dropping ``--hash`` silently downgrades a
        verified install to an unverified one. The file must be left intact.
        """
        before = project.read_bytes()

        with pytest.raises(DepKeeperError, match="--allow-hash-removal"):
            await run_update(project, store)

        assert project.read_bytes() == before

    async def test_the_opt_in_updates_and_removes_the_stale_digests(
        self, project: Path, store: FakePyPIStore
    ) -> None:
        """Hashes are version-specific, so keeping them would be worse than
        removing them: pip would reject the install outright.

        Only the line that changes loses its digests. ``certifi`` is held back
        by the major-boundary rule (calendar versioning) and ``urllib3`` by its
        own 1.x pin, so both keep their hashes. The resulting file is therefore
        *partially* hashed, which ``pip install --require-hashes`` rejects — the
        user is expected to regenerate the lockfile, which is why the opt-in
        exists rather than this being the default.
        """
        await run_update(project, store, allow_hash_removal=True)

        assert project.read_text(encoding="utf-8") == (
            "#\n"
            "# This file is autogenerated by pip-compile with Python 3.11\n"
            "# To update, run: pip-compile --generate-hashes requirements.in\n"
            "#\n"
            "certifi==2023.7.22 --hash=sha256:539cc1d13202e33ca466e88b2807e29f"
            "4c13049d6d87031a3c110744495cb082\n"
            "requests==2.32.3\n"
            "urllib3==1.26.18 --hash=sha256:34b97092d7e0a3a8cf7cd10e386f401b37"
            "37364026c45e622aa02903dffe0f07\n"
        )


# ---------------------------------------------------------------------------
# File integrity
# ---------------------------------------------------------------------------


class TestFileIntegrity:
    """Properties of the write itself, independent of which versions were chosen."""

    @pytest.fixture
    def store(self) -> FakePyPIStore:
        return store_for("requests", "urllib3")

    @pytest.mark.parametrize(
        ("line_ending", "trailing_newline"),
        [("\n", True), ("\r\n", True), ("\n", False)],
        ids=["lf", "crlf", "no-final-newline"],
    )
    async def test_line_endings_and_final_newline_are_preserved(
        self,
        tmp_path: Path,
        store: FakePyPIStore,
        line_ending: str,
        trailing_newline: bool,
    ) -> None:
        """A whole-file line-ending flip buries the real change in the diff and,
        on a mixed-platform team, ping-pongs on every run.
        """
        lines = ["# service dependencies", "requests==2.31.0", "urllib3==1.26.5"]
        content = line_ending.join(lines) + (line_ending if trailing_newline else "")
        path = tmp_path / "requirements.txt"
        path.write_bytes(content.encode("utf-8"))

        await run_update(path, store)

        raw = path.read_bytes()
        assert raw.endswith(line_ending.encode()) is trailing_newline
        if line_ending == "\r\n":
            assert b"\r\n" in raw
        else:
            assert b"\r\n" not in raw

    async def test_a_utf8_bom_survives_a_rewrite(
        self, tmp_path: Path, store: FakePyPIStore
    ) -> None:
        """Regression M3: Windows editors write a BOM, and losing it makes the
        file unreadable to tools that assume the signature is present.
        """
        import codecs

        path = tmp_path / "requirements.txt"
        path.write_bytes("requests==2.31.0\nurllib3==1.26.5\n".encode("utf-8-sig"))

        await run_update(path, store)

        raw = path.read_bytes()
        assert raw.startswith(codecs.BOM_UTF8)
        assert not raw[len(codecs.BOM_UTF8):].startswith(codecs.BOM_UTF8)
        assert path.read_text(encoding="utf-8-sig") == (
            "requests==2.32.3\nurllib3==1.26.18\n"
        )

    async def test_a_failed_write_leaves_the_original_file_intact(
        self, tmp_path: Path, store: FakePyPIStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression M7: the writer is atomic. A disk-full or permission error
        mid-write must not leave a truncated requirements file behind — that
        turns a routine update into an outage.
        """
        path = tmp_path / "requirements.txt"
        original = "# service dependencies\nrequests==2.31.0\nurllib3==1.26.5\n"
        path.write_text(original, encoding="utf-8")

        def _fail(*_args: object, **_kwargs: object) -> None:
            raise OSError("ENOSPC: no space left on device")

        monkeypatch.setattr(Path, "replace", _fail)

        with pytest.raises(DepKeeperError):
            await run_update(path, store)

        assert path.read_text(encoding="utf-8") == original
