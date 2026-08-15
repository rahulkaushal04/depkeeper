"""Tests for :mod:`depkeeper.utils.naming`.

Primary purpose: lock the single canonical PEP 503 normalisation rule that
guards against regression M9 — four independent normalisers existed, three
of which folded ``_`` but not ``.``, so a dotted distribution
(``zope.interface``) had two identities inside one process.
"""

from __future__ import annotations

import pytest
from packaging.utils import canonicalize_name

from depkeeper.core.data_store import _normalize as data_store_normalize
from depkeeper.core.dependency_analyzer import _normalize as analyzer_normalize
from depkeeper.core.parser import _normalize_package_name as parser_normalize
from depkeeper.models.conflict import _normalize_name as conflict_normalize
from depkeeper.models.package import _normalize_name as package_normalize
from depkeeper.utils import normalize_package_name
from depkeeper.utils.naming import normalize_package_name as direct_import

# Every module-private alias that must resolve to the same rule.
ALL_NORMALISERS = (
    normalize_package_name,
    direct_import,
    parser_normalize,
    data_store_normalize,
    analyzer_normalize,
    package_normalize,
    conflict_normalize,
)

DOTTED_NAMES = [
    "zope.interface",
    "ruamel.yaml",
    "backports.zoneinfo",
    "jaraco.classes",
    "zope.event",
]


@pytest.mark.unit
class TestNormalizePackageName:
    """Behaviour of the canonical normaliser."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("requests", "requests"),
            ("Django", "django"),
            ("REQUESTS", "requests"),
            ("Flask_Login", "flask-login"),
            ("zope.interface", "zope-interface"),
            ("ruamel.yaml", "ruamel-yaml"),
            ("backports.zoneinfo", "backports-zoneinfo"),
            ("My_Cool.Package", "my-cool-package"),
            ("my__package___name", "my-package-name"),
            ("pkg-v2", "pkg-v2"),
            ("", ""),
        ],
        ids=[
            "already-canonical",
            "mixed-case",
            "upper-case",
            "underscore",
            "dot",
            "dot-ruamel",
            "dot-backports",
            "dot-and-underscore",
            "separator-runs-collapse",
            "trailing-digit",
            "empty",
        ],
    )
    def test_canonical_form(self, raw: str, expected: str) -> None:
        """Separator runs collapse to a single hyphen and case is folded."""
        assert normalize_package_name(raw) == expected

    def test_matches_packaging(self) -> None:
        """The rule is delegated, not re-implemented."""
        for raw in DOTTED_NAMES + ["Flask_Login", "My.Cool_Pkg", "requests"]:
            assert normalize_package_name(raw) == str(canonicalize_name(raw))

    def test_returns_plain_str(self) -> None:
        """Callers and JSON serialisers get a real ``str``, not a NewType."""
        result = normalize_package_name("Zope.Interface")
        assert type(result) is str

    @pytest.mark.parametrize("raw", DOTTED_NAMES + ["My_Cool.Package", "", "requests"])
    def test_idempotent(self, raw: str) -> None:
        """Normalising an already-normalised name is a no-op."""
        once = normalize_package_name(raw)
        assert normalize_package_name(once) == once


@pytest.mark.unit
class TestNormaliserConsistency:
    """Regression guard for M9: every layer must agree on one rule."""

    @pytest.mark.parametrize(
        "raw",
        DOTTED_NAMES
        + ["Flask_Login", "My_Cool.Package", "requests", "DJANGO", "pkg.name"],
    )
    def test_all_layers_agree(self, raw: str) -> None:
        """Parser, data store, analyzer, Package and Conflict produce one key."""
        results = {fn(raw) for fn in ALL_NORMALISERS}
        assert len(results) == 1, f"normalisers disagree on {raw!r}: {results}"

    @pytest.mark.parametrize("raw", DOTTED_NAMES)
    def test_dotted_names_are_hyphenated_everywhere(self, raw: str) -> None:
        """The specific M9 failure: dots must not survive in any layer."""
        for fn in ALL_NORMALISERS:
            assert "." not in fn(raw), f"{fn.__module__}.{fn.__name__} kept a dot"
