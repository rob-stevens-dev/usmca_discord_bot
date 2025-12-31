"""PostgreSQL database client for USMCA Bot.

This module provides an async PostgreSQL client with connection pooling,
query execution, and high-level database operations.
"""

import contextlib
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from usmca_bot.config import Settings
from usmca_bot.database.models import (
    Appeal,
    BrigadeEvent,
    Message,
    ModerationAction,
    User,
)


class PostgresClient:
    """Async PostgreSQL client with connection pooling.

    This client manages a connection pool and provides high-level methods
    for database operations. All methods are async and support transactions.

    Attributes:
        settings: Application settings containing database configuration.
        pool: Async connection pool for PostgreSQL.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize PostgreSQL client.

        Args:
            settings: Application settings.
        """
        self.settings = settings
        self.pool: AsyncConnectionPool | None = None

    async def connect(self) -> None:
        """Establish connection pool to PostgreSQL.

        Creates an async connection pool with configured min/max sizes.

        Raises:
            psycopg.Error: If connection fails.
        """
        self.pool = AsyncConnectionPool(
            conninfo=str(self.settings.postgres_dsn),
            min_size=self.settings.postgres_min_pool_size,
            max_size=self.settings.postgres_max_pool_size,
            kwargs={
                "row_factory": dict_row,
                "autocommit": False,
            },
        )
        await self.pool.wait()

    async def disconnect(self) -> None:
        """Close connection pool gracefully.

        Waits for all connections to be returned before closing.
        """
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    @contextlib.asynccontextmanager
    async def transaction(self) -> AsyncIterator[psycopg.AsyncConnection]:
        """Context manager for database transactions.

                Yields:
                    Database connection with transaction.

                Raises:
                    psycopg.Error: If transaction fails.

                Example:
        ```python
        async with client.transaction() as conn:
                    await conn.execute("INSERT INTO ...")
                    await conn.execute("UPDATE ...")
                # Transaction commits automatically if no exception

        """
        if self.pool is None:
            raise RuntimeError("Database not connected. Call connect() first.")

        async with self.pool.connection() as conn, conn.transaction():
            yield conn

    async def execute(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> list[dict[str, Any]]:
        """Execute query and return results.

        Args:
            query: SQL query string.
            params: Query parameters (optional).

        Returns:
            List of result rows as dictionaries.

        Raises:
            psycopg.Error: If query execution fails.
        """
        if self.pool is None:
            raise RuntimeError("Database not connected. Call connect() first.")

        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(query, params)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = await cur.fetchall()
            return [dict(zip(columns, row, strict=True)) for row in rows]

    async def execute_one(
        self, query: str, params: tuple[Any, ...] | dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Execute query and return single result.

        Args:
            query: SQL query with %s or %(name)s placeholders.
            params: Query parameters as tuple or dict.
        """
        if self.pool is None:
            raise RuntimeError("Database not connected. Call connect() first.")

        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(query, params)
            if cur.description:
                columns = [desc[0] for desc in cur.description]
                row = await cur.fetchone()
                return dict(zip(columns, row, strict=True)) if row else None
            return None

    # User Operations

    async def create_user(self, user: User) -> User:
        """Create a new user record.

        Args:
            user: User object to create.

        Returns:
            Created user with database-generated fields populated.

        Raises:
            psycopg.Error: If creation fails.
        """
        query = """
            INSERT INTO users (
                user_id, username, discriminator, display_name, joined_at,
                first_message_at, total_messages, toxicity_avg, warnings,
                timeouts, kicks, bans, last_action_at, risk_level,
                is_whitelisted, notes
            ) VALUES (
                %(user_id)s, %(username)s, %(discriminator)s, %(display_name)s,
                %(joined_at)s, %(first_message_at)s, %(total_messages)s,
                %(toxicity_avg)s, %(warnings)s, %(timeouts)s, %(kicks)s,
                %(bans)s, %(last_action_at)s, %(risk_level)s,
                %(is_whitelisted)s, %(notes)s
            )
            ON CONFLICT (user_id) DO UPDATE SET
                username = EXCLUDED.username,
                discriminator = EXCLUDED.discriminator,
                display_name = EXCLUDED.display_name,
                updated_at = NOW()
            RETURNING *
        """
        result = await self.execute_one(query, user.model_dump())
        assert result is not None
        return User.model_validate(result)

    async def get_user(self, user_id: int) -> User | None:
        """Get user by ID.

        Args:
            user_id: Discord user ID.

        Returns:
            User object if found, None otherwise.

        Raises:
            psycopg.Error: If query fails.
        """
        query = "SELECT * FROM users WHERE user_id = %s"
        result = await self.execute_one(query, (user_id,))
        return User.model_validate(result) if result else None

    async def update_user_risk_level(self, user_id: int, risk_level: str) -> None:
        """Update user's risk level.

        Args:
            user_id: Discord user ID.
            risk_level: New risk level ('green', 'yellow', 'orange', 'red').

        Raises:
            psycopg.Error: If update fails.
        """
        query = """
            UPDATE users
            SET risk_level = %s, updated_at = NOW()
            WHERE user_id = %s
        """
        await self.execute(query, (risk_level, user_id))

    # Message Operations

    async def create_message(self, message: Message) -> Message:
        """Create a new message record.

        Args:
            message: Message object to create.

        Returns:
            Created message with database-generated fields populated.

        Raises:
            psycopg.Error: If creation fails.
        """
        query = """
            INSERT INTO messages (
                message_id, user_id, channel_id, guild_id, content,
                toxicity_score, severe_toxicity_score, obscene_score,
                threat_score, insult_score, identity_attack_score,
                sentiment_score, is_edited, is_deleted, deleted_at
            ) VALUES (
                %(message_id)s, %(user_id)s, %(channel_id)s, %(guild_id)s,
                %(content)s, %(toxicity_score)s, %(severe_toxicity_score)s,
                %(obscene_score)s, %(threat_score)s, %(insult_score)s,
                %(identity_attack_score)s, %(sentiment_score)s, %(is_edited)s,
                %(is_deleted)s, %(deleted_at)s
            )
            RETURNING *
        """
        result = await self.execute_one(query, message.model_dump())
        assert result is not None
        return Message.model_validate(result)

    async def get_user_recent_messages(self, user_id: int, limit: int = 50) -> list[Message]:
        """Get user's recent messages.

        Args:
            user_id: Discord user ID.
            limit: Maximum number of messages to retrieve.

        Returns:
            List of recent messages, newest first.

        Raises:
            psycopg.Error: If query fails.
        """
        query = """
            SELECT * FROM messages
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """
        results = await self.execute(query, (user_id, limit))
        return [Message.model_validate(r) for r in results]

    async def get_user_toxicity_trend(self, user_id: int, hours: int = 24) -> float:
        """Calculate user's toxicity trend over time window.

        Args:
            user_id: Discord user ID.
            hours: Time window in hours.

        Returns:
            Average toxicity score over the time window, or 0.0 if no messages.

        Raises:
            psycopg.Error: If query fails.
        """
        query = """
            SELECT AVG(toxicity_score) as avg_toxicity
            FROM messages
            WHERE user_id = %s
            AND created_at > NOW() - INTERVAL '%s hours'
            AND toxicity_score IS NOT NULL
        """
        result = await self.execute_one(query, (user_id, hours))
        return float(result["avg_toxicity"]) if result and result["avg_toxicity"] else 0.0

    # Moderation Action Operations

    async def create_moderation_action(self, action: ModerationAction) -> ModerationAction:
        """Create a new moderation action record.

        Args:
            action: ModerationAction object to create.

        Returns:
            Created action with database-generated fields populated.

        Raises:
            psycopg.Error: If creation fails.
        """
        query = """
            INSERT INTO moderation_actions (
                user_id, message_id, action_type, reason, toxicity_score,
                behavior_score, context_score, final_score, is_automated,
                moderator_id, moderator_name, expires_at
            ) VALUES (
                %(user_id)s, %(message_id)s, %(action_type)s, %(reason)s,
                %(toxicity_score)s, %(behavior_score)s, %(context_score)s,
                %(final_score)s, %(is_automated)s, %(moderator_id)s,
                %(moderator_name)s, %(expires_at)s
            )
            RETURNING *
        """
        result = await self.execute_one(
            query,
            action.model_dump(exclude={"id", "action_uuid", "appealed", "appeal_id", "created_at"}),
        )
        assert result is not None
        return ModerationAction.model_validate(result)

    async def get_user_action_history(
        self, user_id: int, limit: int = 20
    ) -> list[ModerationAction]:
        """Get user's moderation action history.

        Args:
            user_id: Discord user ID.
            limit: Maximum number of actions to retrieve.

        Returns:
            List of moderation actions, newest first.

        Raises:
            psycopg.Error: If query fails.
        """
        query = """
            SELECT * FROM moderation_actions
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """
        results = await self.execute(query, (user_id, limit))
        return [ModerationAction.model_validate(r) for r in results]

    async def get_active_timeout(self, user_id: int) -> ModerationAction | None:
        """Get user's active timeout if any.

        Args:
            user_id: Discord user ID.

        Returns:
            Active timeout action if exists, None otherwise.

        Raises:
            psycopg.Error: If query fails.
        """
        query = """
            SELECT * FROM moderation_actions
            WHERE user_id = %s
            AND action_type = 'timeout'
            AND expires_at > NOW()
            ORDER BY expires_at DESC
            LIMIT 1
        """
        result = await self.execute_one(query, (user_id,))
        return ModerationAction.model_validate(result) if result else None

    async def count_user_timeouts(self, user_id: int) -> int:
        """Count total timeouts for a user.

        Args:
            user_id: Discord user ID.

        Returns:
            Number of timeouts received.

        Raises:
            psycopg.Error: If query fails.
        """
        query = """
            SELECT COUNT(*) as count FROM moderation_actions
            WHERE user_id = %s AND action_type = 'timeout'
        """
        result = await self.execute_one(query, (user_id,))
        return int(result["count"]) if result else 0

    # Appeal Operations

    async def create_appeal(self, appeal: Appeal) -> Appeal:
        """Create a new appeal record.

        Args:
            appeal: Appeal object to create.

        Returns:
            Created appeal with database-generated fields populated.

        Raises:
            psycopg.Error: If creation fails.
        """
        query = """
            INSERT INTO appeals (
                action_id, user_id, appeal_text, status
            ) VALUES (
                %(action_id)s, %(user_id)s, %(appeal_text)s, %(status)s
            )
            RETURNING *
        """
        result = await self.execute_one(
            query,
            appeal.model_dump(
                exclude={
                    "id",
                    "review_notes",
                    "reviewed_by",
                    "reviewed_by_name",
                    "reviewed_at",
                    "created_at",
                    "updated_at",
                }
            ),
        )
        assert result is not None
        return Appeal.model_validate(result)

    async def get_pending_appeals(self, limit: int = 50) -> list[Appeal]:
        """Get all pending appeals.

        Args:
            limit: Maximum number of appeals to retrieve.

        Returns:
            List of pending appeals, oldest first.

        Raises:
            psycopg.Error: If query fails.
        """
        query = """
            SELECT * FROM appeals
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT %s
        """
        results = await self.execute(query, (limit,))
        return [Appeal.model_validate(r) for r in results]

    # Brigade Detection Operations

    async def create_brigade_event(self, event: BrigadeEvent) -> BrigadeEvent:
        """Create a new brigade event record.

        Args:
            event: BrigadeEvent object to create.

        Returns:
            Created event with database-generated fields populated.

        Raises:
            psycopg.Error: If creation fails.
        """
        query = """
            INSERT INTO brigade_events (
                participant_count, confidence_score, detection_type, source_hint
            ) VALUES (
                %(participant_count)s, %(confidence_score)s,
                %(detection_type)s, %(source_hint)s
            )
            RETURNING *
        """
        result = await self.execute_one(
            query,
            event.model_dump(
                exclude={
                    "id",
                    "event_uuid",
                    "detected_at",
                    "is_resolved",
                    "resolved_at",
                    "resolution_notes",
                    "created_at",
                }
            ),
        )
        assert result is not None
        return BrigadeEvent.model_validate(result)

    async def add_brigade_participant(
        self, brigade_id: int, user_id: int, participation_score: float
    ) -> None:
        """Add a user to a brigade event.

        Args:
            brigade_id: Brigade event ID.
            user_id: Discord user ID.
            participation_score: Confidence score for participation.

        Raises:
            psycopg.Error: If insertion fails.
        """
        query = """
            INSERT INTO brigade_participants (
                brigade_id, user_id, participation_score
            ) VALUES (%s, %s, %s)
            ON CONFLICT (brigade_id, user_id) DO UPDATE
            SET participation_score = EXCLUDED.participation_score
        """
        await self.execute(query, (brigade_id, user_id, participation_score))

    # Statistics and Analytics

    async def get_daily_stats(self, date: datetime) -> dict[str, Any] | None:
        """Get statistics for a specific date.

        Args:
            date: Date to retrieve stats for.

        Returns:
            Daily statistics dictionary, or None if no data.

        Raises:
            psycopg.Error: If query fails.
        """
        query = "SELECT * FROM daily_stats WHERE date = %s"
        return await self.execute_one(query, (date.date(),))

    async def health_check(self) -> bool:
        """Check database connectivity.

        Returns:
            True if database is accessible, False otherwise.
        """
        try:
            result = await self.execute_one("SELECT 1 as health")
            return result is not None and result.get("health") == 1
        except Exception:
            return False

    async def get_whitelisted_users(self) -> list[User]:
        """Get all whitelisted users."""
        query = "SELECT * FROM users WHERE is_whitelisted = TRUE"
        results = await self.execute(query)
        return [User(**row) for row in results]

    async def set_user_whitelist(self, user_id: int, whitelisted: bool) -> None:
        """Set user whitelist status."""
        query = """
            UPDATE users
            SET is_whitelisted = %s, updated_at = NOW()
            WHERE user_id = %s
        """
        await self.execute(query, (whitelisted, user_id))

    async def clear_user_infractions(self, user_id: int) -> None:
        """Clear all user infractions."""
        query = """
            UPDATE users
            SET warnings = 0, timeouts = 0, kicks = 0, bans = 0, updated_at = NOW()
            WHERE user_id = %s
        """
        await self.execute(query, (user_id,))

    async def get_moderation_stats(self, since: datetime | None = None) -> dict[str, int]:
        """Get moderation statistics."""
        query = """
            SELECT
                action_type,
                COUNT(*) as count
            FROM moderation_actions
            WHERE (%s IS NULL OR created_at >= %s)
            GROUP BY action_type
        """
        results = await self.execute(query, (since, since))
        return {row["action_type"]: row["count"] for row in results}
