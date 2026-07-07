"""Configuration constants for the multi-bot parked-bots system."""
from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------- #
# BOT TOKENS
# --------------------------------------------------------------------------- #
# The FIRST entry is the "master bot": it hosts the /admin panel and listens
# for admin replies typed in the log channel.
BOTS_DICT: dict[str, str] = {
    "@ManagerBotUsername": "Token",
    "@DeadBot1": "Token",
    "@DeadBot2": "Token"   
}

BOT_LIST: list[str] = list(BOTS_DICT.keys())
MASTER_LOG_BOT_USERNAME: str = BOT_LIST[0]

LOG_CHANNEL_ID = -1000123456789
OWNER_CONTACT = "@Username"

# --------------------------------------------------------------------------- #
# ADMIN ACCESS
# --------------------------------------------------------------------------- #
# IMPORTANT: replace the placeholder below with your real numeric Telegram
# user ID (not username). You can get it from @userinfobot. You can list
# more than one ID if several people should have admin-panel access.
ADMIN_IDS: set[int] = {
    123456789,  # <-- put your real Telegram numeric user ID here
}

# --------------------------------------------------------------------------- #
# STORAGE
# --------------------------------------------------------------------------- #
DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

ROUTING_FILE = DATA_DIR / "_routing.json"
MAX_ROUTING_ENTRIES = 5000  # oldest entries are pruned past this to keep the file small

BROADCAST_DELAY_SECONDS = 0.05  # throttle between sends to respect Telegram flood limits
