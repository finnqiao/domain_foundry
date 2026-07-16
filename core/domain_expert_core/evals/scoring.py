"""Full eval scoring: routing / field / disposition / calibration (plan §10.2).

Builds per-pack scorecards on top of the raw :class:`EvalReport` produced by the
replay runner. The scorecards feed committed baseline snapshots and the
regression diff so quality is enforceable in CI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain_expert_core.evals.runner import CaseScore, EvalReport

# Confidence buckets for the calibration curve (§7.4).
_CALIBRATION_BINS = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]

_REAL_DOMAIN_EXCLUDE = {None, "", "_unfiled", "_ledger"}


def _round(value: float, ndigits: int = 4) -> float:
    return round(value, ndigits)


@dataclass
class CalibrationBucket:
    lower: float
    upper: float
    n: int = 0
    correct: int = 0
    confidence_sum: float = 0.0

    @property
    def mean_confidence(self) -> float:
        return (self.confidence_sum / self.n) if self.n else 0.0

    @property
    def observed_accuracy(self) -> float:
        return (self.correct / self.n) if self.n else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "range": [self.lower, self.upper],
            "n": self.n,
            "mean_confidence": _round(self.mean_confidence),
            "observed_accuracy": _round(self.observed_accuracy),
        }


@dataclass
class PackScorecard:
    """Per-pack quality metrics used for baseline comparison."""

    pack: str
    routing_total: int = 0
    routing_correct: int = 0
    field_tp: int = 0  # correct expected field values
    field_fp: int = 0  # extra/wrong actual field values on matched captures
    field_fn: int = 0  # expected field values missing/wrong
    disposition_total: int = 0
    disposition_correct: int = 0
    false_completed_actions: int = 0
    calibration: list[CalibrationBucket] = field(default_factory=list)

    @property
    def routing_accuracy(self) -> float:
        return (self.routing_correct / self.routing_total) if self.routing_total else 1.0

    @property
    def field_precision(self) -> float:
        denom = self.field_tp + self.field_fp
        return (self.field_tp / denom) if denom else 1.0

    @property
    def field_recall(self) -> float:
        denom = self.field_tp + self.field_fn
        return (self.field_tp / denom) if denom else 1.0

    @property
    def field_f1(self) -> float:
        p, r = self.field_precision, self.field_recall
        return (2 * p * r / (p + r)) if (p + r) else 1.0

    @property
    def disposition_accuracy(self) -> float:
        return (
            self.disposition_correct / self.disposition_total
            if self.disposition_total
            else 1.0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "routing_total": self.routing_total,
            "routing_correct": self.routing_correct,
            "routing_accuracy": _round(self.routing_accuracy),
            "field_precision": _round(self.field_precision),
            "field_recall": _round(self.field_recall),
            "field_f1": _round(self.field_f1),
            "disposition_total": self.disposition_total,
            "disposition_accuracy": _round(self.disposition_accuracy),
            "false_completed_actions": self.false_completed_actions,
            "calibration": [b.to_dict() for b in self.calibration if b.n],
        }


@dataclass
class CorpusScore:
    """Overall + per-pack scorecards for a corpus replay."""

    total: int = 0
    routing_correct: int = 0
    false_completed_actions: int = 0
    packs: dict[str, PackScorecard] = field(default_factory=dict)

    @property
    def routing_accuracy(self) -> float:
        return (self.routing_correct / self.total) if self.total else 0.0

    def scorecard(self, pack: str) -> PackScorecard:
        if pack not in self.packs:
            card = PackScorecard(pack)
            card.calibration = [
                CalibrationBucket(_CALIBRATION_BINS[i], _CALIBRATION_BINS[i + 1])
                for i in range(len(_CALIBRATION_BINS) - 1)
            ]
            self.packs[pack] = card
        return self.packs[pack]

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": {
                "total": self.total,
                "routing_correct": self.routing_correct,
                "routing_accuracy": _round(self.routing_accuracy),
                "false_completed_actions": self.false_completed_actions,
            },
            "packs": {name: card.to_dict() for name, card in sorted(self.packs.items())},
        }

    def to_baseline(self) -> dict[str, Any]:
        """Compact, deterministic snapshot committed to the repo for diffing."""
        return {
            "version": 1,
            "overall": {
                "total": self.total,
                "routing_accuracy": _round(self.routing_accuracy),
                "false_completed_actions": self.false_completed_actions,
            },
            "packs": {
                name: {
                    "routing_total": card.routing_total,
                    "routing_accuracy": _round(card.routing_accuracy),
                    "field_f1": _round(card.field_f1),
                    "disposition_accuracy": _round(card.disposition_accuracy),
                    "false_completed_actions": card.false_completed_actions,
                }
                for name, card in sorted(self.packs.items())
            },
        }


def _expected_captures(expected: dict[str, Any]) -> list[dict[str, Any]]:
    caps = expected.get("captures")
    if caps:
        return list(caps)
    if expected.get("domain"):
        return [expected]
    return []


def _expected_packs(expected: dict[str, Any]) -> list[str]:
    packs: list[str] = []
    for cap in _expected_captures(expected):
        dom = cap.get("domain")
        if dom and dom not in packs:
            packs.append(dom)
    return packs


def _fields_equal(want: Any, got: Any) -> bool:
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        return abs(float(want) - float(got)) <= 0.01
    return str(got).lower() == str(want).lower()


def _match_actual(
    want: dict[str, Any], actual: list[dict[str, Any]], used: set[int]
) -> dict[str, Any] | None:
    """Greedy best actual span for an expected capture (domain first)."""
    obj = want.get("object_type") or want.get("object")
    op = want.get("operation")
    for i, got in enumerate(actual):
        if i in used:
            continue
        if want.get("domain") and got.get("domain") != want.get("domain"):
            continue
        if obj and got.get("object_type") != obj:
            continue
        if op and got.get("operation") != op:
            continue
        used.add(i)
        return got
    # Fall back to domain-only match (field scoring still meaningful).
    for i, got in enumerate(actual):
        if i in used:
            continue
        if want.get("domain") and got.get("domain") == want.get("domain"):
            used.add(i)
            return got
    return None


def _bucket_for(card: PackScorecard, confidence: float) -> CalibrationBucket | None:
    for bucket in card.calibration:
        if bucket.lower <= confidence < bucket.upper:
            return bucket
    return card.calibration[-1] if card.calibration else None


def _score_case(score: CaseScore, corpus: CorpusScore) -> None:
    expected = score.expected
    actual = score.actual
    kind = expected.get("kind") or "captures"

    corpus.total += 1
    if score.ok:
        corpus.routing_correct += 1

    # Negative cases: any real auto_apply span is a false completed action.
    if kind == "negative":
        for got in actual:
            dom = got.get("domain")
            if dom in _REAL_DOMAIN_EXCLUDE:
                continue
            if got.get("disposition") == "auto_apply":
                corpus.false_completed_actions += 1
                corpus.scorecard(str(dom)).false_completed_actions += 1
        return

    packs = _expected_packs(expected)
    for pack in packs:
        card = corpus.scorecard(pack)
        card.routing_total += 1
        if score.ok:
            card.routing_correct += 1

    # Field / disposition / calibration scoring against matched captures.
    used: set[int] = set()
    for want in _expected_captures(expected):
        dom = want.get("domain")
        card = corpus.scorecard(str(dom)) if dom else None
        got = _match_actual(want, actual, used)
        if card is None:
            continue

        want_fields = want.get("fields") or {}
        got_fields = (got.get("fields") if got else None) or {}
        for fk, fv in want_fields.items():
            if fk in got_fields and _fields_equal(fv, got_fields[fk]):
                card.field_tp += 1
            else:
                card.field_fn += 1
        # Extra fields the model volunteered that weren't expected: soft FP only
        # when the expected set is non-empty (avoids penalizing rich extraction
        # on fixtures that assert no fields).
        if want_fields:
            for gk in got_fields:
                if gk not in want_fields:
                    card.field_fp += 1

        want_disp = want.get("disposition")
        if want_disp is not None and got is not None:
            card.disposition_total += 1
            if got.get("disposition") == want_disp:
                card.disposition_correct += 1
            elif got.get("disposition") == "auto_apply" and want_disp in {
                "review",
                "confirm",
                "unfiled",
                "ledger_only",
            }:
                corpus.false_completed_actions += 1
                card.false_completed_actions += 1

        if got is not None:
            conf = float(got.get("confidence") or 0.0)
            bucket = _bucket_for(card, conf)
            if bucket is not None:
                bucket.n += 1
                bucket.confidence_sum += conf
                if score.ok:
                    bucket.correct += 1


def score_report(report: EvalReport) -> CorpusScore:
    """Compute per-pack scorecards from a completed replay report."""
    corpus = CorpusScore()
    for score in report.scores:
        _score_case(score, corpus)
    return corpus
