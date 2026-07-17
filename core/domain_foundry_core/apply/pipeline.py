"""Post-route disposition pipeline: auto_apply via executor, review stays queued."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from domain_foundry_core.apply.executor import CanonicalChangeExecutor, ExecutionReceipt
from domain_foundry_core.clock import now_iso
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_rw


@dataclass
class PipelineResult:
    entry_id: str
    status: str
    receipts: list[ExecutionReceipt] = field(default_factory=list)
    pending_approvals: list[str] = field(default_factory=list)


class ApplyPipeline:
    def __init__(
        self,
        workspace: Workspace,
        *,
        registry: PackRegistry | None = None,
        executor: CanonicalChangeExecutor | None = None,
    ) -> None:
        self.ws = workspace
        self.registry = registry or PackRegistry(workspace)
        self.executor = executor or CanonicalChangeExecutor(
            workspace, registry=self.registry
        )

    def process_entry(self, entry_id: str, *, channel: str = "cli") -> PipelineResult:
        conn = connect_rw(self.ws.ledger_db)
        try:
            crs = conn.execute(
                """
                SELECT id, payload_json, status, operation, domain
                FROM change_request
                WHERE entry_id = ? AND status = 'pending'
                ORDER BY id
                """,
                (entry_id,),
            ).fetchall()
        finally:
            conn.close()

        receipts: list[ExecutionReceipt] = []
        pending: list[str] = []
        any_failed = False

        for cr in crs:
            payload = json.loads(cr["payload_json"] or "{}")
            disposition = str(payload.get("disposition") or "review")
            if disposition == "auto_apply":
                receipt = self.executor.execute_change_request(
                    int(cr["id"]),
                    actor="auto_apply",
                    actor_channel=channel,
                )
                receipts.append(receipt)
                if not receipt.applied and not receipt.replayed:
                    any_failed = True
            elif disposition in {"review", "confirm"}:
                # ensure approval row exists
                aid = self._ensure_approval(int(cr["id"]), domain=str(cr["domain"]))
                if aid:
                    pending.append(aid)
            # reject / unfiled handled elsewhere

        status = self._recompute_entry_status(entry_id, any_failed=any_failed)
        return PipelineResult(
            entry_id=entry_id,
            status=status,
            receipts=receipts,
            pending_approvals=pending,
        )

    def _ensure_approval(self, change_request_id: int, *, domain: str) -> str | None:
        from domain_foundry_core.ids import new_ulid

        ts = now_iso()
        conn = connect_rw(self.ws.ledger_db)
        try:
            existing = conn.execute(
                "SELECT id FROM approval_queue WHERE change_request_id = ?",
                (change_request_id,),
            ).fetchone()
            if existing:
                return str(existing["id"])
            cr = conn.execute(
                "SELECT payload_json FROM change_request WHERE id = ?",
                (change_request_id,),
            ).fetchone()
            payload = json.loads(cr["payload_json"] or "{}") if cr else {}
            aid = new_ulid()
            conn.execute(
                """
                INSERT INTO approval_queue (
                    id, change_request_id, decision_status, application_status,
                    domain, summary, diff_json, created_at
                ) VALUES (?, ?, 'pending', 'not_started', ?, ?, ?, ?)
                """,
                (
                    aid,
                    change_request_id,
                    domain,
                    str(payload.get("span") or "")[:200],
                    json.dumps({"fields": payload.get("fields") or {}}, separators=(",", ":")),
                    ts,
                ),
            )
            conn.commit()
            return aid
        finally:
            conn.close()

    def _recompute_entry_status(self, entry_id: str, *, any_failed: bool) -> str:
        ts = now_iso()
        conn = connect_rw(self.ws.ledger_db)
        try:
            entry = conn.execute(
                "SELECT status, fallback_tier FROM entry WHERE id = ?", (entry_id,)
            ).fetchone()
            if entry and entry["status"] in {"unfiled", "ledger_only"}:
                return str(entry["status"])

            crs = conn.execute(
                "SELECT status, payload_json FROM change_request WHERE entry_id = ?",
                (entry_id,),
            ).fetchall()
            if not crs:
                status = "ledger_only"
            else:
                statuses = [str(r["status"]) for r in crs]
                dispositions = [
                    str(json.loads(r["payload_json"] or "{}").get("disposition") or "")
                    for r in crs
                ]
                pending_review = any(
                    s == "pending" and d in {"review", "confirm"}
                    for s, d in zip(statuses, dispositions, strict=False)
                )
                all_applied = all(s == "applied" for s in statuses)
                if pending_review:
                    status = "review"
                elif all_applied and not any_failed:
                    status = "applied"
                elif any(s == "failed" for s in statuses) or any_failed:
                    status = "review"
                else:
                    status = "review"

            conn.execute(
                "UPDATE entry SET status = ?, updated_at = ? WHERE id = ?",
                (status, ts, entry_id),
            )
            conn.commit()
            return status
        finally:
            conn.close()


def list_approvals(
    workspace: Workspace,
    *,
    status: str = "pending",
    domain: str | None = None,
) -> list[dict[str, Any]]:
    conn = connect_rw(workspace.ledger_db)
    try:
        sql = """
            SELECT a.*, c.operation, c.object_type, c.object_uid, c.confidence,
                   c.payload_json, c.status AS change_status
            FROM approval_queue a
            JOIN change_request c ON c.id = a.change_request_id
            WHERE a.decision_status = ?
        """
        params: list[Any] = [status]
        if domain:
            sql += " AND a.domain = ?"
            params.append(domain)
        sql += " ORDER BY a.created_at ASC"
        rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "approval_id": r["id"],
                    "change_request_id": r["change_request_id"],
                    "decision_status": r["decision_status"],
                    "application_status": r["application_status"],
                    "domain": r["domain"],
                    "operation": r["operation"],
                    "object_type": r["object_type"],
                    "object_uid": r["object_uid"],
                    "summary": r["summary"],
                    "confidence": r["confidence"],
                    "change_status": r["change_status"],
                    "created_at": r["created_at"],
                    "resolved_at": r["resolved_at"],
                }
            )
        return out
    finally:
        conn.close()
