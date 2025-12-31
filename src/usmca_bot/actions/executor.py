"""Action executor for Discord moderation actions.

This module executes moderation actions via the Discord API,
including timeouts, kicks, bans, and user notifications.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import discord
import structlog

from usmca_bot.actions.decision import ActionDecision
from usmca_bot.config import Settings
from usmca_bot.database.models import ModerationAction, User
from usmca_bot.database.postgres import PostgresClient
from usmca_bot.database.redis import RedisClient

logger = structlog.get_logger()


@dataclass
class ActionResult:
    """Result of executing a moderation action.

    Attributes:
        success: Whether the action was executed successfully.
        action_type: Type of action executed.
        user_id: Discord user ID.
        message_id: Message ID (if applicable).
        error: Error message if action failed.
        notified_user: Whether user was notified via DM.
        message_deleted: Whether message was deleted.
        recorded_in_db: Whether action was recorded in database.
        execution_time_ms: Time taken to execute action.
        details: Additional execution details.
    """

    success: bool
    action_type: str
    user_id: int
    message_id: int | None = None
    error: str | None = None
    notified_user: bool = False
    message_deleted: bool = False
    recorded_in_db: bool = False
    execution_time_ms: float = 0.0
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation.

        Returns:
            Dictionary containing all result data.
        """
        return {
            "success": self.success,
            "action_type": self.action_type,
            "user_id": self.user_id,
            "message_id": self.message_id,
            "error": self.error,
            "notified_user": self.notified_user,
            "message_deleted": self.message_deleted,
            "recorded_in_db": self.recorded_in_db,
            "execution_time_ms": self.execution_time_ms,
            "details": self.details or {},
        }


class ActionExecutor:
    """Executes moderation actions via Discord API.

    This executor handles Discord API calls for moderation actions,
    user notifications, message deletion, and database recording.

    Attributes:
        settings: Application settings.
        db: PostgreSQL database client.
        redis: Redis client.
        bot: Discord bot client.
    """

    def __init__(
        self,
        settings: Settings,
        db: PostgresClient,
        redis: RedisClient,
        bot: discord.Client,
    ) -> None:
        """Initialize action executor.

        Args:
            settings: Application settings.
            db: PostgreSQL database client.
            redis: Redis client.
            bot: Discord bot client.
        """
        self.settings = settings
        self.db = db
        self.redis = redis
        self.bot = bot
        self._logger = logger.bind(component="action_executor")

    async def execute_action(
        self,
        decision: ActionDecision,
        user: User,
        message: discord.Message | None = None,
        notification_message: str | None = None,
    ) -> ActionResult:
        """Execute a moderation action.

        Args:
            decision: Action decision to execute.
            user: User to action.
            message: Discord message that triggered action (optional).
            notification_message: Custom notification message (optional).

        Returns:
            ActionResult indicating execution status.

        Example:
```python
            executor = ActionExecutor(settings, db, redis, bot)
            result = await executor.execute_action(decision, user, message)
            if result.success:
                print(f"Action executed: {result.action_type}")
```
        """
        import time

        start_time = time.perf_counter()

        # CHECK DRY RUN MODE FIRST
        if self.settings.dry_run_mode:
            self._logger.info(
                "dry_run_action",
                action_type=decision.action_type,
                user_id=user.id,
                username=str(user),
                reason=decision.reason,
                toxicity_score=decision.toxicity_score,
                behavior_score=decision.behavior_score,
                confidence=decision.confidence,
                would_delete_message=message is not None,
                would_send_dm=True,
                timeout_duration=decision.timeout_duration if decision.timeout_duration else None,
            )
            
            # Return success without actually doing anything
            execution_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            return ActionResult(
                success=True,
                action_type=decision.action_type,
                user_id=user.id,
                message_id=message.id if message else None,
                notified_user=False,  # Didn't actually send
                message_deleted=False,  # Didn't actually delete  
                recorded_in_db=False,  # Didn't actually record
                execution_time_ms=execution_time,
                details={
                    "dry_run": True,
                    "would_execute": decision.to_dict(),
                },
            )

        self._logger.info(
            "executing_action",
            action_type=decision.action_type,
            user_id=user.user_id,
            message_id=message.id if message else None,
        )

        result = ActionResult(
            success=False,
            action_type=decision.action_type,
            user_id=user.user_id,
            message_id=message.id if message else None,
        )

        try:
            # Get Discord guild and member
            guild = self.bot.get_guild(self.settings.discord_guild_id)
            if guild is None:
                raise RuntimeError(f"Guild {self.settings.discord_guild_id} not found")

            member = guild.get_member(user.user_id)
            if member is None:
                raise RuntimeError(f"Member {user.user_id} not found in guild")

            # Execute the specific action
            if decision.action_type == "warning":
                await self._execute_warning(member, decision, notification_message)
            elif decision.action_type == "timeout":
                await self._execute_timeout(member, decision, notification_message)
            elif decision.action_type == "kick":
                await self._execute_kick(member, decision, notification_message)
            elif decision.action_type == "ban":
                await self._execute_ban(member, decision, notification_message)
            else:
                raise ValueError(f"Unknown action type: {decision.action_type}")

            # Delete message if requested
            if decision.should_delete_message and message is not None:
                try:
                    await message.delete()
                    result.message_deleted = True
                    self._logger.info(
                        "message_deleted",
                        message_id=message.id,
                        user_id=user.user_id,
                    )
                except discord.Forbidden:
                    self._logger.warning(
                        "message_delete_forbidden",
                        message_id=message.id,
                    )
                except Exception as e:
                    self._logger.error(
                        "message_delete_failed",
                        message_id=message.id,
                        error=str(e),
                    )

            # Record action in database
            await self._record_action(decision, user, message)
            result.recorded_in_db = True

            # Mark as success
            result.success = True

            execution_time = (time.perf_counter() - start_time) * 1000
            result.execution_time_ms = execution_time

            self._logger.info(
                "action_executed_successfully",
                action_type=decision.action_type,
                user_id=user.user_id,
                execution_time_ms=execution_time,
            )

        except Exception as e:
            result.error = str(e)
            self._logger.error(
                "action_execution_failed",
                action_type=decision.action_type,
                user_id=user.user_id,
                error=str(e),
            )

        return result

    async def _execute_warning(
        self,
        member: discord.Member,
        decision: ActionDecision,
        notification_message: str | None,
    ) -> None:
        """Execute a warning action.

        Args:
            member: Discord member to warn.
            decision: Action decision.
            notification_message: Optional custom notification.
        """
        # Send DM notification
        if decision.should_notify_user:
            await self._send_notification(member, notification_message or decision.reason)

    async def _execute_timeout(
        self,
        member: discord.Member,
        decision: ActionDecision,
        notification_message: str | None,
    ) -> None:
        """Execute a timeout action.

        Args:
            member: Discord member to timeout.
            decision: Action decision.
            notification_message: Optional custom notification.

        Raises:
            ValueError: If timeout duration is not specified.
        """
        if decision.duration_seconds is None:
            raise ValueError("Timeout duration must be specified")

        # Calculate timeout expiration
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=decision.duration_seconds
        )

        # Apply timeout via Discord API
        await member.timeout(expires_at, reason=decision.reason)

        # Track in Redis for fast lookup
        await self.redis.set_active_timeout(member.id, expires_at)

        # Send DM notification
        if decision.should_notify_user:
            await self._send_notification(member, notification_message or decision.reason)

        self._logger.info(
            "timeout_applied",
            user_id=member.id,
            duration_seconds=decision.duration_seconds,
            expires_at=expires_at,
        )

    async def _execute_kick(
        self,
        member: discord.Member,
        decision: ActionDecision,
        notification_message: str | None,
    ) -> None:
        """Execute a kick action.

        Args:
            member: Discord member to kick.
            decision: Action decision.
            notification_message: Optional custom notification.
        """
        # Send DM notification first (before kick removes access)
        if decision.should_notify_user:
            await self._send_notification(member, notification_message or decision.reason)

        # Kick member
        await member.kick(reason=decision.reason)

        self._logger.info("member_kicked", user_id=member.id)

    async def _execute_ban(
        self,
        member: discord.Member,
        decision: ActionDecision,
        notification_message: str | None,
    ) -> None:
        """Execute a ban action.

        Args:
            member: Discord member to ban.
            decision: Action decision.
            notification_message: Optional custom notification.
        """
        # Send DM notification first (before ban removes access)
        if decision.should_notify_user:
            await self._send_notification(member, notification_message or decision.reason)

        # Ban member (delete messages from last day)
        await member.ban(
            reason=decision.reason,
            delete_message_days=1,
        )

        self._logger.info("member_banned", user_id=member.id)

    async def _send_notification(
        self, member: discord.Member, message: str
    ) -> None:
        """Send DM notification to user.

        Args:
            member: Discord member to notify.
            message: Notification message.
        """
        try:
            await member.send(message)
            self._logger.info("notification_sent", user_id=member.id)
        except discord.Forbidden:
            self._logger.warning(
                "notification_failed_forbidden",
                user_id=member.id,
                reason="User has DMs disabled or blocked bot",
            )
        except Exception as e:
            self._logger.error(
                "notification_failed",
                user_id=member.id,
                error=str(e),
            )

    async def _record_action(
        self,
        decision: ActionDecision,
        user: User,
        message: discord.Message | None,
    ) -> None:
        """Record action in database.

        Args:
            decision: Action decision.
            user: User who was actioned.
            message: Message that triggered action (optional).
        """
        # Calculate expiration for timeouts
        expires_at = None
        if decision.action_type == "timeout" and decision.duration_seconds:
            expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=decision.duration_seconds
            )

        # Create moderation action record
        action = ModerationAction(
            user_id=user.user_id,
            message_id=message.id if message else None,
            action_type=decision.action_type,  # type: ignore
            reason=decision.reason,
            toxicity_score=decision.toxicity_score,
            behavior_score=decision.behavior_score,
            context_score=decision.context_score,
            final_score=decision.final_score,
            is_automated=True,
            expires_at=expires_at,
        )

        await self.db.create_moderation_action(action)

        self._logger.info(
            "action_recorded",
            user_id=user.user_id,
            action_type=decision.action_type,
        )

    async def remove_timeout(self, user_id: int, reason: str = "Timeout expired") -> ActionResult:
        """Remove an active timeout from a user.

        Args:
            user_id: Discord user ID.
            reason: Reason for removal.

        Returns:
            ActionResult indicating removal status.
        """
        self._logger.info("removing_timeout", user_id=user_id)

        result = ActionResult(
            success=False,
            action_type="remove_timeout",
            user_id=user_id,
        )

        try:
            # Get Discord guild and member
            guild = self.bot.get_guild(self.settings.discord_guild_id)
            if guild is None:
                raise RuntimeError(f"Guild {self.settings.discord_guild_id} not found")

            member = guild.get_member(user_id)
            if member is None:
                raise RuntimeError(f"Member {user_id} not found in guild")

            # Remove timeout
            await member.timeout(None, reason=reason)

            # Clear from Redis
            await self.redis.clear_timeout(user_id)

            result.success = True

            self._logger.info("timeout_removed", user_id=user_id)

        except Exception as e:
            result.error = str(e)
            self._logger.error(
                "timeout_removal_failed",
                user_id=user_id,
                error=str(e),
            )

        return result