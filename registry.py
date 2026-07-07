"""Tiny shared registry so other modules can look up running Application
instances (e.g. to send a message via a specific bot) without creating
circular imports between handlers.py, admin_panel.py and main.py."""
from __future__ import annotations

from telegram.ext import Application

APPLICATIONS: dict[str, Application] = {}
