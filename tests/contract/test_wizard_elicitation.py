"""Conversational elicitation: two sentences, one of them held out (ADR-010).

Offline, for an interest the atlas does not cover, there is exactly one honest
source of domain vocabulary — the user's own words. The wizard asks for two.

The first shapes the design: its tokens become jargon, it becomes a routing
example, its nouns seed identity values. The second is held out of the
shortlist, the examples and the compiled rules, then replayed through the real
router after activation. The second one is only evidence *because* the design
never saw it, so the load-bearing test in this file is the one that proves its
words are absent from every compiled routing regex.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.wizard import engine as eng
from domain_foundry_core.wizard.shortlist import NEGATIVE_TERMS, seed_terms

GOAL = "track my lego builds"
SEED = "built the Hogwarts Castle set today, 6020 pieces"
HELD_OUT = "sorted the loose bricks into the parts bins"
# Words that occur in the held-out sentence and nowhere in the goal or the
# design sentence. If the design leaked, one of these is what leaks.
HELD_OUT_ONLY = ("sorted", "loose", "bricks", "parts", "bins")
# A third real lego sentence, unseen by both the design and the held-out check.
LATER = "finished the Millennium Falcon MOC, 3800 pieces, missing 2 tiles"
IDLE = "nice afternoon, weather was good"


def _force_unindexed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The atlas genuinely has no home for this goal."""

    def fake_neighborhood(goal, overlay=None, cursor_id=None):
        return {
            "cursor": None,
            "breadcrumb": [],
            "refine": [],
            "expand": [],
            "ideas": [],
            "simple_log": True,
            "unindexed": True,
        }

    monkeypatch.setattr("domain_foundry_core.wizard.engine.query_neighborhood", fake_neighborhood)


def _api(workspace, monkeypatch: pytest.MonkeyPatch) -> HarnessAPI:
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    _force_unindexed(monkeypatch)
    api = HarnessAPI(workspace.home)
    api.init()
    return api


def _drive(api: HarnessAPI, *replies: str, goal: str = GOAL) -> tuple[str, dict[str, Any]]:
    """Fork → pick the suggested idea → build → answer the elicitation turns."""
    turn = api.new_domain(goal)
    sid = turn["session_id"]
    turn = api.wizard_reply(sid, "1")
    if turn["state"] == "looks":
        turn = api.wizard_reply(sid, "build it")
    pending = list(replies)
    while turn["state"] == "elicit":
        turn = api.wizard_reply(sid, pending.pop(0) if pending else "skip")
    return sid, turn


def _pack_text(api: HarnessAPI, name: str) -> str:
    """Every YAML file of the installed pack, concatenated."""
    pack = api.packs.get(name)
    assert pack is not None
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(Path(pack.root).glob("*.yaml"))
    )


def _mentions(blob: str, token: str) -> bool:
    return bool(re.search(rf"\b{re.escape(token)}\b", blob, re.IGNORECASE))


def _rule_words(pack) -> str:
    """Compiled rule regexes flattened back to plain words.

    A rule reads ``(\\blego\\b|photo\\ dex)``. Searching that string for a word
    with its own ``\\b`` anchors silently never matches, so the anchors and
    escapes come out first and the search then means what it says.
    """
    blob = " ".join(rule.match for rule in pack.routing.rules)
    blob = blob.replace(r"\b", " ")
    return re.sub(r"\\(.)", r"\1", blob)


def test_unindexed_goal_asks_for_two_sentences_and_stores_them_verbatim(workspace, monkeypatch):
    api = _api(workspace, monkeypatch)
    turn = api.new_domain(GOAL)
    sid = turn["session_id"]
    turn = api.wizard_reply(sid, "1")
    assert turn["state"] == "looks"
    turn = api.wizard_reply(sid, "build it")

    assert turn["state"] == "elicit"
    assert turn["awaiting"] == "elicit"
    assert turn["elicit"] == {"index": 1, "of": 2, "held_out": False, "samples": []}
    assert "Say one thing you'd log — exactly how you'd type it." in turn["message"]
    assert "That becomes the first test of the app." in turn["message"]

    turn = api.wizard_reply(sid, SEED)
    assert turn["state"] == "elicit"
    assert turn["elicit"]["index"] == 2
    assert turn["elicit"]["held_out"] is True
    assert turn["elicit"]["samples"] == [SEED]
    assert "And one more, a different kind of thing." in turn["message"]

    turn = api.wizard_reply(sid, HELD_OUT)
    assert turn["state"] == "test_drive"

    session = api.wizard.store.load(sid)
    assert session is not None
    # Verbatim, in order: the design sentence first, the held-out one second.
    assert session.elicited_samples == [SEED, HELD_OUT]


def test_the_first_sentence_becomes_the_packs_vocabulary(workspace, monkeypatch):
    api = _api(workspace, monkeypatch)
    sid, turn = _drive(api, SEED, HELD_OUT)
    name = turn["pack"]["name"]
    pack = api.packs.get(name)
    assert pack is not None

    rules = _rule_words(pack)
    for token in ("hogwarts", "castle", "pieces", "built"):
        assert _mentions(rules, token), (token, rules)

    # The sentence itself is a routing example, exactly as typed.
    assert SEED in [example.text for example in pack.routing.examples]

    # And the pack can now file a lego sentence it was never shown, because it
    # shares vocabulary with the one the owner typed.
    capture = api.wizard_reply(sid, LATER)
    routed = (capture.get("capture") or {}).get("routed") or []
    assert routed, capture
    assert routed[0]["domain"] == name
    assert routed[0]["disposition"] not in {"unfiled", "ledger_only"}


def test_held_out_sentence_never_reaches_the_compiled_rules(workspace, monkeypatch):
    """The acceptance evidence is only honest if the design never saw it.

    Not "not in the rules" alone — not in the examples, not in the negatives,
    not in the LLM hints, not anywhere in the pack the wizard wrote.
    """
    api = _api(workspace, monkeypatch)
    _sid, turn = _drive(api, SEED, HELD_OUT)
    name = turn["pack"]["name"]
    pack = api.packs.get(name)
    assert pack is not None

    rules = _rule_words(pack)
    for token in HELD_OUT_ONLY:
        assert not _mentions(rules, token), (token, rules)
        for example in pack.routing.examples:
            assert not _mentions(example.text, token), (token, example.text)
        assert not _mentions(pack.routing.llm_hints, token)
        # Belt and braces: the whole written pack, not just the parsed model.
        assert not _mentions(_pack_text(api, name), token), token

    # The sentence is on the session — held out of the design, not thrown away.
    session = api.wizard.store.load(_sid)
    assert session is not None
    assert session.elicited_samples[1] == HELD_OUT


def test_held_out_sentence_is_replayed_and_reported_honestly(workspace, monkeypatch):
    api = _api(workspace, monkeypatch)
    _sid, turn = _drive(api, SEED, HELD_OUT)
    replay = turn["held_out"]
    assert replay["text"] == HELD_OUT
    assert isinstance(replay["filed"], bool)
    assert replay["routed"], replay

    message = turn["message"]
    assert "Your second example" in message
    if replay["filed"]:
        assert turn["pack"]["name"] in message and replay["object_type"] in message
    else:
        # The honest answer for this pack today: one sentence is not enough
        # vocabulary to catch an unrelated second one, and it says so.
        assert "didn't file" in message
        assert "Tell me what it should be and I'll learn it." in message

    # Replaying is a measurement, not a capture: nothing was filed on the
    # user's behalf, so the pack is still empty when they type their first note.
    assert api.query(domain=turn["pack"]["name"]) == []


def test_skip_falls_back_to_todays_behaviour_and_says_so(workspace, monkeypatch):
    api = _api(workspace, monkeypatch)
    sid, turn = _drive(api, "skip")
    assert turn["state"] == "test_drive"
    name = turn["pack"]["name"]
    assert "You skipped the examples" in turn["message"]
    assert "nothing has checked it yet" in turn["message"]
    assert "held_out" not in turn

    session = api.wizard.store.load(sid)
    assert session is not None
    assert session.elicited_samples == []
    assert session.elicit_prompts == 2  # asked once, declined for both

    # Today's behaviour: the keyword scaffold, which still routes its own
    # examples and still files a sentence written in its own words.
    pack = api.packs.get(name)
    assert pack is not None
    assert len(pack.routing.examples) >= 8
    assert turn["dry_run"]["accuracy"] >= 0.95
    rules = _rule_words(pack)
    assert _mentions(rules, "shelf")
    capture = api.wizard_reply(sid, "added a new set to the shelf with photos")
    routed = (capture.get("capture") or {}).get("routed") or []
    assert routed and routed[0]["domain"] == name


def test_skipping_only_the_second_prompt_keeps_the_design(workspace, monkeypatch):
    api = _api(workspace, monkeypatch)
    sid, turn = _drive(api, SEED, "skip")
    assert turn["state"] == "test_drive"
    assert "No second example" in turn["message"]
    assert "held_out" not in turn

    session = api.wizard.store.load(sid)
    assert session is not None
    assert session.elicited_samples == [SEED]

    pack = api.packs.get(turn["pack"]["name"])
    assert pack is not None
    rules = _rule_words(pack)
    assert _mentions(rules, "hogwarts")


def test_elicitation_never_teaches_the_pack_idle_chatter(workspace, monkeypatch):
    """Elicitation widens vocabulary, which is exactly how over-capture starts.

    A real person's sentence carries their small talk with it. Adding the words
    the shipped negatives are written in would teach the fresh pack to file
    "nice afternoon, weather was good" — so those words never survive the seed.
    """
    api = _api(workspace, monkeypatch)
    chatty = "nice afternoon, weather was good, built the Hogwarts Castle set"
    _sid, turn = _drive(api, chatty, HELD_OUT)
    name = turn["pack"]["name"]
    pack = api.packs.get(name)
    assert pack is not None

    rules = _rule_words(pack)
    for chatter in ("afternoon", "weather", "nice"):
        assert not _mentions(rules, chatter), (chatter, rules)
    assert _mentions(rules, "hogwarts")

    receipt = api.capture(IDLE)
    filed = [
        span
        for span in receipt.routed
        if span.domain == name and span.disposition not in {"unfiled", "ledger_only"}
    ]
    assert not filed, receipt.model_dump()


def test_a_nonsense_goal_still_builds_honestly_when_the_user_skips(workspace, monkeypatch):
    api = _api(workspace, monkeypatch)
    sid, turn = _drive(api, "skip", goal="xyzzy plugh foobar")
    assert turn["state"] == "test_drive"
    name = turn["pack"]["name"]
    assert name.startswith("xyzzy")
    capture = api.wizard_reply(sid, "added foobar to the shelf with photos")
    routed = (capture.get("capture") or {}).get("routed") or []
    assert routed and routed[0]["domain"] == name
    assert routed[0]["disposition"] not in {"unfiled", "ledger_only"}


def test_seed_terms_keep_the_words_a_log_line_is_written_in():
    terms = seed_terms("squat 5x5 at 100kg on the rack, last set was a grind")
    assert "5x5" in terms
    assert "100kg" in terms
    assert "squat" in terms
    # Bare small integers match every log line ever written.
    assert "at" not in terms


def test_seed_terms_drop_the_words_the_negatives_are_written_in():
    assert seed_terms("nice afternoon, weather was good") == []
    assert "afternoon" in NEGATIVE_TERMS
    assert "standup" in NEGATIVE_TERMS


def test_invented_cards_use_the_users_words_not_the_fixed_skeleton():
    """Without a seed the cards are the honest "I know nothing" skeleton."""
    bare = eng.invent_idea_cards(GOAL)
    assert bare[0]["jargon"][:4] == ["shelf", "dex", "photos", "keeper"]

    seeded = eng.invent_idea_cards(GOAL, seed=SEED)
    assert "shelf" not in seeded[0]["jargon"]
    assert {"hogwarts", "castle", "pieces"} <= set(seeded[0]["jargon"])
    assert seeded[0]["example"] == SEED
    assert "hogwarts" in seeded[0]["pitch"].lower()
    # The skeleton is identical for nonsense; a seeded card cannot be.
    assert eng.invent_idea_cards("xyzzy plugh foobar")[0]["jargon"][:4] == bare[0]["jargon"][:4]
