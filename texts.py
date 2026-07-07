"""User-facing copy: MarkdownV2 escaping, fallback welcome text, follow-up
acknowledgements, and the admin log-channel contact card."""
from __future__ import annotations

import random
import re
from datetime import datetime, timezone

_ESCAPE_CHARS = r"_*[]()~`>#+-=|{}.!"


def escape_md_v2(text: str) -> str:
    """Escapes mandatory MarkdownV2 characters to avoid parsing exceptions."""
    return re.sub(r"([%s])" % re.escape(_ESCAPE_CHARS), r"\\\1", text)


# Used ONLY when an admin hasn't configured a channel welcome message for a
# bot yet (see the "Welcome message IDs" section of the admin panel).
FALLBACK_PARKED_MESSAGE = r"""🔒 *This Premium Username Is Currently Parked*

The username {bot_username} is currently inactive and available for purchase\.

💬 *Interested in buying it?*
Leave your message here, and I'll get back to you as soon as possible\.

👋 *A quick question:*
What did you expect this bot to do when you opened it?

Your ideas and suggestions help me build bots that people actually want to use\. Thanks for your feedback\! ❤️
"""

# Short, varied acknowledgements shown after a user has already received the
# one-time welcome. Picked at random so repeat visitors don't see the exact
# same line (or the long welcome) every single time.
FOLLOW_UP_ACKS: list[str] = [
    "Got it, thanks! 👍",
    "Thanks for the message — I'll get back to you soon.",
    "Received ✅ I'll follow up shortly.",
    "Noted, thank you!",
    "Thanks! Someone will respond soon.",
    "Message received 📩",
    "Got your message, thanks for your patience 🙏",
    "Thanks for reaching out — noted!",
    "👌 Got it, hang tight.",
    "Appreciate the message, I'll be in touch.",
]


def random_ack() -> str:
    return random.choice(FOLLOW_UP_ACKS)


def contact_card(original_bot_username: str, user) -> str:
    """MarkdownV2 card posted to the log channel the first time a user
    messages a given bot."""
    raw_full_name = " ".join(filter(None, [user.first_name, user.last_name])) or "—"
    full_name = escape_md_v2(raw_full_name[:50])

    raw_handle = f"@{user.username}" if user.username else "—"
    handle = escape_md_v2(raw_handle[:32])

    safe_bot_name = escape_md_v2(original_bot_username)
    timestamp = escape_md_v2(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    return (
        "🆕 *New Buyer Active\\!*\n"
        f"*Triggered Bot:* {safe_bot_name}\n"
        f"*Name:* {full_name}\n"
        f"*User ID:* `{user.id}`\n"
        f"*Username:* {handle}\n"
        f"*Time:* {timestamp}"
    )
