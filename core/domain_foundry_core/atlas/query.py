"""Match a goal sentence to an atlas neighborhood (refine / expand / ideas)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from domain_foundry_core.atlas.loader import load_atlas
from domain_foundry_core.atlas.models import AtlasGraph, AtlasNode

_STOP = frozenset(
    """
    a an the and or of to for my i we you want track keep log journal
    a n about with from into on in is it this that something build
    create make get an app remember see if ive i've i'd im i'm
    """.split()
)
_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9']{1,}")


def tokenize(text: str) -> list[str]:
    return [w.lower().replace("'", "") for w in _WORD_RE.findall(text or "") if w]


def _content_tokens(text: str) -> set[str]:
    return {t for t in tokenize(text) if t not in _STOP and len(t) >= 3}


def _node_terms(node: AtlasNode) -> set[str]:
    bag: set[str] = set()
    for term in node.terms():
        bag.update(_content_tokens(term))
        bag.add(term.lower().replace(" ", ""))
    return bag


def score_node(node: AtlasNode, tokens: set[str], raw: str) -> int:
    if not tokens:
        return 0
    terms = _node_terms(node)
    score = 0
    for token in tokens:
        if token in terms:
            score += 3
        elif any(token in t or t in token for t in terms if len(t) >= 4):
            score += 1
    low = (raw or "").lower()
    for alias in node.aliases + [node.title]:
        alias_l = alias.lower()
        if len(alias_l) >= 4 and alias_l in low:
            score += 6
    if node.kind == "idea":
        score += 1
    elif node.kind == "practice":
        score += 2
    return score


def _best_node(graph: AtlasGraph, goal: str) -> AtlasNode | None:
    tokens = _content_tokens(goal)
    if not tokens:
        return None
    ranked = sorted(
        ((score_node(n, tokens, goal), n) for n in graph.nodes.values()),
        key=lambda pair: (-pair[0], pair[1].kind != "practice", pair[1].id),
    )
    best_score, best = ranked[0]
    if best_score <= 0:
        return None
    # Prefer the practice/bucket parent when an idea wins so refine/expand work.
    if best.kind == "idea":
        parents = graph.parents(best.id)
        if parents:
            return parents[0]
    return best


def _flagship_ideas(graph: AtlasGraph, cursor: AtlasNode, *, limit: int = 6) -> list[AtlasNode]:
    ideas = list(graph.ideas_at(cursor.id))
    if cursor.kind == "bucket":
        for practice in graph.practices_at(cursor.id):
            ideas.extend(graph.ideas_at(practice.id))
    # Horizon ideas (expands_to) belong on the idea list, not only as chips.
    extra: list[AtlasNode] = []
    for node in graph.expands_to(cursor.id):
        if node.kind == "idea":
            extra.append(node)
    for idea in list(ideas):
        for node in graph.expands_to(idea.id):
            if node.kind == "idea":
                extra.append(node)
    ideas.extend(extra)
    # De-dupe, keep world/foundry mix.
    seen: set[str] = set()
    ordered: list[AtlasNode] = []
    world_first = [i for i in ideas if i.provenance in {"world", "both"}]
    foundry = [i for i in ideas if i.provenance == "foundry"]
    rest = [i for i in ideas if i not in world_first and i not in foundry]
    for group in (world_first, foundry, rest):
        for idea in group:
            if idea.id not in seen:
                seen.add(idea.id)
                ordered.append(idea)
    return ordered[:limit]


def _highlight_ids(ideas: list[AtlasNode], goal: str) -> set[str]:
    tokens = _content_tokens(goal)
    low = (goal or "").lower()
    hits: set[str] = set()
    best = 0
    scores: dict[str, int] = {}
    for idea in ideas:
        sc = score_node(idea, tokens, goal)
        scores[idea.id] = sc
        best = max(best, sc)
        if any(a.lower() in low for a in idea.aliases + [idea.title] if len(a) >= 4):
            hits.add(idea.id)
    if hits:
        return hits
    if best >= 4:
        return {i.id for i in ideas if scores[i.id] == best}
    return set()


def neighborhood_for(
    graph: AtlasGraph,
    goal: str,
    *,
    cursor_id: str | None = None,
) -> dict[str, Any]:
    cursor = graph.get(cursor_id) if cursor_id else None
    if cursor is None:
        cursor = _best_node(graph, goal)
    if cursor is None:
        # Unindexed leaf: show buckets as refine.
        buckets = graph.buckets()[:12]
        return {
            "cursor": None,
            "breadcrumb": [],
            "refine": [graph.to_card(b) for b in buckets],
            "expand": [],
            "ideas": [],
            "simple_log": True,
            "unindexed": True,
        }

    refine_nodes = [n for n in graph.children(cursor.id) if n.kind != "idea"]
    expand_nodes: list[tuple[str, AtlasNode]] = []
    for node in graph.adjacent(cursor.id):
        expand_nodes.append(("adjacent", node))
    for node in graph.expands_to(cursor.id):
        expand_nodes.append(("expands_to", node))
    if cursor.kind == "practice":
        for parent in graph.parents(cursor.id):
            for sib in graph.practices_at(parent.id):
                if sib.id != cursor.id:
                    expand_nodes.append(("adjacent", sib))

    seen_expand: set[str] = set()
    expand_cards: list[dict[str, Any]] = []
    for why, node in expand_nodes:
        if node.id in seen_expand or node.id == cursor.id:
            continue
        seen_expand.add(node.id)
        card = graph.to_card(node)
        card["why"] = why
        expand_cards.append(card)

    ideas = _flagship_ideas(graph, cursor)
    highlighted = _highlight_ids(ideas, goal)
    idea_cards = [graph.to_card(i, highlighted=i.id in highlighted) for i in ideas]

    return {
        "cursor": cursor.id,
        "breadcrumb": [
            {"id": n.id, "title": n.title, "kind": n.kind} for n in graph.breadcrumb(cursor.id)
        ],
        "refine": [graph.to_card(n) for n in refine_nodes],
        "expand": expand_cards[:8],
        "ideas": idea_cards,
        "simple_log": True,
        "unindexed": False,
    }


def query_neighborhood(
    goal: str,
    *,
    overlay: Path | None = None,
    cursor_id: str | None = None,
) -> dict[str, Any]:
    graph = load_atlas(overlay)
    return neighborhood_for(graph, goal, cursor_id=cursor_id)
