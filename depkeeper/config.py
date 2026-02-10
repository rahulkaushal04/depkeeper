"""Configuration file loader for depkeeper.

Handles discovery, loading, parsing, and validation of configuration files.
Supports two formats:

- ``depkeeper.toml`` — settings under ``[depkeeper]`` table
- ``pyproject.toml`` — settings under ``[tool.depkeeper]`` table

Discovery order:

1. Explicit path from ``--config`` or ``DEPKEEPER_CONFIG``
2. ``depkeeper.toml`` in current directory
3. ``pyproject.toml`` with ``[tool.depkeeper]`` section

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
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass, field

from depkeeper.exceptions import ConfigError
from depkeeper.utils.logger import get_logger
from depkeeper.constants import (
    DEFAULT_CHECK_CONFLICTS,
    DEFAULT_STRICT_VERSION_MATCHING,
)

logger = get_logger("config")


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
        source_path: Path to loaded config file, or ``None`` if using defaults.
    """

    check_conflicts: bool = DEFAULT_CHECK_CONFLICTS
    strict_version_matching: bool = DEFAULT_STRICT_VERSION_MATCHING

    # Metadata (not a user-facing option)
    source_path: Optional[Path] = field(default=None, repr=False)

    def to_log_dict(self) -> Dict[str, Any]:
        """Return configuration as dictionary for debug logging.

        Excludes ``source_path`` metadata.

        Returns:
            Dictionary of configuration option names to values.
        """
        return {
            "check_conflicts": self.check_conflicts,
            "strict_version_matching": self.strict_version_matching,
        }


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
    # 1. Explicit path takes priority
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

    # 2. depkeeper.toml in current directory
    depkeeper_toml = cwd / "depkeeper.toml"
    if depkeeper_toml.is_file():
        logger.debug("Found depkeeper.toml: %s", depkeeper_toml)
        return depkeeper_toml

    # 3. pyproject.toml with [tool.depkeeper] section
    pyproject_toml = cwd / "pyproject.toml"
    if pyproject_toml.is_file():
        if _pyproject_has_depkeeper_section(pyproject_toml):
            logger.debug("Found [tool.depkeeper] in pyproject.toml: %s", pyproject_toml)
            return pyproject_toml

    logger.debug("No configuration file found")
    return None


def _pyproject_has_depkeeper_section(path: Path) -> bool:
    """Check if pyproject.toml contains [tool.depkeeper] section.

    Quick parse to avoid loading pyproject.toml without depkeeper config.
    Parse errors are silently ignored for graceful fallback.

    Args:
        path: Path to pyproject.toml file.

    Returns:
        ``True`` if ``[tool.depkeeper]`` exists, ``False`` otherwise.
    """
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
            auto-discovery (see :func:`discover_config_file`).

    Returns:
        Validated :class:`DepKeeperConfig` with values from file or defaults.

    Raises:
        ConfigError: File cannot be parsed, has unknown keys, or invalid values.
    """
    resolved = discover_config_file(config_path)

    if resolved is None:
        logger.debug("No config file found, using defaults")
        return DepKeeperConfig()

    logger.info("Loading configuration from %s", resolved)
    raw = _read_toml(resolved)

    # Extract the depkeeper-specific section
    if resolved.name == "pyproject.toml":
        section = raw.get("tool", {}).get("depkeeper", {})
    else:
        # depkeeper.toml — settings live under [depkeeper]
        section = raw.get("depkeeper", {})

    if not section:
        logger.debug("Config file found but no depkeeper section — using defaults")
        return DepKeeperConfig(source_path=resolved)

    config = _parse_section(section, config_path=str(resolved))
    config.source_path = resolved

    logger.debug("Loaded configuration: %s", config.to_log_dict())
    return config


def _read_toml(path: Path) -> Dict[str, Any]:
    """Read and parse a TOML file.

    Uses ``tomli`` if available, otherwise ``tomllib`` (Python 3.11+).

    Args:
        path: Path to TOML file.

    Returns:
        Parsed TOML as nested dictionary.

    Raises:
        ConfigError: File cannot be read, invalid TOML, or no parser available.
    """
    if tomllib is None:
        raise ConfigError(
            "TOML support requires Python 3.11+ or the 'tomli' package. "
            "Install it with: pip install tomli",
            config_path=str(path),
        )

    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"Invalid TOML in {path.name}: {exc}",
            config_path=str(path),
        ) from exc
    except OSError as exc:
        raise ConfigError(
            f"Cannot read configuration file {path}: {exc}",
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
        Validated :class:`DepKeeperConfig` with values from section and defaults.

    Raises:
        ConfigError: Unknown keys or incorrect types (e.g., string for boolean).
    """
    config = DepKeeperConfig()

    # Known depkeeper configuration options
    known_top = {
        "check_conflicts",
        "strict_version_matching",
    }

    # Validate that no unknown keys are present
    unknown_top = set(section.keys()) - known_top
    if unknown_top:
        raise ConfigError(
            f"Unknown configuration keys: {', '.join(sorted(unknown_top))}",
            config_path=config_path,
        )

    # Parse and validate each option
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

    return config
