"""Plain-language receipts for CLI / Telegram (mirrors app/src/lib/receipts.ts)."""

from __future__ import annotations

from typing import Any


def describe_capture_receipt(receipt: Any, *, pack_titles: dict[str, str] | None = None) -> str:
    """One-line human summary of a CaptureReceipt-like object."""
    titles = pack_titles or {}
    status = getattr(receipt, "status", None) or (
        receipt.get("status") if isinstance(receipt, dict) else None
    )
    routed = getattr(receipt, "routed", None)
    if routed is None and isinstance(receipt, dict):
        routed = receipt.get("routed") or []
    real = []
    for span in routed or []:
        domain = getattr(span, "domain", None) or (
            span.get("domain") if isinstance(span, dict) else None
        )
        if domain and domain not in {"_unfiled", "_ledger"}:
            real.append(span)
    if status == "applied" and len(real) == 1:
        span = real[0]
        domain = getattr(span, "domain", None) or span.get("domain")
        otype = getattr(span, "object_type", None) or span.get("object_type") or "entry"
        human = str(otype).replace("_", " ")
        title = titles.get(str(domain), str(domain))
        article = "an" if human[:1].lower() in "aeiou" else "a"
        return f"Saved to {title} as {article} {human}"
    if status == "applied" and real:
        names = []
        for span in real:
            domain = getattr(span, "domain", None) or span.get("domain")
            names.append(titles.get(str(domain), str(domain)))
        uniq = [n for n in dict.fromkeys(names) if n]
        return f"Saved to {' and '.join(uniq)}" if uniq else "Saved to your journal"
    if status == "review":
        return "Saved for your review — I wasn't fully sure where it belongs."
    if status in {"unfiled", "ledger_only"}:
        return "Kept as unfiled — still saved, not guessed into a passion."
    return f"Captured ({status})."


def pack_install_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Hobby-facing pack install/activate summary — no mesh expert stub."""
    return {
        "name": result.get("name"),
        "title": result.get("title") or (result.get("pack") or {}).get("title"),
        "version": result.get("version"),
    }
