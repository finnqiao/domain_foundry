"""P7 gate: full scoring, committed baseline, backfill, sanitized export."""

from __future__ import annotations

import json
from pathlib import Path

from domain_expert_core.api.harness import HarnessAPI
from domain_expert_core.evals.baseline import (
    default_baseline_path,
    diff_baseline,
    load_baseline,
    save_baseline,
)
from domain_expert_core.evals.export import sanitize_text
from domain_expert_core.evals.runner import run_eval
from domain_expert_core.evals.scoring import score_report
from domain_expert_core.paths import Workspace
from domain_expert_core.security.store import connect_rw

CORPUS = (
    Path(__file__).resolve().parents[2] / "examples" / "synthetic" / "routing_eval.jsonl"
)


def _ready(workspace: Workspace) -> HarnessAPI:
    api = HarnessAPI(workspace.home)
    api.init()
    api.packs.activate_bundled("sourdough")
    api.packs.activate_bundled("plants")
    return api


def test_committed_baseline_has_no_regression(workspace: Workspace):
    """The committed baseline snapshot must match a fresh replay (CI PR gate)."""
    assert default_baseline_path().exists(), "baseline snapshot must be committed"
    report = run_eval(CORPUS, workspace=workspace, packs=["plants", "sourdough"])
    score = score_report(report)
    baseline = load_baseline()
    assert baseline is not None
    diff = diff_baseline(score, baseline)
    assert not diff.has_regression, diff.report()


def test_full_scorecard_shape(workspace: Workspace):
    report = run_eval(CORPUS, workspace=workspace, packs=["plants", "sourdough"])
    score = score_report(report)
    data = score.to_dict()
    assert data["overall"]["total"] == 65
    assert data["overall"]["false_completed_actions"] == 0
    for pack in ("sourdough", "plants"):
        card = data["packs"][pack]
        assert 0.0 <= card["routing_accuracy"] <= 1.0
        assert 0.0 <= card["field_f1"] <= 1.0
        assert card["disposition_accuracy"] == 1.0
        # calibration buckets are populated for matched captures
        assert any(b["n"] for b in card["calibration"])


def test_zero_false_completed_actions_on_negatives(workspace: Workspace):
    """Release-blocking safety category: no negative-case auto-apply (§10.3)."""
    report = run_eval(CORPUS, workspace=workspace, packs=["plants", "sourdough"])
    score = score_report(report)
    assert score.false_completed_actions == 0


def test_backfill_creates_eval_cases_from_pre_p3_corrections(workspace: Workspace):
    api = _ready(workspace)
    cap = api.capture(
        "baked a 75% hydration country loaf, bulk 5h, came out great",
        channel="cli",
        source_ref="bf-1",
    )
    # Simulate a *pre-P3* correction: a resolved correction_event with no eval_case.
    conn = connect_rw(workspace.ledger_db)
    try:
        conn.execute(
            """
            INSERT INTO correction_event
                (entry_id, target_kind, target_id, reason_code, wrong_json,
                 right_json, created_at)
            VALUES (?, 'object', ?, 'wrong_field', ?, ?, '2026-01-01T00:00:00Z')
            """,
            (
                cap.entry_id,
                "obj-legacy",
                json.dumps({"hydration": 75}),
                json.dumps(
                    {"domain": "sourdough", "object_type": "bake", "operation": "create",
                     "fields": {"hydration": 80}}
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    dry = api.eval_backfill(dry_run=True)
    assert dry["created"] == 1

    result = api.eval_backfill()
    assert result["created"] == 1

    # Idempotent: re-running creates nothing new.
    again = api.eval_backfill()
    assert again["created"] == 0
    assert again["skipped_existing"] >= 1

    conn = connect_rw(workspace.ledger_db)
    try:
        row = conn.execute(
            "SELECT expected_json, context_json FROM eval_case "
            "WHERE id = ?",
            (result["created_ids"][0],),
        ).fetchone()
    finally:
        conn.close()
    expected = json.loads(row["expected_json"])
    assert expected["captures"][0]["fields"]["hydration"] == 80
    assert json.loads(row["context_json"])["backfilled"] is True


def test_export_sanitizes_pii(workspace: Workspace, tmp_path: Path):
    api = _ready(workspace)
    cap = api.capture("baked a loaf, ping me at a@b.com", channel="cli", source_ref="ex-1")
    conn = connect_rw(workspace.ledger_db)
    try:
        conn.execute(
            """
            INSERT INTO eval_case
                (id, source, raw_text, context_json, expected_json,
                 provenance_json, created_at)
            VALUES (?, 'correction', ?, '{}', ?, '{}', '2026-01-01T00:00:00Z')
            """,
            (
                "ec_export_1",
                "email me at jane.doe@example.com or +1 415 555 0132",
                json.dumps({"captures": [{"domain": "sourdough", "fields": {"notes": "see http://evil.example/x"}}]}),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    out = tmp_path / "contrib.jsonl"
    report = api.eval_export(out, sanitize=True, source="correction")
    assert report["exported"] >= 1
    text = out.read_text(encoding="utf-8")
    assert "jane.doe@example.com" not in text
    assert "example.com" not in text or "[EMAIL]" in text
    assert "[EMAIL]" in text
    assert "evil.example" not in text
    assert report["redaction_count"] >= 1
    # unused capture var kept for realism of the flow
    assert cap.entry_id


def test_sanitize_text_helper():
    out, kinds = sanitize_text("reach me at bob@corp.io and sk-ABCDEFGHIJKLMNOPQRST12345")
    assert "bob@corp.io" not in out
    assert "sk-ABCDEFGHIJKLMNOPQRST12345" not in out
    assert "EMAIL" in kinds
    assert "SECRET" in kinds


def test_save_and_diff_roundtrip(workspace: Workspace, tmp_path: Path):
    report = run_eval(CORPUS, workspace=workspace, packs=["plants", "sourdough"])
    score = score_report(report)
    path = tmp_path / "baseline.json"
    save_baseline(score, path)
    baseline = load_baseline(path)
    assert baseline is not None
    diff = diff_baseline(score, baseline)
    assert not diff.has_regression
