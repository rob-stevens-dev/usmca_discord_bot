"""Tests for configuration module.

This module tests Settings validation, loading, and helper methods.
"""

import os
from typing import Any

import pytest
from pydantic import ValidationError

from usmca_bot.config import Settings, get_settings, reload_settings


class TestSettings:
    """Test suite for Settings class."""

    def test_settings_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading settings from environment variables.

        Args:
            monkeypatch: Pytest monkeypatch fixture.
        """
        monkeypatch.setenv("DISCORD_TOKEN", "x" * 59)
        monkeypatch.setenv("DISCORD_GUILD_ID", "123456789012345678")
        monkeypatch.setenv("POSTGRES_DSN", "postgresql://user:pass@localhost/db")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        settings = Settings()

        assert settings.discord_token == "x" * 59
        assert settings.discord_guild_id == 123456789012345678
        assert settings.log_level == "DEBUG"

    def test_settings_validation_token_too_short(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test validation fails for short Discord token.

        Args:
            monkeypatch: Pytest monkeypatch fixture.
        """
        monkeypatch.setenv("DISCORD_TOKEN", "short")
        monkeypatch.setenv("DISCORD_GUILD_ID", "123456789012345678")
        monkeypatch.setenv("POSTGRES_DSN", "postgresql://user:pass@localhost/db")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        with pytest.raises(ValidationError) as exc_info:
            Settings()

        assert "discord_token" in str(exc_info.value)

    def test_settings_validation_guild_id_negative(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test validation fails for negative guild ID.

        Args:
            monkeypatch: Pytest monkeypatch fixture.
        """
        monkeypatch.setenv("DISCORD_TOKEN", "x" * 59)
        monkeypatch.setenv("DISCORD_GUILD_ID", "-1")
        monkeypatch.setenv("POSTGRES_DSN", "postgresql://user:pass@localhost/db")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        with pytest.raises(ValidationError) as exc_info:
            Settings()

        assert "discord_guild_id" in str(exc_info.value)

    def test_pool_size_validation_invalid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test validation fails when max pool size <= min pool size.

        Args:
            monkeypatch: Pytest monkeypatch fixture.
        """
        monkeypatch.setenv("DISCORD_TOKEN", "x" * 59)
        monkeypatch.setenv("DISCORD_GUILD_ID", "123456789012345678")
        monkeypatch.setenv("POSTGRES_DSN", "postgresql://user:pass@localhost/db")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("POSTGRES_MIN_POOL_SIZE", "20")
        monkeypatch.setenv("POSTGRES_MAX_POOL_SIZE", "10")

        with pytest.raises(ValidationError) as exc_info:
            Settings()

        assert "postgres_max_pool_size" in str(exc_info.value)

    def test_threshold_ordering_validation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test validation enforces threshold ordering.

        Args:
            monkeypatch: Pytest monkeypatch fixture.
        """
        monkeypatch.setenv("DISCORD_TOKEN", "x" * 59)
        monkeypatch.setenv("DISCORD_GUILD_ID", "123456789012345678")
        monkeypatch.setenv("POSTGRES_DSN", "postgresql://user:pass@localhost/db")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        # Set thresholds out of order
        monkeypatch.setenv("TOXICITY_WARNING_THRESHOLD", "0.8")
        monkeypatch.setenv("TOXICITY_TIMEOUT_THRESHOLD", "0.5")

        with pytest.raises(ValidationError) as exc_info:
            Settings()

        assert "toxicity_timeout_threshold" in str(exc_info.value)

    def test_get_timeout_duration_first(self, test_settings: Settings) -> None:
        """Test getting first timeout duration.

        Args:
            test_settings: Test settings fixture.
        """
        duration = test_settings.get_timeout_duration(0)
        assert duration == test_settings.timeout_first

    def test_get_timeout_duration_second(self, test_settings: Settings) -> None:
        """Test getting second timeout duration.

        Args:
            test_settings: Test settings fixture.
        """
        duration = test_settings.get_timeout_duration(1)
        assert duration == test_settings.timeout_second

    def test_get_timeout_duration_third_and_beyond(
        self, test_settings: Settings
    ) -> None:
        """Test getting third and subsequent timeout durations.

        Args:
            test_settings: Test settings fixture.
        """
        duration_third = test_settings.get_timeout_duration(2)
        duration_fourth = test_settings.get_timeout_duration(3)
        duration_tenth = test_settings.get_timeout_duration(10)

        assert duration_third == test_settings.timeout_third
        assert duration_fourth == test_settings.timeout_third
        assert duration_tenth == test_settings.timeout_third

    def test_get_threshold_for_action_warning(
        self, test_settings: Settings
    ) -> None:
        """Test getting threshold for warning action.

        Args:
            test_settings: Test settings fixture.
        """
        threshold = test_settings.get_threshold_for_action("warning")
        assert threshold == test_settings.toxicity_warning_threshold

    def test_get_threshold_for_action_timeout(
        self, test_settings: Settings
    ) -> None:
        """Test getting threshold for timeout action.

        Args:
            test_settings: Test settings fixture.
        """
        threshold = test_settings.get_threshold_for_action("timeout")
        assert threshold == test_settings.toxicity_timeout_threshold

    def test_get_threshold_for_action_kick(self, test_settings: Settings) -> None:
        """Test getting threshold for kick action.

        Args:
            test_settings: Test settings fixture.
        """
        threshold = test_settings.get_threshold_for_action("kick")
        assert threshold == test_settings.toxicity_kick_threshold

    def test_get_threshold_for_action_ban(self, test_settings: Settings) -> None:
        """Test getting threshold for ban action.

        Args:
            test_settings: Test settings fixture.
        """
        threshold = test_settings.get_threshold_for_action("ban")
        assert threshold == test_settings.toxicity_ban_threshold

    def test_get_threshold_for_action_invalid(
        self, test_settings: Settings
    ) -> None:
        """Test getting threshold for invalid action raises error.

        Args:
            test_settings: Test settings fixture.
        """
        with pytest.raises(ValueError) as exc_info:
            test_settings.get_threshold_for_action("invalid")  # type: ignore

        assert "Invalid action type" in str(exc_info.value)

    def test_default_values(self, test_settings: Settings) -> None:
        """Test default configuration values are set correctly.

        Args:
            test_settings: Test settings fixture.
        """
        # Note: test_settings fixture may override defaults
        assert test_settings.log_level in ["DEBUG", "INFO"]  # Can vary by fixture
        assert test_settings.environment in ["development", "production"]  # Can vary by fixture
        assert test_settings.toxicity_warning_threshold == 0.35
        assert test_settings.toxicity_timeout_threshold == 0.55
        assert test_settings.toxicity_kick_threshold == 0.75
        assert test_settings.toxicity_ban_threshold == 0.88
        assert test_settings.timeout_first == 3600
        assert test_settings.timeout_second == 86400
        assert test_settings.timeout_third == 604800
        assert test_settings.brigade_joins_per_minute == 5
        assert test_settings.brigade_similar_messages == 3
        assert test_settings.brigade_time_window == 300
        assert test_settings.model_device in ["cpu", "cuda"]  # Can vary by fixture/system
        assert test_settings.metrics_enabled is False  # Set by test fixture


class TestGetSettings:
    """Test suite for get_settings() function."""

    def test_get_settings_returns_same_instance(
        self, test_settings: Settings
    ) -> None:
        """Test get_settings() returns cached instance.

        Args:
            test_settings: Test settings fixture.
        """
        # Clear the global cache first
        import usmca_bot.config

        usmca_bot.config._settings = None

        settings1 = get_settings()
        settings2 = get_settings()

        assert settings1 is settings2

    def test_reload_settings_creates_new_instance(
        self, test_settings: Settings
    ) -> None:
        """Test reload_settings() creates new instance.

        Args:
            test_settings: Test settings fixture.
        """
        settings1 = get_settings()
        settings2 = reload_settings()

        # They should be different instances
        assert settings1 is not settings2


class TestThresholdValidation:
    """Test suite for comprehensive threshold validation."""

    @pytest.mark.parametrize(
        "warning,timeout,kick,ban,should_pass",
        [
            (0.3, 0.5, 0.7, 0.9, True),  # Valid ordering
            (0.1, 0.3, 0.6, 0.8, True),  # Valid ordering
            (0.5, 0.5, 0.7, 0.9, False),  # Equal warning and timeout
            (0.3, 0.5, 0.4, 0.9, False),  # Kick lower than timeout
            (0.3, 0.5, 0.7, 0.6, False),  # Ban lower than kick
        ],
    )
    def test_threshold_validation_matrix(
        self,
        monkeypatch: pytest.MonkeyPatch,
        warning: float,
        timeout: float,
        kick: float,
        ban: float,
        should_pass: bool,
    ) -> None:
        """Test various threshold combinations.

        Args:
            monkeypatch: Pytest monkeypatch fixture.
            warning: Warning threshold value.
            timeout: Timeout threshold value.
            kick: Kick threshold value.
            ban: Ban threshold value.
            should_pass: Whether validation should pass.
        """
        monkeypatch.setenv("DISCORD_TOKEN", "x" * 59)
        monkeypatch.setenv("DISCORD_GUILD_ID", "123456789012345678")
        monkeypatch.setenv("POSTGRES_DSN", "postgresql://user:pass@localhost/db")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("TOXICITY_WARNING_THRESHOLD", str(warning))
        monkeypatch.setenv("TOXICITY_TIMEOUT_THRESHOLD", str(timeout))
        monkeypatch.setenv("TOXICITY_KICK_THRESHOLD", str(kick))
        monkeypatch.setenv("TOXICITY_BAN_THRESHOLD", str(ban))

        if should_pass:
            settings = Settings()
            assert settings.toxicity_warning_threshold == warning
            assert settings.toxicity_timeout_threshold == timeout
            assert settings.toxicity_kick_threshold == kick
            assert settings.toxicity_ban_threshold == ban
        else:
            with pytest.raises(ValidationError):
                Settings()