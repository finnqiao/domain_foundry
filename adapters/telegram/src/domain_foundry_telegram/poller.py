"""Telegram transport + long-poll loop.

The loop is transport-agnostic: :class:`TelegramPoller` talks to a small
``transport`` object (``get_updates`` / ``send_message``). :class:`HttpxTransport`
is the real Telegram Bot API; the tests inject an in-memory fake to prove the
whole conversation loop offline.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from domain_foundry_telegram.bridge import TelegramBridge


class Transport(Protocol):
    def get_updates(self, offset: int, timeout: int) -> list[dict[str, Any]]: ...
    def send_message(self, chat_id: int, text: str) -> None: ...


class HttpxTransport:
    """Real Telegram Bot API over HTTPS long-polling."""

    def __init__(self, token: str, api_base: str = "https://api.telegram.org") -> None:
        self.token = token
        self.base = f"{api_base.rstrip('/')}/bot{token}"

    def get_updates(self, offset: int, timeout: int) -> list[dict[str, Any]]:
        import httpx

        r = httpx.get(
            f"{self.base}/getUpdates",
            params={"offset": offset, "timeout": timeout},
            timeout=timeout + 10,
        )
        r.raise_for_status()
        return r.json().get("result") or []

    def send_message(self, chat_id: int, text: str) -> None:
        import httpx

        httpx.post(
            f"{self.base}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=30.0,
        ).raise_for_status()


class TelegramPoller:
    """Drives ``bridge.handle_update`` from a transport, sending replies back."""

    def __init__(self, bridge: TelegramBridge, transport: Transport, *, timeout: int = 25) -> None:
        self.bridge = bridge
        self.transport = transport
        self.timeout = timeout
        self.offset = 0

    def run_once(self) -> int:
        """Process one batch of updates. Returns the number handled."""
        updates = self.transport.get_updates(self.offset, self.timeout)
        for update in updates:
            self.offset = max(self.offset, int(update.get("update_id", 0)) + 1)
            reply = self.bridge.handle_update(update)
            if reply:
                self.transport.send_message(reply["chat_id"], reply["text"])
        return len(updates)

    def run(self) -> None:  # pragma: no cover — infinite loop
        while True:
            try:
                self.run_once()
            except Exception as exc:  # noqa: BLE001 — keep the bot alive
                print(f"[domain-foundry-telegram] poll error: {exc}")


def main() -> None:
    """Console entry point. Requires TELEGRAM_BOT_TOKEN."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is required. Create a bot with @BotFather, then:\n"
            "  export TELEGRAM_BOT_TOKEN=123456:ABC...\n"
            "  export DOMAIN_FOUNDRY_HOME=~/.domain_foundry   # optional\n"
            "  export TELEGRAM_ALLOWED_CHAT_IDS=<your chat id> # optional, keeps it private\n"
            "  domain-foundry-telegram"
        )
    home = os.environ.get("DOMAIN_FOUNDRY_HOME")
    api_base = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org")
    allowed_raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    allowed = {int(x) for x in allowed_raw.replace(",", " ").split() if x} or None

    bridge = TelegramBridge(home, allowed_chat_ids=allowed)
    poller = TelegramPoller(bridge, HttpxTransport(token, api_base))
    print("[domain-foundry-telegram] polling… (Ctrl-C to stop)")
    poller.run()


if __name__ == "__main__":
    main()
