"""
Shared fixtures for E2E tests.

All fixtures here are grounded in real CLI behaviour documented in README.md
and confirmed by reading the source in depkeeper/cli.py,
depkeeper/commands/check.py, depkeeper/commands/update.py, and the model files.

Design decisions:
- CliRunner is used for all CLI tests (not subprocess) unless the scenario
  explicitly requires subprocess E2E behaviour (marked @pytest.mark.e2e).
- PyPI is mocked via pytest-httpx for all tests in this directory that are
  NOT marked @pytest.mark.network.  Real-network tests are marked both
  @pytest.mark.e2e and @pytest.mark.network.
- Every requirements file fixture writes to tmp_path so no test ever touches
  the real project requirements.txt.
- Most tests pass --no-check-conflicts unless the scenario specifically
  exercises conflict detection, to avoid needing to mock the secondary
  per-version dependency API calls made by DependencyAnalyzer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pytest
from click.testing import CliRunner

from depkeeper.cli import cli  # the Click group; check/update are subcommands
from depkeeper.utils.console import reconfigure_console


# ---------------------------------------------------------------------------
# Console singleton reset — must run before every E2E test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_rich_console() -> None:
    """Reset the Rich console singleton before every test.

    The Rich console in depkeeper/utils/console.py is a module-level singleton.
    When CliRunner.invoke() runs, it replaces sys.stdout with a capture buffer.
    If the console was already created (pointing to a previous buffer or to the
    real stdout), output would bypass CliRunner's capture.

    Calling reconfigure_console() here forces the next _get_console() call —
    which happens INSIDE the CliRunner's isolation context — to create a fresh
    Console pointed at the current sys.stdout (the capture buffer).
    """
    reconfigure_console()


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------


@pytest.fixture
def cli_runner() -> CliRunner:
    """CliRunner with stderr kept separate from stdout for clean output checks."""
    return CliRunner(mix_stderr=False)


# ---------------------------------------------------------------------------
# PyPI mock response helpers
# ---------------------------------------------------------------------------


def _make_pypi_response(
    name: str,
    latest: str,
    versions: Dict[str, Optional[str]],
    requires_dist: Optional[list] = None,
) -> Dict[str, Any]:
    """Build a minimal PyPI JSON API response compatible with PyPIDataStore.

    Args:
        name: Package name.
        latest: The version string in info.version (what PyPI calls "latest").
        versions: Mapping of version string -> requires_python (None = no constraint).
        requires_dist: Dependency specifiers for the latest version.

    Returns:
        Dict matching the schema of https://pypi.org/pypi/{package}/json
    """
    releases: Dict[str, list] = {}
    for v, rp in versions.items():
        releases[v] = [{"requires_python": rp, "filename": f"{name}-{v}.tar.gz"}]

    return {
        "info": {
            "name": name,
            "version": latest,
            "requires_python": versions.get(latest),
            "requires_dist": requires_dist or [],
        },
        "releases": releases,
    }


@pytest.fixture
def flask_pypi_response() -> Dict[str, Any]:
    """Mock PyPI response for flask.

    Versions available: 2.0.0 (old), 2.3.0 (current in tests), 2.3.4 (latest
    in major 2), 3.0.3 (latest overall — different major).  This structure
    lets tests confirm major-boundary enforcement.
    """
    return _make_pypi_response(
        name="flask",
        latest="3.0.3",
        versions={
            "3.0.3": ">=3.8",
            "2.3.4": ">=3.8",
            "2.3.0": ">=3.8",
            "2.0.0": ">=3.6",
        },
    )


@pytest.fixture
def requests_pypi_response() -> Dict[str, Any]:
    """Mock PyPI response for requests.

    Versions available: 2.25.0, 2.28.0 (current in tests), 2.31.0 (latest).
    All within major 2, so the checker will recommend 2.31.0.
    """
    return _make_pypi_response(
        name="requests",
        latest="2.31.0",
        versions={
            "2.31.0": ">=3.7",
            "2.28.0": ">=3.7",
            "2.25.0": ">=3.7",
        },
    )


@pytest.fixture
def click_pypi_response() -> Dict[str, Any]:
    """Mock PyPI response for click with versions 8.0.0 and 8.1.7."""
    return _make_pypi_response(
        name="click",
        latest="8.1.7",
        versions={
            "8.1.7": ">=3.7",
            "8.0.0": ">=3.6",
        },
    )


# ---------------------------------------------------------------------------
# Requirements file fixtures — all write to tmp_path
# ---------------------------------------------------------------------------


@pytest.fixture
def outdated_requirements_file(tmp_path: Path) -> Path:
    """requirements.txt with flask 2.3.0 and requests 2.28.0, both outdated.

    Used in: happy-path check, update, dry-run, backup, -p flag tests.
    """
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("flask==2.3.0\nrequests==2.28.0\n")
    return req_file


@pytest.fixture
def all_current_requirements_file(tmp_path: Path) -> Path:
    """requirements.txt where all packages are already at their latest-in-major.

    Used in: "nothing to do" tests for check and update.
    """
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("flask==2.3.4\nrequests==2.31.0\n")
    return req_file


@pytest.fixture
def major_boundary_requirements_file(tmp_path: Path) -> Path:
    """requirements.txt with flask pinned at the latest 2.x while 3.x exists.

    PyPI mock must provide 3.0.3 as latest but 2.3.4 as latest in major 2.
    """
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("flask==2.3.4\n")
    return req_file


@pytest.fixture
def commented_requirements_file(tmp_path: Path) -> Path:
    """requirements.txt with blank lines, full-line comments, and inline comments.

    The parser must strip all of these without corrupting package names.
    Grounded in: CLAUDE.md core conventions for requirements parsing.
    """
    req_file = tmp_path / "requirements.txt"
    req_file.write_text(
        "# Web framework\n"
        "flask==2.3.0  # serves our API\n"
        "\n"
        "# HTTP library\n"
        "requests==2.28.0\n"
        "\n"
    )
    return req_file


@pytest.fixture
def include_requirements_setup(tmp_path: Path) -> Tuple[Path, Path]:
    """(main_file, base_file): main_file includes base_file via '-r'.

    Grounded in: RequirementsParser handling of -r include directive.
    """
    base_file = tmp_path / "base.txt"
    base_file.write_text("requests==2.28.0\n")

    main_file = tmp_path / "requirements.txt"
    # Use absolute path so parser can resolve the include regardless of cwd
    main_file.write_text(f"-r {base_file.name}\nflask==2.3.0\n")

    return main_file, base_file


@pytest.fixture
def nested_include_setup(tmp_path: Path) -> Tuple[Path, Path, Path]:
    """(A, B, C): A includes B via -r, B includes C via -r.

    Used to test that multi-level include chains are fully traversed.
    """
    c_file = tmp_path / "c.txt"
    c_file.write_text("click==8.0.0\n")

    b_file = tmp_path / "b.txt"
    b_file.write_text(f"-r {c_file.name}\nrequests==2.28.0\n")

    a_file = tmp_path / "a.txt"
    a_file.write_text(f"-r {b_file.name}\nflask==2.3.0\n")

    return a_file, b_file, c_file


@pytest.fixture
def circular_include_setup(tmp_path: Path) -> Tuple[Path, Path]:
    """(A, B): A includes B and B includes A — circular reference.

    The parser must detect this and raise an error rather than looping.
    """
    a_file = tmp_path / "a.txt"
    b_file = tmp_path / "b.txt"

    # Write both files referencing each other by name (same directory)
    a_file.write_text(f"-r {b_file.name}\nflask==2.3.0\n")
    b_file.write_text(f"-r {a_file.name}\nrequests==2.28.0\n")

    return a_file, b_file


@pytest.fixture
def constraint_requirements_setup(tmp_path: Path) -> Tuple[Path, Path]:
    """(main_file, constraints_file): main references constraints via -c.

    Used to test that -c constraint files narrow the version recommendation.
    """
    constraints_file = tmp_path / "constraints.txt"
    constraints_file.write_text("requests<2.30.0\n")

    main_file = tmp_path / "requirements.txt"
    main_file.write_text(f"-c {constraints_file.name}\nrequests\n")

    return main_file, constraints_file


@pytest.fixture
def vcs_requirements_file(tmp_path: Path) -> Path:
    """requirements.txt with a VCS URL entry alongside a normal package.

    Grounded in: CLAUDE.md — 'VCS URLs (git+https://)' must be handled.
    The parser stores url= on the Requirement and the VCS line must not crash.
    """
    req_file = tmp_path / "requirements.txt"
    req_file.write_text(
        "git+https://github.com/pallets/flask.git@main#egg=flask\n"
        "requests==2.28.0\n"
    )
    return req_file


@pytest.fixture
def editable_requirements_file(tmp_path: Path) -> Path:
    """requirements.txt containing '-e .' alongside a normal package.

    Grounded in: Requirement.editable field; -e is a supported directive.
    """
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("-e .\nflask==2.3.0\n")
    return req_file


@pytest.fixture
def hashed_requirements_file(tmp_path: Path) -> Path:
    """requirements.txt with --hash verification lines (pip hash-checking mode).

    Grounded in: Requirement.hashes field; '--hash' is parsed by RequirementsParser.
    """
    req_file = tmp_path / "requirements.txt"
    req_file.write_text(
        "flask==2.3.0"
        " --hash=sha256:abcd1234ef567890abcd1234ef567890"
        "abcd1234ef567890abcd1234ef567890\n"
    )
    return req_file


@pytest.fixture
def marker_requirements_file(tmp_path: Path) -> Path:
    """requirements.txt with a PEP 508 environment marker.

    Grounded in: Requirement.markers field; markers must be stripped before
    version resolution so only the package name and version specifier are used.
    """
    req_file = tmp_path / "requirements.txt"
    req_file.write_text('requests>=2.25.0; python_version > "3.6"\n')
    return req_file


@pytest.fixture
def empty_requirements_file(tmp_path: Path) -> Path:
    """requirements.txt that exists but contains no packages (0 bytes).

    Grounded in: _check_async early-return when requirements list is empty.
    """
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("")
    return req_file


@pytest.fixture
def unpinned_requirements_file(tmp_path: Path) -> Path:
    """requirements.txt with a bare unpinned package name ('flask' only).

    Grounded in: VersionChecker.extract_current_version returns None for
    specs=[], then _build_package_from_data picks highest compatible stable.
    """
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("flask\n")
    return req_file


@pytest.fixture
def mixed_specifier_requirements_file(tmp_path: Path) -> Path:
    """requirements.txt with pinned (==), range (>=), and unpinned packages.

    Grounded in: CLAUDE.md — parser handles all specifier styles in one file.
    """
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("flask==2.3.0\nrequests>=2.25.0\nclick\n")
    return req_file


@pytest.fixture
def range_lower_bound_requirements_file(tmp_path: Path) -> Path:
    """requirements.txt with 'flask>=2.0' — lower-bound-only specifier."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("flask>=2.0\n")
    return req_file


@pytest.fixture
def upper_bounded_requirements_file(tmp_path: Path) -> Path:
    """requirements.txt with 'flask>=2.0,<3.0' — explicit upper bound."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("flask>=2.0,<3.0\n")
    return req_file


@pytest.fixture
def tilde_pinned_requirements_file(tmp_path: Path) -> Path:
    """requirements.txt with 'flask~=2.3' — compatible-release operator."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("flask~=2.3\n")
    return req_file


@pytest.fixture
def not_equal_requirements_file(tmp_path: Path) -> Path:
    """requirements.txt with 'requests!=2.28.0' — not-equal exclusion."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("requests!=2.28.0\n")
    return req_file


@pytest.fixture
def compound_specifier_requirements_file(tmp_path: Path) -> Path:
    """requirements.txt with multiple operators on one package.

    'requests>=2.25,!=2.27.0,<2.30' — all three constraints apply together.
    """
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("requests>=2.25,!=2.27.0,<2.30\n")
    return req_file


@pytest.fixture
def upper_only_requirements_file(tmp_path: Path) -> Path:
    """requirements.txt with 'flask<3.0' — upper-bound only, no lower bound."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("flask<3.0\n")
    return req_file


@pytest.fixture
def prerelease_only_pypi_response() -> Dict[str, Any]:
    """Mock PyPI response where the only newer version is a pre-release.

    Stable latest: 1.9.0. Pre-release: 2.0.0a1.
    Used to verify that pre-releases are never recommended.
    """
    return _make_pypi_response(
        name="somepackage",
        latest="2.0.0a1",  # PyPI reports this as "latest" in info.version
        versions={
            "2.0.0a1": ">=3.8",
            "1.9.0": ">=3.7",
            "1.8.0": ">=3.7",
        },
    )
