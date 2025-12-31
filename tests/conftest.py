"""Pytest configuration and shared fixtures.

This module provides common test fixtures and configuration for all tests.
"""

import os
from datetime import datetime, timezone
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from pydantic import PostgresDsn, RedisDsn

from usmca_bot.config import Settings
from usmca_bot.database.models import Message, ToxicityScores, User


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Create test settings with safe defaults.

    Returns:
        Settings instance configured for testing.
    """
    # Override environment variables for testing
    os.environ.update(
        {
            "DISCORD_TOKEN": "test_token_" + "x" * 50,
            "DISCORD_GUILD_ID": "123456789012345678",
            "POSTGRES_DSN": "postgresql://test:test@localhost:5432/test_db",
            "REDIS_URL": "redis://localhost:6379/1",
            "LOG_LEVEL": "DEBUG",
            "ENVIRONMENT": "development",
            "MODEL_DEVICE": "cpu",
            "METRICS_ENABLED": "false",
        }
    )

    return Settings()


@pytest.fixture
def mock_discord_user() -> MagicMock:
    """Create a mock Discord user object.

    Returns:
        Mock Discord user with common attributes.
    """
    user = MagicMock()
    user.id = 123456789012345678
    user.name = "testuser"
    user.discriminator = "1234"
    user.display_name = "Test User"
    return user


@pytest.fixture
def mock_discord_message() -> MagicMock:
    """Create a mock Discord message object.

    Returns:
        Mock Discord message with common attributes.
    """
    message = MagicMock()
    message.id = 987654321098765432
    message.author = MagicMock()
    message.author.id = 123456789012345678
    message.author.name = "testuser"
    message.author.discriminator = "1234"
    message.channel = MagicMock()
    message.channel.id = 111222333444555666
    message.guild = MagicMock()
    message.guild.id = 777888999000111222
    message.content = "Test message content"
    message.created_at = datetime.now(timezone.utc)
    return message


@pytest.fixture
def sample_user() -> User:
    """Create a sample User model for testing.

    Returns:
        User model instance with test data.
    """
    return User(
        user_id=123456789012345678,
        username="testuser",
        discriminator="1234",
        display_name="Test User",
        joined_at=datetime.now(timezone.utc),
        total_messages=10,
        toxicity_avg=0.15,
        warnings=0,
        timeouts=0,
        kicks=0,
        bans=0,
        risk_level="green",
        is_whitelisted=False,
    )


@pytest.fixture
def sample_message() -> Message:
    """Create a sample Message model for testing.

    Returns:
        Message model instance with test data.
    """
    return Message(
        message_id=987654321098765432,
        user_id=123456789012345678,
        channel_id=111222333444555666,
        guild_id=777888999000111222,
        content="This is a test message",
        toxicity_score=0.1,
        severe_toxicity_score=0.05,
        obscene_score=0.03,
        threat_score=0.02,
        insult_score=0.04,
        identity_attack_score=0.01,
        sentiment_score=0.5,
    )


@pytest.fixture
def sample_toxicity_scores() -> ToxicityScores:
    """Create sample toxicity scores for testing.

    Returns:
        ToxicityScores instance with moderate values.
    """
    return ToxicityScores(
        toxicity=0.25,
        severe_toxicity=0.10,
        obscene=0.08,
        threat=0.05,
        insult=0.15,
        identity_attack=0.03,
    )


@pytest.fixture
def high_toxicity_scores() -> ToxicityScores:
    """Create high toxicity scores for testing.

    Returns:
        ToxicityScores instance with high values.
    """
    return ToxicityScores(
        toxicity=0.95,
        severe_toxicity=0.90,
        obscene=0.85,
        threat=0.80,
        insult=0.92,
        identity_attack=0.88,
    )


@pytest_asyncio.fixture
async def mock_postgres_client() -> AsyncMock:
    """Create a mock PostgreSQL client.

    Returns:
        AsyncMock of PostgresClient with common methods.
    """
    client = AsyncMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.health_check = AsyncMock(return_value=True)
    client.create_user = AsyncMock()
    client.get_user = AsyncMock()
    client.create_message = AsyncMock()
    client.create_moderation_action = AsyncMock()
    return client


@pytest_asyncio.fixture
async def mock_redis_client() -> AsyncMock:
    """Create a mock Redis client.

    Returns:
        AsyncMock of RedisClient with common methods.
    """
    client = AsyncMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.health_check = AsyncMock(return_value=True)
    client.check_user_rate_limit = AsyncMock(return_value=(True, 1))
    client.is_duplicate_message = AsyncMock(return_value=False)
    client.is_user_timed_out = AsyncMock(return_value=False)
    return client


@pytest_asyncio.fixture
async def mock_classification_engine() -> AsyncMock:
    """Create a mock classification engine.

    Returns:
        AsyncMock of ClassificationEngine with common methods.
    """
    from usmca_bot.classification.engine import ClassificationResult
    from usmca_bot.database.models import ToxicityScores

    engine = AsyncMock()

    # Default classification result
    default_result = ClassificationResult(
        toxicity_scores=ToxicityScores(
            toxicity=0.1,
            severe_toxicity=0.05,
            obscene=0.03,
            threat=0.02,
            insult=0.04,
            identity_attack=0.01,
        ),
        sentiment_score=0.5,
        processing_time_ms=50.0,
        model_versions={"toxicity": "unbiased"},
    )

    engine.classify_message = AsyncMock(return_value=default_result)
    engine.classify_messages_batch = AsyncMock(return_value=[default_result])
    engine.warmup = AsyncMock()
    engine.health_check = AsyncMock(return_value={"status": "healthy"})

    return engine

@pytest.fixture
def mock_discord_member() -> MagicMock:
    """Create a mock Discord member (guild-specific user)."""
    member = MagicMock()
    member.id = 123456789012345678
    member.name = "testuser"
    member.discriminator = "1234"
    member.display_name = "Test User"
    member.timeout = AsyncMock()
    member.send = AsyncMock()
    return member

@pytest.fixture
def mock_discord_bot() -> MagicMock:
    """Create a mock Discord bot client."""
    bot = MagicMock()
    bot.get_guild = MagicMock()
    return bot

# Markers for test categorization
def pytest_configure(config: pytest.Config) -> None:
    """Configure custom pytest markers.

    Args:
        config: Pytest configuration object.
    """
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "unit: marks tests as unit tests")
    config.addinivalue_line("markers", "ml: marks tests that require ML models")