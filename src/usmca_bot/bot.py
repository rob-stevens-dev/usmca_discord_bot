"""Main Discord bot for USMCA Bot.

This module provides the core Discord bot implementation that orchestrates
all components: classification, behavior analysis, and action execution.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any

import discord
import structlog
from discord.ext import tasks

from usmca_bot.actions.decision import DecisionEngine
from usmca_bot.actions.executor import ActionExecutor
from usmca_bot.behavior.analyzer import BehaviorAnalyzer
from usmca_bot.behavior.brigade import BrigadeDetector
from usmca_bot.classification.engine import ClassificationEngine
from usmca_bot.config import Settings
from usmca_bot.database.models import Message, User
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
        self.decision_engine = DecisionEngine(
            settings, self.db, self.behavior_analyzer
        )
        self.action_executor = ActionExecutor(settings, self.db, self.redis, self)

        # Track readiness
        self._ready = False
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
        self._ready = True
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
        self._logger.debug(
            "processing_message",
            message_id=message.id,
            user_id=message.author.id,
            content_length=len(message.content),
        )

        # Check for duplicate processing
        is_duplicate = await self.redis.is_duplicate_message(message.id)
        if is_duplicate:
            self._logger.debug(
                "duplicate_message_skipped",
                message_id=message.id,
            )
            return

        # Rate limiting
        is_allowed, current_count = await self.redis.check_user_rate_limit(
            message.author.id
        )
        if not is_allowed:
            self._logger.warning(
                "user_rate_limited",
                user_id=message.author.id,
                message_count=current_count,
            )
            # Could send warning to user here
            return

        # Global rate limiting
        is_allowed_global, global_count = await self.redis.check_global_rate_limit()
        if not is_allowed_global:
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
            # User is timed out, delete message if they somehow sent one
            try:
                await message.delete()
                self._logger.info(
                    "message_deleted_timeout",
                    user_id=user.user_id,
                    message_id=message.id,
                )
            except discord.Forbidden:
                pass
            return

        # Skip if user is whitelisted
        if user.is_whitelisted:
            self._logger.debug(
                "user_whitelisted",
                user_id=user.user_id,
            )
            return

        # Classify message
        classification = await self.classification_engine.classify_message(
            message.content
        )

        self._logger.info(
            "message_classified",
            message_id=message.id,
            user_id=user.user_id,
            max_toxicity=classification.max_toxicity,
            processing_time_ms=classification.processing_time_ms,
        )

        # Store message in database
        db_message = Message.from_toxicity_scores(
            message_id=message.id,
            user_id=user.user_id,
            channel_id=message.channel.id,
            guild_id=message.guild.id,
            content=message.content,
            scores=classification.toxicity_scores,
            sentiment_score=classification.sentiment_score,
        )
        await self.db.create_message(db_message)

        # Check for brigade activity
        await self._check_brigade_activity(user, message)

        # Only proceed with moderation if toxicity is notable
        if classification.max_toxicity < self.settings.toxicity_warning_threshold:
            return

        # Analyze user behavior
        behavior_score = await self.behavior_analyzer.analyze_user(user)

        self._logger.info(
            "behavior_analyzed",
            user_id=user.user_id,
            behavior_score=behavior_score.final_score,
            risk_level=behavior_score.risk_level,
        )

        # Make moderation decision
        decision = await self.decision_engine.make_decision(
            user, classification, behavior_score
        )

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
            decision, user, message, notification
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

    async def _get_or_create_user(self, discord_user: discord.Member) -> User:
        """Get user from database or create if doesn't exist.

        Args:
            discord_user: Discord member object.

        Returns:
            User database model.
        """
        # Try to get existing user
        user = await self.db.get_user(discord_user.id)

        if user is not None:
            return user

        # Create new user
        new_user = User(
            user_id=discord_user.id,
            username=discord_user.name,
            discriminator=discord_user.discriminator,
            display_name=discord_user.display_name,
            joined_at=discord_user.joined_at or datetime.now(timezone.utc),
        )

        created_user = await self.db.create_user(new_user)

        self._logger.info(
            "user_created",
            user_id=created_user.user_id,
            username=created_user.username,
        )

        return created_user

    async def _check_brigade_activity(
        self, user: User, message: discord.Message
    ) -> None:
        """Check for brigade activity.

        Args:
            user: User who sent the message.
            message: Discord message object.
        """
        # Run comprehensive brigade check
        results = await self.brigade_detector.comprehensive_check(
            user_id=user.user_id,
            message_content=message.content,
            message_timestamp=message.created_at,
        )

        if not results:
            return

        # Aggregate results
        aggregated = self.brigade_detector.aggregate_results(results)

        if aggregated.detected:
            self._logger.warning(
                "brigade_detected",
                detection_type=aggregated.detection_type,
                confidence=aggregated.confidence,
                participant_count=aggregated.participant_count,
            )

            # Record brigade event
            await self.brigade_detector.record_brigade_event(aggregated)

            # Could trigger additional actions here (alert mods, lockdown, etc.)

    async def on_member_join(self, member: discord.Member) -> None:
        """Handle member join event.

        Args:
            member: Discord member who joined.
        """
        # Only process joins in configured guild
        if member.guild.id != self.settings.discord_guild_id:
            return

        self._logger.info(
            "member_joined",
            user_id=member.id,
            username=member.name,
        )

        # Create user record
        await self._get_or_create_user(member)

        # Check for join spike (brigade)
        result = await self.brigade_detector.check_join_spike(
            member.id, member.joined_at or datetime.now(timezone.utc)
        )

        if result.detected:
            self._logger.warning(
                "join_spike_detected",
                confidence=result.confidence,
                participant_count=result.participant_count,
            )

            # Record brigade event
            await self.brigade_detector.record_brigade_event(result)

    async def on_member_remove(self, member: discord.Member) -> None:
        """Handle member removal event.

        Args:
            member: Discord member who left/was removed.
        """
        # Only process removals in configured guild
        if member.guild.id != self.settings.discord_guild_id:
            return

        self._logger.info(
            "member_removed",
            user_id=member.id,
            username=member.name,
        )

    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        """Handle message edit event.

        Args:
            before: Message before edit.
            after: Message after edit.
        """
        # Ignore bot messages
        if after.author.bot:
            return

        # Only process edits in configured guild
        if not after.guild or after.guild.id != self.settings.discord_guild_id:
            return

        # If content didn't change, ignore
        if before.content == after.content:
            return

        self._logger.debug(
            "message_edited",
            message_id=after.id,
            user_id=after.author.id,
        )

        # Treat edited message as a new message
        # (Users shouldn't be able to evade moderation by editing)
        await self._process_message(after)

    async def on_message_delete(self, message: discord.Message) -> None:
        """Handle message deletion event.

        Args:
            message: Deleted message.
        """
        # Only track deletions in configured guild
        if not message.guild or message.guild.id != self.settings.discord_guild_id:
            return

        self._logger.debug(
            "message_deleted",
            message_id=message.id,
            user_id=message.author.id,
        )

        # Could update database to mark message as deleted
        # (Implementation depends on whether you want this tracked)

    async def on_error(self, event: str, *args: Any, **kwargs: Any) -> None:
        """Handle Discord client errors.

        Args:
            event: Event name that caused error.
            args: Positional arguments.
            kwargs: Keyword arguments.
        """
        self._logger.error(
            "discord_error",
            event=event,
            args=args,
            kwargs=kwargs,
        )

    @tasks.loop(hours=1)
    async def cleanup_task(self) -> None:
        """Background task for cleanup operations.

        Runs every hour to clean up expired data.
        """
        try:
            self._logger.debug("cleanup_task_running")

            # Clean up Redis expired data
            await self.redis.cleanup_expired_data()

            self._logger.debug("cleanup_task_complete")

        except Exception as e:
            self._logger.error("cleanup_task_error", error=str(e))

    @cleanup_task.before_loop
    async def before_cleanup_task(self) -> None:
        """Wait until bot is ready before starting cleanup task."""
        await self.wait_until_ready()

    async def close(self) -> None:
        """Close bot and cleanup resources."""
        self._logger.info("bot_shutting_down")

        # Cancel background tasks
        if self.cleanup_task.is_running():
            self.cleanup_task.cancel()

        # Wait for in-flight message processing
        max_wait = 10  # seconds
        waited = 0
        while self._processing_messages > 0 and waited < max_wait:
            self._logger.info(
                "waiting_for_message_processing",
                remaining=self._processing_messages,
            )
            await asyncio.sleep(0.5)
            waited += 0.5

        # Disconnect from databases
        await self.db.disconnect()
        await self.redis.disconnect()

        self._logger.info("bot_shutdown_complete")

        # Call parent close
        await super().close()

    async def health_check(self) -> dict[str, Any]:
        """Perform health check on all components.

        Returns:
            Dictionary with health status of all components.
        """
        health = {
            "bot_ready": self._ready,
            "processing_messages": self._processing_messages,
            "latency_ms": self.latency * 1000 if self._ready else None,
        }

        try:
            # Check database connectivity
            health["postgres"] = await self.db.health_check()
            health["redis"] = await self.redis.health_check()

            # Check classification engine
            engine_health = await self.classification_engine.health_check()
            health["classification_engine"] = engine_health.get("status") == "healthy"

        except Exception as e:
            self._logger.error("health_check_error", error=str(e))
            health["error"] = str(e)

        return health

    def run_bot(self) -> None:
        """Run the bot with token from settings.

        This is a convenience method that calls discord.Client.run().
        """
        self._logger.info("starting_bot")
        self.run(self.settings.discord_token)