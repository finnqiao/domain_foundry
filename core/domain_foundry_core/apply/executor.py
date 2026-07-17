"""CanonicalChangeExecutor — approve ⇒ apply exactly once."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from domain_foundry_core.apply.engine import ApplyEngine, OperationSpec
from domain_foundry_core.apply.journal import write_change_request_result
from domain_foundry_core.clock import now_iso
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_rw

APPLIED = frozenset({"applied"})
TERMINAL_DECISIONS = frozenset({"approved", "denied", "expired"})


@dataclass
class ExecutionReceipt:
    applied: bool
    change_request_id: int
    replayed: bool = False
    object_uid: str | None = None
    approval_id: str | None = None
    decision_status: str | None = None
    application_status: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    projection_status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "change_request_id": self.change_request_id,
            "replayed": self.replayed,
            "object_uid": self.object_uid,
            "approval_id": self.approval_id,
            "decision_status": self.decision_status,
            "application_status": self.application_status,
            "result": self.result,
            "error": self.error,
            "projection_status": self.projection_status,
        }


class CanonicalChangeExecutor:
    def __init__(
        self,
        workspace: Workspace,
        *,
        registry: PackRegistry | None = None,
        engine: ApplyEngine | None = None,
    ) -> None:
        self.ws = workspace
        self.registry = registry or PackRegistry(workspace)
        self.engine = engine or ApplyEngine(workspace, registry=self.registry)

    def execute_change_request(
        self,
        change_request_id: int,
        *,
        actor: str = "system",
        actor_channel: str | None = None,
        approval_id: str | None = None,
    ) -> ExecutionReceipt:
        """Apply a change_request exactly once. Safe under double-call / crash retry."""
        conn = connect_rw(self.ws.ledger_db)
        try:
            row = conn.execute(
                "SELECT * FROM change_request WHERE id = ?",
                (change_request_id,),
            ).fetchone()
            if row is None:
                return ExecutionReceipt(
                    applied=False,
                    change_request_id=change_request_id,
                    error=f"change_request {change_request_id} not found",
                )

            if str(row["status"] or "") in APPLIED and row["result_json"] and not row["error"]:
                prior = json.loads(row["result_json"])
                return ExecutionReceipt(
                    applied=True,
                    replayed=True,
                    change_request_id=change_request_id,
                    object_uid=row["object_uid"],
                    approval_id=approval_id,
                    application_status="applied",
                    result=prior,
                    projection_status="pending",
                )

            if str(row["status"] or "") in {"denied", "expired"}:
                return ExecutionReceipt(
                    applied=False,
                    change_request_id=change_request_id,
                    error=f"change_request is {row['status']!r}",
                )

            payload = json.loads(row["payload_json"] or "{}")
            if not isinstance(payload, dict):
                payload = {}

            fields = dict(payload.get("fields") or {})
            if payload.get("span"):
                fields["_span"] = payload["span"]

            spec = OperationSpec(
                domain=str(row["domain"]),
                operation=str(row["operation"]),
                object_type=str(row["object_type"] or "note"),
                object_uid=row["object_uid"] or payload.get("object_uid"),
                merge_into_uid=payload.get("merge_into_uid"),
                payload=fields,
                confidence=float(row["confidence"] or 1.0),
                entry_id=str(row["entry_id"]) if row["entry_id"] else None,
                channel=str(row["channel"]) if row["channel"] else actor_channel,
            )

            # Hold a write lock marker so concurrent double-resolve serializes
            conn.execute(
                "UPDATE change_request SET status = 'pending', error = NULL WHERE id = ?",
                (change_request_id,),
            )
            conn.commit()
        finally:
            conn.close()

        apply_result = self.engine.apply_spec(
            spec,
            change_request_id=change_request_id,
            actor=actor,
            actor_channel=actor_channel,
        )

        ts = now_iso()
        conn = connect_rw(self.ws.ledger_db)
        try:
            # Re-check for races: another worker may have applied meanwhile
            again = conn.execute(
                "SELECT status, result_json, object_uid, error FROM change_request WHERE id = ?",
                (change_request_id,),
            ).fetchone()
            if (
                again
                and str(again["status"]) in APPLIED
                and again["result_json"]
                and not again["error"]
            ):
                prior = json.loads(again["result_json"])
                self._touch_approval(
                    conn,
                    change_request_id=change_request_id,
                    approval_id=approval_id,
                    decision="approved",
                    application="applied",
                    receipt={"replayed": True, **prior},
                    now=ts,
                )
                conn.commit()
                return ExecutionReceipt(
                    applied=True,
                    replayed=True,
                    change_request_id=change_request_id,
                    object_uid=again["object_uid"],
                    approval_id=approval_id,
                    decision_status="approved",
                    application_status="applied",
                    result=prior,
                )

            if not apply_result.ok:
                write_change_request_result(
                    conn,
                    change_request_id=change_request_id,
                    object_uid=None,
                    result_json=None,
                    error=apply_result.error,
                    now=ts,
                    status="failed",
                )
                self._touch_approval(
                    conn,
                    change_request_id=change_request_id,
                    approval_id=approval_id,
                    decision="approved" if approval_id else None,
                    application="failed",
                    receipt={"error": apply_result.error},
                    now=ts,
                )
                conn.commit()
                return ExecutionReceipt(
                    applied=False,
                    change_request_id=change_request_id,
                    approval_id=approval_id,
                    application_status="failed",
                    error=apply_result.error,
                )

            result_json = {
                "applied": True,
                "approval_id": approval_id,
                "object_uid": apply_result.object_uid,
                "row_id": apply_result.row_id,
                "revision": apply_result.revision,
                "operation": apply_result.operation,
                "details": apply_result.details,
            }
            write_change_request_result(
                conn,
                change_request_id=change_request_id,
                object_uid=apply_result.object_uid,
                result_json=result_json,
                error=None,
                now=ts,
                status="applied",
            )
            self._touch_approval(
                conn,
                change_request_id=change_request_id,
                approval_id=approval_id,
                decision="approved",
                application="applied",
                receipt=result_json,
                now=ts,
            )
            # Mark interpretation applied when linked
            conn.execute(
                """
                UPDATE interpretation SET status = 'applied'
                WHERE id = (SELECT interpretation_id FROM change_request WHERE id = ?)
                """,
                (change_request_id,),
            )
            conn.commit()
            return ExecutionReceipt(
                applied=True,
                replayed=False,
                change_request_id=change_request_id,
                object_uid=apply_result.object_uid,
                approval_id=approval_id,
                decision_status="approved",
                application_status="applied",
                result=result_json,
                projection_status="pending",
            )
        finally:
            conn.close()

    def resolve_approval(
        self,
        approval_id: str,
        *,
        decision: str,
        note: str | None = None,
        resolver: str = "user",
    ) -> ExecutionReceipt:
        """Approve → apply exactly once; deny/expire without apply."""
        if decision not in {"approved", "denied", "expired"}:
            raise ValueError(f"decision must be approved|denied|expired, got {decision!r}")

        ts = now_iso()
        conn = connect_rw(self.ws.ledger_db)
        try:
            row = conn.execute(
                "SELECT * FROM approval_queue WHERE id = ?", (approval_id,)
            ).fetchone()
            if row is None:
                return ExecutionReceipt(
                    applied=False,
                    change_request_id=0,
                    approval_id=approval_id,
                    error=f"approval {approval_id} not found",
                )

            cr_id = int(row["change_request_id"])

            # Exactly-once: if already applied, return prior receipt
            if (
                str(row["decision_status"]) == "approved"
                and str(row["application_status"]) == "applied"
            ):
                prior = {}
                if row["execution_receipt_json"]:
                    prior = json.loads(row["execution_receipt_json"])
                return ExecutionReceipt(
                    applied=True,
                    replayed=True,
                    change_request_id=cr_id,
                    approval_id=approval_id,
                    decision_status="approved",
                    application_status="applied",
                    result=prior,
                    object_uid=prior.get("object_uid"),
                )

            if decision in {"denied", "expired"}:
                conn.execute(
                    """
                    UPDATE approval_queue SET
                        decision_status = ?, application_status = 'skipped',
                        resolved_at = ?, resolver = ?, resolver_note = ?
                    WHERE id = ?
                    """,
                    (decision, ts, resolver, note, approval_id),
                )
                conn.execute(
                    "UPDATE change_request SET status = ? WHERE id = ? AND status = 'pending'",
                    (decision, cr_id),
                )
                conn.commit()
                return ExecutionReceipt(
                    applied=False,
                    change_request_id=cr_id,
                    approval_id=approval_id,
                    decision_status=decision,
                    application_status="skipped",
                )

            # Mark decision approved before apply (independently queryable)
            conn.execute(
                """
                UPDATE approval_queue SET
                    decision_status = 'approved',
                    resolved_at = ?, resolver = ?, resolver_note = ?
                WHERE id = ?
                """,
                (ts, resolver, note, approval_id),
            )
            conn.commit()
        finally:
            conn.close()

        return self.execute_change_request(
            cr_id,
            actor=resolver,
            actor_channel="approval",
            approval_id=approval_id,
        )

    def _touch_approval(
        self,
        conn,
        *,
        change_request_id: int,
        approval_id: str | None,
        decision: str | None,
        application: str,
        receipt: dict[str, Any],
        now: str,
    ) -> None:
        if approval_id:
            conn.execute(
                """
                UPDATE approval_queue SET
                    decision_status = COALESCE(?, decision_status),
                    application_status = ?,
                    execution_receipt_json = ?,
                    resolved_at = COALESCE(resolved_at, ?)
                WHERE id = ?
                """,
                (
                    decision,
                    application,
                    json.dumps(receipt, sort_keys=True),
                    now,
                    approval_id,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE approval_queue SET
                    decision_status = COALESCE(?, decision_status),
                    application_status = ?,
                    execution_receipt_json = ?,
                    resolved_at = COALESCE(resolved_at, ?)
                WHERE change_request_id = ?
                """,
                (
                    decision,
                    application,
                    json.dumps(receipt, sort_keys=True),
                    now,
                    change_request_id,
                ),
            )
