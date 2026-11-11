"""``update --refresh-hashes`` / ``--verify``, adapter hash rewrite, digests, conda lookups."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import pytest

from depkeeper.core.data_store import PyPIDataStore
from depkeeper.core.parser import RequirementsParser
from depkeeper.core.sources.requirements_txt import RequirementsTxtAdapter
from depkeeper.exceptions import DepKeeperError
from depkeeper.models import Package, Requirement
from tests.test_commands.test_update_cli_options import _pkg, _run_update

A, B, C = "a" * 64, "b" * 64, "c" * 64


@dataclass
class _VR:
    ok: bool = True
    skipped: bool = False
    message: str = ""
    conflicts: List[str] = field(default_factory=list)


def _apply(
    text: str, version: str, digests: Dict[Any, Any], tmp_path: Path, **kw: Any
) -> str:
    f = tmp_path / "requirements.txt"
    f.write_bytes(text.encode())
    reqs = RequirementsParser().parse_file(f)
    return RequirementsTxtAdapter().apply_updates(
        text, [(reqs[0], version)], refresh_hashes=True, hash_digests=digests, **kw
    )


D = {("pkg", "2.0"): [C, A, B, A]}


@pytest.mark.unit
class TestAdapterRefresh:
    def test_continuation_layout_sorted_deduped(self, tmp_path: Path) -> None:
        text = "pkg==1.0 \\\n    --hash=sha256:" + "d" * 64 + "\n# c\nother==1\n"
        out = _apply(text, "2.0", D, tmp_path)
        assert out == (
            f"pkg==2.0 \\\n    --hash=sha256:{A} \\\n    --hash=sha256:{B} \\\n"
            f"    --hash=sha256:{C}\n# c\nother==1\n"
        )

    def test_own_line_comment_after_trailing_backslash_kept(
        self, tmp_path: Path
    ) -> None:
        text = (
            "pkg==1.0 \\\n    --hash=sha256:"
            + "d" * 64
            + " \\\n    # via x\nother==1\n"
        )
        out = _apply(text, "2.0", {("pkg", "2.0"): [A]}, tmp_path)
        assert out == f"pkg==2.0 \\\n    --hash=sha256:{A}\n    # via x\nother==1\n"

    def test_crlf_and_indent_preserved(self, tmp_path: Path) -> None:
        text = "pkg==1.0 \\\r\n\t--hash=sha256:" + "d" * 64 + "\r\nz==1\r\n"
        out = _apply(text, "2.0", D, tmp_path)
        assert "\n" not in out.replace("\r\n", "")
        assert out.startswith(
            f"pkg==2.0 \\\r\n\t--hash=sha256:{A} \\\r\n\t--hash=sha256:{B}"
        )
        assert out.endswith("\r\nz==1\r\n")

    def test_single_line_layout_and_comment(self, tmp_path: Path) -> None:
        out = _apply(f"pkg==1.0 --hash=sha256:{'d' * 64}  # why\n", "2.0", D, tmp_path)
        assert (
            out
            == f"pkg==2.0 --hash=sha256:{A} --hash=sha256:{B} --hash=sha256:{C}  # why\n"
        )

    def test_missing_digests_refused(self, tmp_path: Path) -> None:
        with pytest.raises(DepKeeperError, match="no PyPI file digests"):
            _apply(f"pkg==1.0 --hash=sha256:{'d' * 64}\n", "2.0", {}, tmp_path)

    def test_mixed_hashed_unhashed(self, tmp_path: Path) -> None:
        text = f"plain==1.0\npkg==1.0 \\\n    --hash=sha256:{'d' * 64}\n"
        f = tmp_path / "requirements.txt"
        f.write_text(text)
        reqs = RequirementsParser().parse_file(f)
        out = RequirementsTxtAdapter().apply_updates(
            text,
            [(r, "2.0") for r in reqs],
            refresh_hashes=True,
            hash_digests={("pkg", "2.0"): [A]},
        )
        assert out == f"plain==2.0\npkg==2.0 \\\n    --hash=sha256:{A}\n"

    def test_refusal_without_flag(self, tmp_path: Path) -> None:
        text = f"pkg==1.0 --hash=sha256:{'d' * 64}\n"
        f = tmp_path / "requirements.txt"
        f.write_text(text)
        req = RequirementsParser().parse_file(f)[0]
        with pytest.raises(DepKeeperError, match="Refusing"):
            RequirementsTxtAdapter().apply_updates(text, [(req, "2.0")])


HASHED = f"pkg==1.0 \\\n    --hash=sha256:{'d' * 64}\n"


def _run(
    tmp_path: Path,
    *args: str,
    digests: Any = None,
    verify: Any = None,
    body: str = HASHED,
    pkgs: Any = None,
) -> Any:
    async def fake_fetch(_u: Any) -> Dict[Any, Any]:
        return D if digests is None else digests

    patches = [mock.patch("depkeeper.commands.update._fetch_hash_digests", fake_fetch)]
    if verify is not None:
        patches.append(mock.patch("depkeeper.commands.update._run_verify", verify))
    for p in patches:
        p.start()
    try:
        return _run_update(tmp_path, body, pkgs or [_pkg("pkg", "1.0", "2.0")], *args)
    finally:
        for p in patches:
            p.stop()


@pytest.mark.unit
class TestRefreshCli:
    def test_refresh_writes_hashes(self, tmp_path: Path) -> None:
        result, req = _run(tmp_path, "-y", "--refresh-hashes")
        assert result.exit_code == 0, result.output
        assert req.read_text() == (
            f"pkg==2.0 \\\n    --hash=sha256:{A} \\\n    --hash=sha256:{B} \\\n    --hash=sha256:{C}\n"
        )

    def test_dry_run_reports_and_does_not_write(self, tmp_path: Path) -> None:
        result, req = _run(tmp_path, "--dry-run", "--refresh-hashes")
        assert result.exit_code == 0
        assert "would be refreshed for pkg==2.0" in result.output + (
            result.stderr or ""
        )
        assert req.read_text() == HASHED

    def test_missing_digests_leaves_file_untouched(self, tmp_path: Path) -> None:
        result, req = _run(tmp_path, "-y", "--refresh-hashes", digests={})
        assert result.exit_code == 1
        assert req.read_text() == HASHED

    def test_conflicts_with_allow_hash_removal(self, tmp_path: Path) -> None:
        result, req = _run(tmp_path, "-y", "--refresh-hashes", "--allow-hash-removal")
        assert result.exit_code == 2
        assert req.read_text() == HASHED

    def test_sha512_replacement_is_warned(self, tmp_path: Path) -> None:
        body = f"pkg==1.0 \\\n    --hash=sha512:{'d' * 128}\n"
        result, _ = _run(tmp_path, "-y", "--refresh-hashes", body=body)
        assert "non-sha256" in result.output + (result.stderr or "")

    def test_hashed_without_flags_hints_refresh(self, tmp_path: Path) -> None:
        result, _ = _run(tmp_path, "-y")
        assert result.exit_code == 1
        assert "--refresh-hashes" in result.output + (result.stderr or "")


@pytest.mark.unit
class TestVerify:
    BODY = "a==1.0.0\nb==1.0.0\n"
    PKGS = [_pkg("a", "1.0.0", "1.0.1"), _pkg("b", "1.0.0", "1.0.0")]

    def test_ok_proceeds_with_pinned_plan(self, tmp_path: Path) -> None:
        seen: List[List[str]] = []

        def ok(reqs: List[str]) -> _VR:
            seen.append(reqs)
            return _VR()

        result, req = _run(
            tmp_path, "-y", "--verify", verify=ok, body=self.BODY, pkgs=self.PKGS
        )
        assert result.exit_code == 0
        assert seen == [["a==1.0.1", "b==1.0.0"]]
        assert req.read_text() == "a==1.0.1\nb==1.0.0\n"

    def test_conflict_aborts_without_writing(self, tmp_path: Path) -> None:
        bad = lambda reqs: _VR(ok=False, conflicts=["a 1.0.1 conflicts with b"])  # noqa: E731
        result, req = _run(
            tmp_path, "-y", "--verify", verify=bad, body=self.BODY, pkgs=self.PKGS
        )
        assert result.exit_code == 1
        assert "a 1.0.1 conflicts with b" in result.output + (result.stderr or "")
        assert req.read_text() == self.BODY

    def test_no_updates_still_verifies_current_set(self, tmp_path: Path) -> None:
        bad = lambda reqs: _VR(ok=False, conflicts=["flask conflicts with werkzeug"])  # noqa: E731
        pkgs = [_pkg("a", "1.0.0", "1.0.0"), _pkg("b", "1.0.0", "1.0.0")]
        result, _ = _run(
            tmp_path, "-y", "--verify", verify=bad, body=self.BODY, pkgs=pkgs
        )
        assert result.exit_code == 1
        out = result.output + (result.stderr or "")
        assert "flask conflicts with werkzeug" in out
        assert "up to date" not in out

    def test_skipped_warns_and_continues(self, tmp_path: Path) -> None:
        skip = lambda reqs: _VR(ok=False, skipped=True, message="pip unavailable")  # noqa: E731
        result, req = _run(
            tmp_path, "-y", "--verify", verify=skip, body=self.BODY, pkgs=self.PKGS
        )
        assert result.exit_code == 0
        assert "pip unavailable" in result.output + (result.stderr or "")
        assert req.read_text() == "a==1.0.1\nb==1.0.0\n"


@pytest.mark.unit
class TestConda:
    def _req(self, raw: str, name: str, spec: str) -> Requirement:
        return Requirement(
            name=name, specs=[("==", spec)], raw_line=raw, approximate=True
        )

    def test_fuzzy_noop_not_listed(self) -> None:
        from depkeeper.commands.update import _find_updates

        req = self._req("numpy=1.24", "numpy", "1.24")
        pkg = _pkg("numpy", "1.24", "1.24.5")
        assert _find_updates([pkg], [req]) == []
        pkg2 = _pkg("numpy", "1.24", "1.25.1")
        assert len(_find_updates([pkg2], [req])) == 1

    def test_exact_conda_pin_still_updates(self) -> None:
        from depkeeper.commands.update import _find_updates

        req = self._req("numpy==1.24.0", "numpy", "1.24.0")
        assert len(_find_updates([_pkg("numpy", "1.24.0", "1.24.5")], [req])) == 1

    def test_lookup_failure_is_warning_not_exit_4(self, tmp_path: Path) -> None:
        stub = Package(
            name="ghost",
            current_version="1.0",
            latest_version=None,
            recommended_version=None,
        )
        req = Requirement(name="ghost", specs=[("==", "1.0")], approximate=True)
        with mock.patch("depkeeper.commands.update.parse_targets", return_value=[req]):
            result, _ = _run_update(tmp_path, "ghost==1.0\n", [stub], "-y")
        assert result.exit_code == 0
        assert "conda-only" in result.output


class _Resp:
    def __init__(self, status: int, body: Any) -> None:
        self.status_code, self._b = status, body

    def json(self) -> Any:
        return self._b


class _Http:
    def __init__(self, *responses: _Resp) -> None:
        self.responses, self.calls = list(responses), 0

    async def get(self, url: str, **_: Any) -> _Resp:
        self.calls += 1
        return self.responses.pop(0)


@pytest.mark.unit
class TestDigests:
    def test_fetch_dedupes_sorts_and_caches(self) -> None:
        files = [
            {"digests": {"sha256": B.upper()}},
            {"digests": {"sha256": A}},
            {"digests": {"sha256": A}},
        ]
        http = _Http(_Resp(200, {"urls": files}))
        store = PyPIDataStore(http)  # type: ignore[arg-type]
        assert asyncio.run(store.get_version_digests("Pkg", "2.0")) == [A, B]
        assert asyncio.run(store.get_version_digests("pkg", "2.0")) == [A, B]
        assert http.calls == 1

    def test_failures_not_cached(self) -> None:
        http = _Http(_Resp(500, {}), _Resp(200, {"urls": [{"digests": {"sha256": A}}]}))
        store = PyPIDataStore(http)  # type: ignore[arg-type]
        assert asyncio.run(store.get_version_digests("pkg", "2.0")) is None
        assert asyncio.run(store.get_version_digests("pkg", "2.0")) == [A]

    def test_no_digests_is_none(self) -> None:
        store = PyPIDataStore(_Http(_Resp(200, {"urls": [{}]})))  # type: ignore[arg-type]
        assert asyncio.run(store.get_version_digests("pkg", "2.0")) is None


@pytest.mark.unit
def test_verify_receives_constraint_entries(tmp_path: Path) -> None:
    (tmp_path / "c.txt").write_text("a<2\n")
    seen: List[Any] = []

    def ok(reqs: List[str], constraints: Any = ()) -> _VR:
        seen.append(list(constraints))
        return _VR()

    result, _ = _run(
        tmp_path,
        "-y",
        "--verify",
        verify=ok,
        body="-c c.txt\na==1.0.0\n",
        pkgs=[_pkg("a", "1.0.0", "1.0.1")],
    )
    assert result.exit_code == 0 and seen and any("a<2" in c for c in seen[0])
