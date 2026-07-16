"""Few-shot bank rebuild + eval_case append from corrections."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from domain_expert_core.clock import now_iso
from domain_expert_core.ids import new_ulid
from domain_expert_core.paths import Workspace
from domain_expert_core.security.store import connect_rw

# Rough token budget for injection into L2 prompts
DEFAULT_TOKEN_BUDGET = 1200


def fewshot_path(workspace: Workspace) -> Path:
    return workspace.home / "fewshot.json"


def rebuild_fewshot_bank(
    workspace: Workspace, *, token_budget: int = DEFAULT_TOKEN_BUDGET
) -> dict[str, Any]:
    """Select representative wrong→right pairs per reason_code under a token budget."""
    conn = connect_rw(workspace.ledger_db)
    try:
        rows = conn.execute(
            """
            SELECT id, reason_code, wrong_json, right_json, entry_id, created_at
            FROM correction_event
            WHERE right_json IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 200
            """
        ).fetchall()
    finally:
        conn.close()

    by_reason: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        reason = str(r["reason_code"] or "other")
        example = {
            "correction_event_id": r["id"],
            "reason_code": reason,
            "wrong": json.loads(r["wrong_json"]) if r["wrong_json"] else None,
            "right": json.loads(r["right_json"]) if r["right_json"] else None,
            "entry_id": r["entry_id"],
        }
        by_reason.setdefault(reason, []).append(example)

    selected: list[dict[str, Any]] = []
    # round-robin across reason codes
    reasons = sorted(by_reason)
    idxs = {k: 0 for k in reasons}
    approx_tokens = 0
    while reasons and approx_tokens < token_budget:
        progressed = False
        for reason in list(reasons):
            bucket = by_reason[reason]
            i = idxs[reason]
            if i >= len(bucket):
                reasons.remove(reason)
                continue
            ex = bucket[i]
            idxs[reason] = i + 1
            chunk = json.dumps(ex, separators=(",", ":"))
            cost = max(1, len(chunk) // 4)
            if approx_tokens + cost > token_budget and selected:
                reasons = []
                break
            selected.append(ex)
            approx_tokens += cost
            progressed = True
        if not progressed:
            break

    bank = {
        "version": 1,
        "built_at": now_iso(),
        "totalExamples": len(selected),
        "approx_tokens": approx_tokens,
        "examples": selected,
    }
    path = fewshot_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bank, indent=2), encoding="utf-8")
    return bank


def load_fewshot_bank(workspace: Workspace) -> dict[str, Any]:
    path = fewshot_path(workspace)
    if not path.exists():
        return {"version": 1, "totalExamples": 0, "examples": []}
    return json.loads(path.read_text(encoding="utf-8"))


def append_eval_case(
    workspace: Workspace,
    *,
    source: str,
    raw_text: str,
    expected: dict[str, Any],
    correction_event_id: int | None = None,
    context: dict[str, Any] | None = None,
) -> str:
    """Auto-append an eval_case (closes the private-system gap)."""
    case_id = f"ec_{new_ulid()}"
    ts = now_iso()
    ctx = context or {"packs": [], "date": ts[:10], "open_hints": []}
    provenance = {
        "correction_event_id": correction_event_id,
    }
    conn = connect_rw(workspace.ledger_db)
    try:
        conn.execute(
            """
            INSERT INTO eval_case (
                id, source, raw_text, context_json, expected_json,
                provenance_json, correction_event_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                source,
                raw_text,
                json.dumps(ctx, separators=(",", ":")),
                json.dumps(expected, separators=(",", ":")),
                json.dumps(provenance, separators=(",", ":")),
                correction_event_id,
                ts,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return case_id
