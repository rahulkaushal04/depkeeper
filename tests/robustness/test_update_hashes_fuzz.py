"""Hashed layouts, markdown escaping, unicode paths and a seeded minimal-diff fuzz."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import pytest

import depkeeper.commands.update as upd
from tests.robustness.update_harness import invoke, strays

T = {"requests": "2.31.0", "flask": "3.0.0", "idna": "3.7", "my-pkg": "9.0.0"}
D64 = "a" * 64


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)


def go(f: Path, *args: str, **kw: Any) -> Any:
    return invoke(T, ["update", *args, str(f)], **kw)


def text(r: Any) -> str:
    return r.stdout + r.stderr


HASHED = [
    b"requests==2.0.0 \\\n    --hash=sha256:%s \\\n    --hash=sha256:%s\n"
    % (b"1" * 64, b"2" * 64),
    b"requests==2.0.0 --hash=sha256:%s --hash=sha512:%s\n" % (b"1" * 64, b"3" * 128),
    b"requests==2.0.0 \\\r\n    --hash=sha256:%s  # why\r\n" % (b"1" * 64),
]


class TestHashes:
    @pytest.mark.parametrize("raw", HASHED)
    def test_refused_by_default_file_untouched(
        self, tmp_path: Path, raw: bytes
    ) -> None:
        f = tmp_path / "requirements.txt"
        f.write_bytes(raw)
        r = go(f, "-y")
        assert r.exit_code == 1 and "--hash" in text(r)
        assert f.read_bytes() == raw and strays(tmp_path) == []

    @pytest.mark.parametrize("raw", HASHED)
    def test_dry_run_flags_it_and_writes_nothing(
        self, tmp_path: Path, raw: bytes
    ) -> None:
        f = tmp_path / "requirements.txt"
        f.write_bytes(raw)
        r = go(f, "--dry-run")
        assert r.exit_code == 0 and f.read_bytes() == raw

    @pytest.mark.parametrize("raw", HASHED)
    def test_allow_removal_leaves_no_orphan_hash_lines(
        self, tmp_path: Path, raw: bytes
    ) -> None:
        f = tmp_path / "requirements.txt"
        f.write_bytes(raw)
        r = go(f, "-y", "--allow-hash-removal")
        assert r.exit_code == 0, text(r)
        new = f.read_bytes().decode()
        assert "--hash" not in new and "2.31.0" in new
        assert not new.rstrip().endswith("\\")
        for line in new.splitlines():
            assert not line.strip().startswith("--hash")

    @pytest.mark.parametrize("raw", HASHED)
    def test_refresh_replaces_digests_and_missing_refuses(
        self, tmp_path: Path, raw: bytes
    ) -> None:
        f = tmp_path / "requirements.txt"
        f.write_bytes(raw)

        async def none(_u: Any) -> Dict[Any, List[str]]:
            return {}

        with mock.patch.object(upd, "_fetch_hash_digests", none):
            r = go(f, "-y", "--refresh-hashes")
        assert r.exit_code == 1 and f.read_bytes() == raw

        async def some(_u: Any) -> Dict[Any, List[str]]:
            return {("requests", "2.31.0"): [D64, "b" * 64]}

        with mock.patch.object(upd, "_fetch_hash_digests", some):
            r = go(f, "-y", "--refresh-hashes")
        assert r.exit_code == 0, text(r)
        new = f.read_bytes().decode()
        assert new.count("--hash=sha256:") == 2 and D64 in new and "1" * 64 not in new
        assert ("\r\n" in new) == (b"\r\n" in raw)
        # Comment must follow the last hash, never swallow a continuation.
        for line in new.splitlines():
            if line.rstrip().endswith("\\"):
                assert "#" not in line.split("\\")[0]


class TestOutput:
    def test_markdown_escapes_and_goes_to_stdout_only(self, tmp_path: Path) -> None:
        f = tmp_path / "requirements.txt"
        f.write_bytes(b"my_pkg==1.0.0\nrequests==2.0.0\n")
        r = go(f, "-f", "markdown", "-y")
        assert r.exit_code == 0
        assert "my-pkg" in r.stdout.lower() or "my_pkg" in r.stdout.lower()
        assert "Successfully updated" not in r.stdout  # status lines go to stderr
        assert "|" in r.stdout

    def test_markdown_dry_run_title(self, tmp_path: Path) -> None:
        f = tmp_path / "requirements.txt"
        f.write_bytes(b"requests==2.0.0\n")
        r = go(f, "-f", "markdown", "--dry-run")
        assert "dry run" in r.stdout.lower() and f.read_bytes() == b"requests==2.0.0\n"

    def test_unicode_and_spaced_paths(self, tmp_path: Path) -> None:
        d = tmp_path / "pröjekt ünï 日本 😀"
        d.mkdir()
        f = d / "requirements.txt"
        f.write_bytes(b"requests==2.0.0\n")
        r = go(f, "-y", "--backup")
        assert r.exit_code == 0, text(r)
        assert f.read_bytes() == b"requests==2.31.0\n"
        assert strays(d) == []

    def test_huge_file(self, tmp_path: Path) -> None:
        f = tmp_path / "requirements.txt"
        body = (
            b"".join(b"# comment %d\n" % i for i in range(60000)) + b"requests==2.0.0\n"
        )
        f.write_bytes(body)
        r = go(f, "-y")
        assert r.exit_code == 0
        assert f.read_bytes() == body.replace(b"2.0.0", b"2.31.0")


def _gen(rng: random.Random) -> bytes:
    eol = rng.choice(["\n", "\r\n"])
    names = ["requests", "Flask", "idna", "ghost", "My_Pkg", "REQUESTS"]
    specs = [
        "==1.0",
        " == 2.0.0",
        ">=1.0",
        ">=1.0, <4",
        "~=1.4",
        "!=1.5,>=1.0",
        "",
        "<9",
        "  >=1.0",
    ]
    lines: List[str] = []
    for _ in range(rng.randint(1, 12)):
        k = rng.random()
        if k < 0.15:
            lines.append("# " + rng.choice(["note", "é ü", "requests==0.0.1", ""]))
        elif k < 0.2:
            lines.append("")
        else:
            n = rng.choice(names)
            extra = (
                rng.choice(["", "[security]", "  ", "\t"]) if n == "requests" else ""
            )
            ln = f"{n}{extra if extra.startswith('[') else ''}{rng.choice(specs)}"
            if rng.random() < 0.3:
                ln += "  # " + rng.choice(["pinned", "see #5", "é"])
            if rng.random() < 0.15:
                ln += '; python_version >= "3.8"'
            lines.append(ln)
    body = eol.join(lines)
    if rng.random() < 0.7:
        body += eol
    return (b"\xef\xbb\xbf" if rng.random() < 0.2 else b"") + body.encode()


def test_minimal_diff_and_idempotence_fuzz(tmp_path: Path) -> None:
    import re

    rng = random.Random(20260611)
    spec = re.compile(rb"(===|==|>=|<=|~=|!=|<|>)\s*[0-9][0-9A-Za-z.*+!-]*")

    def strip_specs(line: bytes) -> bytes:
        # A new bound may be added to, or a first pin written for, a bare name.
        return re.sub(rb"S(\s*,?\s*S)*", b"", spec.sub(b"S", line))

    for case in range(150):
        d = tmp_path / f"c{case}"
        d.mkdir()
        f = d / "requirements.txt"
        raw = _gen(rng)
        f.write_bytes(raw)
        r = go(f, "-y")
        assert r.exit_code in (0, 4), (raw, text(r))
        new = f.read_bytes()
        assert new.startswith(b"\xef\xbb\xbf") == raw.startswith(b"\xef\xbb\xbf")
        assert new.count(b"\r\n") == raw.count(b"\r\n"), raw
        assert new.endswith(b"\n") == raw.endswith(b"\n"), raw
        old_l, new_l = raw.splitlines(True), new.splitlines(True)
        assert len(old_l) == len(new_l), (raw, new)
        for a, b in zip(old_l, new_l):
            if a != b:
                # comment and environment-marker bytes never change
                assert a.partition(b"#")[2] == b.partition(b"#")[2], (a, b)
                assert a.partition(b";")[2] == b.partition(b";")[2], (a, b)
                assert strip_specs(a) == strip_specs(b), (a, b)
        # idempotent: second run is a byte-for-byte no-op
        again = f.read_bytes()
        r2 = go(f, "-y")
        assert r2.exit_code in (0, 4)
        assert f.read_bytes() == again, (raw, new)
        assert strays(d) == []
