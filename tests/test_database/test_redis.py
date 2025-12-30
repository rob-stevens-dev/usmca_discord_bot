"""Comprehensive tests for Redis client.

Tests all RedisClient methods with proper async mocking.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from usmca_bot.config import Settings
from usmca_bot.database.redis import RedisClient


@pytest.mark.unit
class TestRedisClientInit:
    """Test initialization and connection management."""

    def test_initialization(self, test_settings: Settings) -> None:
        """Test client initializes correctly."""
        client = RedisClient(test_settings)
        assert client.settings == test_settings
        assert client.client is None

    @pytest.mark.asyncio
    @patch("usmca_bot.database.redis.redis.from_url")
    async def test_connect_success(
        self, mock_from_url: MagicMock, test_settings: Settings
    ) -> None:
        """Test successful connection."""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()
        mock_from_url.return_value = mock_redis

        client = RedisClient(test_settings)
        await client.connect()

        assert client.client == mock_redis
        mock_redis.ping.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_when_connected(
        self, test_settings: Settings
    ) -> None:
        """Test disconnect closes client."""
        client = RedisClient(test_settings)
        mock_redis = AsyncMock()
        client.client = mock_redis

        await client.disconnect()

        mock_redis.aclose.assert_awaited_once()
        assert client.client is None

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(
        self, test_settings: Settings
    ) -> None:
        """Test disconnect without connection."""
        client = RedisClient(test_settings)
        await client.disconnect()
        assert client.client is None


@pytest.mark.unit
class TestRedisClientRateLimiting:
    """Test rate limiting operations."""

    @pytest.fixture
    def client_with_redis(self, test_settings: Settings) -> RedisClient:
        """Create client with mocked Redis."""
        client = RedisClient(test_settings)
        client.client = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_check_rate_limit_without_connection(
        self, test_settings: Settings
    ) -> None:
        """Test rate limit check raises error when not connected."""
        client = RedisClient(test_settings)

        with pytest.raises(RuntimeError, match="not connected"):
            await client.check_user_rate_limit(123456789)

    @pytest.mark.asyncio
    async def test_check_user_rate_limit_allowed(
        self, client_with_redis: RedisClient
    ) -> None:
        """Test rate limit check when under limit."""
        # Mock pipeline - pipeline() returns the mock, methods are sync
        mock_pipeline = MagicMock()
        mock_pipeline.zremrangebyscore = MagicMock(return_value=mock_pipeline)
        mock_pipeline.zadd = MagicMock(return_value=mock_pipeline)
        mock_pipeline.zcard = MagicMock(return_value=mock_pipeline)
        mock_pipeline.expire = MagicMock(return_value=mock_pipeline)
        mock_pipeline.execute = AsyncMock(return_value=[None, None, 5, True])
        client_with_redis.client.pipeline = MagicMock(return_value=mock_pipeline)

        is_allowed, count = await client_with_redis.check_user_rate_limit(
            user_id=123456789, max_messages=10, window_seconds=60
        )

        assert is_allowed is True
        assert count == 5

    @pytest.mark.asyncio
    async def test_check_user_rate_limit_exceeded(
        self, client_with_redis: RedisClient
    ) -> None:
        """Test rate limit check when limit exceeded."""
        # Mock pipeline - 15 messages (over limit of 10)
        mock_pipeline = MagicMock()
        mock_pipeline.zremrangebyscore = MagicMock(return_value=mock_pipeline)
        mock_pipeline.zadd = MagicMock(return_value=mock_pipeline)
        mock_pipeline.zcard = MagicMock(return_value=mock_pipeline)
        mock_pipeline.expire = MagicMock(return_value=mock_pipeline)
        mock_pipeline.execute = AsyncMock(return_value=[None, None, 15, True])
        client_with_redis.client.pipeline = MagicMock(return_value=mock_pipeline)

        is_allowed, count = await client_with_redis.check_user_rate_limit(
            user_id=123456789, max_messages=10, window_seconds=60
        )

        assert is_allowed is False
        assert count == 15

    @pytest.mark.asyncio
    async def test_check_global_rate_limit(
        self, client_with_redis: RedisClient
    ) -> None:
        """Test global rate limit check."""
        mock_pipeline = MagicMock()
        mock_pipeline.zremrangebyscore = MagicMock(return_value=mock_pipeline)
        mock_pipeline.zadd = MagicMock(return_value=mock_pipeline)
        mock_pipeline.zcard = MagicMock(return_value=mock_pipeline)
        mock_pipeline.expire = MagicMock(return_value=mock_pipeline)
        mock_pipeline.execute = AsyncMock(return_value=[None, None, 50, True])
        client_with_redis.client.pipeline = MagicMock(return_value=mock_pipeline)

        is_allowed, count = await client_with_redis.check_global_rate_limit(
            max_messages=100, window_seconds=60
        )

        assert is_allowed is True
        assert count == 50


@pytest.mark.unit
class TestRedisClientDeduplication:
    """Test message deduplication operations."""

    @pytest.fixture
    def client_with_redis(self, test_settings: Settings) -> RedisClient:
        """Create client with mocked Redis."""
        client = RedisClient(test_settings)
        client.client = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_is_duplicate_message_new(
        self, client_with_redis: RedisClient
    ) -> None:
        """Test checking if message is duplicate (new message)."""
        # set() returns True when key was set (not a duplicate)
        client_with_redis.client.set = AsyncMock(return_value=True)

        is_dup = await client_with_redis.is_duplicate_message(
            message_id=987654321, ttl_seconds=60
        )

        assert is_dup is False

    @pytest.mark.asyncio
    async def test_is_duplicate_message_duplicate(
        self, client_with_redis: RedisClient
    ) -> None:
        """Test checking if message is duplicate (duplicate found)."""
        # set() returns None when key already exists (is a duplicate)
        client_with_redis.client.set = AsyncMock(return_value=None)

        is_dup = await client_with_redis.is_duplicate_message(
            message_id=987654321, ttl_seconds=60
        )

        assert is_dup is True


@pytest.mark.unit
class TestRedisClientTimeouts:
    """Test timeout tracking operations."""

    @pytest.fixture
    def client_with_redis(self, test_settings: Settings) -> RedisClient:
        """Create client with mocked Redis."""
        client = RedisClient(test_settings)
        client.client = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_set_active_timeout(
        self, client_with_redis: RedisClient
    ) -> None:
        """Test setting active timeout."""
        client_with_redis.client.setex = AsyncMock()

        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        await client_with_redis.set_active_timeout(123456789, expires_at)

        client_with_redis.client.setex.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_is_user_timed_out_true(
        self, client_with_redis: RedisClient
    ) -> None:
        """Test checking if user is timed out (yes)."""
        client_with_redis.client.exists = AsyncMock(return_value=1)

        is_timed_out = await client_with_redis.is_user_timed_out(123456789)

        assert is_timed_out is True

    @pytest.mark.asyncio
    async def test_is_user_timed_out_false(
        self, client_with_redis: RedisClient
    ) -> None:
        """Test checking if user is timed out (no)."""
        client_with_redis.client.exists = AsyncMock(return_value=0)

        is_timed_out = await client_with_redis.is_user_timed_out(123456789)

        assert is_timed_out is False

    @pytest.mark.asyncio
    async def test_clear_timeout(
        self, client_with_redis: RedisClient
    ) -> None:
        """Test clearing timeout."""
        client_with_redis.client.delete = AsyncMock()

        await client_with_redis.clear_timeout(123456789)

        client_with_redis.client.delete.assert_awaited_once()


@pytest.mark.unit
class TestRedisClientBrigadeDetection:
    """Test brigade detection operations."""

    @pytest.fixture
    def client_with_redis(self, test_settings: Settings) -> RedisClient:
        """Create client with mocked Redis."""
        client = RedisClient(test_settings)
        client.client = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_track_join_event(
        self, client_with_redis: RedisClient
    ) -> None:
        """Test tracking member join."""
        mock_pipeline = MagicMock()
        mock_pipeline.sadd = MagicMock(return_value=mock_pipeline)
        mock_pipeline.expire = MagicMock(return_value=mock_pipeline)
        mock_pipeline.scard = MagicMock(return_value=mock_pipeline)
        mock_pipeline.execute = AsyncMock(return_value=[None, True, 10])
        client_with_redis.client.pipeline = MagicMock(return_value=mock_pipeline)

        count = await client_with_redis.track_join_event(
            user_id=123456789, timestamp=datetime.now(timezone.utc)
        )

        assert count == 10

    @pytest.mark.asyncio
    async def test_track_similar_message(
        self, client_with_redis: RedisClient
    ) -> None:
        """Test tracking similar messages."""
        mock_pipeline = MagicMock()
        mock_pipeline.sadd = MagicMock(return_value=mock_pipeline)
        mock_pipeline.expire = MagicMock(return_value=mock_pipeline)
        mock_pipeline.scard = MagicMock(return_value=mock_pipeline)
        mock_pipeline.execute = AsyncMock(return_value=[None, True, 5])
        client_with_redis.client.pipeline = MagicMock(return_value=mock_pipeline)

        count = await client_with_redis.track_similar_message(
            content="Test message",
            user_id=123456789,
            timestamp=datetime.now(timezone.utc)
        )

        assert count == 5

    @pytest.mark.asyncio
    async def test_get_recent_joins(
        self, client_with_redis: RedisClient
    ) -> None:
        """Test getting recent member joins."""
        # Mock keys() to return brigade keys
        client_with_redis.client.keys = AsyncMock(return_value=[
            "brigade:joins:202412301430",
            "brigade:joins:202412301431",
        ])
        
        # Mock smembers() to return user IDs
        client_with_redis.client.smembers = AsyncMock(return_value={
            "123456789",
            "987654321",
        })

        joins = await client_with_redis.get_recent_joins(minutes=5)

        assert len(joins) >= 2
        assert isinstance(joins, set)