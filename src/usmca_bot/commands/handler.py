"""Command handler for dispatching admin commands.

This module provides the main command dispatcher that parses messages,
routes commands, and handles errors.
"""

import discord
import structlog

from usmca_bot.commands.base import (
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
from usmca_bot.database.postgres import PostgresClient

logger = structlog.get_logger()

# Global command registry
command_registry = CommandRegistry()


class CommandHandler:
    """Handles parsing and dispatching of admin commands.

    Attributes:
        settings: Bot settings.
        db: Database client.
        bot: Discord bot client.
        prefix: Command prefix (default: "!usmca").
    """

    def __init__(
        self,
        settings: Settings,
        db: PostgresClient,
        bot: discord.Client,
        prefix: str = "!usmca",
    ) -> None:
        """Initialize command handler.

        Args:
            settings: Bot settings.
            db: Database client.
            bot: Discord bot client.
            prefix: Command prefix.
        """
        self.settings = settings
        self.db = db
        self.bot = bot
        self.prefix = prefix
        self._logger = logger.bind(component="command_handler")

        # Register all commands
        self._register_commands()

    def _register_commands(self) -> None:
        """Register all available commands."""
        # Config commands
        command_registry.register(ThresholdCommand())
        command_registry.register(TimeoutCommand())
        command_registry.register(BrigadeCommand())

        # User commands
        command_registry.register(WhitelistCommand())
        command_registry.register(UserInfoCommand())
        command_registry.register(PardonCommand())
        command_registry.register(UnbanCommand())

        # System commands
        command_registry.register(ModeCommand())
        command_registry.register(StatusCommand())
        command_registry.register(StatsCommand())
        command_registry.register(HelpCommand())

        self._logger.info(
            "commands_registered",
            count=len(command_registry.commands),
            commands=list(command_registry.commands.keys()),
        )

    async def handle(self, message: discord.Message) -> bool:
        """Handle a potential command message.

        Args:
            message: Discord message to check.

        Returns:
            True if message was a command and was handled, False otherwise.
        """
        # Check if message starts with prefix
        if not message.content.startswith(self.prefix):
            return False

        # Ignore bot messages
        if message.author.bot:
            return False

        # Must be in a guild
        if not message.guild:
            await message.channel.send("❌ Commands can only be used in a server, not in DMs.")
            return True

        # Parse command
        parts = message.content[len(self.prefix) :].strip().split()
        if not parts:
            # Just "!usmca" with nothing else - show help
            parts = ["help"]

        command_name = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        # Get command
        command = command_registry.get(command_name)
        if not command:
            await message.channel.send(
                f"❌ Unknown command '{command_name}'. "
                f"Use `{self.prefix} help` to see available commands."
            )
            return True

        # Create context
        ctx = CommandContext(
            author=message.author,  # type: ignore
            channel=message.channel,  # type: ignore
            guild=message.guild,
            message=message,
            args=args,
            settings=self.settings,
            db=self.db,
        )

        # Execute command with error handling
        try:
            await command.execute(ctx)

        except UnauthorizedError as e:
            await ctx.reply_error(str(e))
            self._logger.warning(
                "command_unauthorized",
                user_id=message.author.id,
                command=command_name,
                error=str(e),
            )

        except InvalidArgumentError as e:
            await ctx.reply_error(str(e))
            self._logger.info(
                "command_invalid_args",
                user_id=message.author.id,
                command=command_name,
                error=str(e),
            )

        except CommandError as e:
            await ctx.reply_error(f"Command failed: {e}")
            self._logger.error(
                "command_error",
                user_id=message.author.id,
                command=command_name,
                error=str(e),
            )

        except Exception as e:
            await ctx.reply_error("An unexpected error occurred. Please check logs.")
            self._logger.error(
                "command_unexpected_error",
                user_id=message.author.id,
                command=command_name,
                error=str(e),
                exc_info=True,
            )

        return True

    def get_available_commands(self, user_is_owner: bool, user_is_admin: bool) -> list[str]:
        """Get list of commands available to a user.

        Args:
            user_is_owner: Whether user is the bot owner.
            user_is_admin: Whether user is an admin.

        Returns:
            List of command names the user can run.
        """
        return command_registry.list_commands(user_is_owner, user_is_admin)
