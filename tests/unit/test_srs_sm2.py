"""Property tests for Anki-flavoured SM-2 against known grade sequences."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from domain_foundry_core.mesh.srs import (
    DEFAULT_EASE,
    DEFAULT_EASY_BONUS,
    DEFAULT_HARD_INTERVAL,
    KNOWN_SEQUENCE_EASY_EASE_BUMPS,
    KNOWN_SEQUENCE_HARD_THEN_GOOD,
    KNOWN_SEQUENCE_THREE_GOOD_THEN_AGAIN,
    KNOWN_SEQUENCE_TWO_STEP_LEARNING,
    MIN_EASE,
    SM2Config,
    SM2Scheduler,
    CardState,
    Grade,
    GRADES,
    GRADE_TO_QUALITY,
    anki_easy_interval,
    anki_hard_interval,
    sm2_ease_delta,
    sm2_next_ease,
    sm2_next_interval,
)

T0 = datetime(2026, 7, 22, 9, 0, 0, tzinfo=UTC)


def _run_sequence(
    steps: list[tuple[Grade, dict]],
    *,
    start: CardState | None = None,
    scheduler: SM2Scheduler | None = None,
) -> list[CardState]:
    sched = scheduler or SM2Scheduler()
    state = start or CardState()
    out: list[CardState] = []
    for grade, _expected in steps:
        result = sched.review(state, grade, T0)
        state = result.state
        out.append(state)
    return out


def test_known_sequence_three_good_then_again():
    states = _run_sequence(KNOWN_SEQUENCE_THREE_GOOD_THEN_AGAIN)
    for state, (_grade, expected) in zip(
        states, KNOWN_SEQUENCE_THREE_GOOD_THEN_AGAIN, strict=True
    ):
        assert state.ease_factor == pytest.approx(expected["ease_factor"])
        assert state.reps == expected["reps"]
        assert state.lapses == expected["lapses"]
        assert state.interval_days == pytest.approx(expected["interval_days"])
        assert state.next_review is not None
        assert state.last_reviewed is not None


def test_known_sequence_easy_ease_bumps():
    states = _run_sequence(KNOWN_SEQUENCE_EASY_EASE_BUMPS)
    for state, (_grade, expected) in zip(
        states, KNOWN_SEQUENCE_EASY_EASE_BUMPS, strict=True
    ):
        assert state.ease_factor == pytest.approx(expected["ease_factor"])
        assert state.reps == expected["reps"]
        assert state.interval_days == pytest.approx(expected["interval_days"])


def test_known_sequence_hard_then_good():
    states = _run_sequence(KNOWN_SEQUENCE_HARD_THEN_GOOD)
    for state, (_grade, expected) in zip(
        states, KNOWN_SEQUENCE_HARD_THEN_GOOD, strict=True
    ):
        assert state.ease_factor == pytest.approx(expected["ease_factor"])
        assert state.reps == expected["reps"]
        assert state.interval_days == pytest.approx(expected["interval_days"])
        if "learning_step" in expected:
            assert state.learning_step == expected["learning_step"]


def test_two_step_learning_before_graduation():
    sched = SM2Scheduler(SM2Config(learning_steps=(1.0, 1.0)))
    states = _run_sequence(KNOWN_SEQUENCE_TWO_STEP_LEARNING, scheduler=sched)
    for state, (_grade, expected) in zip(
        states, KNOWN_SEQUENCE_TWO_STEP_LEARNING, strict=True
    ):
        assert state.reps == expected["reps"]
        assert state.interval_days == pytest.approx(expected["interval_days"])
        assert state.learning_step == expected["learning_step"]


def test_hard_interval_is_previous_times_factor():
    assert anki_hard_interval(10.0) == pytest.approx(12.0)
    assert anki_hard_interval(10.0, factor=DEFAULT_HARD_INTERVAL) == 12.0
    state = CardState(ease_factor=2.5, interval_days=10.0, reps=3)
    result = SM2Scheduler().review(state, "hard", T0)
    assert result.state.interval_days == pytest.approx(12.0)
    assert result.state.reps == 4
    assert result.state.ease_factor == pytest.approx(2.36)


def test_easy_bonus_multiplies_good_interval():
    assert anki_easy_interval(10.0) == pytest.approx(13.0)
    assert anki_easy_interval(10.0, easy_bonus=DEFAULT_EASY_BONUS) == 13.0
    # Graduated: Good base = round(10 * 2.5) = 25; Easy uses ease-after 2.6 →
    # round(10 * 2.6) = 26, then ×1.3 → 34
    state = CardState(ease_factor=2.5, interval_days=10.0, reps=3)
    good = SM2Scheduler().review(state, "good", T0)
    easy = SM2Scheduler().review(state, "easy", T0)
    assert good.state.interval_days == pytest.approx(25.0)
    assert easy.state.interval_days == pytest.approx(34.0)
    assert easy.state.ease_factor == pytest.approx(2.6)


@pytest.mark.parametrize("grade", GRADES)
def test_every_grade_emits_sm2_review_event_fields(grade: Grade):
    sched = SM2Scheduler()
    result = sched.review(CardState(), grade, T0)
    assert result.algorithm == "sm2"
    assert result.grade == grade
    assert result.quality == GRADE_TO_QUALITY[grade]
    fields = result.review_event_fields(card_uid="japanese:jp_vocab:test")
    assert fields["algorithm"] == "sm2"
    assert fields["grade"] == grade
    assert fields["prev_interval_days"] == 0.0
    assert fields["next_interval_days"] == result.next_interval_days
    assert "card_uid=" in (fields.get("notes") or "")
    patch = result.card_update_fields()
    assert set(patch) >= {
        "ease_factor",
        "interval_days",
        "reps",
        "lapses",
        "next_review",
        "last_reviewed",
        "learning_step",
    }


def test_ease_never_below_floor():
    # Graduated Again → relearning (lapse once); further Again stays in learning.
    state = CardState(ease_factor=MIN_EASE, interval_days=10, reps=5, lapses=0)
    sched = SM2Scheduler()
    for _ in range(5):
        result = sched.review(state, "again", T0)
        assert result.state.ease_factor >= MIN_EASE
        state = result.state
    assert state.reps == 0
    assert state.lapses == 1
    assert state.interval_days == 1.0


def test_interval_growth_after_graduation_is_ease_product():
    # After two goods: reps=2, I=6, EF=2.5 → third good → round(6*2.5)=15
    state = CardState(ease_factor=DEFAULT_EASE, interval_days=6.0, reps=2)
    result = SM2Scheduler().review(state, "good", T0)
    assert result.state.interval_days == 15.0
    assert result.state.reps == 3
    assert sm2_next_interval(
        prev_interval=6.0, reps_after=3, ease_after=2.5, quality=4
    ) == 15.0


def test_sm2_ease_delta_formula_points():
    # Classic SuperMemo table points.
    assert sm2_ease_delta(5) == pytest.approx(0.1)
    assert sm2_ease_delta(4) == pytest.approx(0.0)
    assert sm2_ease_delta(3) == pytest.approx(-0.14)
    assert sm2_ease_delta(1) == pytest.approx(-0.54)
    assert sm2_next_ease(2.5, 1) == pytest.approx(1.96)
