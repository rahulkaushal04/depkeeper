"""Adversarial tests of config discovery/validation, exit codes and logging for the CLI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, List
from unittest import mock

import click
import pytest

from depkeeper import cli as cli_module
from depkeeper.config import discover_config_file, load_config
from depkeeper.exceptions import ConfigError, DepKeeperError
from depkeeper.models import Package
from depkeeper.utils.logger import ColoredFormatter
from tests.test_commands.test_check_output_streams import _run_check


@pytest.fixture(autouse=True)
def _plain(no_color: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEPKEEPER_CONFIG", raising=False)
    monkeypatch.delenv("DEPKEEPER_COLOR", raising=False)


def _pkg() -> Package:
    return Package(
        name="flask",
        current_version="1.0.0",
        latest_version="2.0.0",
        recommended_version="2.0.0",
    )


class TestConfigShape:
    @pytest.mark.parametrize(
        "body", ["depkeeper = 5", 'depkeeper = "x"', "depkeeper = [1]"]
    )
    def test_non_table_section_is_config_error(self, tmp_path: Path, body: str) -> None:
        (tmp_path / "depkeeper.toml").write_text(body + "\n")
        r = _run_check(tmp_path, ["check"], packages=[_pkg()])
        assert r.exit_code == 1
        assert "must be a table" in r.stderr
        assert "Unexpected error" not in r.stderr

    @pytest.mark.parametrize(
        "body", ["tool = 5", "tool = 'depkeeper'", "[tool]\ndepkeeper = 1"]
    )
    def test_pyproject_odd_tool_tables(self, tmp_path: Path, body: str) -> None:
        path = tmp_path / "pyproject.toml"
        path.write_text(body + "\n")
        # discovery never crashes on a pyproject that is not ours
        discover_config_file()
        with pytest.raises(ConfigError):
            load_config(path)

    @pytest.mark.parametrize(
        "body",
        [
            "check_conflicts = 'yes'",
            "strict_version_matching = 1",
            "fail_on = 'UPDATES'",
            "fail_on = ['none']",
            "ignore = 'flask'",
            "ignore = [1]",
            "python_version = 3.9",
            "python_version = '3'",
            "min_age = true",
            "min_age = -1",
            "min_age = 'soon'",
            "versioning = 'x'",
            "packages = 3",
            "bogus = 1",
        ],
    )
    def test_invalid_values_exit_1_with_message(
        self, tmp_path: Path, body: str
    ) -> None:
        (tmp_path / "depkeeper.toml").write_text(f"[depkeeper]\n{body}\n")
        r = _run_check(tmp_path, ["check"], packages=[_pkg()])
        assert r.exit_code == 1
        assert r.stderr.startswith("[ERROR]")
        assert "Traceback" not in r.stderr + r.stdout

    def test_bom_and_crlf(self, tmp_path: Path) -> None:
        (tmp_path / "depkeeper.toml").write_bytes(
            b"\xef\xbb\xbf[depkeeper]\r\nfail_on = 'updates'\r\n"
        )
        assert _run_check(tmp_path, ["check"], packages=[_pkg()]).exit_code == 3

    def test_non_utf8_config(self, tmp_path: Path) -> None:
        (tmp_path / "depkeeper.toml").write_bytes(b"[depkeeper]\n# \xff\xfe\n")
        r = _run_check(tmp_path, ["check"], packages=[_pkg()])
        assert r.exit_code == 1 and "UTF-8" in r.stderr

    def test_empty_config_is_defaults(self, tmp_path: Path) -> None:
        (tmp_path / "depkeeper.toml").write_text("")
        assert _run_check(tmp_path, ["check"], packages=[_pkg()]).exit_code == 0


class TestDiscovery:
    def test_directory_named_like_config_is_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "depkeeper.toml").mkdir()
        (tmp_path / "pyproject.toml").mkdir()
        assert discover_config_file() is None

    def test_walks_up_to_git_root_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        sub = repo / "a" / "b"
        sub.mkdir(parents=True)
        (tmp_path / "depkeeper.toml").write_text("[depkeeper]\n")  # above the repo
        (repo / ".git").mkdir()
        monkeypatch.chdir(sub)
        assert discover_config_file() is None
        (repo / "depkeeper.toml").write_text("[depkeeper]\n")
        assert discover_config_file() == repo / "depkeeper.toml"

    def test_depkeeper_toml_beats_pyproject(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool.depkeeper]\nfail_on='major'\n")
        (tmp_path / "depkeeper.toml").write_text("[depkeeper]\nfail_on='minor'\n")
        assert load_config().fail_on == "minor"

    def test_pyproject_without_section_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
        assert discover_config_file() is None

    def test_broken_pyproject_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool.depkeeper\n")
        assert discover_config_file() is None

    def test_explicit_dir_is_usage_error(self, tmp_path: Path) -> None:
        r = _run_check(tmp_path, ["-c", str(tmp_path), "check"], packages=[_pkg()])
        assert r.exit_code == 2

    def test_envvar_config_and_flag_precedence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_cfg = tmp_path / "env.toml"
        env_cfg.write_text("[depkeeper]\nfail_on='updates'\n")
        flag_cfg = tmp_path / "flag.toml"
        flag_cfg.write_text("[depkeeper]\nfail_on='none'\n")
        monkeypatch.setenv("DEPKEEPER_CONFIG", str(env_cfg))
        assert _run_check(tmp_path, ["check"], packages=[_pkg()]).exit_code == 3
        r = _run_check(tmp_path, ["-c", str(flag_cfg), "check"], packages=[_pkg()])
        assert r.exit_code == 0

    def test_explicit_file_without_section_errors(self, tmp_path: Path) -> None:
        other = tmp_path / "other.toml"
        other.write_text("x = 1\n")
        r = _run_check(tmp_path, ["-c", str(other), "check"], packages=[_pkg()])
        assert r.exit_code == 1 and "no [depkeeper] table" in r.stderr


class TestMainExitCodes:
    @pytest.mark.parametrize(
        "exc,code",
        [
            (KeyboardInterrupt(), 130),
            (click.Abort(), 130),
            (click.UsageError("bad"), 2),
            (DepKeeperError("boom"), 1),
            (RuntimeError("x"), 1),
        ],
    )
    def test_main_maps_exceptions(self, exc: BaseException, code: int) -> None:
        with mock.patch.object(cli_module, "cli", side_effect=exc):
            assert cli_module.main() == code

    def test_ctrl_c_during_check_is_130(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "requirements.txt").write_text("flask==1\n")
        monkeypatch.setattr("sys.argv", ["depkeeper", "check"])

        async def boom(*a: Any, **k: Any) -> int:
            raise KeyboardInterrupt

        with mock.patch("depkeeper.commands.check._check_async", boom):
            assert cli_module.main() == 130

    def test_unexpected_error_in_check_is_exit_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "requirements.txt").write_text("flask==1\n")
        monkeypatch.setattr("sys.argv", ["depkeeper", "check"])

        async def boom(*a: Any, **k: Any) -> int:
            raise ValueError("kaboom")

        with mock.patch("depkeeper.commands.check._check_async", boom):
            with pytest.raises(SystemExit) as info:
                cli_module.main()
        assert info.value.code == 1

    @pytest.mark.parametrize(
        "args",
        [
            ["check", "--fail-on", "bogus"],
            ["check", "-f", "xml"],
            ["check", "--python-version", "3"],
            ["check", "--min-age", "-1d"],
            ["check", "--min-age", "1e999"],
            ["check", "a", "b"],
            ["nope"],
        ],
    )
    def test_usage_errors_are_exit_2(self, tmp_path: Path, args: List[str]) -> None:
        assert _run_check(tmp_path, args, packages=[_pkg()]).exit_code == 2

    def test_missing_and_bad_inputs(self, tmp_path: Path) -> None:
        assert (
            _run_check(tmp_path, ["check", "missing.txt"], packages=[_pkg()]).exit_code
            == 2
        )
        (tmp_path / "bin.txt").write_bytes(b"\x00\xff\xfe")
        r = _run_check(tmp_path, ["check", "bin.txt", "-f", "json"], packages=[_pkg()])
        assert r.exit_code == 1 and r.stdout == ""
        (tmp_path / "emptydir").mkdir()
        assert (
            _run_check(tmp_path, ["check", "emptydir"], packages=[_pkg()]).exit_code
            == 1
        )


class TestLogging:
    def test_colored_formatter_does_not_mutate_record(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.setattr(
            ColoredFormatter, "_should_use_color", staticmethod(lambda: True)
        )
        fmt = ColoredFormatter("%(levelname)s %(message)s")
        rec = logging.LogRecord("depkeeper", logging.INFO, __file__, 1, "m", (), None)
        first = fmt.format(rec)
        assert rec.levelname == "INFO"
        assert fmt.format(rec) == first
        assert first.count("\033[32m") == 1

    @pytest.mark.parametrize(
        "flags,expect", [([], False), (["-v"], True), (["-vv"], True)]
    )
    def test_verbosity_levels(
        self, tmp_path: Path, flags: List[str], expect: bool
    ) -> None:
        r = _run_check(tmp_path, [*flags, "check", "-f", "json"], packages=[_pkg()])
        assert ("Checking" in r.stderr) is expect
        assert ("DEBUG" in r.stderr) is (flags == ["-vv"])
        assert "Checking" not in r.stdout

    def test_vv_does_not_log_url_credentials(self, tmp_path: Path) -> None:
        body = (
            "--index-url https://user:SEKRET1@idx.example.com/simple\n"
            "mypkg @ https://tok:SEKRET2@example.com/mypkg-1.0.whl\n"
            "flask==1.0.0\n"
        )
        r = _run_check(tmp_path, ["-vv", "check"], packages=[_pkg()], contents=body)
        assert "SEKRET" not in r.stderr + r.stdout
