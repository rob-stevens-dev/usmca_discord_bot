"""User management commands.

This module provides commands for managing users including whitelisting,
viewing user information, and pardoning actions.
"""

import discord

from usmca_bot.commands.base import BaseCommand, CommandContext, InvalidArgumentError
from usmca_bot.database.models import ModerationAction


class WhitelistCommand(BaseCommand):
    """Manage user whitelist."""

    def __init__(self) -> None:
        """Initialize whitelist command."""
        super().__init__(
            name="whitelist",
            description="Manage whitelisted users",
            usage="!usmca whitelist [add|remove|list] [@user]",
            requires_admin=True,
        )

    async def _execute(self, ctx: CommandContext) -> None:
        """Execute whitelist command.

        Args:
            ctx: Command context.
        """
        if not ctx.args:
            raise InvalidArgumentError("Missing action. Use: add, remove, or list")

        action = ctx.args[0].lower()

        if action == "list":
            await self._list_whitelisted(ctx)
        elif action == "add":
            await self._add_to_whitelist(ctx)
        elif action == "remove":
            await self._remove_from_whitelist(ctx)
        else:
            raise InvalidArgumentError(f"Invalid action '{action}'. Use: add, remove, or list")

    async def _list_whitelisted(self, ctx: CommandContext) -> None:
        """List all whitelisted users.

        Args:
            ctx: Command context.
        """
        # Get whitelisted users from database
        users = await ctx.db.get_whitelisted_users()

        if not users:
            await ctx.reply("No users are currently whitelisted.")
            return

        embed = discord.Embed(
            title="✅ Whitelisted Users",
            description=f"{len(users)} user(s) exempt from moderation",
            color=discord.Color.green(),
        )

        # Group users in chunks for fields (Discord embed limit)
        chunk_size = 10
        for i in range(0, len(users), chunk_size):
            chunk = users[i : i + chunk_size]
            user_list = "\n".join(f"• <@{user.user_id}> ({user.username})" for user in chunk)
            embed.add_field(
                name=f"Users {i + 1}-{min(i + chunk_size, len(users))}",
                value=user_list,
                inline=False,
            )

        await ctx.channel.send(embed=embed)

    async def _add_to_whitelist(self, ctx: CommandContext) -> None:
        """Add user to whitelist.

        Args:
            ctx: Command context.
        """
        if len(ctx.message.mentions) == 0:
            raise InvalidArgumentError("You must mention a user to whitelist")

        target_user = ctx.message.mentions[0]

        # Get or create user in database
        db_user = await ctx.db.get_user(target_user.id)
        if db_user is None:
            # User not in system yet - they'll be created on first message
            await ctx.reply_error(
                f"User {target_user.mention} hasn't sent any messages yet. "
                f"They'll be auto-whitelisted on first message."
            )
            return

        if db_user.is_whitelisted:
            await ctx.reply(f"User {target_user.mention} is already whitelisted.")
            return

        # Update whitelist status
        await ctx.db.set_user_whitelist(target_user.id, True)

        await ctx.reply_success(
            f"Added {target_user.mention} to whitelist. "
            f"They are now exempt from automated moderation."
        )

    async def _remove_from_whitelist(self, ctx: CommandContext) -> None:
        """Remove user from whitelist.

        Args:
            ctx: Command context.
        """
        if len(ctx.message.mentions) == 0:
            raise InvalidArgumentError("You must mention a user to remove")

        target_user = ctx.message.mentions[0]

        # Get user from database
        db_user = await ctx.db.get_user(target_user.id)
        if db_user is None or not db_user.is_whitelisted:
            await ctx.reply(f"User {target_user.mention} is not whitelisted.")
            return

        # Update whitelist status
        await ctx.db.set_user_whitelist(target_user.id, False)

        await ctx.reply_success(
            f"Removed {target_user.mention} from whitelist. "
            f"They are now subject to normal moderation."
        )


class UserInfoCommand(BaseCommand):
    """Display user information and history."""

    def __init__(self) -> None:
        """Initialize user info command."""
        super().__init__(
            name="user",
            description="View user information and moderation history",
            usage="!usmca user [@user]",
            requires_admin=True,
        )

    async def _execute(self, ctx: CommandContext) -> None:
        """Execute user info command.

        Args:
            ctx: Command context.
        """
        if len(ctx.message.mentions) == 0:
            raise InvalidArgumentError("You must mention a user")

        target_user = ctx.message.mentions[0]

        # Get user from database
        db_user = await ctx.db.get_user(target_user.id)
        if db_user is None:
            await ctx.reply(
                f"No data found for {target_user.mention}. They haven't sent any messages yet."
            )
            return

        # Create info embed
        embed = discord.Embed(
            title=f"👤 User Information: {db_user.display_name}",
            color=self._get_risk_color(db_user.risk_level),
        )

        # Basic info
        embed.add_field(
            name="Username",
            value=f"{db_user.username}#{db_user.discriminator}",
            inline=True,
        )
        embed.add_field(
            name="User ID",
            value=f"`{db_user.user_id}`",
            inline=True,
        )
        embed.add_field(
            name="Whitelisted",
            value="✅ Yes" if db_user.is_whitelisted else "❌ No",
            inline=True,
        )

        # Activity stats
        embed.add_field(
            name="Total Messages",
            value=f"`{db_user.total_messages:,}`",
            inline=True,
        )
        embed.add_field(
            name="Avg Toxicity",
            value=f"`{db_user.toxicity_avg:.3f}`",
            inline=True,
        )
        embed.add_field(
            name="Risk Level",
            value=f"`{db_user.risk_level.upper()}`",
            inline=True,
        )

        # Moderation history
        embed.add_field(
            name="⚠️ Warnings",
            value=f"`{db_user.warnings}`",
            inline=True,
        )
        embed.add_field(
            name="🔇 Timeouts",
            value=f"`{db_user.timeouts}`",
            inline=True,
        )
        embed.add_field(
            name="👢 Kicks",
            value=f"`{db_user.kicks}`",
            inline=True,
        )
        embed.add_field(
            name="🔨 Bans",
            value=f"`{db_user.bans}`",
            inline=True,
        )

        # Timestamps
        joined_ts = int(db_user.joined_at.timestamp())
        embed.add_field(
            name="Joined Server",
            value=f"<t:{joined_ts}:R>",
            inline=True,
        )

        if db_user.last_action_at:
            last_action_ts = int(db_user.last_action_at.timestamp())
            embed.add_field(
                name="Last Action",
                value=f"<t:{last_action_ts}:R>",
                inline=True,
            )

        # Notes if any
        if db_user.notes:
            embed.add_field(
                name="📝 Notes",
                value=db_user.notes,
                inline=False,
            )

        embed.set_thumbnail(url=target_user.display_avatar.url)
        embed.set_footer(text=f"Last updated: {db_user.updated_at.strftime('%Y-%m-%d %H:%M UTC')}")

        await ctx.channel.send(embed=embed)

    def _get_risk_color(self, risk_level: str) -> discord.Color:
        """Get embed color based on risk level.

        Args:
            risk_level: User risk level.

        Returns:
            Discord color for the risk level.
        """
        colors = {
            "green": discord.Color.green(),
            "yellow": discord.Color.gold(),
            "orange": discord.Color.orange(),
            "red": discord.Color.red(),
        }
        return colors.get(risk_level, discord.Color.greyple())


class PardonCommand(BaseCommand):
    """Clear user's moderation history."""

    def __init__(self) -> None:
        """Initialize pardon command."""
        super().__init__(
            name="pardon",
            description="Clear a user's moderation history (use with caution)",
            usage="!usmca pardon [@user] [reason]",
            requires_admin=True,
        )

    async def _execute(self, ctx: CommandContext) -> None:
        """Execute pardon command.

        Args:
            ctx: Command context.
        """
        if len(ctx.message.mentions) == 0:
            raise InvalidArgumentError("You must mention a user to pardon")

        target_user = ctx.message.mentions[0]

        # Get reason (everything after the mention)
        reason = " ".join(ctx.args[1:]) if len(ctx.args) > 1 else "No reason provided"

        # Get user from database
        db_user = await ctx.db.get_user(target_user.id)
        if db_user is None:
            await ctx.reply(f"No data found for {target_user.mention}.")
            return

        if db_user.total_infractions == 0:
            await ctx.reply(f"User {target_user.mention} has no infractions to pardon.")
            return

        # Clear infractions
        await ctx.db.clear_user_infractions(target_user.id)

        # Log the pardon as a moderation action
        action = ModerationAction(
            user_id=target_user.id,
            action_type="unban",
            reason=reason,
            is_automated=False,
            moderator_id=ctx.author.id,
            moderator_name=str(ctx.author),
        )
        await ctx.db.create_moderation_action(action)

        await ctx.reply_success(
            f"Pardoned {target_user.mention}.\n"
            f"**Previous infractions:** {db_user.warnings} warnings, "
            f"{db_user.timeouts} timeouts, {db_user.kicks} kicks, {db_user.bans} bans\n"
            f"**Reason:** {reason}\n"
            f"All infractions have been cleared."
        )


class UnbanCommand(BaseCommand):
    """Remove a ban from a user."""

    def __init__(self) -> None:
        """Initialize unban command."""
        super().__init__(
            name="unban",
            description="Remove a ban from a user",
            usage="!usmca unban <user_id> [reason]",
            requires_admin=True,
        )

    async def _execute(self, ctx: CommandContext) -> None:
        """Execute unban command.

        Args:
            ctx: Command context.
        """
        self.require_args(ctx, min_args=1)

        try:
            user_id = int(ctx.args[0])
        except ValueError as e:
            raise InvalidArgumentError(f"Invalid user ID '{ctx.args[0]}'. Must be a number.") from e

        reason = " ".join(ctx.args[1:]) if len(ctx.args) > 1 else "No reason provided"

        # Try to unban via Discord API
        try:
            await ctx.guild.unban(
                discord.Object(id=user_id), reason=f"Unbanned by {ctx.author.name}: {reason}"
            )

            # Log the unban
            action = ModerationAction(
                user_id=user_id,
                action_type="unban",
                reason=reason,
                is_automated=False,
                moderator_id=ctx.author.id,
                moderator_name=str(ctx.author),
            )
            await ctx.db.create_moderation_action(action)

            await ctx.reply_success(f"Unbanned user `{user_id}`.\n" f"**Reason:** {reason}")

        except discord.NotFound:
            await ctx.reply_error(f"User `{user_id}` is not banned.")
        except discord.Forbidden:
            await ctx.reply_error("I don't have permission to unban users.")
        except discord.HTTPException as e:
            await ctx.reply_error(f"Failed to unban user: {e}")
