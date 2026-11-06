"""Exit-code, lookup-failure, --ignore and NO_COLOR tests for ``check``."""

from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
from typing import Any, List

import pytest

from depkeeper.models import Package
from tests.test_commands.test_check_output_streams import _run_check


def _pkg(name: str, cur: str, rec: str, latest: str = "") -> Package:
    return Package(
        name=name,
        current_version=cur,
        latest_version=latest or rec,
        recommended_version=rec,
    )


STUB = Package(
    name="ghost", current_version="1.0", latest_version=None, recommended_version=None
)


@pytest.mark.unit
class TestExitCodes:
    @pytest.mark.parametrize(
        "args,pkgs,code",
        [
            ([], [_pkg("a", "1.0.0", "1.0.1")], 0),
            (["--fail-on", "updates"], [_pkg("a", "1.0.0", "1.0.1")], 3),
            (["--fail-on", "updates"], [_pkg("a", "1.0.0", "1.0.0")], 0),
            (["--fail-on", "minor"], [_pkg("a", "1.0.0", "1.0.1")], 0),
            (["--fail-on", "minor"], [_pkg("a", "1.0.0", "1.1.0")], 3),
            (["--fail-on", "major"], [_pkg("a", "1.0.0", "1.1.0")], 0),
            (["--fail-on", "major"], [_pkg("a", "1.0.0", "2.0.0")], 3),
            ([], [STUB], 4),
            (["--fail-on", "updates"], [STUB, _pkg("a", "1.0.0", "1.0.1")], 4),
            (["--outdated-only"], [STUB], 4),
        ],
    )
    def test_codes(self, tmp_path: Path, args: List[str], pkgs: Any, code: int) -> None:
        result = _run_check(tmp_path, ["check", *args], packages=pkgs)
        assert result.exit_code == code

    def test_failure_never_says_up_to_date(self, tmp_path: Path) -> None:
        result = _run_check(tmp_path, ["check", "--outdated-only"], packages=[STUB])
        assert "up to date" not in result.stdout + result.stderr
        assert "ghost" in result.stderr
        assert "could not be checked" in result.stderr

    def test_json_stays_valid_and_carries_error(self, tmp_path: Path) -> None:
        result = _run_check(tmp_path, ["check", "-f", "json"], packages=[STUB])
        data = json.loads(result.stdout)
        assert data[0]["error"]
        assert "ghost" in result.stderr
        assert result.exit_code == 4

    def test_fail_on_from_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "depkeeper.toml").write_text('[depkeeper]\nfail_on="updates"\n')
        monkeypatch.chdir(tmp_path)
        result = _run_check(tmp_path, ["check"], packages=[_pkg("a", "1.0.0", "1.0.1")])
        assert result.exit_code == 3
        result = _run_check(
            tmp_path,
            ["check", "--fail-on", "none"],
            packages=[_pkg("a", "1.0.0", "1.0.1")],
        )
        assert result.exit_code == 0


@pytest.mark.unit
class TestIgnoreAndStrict:
    def test_ignore_filters_requirements(self, tmp_path: Path) -> None:
        seen: List[str] = []
        import depkeeper.commands.check as mod

        from tests.test_commands import test_check_output_streams as t

        class Checker:
            def __init__(self, *a, **k) -> None:
                pass

            @classmethod
            def from_config(cls, *a: Any, **k: Any) -> Any:
                return cls()

            async def check_packages(self, reqs: Any) -> Any:
                seen.extend(r.name for r in reqs)
                return []

        (tmp_path / "requirements.txt").write_text("Flask_X==1\nrequests==2\n")
        from unittest import mock

        with ExitStack() as _stack:
            _stack.enter_context(
                mock.patch.object(mod, "HTTPClient", t._FakeHTTPClient)
            )
            _stack.enter_context(
                mock.patch.object(mod, "PyPIDataStore", t._FakeDataStore)
            )
            _stack.enter_context(mock.patch.object(mod, "VersionChecker", Checker))
            _stack.enter_context(
                mock.patch.object(mod, "DependencyAnalyzer", t._fake_analyzer(None))
            )
            from depkeeper.cli import cli

            r = t._make_runner().invoke(
                cli,
                ["check", str(tmp_path / "requirements.txt"), "--ignore", "flask-x"],
            )
        assert r.exit_code == 0, r.output
        assert seen == ["requests"]

    def test_no_strict_flag_accepted(self, tmp_path: Path) -> None:
        result = _run_check(tmp_path, ["check", "--no-strict-version-matching"])
        assert result.exit_code == 0


@pytest.mark.unit
class TestColorAndAbort:
    def test_default_color_keeps_user_no_color(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import os

        monkeypatch.setenv("NO_COLOR", "1")
        _run_check(tmp_path, ["check"])
        assert os.environ.get("NO_COLOR") == "1"

    def test_abort_exits_130(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import click

        import depkeeper.cli as c

        def boom(**kw: Any) -> None:
            raise click.Abort()

        monkeypatch.setattr(c, "cli", boom)
        assert c.main() == 130
        assert "Aborted" in capsys.readouterr().err


@pytest.mark.unit
class TestDirectReferences:
    EDITABLE = Package(
        name="local",
        current_version=None,
        latest_version=None,
        recommended_version=None,
    )
    CONTENTS = "-e git+https://github.com/x/local.git#egg=local\n"

    @pytest.mark.parametrize("args", [[], ["--outdated-only"]])
    def test_editable_is_not_a_lookup_failure(self, tmp_path: Path, args: Any) -> None:
        result = _run_check(
            tmp_path,
            ["check", str(tmp_path / "requirements.txt"), *args],
            packages=[self.EDITABLE],
            contents=self.CONTENTS,
        )
        assert result.exit_code == 0
        assert "could not be checked" not in result.stderr
