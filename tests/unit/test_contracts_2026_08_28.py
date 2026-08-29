"""Phase 0 contracts for the 2026-08-28 rebuild kit.

Every lane codes against these types. If one of these tests goes red, a lane is
about to be built on a contract that moved: fix the contract with the
integrator, not the lane.

See docs/rebuild-plan-2026-08-28/00-OVERVIEW.md.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from domain_foundry_core.cli import LANE_CLI_MODULES, register_lane_commands
from domain_foundry_core.foundry.loader import load_golden_specs
from domain_foundry_core.foundry.models import (
    BESPOKE_CSS_BUDGET_BYTES,
    DENSITY_SCALE_LABELS,
    SEED_SOURCE_LABELS,
    SIGNATURE_ELEMENT_LABELS,
    TYPOGRAPHY_STACK_LABELS,
    BespokeLayer,
    BorrowedFragment,
    LookBinding,
    SeedProvenance,
    TraitEdge,
)


def _round_trip(model):
    return type(model).model_validate(model.model_dump(mode="json"))


# --------------------------------------------------------------- BespokeLayer


def test_bespoke_layer_round_trips() -> None:
    layer = BespokeLayer(
        css=".tide-bar { background: var(--accent); border-radius: 4px; }",
        rationale="The tide bar is the one thing she looks at before leaving the house.",
    )
    assert _round_trip(layer) == layer


@pytest.mark.parametrize(
    "css",
    [
        "@import url(https://evil.example/x.css);",
        ".x { background: url(https://evil.example/pixel.png); }",
        ".x { width: expression(alert(1)); }",
        ".x { background: javascript:alert(1); }",
        "</style><script>fetch('https://evil.example')</script>",
        ".x { -moz-binding: url(#x); }",
    ],
)
def test_bespoke_layer_rejects_hostile_css(css: str) -> None:
    with pytest.raises(ValidationError):
        BespokeLayer(css=css, rationale="hostile")


def test_bespoke_layer_has_a_size_budget() -> None:
    with pytest.raises(ValidationError):
        BespokeLayer(css="a" * (BESPOKE_CSS_BUDGET_BYTES + 1), rationale="too big")


# ---------------------------------------------------------------- LookBinding


def test_look_binding_round_trips_everything_the_review_page_can_say() -> None:
    binding = LookBinding(
        look_id="look-tidepool-1",
        concept_id="concept-session",
        topology="session",
        typography_stack="reading_serif",
        density_scale="bench",
        token_overrides={"accent": "#E39A2D", "radius_px": "6"},
        signature_elements=["progress_bar", "life_list"],
        borrowed_fragments=[
            BorrowedFragment(
                from_concept="concept-place",
                piece="the map strip along the top",
                reason="She wants to see which pools she has not walked yet.",
            )
        ],
        bespoke=BespokeLayer(css=".x { color: var(--text); }", rationale="one small thing"),
        notes=["The species panel should sit on the right."],
        approved_at="2026-08-28T09:00:00Z",
    )
    assert _round_trip(binding) == binding


def test_look_binding_rejects_a_token_that_does_not_exist() -> None:
    with pytest.raises(ValidationError):
        LookBinding(look_id="l1", token_overrides={"accent_alt_2": "#000000"})


@pytest.mark.parametrize("value", ["red", "#FFF", "#GGGGGG", ""])
def test_look_binding_rejects_a_colour_that_is_not_a_colour(value: str) -> None:
    with pytest.raises(ValidationError):
        LookBinding(look_id="l1", token_overrides={"accent": value})


def test_look_binding_radius_stays_in_range() -> None:
    LookBinding(look_id="l1", token_overrides={"radius_px": "24"})
    with pytest.raises(ValidationError):
        LookBinding(look_id="l1", token_overrides={"radius_px": "25"})


def test_a_partly_marked_page_still_binds() -> None:
    binding = LookBinding(look_id="look-1")
    assert binding.topology is None
    assert _round_trip(binding) == binding


# -------------------------------------------------------------- SeedProvenance


def test_personal_upload_is_never_shareable() -> None:
    seed = SeedProvenance(
        id="seed-tidepool-log",
        kind="personal_upload",
        label="your tidepool log",
        location="/Users/june/Documents/tidepools.xlsx",
        row_count=214,
        columns=["date", "place", "species", "count", "notes"],
    )
    assert seed.shareable is False
    assert _round_trip(seed) == seed


def test_a_public_link_can_travel_and_must_say_where_it_came_from() -> None:
    seed = SeedProvenance(
        id="seed-field-guide",
        kind="public_link",
        label="the field guide page you pointed at",
        location="https://example.org/tidepool-species",
        retrieved_at="2026-08-28",
    )
    assert seed.shareable is True
    with pytest.raises(ValidationError):
        SeedProvenance(id="s", kind="public_link", label="a page")


def test_a_personal_upload_does_not_carry_a_license() -> None:
    with pytest.raises(ValidationError):
        SeedProvenance(
            id="s",
            kind="personal_upload",
            label="your spreadsheet",
            license="CC-BY-4.0",
        )


# ------------------------------------------------------------------ TraitEdge


def test_authored_trait_edge_must_cite_evidence() -> None:
    edge = TraitEdge(
        id="trait-tide-driven",
        trait="driven by tides or the moon",
        consequence="time windows come first: show what is open right now",
        topology="session",
        signature_elements=["progress_bar"],
        evidence_ids=["ev-tide-tables"],
    )
    assert _round_trip(edge) == edge
    with pytest.raises(ValidationError):
        TraitEdge(id="t", trait="a", consequence="b")


def test_detected_trait_edge_names_the_seed_it_was_read_off() -> None:
    edge = TraitEdge(
        id="trait-place-bound",
        trait="the same few places come up again and again",
        consequence="an atlas with a history per place",
        origin="detected",
        seed_ids=["seed-tidepool-log"],
    )
    assert _round_trip(edge) == edge
    with pytest.raises(ValidationError):
        TraitEdge(id="t", trait="a", consequence="b", origin="detected")


# ------------------------------------------------------- attachment and labels


def test_every_named_choice_has_plain_words_for_it() -> None:
    for labels in (
        TYPOGRAPHY_STACK_LABELS,
        DENSITY_SCALE_LABELS,
        SIGNATURE_ELEMENT_LABELS,
        SEED_SOURCE_LABELS,
    ):
        assert labels
        for text in labels.values():
            assert text == text.strip()
            assert "—" not in text, "no em dashes in user-facing copy"
            lowered = text.casefold()
            for banned in ("free", "paid", "pricing", "upgrade"):
                assert banned not in lowered.split(), f"no cost words: {text!r}"


def test_the_new_fields_are_optional_so_todays_goldens_still_load() -> None:
    specs = load_golden_specs()
    assert len(specs) == 3
    for spec in specs:
        assert spec.look is None
        assert spec.research.seeds == []
        assert spec.research.traits == []
        assert spec.experience.visual_world.bespoke is None
        assert spec.experience.visual_world.typography_stack is None
        assert spec.experience.visual_world.signature_element_ids == []
        assert spec.remix.parent_spec is None


def test_a_golden_round_trips_with_the_new_contracts_attached() -> None:
    spec = load_golden_specs()[0]
    payload = spec.model_dump(mode="json")
    payload["look"] = LookBinding(look_id="look-1", topology="hub").model_dump(mode="json")
    payload["research"]["seeds"] = [
        SeedProvenance(
            id="seed-1", kind="personal_upload", label="your spreadsheet", row_count=12
        ).model_dump(mode="json")
    ]
    payload["research"]["traits"] = [
        TraitEdge(
            id="trait-1",
            trait="collected instances",
            consequence="a catalog split into owned and still missing",
            origin="detected",
            seed_ids=["seed-1"],
        ).model_dump(mode="json")
    ]
    rebuilt = type(spec).model_validate(payload)
    assert rebuilt.look is not None
    assert rebuilt.research.seeds[0].shareable is False
    assert rebuilt.research.traits[0].origin == "detected"


def test_fork_parentage_must_look_like_a_spec_id() -> None:
    spec = load_golden_specs()[0]
    payload = spec.model_dump(mode="json")
    payload["remix"]["parent_spec"] = "sourdough-lab"
    assert type(spec).model_validate(payload).remix.parent_spec == "sourdough-lab"

    payload["remix"]["parent_spec"] = "../../etc/passwd"
    with pytest.raises(ValidationError):
        type(spec).model_validate(payload)


# ------------------------------------------------------------ the CLI registry


def test_the_lane_registry_starts_empty_and_attaches_cleanly() -> None:
    assert isinstance(LANE_CLI_MODULES, tuple)
    assert register_lane_commands() == LANE_CLI_MODULES


def test_an_unregisterable_lane_module_is_a_loud_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import domain_foundry_core.cli as cli_module

    monkeypatch.setattr(cli_module, "LANE_CLI_MODULES", ("clock",))
    with pytest.raises(RuntimeError, match="register"):
        cli_module.register_lane_commands()
