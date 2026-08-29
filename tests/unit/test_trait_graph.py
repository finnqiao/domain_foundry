"""Lane F3: the local interest graph, and what it is for.

One sentence about a hobby should produce three app ideas that are actually
different, not three names for the same log. The trait graph is how: it says
what a practice is like, and what the app should be shaped like because of it.

The tests here pin three things. The shipped rules are honest (authored, cited,
and each one says a structural consequence). Detection reads traits off the
brief and off what the user already keeps, and says which is which. And the
result of detection is a set of *structures*, so concepts built from it cannot
be phrasing variants of each other.
"""

from __future__ import annotations

from pathlib import Path

from domain_foundry_core.atlas.traits import (
    bundled_trait_edges,
    detect_traits,
    load_trait_graph,
    structural_options,
    validate_trait_graph,
)
from domain_foundry_core.foundry.models import SeedProvenance

TIDEPOOL_BRIEF = (
    "I go tidepooling on the north coast. I walk a spot on a low tide and write "
    "down what species I find, and I want to know which ones I have never seen."
)

PIANO_BRIEF = (
    "I am learning piano. I practice scales and one piece at a time, and I want "
    "to know what to work on in the next lesson."
)

TIDEPOOL_COLUMNS = ["date", "time", "spot", "species", "count", "tide_height_m", "notes"]


def _tidepool_log() -> SeedProvenance:
    return SeedProvenance(
        id="tidepool_log",
        kind="personal_upload",
        label="Tidepool log spreadsheet",
        row_count=214,
        columns=list(TIDEPOOL_COLUMNS),
    )


# --------------------------------------------------------------------------- #
# The shipped rules
# --------------------------------------------------------------------------- #


def test_the_shipped_rules_are_authored_cited_and_say_something_structural() -> None:
    graph = load_trait_graph()

    assert len(graph) >= 6
    assert validate_trait_graph(graph) == []
    for rule in graph.rules.values():
        assert rule.edge.origin == "authored"
        assert rule.edge.evidence_ids, f"{rule.id} cites nothing"
        assert rule.edge.topology is not None
        # An authored rule never claims to have been read off a seed.
        assert rule.edge.seed_ids == []


def test_the_six_story_rules_are_all_present() -> None:
    graph = load_trait_graph()

    assert {
        "cycle_driven",
        "collected_instances",
        "practiced_skill",
        "place_bound",
        "produces_artifacts",
        "improves_over_time",
    } <= set(graph.rules)


def test_the_rules_reach_more_than_one_topology() -> None:
    """A graph whose every rule wants the same shape cannot differentiate."""
    assert len(load_trait_graph().topologies()) >= 4


def test_the_rule_file_ships_inside_the_package() -> None:
    path = bundled_trait_edges()
    assert path.is_file()
    assert path.parent.name == "atlas"
    assert "domain_foundry_core" in path.parts


def test_a_user_overlay_shadows_a_shipped_rule(tmp_path: Path) -> None:
    """Someone who knows their hobby better than the shipped rules can say so."""
    (tmp_path / "trait_edges.yaml").write_text(
        "\n".join(
            [
                "rules:",
                "  - signals:",
                "      words: [tide, moon]",
                "    edge:",
                "      id: cycle_driven",
                "      trait: My own wording for this",
                "      consequence: And my own consequence",
                "      origin: authored",
                "      topology: workflow",
                "      evidence_ids: [my_own_note]",
            ]
        ),
        encoding="utf-8",
    )
    graph = load_trait_graph(overlay=tmp_path)

    rule = graph.get("cycle_driven")
    assert rule is not None
    assert rule.edge.topology == "workflow"
    assert rule.edge.trait == "My own wording for this"
    # Everything else survives; the overlay replaces one rule, not the file.
    assert len(graph) >= 6


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #


def test_the_tidepool_brief_yields_the_three_story_structures() -> None:
    traits = detect_traits(text=TIDEPOOL_BRIEF, seeds=[_tidepool_log()])
    options = structural_options(traits)

    assert [option.topology for option in options] == ["session", "split", "canvas"]
    # Three shapes, and no two of them share a topology, so three concepts built
    # from these cannot be the same concept wearing different words.
    assert len({option.topology for option in options}) == 3


def test_a_practiced_skill_brief_yields_session_topology() -> None:
    traits = detect_traits(text=PIANO_BRIEF)

    assert any(edge.id == "detected_practiced_skill" for edge in traits)
    options = structural_options(traits)
    assert options and options[0].topology == "session"


def test_a_detected_edge_names_the_seed_it_was_read_off() -> None:
    traits = detect_traits(text="", seeds=[_tidepool_log()])

    assert traits
    for edge in traits:
        assert edge.origin == "detected"
        assert edge.seed_ids == ["tidepool_log"]
        # And it names the authored rule it fired, so the reasoning is checkable.
        assert edge.evidence_ids[0] in load_trait_graph().rules


def test_a_trait_read_off_the_brief_alone_still_cites_its_rule() -> None:
    traits = detect_traits(text=PIANO_BRIEF)

    assert traits
    for edge in traits:
        assert edge.origin == "detected"
        assert edge.seed_ids == []
        assert edge.evidence_ids, "a detected edge must say where it came from"


def test_one_stray_word_does_not_fire_a_rule() -> None:
    """A coincidence is not a trait."""
    assert detect_traits(text="I need somewhere to put my meeting notes") == []
    assert detect_traits(text="the moon was out") == []


def test_a_recorded_column_counts_more_than_a_word() -> None:
    """A column the user has kept for a year outweighs a passing mention."""
    columns_only = SeedProvenance(
        id="log",
        kind="personal_upload",
        label="log",
        columns=["tide_height_m"],
    )
    detected = detect_traits(text="", seeds=[columns_only])

    assert [edge.id for edge in detected] == ["detected_cycle_driven"]


def test_structural_options_collapse_traits_that_want_the_same_shape() -> None:
    traits = detect_traits(
        text="I practice drills and lessons and I want to get faster and beat my personal best",
    )
    options = structural_options(traits)

    assert len({option.topology for option in options}) == len(options)
