from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from depkeeper.__main__ import _print_startup_error, main


@pytest.mark.unit
class TestMain:
    """Tests for main() entry point function."""

    @pytest.mark.parametrize(
        "exit_code",
        [0, 1, 130],
        ids=["success", "error", "interrupted"],
    )
    def test_main_returns_cli_exit_code(self, exit_code: int) -> None:
        """Test main returns exit code from cli_main when import succeeds."""
        mock_cli_module = MagicMock()
        mock_cli_module.main = MagicMock(return_value=exit_code)

        with patch.dict("sys.modules", {"depkeeper.cli": mock_cli_module}):
            result = main()

        assert result == exit_code
        mock_cli_module.main.assert_called_once()

    def test_main_import_error_returns_one(self, capsys: pytest.CaptureFixture) -> None:
        """Test main returns 1 when cli module import fails."""
        import_error = ImportError("No module named 'depkeeper.cli'")

        with patch.dict("sys.modules", {"depkeeper.cli": None}):
            with patch(
                "builtins.__import__",
                side_effect=lambda name, *args, **kwargs: (
                    (_ for _ in ()).throw(import_error)
                    if name == "depkeeper.cli"
                    else __import__(name, *args, **kwargs)
                ),
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "ImportError:" in captured.err
        assert "No module named 'depkeeper.cli'" in captured.err

    def test_main_calls_cli_main_without_arguments(self) -> None:
        """Test main calls cli_main without passing any arguments."""
        mock_cli_module = MagicMock()
        mock_cli_module.main = MagicMock(return_value=0)

        with patch.dict("sys.modules", {"depkeeper.cli": mock_cli_module}):
            main()

        mock_cli_module.main.assert_called_once_with()


@pytest.mark.unit
class TestPrintStartupError:
    """Tests for _print_startup_error helper function."""

    def test_print_startup_error_with_version(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """Test _print_startup_error prints version when available."""
        test_error = ImportError("Test error message")
        test_version = "1.2.3"
        mock_version_module = MagicMock(__version__=test_version)

        with patch.dict(sys.modules, {"depkeeper.__version__": mock_version_module}):
            _print_startup_error(test_error)

        captured = capsys.readouterr()
        assert f"depkeeper version: {test_version}" in captured.err
        assert "ImportError: Test error message" in captured.err

    def test_print_startup_error_version_import_fails(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """Test _print_startup_error handles version import failure gracefully."""
        test_error = ImportError("Test error message")

        def mock_import(name, *args, **kwargs):
            if "depkeeper.__version__" in name or name == "depkeeper.__version__":
                raise ImportError("Cannot import version")
            return __import__(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            _print_startup_error(test_error)

        captured = capsys.readouterr()
        assert "depkeeper version: <unknown>" in captured.err
        assert "ImportError: Test error message" in captured.err

    def test_print_startup_error_writes_to_stderr(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """Test _print_startup_error writes output to stderr, not stdout."""
        test_error = ImportError("Test error")

        _print_startup_error(test_error)

        captured = capsys.readouterr()
        assert len(captured.err) > 0
        assert "ImportError:" in captured.err
        assert captured.out == ""

    def test_print_startup_error_includes_blank_line(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """Test _print_startup_error includes blank line for readability."""
        test_error = ImportError("Test error")
        test_version = "1.0.0"
        mock_version_module = MagicMock(__version__=test_version)

        with patch.dict(sys.modules, {"depkeeper.__version__": mock_version_module}):
            _print_startup_error(test_error)

        captured = capsys.readouterr()
        lines = captured.err.split("\n")

        # Check for version line, blank line, then error
        assert any("depkeeper version:" in line for line in lines)
        assert any("ImportError:" in line for line in lines)
        assert "" in lines  # blank line present
