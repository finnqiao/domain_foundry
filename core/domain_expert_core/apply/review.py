"""Review queue enrichment (P4): filters, diff previews, bulk ops, SLO counters.

Extends the basic list/resolve from P3 (`apply/pipeline.list_approvals`,
`executor.resolve_approval`) with the operational surface the review queue needs:
proposed-vs-canonical diffs, bulk triage, and SLO counters (pending / overdue /
oldest-age) — the backlog lesson from §3.4.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from domain_expert_core.apply.engine import load_domain_row
from domain_expert_core.clock import now
from domain_expert_core.paths import Workspace
from domain_expert_core.security.store import connect_ro

if TYPE_CHECKING:
    from domain_expert_core.apply.executor import CanonicalChangeExecutor

# Default SLO: a pending review older than this is "overdue".
DEFAULT_OVERDUE_SECONDS = 24 * 3600


def _age_seconds(iso_ts: str | None) -> float | None:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (now() - dt).total_seconds())


def review_diff(
    workspace: Workspace, approval_id: str
) -> dict[str, Any]:
    """Field-level diff of the proposed change vs the current canonical object."""
    conn = connect_ro(workspace.ledger_db)
    try:
        row = conn.execute(
            """
            SELECT a.id AS approval_id, c.domain, c.object_type, c.operation,
                   c.object_uid, c.payload_json
            FROM approval_queue a
            JOIN change_request c ON c.id = a.change_request_id
            WHERE a.id = ?
            """,
            (approval_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {"approval_id": approval_id, "error": "approval not found"}
    return _build_diff(
        workspace,
        domain=str(row["domain"]),
        object_type=str(row["object_type"] or ""),
        operation=str(row["operation"]),
        object_uid=row["object_uid"],
        payload_json=row["payload_json"],
    )


def _build_diff(
    workspace: Workspace,
    *,
    domain: str,
    object_type: str,
    operation: str,
    object_uid: str | None,
    payload_json: str | None,
) -> dict[str, Any]:
    payload = json.loads(payload_json or "{}")
    proposed = dict(payload.get("fields") or {})
    current: dict[str, Any] = {}
    if object_uid and object_type:
        row = load_domain_row(workspace.domains_db, domain, object_type, object_uid)
        if row:
            current = {
                k: v
                for k, v in row.items()
                if k not in {"id", "object_uid", "entry_id", "tombstoned"}
            }
    fields: list[dict[str, Any]] = []
    for key in sorted(set(proposed) | set(current)):
        cur_v = current.get(key)
        prop_v = proposed.get(key) if key in proposed else cur_v
        fields.append(
            {
                "field": key,
                "current": cur_v,
                "proposed": prop_v,
                "changed": key in proposed and cur_v != prop_v,
            }
        )
    return {
        "operation": operation,
        "object_uid": object_uid,
        "is_new": operation == "create" or not object_uid,
        "fields": fields,
    }


def review_items(
    workspace: Workspace,
    *,
    status: str = "pending",
    domain: str | None = None,
    operation: str | None = None,
    object_type: str | None = None,
    overdue_only: bool = False,
    overdue_seconds: int = DEFAULT_OVERDUE_SECONDS,
    include_diff: bool = True,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Enriched approval listing with filters, age, and (optionally) diffs."""
    conn = connect_ro(workspace.ledger_db)
    try:
        sql = """
            SELECT a.id AS approval_id, a.change_request_id, a.decision_status,
                   a.application_status, a.domain, a.summary, a.created_at,
                   a.resolved_at, a.expires_at,
                   c.operation, c.object_type, c.object_uid, c.confidence,
                   c.payload_json, c.status AS change_status
            FROM approval_queue a
            JOIN change_request c ON c.id = a.change_request_id
            WHERE a.decision_status = ?
        """
        params: list[Any] = [status]
        if domain:
            sql += " AND a.domain = ?"
            params.append(domain)
        if operation:
            sql += " AND c.operation = ?"
            params.append(operation)
        if object_type:
            sql += " AND c.object_type = ?"
            params.append(object_type)
        sql += " ORDER BY a.created_at ASC LIMIT ?"
        params.append(int(limit))
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for r in rows:
        age = _age_seconds(r["created_at"])
        overdue = _is_overdue(
            age, expires_at=r["expires_at"], overdue_seconds=overdue_seconds
        )
        if overdue_only and not overdue:
            continue
        item: dict[str, Any] = {
            "approval_id": r["approval_id"],
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
            "age_seconds": age,
            "overdue": overdue,
        }
        if include_diff:
            item["diff"] = _build_diff(
                workspace,
                domain=str(r["domain"]),
                object_type=str(r["object_type"] or ""),
                operation=str(r["operation"]),
                object_uid=r["object_uid"],
                payload_json=r["payload_json"],
            )
        out.append(item)
    return out


def _is_overdue(
    age_seconds: float | None, *, expires_at: str | None, overdue_seconds: int
) -> bool:
    if expires_at:
        exp_age = _age_seconds(expires_at)
        if exp_age is not None and exp_age >= 0:
            return True
    return age_seconds is not None and age_seconds >= overdue_seconds


def review_stats(
    workspace: Workspace,
    *,
    domain: str | None = None,
    overdue_seconds: int = DEFAULT_OVERDUE_SECONDS,
) -> dict[str, Any]:
    """SLO counters: pending count, overdue count, oldest pending age."""
    conn = connect_ro(workspace.ledger_db)
    try:
        sql = """
            SELECT a.created_at, a.expires_at, a.domain
            FROM approval_queue a
            WHERE a.decision_status = 'pending'
        """
        params: list[Any] = []
        if domain:
            sql += " AND a.domain = ?"
            params.append(domain)
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    pending = len(rows)
    overdue = 0
    oldest_age: float | None = None
    oldest_at: str | None = None
    by_domain: dict[str, int] = {}
    for r in rows:
        age = _age_seconds(r["created_at"])
        if _is_overdue(age, expires_at=r["expires_at"], overdue_seconds=overdue_seconds):
            overdue += 1
        if age is not None and (oldest_age is None or age > oldest_age):
            oldest_age = age
            oldest_at = r["created_at"]
        dom = str(r["domain"] or "—")
        by_domain[dom] = by_domain.get(dom, 0) + 1
    return {
        "pending": pending,
        "overdue": overdue,
        "oldest_pending_age_seconds": oldest_age,
        "oldest_pending_at": oldest_at,
        "by_domain": by_domain,
        "overdue_seconds": overdue_seconds,
    }


def resolve_bulk(
    executor: CanonicalChangeExecutor,
    approval_ids: list[str],
    *,
    decision: str,
    note: str | None = None,
    resolver: str = "user",
) -> dict[str, Any]:
    """Resolve many approvals with the same decision. Each resolves exactly once."""
    results: list[dict[str, Any]] = []
    applied = 0
    failed = 0
    for approval_id in approval_ids:
        receipt = executor.resolve_approval(
            approval_id, decision=decision, note=note, resolver=resolver
        )
        results.append({"approval_id": approval_id, **receipt.to_dict()})
        if receipt.applied:
            applied += 1
        elif receipt.error:
            failed += 1
    return {
        "count": len(approval_ids),
        "applied": applied,
        "failed": failed,
        "decision": decision,
        "results": results,
    }
