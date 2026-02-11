from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import click
import pytest

from depkeeper.config import DepKeeperConfig
from depkeeper.context import DepKeeperContext, pass_context


@pytest.mark.unit
class TestDepKeeperContext:
    """Tests for DepKeeperContext class."""

    def test_default_initialization(self) -> None:
        """Test DepKeeperContext initializes with correct default values."""
        ctx = DepKeeperContext()

        assert ctx.config_path is None
        assert ctx.verbose == 0
        assert ctx.color is True
        assert ctx.config is None

    def test_instances_are_independent(self) -> None:
        """Test multiple DepKeeperContext instances are independent."""
        ctx1 = DepKeeperContext()
        ctx2 = DepKeeperContext()

        # Modify first instance
        ctx1.verbose = 2
        ctx1.color = False

        # Second instance should be unaffected
        assert ctx2.verbose == 0
        assert ctx2.color is True
        assert ctx1 is not ctx2

    def test_all_attributes_can_be_set(self) -> None:
        """Test all context attributes can be set and retrieved."""
        ctx = DepKeeperContext()
        test_path = Path("/path/to/config.toml")
        mock_config = MagicMock(spec=DepKeeperConfig)

        # Set all attributes
        ctx.config_path = test_path
        ctx.verbose = 2
        ctx.color = False
        ctx.config = mock_config

        # Verify all attributes
        assert ctx.config_path == test_path
        assert ctx.verbose == 2
        assert ctx.color is False
        assert ctx.config is mock_config

    def test_slots_prevents_arbitrary_attributes(self) -> None:
        """Test __slots__ prevents setting undefined attributes."""
        ctx = DepKeeperContext()

        with pytest.raises(AttributeError):
            ctx.arbitrary_attribute = "value"  # type: ignore


@pytest.mark.unit
class TestPassContextDecorator:
    """Tests for pass_context decorator."""

    def test_pass_context_injects_existing_context(self) -> None:
        """Test pass_context decorator injects existing DepKeeperContext."""

        @click.command()
        @pass_context
        def test_command(ctx: DepKeeperContext) -> DepKeeperContext:
            return ctx

        # Create Click context with DepKeeperContext
        click_ctx = click.Context(click.Command("test"))
        depkeeper_ctx = DepKeeperContext()
        click_ctx.obj = depkeeper_ctx

        result = click_ctx.invoke(test_command)

        assert result is depkeeper_ctx

    def test_pass_context_creates_context_when_missing(self) -> None:
        """Test pass_context creates DepKeeperContext when none exists."""

        @click.command()
        @pass_context
        def test_command(ctx: DepKeeperContext) -> DepKeeperContext:
            return ctx

        # Create Click context without obj (no DepKeeperContext)
        click_ctx = click.Context(click.Command("test"))

        result = click_ctx.invoke(test_command)

        # Should auto-create context with defaults
        assert isinstance(result, DepKeeperContext)
        assert result.verbose == 0
        assert result.color is True

    def test_pass_context_preserves_modifications(self) -> None:
        """Test context modifications are preserved across decorator usage."""

        @click.command()
        @pass_context
        def test_command(ctx: DepKeeperContext) -> None:
            ctx.verbose = 3
            ctx.color = False

        click_ctx = click.Context(click.Command("test"))
        depkeeper_ctx = DepKeeperContext()
        click_ctx.obj = depkeeper_ctx

        click_ctx.invoke(test_command)

        # Modifications should persist
        assert depkeeper_ctx.verbose == 3
        assert depkeeper_ctx.color is False
