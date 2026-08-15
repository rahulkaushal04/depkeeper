"""Canonical package-name normalization for depkeeper.

This module is the **single** source of truth for turning a distribution
name into its canonical PEP 503 form. Every layer that keys a mapping,
compares, caches or deduplicates by package name must go through
:func:`normalize_package_name`.

Why this matters: a name can legitimately reach depkeeper in several
spellings from independent sources — the requirements file
(``zope.interface==5.4.0``), PyPI ``requires_dist`` metadata
(``zope.interface>=6.0``), and the CLI (``--packages zope_interface``).
PEP 503 declares all of these equivalent to ``zope-interface``. Any
normalization rule that disagrees (for example one that folds ``_`` but
not ``.``) silently splits a single distribution into two identities, so
cross-package lookups miss and caches duplicate.

The rule is delegated to :func:`packaging.utils.canonicalize_name` rather
than re-implemented, so depkeeper always agrees with pip, PyPI and the
rest of the packaging ecosystem.
"""

from __future__ import annotations

from packaging.utils import canonicalize_name

__all__ = ["normalize_package_name"]


def normalize_package_name(name: str) -> str:
    """Return the canonical PEP 503 form of a distribution name.

    Runs of ``-``, ``_`` and ``.`` collapse to a single ``-`` and the
    result is lower-cased. The operation is idempotent, so it is safe to
    apply to a value that has already been normalized.

    Args:
        name: Raw distribution name in any casing / separator style.

    Returns:
        The canonical name. An empty string maps to an empty string.

    Example::

        >>> normalize_package_name("Flask_Login")
        'flask-login'
        >>> normalize_package_name("zope.interface")
        'zope-interface'
        >>> normalize_package_name("My_Cool.Package")
        'my-cool-package'
        >>> normalize_package_name("requests")
        'requests'
    """
    # canonicalize_name returns a NormalizedName (a NewType over str);
    # str() keeps the public signature a plain str for callers/serializers.
    return str(canonicalize_name(name))
