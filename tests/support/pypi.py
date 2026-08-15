"""An in-memory PyPI data store plus a registry of real release histories.

Why real data
-------------
Resolver behaviour is dominated by the *shape* of a dependency graph: how many
versions sit between two majors, whether an upper bound leaves a usable
candidate, whether stepping a source package back actually relaxes the
constraint. Synthetic ``["1.0.0", "2.0.0"]`` histories collapse all of those
distinctions, so a resolver bug can pass every test and still corrupt a real
requirements file.

:data:`ECOSYSTEM` therefore mirrors published PyPI metadata for a slice of the
ecosystem depkeeper is actually pointed at (Flask, Requests, Django, Celery,
pandas). The dependency edges are the real ``requires_dist`` constraints, which
is what makes the Flask/Werkzeug and Celery/Kombu scenarios genuinely
conflicting rather than artificially so.

The data is a *snapshot*, not a live mirror: tests assert against it directly,
so it must stay stable. Add versions rather than moving existing ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from packaging.version import parse

from depkeeper.core.data_store import PyPIDataStore, PyPIPackageData
from depkeeper.exceptions import PyPIError


@dataclass(frozen=True)
class Release:
    """One published release of a distribution.

    Attributes:
        version: PEP 440 version string.
        requires_python: The release's ``requires_python`` marker, if any.
        requires: Base (non-extra) runtime dependency specifiers, exactly as
            PyPI reports them in ``requires_dist``.
    """

    version: str
    requires_python: Optional[str] = None
    requires: Sequence[str] = ()


@dataclass(frozen=True)
class Distribution:
    """A distribution's published release history.

    Attributes:
        name: PEP 503 normalised distribution name.
        releases: Releases in ascending version order.
    """

    name: str
    releases: Sequence[Release] = field(default_factory=tuple)

    @property
    def versions(self) -> List[str]:
        """Version strings, newest first (matching ``PyPIPackageData``)."""
        return sorted((r.version for r in self.releases), key=parse, reverse=True)

    @property
    def latest(self) -> str:
        """Newest published version string."""
        return self.versions[0]

    def release(self, version: str) -> Release:
        """Return the :class:`Release` for *version*.

        Raises:
            KeyError: No such version is registered.
        """
        for candidate in self.releases:
            if candidate.version == version:
                return candidate
        raise KeyError(f"{self.name} has no release {version}")


def _dist(name: str, *releases: Release) -> Distribution:
    return Distribution(name=name, releases=releases)


# ---------------------------------------------------------------------------
# Snapshot of real PyPI metadata
# ---------------------------------------------------------------------------

#: Real release histories and dependency edges, keyed by normalised name.
#:
#: The Flask 2.3.3 -> ``Werkzeug>=2.3.7`` edge and the Celery 5.3.6 ->
#: ``kombu>=5.3.4,<6.0`` edge are the two graphs most resolver tests build on:
#: both have a satisfiable answer that requires *moving* a package, and both
#: have a neighbouring version whose constraint is looser.
ECOSYSTEM: Dict[str, Distribution] = {
    dist.name: dist
    for dist in (
        _dist(
            "flask",
            Release("2.0.3", ">=3.6", ("Werkzeug>=2.0", "Jinja2>=3.0", "click>=7.1.2")),
            Release("2.1.3", ">=3.7", ("Werkzeug>=2.0", "Jinja2>=3.0", "click>=8.0")),
            Release("2.2.5", ">=3.7", ("Werkzeug>=2.2.2", "Jinja2>=3.0", "click>=8.0")),
            Release(
                "2.3.3",
                ">=3.8",
                ("Werkzeug>=2.3.7", "Jinja2>=3.1.2", "click>=8.1.3", "blinker>=1.6.2"),
            ),
            Release(
                "3.0.3",
                ">=3.8",
                ("Werkzeug>=3.0.0", "Jinja2>=3.1.2", "click>=8.1.3", "blinker>=1.6.2"),
            ),
        ),
        _dist(
            "werkzeug",
            Release("2.0.3", ">=3.6"),
            Release("2.1.2", ">=3.7"),
            Release("2.2.3", ">=3.7", ("MarkupSafe>=2.1.1",)),
            Release("2.3.7", ">=3.8", ("MarkupSafe>=2.1.1",)),
            Release("3.0.3", ">=3.8", ("MarkupSafe>=2.1.1",)),
        ),
        _dist(
            "jinja2",
            Release("3.0.3", ">=3.6", ("MarkupSafe>=2.0",)),
            Release("3.1.2", ">=3.7", ("MarkupSafe>=2.0",)),
            Release("3.1.4", ">=3.7", ("MarkupSafe>=2.0",)),
        ),
        _dist(
            "markupsafe",
            Release("2.0.1", ">=3.6"),
            Release("2.1.5", ">=3.7"),
        ),
        _dist(
            "click",
            Release("8.0.4", ">=3.6"),
            Release("8.1.3", ">=3.7"),
            Release("8.1.7", ">=3.7"),
        ),
        _dist("blinker", Release("1.6.2", ">=3.7"), Release("1.8.2", ">=3.8")),
        _dist(
            "requests",
            Release(
                "2.25.1",
                ">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*",
                ("urllib3<1.27,>=1.21.1", "certifi>=2017.4.17", "idna<3,>=2.5"),
            ),
            Release(
                "2.28.2",
                ">=3.7, <4",
                ("urllib3<1.27,>=1.21.1", "certifi>=2017.4.17", "idna<4,>=2.5"),
            ),
            Release(
                "2.31.0",
                ">=3.7",
                ("urllib3<3,>=1.21.1", "certifi>=2017.4.17", "idna<4,>=2.5"),
            ),
            Release(
                "2.32.3",
                ">=3.8",
                ("urllib3<3,>=1.21.1", "certifi>=2017.4.17", "idna<4,>=2.5"),
            ),
        ),
        _dist(
            "urllib3",
            Release("1.26.5", ">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*"),
            Release("1.26.18", ">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*"),
            Release("2.0.7", ">=3.7"),
            Release("2.2.2", ">=3.8"),
        ),
        _dist("certifi", Release("2023.7.22", ">=3.6"), Release("2024.7.4", ">=3.6")),
        _dist("idna", Release("2.10", ">=3.5"), Release("3.7", ">=3.5")),
        _dist(
            "django",
            Release("3.2.25", ">=3.6", ("asgiref<4,>=3.3.2", "sqlparse>=0.2.2")),
            Release("4.1.13", ">=3.8", ("asgiref<4,>=3.5.2", "sqlparse>=0.3.1")),
            Release("4.2.11", ">=3.8", ("asgiref<4,>=3.6.0", "sqlparse>=0.3.1")),
            Release("5.0.6", ">=3.10", ("asgiref<4,>=3.7.0", "sqlparse>=0.3.1")),
        ),
        _dist("asgiref", Release("3.5.2", ">=3.7"), Release("3.8.1", ">=3.8")),
        _dist("sqlparse", Release("0.4.4", ">=3.5"), Release("0.5.0", ">=3.8")),
        _dist(
            "celery",
            Release(
                "5.2.7",
                ">=3.7",
                ("kombu<6.0,>=5.2.3", "billiard<4.0,>=3.6.4.0", "click<9.0,>=8.0.3"),
            ),
            Release(
                "5.3.6",
                ">=3.8",
                ("kombu<6.0,>=5.3.4", "billiard<5.0,>=4.2.0", "click<9.0,>=8.1.2"),
            ),
            Release(
                "5.4.0",
                ">=3.8",
                ("kombu<6.0,>=5.3.4", "billiard<5.0,>=4.2.0", "click<9.0,>=8.1.2"),
            ),
        ),
        _dist(
            "kombu",
            Release("5.2.4", ">=3.7", ("amqp<6.0.0,>=5.0.9",)),
            Release("5.3.4", ">=3.8", ("amqp<6.0.0,>=5.1.1",)),
            Release("5.3.7", ">=3.8", ("amqp<6.0.0,>=5.1.1",)),
        ),
        _dist("billiard", Release("3.6.4.0"), Release("4.2.0", ">=3.7")),
        _dist("amqp", Release("5.1.1", ">=3.6"), Release("5.2.0", ">=3.6")),
        _dist(
            "numpy",
            Release("1.24.4", ">=3.8"),
            Release("1.26.4", ">=3.9"),
            Release("2.0.0", ">=3.9"),
        ),
        _dist(
            "pandas",
            Release("2.0.3", ">=3.8", ("numpy>=1.20.3", "python-dateutil>=2.8.2")),
            Release("2.2.2", ">=3.9", ("numpy>=1.22.4", "python-dateutil>=2.8.2")),
        ),
        _dist("python-dateutil", Release("2.8.2"), Release("2.9.0")),
        _dist(
            "sqlalchemy",
            Release("1.4.52", ">=2.7", ("greenlet!=0.4.17",)),
            Release("2.0.30", ">=3.7", ("greenlet!=0.4.17", "typing-extensions>=4.6.0")),
        ),
        _dist("greenlet", Release("3.0.3", ">=3.7")),
        _dist("typing-extensions", Release("4.12.2", ">=3.8")),
        _dist(
            "rich",
            Release("13.0.0", ">=3.7", ("markdown-it-py>=2.2.0", "pygments<3,>=2.13")),
            Release("13.7.1", ">=3.7", ("markdown-it-py>=2.2.0", "pygments<3,>=2.13")),
        ),
        # Deliberately dotted and mixed-case upstream names: these exercise the
        # PEP 503 normalisation path that keyed lookups depend on.
        _dist("zope-interface", Release("5.4.0", ">=2.7"), Release("6.4.post2", ">=3.7")),
        _dist("ruamel-yaml", Release("0.17.40", ">=3.7"), Release("0.18.6", ">=3.7")),
    )
}


def package_data(
    name: str,
    versions: Optional[Sequence[str]] = None,
    *,
    requires_python: Optional[Mapping[str, Optional[str]]] = None,
) -> PyPIPackageData:
    """Build :class:`PyPIPackageData` for *name*.

    With no *versions*, the real release history from :data:`ECOSYSTEM` is
    used, including each release's ``requires_python``. Pass *versions*
    explicitly only when a test needs a version layout that does not exist
    upstream (for example to probe a major-version boundary).

    Args:
        name: Distribution name; must be present in :data:`ECOSYSTEM` unless
            *versions* is supplied.
        versions: Override the release list. Order is irrelevant; the result is
            always sorted newest-first like the real store.
        requires_python: Override ``requires_python`` per version. Versions not
            listed default to ``None`` (unconstrained).

    Returns:
        Package metadata equivalent to what :class:`PyPIDataStore` would build
        from a PyPI JSON response.
    """
    if versions is None:
        distribution = ECOSYSTEM[name]
        ordered = distribution.versions
        python_requirements: Dict[str, Optional[str]] = {
            release.version: release.requires_python for release in distribution.releases
        }
    else:
        ordered = sorted(versions, key=parse, reverse=True)
        python_requirements = {version: None for version in ordered}

    if requires_python is not None:
        python_requirements = {
            version: requires_python.get(version) for version in ordered
        }

    return PyPIPackageData(
        name=name,
        latest_version=ordered[0],
        all_versions=ordered,
        parsed_versions=[(version, parse(version)) for version in ordered],
        python_requirements=python_requirements,
    )


def pypi_json_payload(name: str, *, versions: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Render *name* as a raw PyPI ``/pypi/{name}/json`` response body.

    Use this for tests that exercise :class:`PyPIDataStore`'s own parsing;
    tests that only need metadata should use :func:`package_data` instead.

    Args:
        name: Distribution name present in :data:`ECOSYSTEM`.
        versions: Restrict the ``releases`` map to these versions.

    Returns:
        A dict with the ``info`` and ``releases`` keys the parser reads.
    """
    distribution = ECOSYSTEM[name]
    selected = list(versions) if versions is not None else distribution.versions
    latest = distribution.release(max(selected, key=parse))

    releases: Dict[str, List[Dict[str, Any]]] = {}
    for version in selected:
        release = distribution.release(version)
        releases[version] = [
            {
                "filename": f"{name}-{version}-py3-none-any.whl",
                "requires_python": release.requires_python,
                "packagetype": "bdist_wheel",
            }
        ]

    return {
        "info": {
            "name": name,
            "version": latest.version,
            "requires_python": latest.requires_python,
            "requires_dist": list(latest.requires),
        },
        "releases": releases,
    }


class FakePyPIStore(PyPIDataStore):
    """In-memory :class:`PyPIDataStore` — no HTTP client, no event loop tricks.

    Subclassing (rather than duck-typing a ``MagicMock``) keeps the fake honest:
    if production code starts calling a store method this class does not
    override, the real implementation runs and fails loudly on the missing HTTP
    client instead of silently returning a mock.

    Attributes:
        fetch_calls: Every name passed to :meth:`get_package_data`, in order.
            Assert on this to prove caching/coalescing behaviour.
        prefetch_calls: Every batch passed to :meth:`prefetch_packages`.
    """

    def __init__(
        self,
        available: Optional[Mapping[str, PyPIPackageData]] = None,
        *,
        dependencies: Optional[Mapping[str, Sequence[str]]] = None,
        error: Optional[Exception] = None,
        use_real_dependencies: bool = False,
    ) -> None:
        """Create a store serving *available*.

        Args:
            available: Metadata keyed by package name. Names absent from this
                mapping raise, exactly as the real store does for a 404.
            dependencies: Per-version dependency lists keyed ``"name==version"``.
            error: Raise this instead of the default :class:`PyPIError` when a
                lookup misses. Use it to model timeouts and rate limiting.
            use_real_dependencies: Fall back to the published ``requires_dist``
                edges in :data:`ECOSYSTEM` for versions *dependencies* does not
                cover. Off by default so a test that spells out a graph gets
                exactly that graph and nothing else.
        """
        self.available: Dict[str, PyPIPackageData] = dict(available or {})
        self.dependencies: Dict[str, List[str]] = {
            key: list(value) for key, value in (dependencies or {}).items()
        }
        self.error = error
        self.use_real_dependencies = use_real_dependencies
        self.fetch_calls: List[str] = []
        self.prefetch_calls: List[List[str]] = []

    async def get_package_data(self, name: str) -> PyPIPackageData:
        self.fetch_calls.append(name)
        if name in self.available:
            return self.available[name]
        raise self.error or PyPIError(
            f"Package '{name}' not found on PyPI", package_name=name
        )

    async def prefetch_packages(self, names: List[str]) -> None:
        self.prefetch_calls.append(list(names))

    async def get_version_dependencies(self, name: str, version: str) -> List[str]:
        key = f"{name}=={version}"
        if key in self.dependencies:
            return self.dependencies[key]

        if not self.use_real_dependencies:
            return []

        distribution = ECOSYSTEM.get(name)
        if distribution is None:
            return []
        try:
            return list(distribution.release(version).requires)
        except KeyError:
            return []

    def get_versions(self, name: str) -> List[str]:
        data = self.available.get(name)
        return data.all_versions if data else []

    def get_cached_package(self, name: str) -> Optional[PyPIPackageData]:
        return self.available.get(name)


def store_for(
    *names: str,
    dependencies: Optional[Mapping[str, Sequence[str]]] = None,
) -> FakePyPIStore:
    """Build a :class:`FakePyPIStore` serving the real history of *names*.

    Args:
        *names: Distribution names present in :data:`ECOSYSTEM`.
        dependencies: Optional per-version dependency overrides, keyed
            ``"name==version"``; useful for pinning a scenario against future
            edits to :data:`ECOSYSTEM`.

    Returns:
        A store whose ``available`` map covers exactly *names*.
    """
    return FakePyPIStore(
        {name: package_data(name) for name in names},
        dependencies=dependencies,
        use_real_dependencies=True,
    )
