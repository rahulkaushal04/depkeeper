"""End-to-end ``update`` flags and file-preservation guarantees on real tmp files."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import pytest

from tests.robustness.update_harness import invoke, snapshot, strays

T = {"requests": "2.31.0", "flask": "3.0.0", "django": "5.0.1", "numpy": "1.26.4"}


def run(tmp: Path, *args: str, table: Any = None, **kw: Any) -> Any:
    return invoke(T if table is None else table, ["update", *args], **kw)


def out(r: Any) -> str:
    return r.stdout + r.stderr


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)


def write(p: Path, data: bytes) -> Path:
    p.write_bytes(data)
    return p


class TestByteFidelity:
    @pytest.mark.parametrize(
        "raw",
        [
            b"requests==2.0.0\r\nflask==1.0.0\r\n",
            b"requests==2.0.0\nflask==1.0.0",  # no trailing newline
            b"requests==2.0.0\r\nflask==1.0.0",  # CRLF, no trailing newline
            b"\xef\xbb\xbfrequests==2.0.0\r\nflask==1.0.0\r\n",  # BOM + CRLF
            b"requests==2.0.0\nflask==1.0.0\r\n# c\r\n\n",  # mixed endings
            b"# \xc3\xa9\xe2\x82\xac\nrequests==2.0.0  # pin \xf0\x9f\x98\x80\n",
        ],
    )
    def test_only_version_bytes_change(self, tmp_path: Path, raw: bytes) -> None:
        f = write(tmp_path / "requirements.txt", raw)
        r = run(tmp_path, "-y", str(f))
        assert r.exit_code == 0, out(r)
        new = f.read_bytes()
        assert new.startswith(b"\xef\xbb\xbf") == raw.startswith(b"\xef\xbb\xbf")
        assert new.count(b"\r\n") == raw.count(b"\r\n")
        assert new.endswith(b"\n") == raw.endswith(b"\n")
        assert new.replace(b"2.31.0", b"2.0.0").replace(b"3.0.0", b"1.0.0") == raw
        assert strays(tmp_path) == []

    def test_mode_preserved(self, tmp_path: Path) -> None:
        f = write(tmp_path / "requirements.txt", b"requests==2.0.0\n")
        os.chmod(f, 0o640)
        assert run(tmp_path, "-y", str(f)).exit_code == 0
        assert stat.S_IMODE(f.stat().st_mode) == 0o640

    def test_idempotent(self, tmp_path: Path) -> None:
        f = write(tmp_path / "requirements.txt", b"requests>=2.0.0,<3\nflask==1.0\n")
        assert run(tmp_path, "-y", str(f)).exit_code == 0
        first = f.read_bytes()
        mtime = f.stat().st_mtime_ns
        r = run(tmp_path, "-y", str(f))
        assert r.exit_code == 0 and "up to date" in out(r).lower()
        assert f.read_bytes() == first and f.stat().st_mtime_ns == mtime


class TestFlags:
    BODY = b"requests==2.0.0\nflask==1.0.0\ndjango==4.0.0\n"

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        f = write(tmp_path / "requirements.txt", self.BODY)
        before = snapshot(tmp_path)
        r = run(tmp_path, "--dry-run", "--backup", str(f))
        assert r.exit_code == 0
        assert snapshot(tmp_path) == before
        assert "would be applied" in out(r)

    def test_applied_major_warning(self, tmp_path: Path) -> None:
        f = write(tmp_path / "requirements.txt", self.BODY)
        r = run(tmp_path, "-y", str(f))
        assert "applied: " in out(r) and "would be" not in out(r)

    def test_packages_selection_case_and_duplicates(self, tmp_path: Path) -> None:
        f = write(tmp_path / "requirements.txt", self.BODY)
        r = run(tmp_path, "-y", "-p", "REQUESTS", "-p", "requests", str(f))
        assert r.exit_code == 0
        assert f.read_bytes() == b"requests==2.31.0\nflask==1.0.0\ndjango==4.0.0\n"

    def test_packages_no_match_exit1_untouched(self, tmp_path: Path) -> None:
        f = write(tmp_path / "requirements.txt", self.BODY)
        r = run(tmp_path, "-y", "-p", "nothere", str(f))
        assert r.exit_code == 1
        assert f.read_bytes() == self.BODY

    def test_hash_flags_conflict_is_usage_error(self, tmp_path: Path) -> None:
        f = write(tmp_path / "requirements.txt", self.BODY)
        r = run(tmp_path, "-y", "--refresh-hashes", "--allow-hash-removal", str(f))
        assert r.exit_code == 2 and f.read_bytes() == self.BODY

    def test_markdown_needs_yes_or_dry_run(self, tmp_path: Path) -> None:
        f = write(tmp_path / "requirements.txt", self.BODY)
        assert run(tmp_path, "-f", "markdown", str(f)).exit_code == 2
        r = run(tmp_path, "-f", "MARKDOWN", "--dry-run", str(f))
        assert r.exit_code == 0 and r.stdout.lstrip().startswith("#")
        assert f.read_bytes() == self.BODY

    def test_backup_names_and_content(self, tmp_path: Path) -> None:
        f = write(tmp_path / "requirements.txt", self.BODY)
        os.chmod(f, 0o600)
        r = run(tmp_path, "-y", "--backup", str(f))
        assert r.exit_code == 0
        backups = [p for p in tmp_path.iterdir() if "backup" in p.name]
        assert len(backups) == 1 and backups[0].read_bytes() == self.BODY

    def test_backups_are_not_rediscovered_as_requirements(self, tmp_path: Path) -> None:
        f = write(tmp_path / "requirements.txt", self.BODY)
        assert run(tmp_path, "-y", "--backup", str(f)).exit_code == 0
        before = [p.name for p in tmp_path.iterdir()]
        r = run(tmp_path, "-y", "--backup", str(tmp_path))
        assert r.exit_code == 0, out(r)
        # A second run in directory mode must back up and touch only the real file.
        names = [p.name for p in tmp_path.iterdir() if "backup" in p.name]
        assert len(names) <= 2, (before, names)
        for p in tmp_path.iterdir():
            if "backup" in p.name and p.name not in before:
                pytest.fail(f"a backup file was treated as a requirements file: {p}")

    def test_pin_replaces_ranges(self, tmp_path: Path) -> None:
        f = write(tmp_path / "requirements.txt", b"requests>=2.0,<3\n")
        assert run(tmp_path, "-y", "--pin", str(f)).exit_code == 0
        assert f.read_bytes() == b"requests==2.31.0\n"

    def test_ignore_and_max_update(self, tmp_path: Path) -> None:
        f = write(tmp_path / "requirements.txt", self.BODY)
        r = run(tmp_path, "-y", "--ignore", "Flask", "--max-update", "minor", str(f))
        assert r.exit_code == 0
        assert f.read_bytes() == b"requests==2.31.0\nflask==1.0.0\ndjango==4.0.0\n"

    def test_lookup_failure_exit4_but_others_applied(self, tmp_path: Path) -> None:
        f = write(tmp_path / "requirements.txt", b"requests==2.0.0\nghost==1.0\n")
        r = run(tmp_path, "-y", str(f))
        assert r.exit_code == 4
        assert f.read_bytes() == b"requests==2.31.0\nghost==1.0\n"


class TestConfirmation:
    BODY = b"requests==2.0.0\n"

    @pytest.mark.parametrize(
        "inp,changed",
        [("y\n", True), ("n\n", False), ("Y\n", True), ("N\n", False)],
    )
    def test_answers(self, tmp_path: Path, inp: str, changed: bool) -> None:
        f = write(tmp_path / "requirements.txt", self.BODY)
        r = run(tmp_path, str(f), input=inp)
        assert (f.read_bytes() != self.BODY) is changed
        assert r.exit_code == (0 if changed else 1)

    @pytest.mark.parametrize("stdin", ["", "maybe\nwhat\n", "\x04"])
    def test_eof_or_garbage_never_confirms(
        self, monkeypatch: pytest.MonkeyPatch, stdin: str
    ) -> None:
        """Closed stdin / junk answers must not count as consent (real ``input()``)."""
        import io

        import depkeeper.commands.update as upd
        from depkeeper.exceptions import DepKeeperError

        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
        with pytest.raises(DepKeeperError, match="--yes"):
            upd._confirm_update(2)

    def test_blank_answer_takes_documented_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import io

        import depkeeper.commands.update as upd

        monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
        assert upd._confirm_update(1) is True


class TestMultiFile:
    def test_includes_write_to_included_file(self, tmp_path: Path) -> None:
        (tmp_path / "base.txt").write_bytes(b"requests==2.0.0\r\n")
        main = write(
            tmp_path / "requirements.txt",
            b"-r base.txt\nflask==1.0.0\nrequests==2.0.0\n",
        )
        r = run(tmp_path, "-y", "--backup", str(main))
        assert r.exit_code == 0, out(r)
        assert (tmp_path / "base.txt").read_bytes() == b"requests==2.31.0\r\n"
        assert main.read_bytes() == b"-r base.txt\nflask==3.0.0\nrequests==2.31.0\n"
        assert len([p for p in tmp_path.iterdir() if "backup" in p.name]) == 2

    def test_directory_mode_mixed_formats(self, tmp_path: Path) -> None:
        write(tmp_path / "requirements.txt", b"requests==2.0.0\n")
        pp = write(
            tmp_path / "pyproject.toml",
            b'[project]\nname="x"\nversion="1"\ndependencies = [\n  "flask>=1.0",\n]\n',
        )
        cy = write(
            tmp_path / "environment.yml",
            b"name: e\ndependencies:\n  - numpy=1.20\n  - pip\n",
        )
        r = run(tmp_path, "-y", str(tmp_path))
        assert r.exit_code == 0, out(r)
        assert b"flask>=3.0.0" in pp.read_bytes()
        assert b"numpy" in cy.read_bytes()
        assert (tmp_path / "requirements.txt").read_bytes() == b"requests==2.31.0\n"
        assert strays(tmp_path) == []

    def test_symlinked_requirements_target_updated_link_kept(
        self, tmp_path: Path
    ) -> None:
        real = write(tmp_path / "real.txt", b"requests==2.0.0\n")
        link = tmp_path / "requirements.txt"
        link.symlink_to(real)
        r = run(tmp_path, "-y", str(link))
        assert r.exit_code == 0, out(r)
        assert link.is_symlink() and real.read_bytes() == b"requests==2.31.0\n"


class TestSamePackageManyPlaces:
    def test_duplicate_in_one_file_with_markers(self, tmp_path: Path) -> None:
        f = write(
            tmp_path / "requirements.txt",
            b'requests==2.0.0; python_version<"3.8"\nrequests==2.1.0; python_version>="3.8"\n',
        )
        r = run(tmp_path, "-y", str(f))
        assert r.exit_code == 0, out(r)
        assert f.read_bytes() == (
            b'requests==2.31.0; python_version<"3.8"\n'
            b'requests==2.31.0; python_version>="3.8"\n'
        )

    def test_same_package_in_every_file_of_a_directory(self, tmp_path: Path) -> None:
        write(tmp_path / "requirements.txt", b"requests==2.0.0\n")
        write(tmp_path / "requirements-dev.txt", b"requests>=2.1\n")
        pp = write(
            tmp_path / "pyproject.toml",
            b'[project]\nname="x"\nversion="1"\ndependencies = ["requests>=2.2"]\n',
        )
        r = run(tmp_path, "-y", str(tmp_path))
        assert r.exit_code == 0, out(r)
        assert (tmp_path / "requirements.txt").read_bytes() == b"requests==2.31.0\n"
        assert (tmp_path / "requirements-dev.txt").read_bytes() == b"requests>=2.31.0\n"
        assert b'"requests>=2.31.0"' in pp.read_bytes()

    def test_include_cycle_and_diamond_write_each_file_once(
        self, tmp_path: Path
    ) -> None:
        write(tmp_path / "base.txt", b"requests==2.0.0\n")
        write(tmp_path / "a.txt", b"-r base.txt\n")
        write(tmp_path / "b.txt", b"-r base.txt\n")
        main = write(tmp_path / "requirements.txt", b"-r a.txt\n-r b.txt\n")
        r = run(tmp_path, "-y", "--backup", str(main))
        assert r.exit_code == 0, out(r)
        assert (tmp_path / "base.txt").read_bytes() == b"requests==2.31.0\n"
        assert len([p for p in tmp_path.iterdir() if p.name.endswith(".backup")]) == 1
