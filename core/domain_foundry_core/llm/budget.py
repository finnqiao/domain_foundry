"""Canonical paid HTTP admission. No caller may bypass this transport.

Quotes are deliberately conservative LOCAL estimates, not provider-side dollar
caps. Unknown endpoints/models fail closed. Provider price changes can invalidate
an estimate; any measured overrun latches further admission off for review.
"""
from __future__ import annotations

import json
import math
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from domain_foundry_core.llm.pricing import _ALIASES, _MODEL_PRICING, ModelPrice
from domain_foundry_core.paths import Workspace

MAX_OUTPUT_TOKENS = 8192
_APPROVED_HOSTS = {'api.openai.com', 'api.anthropic.com', 'api.deepseek.com',
                   'openrouter.ai', 'eu.openrouter.ai', 'us.openrouter.ai'}


_POLICY_TIER: ContextVar[str | None] = ContextVar("llm_budget_tier", default=None)
_POLICY_GUARD: ContextVar[Any] = ContextVar("llm_budget_guard", default=None)


@contextmanager
def budget_scope(tier: str, guard: Any = None):
    if tier not in {"routine", "sota", "foundry"}:
        raise BudgetAdmissionError("Unknown policy tier")
    token = _POLICY_TIER.set(tier)
    guard_token = _POLICY_GUARD.set(guard if guard is not None else _POLICY_GUARD.get())
    try:
        yield
    finally:
        _POLICY_TIER.reset(token)
        _POLICY_GUARD.reset(guard_token)


class BudgetAdmissionError(RuntimeError):
    """No external request was permitted."""


class BudgetAccountingError(RuntimeError):
    """The request may be billed; its durable hold remains unreleased."""


def exact_price(model: str, url: str) -> ModelPrice:
    endpoint = urlsplit(url)
    allowed_paths = {
        "api.openai.com": {"/v1/chat/completions"},
        "api.anthropic.com": {"/v1/messages"},
        "api.deepseek.com": {"/chat/completions", "/v1/chat/completions"},
        "openrouter.ai": {"/api/v1/chat/completions"},
        "eu.openrouter.ai": {"/api/v1/chat/completions"},
        "us.openrouter.ai": {"/api/v1/chat/completions"},
    }
    if (endpoint.scheme != "https" or endpoint.hostname not in _APPROVED_HOSTS
            or endpoint.username or endpoint.password or endpoint.port not in {None, 443}
            or endpoint.query or endpoint.fragment
            or endpoint.path not in allowed_paths.get(endpoint.hostname or "", set())):
        raise BudgetAdmissionError("Endpoint pricing is not approved; no request sent")
    host = endpoint.hostname
    if ((host == "api.openai.com" and (not model.startswith("gpt-") or "/" in model))
            or (host == "api.anthropic.com" and (not model.startswith("claude-") or "/" in model))
            or (host == "api.deepseek.com" and (not model.startswith("deepseek-") or "/" in model))
            or (host in {"openrouter.ai", "eu.openrouter.ai", "us.openrouter.ai"} and model not in _ALIASES)):
        raise BudgetAdmissionError("Model/provider pricing pair unavailable; no request sent")
    # Never infer rates from an arbitrary provider prefix or model suffix.
    key = _ALIASES.get(model, model)
    rates = _MODEL_PRICING.get(key)
    if rates is None or any(not math.isfinite(v) or v < 0 for v in rates) or not any(rates):
        raise BudgetAdmissionError('Exact model pricing unavailable; no request sent')
    return ModelPrice(*rates)


def _count(usage: dict[str, Any], name: str, *, optional: bool = False) -> int:
    value = usage.get(name, 0 if optional else None)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BudgetAccountingError('Missing or invalid token accounting; reservation retained')
    return value


def post_json(
    url: str, *, headers: dict[str, str], body: dict[str, Any], timeout: float,
    home: Path | None, tier: str, dialect: str,
) -> dict[str, Any]:
    from domain_foundry_core.routing.cost import CostGuard, CostGuardConfig

    if tier not in {'routine', 'sota', 'foundry'}:
        raise BudgetAdmissionError('Unknown budget tier; no request sent')
    host = urlsplit(url).hostname
    if dialect not in {"anthropic", "openai_compatible"} or ((host == "api.anthropic.com") != (dialect == "anthropic")):
        raise BudgetAdmissionError("Unknown or mismatched wire dialect; no request sent")
    output_fields = {"max_tokens", "max_completion_tokens"} & body.keys()
    expected_output = "max_completion_tokens" if host == "api.openai.com" else "max_tokens"
    if output_fields != {expected_output}:
        raise BudgetAdmissionError("Ambiguous or incompatible output bound; no request sent")
    allowed_fields = {"model", "messages", "response_format", "thinking", "reasoning_effort",
                      "system", "max_tokens", "max_completion_tokens", "temperature", "output_config"}
    if body.keys() - allowed_fields:
        raise BudgetAdmissionError("Unpriced request features; no request sent")
    if "system" in body and not isinstance(body["system"], str):
        raise BudgetAdmissionError("Unpriced system content; no request sent")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages or any(
        not isinstance(m, dict) or set(m) != {"role", "content"} or not isinstance(m["content"], str)
        for m in messages
    ):
        raise BudgetAdmissionError("Unpriced message content; no request sent")
    if "output_config" in body and (not isinstance(body["output_config"], dict) or body["output_config"].keys() - {"effort"}):
        raise BudgetAdmissionError("Unpriced output configuration; no request sent")
    model = body.get('model')
    if not isinstance(model, str):
        raise BudgetAdmissionError('Exact model required; no request sent')
    price = exact_price(model, url)
    output_limit = body.get('max_completion_tokens', body.get('max_tokens'))
    if isinstance(output_limit, bool) or not isinstance(output_limit, int) or not 1 <= output_limit <= MAX_OUTPUT_TOKENS:
        raise BudgetAdmissionError('Bounded output required; no request sent')
    # Include the FINAL retry/schema body, Unicode bytes and generous framing.
    # This is an estimate, not a tokenizer/provider billing guarantee.
    input_bound = len(json.dumps(body, ensure_ascii=False).encode('utf-8')) + 2048
    quote = (input_bound * price.input_per_million * 2 + output_limit * price.output_per_million) / 1_000_000
    guard = CostGuard(Workspace(home).ledger_db)
    policy_guard = _POLICY_GUARD.get()
    if policy_guard is not None:
        if policy_guard.ledger_db.resolve() != guard.ledger_db.resolve():
            raise BudgetAdmissionError("Budget workspace mismatch; no request sent")
        policy_guard.config.__post_init__()
        caps = {
            key: min(guard.config.tier_caps.get(key, math.inf), policy_guard.config.tier_caps.get(key, math.inf))
            for key in guard.config.tier_caps.keys() | policy_guard.config.tier_caps.keys()
        }
        guard = CostGuard(guard.ledger_db, CostGuardConfig(
            min(guard.config.daily_usd_cap, policy_guard.config.daily_usd_cap), caps
        ))
    reservation = guard.reserve(quote, tier=_POLICY_TIER.get() or tier)
    if reservation is None:
        raise BudgetAdmissionError('Budget unavailable or ledger needs migration/reconciliation; no request sent')

    # Once dispatch begins, no exception refunds the hold: even timeouts and
    # invalid JSON can have incurred provider charges. Every retry re-enters.
    response = httpx.post(url, headers=headers, json=body, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise BudgetAccountingError('Invalid response accounting; reservation retained')
    actual_model = payload.get('model')
    if actual_model is not None and actual_model != model:
        if _ALIASES.get(actual_model, actual_model) != _ALIASES.get(model, model):
            raise BudgetAccountingError('Response model differs from quote; reservation retained')
    usage = payload.get('usage')
    if not isinstance(usage, dict):
        raise BudgetAccountingError('Missing usage; reservation retained')
    if dialect == 'anthropic':
        inp = _count(usage, 'input_tokens')
        out = _count(usage, 'output_tokens')
        # Conservatively charge cache writes at 2x input rate, reads at full
        # input rate. Do not silently discard these billable token categories.
        cache_create = _count(usage, 'cache_creation_input_tokens', optional=True)
        cache_read = _count(usage, 'cache_read_input_tokens', optional=True)
        billed_input = inp + 2 * cache_create + cache_read
    else:
        inp = _count(usage, 'prompt_tokens')
        out = _count(usage, 'completion_tokens')
        billed_input = inp
    cost = (billed_input * price.input_per_million + out * price.output_per_million) / 1_000_000
    # Persist before caller parses generated JSON, refusal, or schema validation.
    try:
        settled = guard.settle(reservation, provider=dialect, model=model,
                               input_tokens=inp, output_tokens=out, cost_usd=cost)
    except Exception as exc:
        raise BudgetAccountingError('Accounting unavailable; reservation retained') from exc
    if not settled:
        raise BudgetAccountingError('Reservation identity unavailable; no unaccounted result returned')
    # Private metadata is produced here, never trusted from provider payloads.
    payload['_domain_foundry_accounted'] = True
    payload['_domain_foundry_cost_usd'] = cost
    return payload
