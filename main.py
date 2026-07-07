"""
Multi-bot "parked bots" system - entry point.

- Every bot persists its own users to data/<bot>.json (survives restarts).
- New visitors get a one-time welcome copied from a channel post (no forward
  tag); repeat visitors get a short, randomly-varied acknowledgement instead.
- The master bot (first entry in config.BOTS_DICT) hosts an inline-keyboard
  /admin panel: statistics, user management, welcome-message IDs, broadcasts.
- Admin replies typed in the log channel (as a reply to a forwarded message)
  are routed back to the right user via the right bot.
"""
from __future__ import annotations

import asyncio
import logging

from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from admin_panel import cmd_admin, on_admin_callback
from config import BOTS_DICT, LOG_CHANNEL_ID, MASTER_LOG_BOT_USERNAME
from handlers import handle_channel_reply, handle_incoming_private
from registry import APPLICATIONS
from texts import escape_md_v2

# --------------------------------------------------------------------------- #
# LOGGING (silenced getUpdates polling noise)
# --------------------------------------------------------------------------- #
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.WARNING,
)
logger = logging.getLogger("parked_bots")
logger.setLevel(logging.INFO)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext._updater").setLevel(logging.WARNING)
logging.getLogger("telegram.ext._application").setLevel(logging.WARNING)


# --------------------------------------------------------------------------- #
# BOT CORE LIFECYCLE
# --------------------------------------------------------------------------- #

async def run_bot(bot_username: str, token: str) -> Application:
    application = Application.builder().token(token).build()
    application.bot_data["bot_username"] = bot_username

    if bot_username == MASTER_LOG_BOT_USERNAME:
        # Registered first so they take priority over the generic private handler.
        application.add_handler(CommandHandler("admin", cmd_admin, filters=filters.ChatType.PRIVATE))
        application.add_handler(CallbackQueryHandler(on_admin_callback, pattern=r"^adm:"))
        application.add_handler(MessageHandler(filters.ChatType.CHANNEL & filters.REPLY, handle_channel_reply))

    application.add_handler(MessageHandler(filters.ChatType.PRIVATE, handle_incoming_private))

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)

    APPLICATIONS[bot_username] = application

    safe_startup_name = escape_md_v2(bot_username)
    try:
        await application.bot.send_message(
            chat_id=LOG_CHANNEL_ID,
            text=fr"🤖 *{safe_startup_name}* started working\!",
            parse_mode="MarkdownV2",
        )
    except TelegramError as exc:
        logger.warning("Could not send startup message for %s: %s", bot_username, exc)

    logger.info("%s is online.", bot_username)
    return application


async def shutdown_bot(application: Application) -> None:
    await application.updater.stop()
    await application.stop()
    await application.shutdown()


# --------------------------------------------------------------------------- #
# ENTRY POINT
# --------------------------------------------------------------------------- #

async def main() -> None:
    applications = await asyncio.gather(
        *(run_bot(username, token) for username, token in BOTS_DICT.items())
    )

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Gracefully stopping all active instances...")
        await asyncio.gather(*(shutdown_bot(app) for app in applications))


if __name__ == "__main__":
    asyncio.run(main())
