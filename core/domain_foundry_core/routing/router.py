"""Two-layer router with multi-domain fan-out and never-drop ladder."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from domain_foundry_core.clock import now_iso
from domain_foundry_core.interpret.fewshot import load_fewshot_bank
from domain_foundry_core.llm.pricing import estimate_cost_usd
from domain_foundry_core.llm.provider import (
    HeuristicProvider,
    LLMProvider,
    TokenUsage,
    get_default_provider,
    is_heuristic_provider,
    select_model_tier,
)
from domain_foundry_core.packs.models import DomainPack
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace
from domain_foundry_core.policy.evaluator import evaluate_policy
from domain_foundry_core.routing.cost import CostGuard, CostGuardConfig
from domain_foundry_core.routing.l1 import L1Matcher, L1Result
from domain_foundry_core.security.store import connect_rw

ROUTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "captures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string"},
                    "object_type": {"type": "string"},
                    "operation": {"type": "string"},
                    "span": {"type": "string"},
                    "confidence": {"type": "number"},
                    "fields": {"type": "object"},
                    "links": {"type": "array"},
                },
                "required": ["domain", "object_type", "operation"],
            },
        },
        "unmatched_text": {},
        "needs_clarification": {"type": "boolean"},
        "clarifying_question": {},
    },
    "required": ["captures"],
}


@dataclass
class CaptureSpan:
    domain: str
    object_type: str
    operation: str
    span: str
    confidence: float
    fields: dict[str, Any] = field(default_factory=dict)
    links: list[dict[str, Any]] = field(default_factory=list)
    disposition: str = "auto_apply"  # auto_apply | review | unfiled | ledger_only


@dataclass
class RouteResult:
    entry_id: str
    spans: list[CaptureSpan]
    status: str
    fallback_tier: str | None
    interpreter: str
    cost_usd: float = 0.0
    l1: L1Result | None = None
    clarification: str | None = None
    model_tier: str | None = None
    usage: TokenUsage | None = None


class Router:
    def __init__(
        self,
        workspace: Workspace | None = None,
        *,
        registry: PackRegistry | None = None,
        llm: LLMProvider | None = None,
        cost_cap: float = 0.25,
    ) -> None:
        self.ws = workspace or Workspace()
        self.registry = registry or PackRegistry(self.ws)
        self.cost = CostGuard(
            self.ws.ledger_db, CostGuardConfig.from_env(daily_usd_cap=cost_cap)
        )
        cassette_dir = self.ws.home / "cassettes"
        self.llm = llm or get_default_provider(cassette_dir=cassette_dir)
        self.heuristic = HeuristicProvider()

    def route_text(self, text: str, *, channel: str = "cli") -> RouteResult:
        """Route without persisting — used by eval runner."""
        packs = self.registry.list()
        l1 = L1Matcher(packs).match(text)
        spans, interpreter, cost, clarification, model_tier, usage = self._interpret(
            text, channel=channel, l1=l1, packs=packs, entry_id=None
        )
        status, tier = self._finalize_status(spans, clarification)
        return RouteResult(
            entry_id="",
            spans=spans,
            status=status,
            fallback_tier=tier,
            interpreter=interpreter,
            cost_usd=cost,
            l1=l1,
            clarification=clarification,
            model_tier=model_tier,
            usage=usage,
        )

    def route_entry(self, entry_id: str, text: str, *, channel: str = "cli") -> RouteResult:
        packs = self.registry.list()
        l1 = L1Matcher(packs, demotions=self._load_demotions()).match(text)
        spans, interpreter, cost, clarification, model_tier, usage = self._interpret(
            text, channel=channel, l1=l1, packs=packs, entry_id=entry_id
        )
        status, tier = self._finalize_status(spans, clarification)
        self._persist(entry_id, text, spans, status, tier, interpreter, clarification)
        if cost > 0 and usage is not None:
            self.cost.record(
                provider=usage.provider or getattr(self.llm, "name", "llm"),
                model=usage.model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cost_usd=cost,
                entry_id=entry_id,
                tier=usage.tier or model_tier,
            )
        elif cost > 0:
            self.cost.record(
                provider=getattr(self.llm, "name", "llm"),
                model=None,
                input_tokens=0,
                output_tokens=0,
                cost_usd=cost,
                entry_id=entry_id,
                tier=model_tier,
            )
        return RouteResult(
            entry_id=entry_id,
            spans=spans,
            status=status,
            fallback_tier=tier,
            interpreter=interpreter,
            cost_usd=cost,
            l1=l1,
            clarification=clarification,
            model_tier=model_tier,
            usage=usage,
        )

    def _interpret(
        self,
        text: str,
        *,
        channel: str,
        l1: L1Result,
        packs: list[DomainPack],
        entry_id: str | None,
    ) -> tuple[list[CaptureSpan], str, float, str | None, str | None, TokenUsage | None]:
        if not packs:
            return [], "none", 0.0, None, None, None

        if not l1.escalate and l1.hits:
            # Prefer highest-boost hit (e.g. plant acquisition over plant-name mention)
            hit = max(l1.hits, key=lambda h: (h.boost, h.rule_index))
            pack = next(p for p in packs if p.name == hit.pack)
            fields = self._l1_fields(text, pack, hit.object_type)
            if pack.name == "food":
                from domain_foundry_core.geo.capture_hints import enrich_venue_fields

                fields = enrich_venue_fields(
                    object_type=hit.object_type, fields=fields, raw_text=text
                )
            span = CaptureSpan(
                domain=hit.pack,
                object_type=hit.object_type,
                operation=hit.operation,
                span=text,
                confidence=l1.confidence,
                fields=fields,
            )
            span.disposition = self._policy_action(pack, span, channel)
            return [span], "rules", 0.0, None, None, None

        # L2
        ctx = self._build_context(text, packs, l1)
        user = "Route this capture.\nCONTEXT_JSON:\n" + json.dumps(ctx, ensure_ascii=False)
        system = (
            "You are the domain_foundry router. Return JSON with captures[], "
            "unmatched_text, needs_clarification, clarifying_question. "
            "Fan out multi-domain messages into separate captures with links."
        )

        model_tier = self._select_tier(text, l1, packs)
        use_llm = (
            self.cost.allow_llm(tier=model_tier) and not is_heuristic_provider(self.llm)
        )
        # Prefer configured provider; fall back to heuristic on failure / cost guard
        interpreter = "heuristic"
        cost = 0.0
        usage: TokenUsage | None = None
        raw: dict[str, Any]
        if use_llm:
            try:
                result = self.llm.complete_json(
                    system=system,
                    user=user,
                    schema=ROUTE_SCHEMA,
                    tier=model_tier,
                )
                raw = result.data
                usage = result.usage
                usage.tier = usage.tier or model_tier
                interpreter = getattr(self.llm, "name", "llm")
                cost = estimate_cost_usd(
                    model=usage.model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                )
            except Exception:
                raw = self.heuristic.complete_json(
                    system=system, user=user, tier=model_tier
                ).data
                interpreter = "heuristic_fallback"
                usage = None
                cost = 0.0
        else:
            # cost guard or heuristic mode
            if not self.cost.allow_llm(tier=model_tier) and not is_heuristic_provider(
                self.llm
            ):
                interpreter = "rules_only_cost_guard"
            raw = self.heuristic.complete_json(
                system=system, user=user, tier=model_tier
            ).data

        spans: list[CaptureSpan] = []
        for c in raw.get("captures") or []:
            domain = c.get("domain")
            pack = next((p for p in packs if p.name == domain), None)
            if not pack:
                # try alias
                pack = self.registry.get_by_alias(str(domain or ""))
            if not pack:
                continue
            object_type = str(c.get("object_type") or next(iter(pack.objects), "note"))
            fields = dict(c.get("fields") or {})
            if pack.name == "food":
                from domain_foundry_core.geo.capture_hints import enrich_venue_fields

                fields = enrich_venue_fields(
                    object_type=object_type, fields=fields, raw_text=text
                )
            span = CaptureSpan(
                domain=pack.name,
                object_type=object_type,
                operation=str(c.get("operation") or "create"),
                span=str(c.get("span") or text),
                confidence=float(c.get("confidence") or 0.7),
                fields=fields,
                links=list(c.get("links") or []),
            )
            span.disposition = self._policy_action(pack, span, channel)
            spans.append(span)

        clarification = None
        if raw.get("needs_clarification") and raw.get("clarifying_question"):
            clarification = str(raw["clarifying_question"])

        unmatched = raw.get("unmatched_text")
        if unmatched and not spans:
            # never-drop ladder
            tier_spans = self._never_drop(str(unmatched), packs)
            spans.extend(tier_spans)

        if not spans:
            spans = self._never_drop(text, packs)

        return spans, interpreter, cost, clarification, model_tier, usage

    def _select_tier(self, text: str, l1: L1Result, packs: list[DomainPack]) -> str:
        rule_tiers: list[str | None] = []
        structural = False
        pack_by_name = {p.name: p for p in packs}
        for hit in l1.hits:
            pack = pack_by_name.get(hit.pack)
            if not pack:
                continue
            if hit.rule_index < len(pack.routing.rules):
                rule = pack.routing.rules[hit.rule_index]
                rule_tiers.append(rule.tier)
                if rule.operation in {"update", "delete", "merge", "correct"}:
                    structural = True
            if hit.operation in {"update", "delete", "merge", "correct"}:
                structural = True
        return select_model_tier(
            l1_confidence=l1.confidence,
            l1_reason=l1.reason,
            text=text,
            rule_tiers=rule_tiers,
            structural=structural,
        )

    def _never_drop(self, text: str, packs: list[DomainPack]) -> list[CaptureSpan]:
        # 1) pack-declared fallback via unfiled if any pack has fallback unfiled_card
        if packs:
            return [
                CaptureSpan(
                    domain="_unfiled",
                    object_type="card",
                    operation="create",
                    span=text,
                    confidence=0.2,
                    fields={"title": text[:80], "data": {"raw": text}},
                    disposition="unfiled",
                )
            ]
        return [
            CaptureSpan(
                domain="_ledger",
                object_type="entry",
                operation="create",
                span=text,
                confidence=0.1,
                fields={},
                disposition="ledger_only",
            )
        ]

    def _finalize_status(
        self, spans: list[CaptureSpan], clarification: str | None
    ) -> tuple[str, str | None]:
        if clarification:
            return "review", None
        if not spans:
            return "ledger_only", "ledger_only"
        if any(s.disposition == "unfiled" for s in spans):
            return "unfiled", "unfiled_card"
        if any(s.disposition == "ledger_only" for s in spans):
            return "ledger_only", "ledger_only"
        if any(s.disposition in {"review", "confirm"} for s in spans):
            return "review", None
        if spans and all(s.disposition == "auto_apply" for s in spans):
            # Pipeline will confirm applied after CanonicalChangeExecutor runs
            return "applied", None
        return "review", None

    def _policy_action(self, pack: DomainPack, span: CaptureSpan, channel: str) -> str:
        decision = evaluate_policy(
            self.ws.ledger_db,
            domain=pack.name,
            operation=span.operation,
            object_type=span.object_type,
            channel=channel,
            confidence=span.confidence,
            pack=pack,
        )
        return decision.action

    def _build_context(self, text: str, packs: list[DomainPack], l1: L1Result) -> dict[str, Any]:
        shortlisted = set(l1.packs_matched) or {p.name for p in packs}
        pack_payloads = []
        for pack in packs:
            objects = {}
            for oname, obj in pack.objects.items():
                objects[oname] = {
                    "fields": {k: v.model_dump(exclude_none=True) for k, v in obj.fields.items()}
                }
            pack_payloads.append(
                {
                    "name": pack.name,
                    "description": pack.manifest.description,
                    "interpretation": pack.manifest.interpretation,
                    "rules": [r.model_dump() for r in pack.routing.rules],
                    "examples": [e.text for e in pack.routing.examples[:3]],
                    "objects": objects if pack.name in shortlisted else {},
                    "llm_hints": pack.routing.llm_hints,
                }
            )
        fewshot = load_fewshot_bank(self.ws)
        return {
            "text": text,
            "packs": pack_payloads,
            "l1_hits": [
                {
                    "pack": h.pack,
                    "object_type": h.object_type,
                    "operation": h.operation,
                    "rule_index": h.rule_index,
                }
                for h in l1.hits
            ],
            "l1_confidence": l1.confidence,
            "l1_reason": l1.reason,
            "fewshot": fewshot.get("examples") or [],
        }

    def _l1_fields(self, text: str, pack: DomainPack, object_type: str) -> dict[str, Any]:
        # Reuse heuristic field extraction
        from domain_foundry_core.llm.provider import _extract_fields

        objects = {
            oname: {"fields": {k: v.model_dump(exclude_none=True) for k, v in obj.fields.items()}}
            for oname, obj in pack.objects.items()
        }
        return _extract_fields(text, {"objects": objects}, object_type)

    def _load_demotions(self) -> dict[tuple[str, int], float]:
        if not self.ws.ledger_db.exists():
            return {}
        conn = connect_rw(self.ws.ledger_db)
        try:
            rows = conn.execute(
                "SELECT pack, rule_index, confidence_cap FROM rule_demotion "
                "WHERE confidence_cap IS NOT NULL"
            ).fetchall()
            return {(r["pack"], int(r["rule_index"])): float(r["confidence_cap"]) for r in rows}
        except Exception:
            return {}
        finally:
            conn.close()

    def _persist(
        self,
        entry_id: str,
        text: str,
        spans: list[CaptureSpan],
        status: str,
        tier: str | None,
        interpreter: str,
        clarification: str | None,
    ) -> None:
        from domain_foundry_core.ids import new_ulid

        ts = now_iso()
        conn = connect_rw(self.ws.ledger_db)
        try:
            primary = next((s for s in spans if s.domain not in {"_unfiled", "_ledger"}), None)
            conf = primary.confidence if primary else (spans[0].confidence if spans else None)
            conn.execute(
                """
                UPDATE entry SET
                    status = ?, domain = ?, object_type = ?, operation = ?,
                    routing_confidence = ?, fallback_tier = ?, updated_at = ?,
                    summary = COALESCE(summary, ?)
                WHERE id = ?
                """,
                (
                    status,
                    primary.domain if primary else None,
                    primary.object_type if primary else None,
                    primary.operation if primary else None,
                    conf,
                    tier,
                    ts,
                    (primary.span if primary else text)[:120],
                    entry_id,
                ),
            )

            payload = {
                "captures": [
                    {
                        "domain": s.domain,
                        "object_type": s.object_type,
                        "operation": s.operation,
                        "span": s.span,
                        "confidence": s.confidence,
                        "fields": s.fields,
                        "links": s.links,
                        "disposition": s.disposition,
                    }
                    for s in spans
                ],
                "clarification": clarification,
            }
            cur = conn.execute(
                """
                INSERT INTO interpretation (
                    entry_id, version, interpreter, payload_json, confidence,
                    status, created_at
                ) VALUES (?, 1, ?, ?, ?, 'proposed', ?)
                """,
                (
                    entry_id,
                    interpreter,
                    json.dumps(payload, separators=(",", ":")),
                    conf or 0.0,
                    ts,
                ),
            )
            interp_id = int(cur.lastrowid)

            span_cr: list[tuple[CaptureSpan, int]] = []
            for s in spans:
                if s.domain in {"_unfiled", "_ledger"}:
                    continue
                cur = conn.execute(
                    """
                    INSERT INTO change_request (
                        entry_id, interpretation_id, domain, object_type, operation,
                        payload_json, confidence, channel, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        entry_id,
                        interp_id,
                        s.domain,
                        s.object_type,
                        s.operation,
                        json.dumps(
                            {
                                "fields": s.fields,
                                "span": s.span,
                                "disposition": s.disposition,
                                "links": s.links,
                            },
                            separators=(",", ":"),
                        ),
                        s.confidence,
                        None,
                        ts,
                    ),
                )
                cr_id = int(cur.lastrowid)
                span_cr.append((s, cr_id))
                # auto_apply is executed by ApplyPipeline; only review/confirm enqueue
                if s.disposition in {"review", "confirm"}:
                    conn.execute(
                        """
                        INSERT INTO approval_queue (
                            id, change_request_id, decision_status, application_status,
                            domain, summary, diff_json, created_at
                        ) VALUES (?, ?, 'pending', 'not_started', ?, ?, ?, ?)
                        """,
                        (
                            new_ulid(),
                            cr_id,
                            s.domain,
                            s.span[:200],
                            json.dumps({"fields": s.fields}, separators=(",", ":")),
                            ts,
                        ),
                    )

            domain_to_cr: dict[str, list[int]] = {}
            for s, cr_id in span_cr:
                domain_to_cr.setdefault(s.domain, []).append(cr_id)

            for s, from_cr in span_cr:
                for link in s.links:
                    to_domain = link.get("to_domain")
                    if not to_domain or to_domain not in domain_to_cr:
                        continue
                    to_ids = domain_to_cr[to_domain]
                    if not to_ids:
                        continue
                    conn.execute(
                        """
                        INSERT INTO object_link (
                            from_change_request_id, to_change_request_id,
                            from_domain, to_domain, relation, entry_id, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            from_cr,
                            to_ids[0],
                            s.domain,
                            to_domain,
                            str(link.get("relation") or "related"),
                            entry_id,
                            ts,
                        ),
                    )

            if status == "unfiled":
                card_id = new_ulid()
                conn.execute(
                    """
                    INSERT INTO unfiled_card (
                        id, entry_id, capture_event_id, title, data_json,
                        status, created_at, updated_at
                    )
                    SELECT ?, e.id, e.capture_event_id, ?, ?, 'open', ?, ?
                    FROM entry e WHERE e.id = ?
                    """,
                    (
                        card_id,
                        text[:80],
                        json.dumps({"raw": text, "spans": payload["captures"]}),
                        ts,
                        ts,
                        entry_id,
                    ),
                )

            conn.commit()
        finally:
            conn.close()
