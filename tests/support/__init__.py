"""Shared test support for the depkeeper suite.

Nothing in this package is collected by pytest (``python_files = test_*.py``);
it exists so that test modules share one set of builders, fakes and realistic
datasets instead of re-declaring near-identical helpers.

Layout:

- :mod:`tests.support.factories` — builders for the domain models.
- :mod:`tests.support.pypi` — an in-memory :class:`PyPIDataStore` plus a
  registry of real PyPI release histories and dependency graphs.
- :mod:`tests.support.datasets` — realistic ``requirements.txt`` corpora.
"""

from __future__ import annotations

from tests.support.factories import (
    make_conflict,
    make_conflict_set,
    make_package,
    make_requirement,
)
from tests.support.pypi import (
    ECOSYSTEM,
    FakePyPIStore,
    package_data,
    pypi_json_payload,
    store_for,
)

__all__ = [
    "ECOSYSTEM",
    "FakePyPIStore",
    "make_conflict",
    "make_conflict_set",
    "make_package",
    "make_requirement",
    "package_data",
    "pypi_json_payload",
    "store_for",
]
