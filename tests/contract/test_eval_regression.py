"""P7 acceptance gate: a deliberately-breakable per-pack regression path.

Mutating the expected routing in a fixture must produce a clear per-pack
regression failure vs the committed baseline; restoring the fixture passes.
This is the "break a heuristic on a branch -> CI fails with a legible per-pack
diff; restore -> green" gate from plan §10.3.
"""

from __future__ import annotations

import json
from pathlib import Path

from domain_foundry_core.evals.baseline import diff_baseline, load_baseline, save_baseline
from domain_foundry_core.evals.runner import run_eval
from domain_foundry_core.evals.scoring import score_report
from domain_foundry_core.paths import Workspace

CORPUS = (
    Path(__file__).resolve().parents[2] / "examples" / "synthetic" / "routing_eval.jsonl"
)


def _score(corpus: Path, workspace: Workspace):
    report = run_eval(corpus, workspace=workspace, packs=["plants", "sourdough"])
    return score_report(report)


def _mutate_one_sourdough_case(corpus: Path, dest: Path) -> str:
    """Break a single sourdough fixture's expected operation so routing misses."""
    lines = corpus.read_text(encoding="utf-8").splitlines()
    mutated_id = ""
    out: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        case = json.loads(line)
        caps = case.get("expected", {}).get("captures") or []
        if not mutated_id and caps and caps[0].get("domain") == "sourdough":
            caps[0]["operation"] = "delete"  # router emits "create" -> mismatch
            mutated_id = case["id"]
        out.append(json.dumps(case))
    dest.write_text("\n".join(out) + "\n", encoding="utf-8")
    return mutated_id


def test_break_then_restore_regression(workspace: Workspace, tmp_path: Path):
    # 1) Baseline from the pristine corpus.
    baseline_path = tmp_path / "baseline.json"
    save_baseline(_score(CORPUS, workspace), baseline_path)
    baseline = load_baseline(baseline_path)
    assert baseline is not None

    # 2) Break one sourdough fixture -> per-pack regression, legible message.
    mutated = tmp_path / "mutated.jsonl"
    mutated_id = _mutate_one_sourdough_case(CORPUS, mutated)
    assert mutated_id

    broken_diff = diff_baseline(_score(mutated, workspace), baseline)
    assert broken_diff.has_regression, "mutation should regress"
    packs_hit = {r.pack for r in broken_diff.regressions}
    metrics_hit = {r.metric for r in broken_diff.regressions}
    assert "sourdough" in packs_hit
    assert "plants" not in packs_hit  # regression is isolated per pack
    assert "routing_accuracy" in metrics_hit
    assert "sourdough: routing_accuracy" in broken_diff.report()

    # 3) Restore the fixture -> green.
    restored_diff = diff_baseline(_score(CORPUS, workspace), baseline)
    assert not restored_diff.has_regression, restored_diff.report()


def test_false_completed_action_is_release_blocking(workspace: Workspace, tmp_path: Path):
    """An injected false-completed-action fails the gate even at count 1."""
    baseline_path = tmp_path / "baseline.json"
    save_baseline(_score(CORPUS, workspace), baseline_path)
    baseline = load_baseline(baseline_path)
    assert baseline is not None
    # Forge a scorecard with a false-completed action and confirm the diff blocks.
    score = _score(CORPUS, workspace)
    score.false_completed_actions += 1
    score.scorecard("sourdough").false_completed_actions += 1
    diff = diff_baseline(score, baseline)
    assert diff.has_regression
    assert any(r.metric == "false_completed_actions" for r in diff.regressions)
