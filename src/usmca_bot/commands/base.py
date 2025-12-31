"""Base command infrastructure for admin commands.

This module provides the foundation for all admin commands including
authorization, error handling, and audit logging.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import discord
import structlog

from usmca_bot.config import Settings
from usmca_bot.database.postgres import PostgresClient

logger = structlog.get_logger()


class CommandError(Exception):
    """Base exception for command errors."""

    pass


class UnauthorizedError(CommandError):
    """User is not authorized to run this command."""

    pass


class InvalidArgumentError(CommandError):
    """Command received invalid arguments."""

    pass


@dataclass
class CommandContext:
    """Context for command execution.

    Attributes:
        author: Discord member who invoked the command.
        channel: Channel where command was invoked.
        guild: Guild where command was invoked.
        message: Original message containing the command.
        args: Command arguments (split by whitespace).
        settings: Bot settings.
        db: Database client.
    """

    author: discord.Member
    channel: discord.TextChannel
    guild: discord.Guild
    message: discord.Message
    args: list[str]
    settings: Settings
    db: PostgresClient

    def is_owner(self) -> bool:
        """Check if author is the bot owner.

        Returns:
            True if author is the owner.
        """
        return self.author.id == self.settings.bot_owner_id

    def is_admin(self) -> bool:
        """Check if author is an admin or owner.

        Returns:
            True if author is admin or owner.
        """
        return self.is_owner() or self.author.id in self.settings.bot_admin_ids

    async def reply(self, content: str, ephemeral: bool = False) -> None:
        """Send a reply to the command.

        Args:
            content: Message content to send.
            ephemeral: Whether to delete after short delay.
        """
        msg = await self.channel.send(content)
        if ephemeral:
            # Delete after 10 seconds
            await msg.delete(delay=10.0)

    async def reply_error(self, error: str) -> None:
        """Send an error message.

        Args:
            error: Error message to send.
        """
        await self.reply(f"❌ **Error:** {error}", ephemeral=True)

    async def reply_success(self, message: str) -> None:
        """Send a success message.

        Args:
            message: Success message to send.
        """
        await self.reply(f"✅ {message}")


class BaseCommand(ABC):
    """Base class for all admin commands.

    Attributes:
        name: Command name (e.g., 'threshold', 'whitelist').
        description: Human-readable command description.
        usage: Usage string showing syntax.
        requires_owner: Whether command requires owner permission.
        requires_admin: Whether command requires admin permission.
    """

    def __init__(
        self,
        name: str,
        description: str,
        usage: str,
        requires_owner: bool = False,
        requires_admin: bool = True,
    ) -> None:
        """Initialize command.

        Args:
            name: Command name.
            description: Command description.
            usage: Usage syntax.
            requires_owner: If True, only owner can run.
            requires_admin: If True, only admins can run.
        """
        self.name = name
        self.description = description
        self.usage = usage
        self.requires_owner = requires_owner
        self.requires_admin = requires_admin
        self._logger = logger.bind(component=f"command_{name}")

    async def execute(self, ctx: CommandContext) -> None:
        """Execute the command with authorization and error handling.

        Args:
            ctx: Command context.

        Raises:
            UnauthorizedError: If user lacks permission.
            InvalidArgumentError: If arguments are invalid.
            CommandError: For other command errors.
        """
        # Check authorization
        if self.requires_owner and not ctx.is_owner():
            raise UnauthorizedError("This command requires bot owner permission")

        if self.requires_admin and not ctx.is_admin():
            raise UnauthorizedError("This command requires admin permission")

        # Log command execution
        self._logger.info(
            "command_executing",
            command=self.name,
            user_id=ctx.author.id,
            user_name=str(ctx.author),
            args=ctx.args,
        )

        try:
            # Execute the actual command
            await self._execute(ctx)

            # Log success
            await self._audit_log(ctx, success=True, error=None)

        except (UnauthorizedError, InvalidArgumentError, CommandError) as e:
            # Log failure
            await self._audit_log(ctx, success=False, error=str(e))
            raise

        except Exception as e:
            # Unexpected error
            self._logger.error(
                "command_error",
                command=self.name,
                error=str(e),
                exc_info=True,
            )
            await self._audit_log(ctx, success=False, error=f"Unexpected error: {e}")
            raise CommandError(f"Command failed: {e}") from e

    @abstractmethod
    async def _execute(self, ctx: CommandContext) -> None:
        """Execute the command logic.

        Subclasses must implement this method.

        Args:
            ctx: Command context.

        Raises:
            InvalidArgumentError: If arguments are invalid.
            CommandError: For other errors.
        """
        pass

    async def _audit_log(self, ctx: CommandContext, success: bool, error: str | None) -> None:
        """Log command execution to audit trail.

        Args:
            ctx: Command context.
            success: Whether command succeeded.
            error: Error message if failed.
        """
        query = """
            INSERT INTO admin_commands (
                admin_user_id, command, arguments, success, error_message
            ) VALUES (
                $1, $2, $3, $4, $5
            )
        """

        try:
            await ctx.db.execute(
                query,
                (
                    ctx.author.id,
                    self.name,
                    " ".join(ctx.args) if ctx.args else None,
                    success,
                    error,
                ),
            )
        except Exception as e:
            self._logger.error(
                "audit_log_failed",
                command=self.name,
                error=str(e),
            )

    def require_args(self, ctx: CommandContext, min_args: int, max_args: int | None = None) -> None:
        """Validate argument count.

        Args:
            ctx: Command context.
            min_args: Minimum required arguments.
            max_args: Maximum allowed arguments (None = unlimited).

        Raises:
            InvalidArgumentError: If argument count is invalid.
        """
        arg_count = len(ctx.args)

        if arg_count < min_args:
            raise InvalidArgumentError(f"Not enough arguments. Usage: {self.usage}")

        if max_args is not None and arg_count > max_args:
            raise InvalidArgumentError(f"Too many arguments. Usage: {self.usage}")


class CommandRegistry:
    """Registry for managing admin commands.

    Attributes:
        commands: Dictionary of command name -> command instance.
    """

    def __init__(self) -> None:
        """Initialize empty command registry."""
        self.commands: dict[str, BaseCommand] = {}
        self._logger = logger.bind(component="command_registry")

    def register(self, command: BaseCommand) -> None:
        """Register a command.

        Args:
            command: Command instance to register.
        """
        self.commands[command.name] = command
        self._logger.info("command_registered", command=command.name)

    def get(self, name: str) -> BaseCommand | None:
        """Get a command by name.

        Args:
            name: Command name.

        Returns:
            Command instance or None if not found.
        """
        return self.commands.get(name)

    def list_commands(self, user_is_owner: bool, user_is_admin: bool) -> list[str]:
        """List commands available to a user.

        Args:
            user_is_owner: Whether user is the owner.
            user_is_admin: Whether user is an admin.

        Returns:
            List of command names the user can run.
        """
        available = []
        for cmd in self.commands.values():
            if cmd.requires_owner and not user_is_owner:
                continue
            if cmd.requires_admin and not user_is_admin:
                continue
            available.append(cmd.name)

        return sorted(available)
