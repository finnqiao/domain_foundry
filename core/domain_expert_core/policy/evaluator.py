"""Apply-policy evaluation against seeded pack rows + user overrides."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from domain_expert_core.packs.models import DomainPack
from domain_expert_core.security.store import connect_ro, connect_rw

PolicyAction = str  # auto_apply | review | confirm | reject


@dataclass(frozen=True)
class PolicyDecision:
    action: PolicyAction
    matched_rule_id: int | None = None
    source: str | None = None
    reason: str = ""


def evaluate_policy(
    ledger_db: Path,
    *,
    domain: str,
    operation: str,
    object_type: str,
    channel: str,
    confidence: float,
    pack: DomainPack | None = None,
) -> PolicyDecision:
    """Return the winning policy action for an operation.

    User overrides (source=user) beat pack rows. More-specific matches win when
    priority is equal. Below min_confidence ⇒ review.
    """
    if operation == "delete" and pack is None:
        # safe default if DB empty
        pass

    rows = _load_rows(ledger_db, domain)
    if not rows and pack is not None:
        return _evaluate_pack_defaults(pack, operation, object_type, channel, confidence)

    candidates = [r for r in rows if _matches(r, operation, object_type, channel)]
    if not candidates:
        if pack is not None:
            return _evaluate_pack_defaults(pack, operation, object_type, channel, confidence)
        return PolicyDecision(action="review", reason="no_matching_policy")

    # user source first, then lower priority number, then specificity
    candidates.sort(
        key=lambda r: (
            0 if r["source"] == "user" else 1,
            int(r["priority"]),
            -_specificity(r),
        )
    )
    winner = candidates[0]
    min_conf = float(winner["min_confidence"] if winner["min_confidence"] is not None else 0.0)
    if confidence < min_conf:
        return PolicyDecision(
            action="review",
            matched_rule_id=int(winner["id"]),
            source=str(winner["source"]),
            reason=f"confidence {confidence:.2f} < min {min_conf:.2f}",
        )
    return PolicyDecision(
        action=str(winner["action"]),
        matched_rule_id=int(winner["id"]),
        source=str(winner["source"]),
        reason="matched",
    )


def seed_user_override(
    ledger_db: Path,
    *,
    domain: str,
    operation: str = "*",
    object_type: str = "*",
    channel: str = "*",
    min_confidence: float = 0.0,
    action: PolicyAction = "review",
    priority: int = 10,
) -> None:
    conn = connect_rw(ledger_db)
    try:
        conn.execute(
            """
            INSERT INTO apply_policy (
                domain, operation, object_type, channel, min_confidence,
                condition_json, action, priority, source
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, 'user')
            ON CONFLICT(domain, operation, object_type, channel, source) DO UPDATE SET
                min_confidence = excluded.min_confidence,
                action = excluded.action,
                priority = excluded.priority
            """,
            (domain, operation, object_type, channel, min_confidence, action, priority),
        )
        conn.commit()
    finally:
        conn.close()


def _load_rows(ledger_db: Path, domain: str) -> list[dict[str, Any]]:
    if not ledger_db.exists():
        return []
    conn = connect_ro(ledger_db)
    try:
        rows = conn.execute(
            "SELECT * FROM apply_policy WHERE domain = ? OR domain = '*'",
            (domain,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def _matches(row: dict[str, Any], operation: str, object_type: str, channel: str) -> bool:
    op = str(row.get("operation") or "*")
    ot = str(row.get("object_type") or "*")
    ch = str(row.get("channel") or "*")
    if op not in {"*", operation}:
        return False
    if ot not in {"*", object_type}:
        return False
    if ch not in {"*", channel}:
        return False
    return True


def _specificity(row: dict[str, Any]) -> int:
    score = 0
    if str(row.get("operation") or "*") != "*":
        score += 4
    if str(row.get("object_type") or "*") != "*":
        score += 2
    if str(row.get("channel") or "*") != "*":
        score += 1
    return score


def _evaluate_pack_defaults(
    pack: DomainPack,
    operation: str,
    object_type: str,
    channel: str,
    confidence: float,
) -> PolicyDecision:
    action = "auto_apply"
    for row in pack.policy.defaults:
        if row.operation and row.operation not in {"*", operation}:
            continue
        if row.object_type and row.object_type not in {"*", object_type}:
            continue
        ch = None
        if row.channel:
            ch = row.channel
        elif row.match and row.match.get("channel"):
            ch = str(row.match["channel"])
        if ch and ch != channel:
            continue
        if row.min_confidence is not None and confidence < row.min_confidence:
            return PolicyDecision(action="review", reason="pack_min_confidence")
        action = row.action
    if operation == "delete":
        return PolicyDecision(action="review", reason="delete_default")
    return PolicyDecision(action=action, source="pack", reason="pack_defaults")
