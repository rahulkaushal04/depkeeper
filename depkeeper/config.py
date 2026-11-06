"""Configuration file loader for depkeeper.

Handles discovery, loading, parsing, and validation of configuration files.
Supports two formats:

- ``depkeeper.toml`` — settings under ``[depkeeper]`` table
- ``pyproject.toml`` — settings under ``[tool.depkeeper]`` table

Discovery order:

1. Explicit path from ``--config`` or ``DEPKEEPER_CONFIG``
2. ``depkeeper.toml`` in the current directory or the nearest parent
3. ``pyproject.toml`` with ``[tool.depkeeper]`` section, same search

The upward search stops at the first directory containing ``.git`` (the
repository root) or at the filesystem root.

Configuration precedence: defaults < config file < environment < CLI args.

Typical usage::

    config = load_config()  # Auto-discover
    config = load_config(Path("custom.toml"))  # Explicit path

Example (``depkeeper.toml``)::

    [depkeeper]
    check_conflicts = true
    strict_version_matching = false
"""

from __future__ import annotations

import tomli as tomllib
import re
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field

from depkeeper.exceptions import ConfigError
from depkeeper.utils.logger import get_logger
from depkeeper.utils.naming import normalize_package_name
from depkeeper.utils.version_utils import VERSIONING_CHOICES
from depkeeper.constants import (
    DEFAULT_CHECK_CONFLICTS,
    DEFAULT_READ_ENCODING,
    DEFAULT_STRICT_VERSION_MATCHING,
)

logger = get_logger("config")

#: Valid ``fail_on`` values, from never failing to failing on any update.
FAIL_ON_CHOICES = ("none", "updates", "minor", "major")

#: Valid ``max_update`` values (per-package policy).
MAX_UPDATE_CHOICES = ("patch", "minor", "major")

_DURATION_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([smhdw]?)\s*$", re.I)
_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "": 86400}
_PYTHON_VERSION_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")


def parse_duration(value: Union[str, int, float]) -> timedelta:
    """Parse a release-cooldown duration.

    Accepts a number of days (``7``, ``"7"``) or a string with a unit suffix
    ``s``/``m``/``h``/``d``/``w`` (``"12h"``, ``"7d"``, ``"2w"``).

    Raises:
        ValueError: Negative, boolean or unparseable input.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"invalid duration {value!r}")
    if isinstance(value, (int, float)):
        if value < 0:
            raise ValueError(f"duration must not be negative, got {value!r}")
        try:
            return timedelta(days=value)
        except OverflowError:
            raise ValueError(f"duration {value!r} is too large") from None
    match = _DURATION_RE.match(value)
    if not match:
        raise ValueError(f"invalid duration {value!r} (use e.g. '7d', '12h', '2w')")
    try:
        return timedelta(
            seconds=float(match.group(1)) * _DURATION_UNITS[match.group(2).lower()]
        )
    except OverflowError:
        raise ValueError(f"duration {value!r} is too large") from None


@dataclass
class PackagePolicy:
    """Per-package overrides from ``[depkeeper.packages.<name>]``.

    ``None`` means "inherit the global setting".

    Attributes:
        max_update: Largest update level allowed (``patch``/``minor``/``major``).
            For calver packages ``month`` ranks as minor and ``year`` as major.
        hold: Keep the package at its current version.
        allow_prerelease: Consider pre-releases as candidates.
        versioning: ``auto``/``semver``/``calver`` for this package.
        ignore: Skip the package entirely (never recommend a change).
    """

    max_update: Optional[str] = None
    hold: bool = False
    allow_prerelease: bool = False
    versioning: Optional[str] = None
    ignore: bool = False


@dataclass
class DepKeeperConfig:
    """Parsed and validated depkeeper configuration.

    Contains settings from ``depkeeper.toml`` or ``pyproject.toml``.
    All fields have defaults, so empty config files are valid.

    Attributes:
        check_conflicts: Enable dependency conflict resolution. When ``True``,
            analyzes transitive dependencies to avoid conflicts.
        strict_version_matching: Only consider exact pins (``==``) as current
            versions. Ignores range constraints like ``>=2.0``.
        fail_on: ``check`` exit-code gate: ``none`` (default), ``updates``,
            ``minor`` or ``major``.
        ignore: Package names that ``check`` skips.
        python_version: Target Python (``"3.9"``) candidates must support;
            ``None`` means the running interpreter.
        min_age: Release cooldown; versions uploaded more recently are not
            recommended. ``None`` disables it.
        versioning: Global ``auto``/``semver``/``calver`` (default ``auto``).
        packages: Per-package `PackagePolicy`, keyed by normalized name.
        source_path: Path to loaded config file, or ``None`` if using defaults.
    """

    check_conflicts: bool = DEFAULT_CHECK_CONFLICTS
    strict_version_matching: bool = DEFAULT_STRICT_VERSION_MATCHING
    fail_on: str = "none"
    ignore: List[str] = field(default_factory=list)
    python_version: Optional[str] = None
    min_age: Optional[timedelta] = None
    versioning: str = "auto"
    packages: Dict[str, PackagePolicy] = field(default_factory=dict)

    # Provenance, not a user-facing option: never serialized back to TOML.
    source_path: Optional[Path] = field(default=None, repr=False)

    def to_log_dict(self) -> Dict[str, Any]:
        """Return configuration as dictionary for debug logging.

        Excludes ``source_path`` metadata.

        Returns:
            Dictionary of configuration option names to values.
        """
        result: Dict[str, Any] = {
            "check_conflicts": self.check_conflicts,
            "strict_version_matching": self.strict_version_matching,
            "fail_on": self.fail_on,
            "ignore": list(self.ignore),
        }
        # Optional settings appear only when set, keeping the default dict stable.
        if self.python_version:
            result["python_version"] = self.python_version
        if self.min_age is not None:
            result["min_age"] = str(self.min_age)
        if self.versioning != "auto":
            result["versioning"] = self.versioning
        if self.packages:
            result["packages"] = sorted(self.packages)
        return result


def discover_config_file(explicit_path: Optional[Path] = None) -> Optional[Path]:
    """Find the configuration file to load.

    Search order:

    1. ``explicit_path`` (from ``--config`` or ``DEPKEEPER_CONFIG``)
    2. ``depkeeper.toml`` in current directory
    3. ``pyproject.toml`` with ``[tool.depkeeper]`` section in current directory

    Validates ``pyproject.toml`` contains depkeeper section before using it.

    Args:
        explicit_path: Explicit config path. If provided, must exist.

    Returns:
        Resolved path to config file, or ``None`` if not found.

    Raises:
        ConfigError: Explicit path provided but does not exist.
    """
    if explicit_path is not None:
        resolved = explicit_path.resolve()
        if not resolved.is_file():
            raise ConfigError(
                f"Configuration file not found: {explicit_path}",
                config_path=str(explicit_path),
            )
        logger.debug("Using explicit config: %s", resolved)
        return resolved

    cwd = Path.cwd()

    # Walk up so running from a subdirectory finds the project's config; stop
    # at the repository root (.git) so a stray file in $HOME is not adopted.
    # Without a .git, never walk above $HOME (outside $HOME the walk ends at
    # the filesystem root), so a file in a parent of $HOME is not adopted.
    home = Path.home().resolve()
    stop = home if home in (cwd, *cwd.parents) else None
    for directory in (cwd, *cwd.parents):
        depkeeper_toml = directory / "depkeeper.toml"
        if depkeeper_toml.is_file():
            logger.debug("Found depkeeper.toml: %s", depkeeper_toml)
            return depkeeper_toml

        # pyproject.toml is only adopted when it actually configures
        # depkeeper; otherwise it would shadow the built-in defaults.
        pyproject_toml = directory / "pyproject.toml"
        if pyproject_toml.is_file() and _pyproject_has_depkeeper_section(
            pyproject_toml
        ):
            logger.debug("Found [tool.depkeeper] in pyproject.toml: %s", pyproject_toml)
            return pyproject_toml

        if (directory / ".git").exists() or directory == stop:
            break

    logger.debug("No configuration file found")
    return None


def _pyproject_has_depkeeper_section(path: Path) -> bool:
    """Return True if *path* has a ``[tool.depkeeper]`` table (False on any error)."""
    try:
        raw = _read_toml(path)
        return "depkeeper" in raw.get("tool", {})
    except Exception:
        return False


def load_config(config_path: Optional[Path] = None) -> DepKeeperConfig:
    """Load and validate depkeeper configuration.

    Discovers config file (or uses provided path), parses and validates it.
    Returns config with defaults if no file found.

    Handles both ``depkeeper.toml`` and ``pyproject.toml`` formats.

    Args:
        config_path: Explicit path to config file. If ``None``, uses
            auto-discovery (see `discover_config_file`).

    Returns:
        Validated `DepKeeperConfig` with values from file or defaults.

    Raises:
        ConfigError: File cannot be parsed, has unknown keys, or invalid values.
    """
    resolved = discover_config_file(config_path)

    if resolved is None:
        logger.debug("No config file found, using defaults")
        return DepKeeperConfig()

    logger.info("Loading configuration from %s", resolved)
    raw = _read_toml(resolved)

    # The two supported files nest the settings differently.
    if resolved.name == "pyproject.toml":
        section = raw.get("tool", {}).get("depkeeper")
        table_name = "[tool.depkeeper]"
    else:
        section = raw.get("depkeeper")
        table_name = "[depkeeper]"

    # An explicitly requested file that configures nothing is almost surely a
    # wrong path; silently using defaults would hide that.
    if section is None and config_path is not None:
        raise ConfigError(
            f"Configuration file {resolved.name} has no {table_name} table",
            config_path=str(resolved),
        )

    if not section:
        logger.debug("Config file found but no depkeeper section — using defaults")
        return DepKeeperConfig(source_path=resolved)

    config = _parse_section(section, config_path=str(resolved))
    config.source_path = resolved

    logger.debug("Loaded configuration: %s", config.to_log_dict())
    return config


def _read_toml(path: Path) -> Dict[str, Any]:
    """Read and parse a TOML file.

    Decodes with ``utf-8-sig`` because TOML parsers reject a leading byte
    order mark (written by some Windows editors).

    Args:
        path: Path to TOML file.

    Returns:
        Parsed TOML as nested dictionary.

    Raises:
        ConfigError: File cannot be read or decoded, TOML is invalid, or no
            parser is available.
    """
    if tomllib is None:
        raise ConfigError(
            "TOML support requires Python 3.11+ or the 'tomli' package. "
            "Install it with: pip install tomli",
            config_path=str(path),
        )

    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise ConfigError(
            f"Cannot read configuration file {path}: {exc}",
            config_path=str(path),
        ) from exc

    try:
        content = raw_bytes.decode(DEFAULT_READ_ENCODING)
    except UnicodeDecodeError as exc:
        raise ConfigError(
            f"Configuration file {path.name} is not valid UTF-8: {exc}",
            config_path=str(path),
        ) from exc

    try:
        return tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"Invalid TOML in {path.name}: {exc}",
            config_path=str(path),
        ) from exc


def _parse_section(
    section: Dict[str, Any],
    *,
    config_path: str,
) -> DepKeeperConfig:
    """Parse and validate depkeeper configuration section.

    Validates ``[depkeeper]`` or ``[tool.depkeeper]`` table from TOML.
    Rejects unknown keys and type mismatches.

    Args:
        section: Raw config dictionary from TOML file.
        config_path: Path string for error messages.

    Returns:
        Validated `DepKeeperConfig` with values from section and defaults.

    Raises:
        ConfigError: Unknown keys or incorrect types (e.g., string for boolean).
    """
    config = DepKeeperConfig()

    known_top = {
        "check_conflicts",
        "strict_version_matching",
        "fail_on",
        "ignore",
        "python_version",
        "min_age",
        "versioning",
        "packages",
    }

    # Unknown keys are an error rather than a warning: silently ignoring a
    # typo would leave the user believing a setting is in effect when it is not.
    unknown_top = set(section.keys()) - known_top
    if unknown_top:
        raise ConfigError(
            f"Unknown configuration keys: {', '.join(sorted(unknown_top))}",
            config_path=config_path,
        )

    if "check_conflicts" in section:
        val = section["check_conflicts"]
        if not isinstance(val, bool):
            raise ConfigError(
                f"check_conflicts must be a boolean, got {type(val).__name__}",
                config_path=config_path,
                option="check_conflicts",
            )
        config.check_conflicts = val

    if "strict_version_matching" in section:
        val = section["strict_version_matching"]
        if not isinstance(val, bool):
            raise ConfigError(
                f"strict_version_matching must be a boolean, got {type(val).__name__}",
                config_path=config_path,
                option="strict_version_matching",
            )
        config.strict_version_matching = val

    if "fail_on" in section:
        val = section["fail_on"]
        if val not in FAIL_ON_CHOICES:
            raise ConfigError(
                f"fail_on must be one of {', '.join(FAIL_ON_CHOICES)}, got {val!r}",
                config_path=config_path,
                option="fail_on",
            )
        config.fail_on = val

    if "ignore" in section:
        val = section["ignore"]
        if not isinstance(val, list) or not all(isinstance(v, str) for v in val):
            raise ConfigError(
                "ignore must be a list of package names",
                config_path=config_path,
                option="ignore",
            )
        config.ignore = list(val)

    if "python_version" in section:
        val = section["python_version"]
        if not isinstance(val, str) or not _PYTHON_VERSION_RE.match(val):
            raise ConfigError(
                f"python_version must look like '3.9', got {val!r}",
                config_path=config_path,
                option="python_version",
            )
        config.python_version = val

    if "min_age" in section:
        try:
            config.min_age = parse_duration(section["min_age"])
        except ValueError as exc:
            raise ConfigError(
                f"min_age: {exc}", config_path=config_path, option="min_age"
            ) from exc

    if "versioning" in section:
        config.versioning = _check_versioning(
            section["versioning"], "versioning", config_path
        )

    if "packages" in section:
        config.packages = _parse_packages(section["packages"], config_path)

    return config


def _check_versioning(val: Any, option: str, config_path: str) -> str:
    """Return *val* when it is a valid versioning mode, else raise `ConfigError`."""
    if val not in VERSIONING_CHOICES:
        raise ConfigError(
            f"{option} must be one of {', '.join(VERSIONING_CHOICES)}, got {val!r}",
            config_path=config_path,
            option=option,
        )
    return str(val)


def _parse_packages(raw: Any, config_path: str) -> Dict[str, PackagePolicy]:
    """Validate the ``packages`` table into policies keyed by normalized name."""
    if not isinstance(raw, dict):
        raise ConfigError(
            "packages must be a table of per-package tables",
            config_path=config_path,
            option="packages",
        )
    bool_keys = ("hold", "allow_prerelease", "ignore")
    known = {"max_update", "versioning", *bool_keys}
    policies: Dict[str, PackagePolicy] = {}

    for name, body in raw.items():
        option = f"packages.{name}"
        if not isinstance(body, dict):
            raise ConfigError(
                f"{option} must be a table", config_path=config_path, option=option
            )
        unknown = set(body) - known
        if unknown:
            raise ConfigError(
                f"Unknown keys in {option}: {', '.join(sorted(unknown))}",
                config_path=config_path,
                option=option,
            )
        key = normalize_package_name(name)
        if key in policies:
            raise ConfigError(
                f"{option} duplicates another entry for '{key}'",
                config_path=config_path,
                option=option,
            )
        policy = PackagePolicy()
        for flag in bool_keys:
            if flag in body:
                if not isinstance(body[flag], bool):
                    raise ConfigError(
                        f"{option}.{flag} must be a boolean, "
                        f"got {type(body[flag]).__name__}",
                        config_path=config_path,
                        option=f"{option}.{flag}",
                    )
                setattr(policy, flag, body[flag])
        if "max_update" in body:
            if body["max_update"] not in MAX_UPDATE_CHOICES:
                raise ConfigError(
                    f"{option}.max_update must be one of "
                    f"{', '.join(MAX_UPDATE_CHOICES)}, got {body['max_update']!r}",
                    config_path=config_path,
                    option=f"{option}.max_update",
                )
            policy.max_update = body["max_update"]
        if "versioning" in body:
            policy.versioning = _check_versioning(
                body["versioning"], f"{option}.versioning", config_path
            )
        policies[key] = policy

    return policies
