"""Committed baseline snapshots + regression diff (plan §10.2/§10.3).

The baseline is a small JSON file checked into the repo. Every PR replays the
corpus with cassettes and diffs the fresh scorecards against this baseline; any
per-pack drop (routing accuracy, field F1, disposition accuracy) or any increase
in false-completed-action cases fails the build with a legible message.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from domain_foundry_core.evals.scoring import CorpusScore

# Floating point slack so identical deterministic runs never spuriously regress.
_EPSILON = 1e-6


def default_baseline_path() -> Path:
    """Repo-committed baseline for the bundled synthetic corpus."""
    return _repo_root() / "examples" / "synthetic" / "eval_baseline.json"


def _repo_root() -> Path:
    # core/domain_foundry_core/evals/baseline.py -> repo root is parents[3]
    return Path(__file__).resolve().parents[3]


def save_baseline(score: CorpusScore, path: Path | None = None) -> Path:
    target = path or default_baseline_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(score.to_baseline(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def load_baseline(path: Path | None = None) -> dict[str, Any] | None:
    target = path or default_baseline_path()
    if not target.exists():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


@dataclass
class Regression:
    pack: str
    metric: str
    baseline: float
    current: float

    @property
    def delta(self) -> float:
        return self.current - self.baseline

    def __str__(self) -> str:
        return (
            f"{self.pack}: {self.metric} {self.baseline:.3f} -> {self.current:.3f} "
            f"({self.delta:+.3f})"
        )


@dataclass
class RegressionDiff:
    regressions: list[Regression] = field(default_factory=list)
    missing_packs: list[str] = field(default_factory=list)

    @property
    def has_regression(self) -> bool:
        return bool(self.regressions or self.missing_packs)

    def report(self) -> str:
        if not self.has_regression:
            return "no regressions vs baseline"
        lines = ["REGRESSIONS vs baseline:"]
        for pack in self.missing_packs:
            lines.append(f"  - {pack}: pack missing from current run")
        for reg in self.regressions:
            lines.append(f"  - {reg}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_regression": self.has_regression,
            "missing_packs": list(self.missing_packs),
            "regressions": [
                {
                    "pack": r.pack,
                    "metric": r.metric,
                    "baseline": round(r.baseline, 4),
                    "current": round(r.current, 4),
                    "delta": round(r.delta, 4),
                }
                for r in self.regressions
            ],
        }


# Per-pack metrics that must not drop below baseline.
_MONOTONE_METRICS = ("routing_accuracy", "field_f1", "disposition_accuracy")


def diff_baseline(current: CorpusScore, baseline: dict[str, Any]) -> RegressionDiff:
    """Compare a fresh corpus score against a committed baseline snapshot."""
    diff = RegressionDiff()
    cur = current.to_baseline()

    # Overall false-completed actions are release-blocking at zero (§10.3).
    base_fca = baseline.get("overall", {}).get("false_completed_actions", 0)
    cur_fca = cur["overall"]["false_completed_actions"]
    if cur_fca > base_fca:
        diff.regressions.append(
            Regression("<overall>", "false_completed_actions", base_fca, cur_fca)
        )

    base_packs: dict[str, Any] = baseline.get("packs", {})
    cur_packs: dict[str, Any] = cur["packs"]
    for pack, base_metrics in base_packs.items():
        if pack not in cur_packs:
            diff.missing_packs.append(pack)
            continue
        cur_metrics = cur_packs[pack]
        for metric in _MONOTONE_METRICS:
            base_val = float(base_metrics.get(metric, 0.0))
            cur_val = float(cur_metrics.get(metric, 0.0))
            if cur_val + _EPSILON < base_val:
                diff.regressions.append(Regression(pack, metric, base_val, cur_val))
        base_pack_fca = int(base_metrics.get("false_completed_actions", 0))
        cur_pack_fca = int(cur_metrics.get("false_completed_actions", 0))
        if cur_pack_fca > base_pack_fca:
            diff.regressions.append(
                Regression(pack, "false_completed_actions", base_pack_fca, cur_pack_fca)
            )
    return diff
