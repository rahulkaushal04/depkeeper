"""
Integration tests: PyPIDataStore caching behaviour.

Covers scenarios 52, 58, 59 from the scenario document.

- SCENARIO-52: Same package fetched from PyPI only once; second call is cache hit
- SCENARIO-58: prefetch_packages warms the cache for multiple packages concurrently
- SCENARIO-59: get_version_dependencies uses cached layer-1 data; no extra HTTP call

All tests use a MagicMock HTTPClient with an AsyncMock .get method so that call
counts can be asserted.  No real network connections are made.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from depkeeper.core.data_store import PyPIDataStore, PyPIPackageData
from depkeeper.utils.http import HTTPClient


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _pypi_response(
    name: str,
    latest: str,
    versions: Dict[str, Optional[str]],
    requires_dist: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Minimal PyPI JSON API response for a package."""
    releases: Dict[str, list] = {
        v: [{"requires_python": rp, "filename": f"{name}-{v}.tar.gz"}]
        for v, rp in versions.items()
    }
    return {
        "info": {
            "name": name,
            "version": latest,
            "requires_python": versions.get(latest),
            "requires_dist": requires_dist or [],
        },
        "releases": releases,
    }


def _version_response(deps: List[str]) -> Dict[str, Any]:
    """Minimal PyPI /pypi/{name}/{version}/json response."""
    return {
        "info": {
            "requires_dist": deps,
        }
    }


def _make_async_client(*responses: Dict[str, Any]) -> MagicMock:
    """Build a mock HTTPClient whose .get returns each response in order.

    If only one response is supplied it is returned for every call.
    If multiple responses are supplied they are consumed in sequence.
    """
    mock_client = MagicMock(spec=HTTPClient)

    if len(responses) == 1:
        mock_response = MagicMock()
        mock_response.json.return_value = responses[0]
        mock_client.get = AsyncMock(return_value=mock_response)
    else:
        side_effects = []
        for resp in responses:
            mock_response = MagicMock()
            mock_response.json.return_value = resp
            side_effects.append(mock_response)
        mock_client.get = AsyncMock(side_effect=side_effects)

    return mock_client


# ---------------------------------------------------------------------------
# SCENARIO-52 — Same package fetched exactly once; second call is cache hit
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_same_package_fetched_only_once() -> None:
    """get_package_data('flask') triggers one HTTP call; the second is a cache hit.

    Implementation: PyPIDataStore.get_package_data uses double-checked locking
    (fast-path check before the semaphore, second check inside it).  Once
    _package_data[normalised_name] is populated, subsequent calls return
    immediately without entering the semaphore.
    """
    flask_resp = _pypi_response(
        name="flask",
        latest="2.3.4",
        versions={"2.3.4": ">=3.8", "2.3.0": ">=3.8"},
    )
    client = _make_async_client(flask_resp)
    store = PyPIDataStore(client)

    # First call — should hit the network
    data1 = await store.get_package_data("flask")
    assert data1.name == "flask"
    assert data1.latest_version == "2.3.4"
    assert client.get.call_count == 1

    # Second call — should return from cache without another HTTP call
    data2 = await store.get_package_data("flask")
    assert data2 is data1  # same object, not a copy
    assert client.get.call_count == 1  # still exactly one HTTP call


@pytest.mark.integration
async def test_case_insensitive_name_is_also_cache_hit() -> None:
    """get_package_data normalises the name, so 'Flask' and 'flask' share cache.

    Implementation: _normalize() lowercases and replaces underscores with hyphens
    before the cache lookup, so different capitalisations resolve to the same key.
    """
    flask_resp = _pypi_response(
        name="flask",
        latest="2.3.4",
        versions={"2.3.4": ">=3.8"},
    )
    client = _make_async_client(flask_resp)
    store = PyPIDataStore(client)

    # Fetch with different capitalisations
    await store.get_package_data("Flask")
    await store.get_package_data("flask")
    await store.get_package_data("FLASK")

    # Despite three calls, only one HTTP request was made
    assert client.get.call_count == 1


@pytest.mark.integration
async def test_two_different_packages_make_two_fetches() -> None:
    """Each distinct package name triggers its own HTTP fetch.

    Verifies that caching is per-package: flask and requests each get one call.
    """
    flask_resp = _pypi_response("flask", "2.3.4", {"2.3.4": ">=3.8"})
    requests_resp = _pypi_response("requests", "2.31.0", {"2.31.0": ">=3.7"})
    client = _make_async_client(flask_resp, requests_resp)
    store = PyPIDataStore(client)

    flask = await store.get_package_data("flask")
    requests = await store.get_package_data("requests")

    assert flask.name == "flask"
    assert requests.name == "requests"
    assert client.get.call_count == 2

    # Repeat fetches are still served from cache
    await store.get_package_data("flask")
    await store.get_package_data("requests")
    assert client.get.call_count == 2


# ---------------------------------------------------------------------------
# SCENARIO-58 — prefetch_packages warms cache for multiple packages
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_prefetch_packages_warms_cache() -> None:
    """prefetch_packages fires concurrent fetches and populates _package_data.

    After prefetch_packages(['flask', 'requests']):
    - Both are in _package_data (cache is warm)
    - Subsequent get_package_data calls for either package do NOT make HTTP calls
    """
    flask_resp = _pypi_response("flask", "2.3.4", {"2.3.4": ">=3.8"})
    requests_resp = _pypi_response("requests", "2.31.0", {"2.31.0": ">=3.7"})
    client = _make_async_client(flask_resp, requests_resp)
    store = PyPIDataStore(client)

    await store.prefetch_packages(["flask", "requests"])

    # Cache must be warm for both packages
    assert store.get_cached_package("flask") is not None
    assert store.get_cached_package("requests") is not None

    # Call count: exactly two (one per package)
    assert client.get.call_count == 2

    # Subsequent get_package_data — no new HTTP calls
    flask = await store.get_package_data("flask")
    requests = await store.get_package_data("requests")
    assert flask.latest_version == "2.3.4"
    assert requests.latest_version == "2.31.0"
    assert client.get.call_count == 2


@pytest.mark.integration
async def test_prefetch_packages_skips_already_cached() -> None:
    """prefetch_packages does NOT re-fetch packages already in the cache.

    If flask was fetched individually before prefetch, it must not be
    fetched again during the prefetch call.
    """
    flask_resp = _pypi_response("flask", "2.3.4", {"2.3.4": ">=3.8"})
    requests_resp = _pypi_response("requests", "2.31.0", {"2.31.0": ">=3.7"})
    client = _make_async_client(flask_resp, requests_resp)
    store = PyPIDataStore(client)

    # Pre-warm flask manually
    await store.get_package_data("flask")
    assert client.get.call_count == 1

    # prefetch including flask again — only requests should be fetched
    await store.prefetch_packages(["flask", "requests"])
    assert client.get.call_count == 2  # only one additional call (for requests)


@pytest.mark.integration
async def test_prefetch_packages_handles_unknown_package_gracefully() -> None:
    """prefetch_packages silences per-package errors; other packages still cached.

    Implementation: asyncio.gather(..., return_exceptions=True) swallows failures.
    One failing package must not prevent the others from being cached.
    """
    from depkeeper.exceptions import NetworkError

    flask_resp = _pypi_response("flask", "2.3.4", {"2.3.4": ">=3.8"})
    client = MagicMock(spec=HTTPClient)

    # First call (for flask or totally-missing, order is async) — give flask success
    # and totally-missing a 404-style NetworkError
    call_count = 0

    async def mock_get(url: str):
        nonlocal call_count
        call_count += 1
        if "totally-missing" in url:
            raise NetworkError("404", status_code=404)
        mock_resp = MagicMock()
        mock_resp.json.return_value = flask_resp
        return mock_resp

    client.get = mock_get
    store = PyPIDataStore(client)

    # Should not raise even though totally-missing errors
    await store.prefetch_packages(["flask", "totally-missing"])

    # flask must be cached; totally-missing must not be
    assert store.get_cached_package("flask") is not None
    assert store.get_cached_package("totally-missing") is None


# ---------------------------------------------------------------------------
# SCENARIO-59 — get_version_dependencies uses cached data (no extra HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_version_dependencies_uses_layer1_cache() -> None:
    """get_version_dependencies returns from _version_deps_cache without HTTP.

    When _version_deps_cache['flask==2.3.4'] is pre-seeded, the method must
    return immediately without calling http_client.get.

    Implementation: Layer 1 check (fast path) in get_version_dependencies.
    """
    client = MagicMock(spec=HTTPClient)
    client.get = AsyncMock()  # should never be called
    store = PyPIDataStore(client)

    # Pre-seed layer-1 cache directly
    store._version_deps_cache["flask==2.3.4"] = ["werkzeug>=2.3.0", "jinja2>=3.1.2"]

    deps = await store.get_version_dependencies("flask", "2.3.4")

    assert deps == ["werkzeug>=2.3.0", "jinja2>=3.1.2"]
    client.get.assert_not_called()


@pytest.mark.integration
async def test_get_version_dependencies_uses_layer2_latest_version() -> None:
    """get_version_dependencies returns latest_dependencies without extra HTTP.

    When _package_data is populated and the requested version == latest_version,
    Layer 2 serves the response from latest_dependencies without HTTP.
    """
    from packaging.version import Version

    client = MagicMock(spec=HTTPClient)
    client.get = AsyncMock()  # must not be called

    store = PyPIDataStore(client)
    store._package_data["flask"] = PyPIPackageData(
        name="flask",
        latest_version="2.3.4",
        latest_requires_python=">=3.8",
        latest_dependencies=["werkzeug>=2.3.0"],
        all_versions=["2.3.4", "2.3.0"],
        parsed_versions=[("2.3.4", Version("2.3.4")), ("2.3.0", Version("2.3.0"))],
        python_requirements={"2.3.4": ">=3.8", "2.3.0": ">=3.8"},
        releases={},
        dependencies_cache={},
    )

    deps = await store.get_version_dependencies("flask", "2.3.4")

    assert deps == ["werkzeug>=2.3.0"]
    client.get.assert_not_called()


@pytest.mark.integration
async def test_get_version_dependencies_uses_layer2_dependencies_cache() -> None:
    """get_version_dependencies reads from PyPIPackageData.dependencies_cache.

    When the requested version is not the latest but IS in the package's
    dependencies_cache, Layer 2 serves the response without HTTP.
    """
    from packaging.version import Version

    client = MagicMock(spec=HTTPClient)
    client.get = AsyncMock()

    store = PyPIDataStore(client)
    store._package_data["flask"] = PyPIPackageData(
        name="flask",
        latest_version="2.3.4",
        latest_requires_python=">=3.8",
        latest_dependencies=["werkzeug>=2.3.0"],
        all_versions=["2.3.4", "2.3.0"],
        parsed_versions=[("2.3.4", Version("2.3.4")), ("2.3.0", Version("2.3.0"))],
        python_requirements={"2.3.4": ">=3.8", "2.3.0": ">=3.8"},
        releases={},
        # 2.3.0 is NOT the latest, but IS in dependencies_cache
        dependencies_cache={"2.3.0": ["werkzeug>=1.0.0"]},
    )

    deps = await store.get_version_dependencies("flask", "2.3.0")

    assert deps == ["werkzeug>=1.0.0"]
    client.get.assert_not_called()


@pytest.mark.integration
async def test_get_version_dependencies_caches_result_after_fetch() -> None:
    """After a layer-3 HTTP fetch, the result is stored in _version_deps_cache.

    The second call for the same version must be served from layer-1 cache
    with no additional HTTP call.
    """
    flask_version_resp = _version_response(["werkzeug>=2.3.0"])
    client = _make_async_client(flask_version_resp)
    store = PyPIDataStore(client)

    # First call — triggers layer-3 HTTP fetch
    deps1 = await store.get_version_dependencies("flask", "2.3.0")
    assert client.get.call_count == 1

    # Second call — must hit layer-1 cache
    deps2 = await store.get_version_dependencies("flask", "2.3.0")
    assert deps2 == deps1
    assert client.get.call_count == 1  # no second HTTP call
