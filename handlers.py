"""Private-chat and channel-reply handlers for parked bots."""
from __future__ import annotations

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from admin_panel import handle_admin_private_message, is_admin
from config import LOG_CHANNEL_ID, MASTER_LOG_BOT_USERNAME, REQUIRED_CHANNELS
from registry import APPLICATIONS
from storage import get_bot_store, routing_store
from texts import FALLBACK_PARKED_MESSAGE, contact_card, escape_md_v2, random_ack

logger = logging.getLogger("parked_bots.handlers")

# --- SUBSCRIPTION CHECK ---
async def is_user_subscribed(user_id, context):
    required_channels = REQUIRED_CHANNELS
    for ch in required_channels:
        try:
            member = await context.bot.get_chat_member(ch, user_id)
            if member.status not in ("member", "administrator", "creator"):
                return False
        except:
            return False
    return True

async def ask_to_join(update: Update, context):
    user_id = update.effective_user.id
    required_channels = REQUIRED_CHANNELS
    buttons = []
    
    for ch in required_channels:
        is_subscribed = False
        try:
            member = await context.bot.get_chat_member(ch, user_id)
            if member.status in ("member", "administrator", "creator"):
                is_subscribed = True
        except:
            pass
        
        if not is_subscribed and ch.startswith("@"):
            buttons.append([
                InlineKeyboardButton(
                    f"📢 Subscribe {ch[1:]}",
                    url=f"https://t.me/{ch[1:]}"
                )
            ])

    buttons.append([
        InlineKeyboardButton("✅ Submit", callback_data="check_subscription")
    ])
    
    await context.bot.send_message(
        update.effective_chat.id,
        f"🚫 Hello {update.effective_user.first_name}. Welcome to {context.bot_data['bot_username']}. To use this bot, please join this channel:\n\n"
        "👉 After joining, please click the «✅ Submit» button.",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def handle_incoming_private(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    bot_username: str = context.bot_data["bot_username"]

    # Admins talking to the master bot privately go through the admin panel
    if bot_username == MASTER_LOG_BOT_USERNAME and is_admin(user.id):
        handled = await handle_admin_private_message(update, context)
        if handled:
            return

    # =================================================================
    # 1. ALWAYS SAVE & LOG NEW USER FIRST
    # =================================================================
    store = get_bot_store(bot_username)
    record, is_new = await store.touch_user(user)

    # Post a contact card to the shared log channel the first time we see this user
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

    # =================================================================
    # 2. SUBSCRIPTION CHECK (GATEKEEPER)
    # =================================================================
    # Skip subscription checks for admins so they don't lock themselves out
    if not (bot_username == MASTER_LOG_BOT_USERNAME and is_admin(user.id)):
        subscribed = await is_user_subscribed(user.id, context)
        if not subscribed:
            await ask_to_join(update, context)
            return  # HALT HERE: User is saved and logged, but cannot proceed further
    # =================================================================

    # =================================================================
    # 3. ROUTE MESSAGES (Only reached if subscribed)
    # =================================================================
    # Native forwarding of the raw message to the log channel
    try:
        forwarded = await context.bot.forward_message(
            chat_id=LOG_CHANNEL_ID,
            from_chat_id=message.chat_id,
            message_id=message.message_id,
        )
        await routing_store.set(forwarded.message_id, user.id, bot_username)
    except TelegramError as exc:
        logger.warning("%s failed to forward message: %s", bot_username, exc)

    # Reply to the user (Welcome message or acknowledgement)
    if not record.get("welcomed"):
        await _send_welcome(context, bot_username, message)
        await store.mark_welcomed(user.id)
    else:
        try:
            await message.reply_text(random_ack())
        except TelegramError as exc:
            logger.warning("Could not send follow-up ack via %s: %s", bot_username, exc)


async def handle_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    
    # Always answer callback queries to remove the loading clock icon on Telegram
    await query.answer()

    subscribed = await is_user_subscribed(user_id, context)
    
    if subscribed:
        # Success UI updated to Uzbek language context
        await query.delete_message()  # Remove the subscription prompt message
        await handle_incoming_private(update, context)  # Re-run the private message handler
    else:
        # Failure alert window
        await query.answer(
            text="❌ You are not yet subscribed to all required channels!",
            show_alert=True
        )


async def _send_welcome(context: ContextTypes.DEFAULT_TYPE, bot_username: str, message) -> None:
    store = get_bot_store(bot_username)
    welcome_message_id = await store.get_welcome_message_id()

    if welcome_message_id:
        try:
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

    safe_bot = escape_md_v2(bot_username)
    try:
        await message.reply_text(
            FALLBACK_PARKED_MESSAGE.format(bot_username=safe_bot),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except TelegramError as exc:
        logger.warning("Could not send fallback welcome via %s: %s", bot_username, exc)


async def handle_channel_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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