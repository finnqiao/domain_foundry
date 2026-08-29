"""Release proof #4: an out-of-corpus passion, seeded from a spreadsheet, gives an honest app.

Two cases.

The full case is June at low tide: a passion the reviewed corpus has never
heard of, seeded from a spreadsheet she already keeps and a field guide page
she trusts, built into an app that opens with her own history inside it, with
the model's contributions marked apart from her guide.

The cheap case is the honesty floor: the same out-of-corpus passion with no
seeds and nobody consenting to model knowledge stops with the three paths
instead of inventing an app.

    python -m pytest tests/e2e-foundry/test_stranger_passion.py -q

Status right now: the honesty floor is green. The full case is RED and says
what is missing. It waits on Lane E (the `seed` command and the tidepool
fixtures) and on cassettes recorded against a live model. See the failure
messages, which name each missing piece.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from domain_foundry_core.foundry.research import (
    MODEL_CLAIM_MARK,
    THREE_PATHS,
    KnowledgeRetriever,
    ResearchPlan,
    ResearchUnavailable,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_FIXTURES = REPO_ROOT / "examples" / "seed-fixtures"
CASSETTES = Path(__file__).resolve().parent / "cassettes" / "stranger-passion"

INTEREST = "nudibranch sightings in Pacific tide pools"


def _plan() -> ResearchPlan:
    return ResearchPlan(
        interest=INTEREST,
        desired_outcome="Keep a log of what I saw, where, and on which tide.",
        practice_hypotheses=[
            "Each visit records a date, a spot and what was seen.",
            "Tide height and time of day decide when a visit is worth making.",
        ],
        # Deliberately avoids the word "species": it overlaps the aquarium
        # exemplar's topics and routes this passion into the reviewed corpus,
        # which would hide the very gap this test exists to prove. Noted for
        # Lane F in the Lane G resume notes.
        queries=[INTEREST, "nudibranch identification guide", "tide pool survey method"],
        vertical_keywords=["nudibranch", "tide pool", "sea slug"],
        artifact_questions=["What does a sightings spreadsheet already record?"],
    )


# --------------------------------------------------------------------------
# The honesty floor. Green today.
# --------------------------------------------------------------------------


def test_no_seeds_and_no_consent_fails_closed_with_the_three_paths() -> None:
    with pytest.raises(ResearchUnavailable) as caught:
        KnowledgeRetriever().retrieve(_plan(), allow_model_knowledge=False)

    message = str(caught.value)
    assert "The reviewed sources have nothing" in message
    for path in THREE_PATHS:
        assert path in message
    assert caught.value.paths == THREE_PATHS
    # Nothing is offered for money and nothing is called free.
    for banned in ("—", "free", "upgrade", "pricing", "cost"):
        assert banned not in message.lower()


def test_the_three_paths_name_exactly_what_to_provide() -> None:
    """Copy rule: an ask names the thing, never 'sources'."""
    keeps, page, model = THREE_PATHS
    assert "spreadsheet" in keeps and "notes folder" in keeps
    assert "field guide" in page or "handbook" in page
    assert "marked" in model
    assert MODEL_CLAIM_MARK.endswith("Nothing was read to check it.")


# --------------------------------------------------------------------------
# The full case. RED until Lane E lands.
# --------------------------------------------------------------------------


def test_seed_fixtures_exist() -> None:
    """The tidepool fixtures this proof seeds from.

    Lane G guessed the names before Lane E shipped them; the integrator
    corrected them to what is actually on disk.
    """
    spreadsheet = SEED_FIXTURES / "tidepool-log.xlsx"
    guide = SEED_FIXTURES / "field-guide.html"
    missing = [str(path) for path in (spreadsheet, guide) if not path.exists()]
    assert not missing, (
        "The stranger-passion proof seeds from two fixtures that do not exist yet: "
        f"{', '.join(missing)}. "
        "Owner: Lane E, which creates examples/seed-fixtures/ along with the "
        "`seed` command. Until they land, proof #4 cannot run."
    )


def test_seed_command_exists() -> None:
    """RED: the `seed` verb this proof drives is not built yet."""
    import importlib.util

    found = importlib.util.find_spec("domain_foundry_core.cli_seed")
    assert found is not None, (
        "There is no `domain-foundry seed` verb. "
        "Missing: core/domain_foundry_core/cli_seed.py and the "
        "core/domain_foundry_core/seed/ package. "
        "Owner: Lane E. Until they land, proof #4 cannot run."
    )


def test_stranger_passion_cassettes_are_recorded() -> None:
    """RED: nobody has recorded a live run of this passion yet."""
    recorded = sorted(CASSETTES.glob("*.json")) if CASSETTES.is_dir() else []
    assert recorded, (
        f"There are no cassettes under {CASSETTES}. "
        "This gate runs in replay so CI is deterministic, and it will not fall "
        "back to the offline keyword scaffold, because that would put an "
        "unresearched spec under a generated label. "
        "To record them: set a reasoning model with `domain-foundry setup`, then "
        "run this file once with DOMAIN_FOUNDRY_LIVE_GATE=1. Commit the "
        "cassettes as the evidence for proof #4."
    )


def test_seeded_app_opens_with_the_users_history_inside() -> None:
    """RED: the end-to-end walk, blocked on the three gaps above.

    When Lane E lands, this becomes the real walk: seed the spreadsheet and the
    guide, consent to model knowledge, propose, pick a concept, build, and then
    check three things.

      1. The built app opens with the seeded records in it, and the count
         matches the fixture.
      2. Evidence tells the user's guide apart from the model's own claims:
         every model claim carries MODEL_CLAIM_MARK and every seeded claim
         names the file or the link it came from.
      3. No five-field generic shape: the domain has more than one entity and
         the views carry more than one region kind.
    """
    pytest.fail(
        "Proof #4 is not runnable yet. Blocked on Lane E "
        "(examples/seed-fixtures/, core/domain_foundry_core/seed/, cli_seed.py) "
        "and on a recorded live run for the cassettes. "
        "The honesty floor half of this proof is green; see the tests above."
    )
