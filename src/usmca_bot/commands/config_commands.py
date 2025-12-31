"""Configuration management commands.

This module provides commands for managing bot configuration including
thresholds, timeouts, and brigade detection settings.
"""

import discord

from usmca_bot.commands.base import BaseCommand, CommandContext, InvalidArgumentError


class ThresholdCommand(BaseCommand):
    """Manage toxicity thresholds."""

    def __init__(self) -> None:
        """Initialize threshold command."""
        super().__init__(
            name="threshold",
            description="View or update toxicity thresholds",
            usage="!usmca threshold [show|warning|timeout|kick|ban] [value]",
            requires_admin=True,
        )

    async def _execute(self, ctx: CommandContext) -> None:
        """Execute threshold command.

        Args:
            ctx: Command context.
        """
        if not ctx.args or ctx.args[0] == "show":
            await self._show_thresholds(ctx)
        else:
            await self._set_threshold(ctx)

    async def _show_thresholds(self, ctx: CommandContext) -> None:
        """Show current thresholds.

        Args:
            ctx: Command context.
        """
        embed = discord.Embed(
            title="🎯 Toxicity Thresholds",
            description="Current moderation thresholds (0.0 - 1.0 scale)",
            color=discord.Color.blue(),
        )

        embed.add_field(
            name="⚠️ Warning",
            value=f"`{ctx.settings.toxicity_warning_threshold:.2f}`",
            inline=True,
        )
        embed.add_field(
            name="🔇 Timeout",
            value=f"`{ctx.settings.toxicity_timeout_threshold:.2f}`",
            inline=True,
        )
        embed.add_field(
            name="👢 Kick",
            value=f"`{ctx.settings.toxicity_kick_threshold:.2f}`",
            inline=True,
        )
        embed.add_field(
            name="🔨 Ban",
            value=f"`{ctx.settings.toxicity_ban_threshold:.2f}`",
            inline=True,
        )

        embed.set_footer(text="Use '!usmca threshold <type> <value>' to update")

        await ctx.channel.send(embed=embed)

    async def _set_threshold(self, ctx: CommandContext) -> None:
        """Set a threshold value.

        Args:
            ctx: Command context.
        """
        self.require_args(ctx, min_args=2, max_args=2)

        threshold_type = ctx.args[0].lower()
        try:
            value = float(ctx.args[1])
        except ValueError as e:
            raise InvalidArgumentError(
                f"Invalid value '{ctx.args[1]}'. Must be a number between 0.0 and 1.0"
            ) from e

        if not 0.0 <= value <= 1.0:
            raise InvalidArgumentError(f"Value must be between 0.0 and 1.0, got {value}")

        # Map threshold types to settings attributes
        threshold_map: dict[str, str] = {
            "warning": "toxicity_warning_threshold",
            "timeout": "toxicity_timeout_threshold",
            "kick": "toxicity_kick_threshold",
            "ban": "toxicity_ban_threshold",
        }

        if threshold_type not in threshold_map:
            raise InvalidArgumentError(
                f"Invalid threshold type '{threshold_type}'. "
                f"Must be one of: {', '.join(threshold_map.keys())}"
            )

        attr_name = threshold_map[threshold_type]
        old_value = getattr(ctx.settings, attr_name)

        # Update the setting (in-memory for this session)
        # Note: This is temporary until bot restart
        setattr(ctx.settings, attr_name, value)

        # TODO: Store in database configuration table for persistence

        await ctx.reply_success(
            f"Updated **{threshold_type}** threshold: `{old_value:.2f}` → `{value:.2f}`\n"
            f"⚠️ *Note: This change is temporary until bot restart. "
            f"Update `.env` file for permanent change.*"
        )


class TimeoutCommand(BaseCommand):
    """Manage timeout durations."""

    def __init__(self) -> None:
        """Initialize timeout command."""
        super().__init__(
            name="timeout",
            description="View or update timeout durations",
            usage="!usmca timeout [show|first|second|third] [seconds]",
            requires_admin=True,
        )

    async def _execute(self, ctx: CommandContext) -> None:
        """Execute timeout command.

        Args:
            ctx: Command context.
        """
        if not ctx.args or ctx.args[0] == "show":
            await self._show_timeouts(ctx)
        else:
            await self._set_timeout(ctx)

    async def _show_timeouts(self, ctx: CommandContext) -> None:
        """Show current timeout durations.

        Args:
            ctx: Command context.
        """
        embed = discord.Embed(
            title="⏱️ Timeout Durations",
            description="Progressive timeout durations",
            color=discord.Color.blue(),
        )

        first_hours = ctx.settings.timeout_first / 3600
        second_hours = ctx.settings.timeout_second / 3600
        third_hours = ctx.settings.timeout_third / 3600

        embed.add_field(
            name="1️⃣ First Timeout",
            value=f"`{ctx.settings.timeout_first}s` ({first_hours:.1f}h)",
            inline=True,
        )
        embed.add_field(
            name="2️⃣ Second Timeout",
            value=f"`{ctx.settings.timeout_second}s` ({second_hours:.1f}h)",
            inline=True,
        )
        embed.add_field(
            name="3️⃣ Third+ Timeout",
            value=f"`{ctx.settings.timeout_third}s` ({third_hours:.1f}h)",
            inline=True,
        )

        embed.set_footer(text="Use '!usmca timeout <level> <seconds>' to update")

        await ctx.channel.send(embed=embed)

    async def _set_timeout(self, ctx: CommandContext) -> None:
        """Set timeout duration.

        Args:
            ctx: Command context.
        """
        self.require_args(ctx, min_args=2, max_args=2)

        level = ctx.args[0].lower()
        try:
            seconds = int(ctx.args[1])
        except ValueError as e:
            raise InvalidArgumentError(f"Invalid value '{ctx.args[1]}'. Must be an integer") from e

        if seconds < 60 or seconds > 2419200:  # 60s to 28 days
            raise InvalidArgumentError("Duration must be between 60 seconds and 28 days")

        # Map levels to settings attributes
        level_map: dict[str, str] = {
            "first": "timeout_first",
            "second": "timeout_second",
            "third": "timeout_third",
        }

        if level not in level_map:
            raise InvalidArgumentError(
                f"Invalid level '{level}'. Must be one of: {', '.join(level_map.keys())}"
            )

        attr_name = level_map[level]
        old_value = getattr(ctx.settings, attr_name)

        # Update the setting
        setattr(ctx.settings, attr_name, seconds)

        hours = seconds / 3600
        old_hours = old_value / 3600

        await ctx.reply_success(
            f"Updated **{level}** timeout: `{old_value}s` ({old_hours:.1f}h) → "
            f"`{seconds}s` ({hours:.1f}h)\n"
            f"⚠️ *Note: This change is temporary until bot restart.*"
        )


class BrigadeCommand(BaseCommand):
    """Manage brigade detection settings."""

    def __init__(self) -> None:
        """Initialize brigade command."""
        super().__init__(
            name="brigade",
            description="View or update brigade detection settings",
            usage="!usmca brigade [show|joins|messages|window] [value]",
            requires_admin=True,
        )

    async def _execute(self, ctx: CommandContext) -> None:
        """Execute brigade command.

        Args:
            ctx: Command context.
        """
        if not ctx.args or ctx.args[0] == "show":
            await self._show_settings(ctx)
        else:
            await self._update_setting(ctx)

    async def _show_settings(self, ctx: CommandContext) -> None:
        """Show current brigade settings.

        Args:
            ctx: Command context.
        """
        embed = discord.Embed(
            title="🚨 Brigade Detection Settings",
            description="Settings for detecting coordinated attacks",
            color=discord.Color.blue(),
        )

        embed.add_field(
            name="👥 Joins Per Minute",
            value=f"`{ctx.settings.brigade_joins_per_minute}` users/min",
            inline=True,
        )
        embed.add_field(
            name="💬 Similar Messages",
            value=f"`{ctx.settings.brigade_similar_messages}` messages",
            inline=True,
        )
        embed.add_field(
            name="⏱️ Time Window",
            value=f"`{ctx.settings.brigade_time_window}s` ({ctx.settings.brigade_time_window / 60:.1f}min)",
            inline=True,
        )

        embed.set_footer(text="Use '!usmca brigade <setting> <value>' to update")

        await ctx.channel.send(embed=embed)

    async def _update_setting(self, ctx: CommandContext) -> None:
        """Update a brigade setting.

        Args:
            ctx: Command context.
        """
        self.require_args(ctx, min_args=2, max_args=2)

        setting = ctx.args[0].lower()
        try:
            value = int(ctx.args[1])
        except ValueError as e:
            raise InvalidArgumentError(f"Invalid value '{ctx.args[1]}'. Must be an integer") from e

        # Map settings to attributes and validate
        if setting == "joins":
            if not 1 <= value <= 100:
                raise InvalidArgumentError("Joins per minute must be between 1 and 100")
            old_value = ctx.settings.brigade_joins_per_minute
            ctx.settings.brigade_joins_per_minute = value
            unit = "users/min"

        elif setting == "messages":
            if not 2 <= value <= 20:
                raise InvalidArgumentError("Similar messages must be between 2 and 20")
            old_value = ctx.settings.brigade_similar_messages
            ctx.settings.brigade_similar_messages = value
            unit = "messages"

        elif setting == "window":
            if not 60 <= value <= 3600:
                raise InvalidArgumentError("Time window must be between 60 and 3600 seconds")
            old_value = ctx.settings.brigade_time_window
            ctx.settings.brigade_time_window = value
            unit = f"s ({value / 60:.1f}min)"

        else:
            raise InvalidArgumentError(
                f"Invalid setting '{setting}'. Must be one of: joins, messages, window"
            )

        await ctx.reply_success(
            f"Updated **{setting}** setting: `{old_value}` → `{value}` {unit}\n"
            f"⚠️ *Note: This change is temporary until bot restart.*"
        )
