"""Domain Foundry Telegram bridge — text a bot, get structured personal data.

One of Domain Foundry's three tested harnesses (with the MCP server and the
hermes-agent adapter). Captures Telegram messages first, routes them to typed
domain records, and applies one-message corrections — all into local SQLite.
"""

from __future__ import annotations

from domain_foundry_telegram.bridge import HELP_TEXT, TelegramBridge
from domain_foundry_telegram.poller import HttpxTransport, TelegramPoller, main

__all__ = ["TelegramBridge", "TelegramPoller", "HttpxTransport", "HELP_TEXT", "main"]
__version__ = "0.1.0"
