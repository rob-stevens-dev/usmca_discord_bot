"""System management commands.

This module provides commands for system control including dry run mode,
status checks, statistics, and help.
"""

from datetime import UTC, datetime, timedelta

import discord

from usmca_bot.commands.base import BaseCommand, CommandContext, InvalidArgumentError


class ModeCommand(BaseCommand):
    """Control dry run mode."""

    def __init__(self) -> None:
        """Initialize mode command."""
        super().__init__(
            name="mode",
            description="Switch between dry-run and live mode",
            usage="!usmca mode [dry-run|live|show]",
            requires_admin=True,
        )

    async def _execute(self, ctx: CommandContext) -> None:
        """Execute mode command.

        Args:
            ctx: Command context.
        """
        if not ctx.args or ctx.args[0] == "show":
            await self._show_mode(ctx)
        else:
            await self._set_mode(ctx)

    async def _show_mode(self, ctx: CommandContext) -> None:
        """Show current mode.

        Args:
            ctx: Command context.
        """
        mode = "Dry Run 🧪" if ctx.settings.dry_run_mode else "Live ⚡"
        color = discord.Color.gold() if ctx.settings.dry_run_mode else discord.Color.green()

        embed = discord.Embed(
            title="🎛️ Bot Mode",
            description=f"Current mode: **{mode}**",
            color=color,
        )

        if ctx.settings.dry_run_mode:
            embed.add_field(
                name="Dry Run Mode",
                value="✅ Actions are logged but not executed\n"
                "✅ Safe for testing\n"
                "✅ No users will be affected",
                inline=False,
            )
        else:
            embed.add_field(
                name="Live Mode",
                value="⚡ Actions are executed immediately\n"
                "⚠️ Users will be warned/timed out/kicked/banned\n"
                "⚠️ Use with caution",
                inline=False,
            )

        await ctx.channel.send(embed=embed)

    async def _set_mode(self, ctx: CommandContext) -> None:
        """Set bot mode.

        Args:
            ctx: Command context.
        """
        self.require_args(ctx, min_args=1, max_args=1)

        mode = ctx.args[0].lower()

        if mode == "dry-run":
            ctx.settings.dry_run_mode = True
            await ctx.reply_success(
                "Switched to **Dry Run Mode** 🧪\n"
                "Actions will be logged but not executed. Safe for testing."
            )
        elif mode == "live":
            ctx.settings.dry_run_mode = False
            await ctx.reply_success(
                "Switched to **Live Mode** ⚡\n"
                "⚠️ Actions will now be executed immediately. Use with caution."
            )
        else:
            raise InvalidArgumentError(f"Invalid mode '{mode}'. Use 'dry-run' or 'live'")


class StatusCommand(BaseCommand):
    """Display bot status and configuration."""

    def __init__(self) -> None:
        """Initialize status command."""
        super().__init__(
            name="status",
            description="Display bot status and current configuration",
            usage="!usmca status",
            requires_admin=True,
        )

    async def _execute(self, ctx: CommandContext) -> None:
        """Execute status command.

        Args:
            ctx: Command context.
        """
        mode = "Dry Run 🧪" if ctx.settings.dry_run_mode else "Live ⚡"
        color = discord.Color.gold() if ctx.settings.dry_run_mode else discord.Color.green()

        embed = discord.Embed(
            title="📊 Bot Status",
            color=color,
        )

        # Mode
        embed.add_field(
            name="Mode",
            value=f"**{mode}**",
            inline=True,
        )

        # Environment
        embed.add_field(
            name="Environment",
            value=f"`{ctx.settings.environment}`",
            inline=True,
        )

        # Log level
        embed.add_field(
            name="Log Level",
            value=f"`{ctx.settings.log_level}`",
            inline=True,
        )

        # Thresholds
        thresholds = (
            f"Warning: `{ctx.settings.toxicity_warning_threshold:.2f}`\n"
            f"Timeout: `{ctx.settings.toxicity_timeout_threshold:.2f}`\n"
            f"Kick: `{ctx.settings.toxicity_kick_threshold:.2f}`\n"
            f"Ban: `{ctx.settings.toxicity_ban_threshold:.2f}`"
        )
        embed.add_field(
            name="🎯 Thresholds",
            value=thresholds,
            inline=True,
        )

        # Timeouts
        timeouts = (
            f"1st: `{ctx.settings.timeout_first}s` ({ctx.settings.timeout_first/3600:.1f}h)\n"
            f"2nd: `{ctx.settings.timeout_second}s` ({ctx.settings.timeout_second/3600:.1f}h)\n"
            f"3rd: `{ctx.settings.timeout_third}s` ({ctx.settings.timeout_third/3600:.1f}h)"
        )
        embed.add_field(
            name="⏱️ Timeouts",
            value=timeouts,
            inline=True,
        )

        # Brigade settings
        brigade = (
            f"Joins: `{ctx.settings.brigade_joins_per_minute}/min`\n"
            f"Messages: `{ctx.settings.brigade_similar_messages}`\n"
            f"Window: `{ctx.settings.brigade_time_window}s`"
        )
        embed.add_field(
            name="🚨 Brigade Detection",
            value=brigade,
            inline=True,
        )

        # Channel filtering
        if ctx.settings.allowed_channel_ids:
            channels = f"Allowlist: {len(ctx.settings.allowed_channel_ids)} channels"
        elif ctx.settings.blocked_channel_ids:
            channels = f"Blocklist: {len(ctx.settings.blocked_channel_ids)} channels"
        else:
            channels = "Monitoring all channels"

        embed.add_field(
            name="📢 Channel Filtering",
            value=channels,
            inline=True,
        )

        # Database
        embed.add_field(
            name="💾 Database",
            value=f"Pool: `{ctx.settings.postgres_min_pool_size}-{ctx.settings.postgres_max_pool_size}`",
            inline=True,
        )

        # ML
        embed.add_field(
            name="🤖 ML Model",
            value=f"Device: `{ctx.settings.model_device}`",
            inline=True,
        )

        embed.set_footer(text=f"Guild: {ctx.guild.name} ({ctx.guild.id})")

        await ctx.channel.send(embed=embed)


class StatsCommand(BaseCommand):
    """Display moderation statistics."""

    def __init__(self) -> None:
        """Initialize stats command."""
        super().__init__(
            name="stats",
            description="Display moderation statistics",
            usage="!usmca stats [today|week|month|all]",
            requires_admin=True,
        )

    async def _execute(self, ctx: CommandContext) -> None:
        """Execute stats command.

        Args:
            ctx: Command context.
        """
        period = ctx.args[0].lower() if ctx.args else "today"

        if period not in ["today", "week", "month", "all"]:
            raise InvalidArgumentError(
                f"Invalid period '{period}'. Use: today, week, month, or all"
            )

        # Calculate time range
        now = datetime.now(UTC)
        if period == "today":
            since = now.replace(hour=0, minute=0, second=0, microsecond=0)
            title = "📊 Today's Statistics"
        elif period == "week":
            since = now - timedelta(days=7)
            title = "📊 Last 7 Days Statistics"
        elif period == "month":
            since = now - timedelta(days=30)
            title = "📊 Last 30 Days Statistics"
        else:  # all
            since = None
            title = "📊 All-Time Statistics"

        # Get statistics from database
        stats = await ctx.db.get_moderation_stats(since)

        embed = discord.Embed(
            title=title,
            color=discord.Color.blue(),
        )

        # Action counts
        actions = (
            f"Warnings: `{stats.get('warnings', 0):,}`\n"
            f"Timeouts: `{stats.get('timeouts', 0):,}`\n"
            f"Kicks: `{stats.get('kicks', 0):,}`\n"
            f"Bans: `{stats.get('bans', 0):,}`"
        )
        embed.add_field(
            name="⚖️ Actions Taken",
            value=actions,
            inline=True,
        )

        # Message stats
        messages = (
            f"Total: `{stats.get('total_messages', 0):,}`\n"
            f"Flagged: `{stats.get('flagged_messages', 0):,}`\n"
            f"Avg Toxicity: `{stats.get('avg_toxicity', 0.0):.3f}`"
        )
        embed.add_field(
            name="💬 Messages",
            value=messages,
            inline=True,
        )

        # User stats
        users = (
            f"Total: `{stats.get('total_users', 0):,}`\n"
            f"Whitelisted: `{stats.get('whitelisted', 0):,}`\n"
            f"At Risk: `{stats.get('at_risk', 0):,}`"
        )
        embed.add_field(
            name="👥 Users",
            value=users,
            inline=True,
        )

        # Brigade events
        if stats.get("brigade_events", 0) > 0:
            embed.add_field(
                name="🚨 Brigade Events Detected",
                value=f"`{stats.get('brigade_events', 0):,}`",
                inline=True,
            )

        if since:
            embed.set_footer(text=f"Since: {since.strftime('%Y-%m-%d %H:%M UTC')}")

        await ctx.channel.send(embed=embed)


class HelpCommand(BaseCommand):
    """Display help information."""

    def __init__(self) -> None:
        """Initialize help command."""
        super().__init__(
            name="help",
            description="Display available commands and usage",
            usage="!usmca help [command]",
            requires_admin=False,  # Anyone can see help
        )

    async def _execute(self, ctx: CommandContext) -> None:
        """Execute help command.

        Args:
            ctx: Command context.
        """
        if ctx.args:
            await self._show_command_help(ctx, ctx.args[0])
        else:
            await self._show_all_commands(ctx)

    async def _show_all_commands(self, ctx: CommandContext) -> None:
        """Show all available commands.

        Args:
            ctx: Command context.
        """
        from usmca_bot.commands.handler import command_registry

        embed = discord.Embed(
            title="🤖 USMCA Bot Commands",
            description="Available administrative commands",
            color=discord.Color.blue(),
        )

        # Get commands available to this user
        is_owner = ctx.is_owner()
        is_admin = ctx.is_admin()

        available_commands = command_registry.list_commands(is_owner, is_admin)

        if not available_commands:
            embed.add_field(
                name="No Commands Available",
                value="You don't have permission to use admin commands.",
                inline=False,
            )
        else:
            # Group commands by category
            config_cmds = [
                c for c in available_commands if c in ["threshold", "timeout", "brigade"]
            ]
            user_cmds = [
                c for c in available_commands if c in ["whitelist", "user", "pardon", "unban"]
            ]
            system_cmds = [
                c for c in available_commands if c in ["mode", "status", "stats", "help"]
            ]
            admin_cmds = [c for c in available_commands if c in ["admin"]]

            if config_cmds:
                embed.add_field(
                    name="⚙️ Configuration",
                    value="\n".join(f"• `{cmd}`" for cmd in config_cmds),
                    inline=False,
                )

            if user_cmds:
                embed.add_field(
                    name="👥 User Management",
                    value="\n".join(f"• `{cmd}`" for cmd in user_cmds),
                    inline=False,
                )

            if system_cmds:
                embed.add_field(
                    name="🎛️ System",
                    value="\n".join(f"• `{cmd}`" for cmd in system_cmds),
                    inline=False,
                )

            if admin_cmds:
                embed.add_field(
                    name="🔐 Admin Only",
                    value="\n".join(f"• `{cmd}`" for cmd in admin_cmds),
                    inline=False,
                )

        embed.set_footer(text="Use '!usmca help <command>' for detailed usage")

        await ctx.channel.send(embed=embed)

    async def _show_command_help(self, ctx: CommandContext, command_name: str) -> None:
        """Show help for a specific command.

        Args:
            ctx: Command context.
            command_name: Name of command to show help for.
        """
        from usmca_bot.commands.handler import command_registry

        command = command_registry.get(command_name)
        if not command:
            await ctx.reply_error(f"Unknown command '{command_name}'")
            return

        embed = discord.Embed(
            title=f"📖 Command: {command.name}",
            description=command.description,
            color=discord.Color.blue(),
        )

        embed.add_field(
            name="Usage",
            value=f"`{command.usage}`",
            inline=False,
        )

        permissions = []
        if command.requires_owner:
            permissions.append("🔐 Bot Owner Only")
        elif command.requires_admin:
            permissions.append("⚡ Admin Required")
        else:
            permissions.append("✅ All Users")

        embed.add_field(
            name="Permissions",
            value="\n".join(permissions),
            inline=False,
        )

        await ctx.channel.send(embed=embed)
