"""Tests for CLI module.

This module tests the command-line interface.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from usmca_bot.cli import setup_logging


@pytest.mark.unit
class TestCLI:
    """Test suite for CLI functions."""

    def test_setup_logging_development(self, test_settings) -> None:
        """Test logging setup for development environment.

        Args:
            test_settings: Test settings fixture.
        """
        test_settings.environment = "development"
        test_settings.log_level = "DEBUG"

        # Should not raise exception
        setup_logging(test_settings)

    def test_setup_logging_production(self, test_settings) -> None:
        """Test logging setup for production environment.

        Args:
            test_settings: Test settings fixture.
        """
        test_settings.environment = "production"
        test_settings.log_level = "INFO"

        # Should not raise exception
        setup_logging(test_settings)

    @pytest.mark.asyncio
    @patch("usmca_bot.cli.USMCABot")
    async def test_run_bot_async_starts_bot(
        self, mock_bot_class: MagicMock, test_settings
    ) -> None:
        """Test run_bot_async starts the bot.

        Args:
            mock_bot_class: Mocked USMCABot class.
            test_settings: Test settings fixture.
        """
        # Mock bot instance
        mock_bot = MagicMock()
        mock_bot.start = AsyncMock()
        mock_bot.close = AsyncMock()
        mock_bot.is_closed = MagicMock(return_value=False)
        mock_bot_class.return_value = mock_bot

        # Mock settings
        with patch("usmca_bot.cli.get_settings", return_value=test_settings):
            # This will run indefinitely, so we'll just verify it tries to start
            try:
                # Use asyncio.wait_for with timeout to avoid hanging
                import asyncio
                from usmca_bot.cli import run_bot_async

                await asyncio.wait_for(run_bot_async(), timeout=0.1)
            except asyncio.TimeoutError:
                # Expected - bot runs indefinitely
                pass

        # Verify bot was created and started
        mock_bot_class.assert_called_once()