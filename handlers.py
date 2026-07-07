"""Private-chat and channel-reply handlers for parked bots."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from admin_panel import handle_admin_private_message, is_admin
from config import LOG_CHANNEL_ID, MASTER_LOG_BOT_USERNAME
from registry import APPLICATIONS
from storage import get_bot_store, routing_store
from texts import FALLBACK_PARKED_MESSAGE, contact_card, escape_md_v2, random_ack

logger = logging.getLogger("parked_bots.handlers")


async def handle_incoming_private(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    bot_username: str = context.bot_data["bot_username"]

    # Admins talking to the master bot privately go through the admin panel
    # instead of being treated as a regular "parked bot" visitor.
    if bot_username == MASTER_LOG_BOT_USERNAME and is_admin(user.id):
        handled = await handle_admin_private_message(update, context)
        if handled:
            return

    store = get_bot_store(bot_username)
    record, is_new = await store.touch_user(user)

    # 1. Post a contact card to the shared log channel the first time we see
    #    this user (via the master bot, so it's always the same poster).
    if is_new:
        master_app = APPLICATIONS.get(MASTER_LOG_BOT_USERNAME)
        if master_app:
            try:
                await master_app.bot.send_message(
                    chat_id=LOG_CHANNEL_ID,
                    text=contact_card(bot_username, user),
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            except TelegramError as exc:
                logger.warning("Master bot failed to post contact card: %s", exc)

    # 2. Native forwarding of the raw message to the log channel, so admins
    #    can see it and reply to route a message back to this user.
    try:
        forwarded = await context.bot.forward_message(
            chat_id=LOG_CHANNEL_ID,
            from_chat_id=message.chat_id,
            message_id=message.message_id,
        )
        await routing_store.set(forwarded.message_id, user.id, bot_username)
    except TelegramError as exc:
        logger.warning("%s failed to forward message: %s", bot_username, exc)

    # 3. Reply to the user: the full welcome exactly once, short varied
    #    acknowledgements on every message after that.
    if not record.get("welcomed"):
        await _send_welcome(context, bot_username, message)
        await store.mark_welcomed(user.id)
    else:
        try:
            await message.reply_text(random_ack())
        except TelegramError as exc:
            logger.warning("Could not send follow-up ack via %s: %s", bot_username, exc)


async def _send_welcome(context: ContextTypes.DEFAULT_TYPE, bot_username: str, message) -> None:
    store = get_bot_store(bot_username)
    welcome_message_id = await store.get_welcome_message_id()

    if welcome_message_id:
        try:
            # copy_message re-sends the channel content as if the bot wrote
            # it itself - no "Forwarded from" tag, unlike forward_message.
            await context.bot.copy_message(
                chat_id=message.chat_id,
                from_chat_id=LOG_CHANNEL_ID,
                message_id=welcome_message_id,
            )
            return
        except TelegramError as exc:
            logger.warning(
                "Could not copy welcome message %s for %s (%s); falling back to default text.",
                welcome_message_id, bot_username, exc,
            )

    # Fallback: no welcome message configured for this bot yet, or the copy failed.
    safe_bot = escape_md_v2(bot_username)
    try:
        await message.reply_text(
            FALLBACK_PARKED_MESSAGE.format(bot_username=safe_bot),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except TelegramError as exc:
        logger.warning("Could not send fallback welcome via %s: %s", bot_username, exc)


async def handle_channel_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin replies (in the log channel, to a forwarded message) get routed
    back to the originating user via that user's own bot."""
    channel_post = update.channel_post
    if not channel_post or not channel_post.reply_to_message:
        return

    target_msg_id = channel_post.reply_to_message.message_id
    routing_info = await routing_store.get(target_msg_id)
    if not routing_info:
        return

    target_user_id = routing_info["user_id"]
    origin_bot_username = routing_info["bot_username"]

    origin_app = APPLICATIONS.get(origin_bot_username)
    if not origin_app:
        return

    try:
        # copy_message (rather than send_message) also supports photos,
        # documents, voice notes, etc. - not just plain text replies.
        await origin_app.bot.copy_message(
            chat_id=target_user_id,
            from_chat_id=channel_post.chat_id,
            message_id=channel_post.message_id,
        )
        logger.info("Routed reply via %s to User ID %s", origin_bot_username, target_user_id)
    except TelegramError as exc:
        logger.warning(
            "Failed to route reply to user %s via %s: %s", target_user_id, origin_bot_username, exc
        )
