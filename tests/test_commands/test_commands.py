"""Complete test suite for admin commands module.

This module provides comprehensive tests for all command infrastructure,
authorization, and command implementations.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from usmca_bot.commands.base import (
    BaseCommand,
    CommandContext,
    CommandError,
    CommandRegistry,
    InvalidArgumentError,
    UnauthorizedError,
)
from usmca_bot.commands.config_commands import (
    BrigadeCommand,
    ThresholdCommand,
    TimeoutCommand,
)
from usmca_bot.commands.handler import CommandHandler
from usmca_bot.commands.system_commands import (
    HelpCommand,
    ModeCommand,
    StatsCommand,
    StatusCommand,
)
from usmca_bot.commands.user_commands import (
    PardonCommand,
    UnbanCommand,
    UserInfoCommand,
    WhitelistCommand,
)
from usmca_bot.config import Settings
from usmca_bot.database.models import User


@pytest.fixture
def mock_discord_channel():
    """Create mock Discord channel."""
    channel = MagicMock()
    channel.send = AsyncMock()
    return channel


@pytest.fixture
def mock_discord_guild():
    """Create mock Discord guild."""
    guild = MagicMock()
    guild.id = 123456789
    guild.name = "Test Guild"
    guild.unban = AsyncMock()
    return guild


@pytest.fixture
def mock_discord_member():
    """Create mock Discord member."""
    member = MagicMock()
    member.id = 999888777666
    member.name = "testadmin"
    member.discriminator = "1234"
    return member


@pytest.fixture
def mock_discord_message(mock_discord_channel, mock_discord_guild, mock_discord_member):
    """Create mock Discord message."""
    message = MagicMock()
    message.author = mock_discord_member
    message.channel = mock_discord_channel
    message.guild = mock_discord_guild
    message.content = "!usmca help"
    message.mentions = []
    return message


@pytest.fixture
def admin_settings(test_settings: Settings):
    """Create settings with admin configured."""
    test_settings.bot_owner_id = 999888777666  # Same as mock_discord_member
    test_settings.bot_admin_ids_str = "111222333444"
    return test_settings


@pytest.fixture
def command_context(
    mock_discord_member,
    mock_discord_channel,
    mock_discord_guild,
    mock_discord_message,
    admin_settings,
    mock_postgres_client,
):
    """Create command context for testing."""
    return CommandContext(
        author=mock_discord_member,
        channel=mock_discord_channel,
        guild=mock_discord_guild,
        message=mock_discord_message,
        args=[],
        settings=admin_settings,
        db=mock_postgres_client,
    )


# ============================================================================
# Test Command Classes
# ============================================================================


class TestCommand(BaseCommand):
    """Test command implementation."""

    def __init__(self, **kwargs):
        super().__init__(
            name="test",
            description="Test command",
            usage="!usmca test",
            **kwargs,
        )

    async def _execute(self, ctx: CommandContext) -> None:
        """Execute test command."""
        await ctx.reply("Test executed")


class OwnerOnlyCommand(BaseCommand):
    """Owner-only test command."""

    def __init__(self):
        super().__init__(
            name="owner_cmd",
            description="Owner only command",
            usage="!usmca owner_cmd",
            requires_owner=True,
        )

    async def _execute(self, ctx: CommandContext) -> None:
        await ctx.reply("Owner command executed")


class AdminOnlyCommand(BaseCommand):
    """Admin-only test command."""

    def __init__(self):
        super().__init__(
            name="admin_cmd",
            description="Admin only command",
            usage="!usmca admin_cmd",
            requires_admin=True,
        )

    async def _execute(self, ctx: CommandContext) -> None:
        await ctx.reply("Admin command executed")


class RegularCommand(BaseCommand):
    """Regular command (no admin required)."""

    def __init__(self):
        super().__init__(
            name="regular",
            description="Regular command",
            usage="!usmca regular",
            requires_admin=False,
        )

    async def _execute(self, ctx: CommandContext) -> None:
        await ctx.reply("Regular command executed")


# ============================================================================
# CommandContext Tests
# ============================================================================


@pytest.mark.unit
class TestCommandContext:
    """Test suite for CommandContext."""

    def test_is_owner_returns_true_for_owner(self, command_context):
        """Test is_owner returns True for owner."""
        assert command_context.is_owner() is True

    def test_is_owner_returns_false_for_non_owner(self, command_context):
        """Test is_owner returns False for non-owner."""
        command_context.settings.bot_owner_id = 12345  # Different ID
        assert command_context.is_owner() is False

    def test_is_admin_returns_true_for_owner(self, command_context):
        """Test is_admin returns True for owner."""
        assert command_context.is_admin() is True

    def test_is_admin_returns_true_for_admin(self, command_context):
        """Test is_admin returns True for admin."""
        command_context.settings.bot_owner_id = 12345  # Not owner
        command_context.author.id = 111222333444  # But is admin
        assert command_context.is_admin() is True

    def test_is_admin_returns_false_for_regular_user(self, command_context):
        """Test is_admin returns False for regular user."""
        command_context.settings.bot_owner_id = 12345
        command_context.author.id = 555666777888  # Not admin
        assert command_context.is_admin() is False

    @pytest.mark.asyncio
    async def test_reply_sends_message(self, command_context, mock_discord_channel):
        """Test reply sends message to channel."""
        await command_context.reply("Test message")
        mock_discord_channel.send.assert_called_once_with("Test message")

    @pytest.mark.asyncio
    async def test_reply_error_sends_formatted_message(
        self, command_context, mock_discord_channel
    ):
        """Test reply_error sends formatted error."""
        await command_context.reply_error("Something went wrong")
        mock_discord_channel.send.assert_called_once()
        call_args = mock_discord_channel.send.call_args[0][0]
        assert "❌" in call_args
        assert "Something went wrong" in call_args

    @pytest.mark.asyncio
    async def test_reply_success_sends_formatted_message(
        self, command_context, mock_discord_channel
    ):
        """Test reply_success sends formatted success."""
        await command_context.reply_success("Operation completed")
        mock_discord_channel.send.assert_called_once()
        call_args = mock_discord_channel.send.call_args[0][0]
        assert "✅" in call_args
        assert "Operation completed" in call_args


# ============================================================================
# BaseCommand Tests
# ============================================================================


@pytest.mark.unit
class TestBaseCommand:
    """Test suite for BaseCommand."""

    @pytest.mark.asyncio
    async def test_execute_checks_owner_permission(self, command_context):
        """Test execute checks owner permission."""
        cmd = TestCommand(requires_owner=True)
        command_context.settings.bot_owner_id = 12345  # Not owner

        with pytest.raises(UnauthorizedError) as exc_info:
            await cmd.execute(command_context)

        assert "owner" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_execute_checks_admin_permission(self, command_context):
        """Test execute checks admin permission."""
        cmd = TestCommand(requires_admin=True)
        command_context.settings.bot_owner_id = 12345
        command_context.author.id = 555666777888  # Not admin

        with pytest.raises(UnauthorizedError) as exc_info:
            await cmd.execute(command_context)

        assert "admin" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_execute_allows_authorized_user(self, command_context):
        """Test execute allows authorized user."""
        cmd = TestCommand(requires_admin=True)
        # command_context is already configured as owner
        await cmd.execute(command_context)  # Should not raise

    @pytest.mark.asyncio
    async def test_execute_logs_command(self, command_context, mock_postgres_client):
        """Test execute logs command to audit trail."""
        cmd = TestCommand()
        mock_postgres_client.execute = AsyncMock()

        await cmd.execute(command_context)

        # Should have called execute for audit log
        assert mock_postgres_client.execute.called

    @pytest.mark.asyncio
    async def test_execute_logs_errors(self, command_context, mock_postgres_client):
        """Test execute logs errors to audit trail."""

        class FailingCommand(BaseCommand):
            def __init__(self):
                super().__init__(
                    name="failing",
                    description="Test",
                    usage="test",
                    requires_admin=False,
                )

            async def _execute(self, ctx: CommandContext) -> None:
                raise CommandError("Test error")

        cmd = FailingCommand()
        mock_postgres_client.execute = AsyncMock()

        with pytest.raises(CommandError):
            await cmd.execute(command_context)

        assert mock_postgres_client.execute.called

    def test_require_args_passes_with_valid_count(self, command_context):
        """Test require_args passes with valid argument count."""
        cmd = TestCommand()
        command_context.args = ["arg1", "arg2"]

        # Should not raise
        cmd.require_args(command_context, min_args=2, max_args=2)

    def test_require_args_raises_on_too_few(self, command_context):
        """Test require_args raises on too few arguments."""
        cmd = TestCommand()
        command_context.args = ["arg1"]

        with pytest.raises(InvalidArgumentError) as exc_info:
            cmd.require_args(command_context, min_args=2)

        assert "not enough" in str(exc_info.value).lower()

    def test_require_args_raises_on_too_many(self, command_context):
        """Test require_args raises on too many arguments."""
        cmd = TestCommand()
        command_context.args = ["arg1", "arg2", "arg3"]

        with pytest.raises(InvalidArgumentError) as exc_info:
            cmd.require_args(command_context, min_args=1, max_args=2)

        assert "too many" in str(exc_info.value).lower()


# ============================================================================
# CommandRegistry Tests
# ============================================================================


@pytest.mark.unit
class TestCommandRegistry:
    """Test suite for CommandRegistry."""

    def test_register_adds_command(self):
        """Test register adds command to registry."""
        registry = CommandRegistry()
        cmd = TestCommand()

        registry.register(cmd)

        assert "test" in registry.commands
        assert registry.commands["test"] == cmd

    def test_get_returns_command(self):
        """Test get returns registered command."""
        registry = CommandRegistry()
        cmd = TestCommand()
        registry.register(cmd)

        result = registry.get("test")

        assert result == cmd

    def test_get_returns_none_for_unknown(self):
        """Test get returns None for unknown command."""
        registry = CommandRegistry()

        result = registry.get("unknown")

        assert result is None

    def test_list_commands_returns_all_for_owner(self):
        """Test list_commands returns all commands for owner."""
        registry = CommandRegistry()
        registry.register(TestCommand())
        registry.register(OwnerOnlyCommand())

        result = registry.list_commands(user_is_owner=True, user_is_admin=True)

        assert "test" in result
        assert "owner_cmd" in result

    def test_list_commands_excludes_owner_only(self):
        """Test list_commands excludes owner-only for non-owner."""
        registry = CommandRegistry()
        registry.register(TestCommand())
        registry.register(OwnerOnlyCommand())

        result = registry.list_commands(user_is_owner=False, user_is_admin=True)

        assert "test" in result
        assert "owner_cmd" not in result

    def test_list_commands_excludes_admin_only(self):
        """Test list_commands excludes admin-only for regular user."""
        registry = CommandRegistry()
        registry.register(RegularCommand())
        registry.register(AdminOnlyCommand())

        result = registry.list_commands(user_is_owner=False, user_is_admin=False)

        assert "regular" in result
        assert "admin_cmd" not in result


# ============================================================================
# ThresholdCommand Tests
# ============================================================================


@pytest.mark.unit
class TestThresholdCommand:
    """Test suite for ThresholdCommand."""

    @pytest.mark.asyncio
    async def test_show_thresholds(self, command_context, mock_discord_channel):
        """Test threshold show displays current values."""
        cmd = ThresholdCommand()

        await cmd._execute(command_context)

        # Should send embed with threshold values
        mock_discord_channel.send.assert_called_once()
        call_args = mock_discord_channel.send.call_args
        assert "embed" in call_args[1] or isinstance(call_args[0][0], discord.Embed)

    @pytest.mark.asyncio
    async def test_set_threshold_updates_value(self, command_context):
        """Test threshold set updates setting."""
        cmd = ThresholdCommand()
        command_context.args = ["warning", "0.40"]

        old_value = command_context.settings.toxicity_warning_threshold
        await cmd._execute(command_context)

        assert command_context.settings.toxicity_warning_threshold == 0.40
        assert command_context.settings.toxicity_warning_threshold != old_value

    @pytest.mark.asyncio
    async def test_set_threshold_validates_range(self, command_context):
        """Test threshold set validates value range."""
        cmd = ThresholdCommand()
        command_context.args = ["warning", "1.5"]  # Out of range

        with pytest.raises(InvalidArgumentError):
            await cmd._execute(command_context)

    @pytest.mark.asyncio
    async def test_set_threshold_validates_type(self, command_context):
        """Test threshold set validates threshold type."""
        cmd = ThresholdCommand()
        command_context.args = ["invalid", "0.5"]

        with pytest.raises(InvalidArgumentError):
            await cmd._execute(command_context)


# ============================================================================
# TimeoutCommand Tests
# ============================================================================


@pytest.mark.unit
class TestTimeoutCommand:
    """Test suite for TimeoutCommand."""

    @pytest.mark.asyncio
    async def test_show_timeouts(self, command_context, mock_discord_channel):
        """Test timeout show displays current values."""
        cmd = TimeoutCommand()

        await cmd._execute(command_context)

        # Should send embed with timeout values
        mock_discord_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_timeout_updates_value(self, command_context):
        """Test timeout set updates setting."""
        cmd = TimeoutCommand()
        command_context.args = ["first", "7200"]  # 2 hours

        old_value = command_context.settings.timeout_first
        await cmd._execute(command_context)

        assert command_context.settings.timeout_first == 7200
        assert command_context.settings.timeout_first != old_value

    @pytest.mark.asyncio
    async def test_set_timeout_validates_range(self, command_context):
        """Test timeout set validates value range."""
        cmd = TimeoutCommand()
        command_context.args = ["first", "30"]  # Too short (< 60)

        with pytest.raises(InvalidArgumentError):
            await cmd._execute(command_context)


# ============================================================================
# BrigadeCommand Tests
# ============================================================================


@pytest.mark.unit
class TestBrigadeCommand:
    """Test suite for BrigadeCommand."""

    @pytest.mark.asyncio
    async def test_show_settings(self, command_context, mock_discord_channel):
        """Test brigade show displays current settings."""
        cmd = BrigadeCommand()

        await cmd._execute(command_context)

        # Should send embed with brigade settings
        mock_discord_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_joins_threshold(self, command_context):
        """Test brigade joins updates setting."""
        cmd = BrigadeCommand()
        command_context.args = ["joins", "15"]

        old_value = command_context.settings.brigade_joins_per_minute
        await cmd._execute(command_context)

        assert command_context.settings.brigade_joins_per_minute == 15
        assert command_context.settings.brigade_joins_per_minute != old_value

    @pytest.mark.asyncio
    async def test_set_messages_threshold(self, command_context):
        """Test brigade messages updates setting."""
        cmd = BrigadeCommand()
        command_context.args = ["messages", "8"]

        old_value = command_context.settings.brigade_similar_messages
        await cmd._execute(command_context)

        assert command_context.settings.brigade_similar_messages == 8


# ============================================================================
# ModeCommand Tests
# ============================================================================


@pytest.mark.unit
class TestModeCommand:
    """Test suite for ModeCommand."""

    @pytest.mark.asyncio
    async def test_show_mode_displays_current(
        self, command_context, mock_discord_channel
    ):
        """Test mode show displays current mode."""
        cmd = ModeCommand()

        await cmd._execute(command_context)

        mock_discord_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_mode_dry_run(self, command_context):
        """Test mode dry-run enables dry run mode."""
        cmd = ModeCommand()
        command_context.args = ["dry-run"]
        command_context.settings.dry_run_mode = False

        await cmd._execute(command_context)

        assert command_context.settings.dry_run_mode is True

    @pytest.mark.asyncio
    async def test_set_mode_live(self, command_context):
        """Test mode live disables dry run mode."""
        cmd = ModeCommand()
        command_context.args = ["live"]
        command_context.settings.dry_run_mode = True

        await cmd._execute(command_context)

        assert command_context.settings.dry_run_mode is False

    @pytest.mark.asyncio
    async def test_set_mode_invalid_raises_error(self, command_context):
        """Test invalid mode raises error."""
        cmd = ModeCommand()
        command_context.args = ["invalid"]

        with pytest.raises(InvalidArgumentError):
            await cmd._execute(command_context)


# ============================================================================
# StatusCommand Tests
# ============================================================================


@pytest.mark.unit
class TestStatusCommand:
    """Test suite for StatusCommand."""

    @pytest.mark.asyncio
    async def test_status_displays_configuration(
        self, command_context, mock_discord_channel
    ):
        """Test status displays bot configuration."""
        cmd = StatusCommand()

        await cmd._execute(command_context)

        mock_discord_channel.send.assert_called_once()
        call_args = mock_discord_channel.send.call_args
        # Should send embed
        assert "embed" in call_args[1] or isinstance(call_args[0][0], discord.Embed)


# ============================================================================
# StatsCommand Tests
# ============================================================================


@pytest.mark.unit
class TestStatsCommand:
    """Test suite for StatsCommand."""

    @pytest.mark.asyncio
    async def test_stats_today(
        self, command_context, mock_postgres_client, mock_discord_channel
    ):
        """Test stats today displays statistics."""
        cmd = StatsCommand()
        command_context.args = ["today"]

        # Mock database response
        mock_postgres_client.get_moderation_stats = AsyncMock(
            return_value={
                "warnings": 5,
                "timeouts": 2,
                "kicks": 1,
                "bans": 0,
                "total_messages": 100,
                "flagged_messages": 8,
                "avg_toxicity": 0.25,
                "total_users": 50,
                "whitelisted": 3,
                "at_risk": 2,
            }
        )

        await cmd._execute(command_context)

        mock_postgres_client.get_moderation_stats.assert_called_once()
        mock_discord_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_stats_week(
        self, command_context, mock_postgres_client, mock_discord_channel
    ):
        """Test stats week displays statistics."""
        cmd = StatsCommand()
        command_context.args = ["week"]

        mock_postgres_client.get_moderation_stats = AsyncMock(
            return_value={
                "warnings": 25,
                "timeouts": 10,
                "kicks": 3,
                "bans": 1,
                "total_messages": 500,
                "flagged_messages": 35,
                "avg_toxicity": 0.22,
                "total_users": 75,
                "whitelisted": 5,
                "at_risk": 8,
            }
        )

        await cmd._execute(command_context)

        mock_postgres_client.get_moderation_stats.assert_called_once()
        mock_discord_channel.send.assert_called_once()


# ============================================================================
# WhitelistCommand Tests
# ============================================================================


@pytest.mark.unit
class TestWhitelistCommand:
    """Test suite for WhitelistCommand."""

    @pytest.mark.asyncio
    async def test_list_whitelisted_users(
        self, command_context, mock_postgres_client, mock_discord_channel
    ):
        """Test whitelist list shows whitelisted users."""
        cmd = WhitelistCommand()
        command_context.args = ["list"]

        # Mock database response
        mock_user = User(
            user_id=123456,
            username="testuser",
            discriminator="1234",
            display_name="Test User",
            joined_at=datetime.now(timezone.utc),
        )
        mock_postgres_client.get_whitelisted_users = AsyncMock(return_value=[mock_user])

        await cmd._execute(command_context)

        mock_postgres_client.get_whitelisted_users.assert_called_once()
        mock_discord_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_to_whitelist(
        self, command_context, mock_postgres_client, mock_discord_channel
    ):
        """Test whitelist add adds user."""
        cmd = WhitelistCommand()
        command_context.args = ["add"]

        # Mock mentioned user
        mentioned_user = MagicMock()
        mentioned_user.id = 987654
        mentioned_user.mention = "<@987654>"
        command_context.message.mentions = [mentioned_user]

        # Mock database user
        mock_user = User(
            user_id=987654,
            username="targetuser",
            discriminator="5678",
            display_name="Target User",
            joined_at=datetime.now(timezone.utc),
            is_whitelisted=False,
        )
        mock_postgres_client.get_user = AsyncMock(return_value=mock_user)
        mock_postgres_client.set_user_whitelist = AsyncMock()

        await cmd._execute(command_context)

        mock_postgres_client.set_user_whitelist.assert_called_once_with(987654, True)

    @pytest.mark.asyncio
    async def test_add_requires_mention(self, command_context):
        """Test whitelist add requires user mention."""
        cmd = WhitelistCommand()
        command_context.args = ["add"]
        command_context.message.mentions = []  # No mentions

        with pytest.raises(InvalidArgumentError):
            await cmd._execute(command_context)

    @pytest.mark.asyncio
    async def test_remove_from_whitelist(
        self, command_context, mock_postgres_client, mock_discord_channel
    ):
        """Test whitelist remove removes user."""
        cmd = WhitelistCommand()
        command_context.args = ["remove"]

        # Mock mentioned user
        mentioned_user = MagicMock()
        mentioned_user.id = 987654
        mentioned_user.mention = "<@987654>"
        command_context.message.mentions = [mentioned_user]

        # Mock database user (currently whitelisted)
        mock_user = User(
            user_id=987654,
            username="targetuser",
            discriminator="5678",
            display_name="Target User",
            joined_at=datetime.now(timezone.utc),
            is_whitelisted=True,
        )
        mock_postgres_client.get_user = AsyncMock(return_value=mock_user)
        mock_postgres_client.set_user_whitelist = AsyncMock()

        await cmd._execute(command_context)

        mock_postgres_client.set_user_whitelist.assert_called_once_with(987654, False)


# ============================================================================
# UserInfoCommand Tests
# ============================================================================


@pytest.mark.unit
class TestUserInfoCommand:
    """Test suite for UserInfoCommand."""

    @pytest.mark.asyncio
    async def test_show_user_info(
        self, command_context, mock_postgres_client, mock_discord_channel
    ):
        """Test user info displays user information."""
        cmd = UserInfoCommand()

        # Mock mentioned user
        mentioned_user = MagicMock()
        mentioned_user.id = 123456
        mentioned_user.mention = "<@123456>"
        mentioned_user.display_avatar.url = "https://example.com/avatar.png"
        command_context.message.mentions = [mentioned_user]

        # Mock database user
        mock_user = User(
            user_id=123456,
            username="testuser",
            discriminator="1234",
            display_name="Test User",
            joined_at=datetime.now(timezone.utc),
            total_messages=150,
            toxicity_avg=0.25,
            warnings=2,
            timeouts=1,
            kicks=0,
            bans=0,
            risk_level="yellow",
        )
        mock_postgres_client.get_user = AsyncMock(return_value=mock_user)

        await cmd._execute(command_context)

        mock_postgres_client.get_user.assert_called_once_with(123456)
        mock_discord_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_user_not_found(
        self, command_context, mock_postgres_client, mock_discord_channel
    ):
        """Test user info handles user not found."""
        cmd = UserInfoCommand()

        # Mock mentioned user
        mentioned_user = MagicMock()
        mentioned_user.id = 123456
        mentioned_user.mention = "<@123456>"
        command_context.message.mentions = [mentioned_user]

        # User not in database
        mock_postgres_client.get_user = AsyncMock(return_value=None)

        await cmd._execute(command_context)

        mock_discord_channel.send.assert_called_once()


# ============================================================================
# PardonCommand Tests
# ============================================================================


@pytest.mark.unit
class TestPardonCommand:
    """Test suite for PardonCommand."""

    @pytest.mark.asyncio
    async def test_pardon_user(
        self, command_context, mock_postgres_client, mock_discord_channel
    ):
        """Test pardon clears user infractions."""
        cmd = PardonCommand()
        command_context.args = ["reason for pardon"]

        # Mock mentioned user
        mentioned_user = MagicMock()
        mentioned_user.id = 123456
        mentioned_user.mention = "<@123456>"
        command_context.message.mentions = [mentioned_user]

        # Mock database user with infractions
        mock_user = User(
            user_id=123456,
            username="testuser",
            discriminator="1234",
            display_name="Test User",
            joined_at=datetime.now(timezone.utc),
            warnings=2,
            timeouts=1,
            kicks=0,
            bans=0,
        )
        mock_postgres_client.get_user = AsyncMock(return_value=mock_user)
        mock_postgres_client.clear_user_infractions = AsyncMock()
        mock_postgres_client.create_moderation_action = AsyncMock()

        await cmd._execute(command_context)

        mock_postgres_client.clear_user_infractions.assert_called_once_with(123456)
        mock_postgres_client.create_moderation_action.assert_called_once()

    @pytest.mark.asyncio
    async def test_pardon_no_infractions(
        self, command_context, mock_postgres_client, mock_discord_channel
    ):
        """Test pardon handles user with no infractions."""
        cmd = PardonCommand()
        command_context.args = []

        # Mock mentioned user
        mentioned_user = MagicMock()
        mentioned_user.id = 123456
        mentioned_user.mention = "<@123456>"
        command_context.message.mentions = [mentioned_user]

        # Mock database user with no infractions
        mock_user = User(
            user_id=123456,
            username="testuser",
            discriminator="1234",
            display_name="Test User",
            joined_at=datetime.now(timezone.utc),
            warnings=0,
            timeouts=0,
            kicks=0,
            bans=0,
        )
        mock_postgres_client.get_user = AsyncMock(return_value=mock_user)

        await cmd._execute(command_context)

        mock_discord_channel.send.assert_called_once()
        # Should not clear infractions if there are none
        assert not mock_postgres_client.clear_user_infractions.called


# ============================================================================
# UnbanCommand Tests
# ============================================================================


@pytest.mark.unit
class TestUnbanCommand:
    """Test suite for UnbanCommand."""

    @pytest.mark.asyncio
    async def test_unban_success(
        self, command_context, mock_postgres_client, mock_discord_channel, mock_discord_guild
    ):
        """Test unban removes ban successfully."""
        cmd = UnbanCommand()
        command_context.args = ["123456", "unban reason"]

        mock_discord_guild.unban = AsyncMock()
        mock_postgres_client.create_moderation_action = AsyncMock()

        await cmd._execute(command_context)

        mock_discord_guild.unban.assert_called_once()
        mock_postgres_client.create_moderation_action.assert_called_once()

    @pytest.mark.asyncio
    async def test_unban_not_found(
        self, command_context, mock_discord_channel, mock_discord_guild
    ):
        """Test unban handles user not banned."""
        cmd = UnbanCommand()
        command_context.args = ["123456"]

        mock_discord_guild.unban = AsyncMock(side_effect=discord.NotFound(MagicMock(), ""))

        await cmd._execute(command_context)

        mock_discord_channel.send.assert_called_once()
        call_args = str(mock_discord_channel.send.call_args)
        assert "not banned" in call_args.lower()

    @pytest.mark.asyncio
    async def test_unban_forbidden(
        self, command_context, mock_discord_channel, mock_discord_guild
    ):
        """Test unban handles permission error."""
        cmd = UnbanCommand()
        command_context.args = ["123456"]

        mock_discord_guild.unban = AsyncMock(side_effect=discord.Forbidden(MagicMock(), ""))

        await cmd._execute(command_context)

        mock_discord_channel.send.assert_called_once()
        call_args = str(mock_discord_channel.send.call_args)
        assert "permission" in call_args.lower()


# ============================================================================
# HelpCommand Tests
# ============================================================================


@pytest.mark.unit
class TestHelpCommand:
    """Test suite for HelpCommand."""

    @pytest.mark.asyncio
    async def test_help_shows_all_commands(
        self, command_context, mock_discord_channel
    ):
        """Test help shows all available commands."""
        cmd = HelpCommand()

        await cmd._execute(command_context)

        mock_discord_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_help_shows_specific_command(
        self, command_context, mock_discord_channel
    ):
        """Test help shows details for specific command."""
        cmd = HelpCommand()
        command_context.args = ["threshold"]

        await cmd._execute(command_context)

        mock_discord_channel.send.assert_called_once()


# ============================================================================
# CommandHandler Tests
# ============================================================================


@pytest.mark.unit
class TestCommandHandler:
    """Test suite for CommandHandler."""

    @pytest.mark.asyncio
    async def test_handle_ignores_non_command_messages(
        self, mock_discord_message, admin_settings, mock_postgres_client
    ):
        """Test handler ignores messages without prefix."""
        handler = CommandHandler(admin_settings, mock_postgres_client, MagicMock())
        mock_discord_message.content = "Just a regular message"

        result = await handler.handle(mock_discord_message)

        assert result is False

    @pytest.mark.asyncio
    async def test_handle_ignores_bot_messages(
        self, mock_discord_message, admin_settings, mock_postgres_client
    ):
        """Test handler ignores bot messages."""
        handler = CommandHandler(admin_settings, mock_postgres_client, MagicMock())
        mock_discord_message.author.bot = True
        mock_discord_message.content = "!usmca help"

        result = await handler.handle(mock_discord_message)

        assert result is False

    @pytest.mark.asyncio
    async def test_handle_processes_valid_command(
        self, mock_discord_message, admin_settings, mock_postgres_client
    ):
        """Test handler processes valid command."""
        handler = CommandHandler(admin_settings, mock_postgres_client, MagicMock())
        mock_discord_message.content = "!usmca help"
        mock_discord_message.author.bot = False

        result = await handler.handle(mock_discord_message)

        assert result is True

    @pytest.mark.asyncio
    async def test_handle_reports_unknown_command(
        self, mock_discord_message, admin_settings, mock_postgres_client
    ):
        """Test handler reports unknown command."""
        handler = CommandHandler(admin_settings, mock_postgres_client, MagicMock())
        mock_discord_message.content = "!usmca unknown"
        mock_discord_message.author.bot = False

        result = await handler.handle(mock_discord_message)

        assert result is True
        mock_discord_message.channel.send.assert_called_once()
        call_args = str(mock_discord_message.channel.send.call_args)
        assert "unknown" in call_args.lower()

    @pytest.mark.asyncio
    async def test_handle_catches_unauthorized_error(
        self, mock_discord_message, admin_settings, mock_postgres_client
    ):
        """Test handler catches UnauthorizedError."""
        handler = CommandHandler(admin_settings, mock_postgres_client, MagicMock())
        mock_discord_message.content = "!usmca threshold show"
        mock_discord_message.author.bot = False
        mock_discord_message.author.id = 999999  # Not authorized

        result = await handler.handle(mock_discord_message)

        assert result is True
        # Should have sent error message
        assert mock_discord_message.channel.send.called

    def test_get_available_commands_for_owner(
        self, admin_settings, mock_postgres_client
    ):
        """Test get_available_commands returns all for owner."""
        handler = CommandHandler(admin_settings, mock_postgres_client, MagicMock())

        commands = handler.get_available_commands(
            user_is_owner=True, user_is_admin=True
        )

        # Should include admin commands
        assert "threshold" in commands
        assert "mode" in commands
        assert "whitelist" in commands


# ============================================================================
# Integration Test
# ============================================================================


@pytest.mark.integration
class TestCommandsIntegration:
    """Integration tests for command system."""

    @pytest.mark.asyncio
    async def test_full_command_flow(
        self, mock_discord_message, admin_settings, mock_postgres_client
    ):
        """Test complete command execution flow."""
        # Setup
        handler = CommandHandler(admin_settings, mock_postgres_client, MagicMock())
        mock_discord_message.content = "!usmca mode dry-run"
        mock_discord_message.author.bot = False
        mock_discord_message.author.id = admin_settings.bot_owner_id  # Is owner
        mock_postgres_client.execute = AsyncMock()

        # Execute
        result = await handler.handle(mock_discord_message)

        # Verify
        assert result is True
        assert admin_settings.dry_run_mode is True
        mock_discord_message.channel.send.assert_called()
        # Should have logged to audit trail
        assert mock_postgres_client.execute.called