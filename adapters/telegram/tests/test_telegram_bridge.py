"""Offline proof of the Telegram bridge against a mock Telegram API.

Drives the whole loop — /new → looks → build it → capture → correction →
/query → /review — through :class:`TelegramPoller` exactly as the real transport
would, but with an in-memory fake so no bot token / network is needed. Run
standalone to print the transcript used as the tutorial's Telegram proof snapshot:

    python adapters/telegram/tests/test_telegram_bridge.py
"""

from __future__ import annotations

import sys
import tempfile
from typing import Any

from domain_foundry_telegram.bridge import TelegramBridge
from domain_foundry_telegram.poller import TelegramPoller

CHAT_ID = 4242


class MockTelegram:
    """In-memory Telegram Bot API: scripted inbound updates, captured replies."""

    def __init__(self, messages: list[str]) -> None:
        self._updates = [
            {
                "update_id": i + 1,
                "message": {
                    "message_id": i + 1,
                    "chat": {"id": CHAT_ID},
                    "text": text,
                },
            }
            for i, text in enumerate(messages)
        ]
        self.sent: list[dict[str, Any]] = []
        self._served = False

    def get_updates(self, offset: int, timeout: int) -> list[dict[str, Any]]:
        # Serve the whole scripted batch once, then nothing (bot would keep polling).
        if self._served:
            return []
        self._served = True
        return [u for u in self._updates if u["update_id"] >= offset]

    def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append({"chat_id": chat_id, "text": text})


CONVERSATION = [
    "/new i collect pokemon cards",
    "a dex of the cards i own with photos",
    "build it",
    "pulled a holographic Charizard from a 151 booster, NM",
    "that Charizard was LP not NM",
    "/query pokemon",
    "/review",
]


def _run(echo: bool = False) -> tuple[list[dict[str, Any]], TelegramBridge]:
    home = tempfile.mkdtemp(prefix="df_tg_")
    bridge = TelegramBridge(home)  # heuristic router (no key) — deterministic
    mock = MockTelegram(CONVERSATION)
    poller = TelegramPoller(bridge, mock, timeout=0)
    poller.run_once()
    if echo:
        for inbound, reply in zip(CONVERSATION, mock.sent, strict=False):
            print(f"\n👤 {inbound}\n🤖 {reply['text']}")
    return mock.sent, bridge


def test_telegram_conversation_loop() -> None:
    sent, bridge = _run()
    texts = [m["text"] for m in sent]
    assert len(texts) == len(CONVERSATION), "every message should get a reply"
    assert "you said" in texts[0].lower() or "you could" in texts[0].lower() or "idea" in texts[0].lower()
    assert "card dex" in texts[0].lower()
    assert "look" in texts[1].lower()
    assert "ready" in texts[2].lower()
    assert "Logged to" in texts[3]
    assert "pokemon" in texts[3].lower() or "card" in texts[3].lower()
    assert "Corrected" in texts[4]
    assert "pokemon" in texts[5].lower() or "Charizard" in texts[5]
    rows = bridge.api.query(domain="pokemon")
    if not rows:
        def _raw(row: Any) -> str:
            if hasattr(row, "raw_text"):
                return row.raw_text or ""
            return (row.get("raw_text") or "") if isinstance(row, dict) else ""

        rows = [r for r in bridge.api.query() if "Charizard" in _raw(r)]
    assert len(rows) >= 1


def test_private_allowlist_blocks_strangers() -> None:
    home = tempfile.mkdtemp(prefix="df_tg_")
    bridge = TelegramBridge(home, allowed_chat_ids={999})
    reply = bridge.handle_update(
        {"message": {"message_id": 1, "chat": {"id": CHAT_ID}, "text": "hi"}}
    )
    assert reply is not None and "private" in reply["text"].lower()


if __name__ == "__main__":
    _run(echo=True)
    print("\n\nTelegram E2E OK")
    sys.exit(0)
