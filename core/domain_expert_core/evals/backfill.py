"""Correction -> corpus backfill for pre-P3 data (plan §10.1, `eval backfill`).

P3 auto-appends an ``eval_case`` whenever a correction resolves. Installs that
accumulated corrections *before* that wiring (or imported history) have
``correction_event`` rows with no matching ``eval_case``. This backfills them:
the expected interpretation is the corrected (`right_json`) shape and the input
is the *original* raw capture text + pack context.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from domain_expert_core.clock import now_iso
from domain_expert_core.ids import new_ulid
from domain_expert_core.paths import Workspace
from domain_expert_core.security.store import connect_rw


@dataclass
class BackfillReport:
    scanned: int = 0
    created: int = 0
    skipped_existing: int = 0
    skipped_no_right: int = 0
    created_ids: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "created": self.created,
            "skipped_existing": self.skipped_existing,
            "skipped_no_right": self.skipped_no_right,
            "created_ids": self.created_ids or [],
        }


def _raw_text_for_entry(conn: Any, entry_id: str | None) -> str | None:
    if not entry_id:
        return None
    row = conn.execute(
        """
        SELECT c.raw_text
        FROM entry e
        JOIN capture_event c ON c.id = e.capture_event_id
        WHERE e.id = ?
        """,
        (entry_id,),
    ).fetchone()
    return row["raw_text"] if row else None


def _expected_from_right(right: dict[str, Any]) -> dict[str, Any]:
    """Normalize a correction's right-hand side into eval expected shape."""
    if "captures" in right:
        return {"captures": right["captures"]}
    capture = {
        k: v
        for k, v in right.items()
        if k in {"domain", "object_type", "operation", "fields", "disposition"}
    }
    if capture:
        return {"captures": [capture]}
    # Fallback: store the raw corrected fields for auditing.
    return {"captures": [{"fields": right}]}


def backfill_corrections(
    workspace: Workspace, *, dry_run: bool = False, limit: int = 1000
) -> BackfillReport:
    report = BackfillReport(created_ids=[])
    conn = connect_rw(workspace.ledger_db)
    try:
        existing = {
            int(r["correction_event_id"])
            for r in conn.execute(
                "SELECT DISTINCT correction_event_id FROM eval_case "
                "WHERE correction_event_id IS NOT NULL"
            ).fetchall()
        }
        rows = conn.execute(
            """
            SELECT id, entry_id, target_kind, target_id, reason_code,
                   right_json, created_at
            FROM correction_event
            WHERE right_json IS NOT NULL
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        for row in rows:
            report.scanned += 1
            ce_id = int(row["id"])
            if ce_id in existing:
                report.skipped_existing += 1
                continue
            right = json.loads(row["right_json"]) if row["right_json"] else None
            if not right:
                report.skipped_no_right += 1
                continue
            raw_text = _raw_text_for_entry(conn, row["entry_id"])
            if raw_text is None:
                # No capture to replay against; skip rather than fabricate input.
                report.skipped_no_right += 1
                continue

            expected = _expected_from_right(right)
            case_id = f"ec_{new_ulid()}"
            ts = now_iso()
            context = {
                "packs": [],
                "date": ts[:10],
                "open_hints": [],
                "backfilled": True,
                "reason_code": row["reason_code"],
            }
            provenance = {"correction_event_id": ce_id, "backfilled": True}
            if not dry_run:
                conn.execute(
                    """
                    INSERT INTO eval_case (
                        id, source, raw_text, context_json, expected_json,
                        provenance_json, correction_event_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        case_id,
                        "correction",
                        raw_text,
                        json.dumps(context, separators=(",", ":")),
                        json.dumps(expected, separators=(",", ":")),
                        json.dumps(provenance, separators=(",", ":")),
                        ce_id,
                        ts,
                    ),
                )
            report.created += 1
            assert report.created_ids is not None
            report.created_ids.append(case_id)
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return report
