"""Opt-in live smoke test for tiered LLM providers + token cost metering.

Skipped unless DOMAIN_FOUNDRY_LIVE_SMOKE=1 and at least one API key is present.

Required env (any subset):
  DEEPSEEK_API_KEY or DOMAIN_FOUNDRY_ROUTINE_API_KEY  → routine (deepseek-chat)
  ANTHROPIC_API_KEY or DOMAIN_FOUNDRY_SOTA_API_KEY    → sota (claude-sonnet-4-6)

Optional:
  DOMAIN_FOUNDRY_ROUTINE_MODEL, DOMAIN_FOUNDRY_SOTA_MODEL
  DOMAIN_FOUNDRY_ROUTINE_BASE_URL (default https://api.deepseek.com/v1)
"""

from __future__ import annotations

import os

import pytest

from domain_foundry_core.llm.pricing import estimate_cost_usd
from domain_foundry_core.llm.provider import HeuristicProvider, build_tiered_provider


def _live_enabled() -> bool:
    return os.environ.get("DOMAIN_FOUNDRY_LIVE_SMOKE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@pytest.mark.skipif(not _live_enabled(), reason="set DOMAIN_FOUNDRY_LIVE_SMOKE=1")
def test_live_tiered_providers_return_nonzero_token_cost():
    provider = build_tiered_provider()
    if not provider.has_live_keys():
        pytest.skip("no DEEPSEEK_API_KEY / ANTHROPIC_API_KEY configured")

    system = "Return a JSON object with key ok set to true."
    user = 'Respond with {"ok": true} only.'
    costs: dict[str, float] = {}

    if not isinstance(provider.routine, HeuristicProvider):
        result = provider.complete_json(system=system, user=user, tier="routine")
        assert isinstance(result.data, dict)
        assert result.usage.input_tokens + result.usage.output_tokens > 0
        cost = estimate_cost_usd(
            model=result.usage.model or provider.routine_model,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )
        assert cost > 0, f"routine cost should be > 0, usage={result.usage}"
        costs["routine"] = cost

    if not isinstance(provider.sota, HeuristicProvider):
        result = provider.complete_json(system=system, user=user, tier="sota")
        assert isinstance(result.data, dict)
        assert result.usage.input_tokens + result.usage.output_tokens > 0
        cost = estimate_cost_usd(
            model=result.usage.model or provider.sota_model,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )
        assert cost > 0, f"sota cost should be > 0, usage={result.usage}"
        costs["sota"] = cost

    assert costs, "expected at least one live tier to run"
