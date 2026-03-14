"""
Shared fixtures for integration tests.

Integration tests exercise components working together with mocked network
calls (zero real PyPI requests).  pytest-httpx is used for all HTTP mocking.

All fixtures are grounded in real classes read from source:
- PyPIDataStore, PyPIPackageData   (depkeeper/core/data_store.py)
- VersionChecker                   (depkeeper/core/checker.py)
- RequirementsParser               (depkeeper/core/parser.py)
- Requirement                      (depkeeper/models/requirement.py)
- Package                          (depkeeper/models/package.py)
- HTTPClient                       (depkeeper/utils/http.py)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest
from packaging.version import Version

from depkeeper.core.data_store import PyPIDataStore, PyPIPackageData
from depkeeper.core.checker import VersionChecker
from depkeeper.core.parser import RequirementsParser
from depkeeper.models.requirement import Requirement
from depkeeper.models.package import Package
from depkeeper.utils.http import HTTPClient


# ---------------------------------------------------------------------------
# HTTP mocking helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_http_client() -> MagicMock:
    """MagicMock wrapping HTTPClient for tests that need a controllable client.

    Pattern mirrors tests/test_core/test_data_store.py so integration tests
    stay consistent with the existing unit test suite.
    """
    return MagicMock(spec=HTTPClient)


# ---------------------------------------------------------------------------
# PyPI response builders
# ---------------------------------------------------------------------------


def _build_pypi_response(
    name: str,
    latest: str,
    versions: Dict[str, Optional[str]],
    requires_dist: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build a minimal PyPI JSON API response.

    Args:
        name: Package name (must match PyPI canonical name).
        latest: Version string placed in info.version.
        versions: Mapping of version -> requires_python (None = no constraint).
        requires_dist: Dependency list for the latest version.

    Returns:
        Dict matching /pypi/{package}/json schema consumed by PyPIDataStore.
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
def pypi_response_factory() -> Callable[..., Dict[str, Any]]:
    """Factory fixture: returns _build_pypi_response callable.

    Allows tests to construct custom PyPI responses inline without
    duplicating the response schema.

    Example::

        def test_something(pypi_response_factory):
            resp = pypi_response_factory(
                name="mylib",
                latest="2.0.0",
                versions={"2.0.0": ">=3.8", "1.0.0": ">=3.7"},
            )
    """
    return _build_pypi_response


@pytest.fixture
def flask_pypi_response() -> Dict[str, Any]:
    """PyPI JSON response for flask with 2.x and 3.x versions.

    Versions: 2.0.0, 2.3.0, 2.3.4, 3.0.3 (latest overall, different major).
    Used to verify major-boundary enforcement in VersionChecker.
    """
    return _build_pypi_response(
        name="flask",
        latest="3.0.3",
        versions={
            "3.0.3": ">=3.8",
            "2.3.4": ">=3.8",
            "2.3.0": ">=3.8",
            "2.0.0": ">=3.6",
        },
        requires_dist=["Werkzeug>=3.0.0", "Jinja2>=3.1.2", "click>=8.1.3"],
    )


@pytest.fixture
def requests_pypi_response() -> Dict[str, Any]:
    """PyPI JSON response for requests with 2.x versions only."""
    return _build_pypi_response(
        name="requests",
        latest="2.31.0",
        versions={
            "2.31.0": ">=3.7",
            "2.28.0": ">=3.7",
            "2.25.0": ">=3.7",
        },
        requires_dist=["charset-normalizer>=2,<4", "idna>=2.5,<4"],
    )


@pytest.fixture
def click_pypi_response() -> Dict[str, Any]:
    """PyPI JSON response for click with 8.x versions."""
    return _build_pypi_response(
        name="click",
        latest="8.1.7",
        versions={
            "8.1.7": ">=3.7",
            "8.0.0": ">=3.6",
        },
    )


# ---------------------------------------------------------------------------
# PyPIPackageData fixtures (pre-parsed, no HTTP required)
# ---------------------------------------------------------------------------


@pytest.fixture
def flask_package_data() -> PyPIPackageData:
    """Pre-parsed PyPIPackageData for flask.

    Contains versions in major 2 (2.0.0, 2.3.0, 2.3.4) and major 3 (3.0.3).
    Grounded in: PyPIPackageData dataclass fields from data_store.py.
    """
    return PyPIPackageData(
        name="flask",
        latest_version="3.0.3",
        latest_requires_python=">=3.8",
        latest_dependencies=["Werkzeug>=3.0.0", "Jinja2>=3.1.2", "click>=8.1.3"],
        all_versions=["3.0.3", "2.3.4", "2.3.0", "2.0.0"],
        parsed_versions=[
            ("3.0.3", Version("3.0.3")),
            ("2.3.4", Version("2.3.4")),
            ("2.3.0", Version("2.3.0")),
            ("2.0.0", Version("2.0.0")),
        ],
        python_requirements={
            "3.0.3": ">=3.8",
            "2.3.4": ">=3.8",
            "2.3.0": ">=3.8",
            "2.0.0": ">=3.6",
        },
        releases={},
        dependencies_cache={},
    )


@pytest.fixture
def requests_package_data() -> PyPIPackageData:
    """Pre-parsed PyPIPackageData for requests (2.x only, no major jump)."""
    return PyPIPackageData(
        name="requests",
        latest_version="2.31.0",
        latest_requires_python=">=3.7",
        latest_dependencies=["charset-normalizer>=2,<4", "idna>=2.5,<4"],
        all_versions=["2.31.0", "2.28.0", "2.25.0"],
        parsed_versions=[
            ("2.31.0", Version("2.31.0")),
            ("2.28.0", Version("2.28.0")),
            ("2.25.0", Version("2.25.0")),
        ],
        python_requirements={
            "2.31.0": ">=3.7",
            "2.28.0": ">=3.7",
            "2.25.0": ">=3.7",
        },
        releases={},
        dependencies_cache={},
    )


@pytest.fixture
def click_package_data() -> PyPIPackageData:
    """Pre-parsed PyPIPackageData for click (8.x only)."""
    return PyPIPackageData(
        name="click",
        latest_version="8.1.7",
        latest_requires_python=">=3.7",
        latest_dependencies=[],
        all_versions=["8.1.7", "8.0.0"],
        parsed_versions=[
            ("8.1.7", Version("8.1.7")),
            ("8.0.0", Version("8.0.0")),
        ],
        python_requirements={
            "8.1.7": ">=3.7",
            "8.0.0": ">=3.6",
        },
        releases={},
        dependencies_cache={},
    )


# ---------------------------------------------------------------------------
# Requirement model fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def flask_requirement() -> Requirement:
    """Parsed Requirement for 'flask==2.3.0'.

    Grounded in: Requirement dataclass (models/requirement.py).
    """
    return Requirement(
        name="flask",
        specs=[("==", "2.3.0")],
        extras=[],
        line_number=1,
        raw_line="flask==2.3.0\n",
    )


@pytest.fixture
def requests_requirement() -> Requirement:
    """Parsed Requirement for 'requests==2.28.0'."""
    return Requirement(
        name="requests",
        specs=[("==", "2.28.0")],
        extras=[],
        line_number=2,
        raw_line="requests==2.28.0\n",
    )


@pytest.fixture
def click_requirement() -> Requirement:
    """Parsed Requirement for 'click==8.0.0'."""
    return Requirement(
        name="click",
        specs=[("==", "8.0.0")],
        extras=[],
        line_number=3,
        raw_line="click==8.0.0\n",
    )


@pytest.fixture
def flask_range_requirement() -> Requirement:
    """Parsed Requirement for 'flask>=2.0' — range lower-bound only."""
    return Requirement(
        name="flask",
        specs=[(">=", "2.0")],
        extras=[],
        line_number=1,
        raw_line="flask>=2.0\n",
    )


@pytest.fixture
def unpinned_flask_requirement() -> Requirement:
    """Parsed Requirement for 'flask' — fully unpinned, specs=[]."""
    return Requirement(
        name="flask",
        specs=[],
        extras=[],
        line_number=1,
        raw_line="flask\n",
    )


# ---------------------------------------------------------------------------
# Compound fixtures: lists of requirements
# ---------------------------------------------------------------------------


@pytest.fixture
def two_outdated_requirements(
    flask_requirement: Requirement,
    requests_requirement: Requirement,
) -> List[Requirement]:
    """[flask==2.3.0, requests==2.28.0] — both have updates available."""
    return [flask_requirement, requests_requirement]


@pytest.fixture
def three_mixed_requirements(
    flask_requirement: Requirement,
    requests_requirement: Requirement,
    click_requirement: Requirement,
) -> List[Requirement]:
    """[flask==2.3.0, requests==2.28.0, click==8.0.0] — three packages."""
    return [flask_requirement, requests_requirement, click_requirement]


# ---------------------------------------------------------------------------
# Parser fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def parser() -> RequirementsParser:
    """Fresh RequirementsParser instance.

    Grounded in: RequirementsParser from core/__init__.py.
    Reset between tests via fixture scoping (function scope by default).
    """
    return RequirementsParser()


# ---------------------------------------------------------------------------
# Factory fixture for temporary requirements files
# ---------------------------------------------------------------------------


@pytest.fixture
def make_requirements_file(tmp_path: Path):
    """Factory: creates a named requirements file in tmp_path with given content.

    Usage::

        def test_foo(make_requirements_file):
            req_file = make_requirements_file("flask==2.3.0\\n")
            # req_file is a Path pointing to tmp_path/requirements.txt
    """

    def _make(content: str, filename: str = "requirements.txt") -> Path:
        req_file = tmp_path / filename
        req_file.write_text(content, encoding="utf-8")
        return req_file

    return _make


# ---------------------------------------------------------------------------
# Pre-wired PyPIDataStore fixture (with flask + requests already cached)
# ---------------------------------------------------------------------------


@pytest.fixture
def data_store_with_flask_and_requests(
    mock_http_client: MagicMock,
    flask_package_data: PyPIPackageData,
    requests_package_data: PyPIPackageData,
) -> PyPIDataStore:
    """PyPIDataStore pre-seeded with flask and requests data (no HTTP calls).

    Used in integration tests that need a ready data store without going
    through the HTTP layer.
    """
    store = PyPIDataStore(mock_http_client)
    store._package_data["flask"] = flask_package_data
    store._package_data["requests"] = requests_package_data
    return store


@pytest.fixture
def version_checker_no_infer(
    data_store_with_flask_and_requests: PyPIDataStore,
) -> VersionChecker:
    """VersionChecker in strict mode (infer_version_from_constraints=False).

    Used to test that range specifiers are NOT used to infer a current version
    when strict mode is active.
    """
    return VersionChecker(
        data_store=data_store_with_flask_and_requests,
        infer_version_from_constraints=False,
    )


@pytest.fixture
def version_checker_with_infer(
    data_store_with_flask_and_requests: PyPIDataStore,
) -> VersionChecker:
    """VersionChecker in default mode (infer_version_from_constraints=True).

    Used to test that '>=' specifiers cause the lower bound to be treated as
    the 'current' version for major-boundary purposes.
    """
    return VersionChecker(
        data_store=data_store_with_flask_and_requests,
        infer_version_from_constraints=True,
    )


# ---------------------------------------------------------------------------
# Include/circular fixtures for file-parsing edge-case tests
# ---------------------------------------------------------------------------


@pytest.fixture
def circular_include_setup(tmp_path: Path) -> Tuple[Path, Path]:
    """Create a circular -r include chain: A includes B, B includes A.

    Returns (a_file, b_file) so tests can parse from a_file.
    """
    a_file = tmp_path / "a.txt"
    b_file = tmp_path / "b.txt"
    a_file.write_text(f"-r {b_file.name}\nflask==2.3.0\n", encoding="utf-8")
    b_file.write_text(f"-r {a_file.name}\nrequests==2.28.0\n", encoding="utf-8")
    return a_file, b_file


@pytest.fixture
def nested_include_setup(tmp_path: Path) -> Tuple[Path, Path, Path]:
    """Create a three-level -r include chain: A → B → C.

    - A includes B and has flask==2.3.0
    - B includes C and has requests==2.28.0
    - C has click==8.0.0

    Returns (a_file, b_file, c_file).
    """
    c_file = tmp_path / "c.txt"
    b_file = tmp_path / "b.txt"
    a_file = tmp_path / "a.txt"
    c_file.write_text("click==8.0.0\n", encoding="utf-8")
    b_file.write_text(f"-r {c_file.name}\nrequests==2.28.0\n", encoding="utf-8")
    a_file.write_text(f"-r {b_file.name}\nflask==2.3.0\n", encoding="utf-8")
    return a_file, b_file, c_file
