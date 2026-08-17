"""Compile an AskPlan onto existing read-only query surfaces."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from domain_foundry_core.ask.schema import AskPlan
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace
from domain_foundry_core.projections.blockdata import BlockDataError, BlockDataService
from domain_foundry_core.search.fts import search_ledger


@dataclass
class AskSource:
    """One row that an answer may cite."""

    object_uid: str | None
    entry_id: str | None
    domain: str | None
    object_type: str | None
    snippet: str


@dataclass
class AskResult:
    plan: AskPlan
    sources: list[AskSource] = field(default_factory=list)
    aggregate: dict[str, Any] | None = None
    empty: bool = True


def execute(plan: AskPlan, workspace: Workspace, registry: PackRegistry) -> AskResult:
    """Read data for a validated plan; this function never writes."""
    blocks = BlockDataService(workspace, registry=registry)
    result = AskResult(plan=plan)
    since = plan.time_range.since if plan.time_range else None
    until = plan.time_range.until if plan.time_range else None

    if plan.intent == "aggregate" and plan.aggregate is not None:
        if plan.domain is None or plan.object_type is None:
            raise ValueError("aggregate plans require domain and object_type")
        aggregate = blocks.aggregate_field(
            plan.domain,
            plan.object_type,
            op=plan.aggregate.op,
            field=plan.aggregate.field,
            since=since,
            until=until,
        )
        result.aggregate = aggregate
        rows = blocks.object_rows(
            plan.domain,
            plan.object_type,
            limit=5,
            since=since,
            until=until,
        )
        result.sources = [_source_from_row(row, plan) for row in rows]
        result.empty = aggregate.get("value") is None
        return result

    if plan.text_query:
        hits = _search_hits(plan, workspace)
        result.sources = [
            AskSource(
                object_uid=hit.ref_id if hit.kind == "canonical" else None,
                entry_id=hit.ref_id if hit.kind == "entry" else None,
                domain=hit.domain,
                object_type=hit.object_type,
                snippet=(hit.raw_text or hit.canonical_text or hit.snippet or "")[:240],
            )
            for hit in hits
        ]
    elif plan.domain and plan.object_type:
        try:
            rows = blocks.object_rows(
                plan.domain,
                plan.object_type,
                limit=plan.limit if plan.intent == "list" else 1,
                since=since,
                until=until,
            )
        except BlockDataError:
            rows = []
        result.sources = [_source_from_row(row, plan) for row in rows]

    result.empty = not result.sources
    return result


def _search_hits(plan: AskPlan, workspace: Workspace) -> list[Any]:
    """Search the full plan first, then useful individual terms if needed."""
    query = plan.text_query or ""
    queries = [query]
    for term in query.split():
        for variant in _term_variants(term):
            if len(variant) >= 2 and variant not in queries:
                queries.append(variant)

    for candidate in queries:
        canonical = search_ledger(
            workspace.ledger_db,
            candidate,
            domain=plan.domain,
            object_type=plan.object_type,
            kind="canonical",
            limit=plan.limit,
        )
        if canonical.hits:
            return canonical.hits

    for candidate in queries:
        entries = search_ledger(
            workspace.ledger_db,
            candidate,
            domain=plan.domain,
            object_type=plan.object_type,
            kind="entry",
            limit=plan.limit,
        )
        if entries.hits:
            return entries.hits
    return []


def _term_variants(term: str) -> list[str]:
    """Cover common English inflections without changing the FTS surface."""
    clean = "".join(ch for ch in term if ch.isalnum() or ch in {"_", "-", "%"})
    if not clean:
        return []
    variants = [clean]
    lower = clean.lower()
    if lower.endswith("ies") and len(clean) > 3:
        variants.append(clean[:-3] + "y")
    elif lower.endswith("es") and len(clean) > 3:
        stem = clean[:-2] + "e"
        variants.extend([stem, stem + "d", stem + "s", stem + "ing"])
    elif lower.endswith("s") and len(clean) > 2:
        variants.append(clean[:-1])
    elif lower.endswith("ed") and len(clean) > 3:
        stem = clean[:-2]
        variants.extend([stem, stem + "e"])
    elif lower.endswith("ing") and len(clean) > 4:
        stem = clean[:-3]
        variants.extend([stem, stem + "e"])
    else:
        variants.extend([clean + "s", clean + "d", clean + "ed", clean + "ing"])
    return list(dict.fromkeys(variants))


def _source_from_row(row: dict[str, Any], plan: AskPlan) -> AskSource:
    preferred_keys = (
        "raw_text",
        "notes",
        "loaf_name",
        "plant_name",
        "route_name",
        "title",
        "name",
        "_title",
    )
    parts: list[str] = []
    for key in preferred_keys:
        value = row.get(key)
        if value not in (None, "") and not isinstance(value, (dict, list)):
            parts.append(str(value))
    if not parts:
        parts = [
            str(value)
            for key, value in sorted(row.items())
            if value not in (None, "")
            and key
            not in {
                "id",
                "object_uid",
                "entry_id",
                "tombstoned",
                "created_at",
                "updated_at",
                "baked_at",
                "logged_at",
                "noted_at",
            }
            and not isinstance(value, (dict, list))
            and not re.match(r"^\d{4}-\d{2}-\d{2}T", str(value))
        ]
    text = " ".join(parts)
    return AskSource(
        object_uid=row.get("object_uid"),
        entry_id=row.get("entry_id"),
        domain=plan.domain,
        object_type=plan.object_type,
        snippet=text[:240],
    )
