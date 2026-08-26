"""Correction & supersession workflow (plan §8)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from domain_foundry_core.apply.engine import ApplyEngine, OperationSpec
from domain_foundry_core.apply.executor import CanonicalChangeExecutor
from domain_foundry_core.clock import now_iso
from domain_foundry_core.corrections.intent import (
    ParsedCorrection,
    has_correction_intent,
    parse_correction_text,
)
from domain_foundry_core.interpret.fewshot import append_eval_case, rebuild_fewshot_bank
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace
from domain_foundry_core.policy.evaluator import evaluate_policy
from domain_foundry_core.routing.l1 import L1Matcher
from domain_foundry_core.security.store import connect_rw, last_row_id


def _values_match(left: Any, right: Any) -> bool:
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return str(left).strip().lower() == str(right).strip().lower()

_AMEND_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"fields": {"type": "object"}},
    "required": ["fields"],
}

_CONDITION_FIELDS = (
    "condition",
    "grade",
    "status",
    "rating",
    "quality",
    "finish",
)


def _explicit_fields(fields: dict[str, Any] | None) -> dict[str, Any]:
    """Fields the caller/regex parser actually resolved (``_`` keys are hints)."""
    return {k: v for k, v in (fields or {}).items() if not k.startswith("_")}


def _amend_dest_field(field_names: dict[str, Any]) -> str | None:
    for name in _CONDITION_FIELDS:
        if name in field_names:
            return name
    if "notes" in field_names:
        return "notes"
    return None


def _row_mentions_identity(current: dict[str, Any], mention: str) -> bool:
    needle = (mention or "").strip()
    if not needle:
        return False
    for value in current.values():
        if value is None:
            continue
        text = str(value)
        if text.strip().lower() == needle.lower():
            return True
        if re.search(rf"\b{re.escape(needle)}\b", text, re.I):
            return True
    return False


@dataclass
class CorrectionReceipt:
    action: str
    entry_id: str | None
    object_uid: str | None
    correction_event_id: int | None
    change_request_id: int | None
    revision: int | None = None
    eval_case_id: str | None = None
    applied: bool = False
    projection_status: str = "pending"
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "entry_id": self.entry_id,
            "object_uid": self.object_uid,
            "correction_event_id": self.correction_event_id,
            "change_request_id": self.change_request_id,
            "revision": self.revision,
            "eval_case_id": self.eval_case_id,
            "applied": self.applied,
            "projection_status": self.projection_status,
            "details": self.details,
            "error": self.error,
        }


class CorrectionService:
    def __init__(
        self,
        workspace: Workspace,
        *,
        registry: PackRegistry | None = None,
        engine: ApplyEngine | None = None,
        executor: CanonicalChangeExecutor | None = None,
    ) -> None:
        self.ws = workspace
        self.registry = registry or PackRegistry(workspace)
        self.engine = engine or ApplyEngine(workspace, registry=self.registry)
        self.executor = executor or CanonicalChangeExecutor(
            workspace, registry=self.registry, engine=self.engine
        )

    def correct(
        self,
        *,
        text: str | None = None,
        entry_id: str | None = None,
        object_uid: str | None = None,
        action: str | None = None,
        fields: dict[str, Any] | None = None,
        merge_into_uid: str | None = None,
        target_domain: str | None = None,
        channel: str = "cli",
    ) -> CorrectionReceipt:
        parsed: ParsedCorrection | None = None
        if text:
            parsed = parse_correction_text(text)
            action = action or parsed.action
            fields = fields or dict(parsed.fields)
            target_domain = target_domain or parsed.target_domain
        action = action or "amend"
        fields = fields or {}

        target = self._resolve_target(
            entry_id=entry_id, object_uid=object_uid, text=text
        )
        if target is None and action != "mark_wrong":
            return CorrectionReceipt(
                action=action,
                entry_id=entry_id,
                object_uid=object_uid,
                correction_event_id=None,
                change_request_id=None,
                error="could not resolve correction target",
            )

        if action == "amend":
            # The regex parser only knows the vocabulary of the bundled packs
            # (hydration, bulk hours, …). On a generated domain it returns
            # nothing, so ask the model which field the user meant — otherwise a
            # correction on your own domain silently amends nothing.
            fields = self._materialize_amend_fields(target, fields, text)
            if not _explicit_fields(fields) and text:
                fields = {**fields, **self._llm_amend_fields(target, text)}
            return self._amend(
                target=target,  # type: ignore[arg-type]
                fields=fields,
                text=text,
                channel=channel,
                reason_code=(parsed.reason_code if parsed else "amend_fields"),
            )
        if action == "undo":
            return self._undo(target=target, text=text, channel=channel)  # type: ignore[arg-type]
        if action == "move":
            return self._move(
                target=target,  # type: ignore[arg-type]
                target_domain=target_domain,
                text=text,
                channel=channel,
            )
        if action == "merge":
            return self._merge(
                target=target,  # type: ignore[arg-type]
                merge_into_uid=merge_into_uid,
                text=text,
                channel=channel,
            )
        if action == "mark_wrong":
            return self._mark_wrong(
                target=target,
                text=text,
                channel=channel,
            )
        return CorrectionReceipt(
            action=action,
            entry_id=entry_id,
            object_uid=object_uid,
            correction_event_id=None,
            change_request_id=None,
            error=f"unknown action {action!r}",
        )

    def _resolve_target(
        self,
        *,
        entry_id: str | None,
        object_uid: str | None,
        text: str | None,
    ) -> dict[str, Any] | None:
        conn = connect_rw(self.ws.ledger_db)
        try:
            if object_uid:
                row = conn.execute(
                    "SELECT * FROM canonical_object WHERE uid = ?", (object_uid,)
                ).fetchone()
                if not row:
                    return None
                return {
                    "object_uid": row["uid"],
                    "domain": row["domain"],
                    "object_type": row["object_type"],
                    "entry_id": entry_id,
                    "table_name": row["table_name"],
                    "row_id": row["row_id"],
                }

            if entry_id:
                cr = conn.execute(
                    """
                    SELECT object_uid, domain, object_type, id
                    FROM change_request
                    WHERE entry_id = ? AND object_uid IS NOT NULL
                    ORDER BY id DESC LIMIT 1
                    """,
                    (entry_id,),
                ).fetchone()
                if cr and cr["object_uid"]:
                    co = conn.execute(
                        "SELECT * FROM canonical_object WHERE uid = ?",
                        (cr["object_uid"],),
                    ).fetchone()
                    if co:
                        return {
                            "object_uid": co["uid"],
                            "domain": co["domain"],
                            "object_type": co["object_type"],
                            "entry_id": entry_id,
                            "table_name": co["table_name"],
                            "row_id": co["row_id"],
                        }
                # fall through to entry-linked pending create
                pending = conn.execute(
                    """
                    SELECT id, domain, object_type, payload_json, object_uid
                    FROM change_request WHERE entry_id = ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (entry_id,),
                ).fetchone()
                if pending:
                    return {
                        "object_uid": pending["object_uid"],
                        "domain": pending["domain"],
                        "object_type": pending["object_type"],
                        "entry_id": entry_id,
                        "change_request_id": pending["id"],
                        "payload": json.loads(pending["payload_json"] or "{}"),
                    }

            rows = conn.execute(
                """
                SELECT * FROM canonical_object
                WHERE status = 'active'
                ORDER BY updated_at DESC LIMIT 20
                """
            ).fetchall()
            if not rows:
                return None

            def _as_target(row: Any, link_id: str | None) -> dict[str, Any]:
                return {
                    "object_uid": row["uid"],
                    "domain": row["domain"],
                    "object_type": row["object_type"],
                    "entry_id": link_id,
                    "table_name": row["table_name"],
                    "row_id": row["row_id"],
                }

            parsed = parse_correction_text(text) if text else None
            wrong = (parsed.fields or {}).get("_wrong") if parsed else None
            field_keys = [
                key for key in (parsed.fields or {}) if not key.startswith("_")
            ] if parsed else []
            identity_mention = (parsed.fields or {}).get("_identity") if parsed else None
            if identity_mention:
                for row in rows:
                    link = conn.execute(
                        """
                        SELECT source_id FROM source_link
                        WHERE target_type = 'canonical_object' AND target_id = ?
                          AND source_type = 'entry'
                        ORDER BY id DESC LIMIT 1
                        """,
                        (row["uid"],),
                    ).fetchone()
                    candidate = _as_target(row, link["source_id"] if link else None)
                    current = self._current_fields(candidate)
                    if _row_mentions_identity(current, str(identity_mention)):
                        return candidate
            if wrong is not None and field_keys:
                for row in rows:
                    link = conn.execute(
                        """
                        SELECT source_id FROM source_link
                        WHERE target_type = 'canonical_object' AND target_id = ?
                          AND source_type = 'entry'
                        ORDER BY id DESC LIMIT 1
                        """,
                        (row["uid"],),
                    ).fetchone()
                    candidate = _as_target(row, link["source_id"] if link else None)
                    current = self._current_fields(candidate)
                    for field_name in field_keys:
                        value = current.get(field_name)
                        if value is None:
                            continue
                        if _values_match(value, wrong):
                            return candidate

            row = rows[0]
            link = conn.execute(
                """
                SELECT source_id FROM source_link
                WHERE target_type = 'canonical_object' AND target_id = ?
                  AND source_type = 'entry'
                ORDER BY id DESC LIMIT 1
                """,
                (row["uid"],),
            ).fetchone()
            return _as_target(row, link["source_id"] if link else None)
        finally:
            conn.close()

    def _amend(
        self,
        *,
        target: dict[str, Any],
        fields: dict[str, Any],
        text: str | None,
        channel: str,
        reason_code: str,
    ) -> CorrectionReceipt:
        # Map generic _value onto a likely numeric field
        clean = {k: v for k, v in fields.items() if not k.startswith("_")}
        if not clean and "_value" in fields:
            pack = self.registry.get(str(target["domain"]))
            obj = pack.objects.get(str(target["object_type"])) if pack else None
            if obj:
                for fname, fspec in obj.fields.items():
                    if fspec.type in {"number", "integer"}:
                        clean[fname] = fields["_value"]
                        break

        if not target.get("object_uid"):
            return CorrectionReceipt(
                action="amend",
                entry_id=target.get("entry_id"),
                object_uid=None,
                correction_event_id=None,
                change_request_id=None,
                error="amend requires an applied object_uid",
            )

        if not clean:
            # An empty amend used to report applied=true and append an eval case
            # asserting the *unchanged* values were correct — poisoning the very
            # corpus that is supposed to prove the system improves.
            return CorrectionReceipt(
                action="amend",
                entry_id=target.get("entry_id"),
                object_uid=str(target["object_uid"]),
                correction_event_id=None,
                change_request_id=None,
                error=(
                    "could not tell which field to change — say it explicitly, "
                    "e.g. \"rating = medium\""
                ),
            )

        wrong = self._current_fields(target)
        ts = now_iso()
        cr_id = self._insert_change_request(
            entry_id=target.get("entry_id"),
            domain=str(target["domain"]),
            object_type=str(target["object_type"]),
            operation="correct",
            object_uid=str(target["object_uid"]),
            payload={"fields": clean, "span": text or "", "disposition": "auto_apply"},
            channel=channel,
            now=ts,
        )
        receipt = self.executor.execute_change_request(
            cr_id, actor="correction", actor_channel=channel
        )
        ce_id = self._write_correction_event(
            entry_id=target.get("entry_id"),
            target_kind="object",
            target_id=str(target["object_uid"]),
            reason_code=reason_code,
            wrong_json=wrong,
            right_json={**wrong, **clean},
            change_request_id=cr_id if receipt.applied else None,
            now=ts,
        )
        self._supersede_interpretation(target.get("entry_id"), clean, text, now=ts)
        eval_id = None
        if receipt.applied:
            eval_id = append_eval_case(
                self.ws,
                source="correction",
                raw_text=self._original_raw_text(target.get("entry_id")) or (text or ""),
                expected={
                    "captures": [
                        {
                            "domain": target["domain"],
                            "object_type": target["object_type"],
                            "operation": "create",
                            "fields": {**wrong, **clean},
                        }
                    ]
                },
                correction_event_id=ce_id,
            )
            self._demote_rules(str(target["domain"]), text)
            rebuild_fewshot_bank(self.ws)

        return CorrectionReceipt(
            action="amend",
            entry_id=target.get("entry_id"),
            object_uid=str(target["object_uid"]),
            correction_event_id=ce_id,
            change_request_id=cr_id,
            revision=receipt.result.get("revision"),
            eval_case_id=eval_id,
            applied=receipt.applied,
            details={"fields": clean},
            error=receipt.error,
        )

    def _undo(
        self, *, target: dict[str, Any], text: str | None, channel: str
    ) -> CorrectionReceipt:
        if not target.get("object_uid"):
            return CorrectionReceipt(
                action="undo",
                entry_id=target.get("entry_id"),
                object_uid=None,
                correction_event_id=None,
                change_request_id=None,
                error="undo requires object_uid",
            )
        ts = now_iso()
        wrong = self._current_fields(target)
        cr_id = self._insert_change_request(
            entry_id=target.get("entry_id"),
            domain=str(target["domain"]),
            object_type=str(target["object_type"]),
            operation="delete",
            object_uid=str(target["object_uid"]),
            payload={
                "fields": {},
                "span": text or "undo",
                "disposition": "auto_apply",
                "undo": True,
            },
            channel=channel,
            now=ts,
        )
        # delete is review by default — force apply for explicit undo
        receipt = self.engine.apply_spec(
            OperationSpec(
                domain=str(target["domain"]),
                operation="delete",
                object_type=str(target["object_type"]),
                object_uid=str(target["object_uid"]),
                payload={},
                entry_id=target.get("entry_id"),
                channel=channel,
            ),
            change_request_id=cr_id,
            actor="correction",
            actor_channel=channel,
        )
        conn = connect_rw(self.ws.ledger_db)
        try:
            from domain_foundry_core.apply.journal import write_change_request_result

            write_change_request_result(
                conn,
                change_request_id=cr_id,
                object_uid=str(target["object_uid"]),
                result_json={
                    "applied": receipt.ok,
                    "operation": "delete",
                    "undo": True,
                    "object_uid": target["object_uid"],
                },
                error=receipt.error,
                now=ts,
                status="applied" if receipt.ok else "failed",
            )
            conn.commit()
        finally:
            conn.close()

        ce_id = self._write_correction_event(
            entry_id=target.get("entry_id"),
            target_kind="object",
            target_id=str(target["object_uid"]),
            reason_code="undo",
            wrong_json=wrong,
            right_json={"tombstoned": True},
            change_request_id=cr_id if receipt.ok else None,
            now=ts,
        )
        eval_id = None
        if receipt.ok:
            eval_id = append_eval_case(
                self.ws,
                source="correction",
                raw_text=self._original_raw_text(target.get("entry_id")) or (text or ""),
                expected={"captures": [], "undo": True},
                correction_event_id=ce_id,
            )
            rebuild_fewshot_bank(self.ws)

        return CorrectionReceipt(
            action="undo",
            entry_id=target.get("entry_id"),
            object_uid=str(target["object_uid"]),
            correction_event_id=ce_id,
            change_request_id=cr_id,
            revision=receipt.revision,
            eval_case_id=eval_id,
            applied=receipt.ok,
            error=receipt.error,
        )

    def _move(
        self,
        *,
        target: dict[str, Any],
        target_domain: str | None,
        text: str | None,
        channel: str,
    ) -> CorrectionReceipt:
        if not target_domain:
            return CorrectionReceipt(
                action="move",
                entry_id=target.get("entry_id"),
                object_uid=target.get("object_uid"),
                correction_event_id=None,
                change_request_id=None,
                error="move requires target_domain",
            )
        pack = self.registry.get(target_domain)
        if not pack:
            return CorrectionReceipt(
                action="move",
                entry_id=target.get("entry_id"),
                object_uid=target.get("object_uid"),
                correction_event_id=None,
                change_request_id=None,
                error=f"unknown domain {target_domain!r}",
            )
        # Re-route: supersede old interpretation; create new CR in target domain
        ts = now_iso()
        entry_id = target.get("entry_id")
        object_type = next(iter(pack.objects))
        fields = self._current_fields(target) if target.get("object_uid") else {}
        # tombstone old if present
        if target.get("object_uid"):
            self.engine.apply_spec(
                OperationSpec(
                    domain=str(target["domain"]),
                    operation="delete",
                    object_type=str(target["object_type"]),
                    object_uid=str(target["object_uid"]),
                    payload={},
                    entry_id=entry_id,
                ),
                actor="correction_move",
                actor_channel=channel,
            )
        cr_id = self._insert_change_request(
            entry_id=entry_id,
            domain=target_domain,
            object_type=object_type,
            operation="create",
            object_uid=None,
            payload={
                "fields": fields,
                "span": text or "",
                "disposition": "auto_apply",
                "moved_from": target.get("domain"),
            },
            channel=channel,
            now=ts,
        )
        receipt = self.executor.execute_change_request(
            cr_id, actor="correction", actor_channel=channel
        )
        ce_id = self._write_correction_event(
            entry_id=entry_id,
            target_kind="entry" if entry_id else "object",
            target_id=str(entry_id or target.get("object_uid")),
            reason_code="move",
            wrong_json={"domain": target.get("domain")},
            right_json={"domain": target_domain, "object_uid": receipt.object_uid},
            change_request_id=cr_id if receipt.applied else None,
            now=ts,
        )
        self._supersede_interpretation(
            entry_id,
            {"domain": target_domain, "object_type": object_type},
            text,
            now=ts,
        )
        if entry_id:
            conn = connect_rw(self.ws.ledger_db)
            try:
                conn.execute(
                    "UPDATE entry SET domain = ?, object_type = ?, updated_at = ? WHERE id = ?",
                    (target_domain, object_type, ts, entry_id),
                )
                conn.commit()
            finally:
                conn.close()
        eval_id = None
        if receipt.applied:
            eval_id = append_eval_case(
                self.ws,
                source="correction",
                raw_text=self._original_raw_text(entry_id) or (text or ""),
                expected={
                    "captures": [
                        {
                            "domain": target_domain,
                            "object_type": object_type,
                            "operation": "create",
                        }
                    ]
                },
                correction_event_id=ce_id,
            )
            rebuild_fewshot_bank(self.ws)

        return CorrectionReceipt(
            action="move",
            entry_id=entry_id,
            object_uid=receipt.object_uid,
            correction_event_id=ce_id,
            change_request_id=cr_id,
            eval_case_id=eval_id,
            applied=receipt.applied,
            details={"from": target.get("domain"), "to": target_domain},
            error=receipt.error,
        )

    def _merge(
        self,
        *,
        target: dict[str, Any],
        merge_into_uid: str | None,
        text: str | None,
        channel: str,
    ) -> CorrectionReceipt:
        if not target.get("object_uid") or not merge_into_uid:
            # try two most recent active objects of same type
            if not merge_into_uid:
                pair = self._two_recent_same_type(str(target.get("domain") or ""))
                if pair and target.get("object_uid"):
                    merge_into_uid = pair[1] if pair[0] == target["object_uid"] else pair[0]
                elif pair:
                    target["object_uid"] = pair[0]
                    merge_into_uid = pair[1]
            if not target.get("object_uid") or not merge_into_uid:
                return CorrectionReceipt(
                    action="merge",
                    entry_id=target.get("entry_id"),
                    object_uid=target.get("object_uid"),
                    correction_event_id=None,
                    change_request_id=None,
                    error="merge requires object_uid and merge_into_uid",
                )

        ts = now_iso()
        pack = self.registry.get(str(target["domain"]))
        policy = evaluate_policy(
            self.ws.ledger_db,
            domain=str(target["domain"]),
            operation="merge",
            object_type=str(target["object_type"]),
            channel=channel,
            confidence=1.0,
            pack=pack,
        )
        disposition = policy.action
        cr_id = self._insert_change_request(
            entry_id=target.get("entry_id"),
            domain=str(target["domain"]),
            object_type=str(target["object_type"]),
            operation="merge",
            object_uid=str(target["object_uid"]),
            payload={
                "fields": {},
                "merge_into_uid": merge_into_uid,
                "span": text or "",
                "disposition": disposition,
            },
            channel=channel,
            now=ts,
        )
        if disposition in {"review", "confirm"}:
            from domain_foundry_core.apply.pipeline import ApplyPipeline

            approval_id = ApplyPipeline(
                self.ws, registry=self.registry, executor=self.executor
            )._ensure_approval(cr_id, domain=str(target["domain"]))
            ce_id = self._write_correction_event(
                entry_id=target.get("entry_id"),
                target_kind="object",
                target_id=str(target["object_uid"]),
                reason_code="merge",
                wrong_json={"uids": [target["object_uid"], merge_into_uid]},
                right_json={"survivor": merge_into_uid},
                change_request_id=None,
                now=ts,
            )
            return CorrectionReceipt(
                action="merge",
                entry_id=target.get("entry_id"),
                object_uid=merge_into_uid,
                correction_event_id=ce_id,
                change_request_id=cr_id,
                applied=False,
                details={
                    "approval_id": approval_id,
                    "survivor_uid": merge_into_uid,
                    "policy": disposition,
                },
            )

        result = self.engine.apply_spec(
            OperationSpec(
                domain=str(target["domain"]),
                operation="merge",
                object_type=str(target["object_type"]),
                object_uid=str(target["object_uid"]),
                merge_into_uid=merge_into_uid,
                payload={},
                entry_id=target.get("entry_id"),
            ),
            change_request_id=cr_id,
            actor="correction",
            actor_channel=channel,
        )
        conn = connect_rw(self.ws.ledger_db)
        try:
            from domain_foundry_core.apply.journal import write_change_request_result

            write_change_request_result(
                conn,
                change_request_id=cr_id,
                object_uid=merge_into_uid,
                result_json={
                    "applied": result.ok,
                    "operation": "merge",
                    "merged_uid": target["object_uid"],
                    "survivor_uid": merge_into_uid,
                    "details": result.details,
                },
                error=result.error,
                now=ts,
                status="applied" if result.ok else "failed",
            )
            conn.commit()
        finally:
            conn.close()

        ce_id = self._write_correction_event(
            entry_id=target.get("entry_id"),
            target_kind="object",
            target_id=str(target["object_uid"]),
            reason_code="merge",
            wrong_json={"uids": [target["object_uid"], merge_into_uid]},
            right_json={"survivor": merge_into_uid},
            change_request_id=cr_id if result.ok else None,
            now=ts,
        )

        # FK gate: no orphan merged rows without survivor link
        if result.ok:
            conn = connect_rw(self.ws.ledger_db)
            try:
                orphans = conn.execute(
                    """
                    SELECT uid FROM canonical_object
                    WHERE status = 'merged' AND merged_into_uid IS NULL
                    """
                ).fetchall()
                if orphans:
                    return CorrectionReceipt(
                        action="merge",
                        entry_id=target.get("entry_id"),
                        object_uid=merge_into_uid,
                        correction_event_id=ce_id,
                        change_request_id=cr_id,
                        applied=False,
                        error="merge left orphaned canonical records",
                    )
            finally:
                conn.close()
            rebuild_fewshot_bank(self.ws)

        return CorrectionReceipt(
            action="merge",
            entry_id=target.get("entry_id"),
            object_uid=merge_into_uid,
            correction_event_id=ce_id,
            change_request_id=cr_id,
            revision=result.revision,
            applied=result.ok,
            details=result.details,
            error=result.error,
        )

    def _mark_wrong(
        self,
        *,
        target: dict[str, Any] | None,
        text: str | None,
        channel: str,
    ) -> CorrectionReceipt:
        ts = now_iso()
        wrong = self._current_fields(target) if target else {"text": text}
        ce_id = self._write_correction_event(
            entry_id=target.get("entry_id") if target else None,
            target_kind="entry" if target and target.get("entry_id") else "object",
            target_id=str(
                (target or {}).get("entry_id")
                or (target or {}).get("object_uid")
                or "unknown"
            ),
            reason_code="mark_wrong",
            wrong_json=wrong,
            right_json=None,
            change_request_id=None,
            now=ts,
        )
        eval_id = append_eval_case(
            self.ws,
            source="correction",
            raw_text=self._original_raw_text((target or {}).get("entry_id"))
            or (text or ""),
            expected={"captures": [], "known_bad": True},
            correction_event_id=ce_id,
        )
        rebuild_fewshot_bank(self.ws)
        return CorrectionReceipt(
            action="mark_wrong",
            entry_id=(target or {}).get("entry_id"),
            object_uid=(target or {}).get("object_uid"),
            correction_event_id=ce_id,
            change_request_id=None,
            eval_case_id=eval_id,
            applied=True,
        )

    def _llm_amend_fields(
        self, target: dict[str, Any] | None, text: str
    ) -> dict[str, Any]:
        """Ask the configured model which field(s) the correction refers to.

        Returns ``{}`` when there is no live model or the answer is unusable —
        the caller then reports "could not tell which field" rather than
        pretending to have corrected something.
        """
        if not target or not target.get("object_uid"):
            return {}
        pack = self.registry.get(str(target["domain"]))
        obj = pack.objects.get(str(target["object_type"])) if pack else None
        if obj is None:
            return {}

        from domain_foundry_core.llm.provider import (
            get_default_provider,
            is_heuristic_provider,
        )

        llm = get_default_provider(
            cassette_dir=self.ws.home / "cassettes", home=self.ws.home
        )
        if is_heuristic_provider(llm):
            return {}

        current = self._current_fields(target)
        schema = {
            name: {"type": spec.type, "values": list(spec.values or [])}
            for name, spec in obj.fields.items()
        }
        try:
            result = llm.complete_json(
                system=(
                    "You apply a user's one-message correction to a stored record. "
                    "Return JSON {\"fields\": {...}} containing ONLY the fields that "
                    "must change, using the record's own field names and types. "
                    "Return an empty object if the correction is not about a field value."
                ),
                user=json.dumps(
                    {
                        "correction": text,
                        "record": current,
                        "schema": schema,
                    },
                    ensure_ascii=False,
                ),
                schema=_AMEND_SCHEMA,
                tier="sota",
            )
        except Exception:
            return {}

        proposed = result.data.get("fields")
        if not isinstance(proposed, dict):
            return {}
        # Only accept real fields whose value actually differs.
        return {
            k: v
            for k, v in proposed.items()
            if k in obj.fields and v is not None and current.get(k) != v
        }

    def _current_fields(self, target: dict[str, Any] | None) -> dict[str, Any]:
        if not target or not target.get("object_uid"):
            return {}
        from domain_foundry_core.apply.engine import load_domain_row

        row = load_domain_row(
            self.ws.domains_db,
            str(target["domain"]),
            str(target["object_type"]),
            str(target["object_uid"]),
        )
        if not row:
            return {}
        skip = {"id", "object_uid", "entry_id", "created_at", "updated_at", "tombstoned"}
        return {k: v for k, v in row.items() if k not in skip and v is not None}

    def _materialize_amend_fields(
        self,
        target: dict[str, Any] | None,
        fields: dict[str, Any] | None,
        text: str | None,
    ) -> dict[str, Any]:
        """Map free-text patches onto *existing* schema fields.

        A proper noun like Charizard is an identity value, never a new field.
        Bind the new value to notes or a condition-like field on that row.
        """
        fields = dict(fields or {})
        if not target or not target.get("domain"):
            return {k: v for k, v in fields.items() if not k.startswith("_")}
        pack = self.registry.get(str(target["domain"]))
        obj = pack.objects.get(str(target["object_type"])) if pack else None
        if obj is None:
            return {k: v for k, v in fields.items() if not k.startswith("_")}

        known = {k: v for k, v in fields.items() if k in obj.fields}
        if known:
            return known

        mention = fields.get("_identity")
        value = fields.get("_value")
        for key, raw in fields.items():
            if key.startswith("_"):
                continue
            mention = mention or key
            if value is None:
                value = raw
        if mention is None and text:
            parsed = parse_correction_text(text)
            mention = parsed.fields.get("_identity")
            if value is None:
                value = parsed.fields.get("_value")
        if value is None:
            return {}
        dest = _amend_dest_field(obj.fields)
        if dest is None:
            return {}
        if dest == "notes":
            current = self._current_fields(target)
            existing = current.get("notes")
            wrong = fields.get("_wrong")
            if existing and wrong and str(wrong) in str(existing):
                return {dest: str(existing).replace(str(wrong), str(value), 1)}
        return {dest: value}

    def _insert_change_request(
        self,
        *,
        entry_id: str | None,
        domain: str,
        object_type: str,
        operation: str,
        object_uid: str | None,
        payload: dict[str, Any],
        channel: str,
        now: str,
    ) -> int:
        # ensure entry exists for FK — create ledger-only correction entry if needed
        conn = connect_rw(self.ws.ledger_db)
        try:
            if not entry_id:
                from domain_foundry_core.ids import new_ulid

                eid = new_ulid()
                ceid = new_ulid()
                conn.execute(
                    """
                    INSERT INTO capture_event (
                        id, channel, source_ref, actor, raw_text, raw_payload_json,
                        attachments_json, content_hash, captured_at, created_at
                    ) VALUES (?, ?, ?, NULL, ?, NULL, NULL, NULL, ?, ?)
                    """,
                    (ceid, channel, f"correction:{eid}", payload.get("span") or "", now, now),
                )
                conn.execute(
                    """
                    INSERT INTO entry (
                        id, capture_event_id, status, domain, object_type, operation,
                        summary, privacy_level, created_at, updated_at
                    ) VALUES (?, ?, 'applied', ?, ?, ?, ?, 'normal', ?, ?)
                    """,
                    (
                        eid,
                        ceid,
                        domain,
                        object_type,
                        operation,
                        (payload.get("span") or "correction")[:120],
                        now,
                        now,
                    ),
                )
                entry_id = eid

            cur = conn.execute(
                """
                INSERT INTO change_request (
                    entry_id, interpretation_id, domain, object_type, operation,
                    object_uid, payload_json, confidence, channel, status, created_at
                ) VALUES (?, NULL, ?, ?, ?, ?, ?, 1.0, ?, 'pending', ?)
                """,
                (
                    entry_id,
                    domain,
                    object_type,
                    operation,
                    object_uid,
                    json.dumps(payload, separators=(",", ":")),
                    channel,
                    now,
                ),
            )
            conn.commit()
            return last_row_id(cur)
        finally:
            conn.close()

    def _write_correction_event(
        self,
        *,
        entry_id: str | None,
        target_kind: str,
        target_id: str,
        reason_code: str,
        wrong_json: dict[str, Any] | None,
        right_json: dict[str, Any] | None,
        change_request_id: int | None,
        now: str,
    ) -> int:
        conn = connect_rw(self.ws.ledger_db)
        try:
            cur = conn.execute(
                """
                INSERT INTO correction_event (
                    entry_id, target_kind, target_id, reason_code,
                    wrong_json, right_json, applied_change_request_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    target_kind,
                    target_id,
                    reason_code,
                    json.dumps(wrong_json, sort_keys=True) if wrong_json is not None else None,
                    json.dumps(right_json, sort_keys=True) if right_json is not None else None,
                    change_request_id,
                    now,
                ),
            )
            conn.commit()
            return last_row_id(cur)
        finally:
            conn.close()

    def _supersede_interpretation(
        self,
        entry_id: str | None,
        right: dict[str, Any],
        text: str | None,
        *,
        now: str,
    ) -> None:
        if not entry_id:
            return
        conn = connect_rw(self.ws.ledger_db)
        try:
            prev = conn.execute(
                """
                SELECT id, version FROM interpretation
                WHERE entry_id = ? ORDER BY version DESC LIMIT 1
                """,
                (entry_id,),
            ).fetchone()
            next_ver = int(prev["version"]) + 1 if prev else 1
            cur = conn.execute(
                """
                INSERT INTO interpretation (
                    entry_id, version, interpreter, payload_json, confidence,
                    status, created_at
                ) VALUES (?, ?, 'correction', ?, 1.0, 'applied', ?)
                """,
                (
                    entry_id,
                    next_ver,
                    json.dumps({"correction": True, "right": right, "text": text}),
                    now,
                ),
            )
            new_id = last_row_id(cur)
            if prev:
                conn.execute(
                    """
                    UPDATE interpretation
                    SET status = 'superseded', superseded_by = ?
                    WHERE id = ?
                    """,
                    (new_id, prev["id"]),
                )
            conn.commit()
        finally:
            conn.close()

    def _original_raw_text(self, entry_id: str | None) -> str | None:
        if not entry_id:
            return None
        conn = connect_rw(self.ws.ledger_db)
        try:
            row = conn.execute(
                """
                SELECT c.raw_text FROM entry e
                JOIN capture_event c ON c.id = e.capture_event_id
                WHERE e.id = ?
                """,
                (entry_id,),
            ).fetchone()
            return str(row["raw_text"]) if row and row["raw_text"] else None
        finally:
            conn.close()

    def _demote_rules(self, domain: str, text: str | None) -> None:
        """Cap confidence on L1 rules implicated by repeated corrections."""
        packs = self.registry.list()
        pack = self.registry.get(domain)
        if not pack or not text:
            return
        l1 = L1Matcher(packs).match(text)
        ts = now_iso()
        conn = connect_rw(self.ws.ledger_db)
        try:
            for hit in l1.hits:
                if hit.pack != domain:
                    continue
                rule = pack.routing.rules[hit.rule_index]
                conn.execute(
                    """
                    INSERT INTO rule_demotion (
                        pack, rule_index, pattern, demotion_count, confidence_cap, updated_at
                    ) VALUES (?, ?, ?, 1, 0.5, ?)
                    ON CONFLICT(pack, rule_index) DO UPDATE SET
                        demotion_count = demotion_count + 1,
                        confidence_cap = CASE
                            WHEN demotion_count + 1 >= 3 THEN 0.3
                            ELSE 0.5
                        END,
                        updated_at = excluded.updated_at
                    """,
                    (domain, hit.rule_index, rule.match, ts),
                )
            conn.commit()
        finally:
            conn.close()

    def _two_recent_same_type(self, domain: str) -> tuple[str, str] | None:
        conn = connect_rw(self.ws.ledger_db)
        try:
            rows = conn.execute(
                """
                SELECT uid FROM canonical_object
                WHERE domain = ? AND status = 'active'
                ORDER BY updated_at DESC LIMIT 2
                """,
                (domain,),
            ).fetchall()
            if len(rows) < 2:
                return None
            return str(rows[0]["uid"]), str(rows[1]["uid"])
        finally:
            conn.close()


__all__ = ["CorrectionService", "CorrectionReceipt", "has_correction_intent"]
