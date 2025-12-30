"""Command-line interface for USMCA Bot.

This module provides the CLI entry point for running the bot.
"""

import asyncio
import signal
import sys
from typing import NoReturn

import structlog

from usmca_bot.bot import USMCABot
from usmca_bot.config import Settings, get_settings

logger = structlog.get_logger()


def setup_logging(settings: Settings) -> None:
    """Configure structured logging.

    Args:
        settings: Application settings.
    """
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer()
            if settings.environment == "development"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(structlog.stdlib, settings.log_level.upper(), structlog.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


async def run_bot_async() -> None:
    """Run the bot asynchronously with proper signal handling."""
    # Get settings
    settings = get_settings()

    # Setup logging
    setup_logging(settings)

    log = logger.bind(component="cli")
    log.info(
        "usmca_bot_starting",
        environment=settings.environment,
        log_level=settings.log_level,
    )

    # Create bot instance
    bot = USMCABot(settings)

    # Setup signal handlers for graceful shutdown
    def signal_handler(sig: int) -> None:
        """Handle shutdown signals.

        Args:
            sig: Signal number.
        """
        signal_name = signal.Signals(sig).name
        log.info("shutdown_signal_received", signal=signal_name)

        # Create task to close bot
        asyncio.create_task(bot.close())

    # Register signal handlers
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))

    try:
        # Start bot
        log.info("connecting_to_discord")
        await bot.start(settings.discord_token)

    except KeyboardInterrupt:
        log.info("keyboard_interrupt_received")
    except Exception as e:
        log.error("bot_error", error=str(e), exc_info=True)
        raise
    finally:
        # Ensure cleanup
        if not bot.is_closed():
            await bot.close()

        log.info("bot_stopped")


def main() -> NoReturn:
    """Main entry point for the CLI.

    This function is called when running `usmca-bot` from the command line.
    """
    try:
        # Run bot
        asyncio.run(run_bot_async())
        sys.exit(0)

    except KeyboardInterrupt:
        logger.info("shutdown_complete")
        sys.exit(0)

    except Exception as e:
        logger.error("fatal_error", error=str(e), exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()