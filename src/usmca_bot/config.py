"""Configuration management for USMCA Bot.

This module handles all configuration via Pydantic settings with environment variable
support and validation. Configuration can be loaded from .env files or environment.
"""

from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All settings can be overridden via environment variables.
    See .env.example for available options.

    Attributes:
        discord_token: Discord bot token for authentication.
        discord_guild_id: Primary guild (server) ID to monitor.
        postgres_dsn: PostgreSQL connection string.
        postgres_min_pool_size: Minimum connection pool size.
        postgres_max_pool_size: Maximum connection pool size.
        redis_url: Redis connection URL.
        redis_max_connections: Maximum Redis connection pool size.
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        environment: Deployment environment.
        toxicity_warning_threshold: Toxicity score threshold for warnings.
        toxicity_timeout_threshold: Toxicity score threshold for timeouts.
        toxicity_kick_threshold: Toxicity score threshold for kicks.
        toxicity_ban_threshold: Toxicity score threshold for bans.
        timeout_first: Duration in seconds for first timeout.
        timeout_second: Duration in seconds for second timeout.
        timeout_third: Duration in seconds for third timeout.
        brigade_joins_per_minute: Max joins per minute before brigade detection.
        brigade_similar_messages: Number of similar messages to trigger brigade detection.
        brigade_time_window: Time window in seconds for brigade detection.
        model_cache_dir: Directory to cache downloaded ML models.
        model_device: Device for ML inference ('cpu' or 'cuda').
        metrics_port: Port for Prometheus metrics server.
        metrics_enabled: Whether to enable Prometheus metrics.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Discord Configuration
    discord_token: str = Field(
        ...,
        description="Discord bot token",
        min_length=50,
    )
    discord_guild_id: int = Field(
        ...,
        description="Primary Discord guild ID",
        gt=0,
    )

    # Database Configuration
    postgres_dsn: PostgresDsn = Field(
        ...,
        description="PostgreSQL connection string",
    )
    postgres_min_pool_size: int = Field(
        default=5,
        description="Minimum PostgreSQL connection pool size",
        ge=1,
        le=50,
    )
    postgres_max_pool_size: int = Field(
        default=20,
        description="Maximum PostgreSQL connection pool size",
        ge=5,
        le=100,
    )

    # Redis Configuration
    redis_url: RedisDsn = Field(
        ...,
        description="Redis connection URL",
    )
    redis_max_connections: int = Field(
        default=50,
        description="Maximum Redis connection pool size",
        ge=10,
        le=500,
    )

    # Bot Configuration
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level",
    )
    environment: Literal["development", "staging", "production"] = Field(
        default="development",
        description="Deployment environment",
    )

    # Moderation Thresholds (0.0-1.0)
    toxicity_warning_threshold: float = Field(
        default=0.35,
        description="Toxicity score threshold for warnings",
        ge=0.0,
        le=1.0,
    )
    toxicity_timeout_threshold: float = Field(
        default=0.55,
        description="Toxicity score threshold for timeouts",
        ge=0.0,
        le=1.0,
    )
    toxicity_kick_threshold: float = Field(
        default=0.75,
        description="Toxicity score threshold for kicks",
        ge=0.0,
        le=1.0,
    )
    toxicity_ban_threshold: float = Field(
        default=0.88,
        description="Toxicity score threshold for bans",
        ge=0.0,
        le=1.0,
    )

    # Timeout Durations (seconds)
    timeout_first: int = Field(
        default=3600,
        description="First timeout duration in seconds",
        ge=60,
        le=604800,
    )
    timeout_second: int = Field(
        default=86400,
        description="Second timeout duration in seconds",
        ge=3600,
        le=604800,
    )
    timeout_third: int = Field(
        default=604800,
        description="Third timeout duration in seconds",
        ge=86400,
        le=2419200,
    )

    # Brigade Detection
    brigade_joins_per_minute: int = Field(
        default=5,
        description="Maximum joins per minute before brigade detection",
        ge=1,
        le=100,
    )
    brigade_similar_messages: int = Field(
        default=3,
        description="Number of similar messages to trigger brigade detection",
        ge=2,
        le=20,
    )
    brigade_time_window: int = Field(
        default=300,
        description="Time window in seconds for brigade detection",
        ge=60,
        le=3600,
    )

    # ML Models
    model_cache_dir: str = Field(
        default="./models",
        description="Directory to cache downloaded ML models",
    )
    model_device: Literal["cpu", "cuda"] = Field(
        default="cpu",
        description="Device for ML inference",
    )

    # Prometheus Metrics
    metrics_port: int = Field(
        default=9090,
        description="Port for Prometheus metrics server",
        ge=1024,
        le=65535,
    )
    metrics_enabled: bool = Field(
        default=True,
        description="Whether to enable Prometheus metrics",
    )

    @field_validator("postgres_max_pool_size")
    @classmethod
    def validate_pool_size(cls, v: int, info: dict) -> int:
        """Validate that max pool size is greater than min pool size.

        Args:
            v: Maximum pool size value.
            info: Field validation info containing other field values.

        Returns:
            Validated maximum pool size.

        Raises:
            ValueError: If max pool size is not greater than min pool size.
        """
        if "postgres_min_pool_size" in info.data:
            min_size = info.data["postgres_min_pool_size"]
            if v <= min_size:
                raise ValueError(
                    f"postgres_max_pool_size ({v}) must be greater than "
                    f"postgres_min_pool_size ({min_size})"
                )
        return v

    @field_validator("toxicity_timeout_threshold")
    @classmethod
    def validate_timeout_threshold(cls, v: float, info: dict) -> float:
        """Validate that timeout threshold is greater than warning threshold.

        Args:
            v: Timeout threshold value.
            info: Field validation info containing other field values.

        Returns:
            Validated timeout threshold.

        Raises:
            ValueError: If threshold ordering is invalid.
        """
        if "toxicity_warning_threshold" in info.data:
            warning = info.data["toxicity_warning_threshold"]
            if v <= warning:
                raise ValueError(
                    f"toxicity_timeout_threshold ({v}) must be greater than "
                    f"toxicity_warning_threshold ({warning})"
                )
        return v

    @field_validator("toxicity_kick_threshold")
    @classmethod
    def validate_kick_threshold(cls, v: float, info: dict) -> float:
        """Validate that kick threshold is greater than timeout threshold.

        Args:
            v: Kick threshold value.
            info: Field validation info containing other field values.

        Returns:
            Validated kick threshold.

        Raises:
            ValueError: If threshold ordering is invalid.
        """
        if "toxicity_timeout_threshold" in info.data:
            timeout = info.data["toxicity_timeout_threshold"]
            if v <= timeout:
                raise ValueError(
                    f"toxicity_kick_threshold ({v}) must be greater than "
                    f"toxicity_timeout_threshold ({timeout})"
                )
        return v

    @field_validator("toxicity_ban_threshold")
    @classmethod
    def validate_ban_threshold(cls, v: float, info: dict) -> float:
        """Validate that ban threshold is greater than kick threshold.

        Args:
            v: Ban threshold value.
            info: Field validation info containing other field values.

        Returns:
            Validated ban threshold.

        Raises:
            ValueError: If threshold ordering is invalid.
        """
        if "toxicity_kick_threshold" in info.data:
            kick = info.data["toxicity_kick_threshold"]
            if v <= kick:
                raise ValueError(
                    f"toxicity_ban_threshold ({v}) must be greater than "
                    f"toxicity_kick_threshold ({kick})"
                )
        return v

    def get_timeout_duration(self, offense_count: int) -> int:
        """Get timeout duration based on offense count.

        Args:
            offense_count: Number of previous timeouts (0-indexed).

        Returns:
            Timeout duration in seconds.
        """
        if offense_count == 0:
            return self.timeout_first
        elif offense_count == 1:
            return self.timeout_second
        else:
            return self.timeout_third

    def get_threshold_for_action(
        self, action: Literal["warning", "timeout", "kick", "ban"]
    ) -> float:
        """Get toxicity threshold for a specific action.

        Args:
            action: Moderation action type.

        Returns:
            Toxicity score threshold for the action.

        Raises:
            ValueError: If action type is invalid.
        """
        thresholds = {
            "warning": self.toxicity_warning_threshold,
            "timeout": self.toxicity_timeout_threshold,
            "kick": self.toxicity_kick_threshold,
            "ban": self.toxicity_ban_threshold,
        }
        if action not in thresholds:
            raise ValueError(f"Invalid action type: {action}")
        return thresholds[action]


# Global settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get the global settings instance.

    Returns:
        The global Settings instance.

    Note:
        Settings are loaded once and cached. To reload, use reload_settings().
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Reload settings from environment.

    Returns:
        Newly loaded Settings instance.

    Note:
        This will replace the global settings instance.
    """
    global _settings
    _settings = Settings()
    return _settings