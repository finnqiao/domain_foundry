"""Match a goal sentence to an atlas neighborhood (refine / expand / ideas)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from domain_foundry_core.atlas.loader import load_atlas
from domain_foundry_core.atlas.models import AtlasGraph, AtlasNode

_STOP = frozenset(
    """
    a an the and or of to for my i we you want track keep log journal
    a n about with from into on in is it this that something build
    create make get an app remember see if ive i've i'd im i'm
    collect collects collected collecting collector collectors
    note notes play plays played playing game games
    practice practices practicing
    home brew brewing board boards project projects finish finished
    maintenance care service history parts training session sessions
    collection collections list lists build builds built
    """.split()
)
# The last two lines are the same idea as "log" and "journal": words for the act
# of recording or doing, not for any subject. They ride into node vocabulary on
# multi-word names ("Dev notes", "where we play", "Instrument practice") and then
# answer for whisky, vinyl, and yoga. A node has to be named by its own word.
_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9']{1,}")
_CAMEL_SPLIT = re.compile(r"(?<=[a-z])(?=[A-Z])")


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for w in _WORD_RE.findall(text or ""):
        cleaned = w.replace("'", "")
        pieces = _CAMEL_SPLIT.split(cleaned) or [cleaned]
        out.append(cleaned.lower())
        if len(pieces) > 1:
            out.extend(p.lower() for p in pieces if p)
    return out


def _content_tokens(text: str) -> set[str]:
    return {t for t in tokenize(text) if t not in _STOP and len(t) >= 3}


def _term_lexicon(graph: AtlasGraph) -> set[str]:
    lexicon: set[str] = set()
    for node in graph.nodes.values():
        for term in node.vocab_terms():
            if " " in term.strip():
                continue
            lexicon.update(_content_tokens(term))
            compact = term.lower().replace("'", "")
            if compact.isalpha() and len(compact) >= 3 and compact not in _STOP:
                lexicon.add(compact)
    return lexicon


def _expand_compounds(tokens: set[str], lexicon: set[str]) -> set[str]:
    """Keep the original token and split camel-free compounds (birdwatching → bird + watching)."""
    extra: set[str] = set()
    for token in tokens:
        if len(token) < 8:
            continue
        for i in range(3, len(token) - 2):
            left, right = token[:i], token[i:]
            if left in lexicon or right in lexicon:
                extra.add(left)
                extra.add(right)
    return tokens | extra


def _goal_tokens(graph: AtlasGraph, goal: str) -> set[str]:
    return _expand_compounds(_content_tokens(goal), _term_lexicon(graph))


def _node_terms(node: AtlasNode) -> set[str]:
    """The scoring bag: title, aliases, single-word jargon, domain slug.

    Never ids or id segments — see ``AtlasNode.vocab_terms``.
    """
    bag: set[str] = set()
    for term in node.vocab_terms():
        bag.add(term.lower().replace(" ", ""))
        bag.update(_content_tokens(term))
    return bag


@dataclass(frozen=True)
class ScoreDetail:
    """Why a node scored, kept separate so evidence and ranking do not blur.

    ``exact`` and ``alias`` are the node's own words showing up in the goal.
    ``weak`` (a prefix overlap) and ``kind_bonus`` are tie-breakers: they order
    candidates that already earned their place, and nothing else.
    """

    exact: int = 0
    weak: int = 0
    alias: int = 0
    kind_bonus: int = 0

    @property
    def strong(self) -> bool:
        """True when the node was actually named, not merely resembled."""
        return self.alias > 0 or self.exact > 0

    @property
    def total(self) -> int:
        base = self.exact + self.weak + self.alias
        return base + self.kind_bonus if base > 0 else 0


def score_node_detail(node: AtlasNode, tokens: set[str], raw: str) -> ScoreDetail:
    if not tokens:
        return ScoreDetail()
    terms = _node_terms(node)
    exact = 0
    weak = 0
    for token in tokens:
        if token in terms:
            exact += 3
        elif len(token) >= 5 and any(
            t.startswith(token) or token.startswith(t) for t in terms if len(t) >= 4
        ):
            # Prefix-only, and only for long tokens: "freediv" ~ "freediving" is a
            # real family, "ink" inside "drinks" is a coincidence.
            weak += 1
    low = (raw or "").lower()
    phrases = list(node.aliases) + [node.title]
    phrases.extend(j for j in (node.jargon or []) if " " in j)
    alias = 0
    for phrase in phrases:
        phrase_l = phrase.lower()
        # A phrase must be a real word/phrase in the goal.  Substring matching
        # makes "brew" claim "homebrew", and lets generic node labels such as
        # "home", "training", or "collection" beat an unknown subject.
        if len(phrase_l) >= 4 and _content_tokens(phrase_l) and re.search(
            rf"(?<![a-zA-Z0-9]){re.escape(phrase_l)}(?![a-zA-Z0-9])", low
        ):
            alias += 6
    if exact + weak + alias <= 0:
        return ScoreDetail()
    kind_bonus = 1 if node.kind == "idea" else 2 if node.kind == "practice" else 0
    return ScoreDetail(exact=exact, weak=weak, alias=alias, kind_bonus=kind_bonus)


def score_node(node: AtlasNode, tokens: set[str], raw: str) -> int:
    return score_node_detail(node, tokens, raw).total


def _best_node(graph: AtlasGraph, goal: str) -> AtlasNode | None:
    tokens = _goal_tokens(graph, goal)
    if not tokens:
        return None
    scored = [(score_node_detail(n, tokens, goal), n) for n in graph.nodes.values()]
    # Evidence floor: a resemblance is not a neighborhood. Without the node's own
    # words in the goal there is no honest answer, and None is the honest answer.
    eligible = [pair for pair in scored if pair[0].strong]
    if not eligible:
        return None
    ranked = sorted(
        eligible,
        key=lambda pair: (-pair[0].total, pair[1].kind != "practice", pair[1].id),
    )
    best = ranked[0][1]
    # Prefer the practice/bucket parent when an idea wins so refine/expand work.
    if best.kind == "idea":
        parents = graph.parents(best.id)
        if parents:
            return parents[0]
    return best


def _flagship_ideas(graph: AtlasGraph, cursor: AtlasNode, *, limit: int = 8) -> list[AtlasNode]:
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
    seen: set[str] = set()
    world_first = [i for i in ideas if i.provenance in {"world", "both"}]
    foundry = [i for i in ideas if i.provenance == "foundry"]
    rest = [i for i in ideas if i not in world_first and i not in foundry]
    ordered: list[AtlasNode] = []

    def _take(node: AtlasNode) -> None:
        if node.id not in seen:
            seen.add(node.id)
            ordered.append(node)

    # Interleave world/foundry so a crowded bucket still shows both.
    i = j = 0
    while len(ordered) < limit and (i < len(world_first) or j < len(foundry)):
        if i < len(world_first):
            _take(world_first[i])
            i += 1
        if len(ordered) >= limit:
            break
        if j < len(foundry):
            _take(foundry[j])
            j += 1
    for node in rest:
        if len(ordered) >= limit:
            break
        _take(node)
    return ordered[:limit]


def _highlight_ids(ideas: list[AtlasNode], goal: str, graph: AtlasGraph | None = None) -> set[str]:
    tokens = _goal_tokens(graph, goal) if graph is not None else _content_tokens(goal)
    low = (goal or "").lower()
    hits: set[str] = set()
    details: dict[str, ScoreDetail] = {}
    for idea in ideas:
        details[idea.id] = score_node_detail(idea, tokens, goal)
        if any(a.lower() in low for a in idea.aliases + [idea.title] if len(a) >= 4):
            hits.add(idea.id)
    if hits:
        return hits
    # Same evidence floor as _best_node: a weak-substring plus kind-bonus pile
    # used to clear 4 and get itself marked "(suggested)".
    strong = {i.id: details[i.id] for i in ideas if details[i.id].strong}
    if not strong:
        return set()
    best = max(d.total for d in strong.values())
    if best < 4:
        return set()
    return {iid for iid, d in strong.items() if d.total == best}


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
    highlighted = _highlight_ids(ideas, goal, graph)
    # Display order is the single source of truth for the fork: the suggested
    # idea is literally #1, so "1", "yes" and "(suggested)" build the same pack.
    ideas = sorted(ideas, key=lambda i: i.id not in highlighted)
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
