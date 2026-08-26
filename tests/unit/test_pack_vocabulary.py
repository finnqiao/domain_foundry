"""A compiled pack has to understand the words its owner will actually type.

Three separate failures put 19 of the 50 interest goals in the right
neighbourhood and then dropped their first real sentence: a tokenizer that
could not see ``5x5`` or ``100kg``, a bounded routing rule that spent its slots
on ``session name`` and ``noted at``, and an atlas that knew "RPE, sets,
deload" but not "squat". These tests pin each one, plus the acceptance sentence
of every domain the atlas now carries vocabulary for.
"""

from __future__ import annotations

import pytest

from domain_foundry_core.atlas.loader import load_atlas
from domain_foundry_core.packs.loader import load_pack
from domain_foundry_core.routing.l1 import L1Matcher
from domain_foundry_core.wizard import blueprint as bp
from domain_foundry_core.wizard.jobs import compile_jobs, shortlist_for_ideas
from domain_foundry_core.wizard.shortlist import (
    GENERIC_RULE_TERMS,
    ShortlistModel,
    _tokens,
    compile_shortlist,
    generic_shape_warnings,
    term_pattern,
)

# ------------------------------------------------------------------ tokenizer


@pytest.mark.parametrize(
    ("text", "wanted", "unwanted"),
    [
        ("squat 5x5 at 100kg, last set was a grind", ["squat", "5x5", "100kg"], ["at"]),
        ("added a 1948 airmail to the inventory, mint", ["1948", "airmail", "mint"], []),
        ("baked a 75% hydration country loaf", ["75%", "hydration", "loaf"], []),
        ("shore dive, 18m, 50 bar SAC", ["18m", "dive"], ["50"]),
        ("3 sets of 20 reps", ["sets", "reps"], ["3", "20"]),
        ("finished the sleeve, blocking tonight", ["sleeve", "blocking"], []),
    ],
)
def test_tokenizer_sees_dimensioned_words_and_ignores_bare_integers(
    text: str, wanted: list[str], unwanted: list[str]
) -> None:
    found = _tokens(text)
    for token in wanted:
        assert token in found, (text, token, found)
    for token in unwanted:
        assert token not in found, (text, token, found)


def test_percent_terms_still_match_after_pattern_building() -> None:
    """``\\b`` after ``%`` is not a boundary — a naive pattern is unmatchable."""
    import re

    pattern = term_pattern("75%")
    assert re.search(pattern, "baked a 75% hydration loaf", re.IGNORECASE)


# ------------------------------------------------------- generic rule budget


def _lifting_pack(tmp_path, name: str = "gym"):
    graph = load_atlas()
    idea = graph.get("sports.strength.session_log")
    assert idea is not None
    goal = "log my gym lifting program"
    shortlist = shortlist_for_ideas([idea], goal=goal)
    blueprint = compile_jobs(shortlist, goal=goal, jobs=list(idea.jobs), domain_hint=name)
    dest = bp.write_pack(blueprint, tmp_path / name)
    return load_pack(dest, validate=True)


def _rule_terms(pack) -> set[str]:
    """Undo ``term_pattern`` so the rule can be read as the word list it is."""
    import re

    terms: set[str] = set()
    for rule in pack.routing.rules:
        body = rule.match
        if body.startswith("(") and body.endswith(")"):
            body = body[1:-1]
        for part in body.split("|"):
            part = part.removeprefix(r"\b").removesuffix(r"\b")
            terms.add(re.sub(r"\\(.)", r"\1", part).lower())
    return terms


def test_generic_field_names_never_become_routing_terms(tmp_path) -> None:
    pack = _lifting_pack(tmp_path)
    terms = _rule_terms(pack)
    assert not (terms & GENERIC_RULE_TERMS), terms & GENERIC_RULE_TERMS
    # And the real vocabulary got the slots those names used to hold.
    assert {"squat", "deadlift", "5x5", "deload"} <= terms, sorted(terms)


def test_no_object_routes_on_generic_terms_alone() -> None:
    """Every atlas idea must compile a rule that carries interest vocabulary."""
    graph = load_atlas()
    checked = 0
    for node in graph.nodes.values():
        if node.kind != "idea" or not node.vocabulary:
            continue
        goal = node.title.lower()
        shortlist = shortlist_for_ideas([node], goal=goal)
        assert generic_shape_warnings(shortlist) == [], (node.id, shortlist.objects)
        checked += 1
    assert checked >= 8


# -------------------------------------------------------- generic-shape lint


_OLD_LIFTING_EXAMPLES = [
    "dumbbell rows felt strong, added extra reps on the bench",
    "RPE sets",
    "sets deload",
    "RPE",
    "sets",
    "deload",
    "workout log",
    "RPE deload",
]


def _wizard_default_shape() -> ShortlistModel:
    """Exactly what the wizard compiled for lifting before the atlas grew words.

    Identity ``session_name``, a measure that fell through to ``value``, and a
    field list that is entirely about the act of logging.
    """
    return ShortlistModel.model_validate(
        {
            "domain": "lifting",
            "title": "Lifting log",
            "description": "What you lifted and how it felt.",
            "objects": ["session"],
            "fields": [
                {"name": "session_name", "type": "text", "role": "identity", "object": "session"},
                {"name": "noted_at", "type": "datetime", "role": "when", "object": "session"},
                {"name": "value", "type": "number", "role": "measure", "object": "session"},
                {"name": "notes", "type": "text", "role": "note", "object": "session"},
            ],
            "jargon": ["RPE", "sets", "deload", "workout log", "gym log"],
            "examples": [
                {"text": text, "object": "session", "fields": {"session_name": "bench"}}
                for text in _OLD_LIFTING_EXAMPLES
            ],
        }
    )


def _bare_shape() -> ShortlistModel:
    """A pack whose whole routing rule is its own object and domain name."""
    return ShortlistModel.model_validate(
        {
            "domain": "widget",
            "title": "Widget log",
            "description": "Widgets and the widget name.",
            "objects": ["widget"],
            "fields": [
                {"name": "widget_name", "type": "text", "role": "identity", "object": "widget"},
                {"name": "noted_at", "type": "datetime", "role": "when", "object": "widget"},
                {"name": "notes", "type": "text", "role": "note", "object": "widget"},
            ],
            "jargon": [],
            "examples": [
                {"text": "widget", "object": "widget", "fields": {"widget_name": "widget"}}
            ]
            * 8,
        }
    )


def test_generic_shape_lint_fires_on_the_wizards_old_default_shape() -> None:
    warnings = generic_shape_warnings(_wizard_default_shape())
    joined = " ".join(warnings)
    assert "measure fell through" in joined, warnings


def test_generic_shape_lint_fires_when_a_rule_is_only_the_object_name() -> None:
    warnings = generic_shape_warnings(_bare_shape())
    assert any("no interest vocabulary" in w for w in warnings), warnings


def test_generic_shape_lint_flags_a_record_name_identity() -> None:
    shape = _wizard_default_shape().model_dump()
    for field in shape["fields"]:
        if field["role"] == "identity":
            field["name"] = "record_name"
    for example in shape["examples"]:
        example["fields"] = {"record_name": "bench"}
    warnings = generic_shape_warnings(ShortlistModel.model_validate(shape))
    assert any("identity is the generic" in w for w in warnings), warnings


def test_generic_shape_lint_is_a_warning_not_a_build_failure() -> None:
    """A thin pack still beats no pack: the caller records, it does not raise."""
    blueprint = compile_shortlist(_wizard_default_shape(), goal="log my gym lifting program")
    recorded = blueprint["meta"]["design_warnings"]
    assert any("measure fell through" in w for w in recorded), recorded


def test_an_enriched_node_records_no_generic_shape_warning() -> None:
    graph = load_atlas()
    idea = graph.get("sports.strength.session_log")
    assert idea is not None
    shortlist = shortlist_for_ideas([idea], goal="log my gym lifting program")
    assert generic_shape_warnings(shortlist) == []


def test_atlas_measure_overrides_the_hardcoded_keyword_table() -> None:
    graph = load_atlas()
    idea = graph.get("sports.strength.session_log")
    assert idea is not None
    shortlist = shortlist_for_ideas([idea], goal="log my gym lifting program")
    measures = [f for f in shortlist.fields if f.role == "measure"]
    assert measures, shortlist.fields
    assert measures[0].name == "top_set"
    assert measures[0].unit == "kg"


# ------------------------------------------- one acceptance sentence, per domain

# Every domain the atlas gained vocabulary for, with the sentence its owner
# would plausibly type first. A pack that cannot match this has not been built.
ACCEPTANCE = [
    (
        "sports.strength.session_log",
        "log my gym lifting program",
        "gym",
        "squat 5x5 at 100kg, last set was a grind",
    ),
    ("sports.strength.lift_catalog", "which lifts I train", "lifts", "deadlift top set at RPE 8"),
    (
        "food.dining.dining_atlas",
        "map of restaurants I've eaten at",
        "map",
        "tried the new ramen shop on 5th, tonkotsu was excellent",
    ),
    (
        "food.cooking.cocktail_book",
        "cocktail recipes I invent at home",
        "cocktail",
        "stirred a rye cocktail, 2:1:1, orange bitters, up",
    ),
    (
        "craft.making.log",
        "knitting projects",
        "knitting",
        "finished the sleeve, blocking tonight, merino DK",
    ),
    (
        "reading.books.log",
        "books I read",
        "books",
        "finished The Left Hand of Darkness, reread later maybe",
    ),
    (
        "home.maintenance.log",
        "apartment maintenance",
        "apartment",
        "replaced the filter and the faucet gasket, leak stopped",
    ),
    (
        "making.dev.log",
        "engineering journal for side projects",
        "dev",
        "flake in the test, repro on main, patched the race",
    ),
    (
        "diving.spearfishing.hunt_log",
        "spearfishing hunt log",
        "spearfishing",
        "freedive hunt, one hogfish, 8m, speared clean",
    ),
    (
        "wellness.yoga.practice_log",
        "yoga practice",
        "yoga",
        "45 minute vinyasa, hips were tight, savasana ran long",
    ),
    (
        "collecting.catalog.dex",
        "stamp collection inventory",
        "stamp",
        "added a 1948 airmail to the inventory, mint, hinge remnant",
    ),
    (
        "food.drinks.tasting_notes",
        "whisky tasting notes",
        "whisky",
        "peated dram, iodine and orchard fruit, 12 year, neat",
    ),
    (
        "music.records.spin_log",
        "i play vinyl records",
        "play",
        "spun Kind of Blue, original pressing, inner sleeve torn",
    ),
]


@pytest.mark.parametrize(
    ("node_id", "goal", "pack_name", "sentence"), ACCEPTANCE, ids=[c[0] for c in ACCEPTANCE]
)
def test_enriched_domain_routes_its_acceptance_sentence(
    tmp_path, node_id: str, goal: str, pack_name: str, sentence: str
) -> None:
    graph = load_atlas()
    idea = graph.get(node_id)
    assert idea is not None, node_id
    shortlist = shortlist_for_ideas([idea], goal=goal)
    blueprint = compile_jobs(shortlist, goal=goal, jobs=list(idea.jobs), domain_hint=pack_name)
    dest = bp.write_pack(blueprint, tmp_path / pack_name)
    pack = load_pack(dest, validate=True)
    hits = L1Matcher([pack]).match(sentence).hits
    assert hits, (node_id, sentence, [r.match for r in pack.routing.rules])


@pytest.mark.parametrize(
    ("node_id", "goal", "pack_name", "sentence"), ACCEPTANCE, ids=[c[0] for c in ACCEPTANCE]
)
def test_enriched_domain_ignores_idle_chatter(
    tmp_path, node_id: str, goal: str, pack_name: str, sentence: str
) -> None:
    """Wider vocabulary must not buy routing with credulity."""
    graph = load_atlas()
    idea = graph.get(node_id)
    assert idea is not None, node_id
    shortlist = shortlist_for_ideas([idea], goal=goal)
    blueprint = compile_jobs(shortlist, goal=goal, jobs=list(idea.jobs), domain_hint=pack_name)
    dest = bp.write_pack(blueprint, tmp_path / pack_name)
    pack = load_pack(dest, validate=True)
    assert not L1Matcher([pack]).match("nice afternoon, weather was good").hits


def test_analog_packs_route_the_sentences_their_atlas_nodes_promise() -> None:
    """``dev`` and ``sourdough`` install as-is, so their own rules must cover it."""
    from domain_foundry_core.packs.loader import bundled_packs_root

    cases = [
        ("dev", "flake in the test, repro on main, patched the race"),
        ("sourdough", "discard pancakes this morning, tangy, used 100g discard"),
        ("sourdough", "baked a 75% hydration country loaf, crumb was open"),
    ]
    for name, sentence in cases:
        pack = load_pack(bundled_packs_root() / name, validate=True)
        assert L1Matcher([pack]).match(sentence).hits, (name, sentence)
