"""Async-safe, atomic JSON persistence.

Each bot gets its own JSON file under data/ (so restarting the whole system
never makes a bot "forget" its users), plus one shared file for the
channel-reply routing map (message IDs live in one shared channel, so a
single map keyed by message_id is enough - no need to duplicate it per bot).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DATA_DIR, MAX_ROUTING_ENTRIES, ROUTING_FILE

logger = logging.getLogger("parked_bots.storage")

_LOCKS: dict[str, asyncio.Lock] = {}


def _lock_for(path: Path) -> asyncio.Lock:
    key = str(path)
    if key not in _LOCKS:
        _LOCKS[key] = asyncio.Lock()
    return _LOCKS[key]


def _safe_filename(bot_username: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", bot_username)
    return f"{name}.json"


def _atomic_write(path: Path, data: dict) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _read(path: Path, default: dict) -> dict:
    if not path.exists():
        return json.loads(json.dumps(default))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Corrupt or unreadable JSON at %s (%s); starting fresh.", path, exc)
        try:
            path.replace(path.with_suffix(".corrupt.json"))
        except OSError:
            pass
        return json.loads(json.dumps(default))


class BotStore:
    """Per-bot persistent state: welcome-message setting + user profiles."""

    _DEFAULT: dict[str, Any] = {"welcome_message_id": None, "users": {}}

    def __init__(self, bot_username: str):
        self.bot_username = bot_username
        self.path = DATA_DIR / _safe_filename(bot_username)
        self._data: dict[str, Any] | None = None

    async def _ensure_loaded(self) -> dict:
        if self._data is None:
            async with _lock_for(self.path):
                if self._data is None:
                    data = _read(self.path, self._DEFAULT)
                    data.setdefault("welcome_message_id", None)
                    data.setdefault("users", {})
                    self._data = data
        return self._data

    async def _save(self) -> None:
        async with _lock_for(self.path):
            _atomic_write(self.path, self._data)

    # ---- users -------------------------------------------------------- #
    async def touch_user(self, user) -> tuple[dict, bool]:
        """Record/update a user's profile on an incoming message.
        Returns (record, is_new_user)."""
        data = await self._ensure_loaded()
        uid = str(user.id)
        now = datetime.now(timezone.utc).isoformat()
        record = data["users"].get(uid)
        is_new = record is None
        if is_new:
            record = {
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "username": user.username or "",
                "first_seen": now,
                "last_seen": now,
                "message_count": 0,
                "welcomed": False,
            }
            data["users"][uid] = record

        record["first_name"] = user.first_name or record.get("first_name", "")
        record["last_name"] = user.last_name or record.get("last_name", "")
        record["username"] = user.username or record.get("username", "")
        record["last_seen"] = now
        record["message_count"] = record.get("message_count", 0) + 1
        await self._save()
        return record, is_new

    async def mark_welcomed(self, user_id: int) -> None:
        data = await self._ensure_loaded()
        record = data["users"].get(str(user_id))
        if record is not None:
            record["welcomed"] = True
            await self._save()

    async def reset_welcomed(self, user_id: int) -> None:
        data = await self._ensure_loaded()
        record = data["users"].get(str(user_id))
        if record is not None:
            record["welcomed"] = False
            await self._save()

    async def delete_user(self, user_id: int) -> bool:
        data = await self._ensure_loaded()
        existed = data["users"].pop(str(user_id), None) is not None
        if existed:
            await self._save()
        return existed

    async def get_user(self, user_id: int) -> dict | None:
        data = await self._ensure_loaded()
        return data["users"].get(str(user_id))

    async def all_users(self) -> dict:
        data = await self._ensure_loaded()
        return data["users"]

    # ---- settings ------------------------------------------------------- #
    async def get_welcome_message_id(self) -> int | None:
        data = await self._ensure_loaded()
        return data.get("welcome_message_id")

    async def set_welcome_message_id(self, message_id: int) -> None:
        data = await self._ensure_loaded()
        data["welcome_message_id"] = message_id
        await self._save()

    # ---- stats ------------------------------------------------------------ #
    async def stats(self) -> dict:
        data = await self._ensure_loaded()
        users = data["users"]
        today = datetime.now(timezone.utc).date()
        active_today = 0
        total_messages = 0
        for rec in users.values():
            total_messages += rec.get("message_count", 0)
            try:
                if datetime.fromisoformat(rec["last_seen"]).date() == today:
                    active_today += 1
            except (KeyError, ValueError):
                pass
        return {
            "total_users": len(users),
            "total_messages": total_messages,
            "active_today": active_today,
        }


_BOT_STORES: dict[str, BotStore] = {}


def get_bot_store(bot_username: str) -> BotStore:
    if bot_username not in _BOT_STORES:
        _BOT_STORES[bot_username] = BotStore(bot_username)
    return _BOT_STORES[bot_username]


class RoutingStore:
    """Shared persistent map: log-channel message_id -> {user_id, bot_username}.

    This lets admin replies typed in the log channel keep working correctly
    even across a restart.
    """

    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, Any] | None = None

    async def _ensure_loaded(self) -> dict:
        if self._data is None:
            async with _lock_for(self.path):
                if self._data is None:
                    self._data = _read(self.path, {})
        return self._data

    async def _save(self) -> None:
        async with _lock_for(self.path):
            _atomic_write(self.path, self._data)

    async def set(self, channel_message_id: int, user_id: int, bot_username: str) -> None:
        data = await self._ensure_loaded()
        data[str(channel_message_id)] = {"user_id": user_id, "bot_username": bot_username}
        if len(data) > MAX_ROUTING_ENTRIES:
            overflow = len(data) - MAX_ROUTING_ENTRIES
            for key in list(data.keys())[:overflow]:
                data.pop(key, None)
        await self._save()

    async def get(self, channel_message_id: int) -> dict | None:
        data = await self._ensure_loaded()
        return data.get(str(channel_message_id))


routing_store = RoutingStore(ROUTING_FILE)
