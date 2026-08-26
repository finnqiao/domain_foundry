"""Parse atlas-browse replies: navigate, commit ideas, simple log, schema."""

from __future__ import annotations

import re
from pathlib import Path
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

# Job words a person actually says. Matched against the current neighborhood
# before any atlas rematch — so "visualize my bakes" stays on a bake lab.
JOB_HINTS: dict[str, tuple[str, ...]] = {
    "improvement": (
        "visualize",
        "visualise",
        "chart",
        "plot",
        "graph",
        "trend",
        "scatter",
        "compare",
        "dashboard",
        "data vis",
        "dataviz",
    ),
    "media_dex": (
        "photo",
        "photos",
        "instagram",
        "gallery",
        "picture",
        "image",
        "album",
        "media",
    ),
    "lab": ("mix", "formula", "starter", "experiment", "hydration", "keepers"),
    "catalog": (
        "catalog",
        "catalogue",
        "collection",
        "pokedex",
        "dex",
        "remember",
        "identify",
        "field guide",
        "field-guide",
        "fieldguide",
    ),
    "atlas": ("map", "where", "location", "site", "places", "pin"),
    "event_log": ("timeline", "journal", "diary", "log of"),
}

JOB_PITCH: dict[str, str] = {
    "improvement": "chart how inputs lead to outcomes",
    "media_dex": "a gallery of the photos",
    "lab": "a mix board of what worked",
    "catalog": "a catalog you can page through",
    "atlas": "a map of where it happened",
    "event_log": "a timeline of what you logged",
    "practice": "a practice board you can return to",
    "graph": "how the pieces link",
    "plan": "a plan you can talk to",
}

STAY_THRESHOLD = 6
_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9']{1,}")
_STOP = frozenset(
    """
    a an the and or of to for my i we you want track keep log journal
    about with from into on in is it this that something build create
    make get app remember see if ive all just have has had
    """.split()
)


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

    # Numeric picks: "1", "1 and 3" — not folder paths that happen to contain digits.
    if "/" in raw or raw.startswith("~"):
        numbers = []
    else:
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
            if len(n) >= 4 and n in low:
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
            if len(n) >= 4 and n in low:
                score = len(n)
                if best is None or score > best[0]:
                    best = (score, card["id"])
    return best[1] if best else None


def hinted_jobs(text: str) -> list[str]:
    """Jobs implied by a free-text reply (visualize → improvement, etc.)."""
    low = (text or "").lower()
    return [job for job, needles in JOB_HINTS.items() if any(n in low for n in needles)]


def job_pitches(jobs: list[str] | None) -> str:
    bits = [JOB_PITCH[j] for j in (jobs or []) if j in JOB_PITCH]
    return " · ".join(bits)


def stay_idea_ids(text: str, neighborhood: dict[str, Any], *, limit: int = 3) -> list[str]:
    """Idea ids in the current neighborhood that this reply is still about."""
    ranked = rank_ideas_in_neighborhood(text, neighborhood)
    if not ranked or ranked[0][0] < STAY_THRESHOLD:
        return []
    best = ranked[0][0]
    picked: list[str] = []
    for score, idea in ranked:
        if score < STAY_THRESHOLD or score < best - 4:
            break
        iid = idea.get("id")
        if iid:
            picked.append(str(iid))
        if len(picked) >= limit:
            break
    return picked


def rank_ideas_in_neighborhood(
    text: str, neighborhood: dict[str, Any]
) -> list[tuple[int, dict[str, Any]]]:
    jobs = set(hinted_jobs(text))
    tokens = {t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOP and len(t) >= 3}
    low = (text or "").lower()
    ranked: list[tuple[int, dict[str, Any]]] = []
    for idea in neighborhood.get("ideas") or []:
        score = _score_idea_card(idea, tokens, low, jobs)
        ranked.append((score, idea))
    ranked.sort(key=lambda pair: (-pair[0], pair[1].get("id") or ""))
    return ranked


def _score_idea_card(
    idea: dict[str, Any],
    tokens: set[str],
    low: str,
    jobs: set[str],
) -> int:
    score = 0
    idea_jobs = set(idea.get("jobs") or [])
    score += 8 * len(jobs & idea_jobs)
    needles = [idea.get("title") or "", idea.get("id") or "", idea.get("pitch") or ""]
    needles.extend(idea.get("aliases") or [])
    needles.extend(idea.get("jargon") or [])
    if idea.get("id"):
        needles.append(str(idea["id"]).split(".")[-1].replace("_", " "))
    bag: set[str] = set()
    for needle in needles:
        n = (needle or "").lower()
        if len(n) >= 4 and n in low:
            score += 6
        bag.update(t for t in _TOKEN_RE.findall(n) if len(t) >= 3)
    for token in tokens:
        if token in bag:
            score += 3
        elif any(token in t or t in token for t in bag if len(t) >= 4):
            score += 1
    return score


def neighborhood_bucket(neighborhood: dict[str, Any]) -> str | None:
    crumb = neighborhood.get("breadcrumb") or []
    if crumb:
        return crumb[0].get("id")
    return neighborhood.get("cursor")


def existing_ingest_path(text: str) -> Path | None:
    """Return a real file/folder path if the reply is pointing at one."""
    raw = (text or "").strip().strip("\"'")
    if not raw:
        return None
    raw = raw.split("\n", 1)[0].strip().strip("\"'")
    looks_like = raw.startswith("~") or raw.startswith("/") or raw.startswith("./") or "/" in raw
    if not looks_like:
        return None
    # Don't treat "Food → Fermentation" style crumbs as paths.
    if "→" in raw or "->" in raw:
        return None
    try:
        path = Path(raw).expanduser()
    except (OSError, ValueError):
        return None
    try:
        if path.exists() and (path.is_file() or path.is_dir()):
            return path
    except OSError:
        return None
    return None
