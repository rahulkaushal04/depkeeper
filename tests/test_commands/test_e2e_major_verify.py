"""Black-box tests of ``--allow-major`` and ``update --verify`` against real PyPI and pip.

Skipped when PyPI is unreachable. Each ``xfail(strict=True)`` documents a known
defect; remove the marker when it is fixed.
"""

from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from depkeeper.cli import cli
from depkeeper.core.verify import verify_plan


def _online() -> bool:
    try:
        socket.create_connection(("pypi.org", 443), timeout=3).close()
        return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(not _online(), reason="PyPI unreachable"),
]


@pytest.fixture(autouse=True)
def _cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # isolate from the repo's own depkeeper config


def _runner() -> CliRunner:
    """Return a runner that keeps stderr separate (click 8.1 needs mix_stderr)."""
    try:
        return CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:  # click >= 8.2 always separates the streams
        return CliRunner()


def _run(*args: str) -> Any:
    return _runner().invoke(cli, list(args))


needs_pip = pytest.mark.skipif(
    importlib.util.find_spec("pip") is None,
    reason="pip is not installed in this interpreter",
)


def _check_json(tmp_path: Path, body: str, *extra: str) -> dict:
    req = tmp_path / "requirements.txt"
    req.write_text(body)
    res = _run("check", "-f", "json", *extra, str(req))
    assert res.exit_code == 0, res.output + res.stderr
    return {p["name"]: p for p in json.loads(res.stdout)}


# --- Feature 1: opt-in major upgrades ---------------------------------------


def test_default_keeps_major_and_reports_major_available(tmp_path: Path) -> None:
    pkgs = _check_json(tmp_path, "django>=3.2,<5.0\n")
    assert pkgs["django"]["versions"]["recommended"].startswith("3.2.")
    assert pkgs["django"]["major_available"].startswith("4.2.")


def test_allow_major_moves_floor_and_keeps_declared_upper_bound(tmp_path: Path) -> None:
    pkgs = _check_json(tmp_path, "django>=3.2,<5.0\n", "--allow-major", "Django")
    assert pkgs["django"]["versions"]["recommended"].startswith("4.2.")
    assert "major_available" not in pkgs["django"]

    req = tmp_path / "requirements.txt"
    res = _run("update", "-y", "--allow-major", "django", str(req))
    assert res.exit_code == 0, res.output
    line = req.read_text().strip()
    assert line.startswith("django>=4.2.") and line.endswith(",<5.0")
    assert "1 major upgrade(s) applied: django" in res.output + res.stderr


def test_max_update_minor_wins_over_allow_major(tmp_path: Path) -> None:
    req = tmp_path / "requirements.txt"
    req.write_text("django>=3.2,<5.0\n")
    res = _run(
        "update", "-y", "--max-update", "minor", "--allow-major", "django", str(req)
    )
    assert res.exit_code == 0, res.output
    assert req.read_text().startswith("django>=3.2.25")


def test_unknown_allow_major_name_warns_once(tmp_path: Path) -> None:
    req = tmp_path / "requirements.txt"
    req.write_text("requests==2.25.0\n")
    res = _run("check", "--allow-major", "nosuch", str(req))
    assert (res.output + res.stderr).count(
        "--allow-major nosuch: not in the requirements"
    ) == 1


def test_config_allow_major_is_honoured(tmp_path: Path) -> None:
    (tmp_path / "depkeeper.toml").write_text(
        "[depkeeper.packages.DJANGO]\nallow_major = true\n"
    )
    req = tmp_path / "requirements.txt"
    req.write_text("django>=3.2,<5.0\nurllib3>=1.26,<3\n")
    res = _run("check", "-f", "json", str(req))
    pkgs = {p["name"]: p for p in json.loads(res.stdout)}
    assert pkgs["django"]["versions"]["recommended"].startswith("4.2.")
    assert pkgs["urllib3"]["versions"]["recommended"].startswith("1.")


def test_python_38_target_is_respected_under_allow_major(tmp_path: Path) -> None:
    pkgs = _check_json(
        tmp_path, "django>=3.2,<5.0\n", "--allow-major", "*", "--python-version", "3.8"
    )
    assert pkgs["django"]["versions"]["recommended"].startswith("4.2.")


def test_compatible_release_upper_bound_is_never_crossed(tmp_path: Path) -> None:
    pkgs = _check_json(tmp_path, "click~=7.0\n", "--allow-major", "click")
    assert pkgs["click"]["versions"]["recommended"].startswith("7.")


def test_major_available_respects_compatible_release(tmp_path: Path) -> None:
    pkgs = _check_json(tmp_path, "click~=7.0\n")
    assert "major_available" not in pkgs["click"]


# --- Feature 2: update --verify ---------------------------------------------


def _pip_supports_target() -> bool:
    r = verify_plan(["packaging==24.0"], python_version="3.9")
    return not r.skipped


@needs_pip
def test_good_plan_prints_what_was_verified(tmp_path: Path) -> None:
    req = tmp_path / "requirements.txt"
    req.write_text("requests==2.25.0\n")
    res = _run("update", "-y", "--verify", str(req))
    out = res.output + res.stderr
    assert res.exit_code == 0, out
    assert "--verify: pip " in out and " resolved " in out and " for Python " in out
    assert req.read_text() != "requests==2.25.0\n"


@needs_pip
def test_conflicting_plan_exits_1_and_leaves_file_untouched(tmp_path: Path) -> None:
    req = tmp_path / "requirements.txt"
    req.write_text("flask==3.0.3\nwerkzeug==2.0.3\n")
    res = _run("update", "-y", "--verify", str(req))
    assert res.exit_code == 1
    assert "Cannot install flask==3.0.3 and werkzeug==2.0.3" in res.output + res.stderr
    assert req.read_text() == "flask==3.0.3\nwerkzeug==2.0.3\n"


@needs_pip
def test_sdist_only_release_is_skipped_not_failed() -> None:
    # pycrypto 2.6.1 ships only a source distribution.
    r = verify_plan(["pycrypto==2.6.1"])
    assert r.skipped and not r.ok and "without building it" in r.message


@needs_pip
def test_nonexistent_version_fails_with_clear_message() -> None:
    r = verify_plan(["requests==999.0.0"])
    assert not r.ok and not r.skipped and "does not exist" in r.message


@needs_pip
def test_timeout_is_skipped_and_leaves_no_orphan_pip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from depkeeper.core import verify as verify_mod

    real_run = verify_mod._run
    req_files = []

    def spy(args: Any, timeout: float) -> Any:
        if "-r" in args:  # tell our pip apart from other processes on the machine
            req_files.append(args[args.index("-r") + 1])
        return real_run(args, timeout)

    monkeypatch.setattr(verify_mod, "_run", spy)
    r = verify_plan(["django==4.2.30", "flask==3.1.0", "pandas==2.2.3"], timeout=0.01)
    assert r.skipped and "timed out" in r.message
    assert len(req_files) == 1
    ps = subprocess.run(
        ["ps", "-axo", "command"], capture_output=True, text=True, check=False
    ).stdout
    assert req_files[0] not in ps


@needs_pip
def test_constraints_on_listed_package_are_applied(tmp_path: Path) -> None:
    (tmp_path / "cons.txt").write_text("requests<2.30\n")
    req = tmp_path / "requirements.txt"
    req.write_text("-c cons.txt\nrequests==2.25.0\n")
    # An explicit target keeps the plan independent of the Python running the test.
    res = _run("update", "-y", "--verify", "--python-version", "3.12", str(req))
    out = res.output + res.stderr
    assert res.exit_code == 0, out
    assert "1 constraint applied" in out


@needs_pip
def test_constraint_on_transitive_dependency_is_enforced(tmp_path: Path) -> None:
    (tmp_path / "cons.txt").write_text("urllib3<1.26\n")
    req = tmp_path / "requirements.txt"
    req.write_text(
        "-c cons.txt\nrequests==2.25.0\n"
    )  # update targets 2.34.x: needs urllib3>=1.26
    res = _run("update", "-y", "--verify", "--python-version", "3.12", str(req))
    assert res.exit_code == 1
    assert req.read_text().endswith("requests==2.25.0\n")


@needs_pip
def test_verify_covers_unchanged_requirements_when_selecting_packages(
    tmp_path: Path,
) -> None:
    req = tmp_path / "requirements.txt"
    req.write_text("flask==3.0.3\nwerkzeug==2.0.3\nrequests==2.25.0\n")
    res = _run("update", "-y", "--verify", "-p", "requests", str(req))
    assert res.exit_code == 1


@needs_pip
def test_python_incompatible_release_is_not_reported_as_nonexistent() -> None:
    if not _pip_supports_target():
        pytest.skip("pip too old for --python-version with --dry-run")
    r = verify_plan(["numpy==2.2.0"], python_version="3.9")
    assert not r.ok  # pip does reject it
    assert "does not exist" not in r.message


def test_crashing_pip_is_skipped_not_failed(tmp_path: Path) -> None:
    fake = tmp_path / "py"
    fake.write_text(
        "#!/bin/sh\n"
        'if [ "$3" = "--version" ]; then echo "pip 23.0.1 from /x (python 3.12)"; exit 0; fi\n'
        "echo \"AttributeError: module 'pkgutil' has no attribute 'ImpImporter'\" >&2\n"
        "exit 1\n"
    )
    fake.chmod(0o755)
    r = verify_plan(["requests==2.31.0"], python_executable=str(fake))
    assert r.skipped
