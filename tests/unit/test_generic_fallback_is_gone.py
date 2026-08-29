"""Lane F4: the five-field generic log is not an answer, and is not a pass.

Two things used to be true and both were dishonest. The wizard had a fallback
that built one `entry` object with title, logged_at, rating, amount and notes out
of the literal words of a goal, and handed it over as if it were an app about the
person's interest. And the held-out suite counted that as a pass, on all fifty
cases at once.

The fallback is gone. `build_blueprint` refuses instead, and says what the user
can do about it. The grading calls a scaffold a failure and calls an honest
refusal what it is: acceptable, countable, and not a pass.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from domain_foundry_core.evals import interest as suite
from domain_foundry_core.wizard import blueprint as bp

REPO_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# The fallback
# --------------------------------------------------------------------------- #


def test_the_generic_spec_builder_does_not_exist() -> None:
    assert not hasattr(bp, "_generic_spec")
    source = inspect.getsource(bp)
    assert "_generic_spec" not in source


def test_an_unknown_goal_is_refused_rather_than_scaffolded() -> None:
    with pytest.raises(bp.GenericFallbackRefused) as caught:
        bp.build_blueprint("track my competitive cloud sculpting")

    message = str(caught.value)
    assert "Three ways forward" in message
    assert len(caught.value.paths) == 3
    # The refusal names what to provide, rather than asking for "sources".
    assert "spreadsheet" in message
    assert "field guide" in message
    assert "marked, so you can always tell which is which" in message


def test_a_known_goal_still_builds_the_real_archetype() -> None:
    """Killing the floor must not take the archetypes with it."""
    built = bp.build_blueprint("I want to track my sourdough journey")

    assert built["domain"] == "sourdough"
    assert built["archetype"] == "sourdough"
    names = {name for obj in built["objects"].values() for name in obj["fields"]}
    assert names - suite.GENERIC_FIELDS, "an archetype must say something about its domain"


# --------------------------------------------------------------------------- #
# The grading
# --------------------------------------------------------------------------- #


def test_the_verdict_order_places_the_two_new_verdicts_correctly() -> None:
    rank = suite.verdict_rank

    # A scaffold handed over as an answer is a failure, and one of the worst,
    # because it misleads rather than merely breaks.
    assert rank("fail_generic_scaffold") < rank("fail_loop")
    assert rank("fail_generic_scaffold") < rank("honest_fail_closed")
    # An honest refusal beats every failure and does not reach a pass.
    assert rank("fail_loop") < rank("honest_fail_closed") < rank("pass_with_gap")
    assert rank("honest_fail_closed") < rank("pass")
    ranked = [rank(verdict) for verdict in suite.VERDICT_ORDER]
    assert ranked == sorted(ranked)


def test_an_honest_refusal_is_countable_and_does_not_fail_the_run() -> None:
    assert "honest_fail_closed" in suite.ACCEPTABLE_VERDICTS
    assert "fail_generic_scaffold" not in suite.ACCEPTABLE_VERDICTS

    results = [
        suite.CaseResult(id="a", bucket="unindexed", goal="g", overall="honest_fail_closed"),
        suite.CaseResult(id="b", bucket="indexed", goal="g", overall="pass"),
    ]
    summary = suite.summarise(results)

    assert summary["failing_ids"] == []
    assert summary["honest_fail_closed"] == 1
    assert summary["pass"] == 1


def test_a_generic_scaffold_that_files_the_sentence_is_still_a_failure() -> None:
    scaffolded = suite.CaseResult(
        id="probe",
        bucket="unindexed",
        goal="track my lego builds",
        pack="lego_builds",
        fork_verdict="honest_miss",
        jargon_ok=True,
        idle_ok=True,
        has_domain_field=False,
    )
    assert suite._overall(scaffolded) == "fail_generic_scaffold"

    real = suite.CaseResult(
        id="probe",
        bucket="indexed",
        goal="track my sourdough",
        pack="sourdough",
        fork_verdict="hit",
        jargon_ok=True,
        idle_ok=True,
        has_domain_field=True,
    )
    assert suite._overall(real) == "pass"


def test_an_honest_refusal_outranks_everything_that_happened_before_it() -> None:
    refused = suite.CaseResult(
        id="probe",
        bucket="unindexed",
        goal="nonsense",
        fork_verdict="honest_miss",
        honest_refusal=True,
    )
    assert suite._overall(refused) == "honest_fail_closed"


# --------------------------------------------------------------------------- #
# The reader that was measuring nothing
# --------------------------------------------------------------------------- #


def test_the_field_reader_finds_the_shape_a_real_turn_carries() -> None:
    """It used to look only at ``schema``, which no turn has ever had."""
    turn = {
        "proposal": {
            "domain": "lego_builds",
            "objects": [
                {"name": "lego_build", "fields": ["lego_builds_name", "noted_at", "notes"]}
            ],
        }
    }
    schema = suite.schema_from_turn(turn)
    assert schema is not None

    ratio, has_domain = suite._score_fields(schema)
    assert ratio == 0.0
    assert has_domain is False, "a pack named after itself says nothing about the interest"


def test_a_pack_with_real_domain_fields_scores_above_zero() -> None:
    schema = {
        "domain": "sourdough",
        "objects": [{"name": "bake", "fields": ["hydration", "crumb", "notes"]}],
    }
    ratio, has_domain = suite._score_fields(schema)

    assert ratio == pytest.approx(2 / 3)
    assert has_domain is True


def test_both_field_shapes_are_understood() -> None:
    """A proposal lists field names; a validated schema lists field objects."""
    strings = {"objects": [{"fields": ["hydration", "notes"]}]}
    dicts = {"objects": [{"fields": [{"name": "hydration"}, {"name": "notes"}]}]}

    assert suite._score_fields(strings) == suite._score_fields(dicts)


def test_a_turn_with_no_shape_at_all_reads_as_nothing() -> None:
    assert suite.schema_from_turn({}) is None
    assert suite._score_fields(None) == (0.0, False)


# --------------------------------------------------------------------------- #
# The baseline
# --------------------------------------------------------------------------- #


def test_the_baseline_explains_the_regrade_in_its_header() -> None:
    import json

    snapshot = json.loads(suite.DEFAULT_BASELINE.read_text(encoding="utf-8"))
    keys = list(snapshot)

    assert keys[0] == "_note", "the explanation is the first thing a reader sees"
    note = snapshot["_note"]
    assert "50/50" in note
    assert "fail_generic_scaffold" in note
    assert "honest_fail_closed" in note


def test_the_baseline_no_longer_pins_fifty_passes() -> None:
    import json

    snapshot = json.loads(suite.DEFAULT_BASELINE.read_text(encoding="utf-8"))

    assert snapshot["n"] == 50
    assert snapshot["pass"] < 50, "a scaffold no longer counts as a pass"
    assert snapshot["generic_scaffolds"] > 0
    assert set(snapshot["cases"].values()) <= set(suite.VERDICT_ORDER)
