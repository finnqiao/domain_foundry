"""Parse atlas-browse replies: navigate, commit ideas, simple log, schema."""

from __future__ import annotations

import re
from typing import Any, Literal

IntentKind = Literal[
    "navigate",
    "commit",
    "simple_log",
    "show_schema",
    "something_else",
    "skip",
    "cancel",
    "unknown",
]


def parse_fork_reply(text: str, neighborhood: dict[str, Any]) -> dict[str, Any]:
    """Return ``{kind, node_id?, idea_ids?}`` from a browse reply."""
    raw = (text or "").strip()
    low = raw.lower()
    if not raw:
        return {"kind": "unknown"}
    if re.search(r"\b(cancel|nevermind|never mind|stop)\b", low):
        return {"kind": "cancel"}
    if re.search(r"\bsomething else\b", low):
        return {"kind": "something_else"}
    if re.search(r"\bshow schema\b|\binspect\b|\bpreview schema\b", low):
        picked = _match_ideas(raw, neighborhood)
        return {"kind": "show_schema", "idea_ids": picked or _highlighted(neighborhood)}
    if re.search(r"\bjust a simple log\b|\bsimple log\b|\bkeep(?:\s+it)? as a scaffold\b", low):
        return {"kind": "simple_log"}
    if re.fullmatch(r"skip(?:\s+(?:it|questions?|defaults?))?", low) or low in {
        "yes",
        "y",
        "ok",
        "okay",
        "go",
        "go ahead",
        "looks good",
        "do it",
        "confirm",
    }:
        return {"kind": "skip"}

    # Numeric picks: "1", "1 and 3"
    numbers = [int(n) for n in re.findall(r"\b(\d+)\b", raw)]
    ideas = list(neighborhood.get("ideas") or [])
    if numbers and ideas:
        ids = []
        for n in numbers:
            if 1 <= n <= len(ideas):
                ids.append(ideas[n - 1]["id"])
        if ids:
            return {"kind": "commit", "idea_ids": list(dict.fromkeys(ids))}

    nav = _match_nav(raw, neighborhood)
    picked = _match_ideas(raw, neighborhood)
    if picked and not nav:
        return {"kind": "commit", "idea_ids": picked}
    if nav and not picked:
        return {"kind": "navigate", "node_id": nav}
    if picked and nav:
        # Prefer idea commit when both match ("recipe lab" vs "cooking").
        return {"kind": "commit", "idea_ids": picked}
    return {"kind": "unknown"}


def _highlighted(neighborhood: dict[str, Any]) -> list[str]:
    return [i["id"] for i in neighborhood.get("ideas") or [] if i.get("highlighted")]


def _match_ideas(text: str, neighborhood: dict[str, Any]) -> list[str]:
    low = text.lower()
    hits: list[str] = []
    for idea in neighborhood.get("ideas") or []:
        needles = [idea.get("title") or "", idea.get("id") or ""]
        needles.extend(idea.get("aliases") or [])
        if idea.get("id"):
            needles.append(str(idea["id"]).split(".")[-1].replace("_", " "))
        for needle in needles:
            n = needle.lower()
            if len(n) >= 3 and n in low:
                hits.append(idea["id"])
                break
    return list(dict.fromkeys(hits))


def _match_nav(text: str, neighborhood: dict[str, Any]) -> str | None:
    low = text.lower()
    cards = (
        list(neighborhood.get("refine") or [])
        + list(neighborhood.get("expand") or [])
        + list(neighborhood.get("breadcrumb") or [])
    )
    best: tuple[int, str] | None = None
    for card in cards:
        needles = [card.get("title") or "", card.get("id") or ""]
        needles.extend(card.get("aliases") or [])
        if card.get("id"):
            needles.append(str(card["id"]).split(".")[-1].replace("_", " "))
        for needle in needles:
            n = needle.lower()
            if len(n) >= 3 and n in low:
                score = len(n)
                if best is None or score > best[0]:
                    best = (score, card["id"])
    return best[1] if best else None
