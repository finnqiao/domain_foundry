"""Spaced-repetition schedulers — SM-2 now; FSRS later is a pure algorithm swap.

Every grade produces a :class:`ReviewResult` that callers persist as a
``review_event`` (``algorithm="sm2"``) so history survives an algorithm change.
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


@dataclass(frozen=True)
class CardState:
    """Per-card SM-2 fields (matches jp_vocab / jp_grammar pack schema)."""

    ease_factor: float = DEFAULT_EASE
    interval_days: float = 0.0
    reps: int = 0
    lapses: int = 0
    next_review: str | None = None  # ISO date YYYY-MM-DD
    last_reviewed: str | None = None  # ISO datetime


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


def sm2_ease_delta(quality: int) -> float:
    """SuperMemo SM-2 ease-factor delta for quality ``q`` in 0..5."""
    q = max(0, min(5, int(quality)))
    return 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)


def sm2_next_ease(ease_factor: float, quality: int) -> float:
    return max(MIN_EASE, float(ease_factor) + sm2_ease_delta(quality))


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


class SM2Scheduler:
    """SuperMemo SM-2 with Anki again/hard/good/easy quality mapping.

    Property-tested against known sequences in ``tests/unit/test_srs_sm2.py``.
    Anki learning-step / hard-interval / easy-bonus extras are intentionally
    deferred (partial Anki UX is OK for this pass).
    """

    algorithm = "sm2"

    def review(
        self, card_state: CardState, grade: Grade, now: datetime
    ) -> ReviewResult:
        if grade not in GRADE_TO_QUALITY:
            raise ValueError(f"unknown grade {grade!r}; expected one of {GRADES}")
        q = GRADE_TO_QUALITY[grade]
        prev_interval = float(card_state.interval_days or 0.0)
        ease = sm2_next_ease(card_state.ease_factor or DEFAULT_EASE, q)
        reviewed_at = _iso_datetime(now)

        if q < 3:
            interval = 1.0
            new_state = replace(
                card_state,
                ease_factor=ease,
                interval_days=interval,
                reps=0,
                lapses=int(card_state.lapses or 0) + 1,
                next_review=_iso_date(_as_utc(now) + timedelta(days=interval)),
                last_reviewed=reviewed_at,
            )
        else:
            reps = int(card_state.reps or 0) + 1
            interval = sm2_next_interval(
                prev_interval=prev_interval,
                reps_after=reps,
                ease_after=ease,
                quality=q,
            )
            new_state = replace(
                card_state,
                ease_factor=ease,
                interval_days=interval,
                reps=reps,
                lapses=int(card_state.lapses or 0),
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


def card_state_from_row(row: dict) -> CardState:
    """Build :class:`CardState` from a domains row / dict."""
    return CardState(
        ease_factor=float(row.get("ease_factor") if row.get("ease_factor") is not None else DEFAULT_EASE),
        interval_days=float(row.get("interval_days") or 0.0),
        reps=int(row.get("reps") or 0),
        lapses=int(row.get("lapses") or 0),
        next_review=row.get("next_review"),
        last_reviewed=row.get("last_reviewed"),
    )


# ---------------------------------------------------------------------------
# Known SM-2 sequences (shared with property tests)
# ---------------------------------------------------------------------------

# Starting EF=2.5, reps=0, interval=0 — three Goods then Again.
KNOWN_SEQUENCE_THREE_GOOD_THEN_AGAIN: list[tuple[Grade, dict]] = [
    (
        "good",
        {
            "quality": 4,
            "ease_factor": 2.5,  # delta 0
            "reps": 1,
            "lapses": 0,
            "interval_days": 1.0,
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
            "interval_days": 1.0,
        },
    ),
]

# Easy bumps EF by +0.1 each time under classic SM-2 (q=5).
KNOWN_SEQUENCE_EASY_EASE_BUMPS: list[tuple[Grade, dict]] = [
    ("easy", {"ease_factor": 2.6, "reps": 1, "interval_days": 1.0}),
    ("easy", {"ease_factor": 2.7, "reps": 2, "interval_days": 6.0}),
    ("easy", {"ease_factor": 2.8, "reps": 3, "interval_days": 17.0}),  # round(6*2.8)=17
]

# Hard (q=3) lowers EF by 0.14 but still advances interval on success.
KNOWN_SEQUENCE_HARD_THEN_GOOD: list[tuple[Grade, dict]] = [
    ("hard", {"ease_factor": 2.36, "reps": 1, "interval_days": 1.0}),  # 2.5-0.14
    ("good", {"ease_factor": 2.36, "reps": 2, "interval_days": 6.0}),
]
