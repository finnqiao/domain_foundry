"""Telegram ⇄ Domain Foundry bridge.

Text a Telegram bot; the message is captured-first into your local ledger and
routed to a typed domain record — the same harness the CLI and MCP server drive.
Corrections ("that Charizard was LP not NM") amend the canonical record and
become regression tests. Everything stays in local SQLite; the only network hop
is to Telegram's own API to receive/send messages.

The message-handling logic (:meth:`TelegramBridge.handle_update`) is pure and
transport-free, so it is proven offline against a mock Telegram API in
``tests/test_telegram_bridge.py``. :class:`TelegramPoller` layers the real
long-poll loop on top.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Correction cues → route to correct() instead of capture(). Mirrors the router's
# own correction detector so "just text it" behaves the same as the CLI.
_CORRECTION_RE = re.compile(
    r"\b(no,?\s+that|actually|undo|should (?:be|have been)|not\s+\w+|wrong|correct(?:ion)?)\b",
    re.IGNORECASE,
)

HELP_TEXT = (
    "🗒️ *Domain Foundry*\n"
    "Just text me and I'll remember it as structured, permanent data.\n\n"
    "• send any note → I capture + file it\n"
    "• `/new i collect pokemon cards` → create a domain\n"
    "• `/query pokemon` → show recent records\n"
    "• `/review` → things I wasn't sure about\n"
    "• `that Charizard was LP not NM` → I correct the last record\n"
)


class TelegramBridge:
    """Turns Telegram messages into harness operations and friendly replies."""

    def __init__(
        self,
        home: Path | str | None = None,
        *,
        allowed_chat_ids: set[int] | None = None,
        api: Any | None = None,
    ) -> None:
        # ``api`` injection keeps the handler unit-testable without a real home.
        if api is not None:
            self.api = api
        else:
            from domain_foundry_core.api.harness import HarnessAPI
            from domain_foundry_core.paths import Workspace

            home_path = Path(home).expanduser() if home is not None else None
            Workspace(home_path).ensure_layout()
            self.api = HarnessAPI(home_path)
            self.api.init()
        # None/empty = open (single-user machine). A set = allowlist (private).
        self.allowed_chat_ids = allowed_chat_ids or set()
        self._wizard: dict[int, str] = {}

    # ------------------------------------------------------------------ routing
    def handle_update(self, update: dict[str, Any]) -> dict[str, Any] | None:
        """Map one Telegram update to a reply. Returns ``{chat_id, text}`` or None."""
        message = update.get("message") or update.get("edited_message")
        if not message:
            return None
        chat_id = (message.get("chat") or {}).get("id")
        text = (message.get("text") or "").strip()
        if chat_id is None or not text:
            return None
        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            return {"chat_id": chat_id, "text": "🔒 This bot is private."}

        source_ref = f"telegram:{chat_id}:{message.get('message_id')}"
        reply = self._dispatch(text, source_ref=source_ref, chat_id=int(chat_id))
        return {"chat_id": chat_id, "text": reply}

    def _dispatch(self, text: str, *, source_ref: str, chat_id: int) -> str:
        if text.startswith("/"):
            return self._command(text, chat_id=chat_id)
        if chat_id in self._wizard:
            return self._wizard_continue(chat_id, text)
        if _CORRECTION_RE.search(text):
            return self._correct(text)
        return self._capture(text, source_ref=source_ref)

    def _command(self, text: str, *, chat_id: int) -> str:
        cmd, _, rest = text.partition(" ")
        cmd = cmd.lstrip("/").lower()
        rest = rest.strip()
        if cmd in {"start", "help"}:
            return HELP_TEXT
        if cmd == "new":
            if not rest:
                return "Tell me what to track, e.g. `/new track my coffee brews`"
            return self._new_domain(rest, chat_id=chat_id)
        if cmd == "query":
            return self._query(rest or None)
        if cmd == "review":
            return self._review()
        if cmd == "correct":
            return self._correct(rest) if rest else "Send `/correct <what to fix>`"
        return f"Unknown command /{cmd}. Try /help."

    # --------------------------------------------------------------- operations
    def _capture(self, text: str, *, source_ref: str) -> str:
        receipt = self.api.capture(text, channel="telegram", source_ref=source_ref)
        self._drain()
        data = receipt.model_dump()
        routed = (data.get("routed") or [{}])[0]
        domain = routed.get("domain")
        status = data.get("status")
        if status == "applied" and domain and domain != "_unfiled":
            return f"✅ Logged to *{domain}* ({routed.get('object_type')})."
        if status == "review":
            return f"🔎 Saved to *{domain}* for your review (I wasn't fully sure)."
        if domain == "_unfiled" or status == "unfiled":
            return "📝 Kept as an unfiled note — send /new to teach me this domain."
        return f"✅ Captured ({status})."

    def _correct(self, text: str) -> str:
        result = self.api.correct(text=text, channel="telegram")
        self._drain()
        if result.get("error"):
            return f"⚠️ Couldn't apply that correction: {result['error']}"
        return "✏️ Corrected — and saved as a regression test."

    def _new_domain(self, goal: str, *, chat_id: int) -> str:
        turn = self.api.new_domain(goal)
        sid = turn.get("session_id")
        if not sid:
            return "Couldn't start that domain — try rephrasing the goal."
        self._wizard[chat_id] = sid
        message = turn.get("message") or "Pick an idea, or describe the look you want."
        return (
            f"{message}\n\n"
            "Reply with a number, an idea name, or describe the look "
            "(chart, photos, a field guide). I won't skip ahead."
        )

    def _wizard_continue(self, chat_id: int, text: str) -> str:
        sid = self._wizard.get(chat_id)
        if not sid:
            return "No open domain conversation — send /new to start one."
        turn = self.api.wizard_reply(sid, text)
        state = turn.get("state")
        if state in {"test_drive", "repair", "done", "failed"}:
            self._wizard.pop(chat_id, None)
        domain = turn.get("domain")
        if state == "looks":
            return turn.get("message") or (
                "Here are the looks. Reply with a number, describe a change, or say `build it`."
            )
        if state in {"test_drive", "repair"} and domain:
            ready = f"🎉 *{domain}* is ready. Send me sample notes and I'll file them."
            # The held-out replay is the one honest measurement of the build.
            # Swallowing it here would leave Telegram the only channel that
            # claims success without showing the check that produced it.
            held_out = turn.get("held_out")
            if isinstance(held_out, dict):
                verdict = "filed" if held_out.get("filed") else "did not file"
                ready += f"\n\nHeld-out check: “{held_out.get('text')}” {verdict}."
            return ready
        return turn.get("message") or "Got it."

    def _query(self, domain: str | None) -> str:
        rows = self.api.query(domain=domain, limit=5)
        if not rows:
            return f"No records yet in *{domain}*." if domain else "No records yet."
        lines = [f"📚 *{domain or 'recent'}* — {len(rows)} shown:"]
        for r in rows:
            d = r.model_dump()
            lines.append(f"• {(d.get('title') or d.get('raw_text') or '')[:70]}")
        return "\n".join(lines)

    def _review(self) -> str:
        items = self.api.review_list(status="pending")
        if not items:
            return "✅ Nothing waiting for review."
        lines = [f"🔎 {len(items)} pending:"]
        for it in items[:5]:
            lines.append(f"• {str(it.get('summary') or it.get('id'))[:70]}")
        return "\n".join(lines)

    def _drain(self) -> None:
        try:
            self.api.drain_projections()
        except Exception:  # noqa: BLE001 — canonical commit already durable
            pass
