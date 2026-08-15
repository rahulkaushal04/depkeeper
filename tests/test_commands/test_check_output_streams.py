"""Stream-separation regression tests for the ``check`` command (M11).

``--format json`` and ``--format simple`` write a machine-consumable payload
to stdout. Warnings, success messages, errors and the resolution summary are
diagnostics and must go to stderr, otherwise ``depkeeper -v check -f json | jq``
receives a corrupted document.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any, Iterator, List, Optional
from unittest import mock

import pytest
from click.testing import CliRunner, Result

from depkeeper.cli import cli
from depkeeper.commands.check import _status_stream_is_stderr
from depkeeper.core.dependency_analyzer import (
    PackageResolution,
    ResolutionResult,
    ResolutionStatus,
)
from depkeeper.models import Package
from depkeeper.utils import console as console_module

# Click < 8.2 defaults CliRunner to mix_stderr=True; only pass it when supported.
_CLIRUNNER_SUPPORTS_MIX_STDERR = "mix_stderr" in inspect.signature(
    CliRunner.__init__
).parameters


def _make_runner() -> CliRunner:
    if _CLIRUNNER_SUPPORTS_MIX_STDERR:
        return CliRunner(mix_stderr=False)
    return CliRunner()


# ---------------------------------------------------------------------------
# Fakes (no network)
# ---------------------------------------------------------------------------


class _FakeHTTPClient:
    """Async context manager standing in for :class:`HTTPClient`."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeHTTPClient":
        return self

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False


class _FakeDataStore:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def prefetch_packages(self, names: List[str]) -> None:
        return None


def _fake_checker(packages: List[Package]) -> Any:
    class _FakeVersionChecker:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def check_packages(self, requirements: Any) -> List[Package]:
            return list(packages)

    return _FakeVersionChecker


def _fake_analyzer(result: Optional[ResolutionResult]) -> Any:
    class _FakeDependencyAnalyzer:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def resolve_and_annotate_conflicts(
            self, packages: List[Package]
        ) -> Optional[ResolutionResult]:
            return result

    return _FakeDependencyAnalyzer


@pytest.fixture(autouse=True)
def _isolated_console(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Force deterministic, colourless consoles bound to the runner streams."""
    monkeypatch.setenv("NO_COLOR", "1")
    console_module.reconfigure_console()
    yield
    console_module.reconfigure_console()


# Note: ``cli()`` reconfigures the process-wide ``depkeeper`` logger (it sets
# ``propagate = False``, which blinds ``caplog`` everywhere afterwards). That is
# undone by the autouse ``_isolate_depkeeper_logger`` fixture in the root
# conftest, so no module-local guard is needed here.


def _run_check(
    tmp_path: Path,
    args: List[str],
    *,
    packages: Optional[List[Package]] = None,
    contents: str = "flask==2.0.0\n",
    resolution: Optional[ResolutionResult] = None,
) -> Result:
    """Invoke the CLI with the network layer replaced by in-memory fakes."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text(contents, encoding="utf-8")

    if packages is None:
        packages = [
            Package(
                name="flask",
                current_version="2.0.0",
                latest_version="2.3.3",
                recommended_version="2.3.3",
            )
        ]

    runner = _make_runner()
    with mock.patch("depkeeper.commands.check.HTTPClient", _FakeHTTPClient), mock.patch(
        "depkeeper.commands.check.PyPIDataStore", _FakeDataStore
    ), mock.patch(
        "depkeeper.commands.check.VersionChecker", _fake_checker(packages)
    ), mock.patch(
        "depkeeper.commands.check.DependencyAnalyzer", _fake_analyzer(resolution)
    ):
        return runner.invoke(cli, args, catch_exceptions=False)


def _resolution_with_change() -> ResolutionResult:
    return ResolutionResult(
        resolved_versions={
            "flask": PackageResolution(
                name="flask",
                original="3.0.0",
                resolved="2.3.3",
                status=ResolutionStatus.DOWNGRADED,
                conflicts=[],
            )
        },
        total_packages=1,
        packages_with_conflicts=0,
        iterations_used=2,
        converged=True,
    )


# ---------------------------------------------------------------------------
# _status_stream_is_stderr
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStatusStreamSelection:
    @pytest.mark.parametrize(
        "fmt,expected",
        [
            ("table", False),
            ("TABLE", False),
            ("simple", True),
            ("json", True),
            ("JSON", True),
        ],
    )
    def test_status_stream_selection(self, fmt: str, expected: bool) -> None:
        assert _status_stream_is_stderr(fmt) is expected


# ---------------------------------------------------------------------------
# M11 regressions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestJsonStreamPurity:
    def test_verbose_json_stdout_is_parseable(self, tmp_path: Path) -> None:
        """M11: `-v check --format json` must emit only JSON on stdout."""
        result = _run_check(
            tmp_path,
            ["-v", "check", str(tmp_path / "requirements.txt"), "--format", "json"],
            resolution=_resolution_with_change(),
        )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert [pkg["name"] for pkg in payload] == ["flask"]

        assert "[WARNING]" not in result.stdout
        assert "Resolution Summary" not in result.stdout
        assert "package(s) have updates available" in result.stderr
        assert "Resolution Summary" in result.stderr

    def test_non_verbose_json_stdout_is_parseable(self, tmp_path: Path) -> None:
        result = _run_check(
            tmp_path,
            ["check", str(tmp_path / "requirements.txt"), "--format", "json"],
        )

        assert result.exit_code == 0
        assert json.loads(result.stdout)

    def test_json_emits_empty_array_when_no_requirements(self, tmp_path: Path) -> None:
        """stdout must stay a valid JSON document even with nothing to report."""
        result = _run_check(
            tmp_path,
            ["-v", "check", str(tmp_path / "requirements.txt"), "--format", "json"],
            contents="# only a comment\n",
        )

        assert result.exit_code == 0
        assert json.loads(result.stdout) == []
        assert "No packages found" in result.stderr

    def test_json_emits_empty_array_when_all_up_to_date(self, tmp_path: Path) -> None:
        result = _run_check(
            tmp_path,
            [
                "-v",
                "check",
                str(tmp_path / "requirements.txt"),
                "--format",
                "json",
                "--outdated-only",
            ],
            packages=[
                Package(
                    name="flask",
                    current_version="2.3.3",
                    latest_version="2.3.3",
                    recommended_version="2.3.3",
                )
            ],
        )

        assert result.exit_code == 0
        assert json.loads(result.stdout) == []
        assert "All packages are up to date!" in result.stderr

    def test_parse_error_message_goes_to_stderr(self, tmp_path: Path) -> None:
        """A fatal error must not be injected into the JSON payload stream."""
        result = _run_check(
            tmp_path,
            ["check", str(tmp_path / "requirements.txt"), "--format", "json"],
            contents="!!!not a requirement!!!\n",
        )

        assert result.exit_code == 1
        assert "[ERROR]" not in result.stdout
        assert "[ERROR]" in result.stderr


@pytest.mark.unit
class TestSimpleStreamPurity:
    def test_simple_payload_has_no_status_lines(self, tmp_path: Path) -> None:
        result = _run_check(
            tmp_path,
            ["-v", "check", str(tmp_path / "requirements.txt"), "--format", "simple"],
            resolution=_resolution_with_change(),
        )

        assert result.exit_code == 0
        assert "flask" in result.stdout
        assert "[WARNING]" not in result.stdout
        assert "Resolution Summary" not in result.stdout
        assert "[WARNING]" in result.stderr


@pytest.mark.unit
class TestTableStreamUnchanged:
    def test_table_status_stays_on_stdout(self, tmp_path: Path) -> None:
        """Backward compatibility: the human format keeps status on stdout."""
        result = _run_check(
            tmp_path,
            ["check", str(tmp_path / "requirements.txt")],
            resolution=_resolution_with_change(),
        )

        assert result.exit_code == 0
        assert "Dependency Status" in result.stdout
        assert "package(s) have updates available" in result.stdout

    def test_table_resolution_summary_stays_on_stdout(self, tmp_path: Path) -> None:
        result = _run_check(
            tmp_path,
            ["-v", "check", str(tmp_path / "requirements.txt")],
            resolution=_resolution_with_change(),
        )

        assert result.exit_code == 0
        assert "Resolution Summary" in result.stdout
