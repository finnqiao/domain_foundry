"""Compiled L1 rules must not file idle chatter or invent filler tokens."""

from __future__ import annotations

import re

from domain_foundry_core.atlas.loader import load_atlas
from domain_foundry_core.packs.loader import load_pack
from domain_foundry_core.wizard.blueprint import write_pack
from domain_foundry_core.wizard.jobs import compile_jobs, shortlist_for_ideas
from domain_foundry_core.wizard.shortlist import analog_few_shots, compile_shortlist, term_pattern

IDLE = "nice afternoon, weather was good"
CHARIZARD = "pulled a holographic Charizard from a 151 booster, NM"


def test_term_pattern_after_does_not_match_afternoon():
    pat = re.compile(term_pattern("after"), re.IGNORECASE)
    assert pat.search("noted it after the session")
    assert not pat.search("afternoon")
    assert not pat.search(IDLE)


def test_card_dex_rules_reject_idle_and_keep_jargon(tmp_path):
    graph = load_atlas()
    idea = graph.get("collecting.catalog.card_dex")
    assert idea is not None
    shortlist = shortlist_for_ideas([idea], goal="i collect pokemon cards")
    assert all("usual method" not in ex.text.lower() for ex in shortlist.examples)
    assert all(
        str((ex.fields or {}).get("card_name") or "").lower() not in {"alpha", "beta", "gamma"}
        for ex in shortlist.examples
    )
    blueprint = compile_jobs(
        shortlist,
        goal="i collect pokemon cards",
        jobs=list(idea.jobs),
        domain_hint="cards",
    )
    idle_hits = [
        rule["match"]
        for rule in blueprint["rules"]
        if re.search(rule["match"], IDLE, re.IGNORECASE)
    ]
    assert idle_hits == [], idle_hits
    assert any(re.search(rule["match"], CHARIZARD, re.IGNORECASE) for rule in blueprint["rules"])
    dest = write_pack(blueprint, tmp_path / "cards")
    pack = load_pack(dest, validate=True)
    assert not any(re.search(rule.match, IDLE, re.IGNORECASE) for rule in pack.routing.rules)
    assert any(re.search(rule.match, CHARIZARD, re.IGNORECASE) for rule in pack.routing.rules)


def test_plants_analog_compiled_rules_do_not_match_afternoon():
    shortlist = analog_few_shots("track my houseplants")[0]["shortlist"]
    blueprint = compile_shortlist(shortlist, goal="track my houseplants")
    for rule in blueprint["rules"]:
        assert not re.search(rule["match"], IDLE, re.IGNORECASE), rule["match"]