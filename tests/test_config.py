from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from depkeeper.config import (
    DepKeeperConfig,
    discover_config_file,
    load_config,
    _parse_section,
    _pyproject_has_depkeeper_section,
    _read_toml,
)
from depkeeper.exceptions import ConfigError


@pytest.mark.unit
class TestDepKeeperConfig:
    """Tests for DepKeeperConfig dataclass."""

    def test_default_initialization(self) -> None:
        """Test DepKeeperConfig initializes with correct defaults."""
        config = DepKeeperConfig()

        assert config.check_conflicts is True
        assert config.strict_version_matching is False
        assert config.source_path is None

    def test_custom_initialization(self) -> None:
        """Test DepKeeperConfig accepts custom values."""
        test_path = Path("/test/config.toml")

        config = DepKeeperConfig(
            check_conflicts=False,
            strict_version_matching=True,
            source_path=test_path,
        )

        assert config.check_conflicts is False
        assert config.strict_version_matching is True
        assert config.source_path == test_path

    def test_to_log_dict(self) -> None:
        """Test to_log_dict returns configuration without metadata."""
        config = DepKeeperConfig(
            check_conflicts=False,
            strict_version_matching=True,
            source_path=Path("/test/path.toml"),
        )

        result = config.to_log_dict()

        assert result == {
            "check_conflicts": False,
            "strict_version_matching": True,
        }
        assert "source_path" not in result


@pytest.mark.unit
class TestDiscoverConfigFile:
    """Tests for discover_config_file function."""

    def test_explicit_path_priority(self, tmp_path: Path) -> None:
        """Test explicit path is used when provided and exists."""
        config_file = tmp_path / "custom.toml"
        config_file.write_text("[depkeeper]\n", encoding="utf-8")

        # Create auto-discoverable file that should be ignored
        (tmp_path / "depkeeper.toml").write_text("[depkeeper]\n", encoding="utf-8")

        with patch("depkeeper.config.Path.cwd", return_value=tmp_path):
            result = discover_config_file(config_file)

        assert result == config_file.resolve()

    def test_explicit_path_not_found_raises_error(self, tmp_path: Path) -> None:
        """Test ConfigError raised when explicit path doesn't exist."""
        non_existent = tmp_path / "nonexistent.toml"

        with pytest.raises(ConfigError) as exc_info:
            discover_config_file(non_existent)

        assert "not found" in str(exc_info.value).lower()

    def test_discovers_depkeeper_toml(self, tmp_path: Path) -> None:
        """Test discovers depkeeper.toml in current directory."""
        config_file = tmp_path / "depkeeper.toml"
        config_file.write_text("[depkeeper]\n", encoding="utf-8")

        with patch("depkeeper.config.Path.cwd", return_value=tmp_path):
            result = discover_config_file()

        assert result == config_file

    def test_discovers_pyproject_toml_with_section(self, tmp_path: Path) -> None:
        """Test discovers pyproject.toml with [tool.depkeeper] section."""
        config_file = tmp_path / "pyproject.toml"
        config_file.write_text(
            "[tool.depkeeper]\ncheck_conflicts = false\n",
            encoding="utf-8",
        )

        with patch("depkeeper.config.Path.cwd", return_value=tmp_path):
            result = discover_config_file()

        assert result == config_file

    def test_ignores_pyproject_toml_without_section(self, tmp_path: Path) -> None:
        """Test ignores pyproject.toml without [tool.depkeeper] section."""
        config_file = tmp_path / "pyproject.toml"
        config_file.write_text("[tool.other]\nkey = 'value'\n", encoding="utf-8")

        with patch("depkeeper.config.Path.cwd", return_value=tmp_path):
            result = discover_config_file()

        assert result is None

    def test_returns_none_when_no_config_found(self, tmp_path: Path) -> None:
        """Test returns None when no configuration file exists."""
        with patch("depkeeper.config.Path.cwd", return_value=tmp_path):
            result = discover_config_file()

        assert result is None

    def test_precedence_order(self, tmp_path: Path) -> None:
        """Test discovery precedence: depkeeper.toml before pyproject.toml."""
        depkeeper_toml = tmp_path / "depkeeper.toml"
        depkeeper_toml.write_text("[depkeeper]\n", encoding="utf-8")

        pyproject_toml = tmp_path / "pyproject.toml"
        pyproject_toml.write_text("[tool.depkeeper]\n", encoding="utf-8")

        with patch("depkeeper.config.Path.cwd", return_value=tmp_path):
            result = discover_config_file()

        assert result == depkeeper_toml


@pytest.mark.unit
class TestPyprojectHasDepkeeperSection:
    """Tests for _pyproject_has_depkeeper_section helper."""

    def test_returns_true_when_section_exists(self, tmp_path: Path) -> None:
        """Test returns True when [tool.depkeeper] section exists."""
        config_file = tmp_path / "pyproject.toml"
        config_file.write_text(
            "[tool.depkeeper]\ncheck_conflicts = true\n",
            encoding="utf-8",
        )

        result = _pyproject_has_depkeeper_section(config_file)

        assert result is True

    def test_returns_false_when_section_missing(self, tmp_path: Path) -> None:
        """Test returns False when [tool.depkeeper] section doesn't exist."""
        config_file = tmp_path / "pyproject.toml"
        config_file.write_text("[tool.other]\nkey = 'value'\n", encoding="utf-8")

        result = _pyproject_has_depkeeper_section(config_file)

        assert result is False

    def test_returns_false_on_errors(self, tmp_path: Path) -> None:
        """Test returns False gracefully on parse errors or missing files."""
        # Invalid TOML
        config_file = tmp_path / "pyproject.toml"
        config_file.write_text("invalid ][[", encoding="utf-8")
        assert _pyproject_has_depkeeper_section(config_file) is False

        # Non-existent file
        non_existent = tmp_path / "nonexistent.toml"
        assert _pyproject_has_depkeeper_section(non_existent) is False


@pytest.mark.unit
class TestReadToml:
    """Tests for _read_toml helper."""

    def test_reads_valid_toml(self, tmp_path: Path) -> None:
        """Test successfully reads and parses valid TOML file."""
        toml_file = tmp_path / "test.toml"
        toml_file.write_text(
            "[tool.depkeeper]\ncheck_conflicts = true\n",
            encoding="utf-8",
        )

        result = _read_toml(toml_file)

        assert isinstance(result, dict)
        assert result["tool"]["depkeeper"]["check_conflicts"] is True

    def test_raises_error_on_invalid_toml(self, tmp_path: Path) -> None:
        """Test raises ConfigError when TOML is invalid."""
        toml_file = tmp_path / "invalid.toml"
        toml_file.write_text("invalid ][[ toml", encoding="utf-8")

        with pytest.raises(ConfigError) as exc_info:
            _read_toml(toml_file)

        assert "Invalid TOML" in str(exc_info.value)

    def test_raises_error_when_file_not_found(self, tmp_path: Path) -> None:
        """Test raises ConfigError when file doesn't exist."""
        toml_file = tmp_path / "nonexistent.toml"

        with pytest.raises(ConfigError) as exc_info:
            _read_toml(toml_file)

        assert "Cannot read" in str(exc_info.value)

    def test_raises_error_when_toml_library_unavailable(self, tmp_path: Path) -> None:
        """Test raises ConfigError when TOML library is not available."""
        toml_file = tmp_path / "test.toml"
        toml_file.write_text("[depkeeper]\n", encoding="utf-8")

        # Mock tomllib as None to simulate missing library
        with patch("depkeeper.config.tomllib", None):
            with pytest.raises(ConfigError) as exc_info:
                _read_toml(toml_file)

            assert "TOML support requires" in str(exc_info.value)
            assert "tomli" in str(exc_info.value)


@pytest.mark.unit
class TestParseSection:
    """Tests for _parse_section configuration validator."""

    def test_parses_empty_section(self) -> None:
        """Test parsing empty section returns defaults."""
        result = _parse_section({}, config_path="test.toml")

        assert result.check_conflicts is True
        assert result.strict_version_matching is False

    def test_parses_all_options(self) -> None:
        """Test parsing all configuration options."""
        section = {
            "check_conflicts": False,
            "strict_version_matching": True,
        }

        result = _parse_section(section, config_path="test.toml")

        assert result.check_conflicts is False
        assert result.strict_version_matching is True

    def test_raises_error_on_unknown_keys(self) -> None:
        """Test raises ConfigError when unknown keys are present."""
        section = {"unknown_key": "value", "another_unknown": True}

        with pytest.raises(ConfigError) as exc_info:
            _parse_section(section, config_path="test.toml")

        assert "Unknown configuration keys" in str(exc_info.value)
        assert "unknown_key" in str(exc_info.value)

    def test_raises_error_on_wrong_type_check_conflicts(self) -> None:
        """Test raises ConfigError when check_conflicts has wrong type."""
        section = {"check_conflicts": "true"}  # String instead of bool

        with pytest.raises(ConfigError) as exc_info:
            _parse_section(section, config_path="test.toml")

        assert "check_conflicts must be a boolean" in str(exc_info.value)

    def test_raises_error_on_wrong_type_strict_version_matching(self) -> None:
        """Test raises ConfigError when strict_version_matching has wrong type."""
        section = {"strict_version_matching": 1}  # Integer instead of bool

        with pytest.raises(ConfigError) as exc_info:
            _parse_section(section, config_path="test.toml")

        assert "strict_version_matching must be a boolean" in str(exc_info.value)


@pytest.mark.unit
class TestLoadConfig:
    """Tests for load_config main function."""

    def test_returns_defaults_when_no_config_found(self, tmp_path: Path) -> None:
        """Test returns defaults when no configuration file exists."""
        with patch("depkeeper.config.Path.cwd", return_value=tmp_path):
            result = load_config()

        assert result.check_conflicts is True
        assert result.strict_version_matching is False
        assert result.source_path is None

    def test_loads_depkeeper_toml(self, tmp_path: Path) -> None:
        """Test loads configuration from depkeeper.toml."""
        config_file = tmp_path / "depkeeper.toml"
        config_file.write_text(
            "[depkeeper]\ncheck_conflicts = false\n",
            encoding="utf-8",
        )

        with patch("depkeeper.config.Path.cwd", return_value=tmp_path):
            result = load_config()

        assert result.check_conflicts is False
        assert result.source_path == config_file

    def test_loads_pyproject_toml(self, tmp_path: Path) -> None:
        """Test loads configuration from pyproject.toml."""
        config_file = tmp_path / "pyproject.toml"
        config_file.write_text(
            "[tool.depkeeper]\nstrict_version_matching = true\n",
            encoding="utf-8",
        )

        with patch("depkeeper.config.Path.cwd", return_value=tmp_path):
            result = load_config()

        assert result.strict_version_matching is True
        assert result.source_path == config_file

    def test_loads_explicit_config_path(self, tmp_path: Path) -> None:
        """Test loads configuration from explicitly specified path."""
        config_file = tmp_path / "custom.toml"
        config_file.write_text(
            "[depkeeper]\ncheck_conflicts = false\n",
            encoding="utf-8",
        )

        result = load_config(config_file)

        assert result.check_conflicts is False
        assert result.source_path == config_file.resolve()

    def test_raises_error_on_invalid_toml(self, tmp_path: Path) -> None:
        """Test raises ConfigError when TOML file is invalid."""
        config_file = tmp_path / "depkeeper.toml"
        config_file.write_text("invalid ][[ toml", encoding="utf-8")

        with patch("depkeeper.config.Path.cwd", return_value=tmp_path):
            with pytest.raises(ConfigError):
                load_config()

    def test_raises_error_on_unknown_keys(self, tmp_path: Path) -> None:
        """Test raises ConfigError when config contains unknown keys."""
        config_file = tmp_path / "depkeeper.toml"
        config_file.write_text(
            "[depkeeper]\nunknown_option = true\n",
            encoding="utf-8",
        )

        with patch("depkeeper.config.Path.cwd", return_value=tmp_path):
            with pytest.raises(ConfigError) as exc_info:
                load_config()

            assert "Unknown configuration keys" in str(exc_info.value)

    def test_handles_empty_depkeeper_section(self, tmp_path: Path) -> None:
        """Test handles empty [depkeeper] section gracefully."""
        config_file = tmp_path / "depkeeper.toml"
        config_file.write_text("[depkeeper]\n", encoding="utf-8")

        with patch("depkeeper.config.Path.cwd", return_value=tmp_path):
            result = load_config()

        assert result.check_conflicts is True  # Defaults
        assert result.strict_version_matching is False
        assert result.source_path == config_file
