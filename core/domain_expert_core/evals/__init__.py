"""Evaluation replay framework (plan §10)."""

from domain_expert_core.evals.backfill import backfill_corrections
from domain_expert_core.evals.baseline import diff_baseline, load_baseline, save_baseline
from domain_expert_core.evals.export import export_cases
from domain_expert_core.evals.runner import EvalReport, run_eval
from domain_expert_core.evals.scoring import CorpusScore, score_report

__all__ = [
    "EvalReport",
    "run_eval",
    "score_report",
    "CorpusScore",
    "load_baseline",
    "save_baseline",
    "diff_baseline",
    "backfill_corrections",
    "export_cases",
]
