"""The review page: what it shows, how it reads, and who can use it.

The page is the only surface in this loop, so these tests hold it to the copy
rules and to the accessibility floor: keyboard operable, visible focus, no state
carried by colour alone, and usable at 320 pixels wide.
"""

from __future__ import annotations

import re

import pytest

from domain_foundry_core.foundry.loader import load_golden_specs
from domain_foundry_core.foundry.models import BorrowedFragment, LookBinding
from domain_foundry_core.review.page import (
    COLOUR_TOKENS,
    ConceptCard,
    ReviewProposal,
    proposal_from_spec,
    render_review_page,
)

GOLDENS = load_golden_specs()


@pytest.fixture(params=GOLDENS, ids=[spec.id for spec in GOLDENS])
def golden(request):
    return request.param


def test_page_generates_for_every_golden(golden) -> None:
    proposal = proposal_from_spec(golden, previews=False)
    page = render_review_page(proposal)
    assert page.startswith("<!doctype html>")
    assert f"Review the look for {golden.title}" in page
    for concept in golden.concepts:
        assert f'data-concept="{concept.id}"' in page
        assert f'value="{concept.id}"' in page
    assert "Save my marks" in page
    assert "review-marks.json" in page


def test_every_concept_card_carries_the_friend_pitch(golden) -> None:
    proposal = proposal_from_spec(golden, previews=False)
    for card in proposal.cards:
        assert card.pitch[0].startswith("Want to ")
        assert card.pitch[0].endswith("?")
        assert card.pitch[1].startswith("You already ")
        assert card.pitch[2].startswith("Build ")
        # One line of design and feel after the pitch, never more.
        assert card.feel.count("\n") == 0


def test_the_three_cards_are_worth_comparing(golden) -> None:
    proposal = proposal_from_spec(golden, previews=False)
    topologies = [card.topology for card in proposal.cards]
    assert len(set(topologies)) == len(topologies)
    assert topologies[0] == golden.experience.navigation.topology


def test_page_copy_follows_the_house_rules(golden) -> None:
    page = render_review_page(proposal_from_spec(golden, previews=False))
    assert "—" not in page
    assert "–" not in page
    words = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S).casefold()
    # The spec's own subject may be anything, so this checks the page's own
    # words, not text the spec supplied.
    for banned in ("free", "upgrade", "pricing", "subscription", "$"):
        assert banned not in words


def test_page_is_keyboard_operable_and_labelled(golden) -> None:
    page = render_review_page(proposal_from_spec(golden, previews=False))
    # Every control that takes a value has a label pointing at its id.
    ids = set(re.findall(r'<(?:input|select|textarea)[^>]*\bid="([^"]+)"', page))
    labelled = set(re.findall(r'<label for="([^"]+)"', page))
    assert ids, "the page has no controls"
    assert ids <= labelled, f"controls with no label: {sorted(ids - labelled)}"
    # The pin layer is a button, so it is reachable by tab, not only by mouse.
    assert '<button type="button" class="pin-layer"' in page
    assert "Add a note without clicking" in page


def test_page_has_visible_focus_and_no_colour_only_state(golden) -> None:
    page = render_review_page(proposal_from_spec(golden, previews=False))
    assert ":focus-visible" in page
    assert "outline: 3px solid var(--focus)" in page
    # The chosen card says "Chosen" in words, and a pressed toggle says "(on)".
    assert "data-chosen-badge" in page
    assert 'button[aria-pressed="true"]::after' in page


def test_page_works_at_320_pixels(golden) -> None:
    page = render_review_page(proposal_from_spec(golden, previews=False))
    assert "@media (max-width: 30rem)" in page
    assert "max-width: 100%" in page
    assert "overflow-x: auto" in page


def test_every_colour_has_its_own_control(golden) -> None:
    page = render_review_page(proposal_from_spec(golden, previews=False))
    for name in COLOUR_TOKENS:
        assert page.count(f'data-token="{name}"') == len(golden.concepts)
    assert page.count('data-token="radius_px"') == len(golden.concepts)


def test_a_bound_spec_starts_from_what_was_already_approved() -> None:
    spec = GOLDENS[0]
    concept = spec.concepts[1].id
    bound = spec.model_copy(
        update={
            "look": LookBinding(
                look_id="already-approved",
                concept_id=concept,
                topology="canvas",
                density_scale="airy",
                token_overrides={"accent": "#E39A2D"},
                borrowed_fragments=[
                    BorrowedFragment(from_concept=spec.concepts[0].id, piece="the big log button")
                ],
                notes=["keep the crumb photo big"],
            )
        }
    )
    proposal = proposal_from_spec(bound, previews=False)
    assert proposal.chosen_concept == concept
    card = next(item for item in proposal.cards if item.id == concept)
    assert card.topology == "canvas"
    assert card.density_scale == "airy"
    assert card.tokens["accent"] == "#E39A2D"
    borrowed = next(item for item in proposal.cards if item.id == spec.concepts[0].id)
    assert borrowed.borrow == "the big log button"
    page = render_review_page(proposal)
    assert f'id="{concept}-chosen" value="{concept}" checked' in page
    assert "keep the crumb photo big" in page


def test_a_supplied_preview_is_embedded_as_a_running_page() -> None:
    card = ConceptCard(
        id="ritual",
        title="Ritual",
        pitch=("Want to bake better?", "You already have notes.", "Build a feeding card."),
        feel="calm: one home screen, room to read, a serif.",
        best_at="the calmest path",
        loop="Feed, look, leave.",
        topology="hub",
        typography_stack="reading_serif",
        density_scale="bench",
        tokens={name: "#123456" for name in COLOUR_TOKENS} | {"radius_px": "10"},
        preview_html="<!doctype html><html><body>a running app</body></html>",
    )
    page = render_review_page(
        ReviewProposal(look_id="x-look", title="X", subject="something", cards=(card,))
    )
    assert 'class="preview"' in page
    assert "srcdoc=" in page
    assert "a running app" in page


def test_a_preview_that_will_not_build_says_so_instead_of_disappearing() -> None:
    card = ConceptCard(
        id="ritual",
        title="Ritual",
        pitch=("Want to bake better?", "You already have notes.", "Build a feeding card."),
        feel="calm: one home screen, room to read, a serif.",
        best_at="the calmest path",
        loop="Feed, look, leave.",
        topology="hub",
        typography_stack="reading_serif",
        density_scale="bench",
        tokens={name: "#123456" for name in COLOUR_TOKENS} | {"radius_px": "10"},
        preview_html="",
        preview_problem="No preview for this one: the build stopped.",
    )
    page = render_review_page(
        ReviewProposal(look_id="x-look", title="X", subject="something", cards=(card,))
    )
    assert "No preview for this one" in page
    assert "srcdoc=" not in page


def test_previews_are_asked_for_and_never_silently_skipped(golden) -> None:
    """A preview either runs in the page or says why it does not."""

    proposal = proposal_from_spec(golden, previews=True)
    for card in proposal.cards:
        assert bool(card.preview_html) != bool(card.preview_problem)
        if card.preview_html:
            assert "<html" in card.preview_html.casefold()
