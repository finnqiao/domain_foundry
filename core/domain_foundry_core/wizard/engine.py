"""Wizard engine: the goal → working-domain state machine (plan §6).

Channel-agnostic and resumable. Both ``new_domain`` and ``wizard_reply`` on
``HarnessAPI`` delegate here, so chat, CLI, and the app shell drive the same
engine. Generation runs the real pack system end to end:
generate → ``pack validate`` → dry-run routing → activate → test-drive →
hardening.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from domain_foundry_core.atlas.loader import load_atlas
from domain_foundry_core.atlas.models import AtlasNode
from domain_foundry_core.atlas.query import _goal_tokens, query_neighborhood
from domain_foundry_core.clock import now_iso
from domain_foundry_core.config import load_llm_config
from domain_foundry_core.evals.runner import score_case
from domain_foundry_core.foundry.cost import LedgerCostMeter
from domain_foundry_core.foundry.models import evidence_tier_label
from domain_foundry_core.llm.provider import (
    CassetteProvider,
    HeuristicProvider,
    LLMProvider,
    build_tiered_provider,
    resolve_tier_settings,
)
from domain_foundry_core.packs.loader import PackValidationError, load_pack
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace
from domain_foundry_core.routing.router import Router
from domain_foundry_core.security.store import connect_ro
from domain_foundry_core.wizard import blueprint as bp
from domain_foundry_core.wizard.acceptance import (
    ACCEPTANCE_THRESHOLD,
    acceptance_run,
    load_suite,
    select_cases,
)
from domain_foundry_core.wizard.design import DesignError, LLMBlueprintDesigner
from domain_foundry_core.wizard.escalation import (
    REQUIRED_SAMPLES,
    BridgeRun,
    BridgeUnavailable,
    atlas_prior,
    persist_artifacts,
    run_bridge,
)
from domain_foundry_core.wizard.fork import (
    existing_ingest_path,
    hinted_jobs,
    job_pitches,
    neighborhood_bucket,
    parse_fork_reply,
    stay_idea_ids,
)
from domain_foundry_core.wizard.hardening import apply_plan, build_plan, looks_like_edit
from domain_foundry_core.wizard.jobs import compile_jobs, shortlist_for_ideas
from domain_foundry_core.wizard.looks import generate_look, hero_job, persist_look
from domain_foundry_core.wizard.models import validate_blueprint
from domain_foundry_core.wizard.release import release_turn
from domain_foundry_core.wizard.session import WizardSession, WizardSessionStore
from domain_foundry_core.wizard.shortlist import seed_terms

if TYPE_CHECKING:
    from domain_foundry_core.api.harness import HarnessAPI

_CONFIRM_RE = re.compile(r"\b(yes|yep|confirm|apply|do it|ok|okay|looks good|go ahead|continue|build(?:\s+it)?|ship)\b", re.IGNORECASE)
_CANCEL_RE = re.compile(r"\b(no|cancel|nevermind|never mind|stop|discard)\b", re.IGNORECASE)
_DONE_RE = re.compile(r"\b(done|finish(?:ed)?|that'?s all|all set|complete)\b", re.IGNORECASE)
# A sign-off is the *whole* utterance. Real domain sentences open with the same
# words — "finished the sleeve, blocking tonight", "finished The Left Hand of
# Darkness" — and a substring match ends the session and swallows the user's
# first real note. Anything carrying content is a note, not a goodbye.
_DONE_ONLY_RE = re.compile(
    r"""^\s*
    (?:(?:ok|okay|alright|great|cool|perfect|yes|yep|yeah|thanks|thank\s+you)\b[\s,.!]*)*
    (?:(?:i\s*am|i'?m|we\s*are|we'?re|that\s+is|that'?s|it\s+is|it'?s)\s+)?
    (?:all\s+)?
    (?:done|finished|finish|complete|completed|that'?s\s+all|all\s+set|no\s+more|nothing\s+else)
    (?:[\s,]+(?:for\s+(?:now|today)|here|now|with\s+(?:this|that|it)|thanks|thank\s+you|please))*
    [\s,.!]*$""",
    re.IGNORECASE | re.VERBOSE,
)
_KEEP_SCAFFOLD_RE = re.compile(r"\bkeep(?:\s+it)?\s+(?:as\s+)?a?\s*scaffold\b", re.IGNORECASE)
# Declining elicitation is the *whole* utterance. "no more than three bowls" is
# a log line; "skip" is a refusal. Anything carrying content is a sentence.
_ELICIT_SKIP_RE = re.compile(
    r"^\s*(?:skip(?:\s+(?:it|for\s+now))?|pass|no(?:\s+thanks)?|nah|none|nothing|dunno|not\s+sure|"
    r"i\s+don'?t\s+know)\s*[.!]?\s*$",
    re.IGNORECASE,
)
# Two sentences is the acceptance evidence (ADR-010): one shapes the design,
# one is held out and replayed through the real router after activation.
ELICIT_PROMPTS = 2
ELICIT_FIRST = (
    "I don't have this one catalogued, so I'll build it out of your words rather "
    "than guess. Say one thing you'd log, exactly how you'd type it. That "
    "becomes the first test of the app. (Or say 'skip'.)"
)
ELICIT_SECOND = (
    "And one more, a different kind of thing. I'll hold this one back, then replay "
    "it once the app exists, so the check is honest. (Or say 'skip'.)"
)


def is_session_signoff(text: str) -> bool:
    """True only for a bare sign-off, never for a sentence that carries content."""
    return bool(_DONE_ONLY_RE.match((text or "").strip()))
_CRITIQUE_RE = re.compile(
    r"\b(more|less|darker|lighter|denser|simpler|again|another|regenerate|too|make it|change|tweak|redo)\b",
    re.IGNORECASE,
)
_LOOK_PICK_RE = re.compile(
    r"\b(this one|that one|look\s*\d+|the scatter|scatter|chart|gallery|mix board|field[- ]?guide|map)\b",
    re.IGNORECASE,
)
MAX_LOOK_ROUNDS = 8

# Live pack view the accepted look's hero_job must bind to.
_HERO_REQUIRED_BLOCKS: dict[str, frozenset[str]] = {
    "media_dex": frozenset({"gallery"}),
    "atlas": frozenset({"map"}),
    "improvement": frozenset({"stats", "compare"}),
    "lab": frozenset({"list", "timeline"}),
    "catalog": frozenset({"search", "list", "gallery"}),
    "event_log": frozenset({"timeline"}),
}

DRY_RUN_THRESHOLD = 0.95
# ``DOMAIN_FOUNDRY_LLM`` values that mean "make no model calls". The bridge is
# the most expensive call in the product, so it honours the switch as well as
# the key: an install that asked for offline behaviour gets offline behaviour
# even on a machine that happens to have a key exported.
_LLM_OFF_MODES = frozenset({"off", "heuristic", "0", "false"})
MAX_REGEN_ROUNDS = 3
MAX_REPAIR_ROUNDS = 3
_DESIGN_INPUT_TOKENS = 6_000
_DESIGN_OUTPUT_TOKENS = 2_500
_HELDOUT_FILENAME = "wizard_hobby_suite.jsonl"
# fallback_reason rides along even when it is None: a slim payload that can only
# say "template" cannot tell a missing key from a designer that blew up.
_LOOK_PUBLIC_KEYS = ("idea_id", "title", "hero_job", "round", "pitch", "fallback_reason")


def looks_public(
    looks: list[dict[str, Any]] | None, *, include_html: bool = True
) -> list[dict[str, Any]]:
    """Project look payloads. HTTP keeps ``html``; MCP/hermes omit it."""
    out: list[dict[str, Any]] = []
    for look in looks or []:
        if include_html:
            out.append(dict(look))
            continue
        out.append({key: look.get(key) for key in _LOOK_PUBLIC_KEYS})
    return out


def analog_covers_hero(view_blocks: set[str] | list[str] | None, hero: str) -> bool:
    """True when a bundled analog already has a live view for this hero job."""
    required = _HERO_REQUIRED_BLOCKS.get(hero or "")
    if not required:
        return True
    return bool(set(view_blocks or []) & required)


def invent_idea_cards(goal: str, *, seed: str = "") -> list[dict[str, Any]]:
    """Three job-shaped idea cards when the atlas has no neighborhood ideas.

    Without a *seed* the only vocabulary available is the goal itself, so the
    three cards are named after its first keyword and share a fixed set of look
    words. That is the same skeleton "xyzzy plugh foobar" produces, which is the
    honest shape of knowing nothing.

    *seed* is one sentence the user said they would log, in their own words. It
    is the single source of real domain language offline, so when it is present
    it supplies the jargon, the worked example, and the identity values instead.
    """
    kws = bp.keywords(goal)
    token = kws[0] if kws else "interest"
    slug = bp.slugify(token)
    label = token.replace("_", " ")
    keyword = (label[:1].upper() + label[1:]) if label else "Interest"
    identity = f"{slug}_name"
    extra = [k for k in kws[1:] if len(k) >= 3][:6]
    said = seed_terms(seed)
    # The user's words when we have them; otherwise shared look words plus
    # leftover goal terms (not the slug) so first captures file.
    jargon = [*said, *extra] if said else ["shelf", "dex", "photos", "keeper", *extra]
    sample = seed.strip()
    said_phrase = ", ".join(said[:3])

    def _card(
        *,
        suffix: str,
        title: str,
        pitch: str,
        jobs: list[str],
        example: str,
        aliases: list[str],
        highlighted: bool,
    ) -> dict[str, Any]:
        return {
            "id": f"invented.{slug}.{suffix}",
            "kind": "idea",
            "title": title,
            "pitch": pitch,
            "jobs": jobs,
            "provenance": "foundry",
            "world_analogs": [],
            "analog_pack": None,
            "domain_slug": slug,
            "identity_hint": identity,
            "example": example,
            "jargon": jargon,
            "aliases": aliases,
            "highlighted": highlighted,
        }

    def _pitch(base: str) -> str:
        return f"{base}. It uses your words: {said_phrase}." if said_phrase else f"{base}."

    return [
        _card(
            suffix="shelf",
            title=f"{keyword} shelf",
            pitch=_pitch(f"A dex of the {label} you keep, with photos"),
            jobs=["catalog", "media_dex"],
            example=(
                sample
                or f"added {' '.join(extra) or 'a new piece'} to the shelf with photos"
            ),
            aliases=["shelf", "photo dex"],
            highlighted=True,
        ),
        _card(
            suffix="timeline",
            title=f"{keyword} timeline",
            pitch=_pitch(f"A timeline of {label} as it happens"),
            jobs=["event_log"],
            example=sample or "logged a session this morning and kept a short note",
            aliases=["timeline"],
            highlighted=False,
        ),
        _card(
            suffix="chart",
            title=f"{keyword} chart",
            pitch=_pitch(f"A chart of {label} inputs → outcomes"),
            jobs=["improvement"],
            example=sample or "tried a different setup, the outcome was better",
            aliases=["chart", "scatter"],
            highlighted=False,
        ),
    ]


def _release_topic(goal: str, *, seed: str = "") -> str:
    """Keep the subject phrase instead of naming an app category for it."""
    topic_fillers = {
        "better",
        "build",
        "building",
        "built",
        "get",
        "got",
        "help",
        "home",
        "improve",
        "improved",
        "improving",
        "learn",
        "learned",
        "learning",
        "make",
        "making",
        "practice",
        "practise",
        "try",
        "trying",
        "use",
        "used",
        "using",
        "want",
    }
    words = [word for word in bp.keywords(goal) if word not in topic_fillers]
    if not words and seed:
        words = [word for word in bp.keywords(seed) if word not in topic_fillers]
    if not words:
        return "this interest"
    # Keep enough of a compound subject to distinguish "model trains" from
    # "trains", while dropping words that describe the act of logging.
    return " ".join(words[:4])


def invent_release_idea_cards(goal: str, *, seed: str = "") -> list[dict[str, Any]]:
    """Offer neutral directions for any topic the atlas does not know.

    These cards are intentionally about the person's next choice, not an
    invented category such as a shelf, timeline, or chart.  Explicit words in
    the goal still add the corresponding capability; otherwise the examples
    decide what the app should keep track of.
    """
    topic = _release_topic(goal, seed=seed)
    slug = bp.slugify(topic)
    seed_text = seed.strip()
    explicit_jobs = hinted_jobs(goal)
    jobs = list(dict.fromkeys(["event_log", *explicit_jobs]))
    jargon = list(dict.fromkeys(seed_terms(seed) + bp.keywords(goal)[:6]))
    if not jargon:
        jargon = [part for part in topic.split() if len(part) >= 3]

    def card(suffix: str, title: str, pitch: str, highlighted: bool) -> dict[str, Any]:
        return {
            "id": f"invented.{slug}.{suffix}",
            "kind": "idea",
            "title": title,
            "pitch": pitch,
            "jobs": jobs,
            "provenance": "foundry",
            "world_analogs": [],
            "analog_pack": None,
            "domain_slug": slug,
            "identity_hint": f"{slug}_name",
            "example": seed_text or f"wrote a note about {topic}",
            "jargon": jargon,
            "aliases": [topic, suffix.replace("_", " ")],
            "highlighted": highlighted,
            "release_direction": suffix,
        }

    return [
        card(
            "notes",
            f"Keep notes about {topic}",
            "Write down what happens in your own words.",
            True,
        ),
        card(
            "details",
            "Keep the details that matter",
            f"Save the parts of {topic} you will want to find again.",
            False,
        ),
        card(
            "your_way",
            "Describe your own way of using it",
            "Add two real notes and let your examples shape the app.",
            False,
        ),
    ]


def neutral_release_idea_cards(
    goal: str, prior: list[AtlasNode], *, seed: str = ""
) -> list[dict[str, Any]]:
    """Keep useful prior vocabulary without showing a neighboring subject.

    An Atlas parent can be right while its child idea is too specific: a
    fermentation parent may offer a sourdough card for a kombucha goal. The
    release view should not repeat that label, but its routing vocabulary and
    job shape are still useful. Copy those hidden inputs onto neutral cards
    named after the person's topic.
    """
    cards = invent_release_idea_cards(goal, seed=seed)
    if not prior:
        return cards
    generic_terms = {
        "better",
        "build",
        "builds",
        "care",
        "collection",
        "finish",
        "finished",
        "history",
        "home",
        "list",
        "log",
        "maintenance",
        "parts",
        "practice",
        "project",
        "projects",
        "service",
        "session",
        "sessions",
        "training",
    }
    subject_terms = [
        term for term in bp.keywords(goal) if term not in generic_terms
    ]
    for index, card in enumerate(cards):
        source = prior[index % len(prior)]
        card_jobs = card.get("jobs") or []
        card_jargon = card.get("jargon") or []
        card["jobs"] = list(dict.fromkeys([*card_jobs, *source.jobs]))
        card["jargon"] = list(
            dict.fromkeys([*subject_terms, *source.jargon, *source.vocabulary, *card_jargon])
        )[:24]
        card["vocabulary"] = list(dict.fromkeys([*subject_terms, *source.vocabulary]))[:24]
        card["routing_examples"] = [item.model_dump() for item in source.routing_examples]
        card["negative_examples"] = list(source.negative_examples)
        card["measure"] = source.measure.model_dump() if source.measure else None
        card["llm_hints"] = source.llm_hints
    return cards


def idea_card_to_node(card: dict[str, Any]) -> AtlasNode:
    """Coerce a neighborhood/invented idea dict into an AtlasNode."""
    provenance = card.get("provenance") or "foundry"
    if provenance not in {"world", "foundry", "both"}:
        provenance = "foundry"
    analog = card.get("analog_pack") or None
    if analog == "":
        analog = None
    return AtlasNode.model_validate(
        {
            "id": str(card["id"]),
            "kind": "idea",
            "title": str(card.get("title") or "Idea"),
            "aliases": list(card.get("aliases") or []),
            "pitch": str(card.get("pitch") or ""),
            "jobs": list(card.get("jobs") or ["event_log"]),
            "provenance": provenance,
            "world_analogs": card.get("world_analogs") or [],
            "analog_pack": analog,
            "domain_slug": card.get("domain_slug"),
            "identity_hint": card.get("identity_hint"),
            "example": str(card.get("example") or ""),
            "jargon": list(card.get("jargon") or []),
            "vocabulary": list(card.get("vocabulary") or []),
            "routing_examples": list(card.get("routing_examples") or []),
            "negative_examples": list(card.get("negative_examples") or []),
            "measure": card.get("measure"),
            "llm_hints": card.get("llm_hints"),
        }
    )


def bundled_view_blocks(name: str) -> set[str]:
    """View block ids declared by a bundled pack's ``projections.app.views``."""
    import yaml

    from domain_foundry_core.packs.loader import bundled_packs_root

    path = bundled_packs_root() / name / "projections.yaml"
    if not path.is_file():
        return set()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return set()
    if not isinstance(data, dict):
        return set()
    views = ((data.get("app") or {}).get("views") or [])
    blocks: set[str] = set()
    for view in views:
        if isinstance(view, dict) and view.get("block"):
            blocks.add(str(view["block"]))
    return blocks


class WizardEngine:
    def __init__(self, harness: HarnessAPI) -> None:
        self.harness = harness
        self.ws = harness.workspace
        self.store = WizardSessionStore(self.ws)

    # ------------------------------------------------------------- public API
    def new_domain(
        self,
        goal_text: str,
        *,
        test_drive: int = 5,
        release_mode: bool = False,
    ) -> dict[str, Any]:
        session = self.store.new(goal_text, test_drive=test_drive)
        session.release_mode = release_mode
        session.history.append({"role": "user", "text": goal_text})
        return release_turn(self._open_fork(session), session)

    def _atlas_overlay(self) -> Any:
        overlay = self.ws.home / "atlas"
        return overlay if overlay.is_dir() else None

    def _open_fork(self, session: WizardSession, *, cursor_id: str | None = None) -> dict[str, Any]:
        nb = query_neighborhood(
            session.goal,
            overlay=self._atlas_overlay(),
            cursor_id=cursor_id or session.atlas_cursor,
        )
        session.state = "fork"
        session.atlas_cursor = nb.get("cursor")
        session.neighborhood = nb
        self._ensure_invented_ideas(session)
        self._order_ideas(session)
        self.store.save(session)
        return self._fork_turn(session)

    def _order_ideas(self, session: WizardSession) -> None:
        """Put the idea we would build on 'yes' at position 1.

        The fork lists ideas by index and marks one "(suggested)". If the list
        order and the suggestion disagree, "1" and "yes" build different packs
        from the same screen. One ordering, computed once, settles all three.
        """
        nb = session.neighborhood if isinstance(session.neighborhood, dict) else None
        if not nb:
            return
        ideas = list(nb.get("ideas") or [])
        if len(ideas) < 2:
            return
        ideas.sort(key=lambda idea: not idea.get("highlighted"))
        preferred = self._starter_pack_idea(session, ideas)
        if preferred:
            ideas.sort(key=lambda idea: idea.get("id") != preferred)
        nb["ideas"] = ideas
        session.neighborhood = nb

    def _starter_pack_idea(
        self, session: WizardSession, ideas: list[dict[str, Any]]
    ) -> str | None:
        """A highlighted idea whose analog pack we actually ship, if there is one."""
        starter = bp.match_starter_pack(session.goal)
        if not starter:
            return None
        want = str(starter.get("name") or "")
        if not want:
            return None
        pool = [i for i in ideas if i.get("highlighted")] or ideas[:1]
        for idea in pool:
            if idea.get("analog_pack") == want and self._bundled_pack_exists(want):
                return str(idea.get("id") or "") or None
        return None

    def _ensure_invented_ideas(self, session: WizardSession) -> None:
        """When the atlas misses, put topic-shaped directions on the session."""
        nb = session.neighborhood if isinstance(session.neighborhood, dict) else {}
        if session.release_mode and nb.get("ideas") and not self._release_ideas_match_goal(session, nb):
            # A parent node can be useful evidence without its child ideas being
            # the person's subject. Do not show a neighbouring practice such as
            # sourdough for a kombucha goal; carry useful prior vocabulary into
            # neutral cards instead.
            graph = load_atlas(self._atlas_overlay())
            prior = [
                graph.get(str(card.get("id")))
                for card in nb.get("ideas") or []
                if isinstance(card, dict)
            ]
            prior = [node for node in prior if node is not None]
            nb = dict(nb)
            nb["unindexed"] = True
            nb["refine"] = []
            nb["expand"] = []
            nb["ideas"] = neutral_release_idea_cards(session.goal, prior)
            session.neighborhood = nb
        if nb.get("unindexed") or not nb.get("ideas"):
            if not nb.get("ideas"):
                nb = dict(nb)
                nb["ideas"] = (
                    invent_release_idea_cards(session.goal)
                    if session.release_mode
                    else invent_idea_cards(session.goal)
                )
                session.neighborhood = nb

    def _release_ideas_match_goal(
        self, session: WizardSession, neighborhood: dict[str, Any]
    ) -> bool:
        """Keep Atlas ideas only when an idea card names the subject.

        A parent node may be a useful prior while a child card is too specific.
        The card itself must share a non-generic subject word with the goal, so
        a release session never presents a neighboring practice as the answer.
        """
        graph = load_atlas(self._atlas_overlay())
        goal_tokens = _goal_tokens(graph, session.goal)
        for card in neighborhood.get("ideas") or []:
            card_text = " ".join(
                [
                    str(card.get("title") or ""),
                    str(card.get("domain_slug") or ""),
                    *(str(alias) for alias in card.get("aliases") or []),
                ]
            )
            if goal_tokens & set(re.findall(r"[a-z][a-z0-9']+", card_text.lower())):
                return True
        return False

    def _neighborhood_cards(self, session: WizardSession) -> dict[str, dict[str, Any]]:
        cards: dict[str, dict[str, Any]] = {}
        for card in (session.neighborhood or {}).get("ideas") or []:
            iid = card.get("id") if isinstance(card, dict) else None
            if iid:
                cards[str(iid)] = card
        return cards

    def _resolve_idea_nodes(
        self, session: WizardSession, idea_ids: list[str]
    ) -> list[AtlasNode]:
        """Atlas graph first; invented / neighborhood cards when graph.get is None."""
        graph = load_atlas(self._atlas_overlay())
        cards = self._neighborhood_cards(session)
        nodes: list[AtlasNode] = []
        seen: set[str] = set()
        for iid in idea_ids:
            if not iid or iid in seen:
                continue
            node = graph.get(iid)
            if node is None and iid in cards:
                try:
                    node = idea_card_to_node(cards[iid])
                except Exception:
                    node = None
            if node is None:
                continue
            seen.add(iid)
            nodes.append(node)
            if len(nodes) >= 3:
                break
        return nodes

    def _hero_for_commit(self, session: WizardSession, idea: AtlasNode) -> str:
        chosen = session.selected_look_id
        look = next(
            (L for L in (session.looks or []) if L.get("idea_id") == chosen),
            None,
        )
        if look and look.get("hero_job"):
            return str(look["hero_job"])
        if len(session.looks or []) == 1 and session.looks[0].get("hero_job"):
            return str(session.looks[0]["hero_job"])
        return hero_job(list(idea.jobs), hints=session.look_job_hints)

    def _make_look(
        self,
        session: WizardSession,
        idea: AtlasNode,
        *,
        critique: str = "",
        previous_html: str = "",
        round: int = 1,
        job_hints: list[str] | None = None,
        llm: Any | None = None,
    ) -> dict[str, Any]:
        look = generate_look(
            idea.model_dump(),
            samples=session.ingest_blob,
            critique=critique,
            previous_html=previous_html,
            round=round,
            job_hints=job_hints if job_hints is not None else session.look_job_hints,
            llm=llm if llm is not None else self._looks_llm(),
        )
        look["pitch"] = idea.pitch
        persist_look(self.store.looks_dir(session.session_id), look)
        return look

    def _fork_turn(self, session: WizardSession) -> dict[str, Any]:
        self._ensure_invented_ideas(session)
        nb = session.neighborhood or {}
        ideas = nb.get("ideas") or []
        lines = []
        for i, idea in enumerate(ideas, start=1):
            mark = " (suggested)" if idea.get("highlighted") else ""
            extra = job_pitches(idea.get("jobs") or [])
            pitch = idea.get("pitch") or ""
            line = f"{i}. {idea.get('title')}{mark}: {pitch}"
            if extra and idea.get("highlighted"):
                line += f"\n   {extra}"
            lines.append(line)
        idea_block = (
            "\n".join(lines)
            if lines
            else "No known ideas here yet. Describe the look you want, or say 'just a simple log'."
        )
        goal = (session.goal or "").strip()
        message = (
            f'You said “{goal}”. You could:\n'
            f"{idea_block}\n"
            "Which of these, or say what you want it to do, like a chart, photos, or a mix board. "
            "Paste a notes folder path to ingest text. Photos: have your agent read them first, then send the text."
        )
        turn = self._turn(session, message=message, awaiting="fork")
        turn["neighborhood"] = nb
        turn["simple_log"] = True
        return turn

    def _handle_fork(self, session: WizardSession, text: str) -> dict[str, Any]:
        path = existing_ingest_path(text)
        if path is not None:
            return self._ingest_during_fork(session, path)
        intent = parse_fork_reply(text, session.neighborhood or {})
        kind = intent.get("kind")
        if kind == "cancel":
            session.state = "failed"
            self.store.save(session)
            return self._turn(session, message="Cancelled. Start a new domain when you're ready.")
        if kind == "navigate":
            return self._open_fork(session, cursor_id=str(intent.get("node_id")))
        if kind == "something_else":
            session.neighborhood = session.neighborhood or {}
            turn = self._fork_turn(session)
            turn["message"] = (
                "Describe what you actually do, or the app you wish existed. "
                "I'll match a nearby idea or start a simple log."
            )
            return turn
        if kind == "simple_log":
            if session.release_mode:
                ids = self._skip_idea_ids(session)
                if ids:
                    return self._commit_ideas(session, ids)
            return self._design_and_activate(session, use_llm=False, tier="sota")
        if kind == "show_schema":
            ids = list(intent.get("idea_ids") or [])
            if not ids:
                ids = [i["id"] for i in (session.neighborhood or {}).get("ideas") or []][:1]
            return self._schema_preview(session, ids)
        if kind == "skip":
            ids = self._skip_idea_ids(session)
            if not ids:
                return self._design_and_activate(session, use_llm=False, tier="sota")
            return self._enter_looks(session, ids)
        if kind == "commit":
            return self._enter_looks(session, list(intent.get("idea_ids") or []))
        stay_ids = stay_idea_ids(text, session.neighborhood or {})
        if stay_ids:
            session.look_job_hints = hinted_jobs(text)
            return self._enter_looks(session, stay_ids, job_hints=session.look_job_hints)
        # Rematch only when the reply is a real topic change, not a job on this neighborhood.
        if len(text.split()) >= 4:
            probe = query_neighborhood(text, overlay=self._atlas_overlay())
            if neighborhood_bucket(probe) and neighborhood_bucket(probe) != neighborhood_bucket(
                session.neighborhood or {}
            ):
                session.goal = text
                session.atlas_cursor = None
                return self._open_fork(session)
        turn = self._fork_turn(session)
        turn["message"] = (
            "I didn't catch that. Pick an idea by name or number, describe the look "
            "(chart, photos, mix), or paste a notes folder path."
        )
        return turn

    def _ingest_during_fork(self, session: WizardSession, path: Path) -> dict[str, Any]:
        n_files = self._load_ingest_blob(session, path)
        from domain_foundry_core.wizard.fork import rank_ideas_in_neighborhood

        nb = session.neighborhood or {}
        ranked = rank_ideas_in_neighborhood(f"{session.goal}\n{session.ingest_blob}", nb)
        top = {idea.get("id") for score, idea in ranked[:2] if score >= 4}
        for idea in nb.get("ideas") or []:
            idea["highlighted"] = idea.get("id") in top if top else idea.get("highlighted")
        session.neighborhood = nb
        self._order_ideas(session)
        self.store.save(session)
        turn = self._fork_turn(session)
        turn["message"] = (
            f"Read {n_files} text file(s) from {path.name}. "
            "Photos aren't read here. Have your agent read them and send the text. "
        ) + turn["message"]
        turn["ingest"] = {"path": str(path), "files": n_files}
        return turn

    def _load_ingest_blob(self, session: WizardSession, path: Path) -> int:
        from domain_foundry_core.ingest import iter_records

        chunks: list[str] = []
        for _ref, text in iter_records(path):
            chunks.append(text)
            if len(chunks) >= 40:
                break
        blob = "\n".join(chunks)[:8000]
        session.ingest_blob = ((session.ingest_blob or "") + "\n" + blob).strip()
        return len(chunks)

    def _looks_llm(self) -> Any | None:
        provider = self._tiered_provider()
        if not getattr(provider, "has_live_keys", lambda: False)():
            return None
        return self._provider_with_cassette(provider)

    def _enter_looks(
        self,
        session: WizardSession,
        idea_ids: list[str],
        *,
        job_hints: list[str] | None = None,
    ) -> dict[str, Any]:
        ideas = self._resolve_idea_nodes(session, idea_ids)
        if not ideas:
            return self._design_and_activate(session, use_llm=False, tier="sota")
        session.selected_ideas = [i.id for i in ideas]
        session.selected_jobs = []
        for idea in ideas:
            for job in idea.jobs:
                if job not in session.selected_jobs:
                    session.selected_jobs.append(job)
        if job_hints:
            session.look_job_hints = list(job_hints)
        session.state = "looks"
        looks: list[dict[str, Any]] = []
        llm = self._looks_llm()
        for idea in ideas:
            looks.append(self._make_look(session, idea, llm=llm))
        session.looks = looks
        session.selected_look_id = looks[0]["idea_id"] if len(looks) == 1 else None
        self.store.save(session)
        return self._looks_turn(session)

    def _looks_turn(self, session: WizardSession, *, extra: str = "") -> dict[str, Any]:
        looks = session.looks or []
        lines = []
        for i, look in enumerate(looks, start=1):
            mark = " (selected)" if look.get("idea_id") == session.selected_look_id else ""
            hero = look.get("hero_job") or ""
            lines.append(f"{i}. {look.get('title')}{mark}, a {hero} look (round {look.get('round', 1)})")
        listing = "\n".join(lines) if lines else "No looks yet."
        message = (
            extra
            + f"Here {'is a look' if len(looks) == 1 else 'are a few looks'}. "
            "Pick one, tell me how to change it (darker, denser, more chart), or say 'build it'.\n"
            f"{listing}"
        )
        turn = self._turn(session, message=message, awaiting="look")
        turn["looks"] = looks_public(looks, include_html=True)
        turn["selected_look_id"] = session.selected_look_id
        turn["neighborhood"] = session.neighborhood
        return turn

    def _match_look_id(self, text: str, session: WizardSession) -> str | None:
        looks = session.looks or []
        if not looks:
            return None
        low = text.strip().lower()
        numbers = [int(n) for n in re.findall(r"\b(\d+)\b", text)]
        if numbers and 1 <= numbers[0] <= len(looks):
            return looks[numbers[0] - 1].get("idea_id")
        for look in looks:
            title = str(look.get("title") or "").lower()
            iid = str(look.get("idea_id") or "")
            slug = iid.split(".")[-1].replace("_", " ")
            if title and title in low:
                return iid
            if slug and len(slug) >= 4 and slug in low:
                return iid
        style_jobs = {
            "scatter": "improvement",
            "chart": "improvement",
            "graph": "improvement",
            "plot": "improvement",
            "gallery": "media_dex",
            "photo": "media_dex",
            "instagram": "media_dex",
            "map": "atlas",
            "field-guide": "catalog",
            "field guide": "catalog",
            "dex": "catalog",
            "mix": "lab",
            "lab": "lab",
            "timeline": "event_log",
        }
        for needle, job in style_jobs.items():
            if needle in low:
                for look in looks:
                    if look.get("hero_job") == job or job in (look.get("jobs") or []):
                        return look.get("idea_id")
        if len(looks) == 1 and _LOOK_PICK_RE.search(low):
            return looks[0].get("idea_id")
        return None

    def _handle_looks(self, session: WizardSession, text: str) -> dict[str, Any]:
        low = text.strip().lower()
        if re.search(r"\b(back|nevermind|never mind)\b", low):
            session.state = "fork"
            session.looks = []
            session.selected_look_id = None
            return self._fork_turn(session)
        path = existing_ingest_path(text)
        if path is not None:
            n_files = self._load_ingest_blob(session, path)
            turn = self._enter_looks(
                session, list(session.selected_ideas), job_hints=session.look_job_hints
            )
            turn["message"] = (
                f"Read {n_files} text file(s) from {path.name} and refreshed the look. "
            ) + turn["message"]
            turn["ingest"] = {"path": str(path), "files": n_files}
            return turn
        matched = self._match_look_id(text, session)
        if matched:
            session.selected_look_id = matched
        critique = bool(_CRITIQUE_RE.search(low)) and not _CONFIRM_RE.search(low)
        # A card title, its number, or the explicit "Choose this" action all
        # mean the same thing.  Keeping the matched-id check here makes the
        # release UI's one-tap choice work for both atlas and invented ideas.
        accept = bool(
            _CONFIRM_RE.search(low)
            or (_LOOK_PICK_RE.search(low) and not critique)
            or (matched and not critique)
        )
        if critique:
            target = session.selected_look_id or (session.looks[0]["idea_id"] if session.looks else None)
            if not target:
                return self._looks_turn(session, extra="Pick a look first. ")
            nodes = self._resolve_idea_nodes(session, [target])
            if not nodes:
                return self._looks_turn(session, extra="That look is gone. Pick another. ")
            idea = nodes[0]
            current = next((L for L in session.looks if L.get("idea_id") == target), {})
            nxt = int(current.get("round") or 1) + 1
            if nxt > MAX_LOOK_ROUNDS:
                return self._looks_turn(session, extra="That's enough rounds. Say 'build it' or pick another. ")
            look = self._make_look(
                session,
                idea,
                critique=text,
                previous_html=str(current.get("html") or ""),
                round=nxt,
                job_hints=session.look_job_hints + hinted_jobs(text),
            )
            session.looks = [look if L.get("idea_id") == target else L for L in session.looks]
            session.selected_look_id = target
            self.store.save(session)
            return self._looks_turn(session, extra="Updated that look. ")
        if accept:
            chosen = session.selected_look_id
            if not chosen and len(session.looks) == 1:
                chosen = session.looks[0].get("idea_id")
            if not chosen:
                return self._looks_turn(session, extra="Pick a look first (a number, or 'the scatter one'). ")
            return self._commit_ideas(session, [chosen])
        self.store.save(session)
        if matched:
            return self._looks_turn(session, extra="That one. Say 'build it' or tell me how to change it. ")
        return self._looks_turn(
            session,
            extra="I didn't catch that. Pick a look, critique it, or say 'build it'. ",
        )

    def _skip_idea_ids(self, session: WizardSession) -> list[str]:
        """The first idea on screen: the one marked "(suggested)", the one "1" picks.

        ``_order_ideas`` already resolved highlighting and the starter-pack
        preference into the display order, so "yes" has nothing left to decide.
        """
        ideas = list((session.neighborhood or {}).get("ideas") or [])
        if not ideas:
            return []
        return [ideas[0]["id"]]

    def _bundled_pack_exists(self, name: str) -> bool:
        from domain_foundry_core.packs.loader import bundled_packs_root

        root = bundled_packs_root() / name
        return root.is_dir() and (root / "pack.yaml").is_file()

    # ----------------------------------------------------------- the ADR-010 bridge
    def _llm_explicitly_off(self) -> bool:
        """True only when the owner said "no model calls", never merely by default.

        ``resolve_llm_mode`` reports ``heuristic`` when nothing is configured,
        which is not the same statement: a user who exported a key and nothing
        else still wants the key used, and ``_looks_llm`` already treats them
        that way. But an install that set ``DOMAIN_FOUNDRY_LLM=heuristic`` asked
        for offline behaviour, and the bridge is the most expensive call in the
        product. That is also what keeps the offline interest suite inert on a
        developer machine with a key exported.
        """
        env = (os.environ.get("DOMAIN_FOUNDRY_LLM") or "").strip().lower()
        if env:
            return env in _LLM_OFF_MODES
        configured = (load_llm_config(self.ws.home).mode or "").strip().lower()
        return bool(configured) and configured in _LLM_OFF_MODES

    def _bridge_provider(self) -> LLMProvider | None:
        """The reasoning model the bridge would use, or None if there isn't one."""
        if self._llm_explicitly_off():
            return None
        provider = self._tiered_provider()
        if not getattr(provider, "has_live_keys", lambda: False)():
            return None
        return self._provider_with_cassette(provider)

    def _atlas_is_thin(self, session: WizardSession, ideas: list[AtlasNode]) -> bool:
        """True when the atlas has neither a pack to copy nor words to lend.

        ADR-010 demotes the atlas to a prior, but only where it was never much
        of an answer: an unindexed goal, or a committed idea with no
        ``analog_pack`` and no ``vocabulary``. Those are exactly the rows the
        50-interest audit measured forking correctly and then failing to file
        the user's first sentence, because no amount of offline cleverness
        invents ``QSO`` or ``bisque``.
        """
        if (session.neighborhood or {}).get("unindexed"):
            return True
        if not ideas:
            return True
        has_pack = any(getattr(idea, "analog_pack", None) for idea in ideas)
        has_words = any(getattr(idea, "vocabulary", None) for idea in ideas)
        return not has_pack and not has_words

    def _bridge_eligible(self, session: WizardSession, ideas: list[AtlasNode]) -> bool:
        """ADR-010's trigger: provider access, and an atlas that cannot furnish this."""
        provider_available = self._bridge_provider() is not None
        if session.release_mode and provider_available:
            # The release journey gives every keyed interest the same research
            # chance. The atlas remains a useful prior, not a hidden gate.
            return True
        return self._atlas_is_thin(session, ideas) and provider_available

    # ------------------------------------------------------------- elicitation
    def _needs_elicitation(self, session: WizardSession, ideas: list[AtlasNode]) -> bool:
        """True when the design would otherwise be built out of keywords alone.

        An unindexed neighbourhood has no vocabulary to lend, and an invented
        card is named after the goal's first word, the identical skeleton
        "xyzzy plugh foobar" produces. Neither can file "finished the Millennium
        Falcon MOC, 3800 pieces". Asking is the only offline source of the words
        that could.

        The bridge asks for the same two sentences and for the same reason: they
        are its acceptance evidence (ADR-010). So a create that is about to
        escalate elicits through this state machine rather than a second one.
        """
        if session.elicit_prompts >= ELICIT_PROMPTS:
            return False
        if session.release_mode:
            return True
        if (session.neighborhood or {}).get("unindexed"):
            return True
        if any(str(idea.id).startswith("invented.") for idea in ideas):
            return True
        return self._bridge_eligible(session, ideas)

    def design_seed(self, session: WizardSession) -> str:
        """The first elicited sentence, the only one design is allowed to see."""
        samples = session.elicited_samples or []
        return samples[0] if samples else ""

    def _held_out_sample(self, session: WizardSession) -> str:
        samples = session.elicited_samples or []
        return samples[1] if len(samples) > 1 else ""

    def _elicit_turn(self, session: WizardSession) -> dict[str, Any]:
        session.state = "elicit"
        first = session.elicit_prompts == 0
        session.elicit_prompts += 1
        self.store.save(session)
        turn = self._turn(
            session,
            message=ELICIT_FIRST if first else ELICIT_SECOND,
            awaiting="elicit",
        )
        turn["elicit"] = {
            "index": session.elicit_prompts,
            "of": ELICIT_PROMPTS,
            "held_out": not first,
            "samples": list(session.elicited_samples),
        }
        turn["neighborhood"] = session.neighborhood
        return turn

    def _handle_elicit(self, session: WizardSession, text: str) -> dict[str, Any]:
        stripped = (text or "").strip()
        if not stripped or _ELICIT_SKIP_RE.match(stripped):
            # Skipping the first prompt skips both: a held-out check needs a
            # design sentence to be held out *from*.
            session.elicit_prompts = ELICIT_PROMPTS
        else:
            session.elicited_samples.append(stripped)
        self.store.save(session)
        if session.elicit_prompts < ELICIT_PROMPTS:
            return self._elicit_turn(session)
        self._reseed_invented_ideas(session)
        return self._commit_ideas(session, list(session.selected_ideas))

    def _reseed_invented_ideas(self, session: WizardSession) -> None:
        """Rebuild the invented cards around the user's sentence, keeping order."""
        seed = self.design_seed(session)
        if not seed:
            return
        nb = dict(session.neighborhood or {})
        ideas = list(nb.get("ideas") or [])
        if not any(str(i.get("id") or "").startswith("invented.") for i in ideas):
            return
        card_factory = invent_release_idea_cards if session.release_mode else invent_idea_cards
        fresh = {card["id"]: card for card in card_factory(session.goal, seed=seed)}
        nb["ideas"] = [
            {**idea, **fresh[idea["id"]], "highlighted": idea.get("highlighted")}
            if idea.get("id") in fresh
            else idea
            for idea in ideas
        ]
        session.neighborhood = nb
        self.store.save(session)

    def _commit_ideas(self, session: WizardSession, idea_ids: list[str]) -> dict[str, Any]:
        ideas = self._resolve_idea_nodes(session, idea_ids)
        if not ideas:
            return self._design_and_activate(session, use_llm=False, tier="sota")
        session.selected_ideas = [i.id for i in ideas]
        session.selected_jobs = []
        for idea in ideas:
            for job in idea.jobs:
                if job not in session.selected_jobs:
                    session.selected_jobs.append(job)
        if self._needs_elicitation(session, ideas):
            return self._elicit_turn(session)
        analog = ideas[0].analog_pack if len(ideas) == 1 else None
        if analog and self._bundled_pack_exists(analog) and not session.release_mode:
            hero = self._hero_for_commit(session, ideas[0])
            if analog_covers_hero(bundled_view_blocks(analog), hero):
                starter = {"name": analog, "title": ideas[0].title, "description": ideas[0].pitch}
                return self._install_starter(session, starter)
        bridged = self._maybe_escalate(session, ideas)
        if bridged is not None:
            return bridged
        provider = self._tiered_provider()
        turn = self._design_and_activate_from_ideas(
            session, ideas, use_llm=provider.has_live_keys(), tier="sota"
        )
        return self._with_bridge_note(session, ideas, turn)

    # ------------------------------------------------------------ escalation
    def _foundry_meter(self, session: WizardSession) -> Any | None:
        """The ledger the bridge's six sota calls are billed against."""
        try:
            return LedgerCostMeter.for_home(self.ws.home, spec_id=session.session_id)
        except Exception:  # noqa: BLE001 - an unmeterable run is still a run
            return None

    def _record_bridge_fallback(self, session: WizardSession, reason: str) -> None:
        """Name what went wrong, on the session, before falling back.

        ``looks.py`` learned this the hard way: swallowing the reason made a
        broken designer endpoint look exactly like having no key at all.
        """
        session.bridge_fallback_reason = str(reason)[:500]
        session.bridge_tier = "fallback_demo"
        self.store.save(session)

    def _maybe_escalate(
        self, session: WizardSession, ideas: list[AtlasNode]
    ) -> dict[str, Any] | None:
        """ADR-010: research this interest and build the pack from the spec.

        Returns a turn when the bridge produced (or definitively failed to
        produce) the pack, and ``None`` when the caller should carry on down the
        ordinary path. Every ``None`` that follows an eligible attempt has left
        a ``bridge_fallback_reason`` behind it.
        """
        provider = self._bridge_provider()
        if provider is None or (
            not session.release_mode and not self._atlas_is_thin(session, ideas)
        ):
            return None

        samples = [text for text in (session.elicited_samples or []) if text.strip()]
        if len(samples) < REQUIRED_SAMPLES:
            self._record_bridge_fallback(
                session,
                "you skipped the sentences a research run uses as its own check",
            )
            return None

        meter = self._foundry_meter(session)
        if meter is not None and not meter.allow():
            self._record_bridge_fallback(session, "the daily cost cap is already spent")
            return None

        jobs = list(session.selected_jobs)
        try:
            run = run_bridge(
                goal=session.goal,
                samples=samples,
                provider=provider,
                prior=atlas_prior(
                    goal=session.goal,
                    neighborhood=session.neighborhood,
                    ideas=ideas,
                    samples=samples,
                ),
                meter=meter,
            )
            blueprint = compile_jobs(run.shortlist, goal=session.goal, jobs=jobs)
        except BridgeUnavailable as exc:
            self._record_bridge_fallback(session, exc.reason)
            return None
        except Exception as exc:  # noqa: BLE001 - compile refusals fall back too
            self._record_bridge_fallback(
                session,
                f"the researched design would not compile ({type(exc).__name__}: {exc})",
            )
            return None

        return self._activate_bridged(session, ideas, run, blueprint)

    def _activate_bridged(
        self,
        session: WizardSession,
        ideas: list[AtlasNode],
        run: BridgeRun,
        blueprint: dict[str, Any],
    ) -> dict[str, Any]:
        """Install a bridged blueprint through the ordinary generate/dry-run gate.

        Nothing about the runtime changed, which is the point: a bridged pack has
        to route its own examples, including the user's first sentence, which
        ``seeded_shortlist`` put among them, before it is allowed to activate.
        """
        blueprint["domain"] = self._unique_domain(blueprint["domain"])
        agent = blueprint.get("agent")
        if isinstance(agent, dict):
            agent["name"] = blueprint["domain"]
        meta = blueprint.setdefault("meta", {})
        meta["atlas_ideas"] = [idea.id for idea in ideas]
        meta["atlas_cursor"] = session.atlas_cursor
        meta["jobs"] = list(session.selected_jobs)
        meta["foundry_spec"] = run.spec.id
        meta["evidence_tier"] = run.evidence_tier

        session.blueprint = blueprint
        session.domain = blueprint["domain"]
        session.questions = []
        session.state = "interview"
        session.design_mode = "llm"
        session.designer_model = resolve_tier_settings("sota", home=self.ws.home).model
        session.bridge_tier = run.evidence_tier
        session.bridge_spec_id = run.spec.id
        session.bridge_fallback_reason = None
        self.store.save(session)

        turn = self._generate(session)
        if session.state == "failed":
            self._record_bridge_fallback(
                session,
                f"the researched pack did not clear the dry-run gate "
                f"({turn.get('message') or 'no detail'})",
            )
            return self._scaffold_after_bridge_failure(session, ideas)

        artifacts: str | None = None
        artifacts_error: str | None = None
        if session.pack_path:
            try:
                artifacts = str(persist_artifacts(Path(session.pack_path), run))
            except Exception as exc:  # noqa: BLE001 - the pack still works
                artifacts_error = f"{type(exc).__name__}: {exc}"

        turn["bridge"] = {
            "spec_id": run.spec.id,
            "evidence_tier": run.evidence_tier,
            "evidence_label": run.evidence_label,
            "sources": len(run.spec.source_ids),
            "evidence": len(run.spec.evidence),
            "spent_usd": run.spent_usd,
            "artifacts": artifacts,
            "artifacts_error": artifacts_error,
        }
        note = (
            f"I researched “{session.goal}” and built this from a specification. "
            f"{run.evidence_label}."
        )
        if artifacts:
            note += f" Every step is under {Path(artifacts).parent.name}/foundry/."
        turn["message"] = f"{note} {turn.get('message') or ''}".strip()
        return turn

    def _scaffold_after_bridge_failure(
        self, session: WizardSession, ideas: list[AtlasNode]
    ) -> dict[str, Any]:
        """Install the ordinary atlas pack after a bridged one could not activate."""
        reason = session.bridge_fallback_reason
        session.state = "interview"
        session.activated = False
        session.pack_path = None
        session.domain = None
        session.dry_run = {}
        session.acceptance = {}
        session.blueprint = {}
        session.questions = []
        session.answers = {}
        session.design_mode = "scaffold"
        session.designer_model = None
        session.bridge_tier = "fallback_demo"
        session.bridge_spec_id = None
        self.store.save(session)
        turn = self._design_and_activate_from_ideas(
            session, ideas, use_llm=False, tier="sota"
        )
        session.bridge_fallback_reason = reason
        self.store.save(session)
        return self._with_bridge_note(session, ideas, turn)

    def _with_bridge_note(
        self, session: WizardSession, ideas: list[AtlasNode], turn: dict[str, Any]
    ) -> dict[str, Any]:
        """Prefix one honest sentence about research: why it didn't run, or didn't work."""
        note = self._bridge_note(session, ideas)
        if note and isinstance(turn.get("message"), str):
            turn["message"] = f"{note} {turn['message']}".strip()
        if session.bridge_fallback_reason:
            turn["bridge_fallback"] = "scaffold"
            turn["bridge_fallback_reason"] = session.bridge_fallback_reason
        return turn

    def _bridge_note(self, session: WizardSession, ideas: list[AtlasNode]) -> str:
        goal = (session.goal or "this").strip()
        if session.bridge_fallback_reason:
            return (
                f"I meant to research “{goal}” for real vocabulary and views and couldn't: "
                f"{session.bridge_fallback_reason}. So this is built from your own words "
                "instead, not from research."
            )
        if self._atlas_is_thin(session, ideas) and self._bridge_provider() is None:
            return (
                f"No reasoning model is configured, so I can't research “{goal}” for real "
                "vocabulary and views. You get a solid basic tracker built from your own "
                "words; add a key later and I'll rebuild it with research."
            )
        return ""

    def _schema_preview(self, session: WizardSession, idea_ids: list[str]) -> dict[str, Any]:
        ideas = self._resolve_idea_nodes(session, idea_ids)
        if not ideas:
            return self._fork_turn(session)
        session.selected_ideas = [i.id for i in ideas]
        session.selected_jobs = []
        for idea in ideas:
            for job in idea.jobs:
                if job not in session.selected_jobs:
                    session.selected_jobs.append(job)
        shortlist = shortlist_for_ideas(
            ideas, goal=session.goal, seed=self.design_seed(session)
        )
        preview = {
            "ideas": [i.id for i in ideas],
            "jobs": list(session.selected_jobs),
            "objects": list(shortlist.objects),
            "fields": [f.model_dump(exclude_none=True) for f in shortlist.fields],
            "analog_pack": ideas[0].analog_pack if len(ideas) == 1 else None,
            "identity_hint": ideas[0].identity_hint,
        }
        session.schema_preview = preview
        session.state = "schema_preview"
        self.store.save(session)
        message = (
            f"Schema for {', '.join(i.title for i in ideas)}: "
            f"objects {', '.join(shortlist.objects)}; "
            f"jobs {', '.join(session.selected_jobs) or 'event_log'}. "
            "Reply 'yes' to build it, or 'back' to pick again."
        )
        turn = self._turn(session, message=message, awaiting="schema_confirm")
        turn["schema_preview"] = preview
        turn["neighborhood"] = session.neighborhood
        return turn

    def _handle_schema_preview(self, session: WizardSession, text: str) -> dict[str, Any]:
        low = text.strip().lower()
        if re.search(r"\b(back|no|cancel|nevermind)\b", low):
            session.state = "fork"
            session.schema_preview = {}
            return self._fork_turn(session)
        if _CONFIRM_RE.search(low) or low in {"build", "activate", "go"}:
            return self._commit_ideas(session, list(session.selected_ideas))
        return self._schema_preview(session, list(session.selected_ideas))

    def _design_and_activate_from_ideas(
        self,
        session: WizardSession,
        ideas: list[Any],
        *,
        use_llm: bool,
        tier: str,
    ) -> dict[str, Any]:
        jobs = list(session.selected_jobs)
        seed = self.design_seed(session)
        kws = bp.keywords(session.goal)
        release_topic = _release_topic(session.goal, seed=seed) if session.release_mode else ""
        domain_hint = (
            bp.slugify(release_topic)
            if session.release_mode
            else ideas[0].domain_slug if ideas else None
        )
        if kws:
            kw = bp.slugify(kws[0])
            # First-word of the goal names the pack unless it's a bucket
            # ("food", "diving") — those are too coarse; keep the idea slug.
            graph = load_atlas(self._atlas_overlay())
            named = graph.get(kw)
            if not session.release_mode and (domain_hint is None or named is None or named.kind != "bucket"):
                domain_hint = kw
        blueprint: dict[str, Any] | None = None
        if use_llm:
            try:
                raw = LLMBlueprintDesigner().design(
                    session.goal,
                    llm=self._provider_with_cassette(self._tiered_provider()),
                    tier=tier,
                    jobs=jobs,
                )
                meta_sl = (raw.get("meta") or {}).get("shortlist")
                if isinstance(meta_sl, list) and meta_sl:
                    from domain_foundry_core.wizard.shortlist import ShortlistModel

                    fallback = shortlist_for_ideas(ideas, goal=session.goal, seed=seed)
                    examples = [
                        {
                            key: example[key]
                            for key in ("text", "object", "fields")
                            if key in example
                        }
                        for example in (raw.get("examples") or [])
                        if isinstance(example, dict)
                    ]
                    sl = ShortlistModel.model_validate(
                        {
                            "domain": raw.get("domain") or domain_hint or fallback.domain,
                            "title": raw.get("title") or fallback.title,
                            "description": raw.get("description") or fallback.description,
                            "objects": list((raw.get("objects") or {}).keys()) or fallback.objects,
                            "fields": meta_sl,
                            "jargon": fallback.jargon,
                            "vocabulary": fallback.vocabulary,
                            "llm_hints": fallback.llm_hints,
                            "examples": examples or fallback.model_dump()["examples"],
                            "negatives": raw.get("negatives") or fallback.negatives,
                        }
                    )
                    blueprint = compile_jobs(
                        sl, goal=session.goal, jobs=jobs, domain_hint=domain_hint
                    )
                else:
                    blueprint = compile_jobs(
                        shortlist_for_ideas(ideas, goal=session.goal, seed=seed),
                        goal=session.goal,
                        jobs=jobs,
                        domain_hint=domain_hint,
                    )
                session.design_mode = "llm"
                settings = resolve_tier_settings(tier, home=self.ws.home)
                session.designer_model = settings.model
            except Exception as exc:
                session.design_fallback_reason = str(exc)
                blueprint = None
        if blueprint is None:
            try:
                blueprint = compile_jobs(
                    shortlist_for_ideas(ideas, goal=session.goal, seed=seed),
                    goal=session.goal,
                    jobs=jobs,
                    domain_hint=domain_hint,
                )
                session.design_mode = "atlas"
                session.designer_model = None
            except Exception:
                return self._design_and_activate(session, use_llm=False, tier=tier)
        if session.release_mode:
            # The atlas can lend useful fields and routing examples without
            # deciding what the person's app is called. Keep the release pack
            # named after the person's subject, even when the prior came from a
            # neighbouring practice.
            topic_title = release_topic[:1].upper() + release_topic[1:]
            blueprint["title"] = topic_title or "Your notes"
            blueprint["description"] = f"Keep notes about {release_topic} in your own words."
        blueprint["domain"] = self._unique_domain(blueprint["domain"])
        agent = blueprint.get("agent")
        if isinstance(agent, dict):
            agent["name"] = blueprint["domain"]
        meta = blueprint.setdefault("meta", {})
        meta["atlas_ideas"] = [i.id for i in ideas]
        meta["atlas_cursor"] = session.atlas_cursor
        meta["jobs"] = jobs
        session.blueprint = blueprint
        session.domain = blueprint["domain"]
        session.questions = []
        session.state = "interview"
        self.store.save(session)
        return self._generate(session)

    def _install_starter(
        self, session: WizardSession, starter: dict[str, Any]
    ) -> dict[str, Any]:
        name = str(starter["name"])
        if session.selected_ideas:
            ideas = self._resolve_idea_nodes(session, list(session.selected_ideas))
            if ideas:
                hero = self._hero_for_commit(session, ideas[0])
                if not analog_covers_hero(bundled_view_blocks(name), hero):
                    provider = self._tiered_provider()
                    return self._design_and_activate_from_ideas(
                        session, ideas, use_llm=provider.has_live_keys(), tier="sota"
                    )
        title = str(starter.get("title") or name)
        already = self.harness.packs.get(name) is not None
        if not already:
            installed = self.harness.activate_pack(name)
            # Prefer the activated pack's name/title (aliases resolve).
            name = str(installed.get("name") or name)
            title = str(installed.get("title") or title)
            pack = self.harness.packs.get(name)
        else:
            pack = self.harness.packs.get(name)
        if pack is None:
            # Fall through to scaffold if activate somehow failed.
            return self._design_and_activate(session, use_llm=False, tier="sota")

        session.design_mode = "starter"
        session.domain = pack.name
        session.pack_version = pack.version
        session.pack_path = str(pack.root)
        session.activated = True
        session.state = "test_drive"
        session.blueprint = {
            "domain": pack.name,
            "title": pack.manifest.title,
            "description": pack.manifest.description,
            "objects": {
                oname: {
                    "title_field": obj.title_field,
                    "fields": list(obj.fields.keys()),
                }
                for oname, obj in pack.objects.items()
            },
        }
        shortlist = [
            f.replace("_", " ")
            for obj in pack.objects.values()
            for f in list(obj.fields.keys())[:8]
        ]
        verb = "already here" if already else "Installed"
        chips = " · ".join(list(dict.fromkeys(shortlist))[:6]) if shortlist else ""
        message = (
            f"{verb} {title}. Talk about it and we'll file it"
            + (f": {chips}." if chips else ".")
        )
        turn = self._turn(session, message=message, awaiting="capture")
        turn["pack"] = {
            "name": pack.name,
            "version": pack.version,
            "title": pack.manifest.title,
            "path": str(pack.root),
        }
        turn["status"] = "live"
        turn["shortlist"] = shortlist[:8]
        turn["proposal"] = {
            "domain": pack.name,
            "title": pack.manifest.title,
            "description": pack.manifest.description,
            "design_mode": "starter",
            "objects": [
                {"name": oname, "fields": list(obj.fields.keys())}
                for oname, obj in pack.objects.items()
            ],
        }
        return turn

    def _design_and_activate(
        self,
        session: WizardSession,
        *,
        use_llm: bool,
        tier: str,
    ) -> dict[str, Any]:
        """Design (or scaffold), skip interview, install, return ready-to-capture turn."""
        turn = self._design_and_propose(session, use_llm=use_llm, tier=tier)
        if session.state == "failed":
            return turn
        # Skip interview — apply defaults and generate/activate in one shot.
        if session.state == "interview":
            turn = self._generate(session)
            # A model pack that fails dry-run must not leave the user with
            # nothing installed — fall back to the labeled keyword scaffold.
            if (
                use_llm
                and session.state == "failed"
                and session.design_mode == "llm"
            ):
                reason = turn.get("message") or "model pack failed dry-run"
                return self._scaffold_after_llm_failure(session, reason=reason, tier=tier)
            return turn
        return turn

    def _scaffold_after_llm_failure(
        self,
        session: WizardSession,
        *,
        reason: str,
        tier: str,
    ) -> dict[str, Any]:
        """Install the deterministic scaffold after an LLM design could not activate."""
        session.design_fallback_reason = reason
        session.design_mode = "scaffold"
        session.designer_model = None
        session.state = "interview"
        session.activated = False
        session.pack_path = None
        session.domain = None
        session.dry_run = {}
        session.acceptance = {}
        session.blueprint = {}
        session.questions = []
        session.answers = {}
        turn = self._design_and_propose(session, use_llm=False, tier=tier)
        # Preserve the LLM failure reason (propose clears it only when design_error set).
        session.design_fallback_reason = reason
        if session.state == "failed":
            return turn
        if session.state == "interview":
            return self._generate(session)
        return turn

    def wizard_reply(self, session_id: str, text: str) -> dict[str, Any]:
        session = self.store.load(session_id)
        if session is None:
            return {
                "error": f"unknown wizard session: {session_id}",
                "session_id": session_id,
                "user_message": "This creation session is no longer available. Start again when you are ready.",
            }
        session.history.append({"role": "user", "text": text})

        if session.state == "fork":
            turn = self._handle_fork(session, text)
        elif session.state == "looks":
            turn = self._handle_looks(session, text)
        elif session.state == "elicit":
            turn = self._handle_elicit(session, text)
        elif session.state == "schema_preview":
            turn = self._handle_schema_preview(session, text)
        elif session.state == "model_confirm":
            turn = self._handle_model_confirm(session, text)
        elif session.state == "interview":
            turn = self._handle_interview(session, text)
        elif session.state == "test_drive":
            turn = self._handle_test_drive(session, text)
        elif session.state == "repair":
            turn = self._handle_repair(session, text)
        elif session.state == "hardening_confirm":
            turn = self._handle_hardening_confirm(session, text)
        elif session.state in {"done", "failed"}:
            turn = self._turn(
                session,
                message="This creation session is closed. Start a new one when you are ready.",
            )
        else:
            turn = self._turn(session, message="Something interrupted this creation step. Your choices are saved.")
        return release_turn(turn, session)

    def resume(self, session_id: str) -> dict[str, Any]:
        """Return the latest release view for a saved session."""
        session = self.store.load(session_id)
        if session is None:
            return {
                "error": f"unknown wizard session: {session_id}",
                "session_id": session_id,
                "user_message": "This creation session is no longer available. Start again when you are ready.",
            }
        last = next(
            (
                item.get("text")
                for item in reversed(session.history)
                if item.get("role") == "assistant" and item.get("text")
            ),
            "Your choices are saved. Continue when you are ready.",
        )
        awaiting = {
            "fork": "fork",
            "looks": "look",
            "elicit": "elicit",
            "schema_preview": "schema_confirm",
            "model_confirm": "model_confirm",
            "interview": "answers",
            "test_drive": "capture",
            "repair": "repair",
            "hardening_confirm": "confirm",
        }.get(session.state)
        turn = self._turn(
            session,
            message=str(last),
            awaiting=awaiting,
            done=session.state == "done",
            record=False,
        )
        if session.state == "fork":
            turn["neighborhood"] = session.neighborhood
        elif session.state == "looks":
            turn["looks"] = looks_public(session.looks, include_html=True)
            turn["selected_look_id"] = session.selected_look_id
            turn["neighborhood"] = session.neighborhood
        elif session.state == "schema_preview":
            turn["schema_preview"] = session.schema_preview
        elif session.state in {"test_drive", "repair", "hardening_confirm", "done"}:
            if session.domain:
                turn["pack"] = {
                    "name": session.domain,
                    "version": session.pack_version,
                    "title": (session.blueprint or {}).get("title"),
                    "path": session.pack_path,
                }
            turn["real_captures"] = session.real_captures
            turn["acceptance"] = session.acceptance
        return release_turn(turn, session)

    def cancel(self, session_id: str) -> dict[str, Any]:
        """Stop future work and preserve the saved choices and receipts."""
        session = self.store.load(session_id)
        if session is None:
            return {
                "error": f"unknown wizard session: {session_id}",
                "session_id": session_id,
                "user_message": "This creation session is no longer available. Start again when you are ready.",
            }
        session.state = "failed"
        self.store.save(session)
        turn = self._turn(
            session,
            message="Your choices are saved. Creation stopped here; you can start a new app any time.",
            done=True,
        )
        return release_turn(turn, session)

    def _model_confirm_turn(self, session: WizardSession) -> dict[str, Any]:
        from domain_foundry_core.llm.pricing import estimate_cost_usd

        settings = resolve_tier_settings("sota", home=self.ws.home)
        routine = resolve_tier_settings("routine", home=self.ws.home)
        estimate = round(
            estimate_cost_usd(
                model=settings.model,
                input_tokens=_DESIGN_INPUT_TOKENS,
                output_tokens=_DESIGN_OUTPUT_TOKENS,
            ),
            4,
        )
        message = (
            "Designing a domain is one deliberate call to a stronger reasoning "
            "model than your everyday chat model. Domain design benefits from "
            f"it. I'd use {settings.model} (your sota tier), estimated "
            f"~${estimate:.2f} for this design. Reply 'yes' to go ahead, "
            f"'use routine' to design with {routine.model} instead, or "
            "'no model' to build a keyword scaffold without any model call."
        )
        turn = self._turn(session, message=message, awaiting="model_confirm")
        cfg = load_llm_config(self.ws.home)
        turn["designer"] = {
            "provider": cfg.provider or "tiered",
            "tier": "sota",
            "model": settings.model,
            "est_cost_usd": float(estimate),
            "routine_model": routine.model,
        }
        return turn

    def _handle_model_confirm(self, session: WizardSession, text: str) -> dict[str, Any]:
        low = text.strip().lower()
        if "routine" in low:
            return self._design_and_propose(session, use_llm=True, tier="routine")
        if re.search(r"\bno\s+model\b", low) or re.search(r"\bnot\s+now\b", low) or (
            _CANCEL_RE.search(low) and not _CONFIRM_RE.search(low)
        ):
            return self._design_and_propose(session, use_llm=False, tier="sota")
        if _CONFIRM_RE.search(low):
            return self._design_and_propose(session, use_llm=True, tier="sota")
        return self._model_confirm_turn(session)

    def _design_and_propose(
        self,
        session: WizardSession,
        *,
        use_llm: bool,
        tier: str,
    ) -> dict[str, Any]:
        blueprint: dict[str, Any] | None = None
        design_error: str | None = None
        if use_llm:
            settings = resolve_tier_settings(tier, home=self.ws.home)
            try:
                blueprint = LLMBlueprintDesigner().design(
                    session.goal,
                    llm=self._provider_with_cassette(self._tiered_provider()),
                    tier=tier,
                )
                session.design_mode = "llm"
                session.designer_model = settings.model
            except DesignError as exc:
                # A bad response, unavailable endpoint, or invalid rendered pack
                # must never install anything.  The user gets a deterministic,
                # explicitly labelled scaffold instead.
                design_error = str(exc)
                blueprint = None

        if blueprint is None:
            blueprint = bp.build_blueprint(session.goal)
            session.design_mode = "scaffold"
            session.designer_model = None
            if design_error is not None:
                session.design_fallback_reason = design_error
            # else: keep any prior design_fallback_reason (dry-run fallback path)

        try:
            blueprint = validate_blueprint(blueprint)
        except Exception as exc:
            session.state = "failed"
            self.store.save(session)
            return self._turn(session, message=f"Could not validate the domain blueprint: {exc}")

        blueprint["domain"] = self._unique_domain(blueprint["domain"])
        agent = blueprint.get("agent")
        if isinstance(agent, dict):
            agent["name"] = blueprint["domain"]
        else:
            blueprint["agent"] = bp.build_agent_spec(blueprint)
        session.blueprint = blueprint
        session.domain = blueprint["domain"]
        session.questions = blueprint.get("questions", [])
        session.state = "interview"
        self.store.save(session)

        turn = self._proposal_turn(session)
        if design_error is not None:
            turn["message"] = (
                "Couldn't shape this interest area with the model "
                f"({design_error}). Using a simple log for now. You can add detail "
                "later, or try again with a clearer description. "
            ) + turn["message"]
            turn["design_fallback"] = "scaffold"
        return turn

    def suggest_hardening(self, domain: str, *, threshold: int = 3) -> dict[str, Any] | None:
        """Neighbor idea from residue, else repeated corrections / leftover fields."""
        from domain_foundry_core.wizard.cobuild import suggest_neighbor

        neighbor = suggest_neighbor(
            self.ws,
            domain,
            overlay=self._atlas_overlay(),
            threshold=threshold,
        )
        if neighbor:
            return neighbor

        import json as _json

        conn = connect_ro(self.ws.ledger_db)
        try:
            rows = conn.execute(
                """
                SELECT reason_code, COUNT(*) AS n
                FROM correction_event
                WHERE entry_id IN (
                    SELECT id FROM entry WHERE domain = ?
                )
                GROUP BY reason_code
                ORDER BY n DESC
                """,
                (domain,),
            ).fetchall()
            for r in rows:
                if int(r["n"]) >= threshold and r["reason_code"] not in {"undo", "mark_wrong"}:
                    return {
                        "domain": domain,
                        "reason_code": r["reason_code"],
                        "count": int(r["n"]),
                        "suggestion": (
                            f"You've corrected '{r['reason_code']}' {r['n']}× in {domain}. "
                            "Want to harden the pack (e.g. fix a unit or add a field)?"
                        ),
                    }

            residue_counts: dict[str, int] = {}
            cr_rows = conn.execute(
                """
                SELECT payload_json FROM change_request
                WHERE domain = ?
                ORDER BY created_at DESC
                LIMIT 200
                """,
                (domain,),
            ).fetchall()
            for row in cr_rows:
                try:
                    payload = _json.loads(row["payload_json"] or "{}")
                except Exception:
                    continue
                residue = payload.get("residue") or {}
                if isinstance(residue, dict):
                    inner = residue.get("residue") if "residue" in residue else residue
                    if isinstance(inner, dict):
                        for key in inner:
                            if key and key not in {"unparsed", "notes"}:
                                residue_counts[str(key)] = residue_counts.get(str(key), 0) + 1
            for key, n in sorted(residue_counts.items(), key=lambda kv: -kv[1]):
                if n >= threshold:
                    return {
                        "domain": domain,
                        "reason_code": f"residue:{key}",
                        "count": n,
                        "suggestion": (
                            f"'{key}' showed up as leftover fact {n}× in {domain}. "
                            "Want to add it as a field?"
                        ),
                    }
        except Exception:
            return None
        finally:
            conn.close()
        return None

    # ------------------------------------------------------------- interview
    def _handle_interview(self, session: WizardSession, text: str) -> dict[str, Any]:
        answers = bp.parse_answers(text, session.questions)
        session.answers.update(answers)
        session.blueprint = bp.apply_answer(session.blueprint, session.answers)
        self.store.save(session)
        return self._generate(session)

    # ------------------------------------------------------------- generate
    def _generate(self, session: WizardSession) -> dict[str, Any]:
        draft_dir = self.store.draft_dir(session.session_id)
        if draft_dir.exists():
            shutil.rmtree(draft_dir)
        try:
            blueprint = validate_blueprint(session.blueprint)
        except Exception as exc:
            session.state = "failed"
            self.store.save(session)
            return self._turn(session, message=f"Generated blueprint failed validation: {exc}")
        session.blueprint = blueprint

        report: dict[str, Any] = {}
        for _round in range(MAX_REGEN_ROUNDS + 1):
            bp.write_pack(blueprint, draft_dir, version=session.pack_version)
            try:
                load_pack(draft_dir, validate=True)
            except PackValidationError as exc:
                session.state = "failed"
                self.store.save(session)
                return self._turn(session, message=f"Generated pack failed validation: {exc}")

            report = self._dry_run(draft_dir)
            if report["accuracy"] >= DRY_RUN_THRESHOLD:
                break
            # Failures regenerate with feedback: add targeted rules (plan §6.1).
            if not self._add_feedback_rules(blueprint, report["failures"]):
                break

        session.dry_run = report
        if report["accuracy"] < DRY_RUN_THRESHOLD:
            session.state = "failed"
            self.store.save(session)
            return self._turn(
                session,
                message=(
                    f"Dry-run routing only reached {report['accuracy']:.0%} "
                    f"({report['routed']}/{report['total']}); needs ≥{DRY_RUN_THRESHOLD:.0%}."
                ),
            )

        # Held-out acceptance is independent of the generated examples.  A
        # missing suite is an explicit uncovered result, never an implicit pass.
        suite_path = self._heldout_suite_path()
        try:
            suite = load_suite(suite_path) if suite_path.exists() else []
        except Exception as exc:
            suite = []
            session.acceptance = {
                "total": 0,
                "passed": 0,
                "accuracy": 0.0,
                "failures": [],
                "heuristic": None,
                "provider": None,
                "provider_live": False,
                "covered": False,
                "error": f"held-out suite unavailable: {exc}",
            }
        else:
            cases = select_cases(session.goal, suite)
            tiered = self._tiered_provider()
            provider = (
                self._provider_with_cassette(tiered)
                if tiered.has_live_keys()
                else None
            )
            session.acceptance = acceptance_run(draft_dir, cases, llm=provider)

        # Activate: install the validated pack into the live workspace.
        installed = self.harness.packs.add(draft_dir, force=True)
        session.domain = installed.name
        session.pack_version = installed.version
        session.pack_path = str(installed.root)
        session.activated = True
        # Hot-register Expert child config with Supervisor (launchd stubbed).
        # Honesty stays on activate_pack / mesh tests — omit from hobby turns.
        self.harness.register_expert(installed.name)
        _write_status(installed.root, session, live=False)

        # Install anyway — held-out misses become a banner, not a blocking gate.
        # (Plan: repair stays as Inbox/banner after they can already log.)
        session.state = "test_drive"
        self.store.save(session)
        turn = self._activated_turn(session)
        # The held-out sentence is replayed here and nowhere earlier: the pack
        # has to exist and be installed before "does it file?" means anything.
        replay = self._replay_held_out(session)
        held_out_note = self._held_out_message(session, replay)
        if held_out_note:
            turn["message"] = f"{turn['message']}{held_out_note}"
        if replay is not None:
            turn["held_out"] = replay
        if (
            session.design_mode == "llm"
            and session.acceptance.get("covered")
            and session.acceptance.get("accuracy", 0.0) < ACCEPTANCE_THRESHOLD
        ):
            misses = len(session.acceptance.get("failures") or [])
            turn["message"] = (
                f"{turn['message']} Note: {misses} held-out phrase(s) missed. "
                "You can teach them later. The place is ready to use now."
            )
            turn["needs_repair"] = True
        # Hobby install receipts omit mesh expert stub noise.
        turn["pack"] = {
            "name": session.domain,
            "version": session.pack_version,
            "title": (session.blueprint or {}).get("title"),
            "path": session.pack_path,
        }
        return turn

    def _replay_held_out(self, session: WizardSession) -> dict[str, Any] | None:
        """Route the second elicited sentence through the real router.

        The design never saw this sentence: not the shortlist, not the
        examples, not the compiled rules. So where it lands is a measurement
        and not a restatement. ``route_text`` does not persist anything, so the
        check costs the user no entry they did not ask for.
        """
        text = self._held_out_sample(session)
        if not text or not session.domain:
            return None
        try:
            self.harness.packs.reload()
            result = self.harness.router.route_text(text, channel="wizard")
        except Exception as exc:  # noqa: BLE001 - an honest report beats a crash
            return {"text": text, "filed": False, "error": f"{type(exc).__name__}: {exc}"}
        spans = [
            {
                "domain": span.domain,
                "object_type": span.object_type,
                "operation": span.operation,
                "disposition": span.disposition,
                "confidence": span.confidence,
            }
            for span in result.spans
        ]
        mine = next((span for span in spans if span["domain"] == session.domain), None)
        filed = mine is not None and mine["disposition"] not in {"unfiled", "ledger_only"}
        return {
            "text": text,
            "filed": filed,
            "object_type": mine["object_type"] if filed and mine else None,
            "disposition": mine["disposition"] if mine else None,
            "routed": spans,
        }

    def _held_out_message(self, session: WizardSession, replay: dict[str, Any] | None) -> str:
        """One honest sentence about the sentence the design was not shown."""
        if replay is None:
            if session.elicit_prompts and not session.elicited_samples:
                return (
                    " You skipped the examples, so this is built from your goal's "
                    "keywords alone and nothing has checked it yet. Log a real note "
                    "and we'll see."
                )
            if session.elicit_prompts and len(session.elicited_samples) == 1:
                return (
                    " No second example, so nothing independent has checked this. "
                    "Log a real note and we'll see."
                )
            return ""
        quoted = replay["text"] if len(replay["text"]) <= 70 else replay["text"][:69] + "…"
        if replay.get("error"):
            return f" I couldn't replay “{quoted}”: {replay['error']}."
        if replay["filed"]:
            if replay.get("disposition") == "review":
                return (
                    f" Your second example, “{quoted}”, went to review as a "
                    f"{session.domain}.{replay['object_type']}; approve it and it lands."
                )
            return (
                f" Your second example, “{quoted}”, filed into "
                f"{session.domain}.{replay['object_type']}. Good."
            )
        return (
            f" Your second example, “{quoted}”, didn't file; it goes to the unfiled "
            "card for review. Tell me what it should be and I'll learn it."
        )

    def _dry_run(self, draft_dir: Path) -> dict[str, Any]:
        pack = load_pack(draft_dir, validate=True)
        cases = []
        for ex in pack.routing.examples:
            expect = {
                "domain": pack.name,
                "object_type": ex.expect.get("object"),
                "operation": ex.expect.get("operation", "create"),
            }
            cases.append({"raw_text": ex.text, "expected": {"captures": [expect]}})

        tmp = Path(tempfile.mkdtemp(prefix="wiz_dry_"))
        try:
            tmp_ws = Workspace(tmp)
            reg = PackRegistry(tmp_ws)
            reg.add(draft_dir, force=True)
            router = Router(tmp_ws, registry=reg, llm=HeuristicProvider(), cost_cap=999)
            total = 0
            correct = 0
            failures: list[dict[str, Any]] = []
            for case in cases:
                result = router.route_text(case["raw_text"], channel="wizard")
                spans = [
                    {
                        "domain": s.domain,
                        "object_type": s.object_type,
                        "operation": s.operation,
                        "fields": s.fields,
                    }
                    for s in result.spans
                ]
                scored = score_case(case, spans)
                total += 1
                if scored.ok:
                    correct += 1
                else:
                    want = case["expected"]["captures"][0]
                    failures.append({"text": case["raw_text"], "expected_object": want["object_type"]})
            accuracy = correct / total if total else 0.0
            return {"total": total, "routed": correct, "accuracy": accuracy, "failures": failures}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _add_feedback_rules(self, blueprint: dict[str, Any], failures: list[dict[str, Any]]) -> bool:
        added = False
        for fail in failures:
            token = _distinctive_token(fail["text"])
            obj = fail["expected_object"]
            if not token or not obj:
                continue
            blueprint["rules"].append({
                "match": re.escape(token),
                "object": obj,
                "confidence_boost": 0.25,
                "operation": "create",
            })
            added = True
        return added

    # ------------------------------------------------------------ test-drive
    def _handle_test_drive(self, session: WizardSession, text: str) -> dict[str, Any]:
        stripped = text.strip()
        if re.fullmatch(r"(?:later|not now|come back later|skip for now)", stripped, re.IGNORECASE):
            turn = self._activated_turn(session)
            turn["message"] = "Your choices are saved. Come back when you have a real note to try."
            return turn
        # Legacy clients still send "skip" after create; seamless path already
        # activated, so treat skip as a no-op ready turn.
        if re.fullmatch(r"skip(?:\s+(?:it|questions?|defaults?))?", stripped, re.IGNORECASE):
            turn = self._activated_turn(session)
            turn["pack"] = {
                "name": session.domain,
                "version": session.pack_version,
                "title": (session.blueprint or {}).get("title"),
                "path": session.pack_path,
            }
            return turn

        if is_session_signoff(stripped) and not looks_like_edit(stripped):
            if session.release_mode and session.real_captures < 1:
                turn = self._activated_turn(session)
                turn["first_use_blocked"] = True
                turn["message"] = (
                    "Your choices are saved. Add one note that goes to the right "
                    "place before calling it ready."
                )
                return turn
            session.state = "done"
            self.store.save(session)
            return self._turn(session, message=f"Domain '{session.domain}' is ready. Happy tracking!", done=True)

        if looks_like_edit(stripped):
            return self._start_hardening(session, stripped)

        receipt = self.harness.capture(text, channel="wizard")
        entry_id = receipt.entry_id
        session.captured_entries.append(entry_id)
        session.test_drive_remaining = max(0, session.test_drive_remaining - 1)
        applied_to_domain = receipt.status == "applied" and any(
            span.domain == session.domain and span.disposition not in {"unfiled", "ledger_only"}
            for span in receipt.routed
        )
        if applied_to_domain:
            session.real_captures += 1
            if session.pack_path:
                _write_status(Path(session.pack_path), session, live=_eligible_live(session))
        self.store.save(session)
        turn = self._capture_turn(session, receipt)
        if applied_to_domain and _status_of(session) == "live":
            turn["message"] += " This applied real capture cleared the activation gate; the domain is now live."
        turn["status"] = _status_of(session)
        turn["real_captures"] = session.real_captures
        return turn

    # --------------------------------------------------------------- repair
    def _repair_turn(
        self,
        session: WizardSession,
        *,
        message: str | None = None,
    ) -> dict[str, Any]:
        failures = (session.acceptance or {}).get("failures") or []
        listing = "; ".join(
            f"“{failure['capture']}” → {failure.get('routed_domain', '_unfiled')}"
            for failure in failures[:5]
        )
        object_name = next(iter(session.blueprint.get("objects") or {"entry": {}}))
        if message is None:
            if failures:
                first = failures[0].get("capture", "the missed phrase")
                hint = f'“{first[:40]}…” is a {object_name}'
                message = (
                    f"Honest check: {len(failures)} of {session.acceptance.get('total', 0)} "
                    f"realistic phrases missed ({listing}). Let's repair it. Reply with "
                    f'example "{hint}" to teach a phrase, describe a schema change '
                    '("add a grade field"), or say "keep it as a scaffold".'
                )
            else:
                message = (
                    "The held-out check needs more coverage. Teach a phrase, describe a "
                    'schema change, or say "keep it as a scaffold".'
                )
        turn = self._turn(session, message=message, awaiting="repair")
        turn["acceptance"] = session.acceptance
        turn["repair_round"] = min(session.repair_rounds + 1, MAX_REPAIR_ROUNDS)
        turn["repair_rounds"] = session.repair_rounds
        turn["repair_limit"] = MAX_REPAIR_ROUNDS
        turn["dry_run"] = session.dry_run
        turn["pack"] = {
            "name": session.domain,
            "version": session.pack_version,
            "path": session.pack_path,
        }
        return turn

    def _handle_repair(self, session: WizardSession, text: str) -> dict[str, Any]:
        stripped = text.strip()
        low = stripped.lower()
        if _KEEP_SCAFFOLD_RE.search(low) or _DONE_RE.search(stripped):
            session.state = "test_drive"
            if session.pack_path:
                _write_status(Path(session.pack_path), session, live=False)
            self.store.save(session)
            turn = self._turn(
                session,
                message=(
                    f"Kept as a scaffold. {len(session.acceptance.get('failures') or [])} "
                    "held-out phrases still miss. Corrections you make while using it "
                    "keep teaching it."
                ),
                awaiting="capture",
            )
            turn["acceptance"] = session.acceptance
            return turn
        if session.repair_rounds >= MAX_REPAIR_ROUNDS:
            session.state = "test_drive"
            if session.pack_path:
                _write_status(Path(session.pack_path), session, live=False)
            self.store.save(session)
            turn = self._turn(
                session,
                message=(
                    f"{MAX_REPAIR_ROUNDS} repair rounds done. Keeping it as an honest "
                    "scaffold. Use it; your corrections continue to improve routing."
                ),
                awaiting="capture",
            )
            turn["acceptance"] = session.acceptance
            return turn

        self.harness.packs.reload()
        pack = self.harness.packs.get(str(session.domain))
        if pack is None:
            return self._repair_turn(session, message="Cannot repair: the domain is not installed.")

        if looks_like_edit(stripped):
            plan = build_plan(stripped, pack)
            if not plan.ok:
                return self._repair_turn(session, message=f"I couldn't apply that repair: {plan.error}")
            result = apply_plan(self.ws, pack, plan, edit_text=stripped)
            self.harness.packs.reload()
            session.pack_version = result.get("version", session.pack_version)
        else:
            failures = (session.acceptance or {}).get("failures") or []
            feedback = [
                {
                    "text": failure.get("capture", ""),
                    "expected_object": failure.get("expected_object")
                    or next(iter(session.blueprint.get("objects") or {"entry": {}})),
                }
                for failure in failures
            ]
            if not self._add_feedback_rules(session.blueprint, feedback):
                return self._repair_turn(
                    session,
                    message=(
                        "I couldn't find a teachable phrase in that feedback. Give me a "
                        'specific held-out phrase or say "keep it as a scaffold".'
                    ),
                )
            try:
                validate_blueprint(session.blueprint)
                bp.write_pack(
                    session.blueprint,
                    Path(session.pack_path or pack.root),
                    version=session.pack_version,
                )
            except Exception as exc:
                return self._repair_turn(session, message=f"I couldn't write that repair safely: {exc}")
            self.harness.packs.reload()

        session.repair_rounds += 1
        session.acceptance = self._acceptance_for_session(session)
        if session.pack_path:
            _write_status(Path(session.pack_path), session, live=False)
        self.store.save(session)

        if session.acceptance.get("accuracy", 0.0) >= ACCEPTANCE_THRESHOLD:
            session.state = "test_drive"
            self.store.save(session)
            turn = self._turn(
                session,
                message=(
                    f"Repaired. Held-out is now {session.acceptance['accuracy']:.0%}. "
                    "One real applied capture from you and it can become live. Try it."
                ),
                awaiting="capture",
            )
            turn["acceptance"] = session.acceptance
            return turn

        if session.repair_rounds >= MAX_REPAIR_ROUNDS:
            session.state = "test_drive"
            self.store.save(session)
            turn = self._turn(
                session,
                message=(
                    f"{MAX_REPAIR_ROUNDS} repair rounds done. Keeping it as an honest "
                    f"scaffold. {len(session.acceptance.get('failures') or [])} "
                    "held-out phrases still miss."
                ),
                awaiting="capture",
            )
            turn["acceptance"] = session.acceptance
            return turn
        session.state = "repair"
        self.store.save(session)
        return self._repair_turn(session)

    def _acceptance_for_session(self, session: WizardSession) -> dict[str, Any]:
        suite_path = self._heldout_suite_path()
        if not suite_path.exists():
            return acceptance_run(Path(session.pack_path or "."), [], llm=None)
        suite = load_suite(suite_path)
        cases = select_cases(session.goal, suite)
        tiered = self._tiered_provider()
        provider = (
            self._provider_with_cassette(tiered) if tiered.has_live_keys() else None
        )
        return acceptance_run(Path(session.pack_path or "."), cases, llm=provider)

    # -------------------------------------------------------------- hardening
    def _start_hardening(self, session: WizardSession, text: str) -> dict[str, Any]:
        self.harness.packs.reload()
        pack = self.harness.packs.get(str(session.domain))
        if pack is None:
            return self._turn(session, message="Cannot harden: the domain is not installed.")
        plan = build_plan(text, pack)
        if not plan.ok:
            return self._turn(
                session,
                message=f"I couldn't turn that into a schema change: {plan.error}",
            )
        session.pending_edit = {"text": text, "plan": plan.to_dict()}
        session.state = "hardening_confirm"
        self.store.save(session)
        return self._diff_turn(session, plan.to_dict())

    def _handle_hardening_confirm(self, session: WizardSession, text: str) -> dict[str, Any]:
        if looks_like_edit(text):
            # A new edit supersedes the pending one.
            session.state = "test_drive"
            return self._start_hardening(session, text.strip())
        if _CANCEL_RE.search(text) and not _CONFIRM_RE.search(text):
            session.pending_edit = {}
            session.state = "test_drive"
            self.store.save(session)
            return self._turn(session, message="Edit discarded. Keep test-driving or describe another change.")
        if not _CONFIRM_RE.search(text):
            return self._diff_turn(
                session, session.pending_edit.get("plan", {}),
                message="Reply 'confirm' to apply this edit, or 'cancel' to discard.",
            )

        pack = self.harness.packs.get(str(session.domain))
        if pack is None:
            return self._turn(session, message="Cannot apply: the domain is not installed.")
        edit_text = session.pending_edit.get("text", "")
        plan = build_plan(edit_text, pack)
        result = apply_plan(self.ws, pack, plan, edit_text=edit_text)
        self.harness.packs.reload()
        session.pending_edit = {}
        session.pack_version = result.get("version", session.pack_version)
        session.state = "test_drive"
        self.store.save(session)
        msg = (
            f"Applied. Migration {result.get('migration')} added "
            f"{', '.join(result.get('added') or []) or 'changes'} to "
            f"{session.domain}.{plan.object} (v{result.get('version')}). "
            "Keep capturing, edit again, or say 'done'."
        )
        turn = self._turn(session, message=msg)
        turn["hardening"] = result
        return turn

    # ------------------------------------------------------------------ views
    def _proposal_turn(self, session: WizardSession) -> dict[str, Any]:
        b = session.blueprint
        design_label = "LLM-designed" if session.design_mode == "llm" else "scaffold"
        objects = [
            {
                "name": name,
                "title_field": obj["title_field"],
                "fields": list(obj["fields"]),
            }
            for name, obj in b["objects"].items()
        ]
        message = (
            f"Here's a {design_label} proposal for '{b['title']}' ({b['domain']}): "
            f"{len(objects)} object(s), {len(b['examples'])} example utterances. "
            f"I have {len(session.questions)} quick question(s). Answer any, or reply 'skip' to accept defaults."
        )
        turn = self._turn(session, message=message, awaiting="answers")
        turn["proposal"] = {
            "domain": b["domain"],
            "title": b["title"],
            "description": b["description"],
            "interpretation": b["interpretation"],
            "objects": objects,
            "example_count": len(b["examples"]),
            "archetype": b.get("archetype"),
            "design_mode": session.design_mode,
            "designer_model": session.designer_model,
        }
        turn["questions"] = session.questions
        return turn

    def _activated_turn(self, session: WizardSession) -> dict[str, Any]:
        acceptance = session.acceptance or {}
        shortlist = []
        meta = (session.blueprint or {}).get("meta") or {}
        if isinstance(meta.get("shortlist"), list):
            shortlist = [
                str(f.get("name") if isinstance(f, dict) else f).replace("_", " ")
                for f in meta["shortlist"]
            ]
        elif session.blueprint.get("objects"):
            for obj in (session.blueprint.get("objects") or {}).values():
                if isinstance(obj, dict):
                    fields = obj.get("fields")
                    if isinstance(fields, dict):
                        shortlist.extend(k.replace("_", " ") for k in fields)
                    elif isinstance(fields, list):
                        shortlist.extend(str(k).replace("_", " ") for k in fields)
        chips = " · ".join(list(dict.fromkeys(shortlist))[:8])
        title = (session.blueprint or {}).get("title") or session.domain
        if session.design_mode == "scaffold":
            if session.design_fallback_reason:
                message = (
                    f"Couldn't shape {title} with the model, so it's a simple "
                    "log for now. Log one real note and we'll file it."
                )
            else:
                message = (
                    f"{title} is ready as a simple log. "
                    "Add a key in Settings to shape this interest area later. "
                    "Log one real note and we'll file it."
                )
        else:
            message = (
                f"{title} is ready to try"
                + (f". We'll file {chips}." if chips else ".")
                + " Log one real note and we'll file it."
            )
        if acceptance.get("covered") and acceptance.get("accuracy", 1.0) < 0.9:
            message += (
                f" ({acceptance.get('passed', 0)}/{acceptance.get('total', 0)} "
                "held-out phrases matched. You can teach more later.)"
            )
        turn = self._turn(session, message=message, awaiting="capture")
        turn["pack"] = {
            "name": session.domain,
            "version": session.pack_version,
            "title": title,
            "path": session.pack_path,
        }
        turn["dry_run"] = session.dry_run
        turn["acceptance"] = session.acceptance
        turn["status"] = _status_of(session)
        turn["real_captures"] = session.real_captures
        turn["shortlist"] = shortlist[:8]
        turn["proposal"] = {
            "domain": session.domain,
            "title": title,
            "description": (session.blueprint or {}).get("description"),
            "design_mode": session.design_mode,
            "objects": [
                {
                    "name": name,
                    "fields": list(obj["fields"])
                    if isinstance(obj.get("fields"), list | dict)
                    else [],
                }
                for name, obj in ((session.blueprint or {}).get("objects") or {}).items()
                if isinstance(obj, dict)
            ],
        }
        return turn

    def _capture_turn(self, session: WizardSession, receipt: Any) -> dict[str, Any]:
        routed = [
            {
                "domain": s.domain,
                "object_type": s.object_type,
                "operation": s.operation,
                "disposition": s.disposition,
                "confidence": s.confidence,
            }
            for s in receipt.routed
        ]
        explanation = self._explain(receipt, routed)
        turn = self._turn(session, message=explanation, awaiting="capture")
        turn["capture"] = {
            "entry_id": receipt.entry_id,
            "status": receipt.status,
            "routed": routed,
            "test_drive_remaining": session.test_drive_remaining,
            "correct_hint": (
                "If that's wrong, reply e.g. \"no, that was <domain>\" or "
                "\"actually it was 80 not 75\", and I'll correct it in one message."
            ),
        }
        return turn

    def _explain(self, receipt: Any, routed: list[dict[str, Any]]) -> str:
        if not routed or receipt.status in {"ledger_only", "unfiled"}:
            return (
                f"Captured (status: {receipt.status}). I couldn't confidently route that "
                "into your new domain. It's safely stored. Try phrasing closer to your examples."
            )
        parts = []
        for r in routed:
            parts.append(
                f"→ {r['domain']}.{r['object_type']} ({r['operation']}, "
                f"confidence {float(r['confidence']):.0%}, {r['disposition']})"
            )
        return "Routed: " + "; ".join(parts) + "."

    def _diff_turn(self, session: WizardSession, plan: dict[str, Any], *, message: str | None = None) -> dict[str, Any]:
        summary = "; ".join(plan.get("summary") or []) or "no changes"
        msg = message or (
            f"Proposed edit to {plan.get('domain')}.{plan.get('object')}: {summary}. "
            "Reply 'confirm' to apply (writes a migration), or 'cancel'."
        )
        turn = self._turn(session, message=msg, awaiting="confirm")
        turn["diff"] = plan
        return turn

    def _turn(
        self,
        session: WizardSession,
        *,
        message: str,
        awaiting: str | None = None,
        done: bool = False,
        record: bool = True,
    ) -> dict[str, Any]:
        if record:
            session.history.append({"role": "assistant", "text": message})
            self.store.save(session)
        turn = {
            "session_id": session.session_id,
            "state": session.state,
            "message": message,
            "awaiting": awaiting,
            "done": done or session.state == "done",
            "domain": session.domain,
            "design_mode": session.design_mode,
            "designer_model": session.designer_model,
            "status": _status_of(session),
        }
        if session.design_fallback_reason:
            turn["design_fallback"] = "scaffold"
            turn["design_fallback_reason"] = session.design_fallback_reason
        if session.bridge_fallback_reason:
            turn["bridge_fallback"] = "scaffold"
            turn["bridge_fallback_reason"] = session.bridge_fallback_reason
        return turn

    # ------------------------------------------------------------------ util
    def _tiered_provider(self) -> Any:
        return build_tiered_provider(self.ws.home)

    def _provider_with_cassette(self, provider: LLMProvider) -> LLMProvider:
        mode = os.environ.get("DOMAIN_FOUNDRY_CASSETTE")
        if not mode:
            return provider
        return CassetteProvider(provider, self.ws.home / "cassettes", mode=mode)

    def _heldout_suite_path(self) -> Path:
        """Find the committed suite in a checkout or a package-adjacent tree."""

        repo_root = Path(__file__).resolve().parents[3]
        candidates = (
            repo_root / "examples" / "heldout" / _HELDOUT_FILENAME,
            Path(__file__).resolve().parent / "heldout" / _HELDOUT_FILENAME,
            Path.cwd() / "examples" / "heldout" / _HELDOUT_FILENAME,
        )
        return next((candidate for candidate in candidates if candidate.exists()), candidates[0])

    def _unique_domain(self, name: str) -> str:
        self.harness.packs.reload()
        existing = {p.name for p in self.harness.packs.list()}
        if name not in existing:
            return name
        for i in range(2, 100):
            candidate = f"{name}_{i}"
            if candidate not in existing:
                return candidate
        return f"{name}_{__import__('secrets').token_hex(2)}"


def _eligible_live(session: WizardSession) -> bool:
    acceptance = session.acceptance or {}
    provider_live = acceptance.get("provider_live")
    if provider_live is None:
        provider_live = acceptance.get("provider") not in {None, "heuristic"}
    return bool(
        session.design_mode == "llm"
        and provider_live
        and acceptance.get("covered")
        and float(acceptance.get("accuracy") or 0.0) >= ACCEPTANCE_THRESHOLD
        and session.real_captures >= 1
    )


def _status_of(session: WizardSession) -> str:
    """Return the status fact used by wizard turns and the sidecar."""

    if _eligible_live(session):
        return "live"
    if session.pack_path:
        path = Path(session.pack_path) / "foundry_status.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        else:
            if data.get("status") == "live":
                return "live"
    return "scaffold"


def _write_status(pack_root: Path, session: WizardSession, *, live: bool) -> None:
    """Persist the wizard-owned activation fact beside an installed pack."""

    if not pack_root or not pack_root.is_dir():
        return
    acceptance = session.acceptance or {}
    at = now_iso()
    payload = {
        "status": "live" if live and _eligible_live(session) else "scaffold",
        # ADR-010's evidence tier, stamped rather than implied. ``fallback_demo``
        # is the honest default: a pack built without research says so, and only
        # a completed bridge run may raise it.
        "mode": session.bridge_tier or "fallback_demo",
        "evidence_label": evidence_tier_label(session.bridge_tier),
        "bridge_spec_id": session.bridge_spec_id,
        "bridge_fallback_reason": session.bridge_fallback_reason,
        "design_mode": session.design_mode,
        "designer_model": session.designer_model,
        "heldout": {
            "covered": bool(acceptance.get("covered")),
            "passed": int(acceptance.get("passed") or 0),
            "accuracy": float(acceptance.get("accuracy") or 0.0),
            "total": int(acceptance.get("total") or 0),
            "provider": acceptance.get("provider"),
            "provider_live": bool(acceptance.get("provider_live")),
            "at": at,
        },
        "real_captures": session.real_captures,
        "updated_at": at,
        "atlas_cursor": session.atlas_cursor,
        "atlas_ideas": list(session.selected_ideas),
        "jobs": list(session.selected_jobs),
    }
    target = pack_root / "foundry_status.json"
    temporary = pack_root / ".foundry_status.json.tmp"
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def _distinctive_token(text: str) -> str | None:
    words = [w for w in re.findall(r"[a-zA-Z]{4,}", text.lower()) if w not in bp._STOPWORDS]
    if not words:
        return None
    return max(words, key=len)
