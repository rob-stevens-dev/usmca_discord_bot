"""Tests for action executor.

This module tests Discord API action execution.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from usmca_bot.actions.decision import ActionDecision
from usmca_bot.actions.executor import ActionExecutor, ActionResult
from usmca_bot.config import Settings
from usmca_bot.database.models import User


@pytest.mark.unit
class TestActionExecutor:
    """Test suite for ActionExecutor class."""

    @pytest.fixture
    def mock_discord_bot(self) -> MagicMock:
        """Create mock Discord bot.

        Returns:
            Mock Discord bot client.
        """
        bot = MagicMock(spec=discord.Client)
        
        # Mock guild
        guild = MagicMock(spec=discord.Guild)
        guild.id = 123456789012345678
        
        # Mock member
        member = MagicMock(spec=discord.Member)
        member.id = 987654321098765432
        member.send = AsyncMock()
        member.timeout = AsyncMock()
        member.kick = AsyncMock()
        member.ban = AsyncMock()
        
        guild.get_member = MagicMock(return_value=member)
        bot.get_guild = MagicMock(return_value=guild)
        
        return bot

    @pytest.fixture
    def executor(
        self,
        test_settings: Settings,
        mock_postgres_client: AsyncMock,
        mock_redis_client: AsyncMock,
        mock_discord_bot: MagicMock,
    ) -> ActionExecutor:
        """Create executor instance for testing.

        Args:
            test_settings: Test settings fixture.
            mock_postgres_client: Mock PostgreSQL client.
            mock_redis_client: Mock Redis client.
            mock_discord_bot: Mock Discord bot.

        Returns:
            ActionExecutor instance.
        """
        return ActionExecutor(
            test_settings,
            mock_postgres_client,
            mock_redis_client,
            mock_discord_bot,
        )

    @pytest.mark.asyncio
    async def test_execute_action_warning_success(
        self,
        executor: ActionExecutor,
        sample_user: User,
        mock_discord_message: MagicMock,
    ) -> None:
        """Test successful warning execution.

        Args:
            executor: ActionExecutor fixture.
            sample_user: Sample user fixture.
            mock_discord_message: Mock Discord message.
        """
        decision = ActionDecision(
            action_type="warning",
            reason="Inappropriate language",
            toxicity_score=0.4,
            behavior_score=0.3,
            context_score=0.2,
            final_score=0.4,
        )

        result = await executor.execute_action(
            decision, sample_user, mock_discord_message
        )

        assert isinstance(result, ActionResult)
        assert result.success is True
        assert result.action_type == "warning"
        assert result.recorded_in_db is True

    @pytest.mark.asyncio
    async def test_execute_action_timeout_success(
        self,
        executor: ActionExecutor,
        sample_user: User,
        mock_discord_message: MagicMock,
        mock_redis_client: AsyncMock,
    ) -> None:
        """Test successful timeout execution.

        Args:
            executor: ActionExecutor fixture.
            sample_user: Sample user fixture.
            mock_discord_message: Mock Discord message.
            mock_redis_client: Mock Redis client.
        """
        decision = ActionDecision(
            action_type="timeout",
            reason="Toxic behavior",
            toxicity_score=0.6,
            behavior_score=0.5,
            context_score=0.2,
            final_score=0.6,
            duration_seconds=3600,
        )

        result = await executor.execute_action(
            decision, sample_user, mock_discord_message
        )

        assert result.success is True
        assert result.action_type == "timeout"
        
        # Verify Redis was updated
        mock_redis_client.set_active_timeout.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_action_kick_success(
        self,
        executor: ActionExecutor,
        sample_user: User,
        mock_discord_message: MagicMock,
    ) -> None:
        """Test successful kick execution.

        Args:
            executor: ActionExecutor fixture.
            sample_user: Sample user fixture.
            mock_discord_message: Mock Discord message.
        """
        decision = ActionDecision(
            action_type="kick",
            reason="Repeated violations",
            toxicity_score=0.8,
            behavior_score=0.7,
            context_score=0.3,
            final_score=0.8,
        )

        result = await executor.execute_action(
            decision, sample_user, mock_discord_message
        )

        assert result.success is True
        assert result.action_type == "kick"

    @pytest.mark.asyncio
    async def test_execute_action_ban_success(
        self,
        executor: ActionExecutor,
        sample_user: User,
        mock_discord_message: MagicMock,
    ) -> None:
        """Test successful ban execution.

        Args:
            executor: ActionExecutor fixture.
            sample_user: Sample user fixture.
            mock_discord_message: Mock Discord message.
        """
        decision = ActionDecision(
            action_type="ban",
            reason="Extreme toxicity",
            toxicity_score=0.95,
            behavior_score=0.9,
            context_score=0.4,
            final_score=0.95,
        )

        result = await executor.execute_action(
            decision, sample_user, mock_discord_message
        )

        assert result.success is True
        assert result.action_type == "ban"

    @pytest.mark.asyncio
    async def test_execute_action_deletes_message(
        self,
        executor: ActionExecutor,
        sample_user: User,
        mock_discord_message: MagicMock,
    ) -> None:
        """Test that message is deleted when requested.

        Args:
            executor: ActionExecutor fixture.
            sample_user: Sample user fixture.
            mock_discord_message: Mock Discord message.
        """
        mock_discord_message.delete = AsyncMock()

        decision = ActionDecision(
            action_type="kick",
            reason="Toxic behavior",
            toxicity_score=0.8,
            behavior_score=0.7,
            context_score=0.3,
            final_score=0.8,
            should_delete_message=True,
        )

        result = await executor.execute_action(
            decision, sample_user, mock_discord_message
        )

        assert result.success is True
        assert result.message_deleted is True
        mock_discord_message.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_action_handles_guild_not_found(
        self,
        executor: ActionExecutor,
        sample_user: User,
        mock_discord_bot: MagicMock,
    ) -> None:
        """Test error handling when guild is not found.

        Args:
            executor: ActionExecutor fixture.
            sample_user: Sample user fixture.
            mock_discord_bot: Mock Discord bot.
        """
        # Mock guild not found
        mock_discord_bot.get_guild = MagicMock(return_value=None)

        decision = ActionDecision(
            action_type="warning",
            reason="Test",
            toxicity_score=0.4,
            behavior_score=0.3,
            context_score=0.2,
            final_score=0.4,
        )

        result = await executor.execute_action(decision, sample_user)

        assert result.success is False
        assert result.error is not None
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_action_handles_member_not_found(
        self,
        executor: ActionExecutor,
        sample_user: User,
        mock_discord_bot: MagicMock,
    ) -> None:
        """Test error handling when member is not found.

        Args:
            executor: ActionExecutor fixture.
            sample_user: Sample user fixture.
            mock_discord_bot: Mock Discord bot.
        """
        # Mock member not found
        guild = mock_discord_bot.get_guild.return_value
        guild.get_member = MagicMock(return_value=None)

        decision = ActionDecision(
            action_type="warning",
            reason="Test",
            toxicity_score=0.4,
            behavior_score=0.3,
            context_score=0.2,
            final_score=0.4,
        )

        result = await executor.execute_action(decision, sample_user)

        assert result.success is False
        assert result.error is not None
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_send_notification_success(
        self,
        executor: ActionExecutor,
        mock_discord_bot: MagicMock,
    ) -> None:
        """Test successful notification sending.

        Args:
            executor: ActionExecutor fixture.
            mock_discord_bot: Mock Discord bot.
        """
        guild = mock_discord_bot.get_guild.return_value
        member = guild.get_member.return_value

        await executor._send_notification(member, "Test message")

        member.send.assert_called_once_with("Test message")

    @pytest.mark.asyncio
    async def test_send_notification_dm_disabled(
        self,
        executor: ActionExecutor,
        mock_discord_bot: MagicMock,
    ) -> None:
        """Test notification when user has DMs disabled.

        Args:
            executor: ActionExecutor fixture.
            mock_discord_bot: Mock Discord bot.
        """
        guild = mock_discord_bot.get_guild.return_value
        member = guild.get_member.return_value
        member.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "Forbidden"))

        # Should not raise exception
        await executor._send_notification(member, "Test message")

    @pytest.mark.asyncio
    async def test_remove_timeout_success(
        self,
        executor: ActionExecutor,
        mock_redis_client: AsyncMock,
    ) -> None:
        """Test successful timeout removal.

        Args:
            executor: ActionExecutor fixture.
            mock_redis_client: Mock Redis client.
        """
        result = await executor.remove_timeout(987654321098765432)

        assert result.success is True
        assert result.action_type == "remove_timeout"
        mock_redis_client.clear_timeout.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_timeout_member_not_found(
        self,
        executor: ActionExecutor,
        mock_discord_bot: MagicMock,
    ) -> None:
        """Test timeout removal when member not found.

        Args:
            executor: ActionExecutor fixture.
            mock_discord_bot: Mock Discord bot.
        """
        guild = mock_discord_bot.get_guild.return_value
        guild.get_member = MagicMock(return_value=None)

        result = await executor.remove_timeout(987654321098765432)

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_record_action_creates_database_entry(
        self,
        executor: ActionExecutor,
        sample_user: User,
        mock_postgres_client: AsyncMock,
    ) -> None:
        """Test that actions are recorded in database.

        Args:
            executor: ActionExecutor fixture.
            sample_user: Sample user fixture.
            mock_postgres_client: Mock PostgreSQL client.
        """
        decision = ActionDecision(
            action_type="warning",
            reason="Test",
            toxicity_score=0.4,
            behavior_score=0.3,
            context_score=0.2,
            final_score=0.4,
        )

        await executor._record_action(decision, sample_user, None)

        mock_postgres_client.create_moderation_action.assert_called_once()
        
        # Verify the action details
        call_args = mock_postgres_client.create_moderation_action.call_args
        action = call_args[0][0]
        
        assert action.user_id == sample_user.user_id
        assert action.action_type == "warning"
        assert action.reason == "Test"
        assert action.is_automated is True
        
        
@pytest.mark.unit
class TestDryRunMode:
    """Test suite for dry run mode."""

    @pytest.fixture
    def dry_run_settings(self, test_settings: Settings) -> Settings:
        """Create settings with dry run enabled.
        
        Args:
            test_settings: Base test settings.
            
        Returns:
            Settings with dry_run_mode=True.
        """
        # Create new settings with dry run enabled
        import copy
        settings = copy.copy(test_settings)
        settings.dry_run_mode = True
        return settings

    @pytest.mark.asyncio
    async def test_dry_run_warning_logs_but_doesnt_execute(
        self,
        dry_run_settings: Settings,
        mock_postgres_client: AsyncMock,
        mock_redis_client: AsyncMock,
        mock_discord_bot: MagicMock,
        mock_discord_user: MagicMock,
        mock_discord_message: MagicMock,
    ) -> None:
        """Test dry run mode logs warning but doesn't execute.
        
        Args:
            dry_run_settings: Settings with dry run enabled.
            mock_postgres_client: Mock PostgreSQL client.
            mock_redis_client: Mock Redis client.
            mock_discord_bot: Mock Discord bot.
            mock_discord_user: Mock Discord user.
            mock_discord_message: Mock Discord message.
        """
        executor = ActionExecutor(
            dry_run_settings,
            mock_postgres_client,
            mock_redis_client,
            mock_discord_bot,
        )

        decision = ActionDecision(
            action_type="warning",
            user_id=123456789,
            reason="Test warning",
            toxicity_score=0.4,
            behavior_score=0.3,
            confidence=0.8,
        )

        result = await executor.execute_action(
            decision, mock_discord_user, mock_discord_message
        )

        # Should report success
        assert result.success is True
        assert result.action_type == "warning"
        
        # Should NOT have actually executed
        assert result.notified_user is False
        assert result.message_deleted is False
        assert result.recorded_in_db is False
        
        # Should indicate dry run
        assert result.details is not None
        assert result.details["dry_run"] is True

        # Should NOT have called Discord API or database
        mock_discord_user.send.assert_not_called()
        mock_discord_message.delete.assert_not_called()
        mock_postgres_client.create_moderation_action.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_timeout_logs_but_doesnt_execute(
        self,
        dry_run_settings: Settings,
        mock_postgres_client: AsyncMock,
        mock_redis_client: AsyncMock,
        mock_discord_bot: MagicMock,
        mock_discord_member: MagicMock,
        mock_discord_message: MagicMock,
    ) -> None:
        """Test dry run mode logs timeout but doesn't execute.
        
        Args:
            dry_run_settings: Settings with dry run enabled.
            mock_postgres_client: Mock PostgreSQL client.
            mock_redis_client: Mock Redis client.
            mock_discord_bot: Mock Discord bot.
            mock_discord_member: Mock Discord member.
            mock_discord_message: Mock Discord message.
        """
        executor = ActionExecutor(
            dry_run_settings,
            mock_postgres_client,
            mock_redis_client,
            mock_discord_bot,
        )

        decision = ActionDecision(
            action_type="timeout",
            user_id=123456789,
            reason="Test timeout",
            toxicity_score=0.6,
            behavior_score=0.5,
            confidence=0.9,
            timeout_duration=3600,
        )

        result = await executor.execute_action(
            decision, mock_discord_member, mock_discord_message
        )

        # Should report success but not actually execute
        assert result.success is True
        assert result.details["dry_run"] is True
        
        # Should NOT have called timeout
        mock_discord_member.timeout.assert_not_called()
        mock_redis_client.set_active_timeout.assert_not_called()

    @pytest.mark.asyncio
    async def test_normal_mode_still_executes(
        self,
        test_settings: Settings,  # Normal settings, dry_run=False
        mock_postgres_client: AsyncMock,
        mock_redis_client: AsyncMock,
        mock_discord_bot: MagicMock,
        mock_discord_user: MagicMock,
        mock_discord_message: MagicMock,
    ) -> None:
        """Test normal mode (dry_run=False) still executes actions.
        
        Args:
            test_settings: Normal test settings.
            mock_postgres_client: Mock PostgreSQL client.
            mock_redis_client: Mock Redis client.
            mock_discord_bot: Mock Discord bot.
            mock_discord_user: Mock Discord user.
            mock_discord_message: Mock Discord message.
        """
        # Ensure dry run is OFF
        assert test_settings.dry_run_mode is False
        
        executor = ActionExecutor(
            test_settings,
            mock_postgres_client,
            mock_redis_client,
            mock_discord_bot,
        )

        decision = ActionDecision(
            action_type="warning",
            user_id=123456789,
            reason="Test warning",
            toxicity_score=0.4,
            behavior_score=0.3,
            confidence=0.8,
        )

        # Mock successful execution
        mock_discord_user.send.return_value = AsyncMock()
        mock_discord_message.delete.return_value = AsyncMock()
        mock_postgres_client.create_moderation_action.return_value = AsyncMock()

        result = await executor.execute_action(
            decision, mock_discord_user, mock_discord_message
        )

        # Should actually execute in normal mode
        assert result.success is True
        
        # Should NOT be dry run
        assert result.details is None or result.details.get("dry_run") is not True
        
        # Should have called Discord API
        mock_discord_user.send.assert_called_once()
        mock_discord_message.delete.assert_called_once()