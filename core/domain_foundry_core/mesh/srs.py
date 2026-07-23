"""Spaced-repetition schedulers — Anki-flavoured SM-2 now; FSRS later is a swap.

Every grade produces a :class:`ReviewResult` that callers persist as a
``review_event`` (``algorithm="sm2"``) so history survives an algorithm change.

Anki extras layered on classic SM-2:
- learning / relearning steps (day-based; default one 1-day step)
- hard-interval factor (default 1.2× previous)
- easy-bonus (default 1.3× the Good interval)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

Grade = Literal["again", "hard", "good", "easy"]
GRADES: tuple[Grade, ...] = ("again", "hard", "good", "easy")

# Anki 4-button → SuperMemo SM-2 quality (0–5).
GRADE_TO_QUALITY: dict[Grade, int] = {
    "again": 1,
    "hard": 3,
    "good": 4,
    "easy": 5,
}

DEFAULT_EASE = 2.5
MIN_EASE = 1.3
DEFAULT_HARD_INTERVAL = 1.2
DEFAULT_EASY_BONUS = 1.3
DEFAULT_LEARNING_STEPS: tuple[float, ...] = (1.0,)
DEFAULT_RELEARNING_STEPS: tuple[float, ...] = (1.0,)
DEFAULT_GRADUATING_INTERVAL = 1.0
DEFAULT_EASY_INTERVAL = 4.0


@dataclass(frozen=True)
class SM2Config:
    """Anki-compatible knobs on top of classic SM-2."""

    learning_steps: tuple[float, ...] = DEFAULT_LEARNING_STEPS
    relearning_steps: tuple[float, ...] = DEFAULT_RELEARNING_STEPS
    graduating_interval: float = DEFAULT_GRADUATING_INTERVAL
    easy_interval: float = DEFAULT_EASY_INTERVAL
    hard_interval_factor: float = DEFAULT_HARD_INTERVAL
    easy_bonus: float = DEFAULT_EASY_BONUS
    starting_ease: float = DEFAULT_EASE
    min_ease: float = MIN_EASE


DEFAULT_SM2_CONFIG = SM2Config()


@dataclass(frozen=True)
class CardState:
    """Per-card SM-2 fields (matches jp_vocab / jp_grammar pack schema)."""

    ease_factor: float = DEFAULT_EASE
    interval_days: float = 0.0
    reps: int = 0
    lapses: int = 0
    next_review: str | None = None  # ISO date YYYY-MM-DD
    last_reviewed: str | None = None  # ISO datetime
    learning_step: int = 0  # index into learning/relearning steps while ungraduated


@dataclass(frozen=True)
class ReviewResult:
    """Outcome of one grade — enough to update the card + append review_event."""

    state: CardState
    grade: Grade
    prev_interval_days: float
    next_interval_days: float
    reviewed_at: str
    algorithm: str = "sm2"
    quality: int = 0

    def review_event_fields(self, *, card_uid: str | None = None) -> dict:
        """Payload for ``review_event`` create via the apply path."""
        notes = f"card_uid={card_uid}" if card_uid else None
        return {
            "grade": self.grade,
            "reviewed_at": self.reviewed_at,
            "prev_interval_days": self.prev_interval_days,
            "next_interval_days": self.next_interval_days,
            "algorithm": self.algorithm,
            "ease_factor_after": self.state.ease_factor,
            **({"notes": notes} if notes else {}),
        }

    def card_update_fields(self) -> dict:
        """Payload patch for jp_vocab / jp_grammar update via the apply path."""
        return {
            "ease_factor": self.state.ease_factor,
            "interval_days": self.state.interval_days,
            "reps": self.state.reps,
            "lapses": self.state.lapses,
            "next_review": self.state.next_review,
            "last_reviewed": self.state.last_reviewed,
            "learning_step": self.state.learning_step,
        }


class Scheduler(Protocol):
    """Algorithm swap surface — SM-2 today, FSRS tomorrow."""

    def review(
        self, card_state: CardState, grade: Grade, now: datetime
    ) -> ReviewResult: ...


def _as_utc(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)


def _iso_date(dt: datetime) -> str:
    return _as_utc(dt).strftime("%Y-%m-%d")


def _iso_datetime(dt: datetime) -> str:
    return _as_utc(dt).isoformat().replace("+00:00", "Z")


def _clamp_interval(days: float) -> float:
    return float(max(1, round(float(days))))


def sm2_ease_delta(quality: int) -> float:
    """SuperMemo SM-2 ease-factor delta for quality ``q`` in 0..5."""
    q = max(0, min(5, int(quality)))
    return 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)


def sm2_next_ease(ease_factor: float, quality: int, *, min_ease: float = MIN_EASE) -> float:
    return max(float(min_ease), float(ease_factor) + sm2_ease_delta(quality))


def sm2_next_interval(
    *,
    prev_interval: float,
    reps_after: int,
    ease_after: float,
    quality: int,
) -> float:
    """Classic SM-2 interval after a successful recall (q ≥ 3).

    ``reps_after`` is the post-increment repetition count (1 on first success).
    """
    if quality < 3:
        return 1.0
    if reps_after <= 1:
        return 1.0
    if reps_after == 2:
        return 6.0
    # n > 2: I(n) = round(I(n-1) * EF')
    return float(max(1, round(float(prev_interval) * float(ease_after))))


def anki_hard_interval(prev_interval: float, *, factor: float = DEFAULT_HARD_INTERVAL) -> float:
    """Anki hard button: previous interval × hard-interval factor (default 1.2)."""
    prev = float(prev_interval or 0.0)
    if prev <= 0:
        return 1.0
    return _clamp_interval(prev * float(factor))


def anki_easy_interval(
    base_interval: float, *, easy_bonus: float = DEFAULT_EASY_BONUS
) -> float:
    """Anki easy button: Good-length interval × easy-bonus (default 1.3)."""
    return _clamp_interval(float(base_interval) * float(easy_bonus))


class SM2Scheduler:
    """SuperMemo SM-2 with Anki learning steps, hard-interval, and easy-bonus.

    Property-tested against known sequences in ``tests/unit/test_srs_sm2.py``.
    """

    algorithm = "sm2"

    def __init__(self, config: SM2Config | None = None) -> None:
        self.config = config or DEFAULT_SM2_CONFIG

    def review(
        self, card_state: CardState, grade: Grade, now: datetime
    ) -> ReviewResult:
        if grade not in GRADE_TO_QUALITY:
            raise ValueError(f"unknown grade {grade!r}; expected one of {GRADES}")
        q = GRADE_TO_QUALITY[grade]
        prev_interval = float(card_state.interval_days or 0.0)
        reviewed_at = _iso_datetime(now)

        if int(card_state.reps or 0) <= 0:
            new_state, interval = self._review_learning(card_state, grade, q, now)
        else:
            new_state, interval = self._review_graduated(
                card_state, grade, q, prev_interval, now
            )

        new_state = replace(
            new_state,
            next_review=_iso_date(_as_utc(now) + timedelta(days=interval)),
            last_reviewed=reviewed_at,
        )
        return ReviewResult(
            state=new_state,
            grade=grade,
            prev_interval_days=prev_interval,
            next_interval_days=interval,
            reviewed_at=reviewed_at,
            algorithm=self.algorithm,
            quality=q,
        )

    def _review_learning(
        self,
        card_state: CardState,
        grade: Grade,
        quality: int,
        now: datetime,  # noqa: ARG002 — kept for API symmetry / future minute steps
    ) -> tuple[CardState, float]:
        cfg = self.config
        steps = cfg.learning_steps or DEFAULT_LEARNING_STEPS
        step = max(0, min(int(card_state.learning_step or 0), len(steps) - 1))
        ease = float(card_state.ease_factor or cfg.starting_ease)
        lapses = int(card_state.lapses or 0)

        if grade == "again":
            interval = float(steps[0])
            return (
                replace(
                    card_state,
                    ease_factor=sm2_next_ease(ease, quality, min_ease=cfg.min_ease),
                    interval_days=interval,
                    reps=0,
                    lapses=lapses,
                    learning_step=0,
                ),
                interval,
            )

        if grade == "hard":
            # Anki: Hard repeats the current learning step.
            interval = float(steps[step])
            return (
                replace(
                    card_state,
                    ease_factor=sm2_next_ease(ease, quality, min_ease=cfg.min_ease),
                    interval_days=interval,
                    reps=0,
                    lapses=lapses,
                    learning_step=step,
                ),
                interval,
            )

        if grade == "easy":
            interval = float(cfg.easy_interval)
            return (
                replace(
                    card_state,
                    ease_factor=sm2_next_ease(ease, quality, min_ease=cfg.min_ease),
                    interval_days=interval,
                    reps=1,
                    lapses=lapses,
                    learning_step=0,
                ),
                interval,
            )

        # Good — advance learning step or graduate.
        if step + 1 >= len(steps):
            interval = float(cfg.graduating_interval)
            return (
                replace(
                    card_state,
                    ease_factor=sm2_next_ease(ease, quality, min_ease=cfg.min_ease),
                    interval_days=interval,
                    reps=1,
                    lapses=lapses,
                    learning_step=0,
                ),
                interval,
            )
        next_step = step + 1
        interval = float(steps[next_step])
        return (
            replace(
                card_state,
                ease_factor=sm2_next_ease(ease, quality, min_ease=cfg.min_ease),
                interval_days=interval,
                reps=0,
                lapses=lapses,
                learning_step=next_step,
            ),
            interval,
        )

    def _review_graduated(
        self,
        card_state: CardState,
        grade: Grade,
        quality: int,
        prev_interval: float,
        now: datetime,  # noqa: ARG002
    ) -> tuple[CardState, float]:
        cfg = self.config
        ease = sm2_next_ease(
            card_state.ease_factor or cfg.starting_ease,
            quality,
            min_ease=cfg.min_ease,
        )
        lapses = int(card_state.lapses or 0)
        reps = int(card_state.reps or 0)

        if grade == "again":
            steps = cfg.relearning_steps or DEFAULT_RELEARNING_STEPS
            interval = float(steps[0])
            return (
                replace(
                    card_state,
                    ease_factor=ease,
                    interval_days=interval,
                    reps=0,
                    lapses=lapses + 1,
                    learning_step=0,
                ),
                interval,
            )

        if grade == "hard":
            interval = anki_hard_interval(
                prev_interval, factor=cfg.hard_interval_factor
            )
            return (
                replace(
                    card_state,
                    ease_factor=ease,
                    interval_days=interval,
                    reps=reps + 1,
                    lapses=lapses,
                    learning_step=0,
                ),
                interval,
            )

        reps_after = reps + 1
        base = sm2_next_interval(
            prev_interval=prev_interval,
            reps_after=reps_after,
            ease_after=ease,
            quality=quality,
        )
        if grade == "easy":
            interval = anki_easy_interval(base, easy_bonus=cfg.easy_bonus)
        else:
            interval = float(base)
        return (
            replace(
                card_state,
                ease_factor=ease,
                interval_days=interval,
                reps=reps_after,
                lapses=lapses,
                learning_step=0,
            ),
            interval,
        )


def card_state_from_row(row: dict) -> CardState:
    """Build :class:`CardState` from a domains row / dict."""
    return CardState(
        ease_factor=float(row.get("ease_factor") if row.get("ease_factor") is not None else DEFAULT_EASE),
        interval_days=float(row.get("interval_days") or 0.0),
        reps=int(row.get("reps") or 0),
        lapses=int(row.get("lapses") or 0),
        next_review=row.get("next_review"),
        last_reviewed=row.get("last_reviewed"),
        learning_step=int(row.get("learning_step") or 0),
    )


# ---------------------------------------------------------------------------
# Known SM-2 sequences (shared with property tests)
# ---------------------------------------------------------------------------

# Starting EF=2.5, reps=0, interval=0 — three Goods then Again.
# Default learning_steps=(1.0,) → first Good graduates at graduating_interval=1.
KNOWN_SEQUENCE_THREE_GOOD_THEN_AGAIN: list[tuple[Grade, dict]] = [
    (
        "good",
        {
            "quality": 4,
            "ease_factor": 2.5,  # delta 0
            "reps": 1,
            "lapses": 0,
            "interval_days": 1.0,
            "learning_step": 0,
        },
    ),
    (
        "good",
        {
            "quality": 4,
            "ease_factor": 2.5,
            "reps": 2,
            "lapses": 0,
            "interval_days": 6.0,
        },
    ),
    (
        "good",
        {
            "quality": 4,
            "ease_factor": 2.5,
            "reps": 3,
            "lapses": 0,
            "interval_days": 15.0,  # round(6 * 2.5)
        },
    ),
    (
        "again",
        {
            "quality": 1,
            "ease_factor": 1.96,  # 2.5 + (0.1 - 4*0.16) = 1.96
            "reps": 0,
            "lapses": 1,
            "interval_days": 1.0,  # relearning step
            "learning_step": 0,
        },
    ),
]

# Easy on new card graduates at easy_interval (4d); later Easy applies easy-bonus.
KNOWN_SEQUENCE_EASY_EASE_BUMPS: list[tuple[Grade, dict]] = [
    ("easy", {"ease_factor": 2.6, "reps": 1, "interval_days": 4.0}),
    # graduated Easy: classic second-rep base=6, then ×1.3 → 8
    ("easy", {"ease_factor": 2.7, "reps": 2, "interval_days": 8.0}),
    # base = round(8 * 2.8) = 22, ×1.3 → 29
    ("easy", {"ease_factor": 2.8, "reps": 3, "interval_days": 29.0}),
]

# Hard on new (learning) repeats the step; Good then graduates.
KNOWN_SEQUENCE_HARD_THEN_GOOD: list[tuple[Grade, dict]] = [
    ("hard", {"ease_factor": 2.36, "reps": 0, "interval_days": 1.0, "learning_step": 0}),
    ("good", {"ease_factor": 2.36, "reps": 1, "interval_days": 1.0, "learning_step": 0}),
]

# Two-day learning steps: Good×2 to graduate.
KNOWN_SEQUENCE_TWO_STEP_LEARNING: list[tuple[Grade, dict]] = [
    ("good", {"reps": 0, "interval_days": 1.0, "learning_step": 1}),
    ("good", {"reps": 1, "interval_days": 1.0, "learning_step": 0}),
]
