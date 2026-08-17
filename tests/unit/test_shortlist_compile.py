"""LLM shortlist compile must L1-route its own examples to the right object."""

from __future__ import annotations

import copy

from domain_foundry_core.packs.loader import load_pack
from domain_foundry_core.routing.l1 import L1Matcher
from domain_foundry_core.wizard import blueprint as bp
from domain_foundry_core.wizard.shortlist import analog_few_shots, compile_shortlist


def _l1_objects(pack, text: str) -> set[str]:
    hits = L1Matcher([pack]).match(text).hits
    return {h.object_type for h in hits}


def test_analog_plants_examples_route_to_expected_object(tmp_path):
    shortlist = copy.deepcopy(analog_few_shots("track my houseplants")[0]["shortlist"])
    blueprint = compile_shortlist(shortlist, goal="track my houseplants")
    draft = tmp_path / "draft"
    bp.write_pack(blueprint, draft)
    pack = load_pack(draft, validate=True)
    for ex in shortlist["examples"]:
        matched = _l1_objects(pack, ex["text"])
        assert ex["object"] in matched, (ex["text"], matched)


def test_two_object_coffee_examples_do_not_all_hit_first_object(tmp_path):
    shortlist = {
        "domain": "coffee",
        "title": "Coffee Brews",
        "description": "Pour-overs and the beans behind them.",
        "objects": ["bean", "brew"],
        "fields": [
            {"name": "bean_name", "type": "text", "role": "identity", "object": "bean", "required": True},
            {"name": "origin", "type": "text", "role": "text", "object": "bean"},
            {"name": "process", "type": "enum", "role": "enum", "object": "bean",
             "values": ["washed", "natural", "honey"]},
            {"name": "brew_name", "type": "text", "role": "identity", "object": "brew", "required": True},
            {"name": "method", "type": "enum", "role": "enum", "object": "brew",
             "values": ["v60", "aeropress", "espresso"]},
            {"name": "dose_g", "type": "number", "role": "measure", "object": "brew", "unit": "g"},
            {"name": "rating", "type": "integer", "role": "measure", "object": "brew"},
            {"name": "notes", "type": "text", "role": "note", "object": "brew"},
        ],
        "jargon": ["v60", "aeropress", "bloom", "yirgacheffe", "washed"],
        "examples": [
            {"text": "opened a bag of washed Yirgacheffe from the roaster", "object": "bean",
             "fields": {"bean_name": "Yirgacheffe", "process": "washed", "origin": "Ethiopia"}},
            {"text": "new natural Ethiopia landed on the shelf", "object": "bean",
             "fields": {"bean_name": "Ethiopia", "process": "natural"}},
            {"text": "honey process from Kenya, floral and sweet", "object": "bean",
             "fields": {"bean_name": "Kenya", "process": "honey"}},
            {"text": "V60 this morning, 15g in, bergamot on the finish", "object": "brew",
             "fields": {"brew_name": "V60 morning", "method": "v60", "dose_g": 15}},
            {"text": "aeropress at work, 14g, tasted like blueberry", "object": "brew",
             "fields": {"brew_name": "work aeropress", "method": "aeropress", "dose_g": 14}},
            {"text": "espresso shot was sour, rating 4", "object": "brew",
             "fields": {"brew_name": "espresso", "method": "espresso", "rating": 4}},
            {"text": "bloomed 30s then poured to 250g", "object": "brew",
             "fields": {"brew_name": "bloom pour", "method": "v60"}},
            {"text": "tasting notes jasmine, rating 8", "object": "brew",
             "fields": {"brew_name": "jasmine cup", "rating": 8, "notes": "jasmine"}},
            {"text": "resting the bag two days after roast", "object": "bean",
             "fields": {"bean_name": "resting bag"}},
            {"text": "pulled a lungo because the first shot choked", "object": "brew",
             "fields": {"brew_name": "lungo", "method": "espresso"}},
        ],
        "negatives": [
            "deploy the release candidate tonight",
            "schedule a standup meeting",
        ],
    }
    blueprint = compile_shortlist(shortlist, goal="log my pour-over coffee brews")
    draft = tmp_path / "draft"
    bp.write_pack(blueprint, draft)
    pack = load_pack(draft, validate=True)

    winners = []
    for ex in shortlist["examples"]:
        result = L1Matcher([pack]).match(ex["text"])
        assert result.hits, ex["text"]
        # Highest-boost hit must be the expected object (same rule the router uses).
        hit = max(result.hits, key=lambda h: (h.boost, h.rule_index))
        winners.append((ex["text"], ex["object"], hit.object_type))
        assert hit.object_type == ex["object"], winners[-1]
