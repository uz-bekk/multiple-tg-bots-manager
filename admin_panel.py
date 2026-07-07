"""Inline-keyboard admin panel: statistics, user management, welcome message
IDs, and broadcasts.

Only reachable in a private chat with the MASTER bot, and only for user IDs
listed in config.ADMIN_IDS. Everything here is driven by callback_data of the
form "adm:<section>:<verb>:<args...>".
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MessageOriginChannel,
    Update,
)
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from config import ADMIN_IDS, BOT_LIST, BROADCAST_DELAY_SECONDS, LOG_CHANNEL_ID
from registry import APPLICATIONS
from storage import get_bot_store

logger = logging.getLogger("parked_bots.admin")

PAGE_SIZE = 8
USERS_PAGE_SIZE = 6

# admin_user_id -> pending multi-step action, e.g. {"action": "set_welcome", "idx": 3}
# Deliberately in-memory only: it's just UI state, not data worth persisting.
_PENDING: dict[int, dict[str, Any]] = {}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _short(bot_username: str) -> str:
    return bot_username.lstrip("@")


async def _safe_edit(query, text: str, kb: InlineKeyboardMarkup) -> None:
    try:
        await query.edit_message_text(text, reply_markup=kb)
    except TelegramError as exc:
        if "not modified" not in str(exc).lower():
            logger.warning("Failed to edit admin panel message: %s", exc)


# --------------------------------------------------------------------------- #
# KEYBOARDS
# --------------------------------------------------------------------------- #

def _home_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton("🏠 Home", callback_data="adm:home")]


def _main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📊 Statistics", callback_data="adm:stats:list:0")],
            [InlineKeyboardButton("👥 Users", callback_data="adm:users:list:0")],
            [InlineKeyboardButton("🆔 Welcome message IDs", callback_data="adm:mids:list:0")],
            [InlineKeyboardButton("📢 Broadcast", callback_data="adm:bcast:list:0")],
            [InlineKeyboardButton("❌ Close", callback_data="adm:close")],
        ]
    )


def _paginated_bot_kb(
    list_prefix: str,
    select_callback: Callable[[int], str],
    page: int,
    extra_row: list[InlineKeyboardButton] | None = None,
) -> InlineKeyboardMarkup:
    """Generic paged list of bots used by stats/users/mids/broadcast sections."""
    start = page * PAGE_SIZE
    chunk = list(enumerate(BOT_LIST))[start : start + PAGE_SIZE]
    rows = [[InlineKeyboardButton(f"🤖 {_short(b)}", callback_data=select_callback(i))] for i, b in chunk]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"{list_prefix}:{page - 1}"))
    if start + PAGE_SIZE < len(BOT_LIST):
        nav.append(InlineKeyboardButton("➡️ Next", callback_data=f"{list_prefix}:{page + 1}"))
    if nav:
        rows.append(nav)
    if extra_row:
        rows.append(extra_row)
    rows.append(_home_row())
    return InlineKeyboardMarkup(rows)


def _user_list_kb(idx: int, page: int, user_ids: list[str]) -> InlineKeyboardMarkup:
    start = page * USERS_PAGE_SIZE
    chunk = user_ids[start : start + USERS_PAGE_SIZE]
    rows = [[InlineKeyboardButton(f"👤 {uid}", callback_data=f"adm:users:profile:{idx}:{uid}")] for uid in chunk]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"adm:users:bot:{idx}:{page - 1}"))
    if start + USERS_PAGE_SIZE < len(user_ids):
        nav.append(InlineKeyboardButton("➡️ Next", callback_data=f"adm:users:bot:{idx}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("⬅️ Bots", callback_data="adm:users:list:0")])
    rows.append(_home_row())
    return InlineKeyboardMarkup(rows)


def _user_list_back_kb(idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Back to list", callback_data=f"adm:users:bot:{idx}:0")], _home_row()]
    )


def _user_detail_kb(idx: int, uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔄 Reset welcome flag", callback_data=f"adm:users:reset:{idx}:{uid}")],
            [InlineKeyboardButton("🗑 Delete record", callback_data=f"adm:users:del:{idx}:{uid}")],
            [InlineKeyboardButton("⬅️ Back to list", callback_data=f"adm:users:bot:{idx}:0")],
            _home_row(),
        ]
    )


def _mid_detail_kb(idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ Set new welcome message", callback_data=f"adm:mids:set:{idx}")],
            [InlineKeyboardButton("⬅️ Back to list", callback_data="adm:mids:list:0")],
            _home_row(),
        ]
    )


# --------------------------------------------------------------------------- #
# ENTRY POINTS (registered in main.py)
# --------------------------------------------------------------------------- #

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    _PENDING.pop(update.effective_user.id, None)
    await update.effective_message.reply_text(
        "🛠 Admin Panel\nChoose a section:", reply_markup=_main_menu_kb()
    )


async def handle_admin_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Called for every private message an admin sends to the master bot
    that isn't a slash command. Returns True if the message was consumed
    here (which is always, for admins - they never fall through to the
    regular "parked bot visitor" flow)."""
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return False

    pending = _PENDING.get(user.id)
    if pending is None:
        await message.reply_text("Use /admin to open the control panel.")
        return True

    action = pending["action"]
    if action == "set_welcome":
        await _finish_set_welcome(update, pending)
    elif action == "broadcast":
        await _finish_broadcast(update, pending)
    return True


async def on_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or not is_admin(user.id):
        if query:
            await query.answer("Not authorized.", show_alert=True)
        return

    await query.answer()
    _PENDING.pop(user.id, None)  # any button tap abandons a pending text-input action

    data = query.data or ""
    parts = data.split(":")
    if len(parts) < 2:
        return
    section = parts[1]

    if section == "home":
        await _safe_edit(query, "🛠 Admin Panel\nChoose a section:", _main_menu_kb())
        return
    if section == "close":
        try:
            await query.delete_message()
        except TelegramError:
            pass
        return

    verb = parts[2] if len(parts) > 2 else None

    if section == "stats":
        if verb == "list":
            await _render_stats_list(query, page=int(parts[3]))
        elif verb == "view":
            await _render_stats_detail(query, idx=int(parts[3]))

    elif section == "users":
        if verb == "list":
            kb = _paginated_bot_kb("adm:users:list", lambda i: f"adm:users:bot:{i}:0", int(parts[3]))
            await _safe_edit(query, "👥 Pick a bot to manage its users:", kb)
        elif verb == "bot":
            await _render_user_list(query, idx=int(parts[3]), page=int(parts[4]))
        elif verb == "profile":
            await _render_user_profile(query, idx=int(parts[3]), uid=parts[4])
        elif verb == "reset":
            await _reset_user(query, idx=int(parts[3]), uid=parts[4])
        elif verb == "del":
            await _delete_user(query, idx=int(parts[3]), uid=parts[4])

    elif section == "mids":
        if verb == "list":
            kb = _paginated_bot_kb("adm:mids:list", lambda i: f"adm:mids:view:{i}", int(parts[3]))
            await _safe_edit(query, "🆔 Pick a bot to view/set its welcome message:", kb)
        elif verb == "view":
            await _render_mid_detail(query, idx=int(parts[3]))
        elif verb == "set":
            await _start_set_welcome(query, user.id, idx=int(parts[3]))

    elif section == "bcast":
        if verb == "list":
            extra = [InlineKeyboardButton("📢 Broadcast to ALL bots", callback_data="adm:bcast:target:all")]
            kb = _paginated_bot_kb(
                "adm:bcast:list", lambda i: f"adm:bcast:target:{i}", int(parts[3]), extra_row=extra
            )
            await _safe_edit(query, "📢 Pick a target bot, or broadcast to all:", kb)
        elif verb == "target":
            target = "all" if parts[3] == "all" else int(parts[3])
            await _start_broadcast(query, user.id, target)


# --------------------------------------------------------------------------- #
# STATISTICS
# --------------------------------------------------------------------------- #

async def _render_stats_list(query, page: int) -> None:
    total_users = total_msgs = 0
    for bot_username in BOT_LIST:
        s = await get_bot_store(bot_username).stats()
        total_users += s["total_users"]
        total_msgs += s["total_messages"]

    text = (
        "📊 Overall Statistics\n\n"
        f"Bots: {len(BOT_LIST)}\n"
        f"Total users: {total_users}\n"
        f"Total messages received: {total_msgs}\n\n"
        "Tap a bot below for its own numbers:"
    )
    kb = _paginated_bot_kb("adm:stats:list", lambda i: f"adm:stats:view:{i}", page)
    await _safe_edit(query, text, kb)


async def _render_stats_detail(query, idx: int) -> None:
    bot_username = BOT_LIST[idx]
    s = await get_bot_store(bot_username).stats()
    text = (
        f"📊 {_short(bot_username)}\n\n"
        f"Total users: {s['total_users']}\n"
        f"Active today: {s['active_today']}\n"
        f"Total messages received: {s['total_messages']}"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm:stats:list:0")], _home_row()])
    await _safe_edit(query, text, kb)


# --------------------------------------------------------------------------- #
# USERS
# --------------------------------------------------------------------------- #

async def _render_user_list(query, idx: int, page: int) -> None:
    bot_username = BOT_LIST[idx]
    users = await get_bot_store(bot_username).all_users()
    user_ids = sorted(users.keys(), key=lambda k: users[k].get("last_seen", ""), reverse=True)

    if not user_ids:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Bots", callback_data="adm:users:list:0")], _home_row()])
        await _safe_edit(query, f"👥 {_short(bot_username)} has no users yet.", kb)
        return

    kb = _user_list_kb(idx, page, user_ids)
    await _safe_edit(query, f"👥 {_short(bot_username)} — {len(user_ids)} user(s). Tap one for details:", kb)


async def _render_user_profile(query, idx: int, uid: str) -> None:
    bot_username = BOT_LIST[idx]
    record = await get_bot_store(bot_username).get_user(int(uid))
    if record is None:
        await _safe_edit(query, "That user record no longer exists.", _user_list_back_kb(idx))
        return

    name = " ".join(filter(None, [record.get("first_name"), record.get("last_name")])) or "—"
    handle = f"@{record['username']}" if record.get("username") else "—"
    text = (
        f"👤 User {uid} ({_short(bot_username)})\n\n"
        f"Name: {name}\n"
        f"Username: {handle}\n"
        f"First seen: {record.get('first_seen', '—')}\n"
        f"Last seen: {record.get('last_seen', '—')}\n"
        f"Messages sent: {record.get('message_count', 0)}\n"
        f"Welcomed: {'Yes' if record.get('welcomed') else 'No'}"
    )
    await _safe_edit(query, text, _user_detail_kb(idx, uid))


async def _reset_user(query, idx: int, uid: str) -> None:
    bot_username = BOT_LIST[idx]
    await get_bot_store(bot_username).reset_welcomed(int(uid))
    await query.answer("Welcome flag reset - they'll get the full welcome message again.")
    await _render_user_profile(query, idx, uid)


async def _delete_user(query, idx: int, uid: str) -> None:
    bot_username = BOT_LIST[idx]
    await get_bot_store(bot_username).delete_user(int(uid))
    await query.answer("User record deleted.")
    await _render_user_list(query, idx, page=0)


# --------------------------------------------------------------------------- #
# WELCOME MESSAGE IDS
# --------------------------------------------------------------------------- #

async def _render_mid_detail(query, idx: int) -> None:
    bot_username = BOT_LIST[idx]
    mid = await get_bot_store(bot_username).get_welcome_message_id()
    text = (
        f"🆔 {_short(bot_username)}\n\n"
        f"Current welcome message ID: {mid if mid else 'not set (using fallback text)'}\n\n"
        "This is the channel post that gets copied - without a forward tag - "
        "to every new visitor of this bot."
    )
    await _safe_edit(query, text, _mid_detail_kb(idx))


async def _start_set_welcome(query, admin_id: int, idx: int) -> None:
    _PENDING[admin_id] = {"action": "set_welcome", "idx": idx}
    bot_username = BOT_LIST[idx]
    text = (
        f"✏️ Setting the welcome message for {_short(bot_username)}.\n\n"
        "Forward me the post from the log channel you want to use, "
        "or just send its numeric message ID as plain text."
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✖️ Cancel", callback_data=f"adm:mids:view:{idx}")]])
    await _safe_edit(query, text, kb)


async def _finish_set_welcome(update: Update, pending: dict) -> None:
    message = update.effective_message
    admin_id = update.effective_user.id
    idx = pending["idx"]
    bot_username = BOT_LIST[idx]

    message_id: int | None = None
    origin = message.forward_origin
    if isinstance(origin, MessageOriginChannel) and origin.chat.id == LOG_CHANNEL_ID:
        message_id = origin.message_id
    elif message.text and message.text.strip().isdigit():
        message_id = int(message.text.strip())

    if message_id is None:
        await message.reply_text(
            "I couldn't read a message ID from that. Forward the post from the "
            "log channel, or send its numeric message ID as plain text."
        )
        return  # keep the pending action active so they can retry

    await get_bot_store(bot_username).set_welcome_message_id(message_id)
    _PENDING.pop(admin_id, None)
    await message.reply_text(
        f"✅ Welcome message for {_short(bot_username)} set to channel message ID {message_id}."
    )


# --------------------------------------------------------------------------- #
# BROADCAST
# --------------------------------------------------------------------------- #

async def _start_broadcast(query, admin_id: int, target) -> None:
    _PENDING[admin_id] = {"action": "broadcast", "target": target}
    label = "ALL bots" if target == "all" else _short(BOT_LIST[target])
    text = f"📢 Send me the message to broadcast to {label} (text, photo, document - anything)."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✖️ Cancel", callback_data="adm:bcast:list:0")]])
    await _safe_edit(query, text, kb)


async def _finish_broadcast(update: Update, pending: dict) -> None:
    message = update.effective_message
    admin_id = update.effective_user.id
    target = pending["target"]
    _PENDING.pop(admin_id, None)

    label = "ALL bots" if target == "all" else _short(BOT_LIST[target])
    await message.reply_text(f"📢 Broadcasting to {label}, this may take a bit...")
    await _execute_broadcast(message.chat_id, message.message_id, target)


async def _execute_broadcast(admin_chat_id: int, admin_message_id: int, target) -> None:
    from config import MASTER_LOG_BOT_USERNAME

    master_app = APPLICATIONS.get(MASTER_LOG_BOT_USERNAME)
    if not master_app:
        return
    master_bot = master_app.bot

    try:
        # Relay the admin's content into the shared log channel first: every
        # bot is already a member/admin there, so every bot can then copy it
        # onward to its own users (a bot can't read a private chat it isn't
        # part of, which rules out copying straight from the admin's chat).
        relay = await master_bot.copy_message(
            chat_id=LOG_CHANNEL_ID, from_chat_id=admin_chat_id, message_id=admin_message_id
        )
    except TelegramError as exc:
        await master_bot.send_message(admin_chat_id, f"⚠️ Could not relay broadcast content: {exc}")
        return

    targets = BOT_LIST if target == "all" else [BOT_LIST[target]]
    total_sent = total_failed = 0
    for bot_username in targets:
        app = APPLICATIONS.get(bot_username)
        if not app:
            continue
        users = await get_bot_store(bot_username).all_users()
        for uid_str in list(users.keys()):
            try:
                await app.bot.copy_message(
                    chat_id=int(uid_str), from_chat_id=LOG_CHANNEL_ID, message_id=relay.message_id
                )
                total_sent += 1
            except TelegramError:
                total_failed += 1
            await asyncio.sleep(BROADCAST_DELAY_SECONDS)

    await master_bot.send_message(
        admin_chat_id, f"📢 Broadcast complete.\n✅ Sent: {total_sent}\n⚠️ Failed: {total_failed}"
    )
