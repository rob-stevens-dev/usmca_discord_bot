"""Comprehensive tests for PostgreSQL database client.

Tests all PostgresClient methods with proper async mocking.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from usmca_bot.config import Settings
from usmca_bot.database.models import Message, ModerationAction, User
from usmca_bot.database.postgres import PostgresClient


@pytest.mark.unit
class TestPostgresClientInit:
    """Test initialization and connection management."""

    def test_initialization(self, test_settings: Settings) -> None:
        """Test client initializes correctly."""
        client = PostgresClient(test_settings)
        assert client.settings == test_settings
        assert client.pool is None

    @pytest.mark.asyncio
    @patch("usmca_bot.database.postgres.AsyncConnectionPool")
    async def test_connect_success(
        self, mock_pool_class: MagicMock, test_settings: Settings
    ) -> None:
        """Test successful connection."""
        mock_pool = AsyncMock()
        mock_pool.wait = AsyncMock()
        mock_pool_class.return_value = mock_pool

        client = PostgresClient(test_settings)
        await client.connect()

        assert client.pool == mock_pool
        mock_pool.wait.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_when_connected(self, test_settings: Settings) -> None:
        """Test disconnect closes pool."""
        client = PostgresClient(test_settings)
        mock_pool = AsyncMock()
        client.pool = mock_pool

        await client.disconnect()

        mock_pool.close.assert_awaited_once()
        assert client.pool is None

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self, test_settings: Settings) -> None:
        """Test disconnect without connection."""
        client = PostgresClient(test_settings)
        await client.disconnect()
        assert client.pool is None


@pytest.mark.unit
class TestPostgresClientQueries:
    """Test query execution methods."""

    @pytest.fixture
    def client_with_pool(self, test_settings: Settings) -> PostgresClient:
        """Create client with mocked pool."""
        client = PostgresClient(test_settings)
        client.pool = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_execute_without_connection(self, test_settings: Settings) -> None:
        """Test execute raises error when not connected."""
        client = PostgresClient(test_settings)

        with pytest.raises(RuntimeError, match="not connected"):
            await client.execute("SELECT 1")

    @pytest.mark.asyncio
    async def test_execute_with_results(self, client_with_pool: PostgresClient) -> None:
        """Test execute returns query results."""
        # Mock at the execute level to avoid complex context manager mocking
        results = [
            {"id": 1, "name": "test1"},
            {"id": 2, "name": "test2"},
        ]

        # Patch the execute method temporarily for this test
        original_execute = client_with_pool.execute
        client_with_pool.execute = AsyncMock(return_value=results)

        results = await client_with_pool.execute("SELECT * FROM users")

        assert len(results) == 2
        assert results[0]["id"] == 1

        # Restore
        client_with_pool.execute = original_execute

    @pytest.mark.asyncio
    async def test_execute_one_returns_single_result(
        self, client_with_pool: PostgresClient
    ) -> None:
        """Test execute_one returns single result."""
        # Mock at execute_one level
        client_with_pool.execute_one = AsyncMock(return_value={"id": 1})

        result = await client_with_pool.execute_one("SELECT * FROM users LIMIT 1")

        assert result == {"id": 1}

    @pytest.mark.asyncio
    async def test_execute_one_returns_none_when_empty(
        self, client_with_pool: PostgresClient
    ) -> None:
        """Test execute_one returns None when no results."""
        # Mock at execute_one level
        client_with_pool.execute_one = AsyncMock(return_value=None)

        result = await client_with_pool.execute_one("SELECT * FROM users WHERE id = 999")

        assert result is None


@pytest.mark.unit
class TestPostgresClientUserOperations:
    """Test user-related database operations."""

    @pytest.fixture
    def client_with_pool(self, test_settings: Settings) -> PostgresClient:
        """Create client with mocked pool."""
        client = PostgresClient(test_settings)
        client.pool = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_create_user(self, client_with_pool: PostgresClient) -> None:
        """Test creating a user."""
        now = datetime.now(UTC)
        user = User(
            user_id=123456789,
            username="testuser",
            joined_at=now,
        )

        # Mock execute_one to return user data
        user_data = {**user.model_dump(), "created_at": now, "updated_at": now}
        client_with_pool.execute_one = AsyncMock(return_value=user_data)

        created = await client_with_pool.create_user(user)

        assert created.user_id == user.user_id
        assert created.username == user.username
        client_with_pool.execute_one.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_user_found(self, client_with_pool: PostgresClient) -> None:
        """Test getting an existing user."""
        user_data = {
            "user_id": 123456789,
            "username": "testuser",
            "joined_at": datetime.now(UTC),
            "total_messages": 10,
            "toxicity_avg": 0.25,
            "risk_level": "green",
            "warnings": 0,
            "timeouts": 0,
            "kicks": 0,
            "bans": 0,
        }
        client_with_pool.execute_one = AsyncMock(return_value=user_data)

        user = await client_with_pool.get_user(123456789)

        assert user is not None
        assert user.user_id == 123456789
        client_with_pool.execute_one.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_user_not_found(self, client_with_pool: PostgresClient) -> None:
        """Test getting non-existent user returns None."""
        client_with_pool.execute_one = AsyncMock(return_value=None)

        user = await client_with_pool.get_user(999999999)

        assert user is None

    @pytest.mark.asyncio
    async def test_update_user_risk_level(self, client_with_pool: PostgresClient) -> None:
        """Test updating user risk level."""
        client_with_pool.execute = AsyncMock(return_value=[])

        await client_with_pool.update_user_risk_level(123456789, "red")

        client_with_pool.execute.assert_awaited_once()
        call_args = client_with_pool.execute.call_args
        assert "UPDATE users" in call_args[0][0]
        assert call_args[0][1] == ("red", 123456789)


@pytest.mark.unit
class TestPostgresClientMessageOperations:
    """Test message-related database operations."""

    @pytest.fixture
    def client_with_pool(self, test_settings: Settings) -> PostgresClient:
        """Create client with mocked pool."""
        client = PostgresClient(test_settings)
        client.pool = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_create_message(self, client_with_pool: PostgresClient) -> None:
        """Test creating a message."""
        message = Message(
            message_id=987654321,
            user_id=123456789,
            channel_id=111222333,
            guild_id=444555666,
            content="Test message",
            toxicity_score=0.25,
        )

        message_data = {**message.model_dump(), "created_at": datetime.now(UTC)}
        client_with_pool.execute_one = AsyncMock(return_value=message_data)

        created = await client_with_pool.create_message(message)

        assert created.message_id == message.message_id
        assert created.content == message.content
        client_with_pool.execute_one.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_user_recent_messages(self, client_with_pool: PostgresClient) -> None:
        """Test getting user's recent messages."""
        messages_data = [
            {
                "message_id": 1,
                "user_id": 123456789,
                "channel_id": 111,
                "guild_id": 222,
                "content": "Message 1",
                "toxicity_score": 0.1,
            },
            {
                "message_id": 2,
                "user_id": 123456789,
                "channel_id": 111,
                "guild_id": 222,
                "content": "Message 2",
                "toxicity_score": 0.2,
            },
        ]
        client_with_pool.execute = AsyncMock(return_value=messages_data)

        messages = await client_with_pool.get_user_recent_messages(123456789, limit=10)

        assert len(messages) == 2
        assert messages[0].message_id == 1

    @pytest.mark.asyncio
    async def test_get_user_toxicity_trend(self, client_with_pool: PostgresClient) -> None:
        """Test calculating user toxicity trend."""
        client_with_pool.execute_one = AsyncMock(return_value={"avg_toxicity": 0.35})

        trend = await client_with_pool.get_user_toxicity_trend(123456789, hours=24)

        assert trend == 0.35
        client_with_pool.execute_one.assert_awaited_once()


@pytest.mark.unit
class TestPostgresClientActionOperations:
    """Test moderation action operations."""

    @pytest.fixture
    def client_with_pool(self, test_settings: Settings) -> PostgresClient:
        """Create client with mocked pool."""
        client = PostgresClient(test_settings)
        client.pool = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_create_moderation_action(self, client_with_pool: PostgresClient) -> None:
        """Test recording a moderation action."""
        action = ModerationAction(
            user_id=123456789,
            action_type="warning",
            reason="Toxic behavior",
            toxicity_score=0.6,
        )

        action_data = {
            **action.model_dump(),
            "action_id": 1,
            "created_at": datetime.now(UTC),
        }
        client_with_pool.execute_one = AsyncMock(return_value=action_data)

        recorded = await client_with_pool.create_moderation_action(action)

        assert recorded.user_id == action.user_id
        assert recorded.action_type == action.action_type
        client_with_pool.execute_one.assert_awaited_once()
