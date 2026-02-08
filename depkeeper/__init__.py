"""
depkeeper — modern Python dependency management for requirements.txt.

depkeeper is an intelligent dependency management tool that helps developers
keep their ``requirements.txt`` files up to date, secure, and conflict-free.

Quick start
-----------
Check for available updates::

    $ depkeeper check

Update packages to newer versions::

    $ depkeeper update

Programmatic usage::

    >>> from depkeeper.core.parser import RequirementsParser
    >>> from depkeeper.core.checker import VersionChecker
    >>> parser = RequirementsParser()
    >>> requirements = parser.parse_file("requirements.txt")

For more information, see:
    https://rahulkaushal04.github.io/depkeeper/
"""

from __future__ import annotations

from depkeeper.__version__ import __version__

__all__ = ["__version__"]
