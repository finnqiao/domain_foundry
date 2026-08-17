"""Translate a question into one validated, schema-constrained AskPlan."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from domain_foundry_core.ask.schema import (
    AskPlan,
    AskPlanError,
    Catalog,
    validate_plan,
)
from domain_foundry_core.llm.provider import LLMProvider, TokenUsage

ASK_PLAN_SCHEMA: dict[str, Any] = AskPlan.model_json_schema()

_SYSTEM = (
    "You translate a user's question about their OWN captured data into a "
    "query plan. Output ONLY a JSON object matching the AskPlan schema. "
    "Use only domains, object types and fields present in CATALOG_JSON. "
    "intent=lookup for single-item questions, intent=list for lists, and "
    "intent=aggregate for counts/sums/averages. Put searchable words in "
    "text_query. Never invent fields. If the question is not answerable from "
    "the catalog, emit a list plan whose text_query contains its key words."
)


def plan_ask(
    question: str,
    catalog: Catalog,
    llm: LLMProvider,
    *,
    tier: str = "routine",
    domain: str | None = None,
) -> tuple[AskPlan, TokenUsage | None]:
    """Return a catalog-validated plan and model usage."""
    user = (
        f"QUESTION:\n{question}\n"
        + (f"SCOPE_DOMAIN: {domain}\n" if domain else "")
        + "CATALOG_JSON:\n"
        + json.dumps(catalog, ensure_ascii=False, sort_keys=True)
    )
    result = llm.complete_json(
        system=_SYSTEM,
        user=user,
        schema=ASK_PLAN_SCHEMA,
        tier=tier,
    )
    try:
        plan = AskPlan.model_validate(result.data)
    except (TypeError, ValueError, ValidationError) as exc:
        raise AskPlanError(f"invalid ask plan: {exc}") from exc

    if domain:
        if plan.domain not in {None, domain}:
            raise AskPlanError(
                f"ask plan escaped requested domain {domain!r}: {plan.domain!r}"
            )
        plan = plan.model_copy(update={"domain": domain})
    try:
        return validate_plan(plan, catalog), result.usage
    except AskPlanError:
        raise
    except Exception as exc:
        raise AskPlanError(str(exc)) from exc


_STOP_WORDS = {
    "a",
    "about",
    "an",
    "and",
    "are",
    "did",
    "do",
    "for",
    "have",
    "how",
    "i",
    "in",
    "is",
    "it",
    "last",
    "logged",
    "many",
    "me",
    "my",
    "of",
    "on",
    "the",
    "this",
    "to",
    "was",
    "what",
    "when",
    "which",
    "with",
}


def fallback_plan(question: str, *, domain: str | None = None) -> AskPlan:
    """Build a deterministic search plan when no model call is available."""
    words = [
        "".join(ch for ch in word if ch.isalnum() or ch in {"_", "-", "%"})
        for word in question.split()
    ]
    keywords = [word for word in words if word and word.lower() not in _STOP_WORDS]
    text_query = " ".join(keywords) or question
    return AskPlan(intent="list", domain=domain, text_query=text_query, limit=20)
