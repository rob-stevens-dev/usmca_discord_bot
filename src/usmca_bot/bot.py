"""Main Discord bot for USMCA Bot.

This module provides the core Discord bot implementation that orchestrates
all components: classification, behavior analysis, and action execution.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import discord
import structlog
from discord import Member
from discord.ext import tasks

from usmca_bot.actions.decision import DecisionEngine
from usmca_bot.actions.executor import ActionExecutor
from usmca_bot.behavior.analyzer import BehaviorAnalyzer
from usmca_bot.behavior.brigade import BrigadeDetector
from usmca_bot.classification.engine import ClassificationEngine
from usmca_bot.config import Settings
from usmca_bot.database.models import Message
from usmca_bot.database.models import User as DBUser
from usmca_bot.database.postgres import PostgresClient
from usmca_bot.database.redis import RedisClient

logger = structlog.get_logger()


class USMCABot(discord.Client):
    """Main USMCA moderation bot.

    This bot monitors Discord messages, classifies toxicity, analyzes behavior,
    and takes appropriate moderation actions.

    Attributes:
        settings: Application settings.
        db: PostgreSQL database client.
        redis: Redis client.
        classification_engine: ML classification engine.
        behavior_analyzer: Behavior analysis engine.
        brigade_detector: Brigade detection engine.
        decision_engine: Moderation decision engine.
        action_executor: Action execution engine.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize USMCA bot.

        Args:
            settings: Application settings.
        """
        # Initialize Discord client with required intents
        intents = discord.Intents.default()
        intents.message_content = True  # Required to read message content
        intents.members = True  # Required for member events
        intents.guilds = True  # Required for guild events

        super().__init__(intents=intents)

        self.settings = settings
        self._logger = logger.bind(component="bot")

        # Initialize database clients
        self.db = PostgresClient(settings)
        self.redis = RedisClient(settings)

        # Initialize engines
        self.classification_engine = ClassificationEngine(settings)
        self.behavior_analyzer = BehaviorAnalyzer(settings, self.db)
        self.brigade_detector = BrigadeDetector(settings, self.db, self.redis)
        self.decision_engine = DecisionEngine(settings, self.db, self.behavior_analyzer)
        self.action_executor = ActionExecutor(settings, self.db, self.redis, self)

        # Track readiness and in-flight message processing
        self._ready: asyncio.Event = asyncio.Event()
        self._processing_messages = 0

    async def setup_hook(self) -> None:
        """Set up the bot before connecting to Discord.

        This is called automatically by discord.py before the bot starts.
        """
        self._logger.info("bot_setup_starting")

        try:
            # Connect to databases
            await self.db.connect()
            self._logger.info("postgres_connected")

            await self.redis.connect()
            self._logger.info("redis_connected")

            # Warm up ML models
            await self.classification_engine.warmup()
            self._logger.info("classification_engine_ready")

            # Start background tasks
            self.cleanup_task.start()
            self._logger.info("background_tasks_started")

            self._logger.info("bot_setup_complete")

        except Exception as e:
            self._logger.error("bot_setup_failed", error=str(e))
            raise

    async def on_ready(self) -> None:
        """Handle bot ready event.

        Called when the bot has successfully connected to Discord.
        """
        self._ready.set()
        self._logger.info(
            "bot_ready",
            bot_user=str(self.user),
            guilds=len(self.guilds),
            latency=f"{self.latency * 1000:.2f}ms",
        )

    async def on_message(self, message: discord.Message) -> None:
        """Handle new message event.

        Args:
            message: Discord message object.
        """
        # Ignore messages from bots (including self)
        if message.author.bot:
            return

        # Ignore DMs (only moderate in guilds)
        if not message.guild:
            return

        # Only process messages in configured guild
        if message.guild.id != self.settings.discord_guild_id:
            return

        # Check if channel should be monitored
        if not self.settings.should_monitor_channel(message.channel.id):
            self._logger.debug(
                "channel_skipped",
                channel_id=message.channel.id,
                channel_name=getattr(message.channel, "name", "unknown"),
            )
            return

        # Track processing
        self._processing_messages += 1

        try:
            await self._process_message(message)
        except Exception as e:
            self._logger.error(
                "message_processing_error",
                message_id=message.id,
                user_id=message.author.id,
                error=str(e),
            )
        finally:
            self._processing_messages -= 1

    async def _process_message(self, message: discord.Message) -> None:
        """Process a message through the moderation pipeline.

        Args:
            message: Discord message to process.
        """
        # Check for duplicate (Redis)
        is_duplicate = await self.redis.is_duplicate_message(message.id, ttl_seconds=300)
        if is_duplicate:
            self._logger.debug("duplicate_message", message_id=message.id)
            return

        # Check rate limits
        user_allowed, user_count = await self.redis.check_user_rate_limit(
            message.author.id,
            max_messages=self.settings.user_rate_limit_messages,
            window_seconds=self.settings.user_rate_limit_window,
        )

        if not user_allowed:
            self._logger.warning(
                "user_rate_limited",
                user_id=message.author.id,
                message_count=user_count,
            )
            return

        global_allowed, global_count = await self.redis.check_global_rate_limit(
            max_messages=self.settings.global_rate_limit_messages,
            window_seconds=self.settings.global_rate_limit_window,
        )

        if not global_allowed:
            self._logger.warning(
                "global_rate_limited",
                message_count=global_count,
            )
            return

        # Get or create user
        user = await self._get_or_create_user(message.author)

        # Check if user is currently timed out
        is_timed_out = await self.redis.is_user_timed_out(user.user_id)
        if is_timed_out:
            self._logger.debug("user_timed_out", user_id=user.user_id)
            # Still process message for logging, but don't take new action
            return

        # Skip whitelisted users (after logging)
        if user.is_whitelisted:
            self._logger.debug("user_whitelisted", user_id=user.user_id)
            return

        # Classify message toxicity
        classification = await self.classification_engine.classify_message(message.content)

        self._logger.info(
            "message_classified",
            message_id=message.id,
            user_id=user.user_id,
            max_toxicity=classification.toxicity_scores.max_score,
            processing_time_ms=classification.processing_time_ms,
        )

        # Store message in database
        if message.guild is None:
            return  # Skip DMs

        guild_id = message.guild.id

        db_message = Message.from_toxicity_scores(
            message_id=message.id,
            user_id=user.user_id,
            channel_id=message.channel.id,
            guild_id=guild_id,
            content=message.content,
            scores=classification.toxicity_scores,
        )
        await self.db.create_message(db_message)

        # Check for brigade activity
        await self._check_brigade_activity(user, message)

        # If toxicity is below warning threshold, no action needed
        if classification.toxicity_scores.max_score < self.settings.toxicity_warning_threshold:
            return

        # Analyze user behavior
        behavior_score = await self.behavior_analyzer.analyze_user(user)

        self._logger.info(
            "behavior_analyzed",
            user_id=user.user_id,
            final_score=behavior_score.final_score,
            risk_level=behavior_score.risk_level,
        )

        # Make moderation decision
        decision = await self.decision_engine.make_decision(user, classification, behavior_score)

        self._logger.info(
            "decision_made",
            user_id=user.user_id,
            action_type=decision.action_type,
            final_score=decision.final_score,
            confidence=decision.confidence,
            escalated=decision.escalated,
        )

        # Check if we should take action
        should_act = await self.decision_engine.should_take_action(decision, user)
        if not should_act:
            self._logger.info(
                "action_skipped",
                user_id=user.user_id,
                action_type=decision.action_type,
            )
            return

        # Execute action
        notification = await self.decision_engine.get_action_message(decision, user)
        result = await self.action_executor.execute_action(
            decision, message.author, message, notification
        )

        if result.success:
            self._logger.info(
                "action_executed",
                user_id=user.user_id,
                action_type=result.action_type,
                execution_time_ms=result.execution_time_ms,
                message_deleted=result.message_deleted,
                notified_user=result.notified_user,
            )
        else:
            self._logger.error(
                "action_execution_failed",
                user_id=user.user_id,
                action_type=result.action_type,
                error=result.error,
            )

    async def _get_or_create_user(self, member: discord.User | Member) -> DBUser:
        """Get user from database or create if doesn't exist.

        Args:
            member: Discord user or member object.

        Returns:
            User database model.
        """
        # Try to get existing user
        user = await self.db.get_user(member.id)

        if user is not None:
            return user

        # Create new user
        new_user = DBUser(
            user_id=member.id,
            username=member.name,
            discriminator=member.discriminator,
            display_name=member.display_name,
            joined_at=getattr(member, "joined_at", None) or datetime.now(UTC),
        )

        created_user = await self.db.create_user(new_user)

        self._logger.info(
            "user_created",
            user_id=created_user.user_id,
            username=created_user.username,
        )

        return created_user

    async def _check_brigade_activity(self, user: DBUser, message: discord.Message) -> None:
        """Check for brigade activity.

        Args:
            user: User who sent the message.
            message: Discord message object.
        """
        # Run all brigade checks
        results = await self.brigade_detector.comprehensive_check(
            user_id=user.user_id,
            message_content=message.content,
            message_timestamp=message.created_at,
        )

        # Aggregate results
        brigade_result = self.brigade_detector.aggregate_results(results)

        if brigade_result.detected:
            self._logger.warning(
                "brigade_detected",
                detection_type=brigade_result.detection_type,
                confidence=brigade_result.confidence,
                participant_count=brigade_result.participant_count,
            )

            # Record brigade event
            await self.brigade_detector.record_brigade_event(brigade_result)

    async def on_member_join(self, member: Member) -> None:
        """Handle member join event.

        Args:
            member: Discord member who joined.
        """
        # Only track joins in configured guild
        if member.guild.id != self.settings.discord_guild_id:
            return

        # Get or create user
        user = await self._get_or_create_user(member)

        # Check for join spike brigade pattern
        result = await self.brigade_detector.check_join_spike(
            user_id=user.user_id,
            join_timestamp=member.joined_at or datetime.now(UTC),
        )

        if result.detected:
            self._logger.warning(
                "join_spike_detected",
                confidence=result.confidence,
                participant_count=result.participant_count,
            )
            await self.brigade_detector.record_brigade_event(result)

    async def on_member_remove(self, member: Member) -> None:
        """Handle member leave/remove event.

        Args:
            member: Discord member who left.
        """
        # Log member removal
        self._logger.info(
            "member_removed",
            user_id=member.id,
            username=str(member),
        )

    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        """Handle message edit event.

        Args:
            before: Message before edit.
            after: Message after edit.
        """
        # Ignore bot messages
        if after.author.bot:
            return

        # Only reprocess if content actually changed
        if before.content == after.content:
            return

        # Reprocess the edited message
        await self._process_message(after)

    async def on_message_delete(self, message: discord.Message) -> None:
        """Handle message delete event.

        Args:
            message: Deleted message.
        """
        # Mark message as deleted in database
        # (This is a simple implementation - you might want more sophisticated tracking)
        self._logger.debug(
            "message_deleted",
            message_id=message.id,
            user_id=message.author.id,
        )

    async def on_error(self, event: str, *args: Any, **kwargs: Any) -> None:
        """Handle Discord client errors.

        Args:
            event: Event name that caused error.
            args: Positional arguments.
            kwargs: Keyword arguments.
        """
        self._logger.error(
            "discord_event_error",
            event=event,
            args=args,
            kwargs=kwargs,
        )

    @tasks.loop(hours=1)
    async def cleanup_task(self) -> None:
        """Background task to clean up expired data.

        Runs hourly to remove old brigade detection data from Redis.
        """
        try:
            await self.redis.cleanup_expired_data()
            self._logger.info("cleanup_task_completed")
        except Exception as e:
            self._logger.error("cleanup_task_failed", error=str(e))

    @cleanup_task.before_loop
    async def before_cleanup_task(self) -> None:
        """Wait for bot to be ready before starting cleanup task."""
        await self._ready.wait()

    async def health_check(self) -> dict[str, Any]:
        """Check health of all bot components.

        Returns:
            Dictionary with health status of each component.
        """
        health = {
            "bot_ready": self._ready.is_set(),
            "postgres": await self.db.health_check(),
            "redis": await self.redis.health_check(),
            "classification_engine": (await self.classification_engine.health_check()).get("status")
            == "healthy",
            "latency_ms": self.latency * 1000,
            "processing_messages": self._processing_messages,
        }

        return health

    async def close(self) -> None:
        """Close bot and cleanup resources gracefully.

        Waits for in-flight message processing to complete before closing.
        """
        self._logger.info("bot_closing")

        # Wait for in-flight messages to finish processing
        waited: float = 0.0
        while self._processing_messages > 0 and waited < 30:
            self._logger.info(
                "waiting_for_messages",
                processing=self._processing_messages,
            )
            await asyncio.sleep(0.5)
            waited += 0.5

        if self._processing_messages > 0:
            self._logger.warning(
                "force_closing_with_pending_messages",
                processing=self._processing_messages,
            )

        # Stop background tasks
        if self.cleanup_task.is_running():
            self.cleanup_task.cancel()

        # Close database connections
        await self.db.disconnect()
        self._logger.info("postgres_disconnected")

        await self.redis.disconnect()
        self._logger.info("redis_disconnected")

        # Close classification engine
        self.classification_engine.cleanup()
        self._logger.info("classification_engine_cleaned")

        # Close Discord connection
        await super().close()

        self._logger.info("bot_closed")
