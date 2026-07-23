"""Unit tests for Phase 1 LLM tier selection + token-derived cost metering."""

from __future__ import annotations

from typing import Any

from domain_foundry_core.ledger.migrate import ensure_migrated
from domain_foundry_core.llm.pricing import estimate_cost_usd, lookup_price, tier_for_model
from domain_foundry_core.llm.provider import (
    CompletionResult,
    HeuristicProvider,
    LLMProvider,
    TieredLLMProvider,
    TokenUsage,
    select_model_tier,
)
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace
from domain_foundry_core.routing.cost import CostGuard, CostGuardConfig
from domain_foundry_core.routing.router import Router


class _FakeLLM(LLMProvider):
    name = "fake_llm"

    def __init__(
        self,
        data: dict[str, Any] | None = None,
        *,
        usage: TokenUsage | None = None,
        raise_exc: bool = False,
    ) -> None:
        self.data = data or {
            "captures": [
                {
                    "domain": "plants",
                    "object_type": "care_event",
                    "operation": "create",
                    "span": "watered the monstera",
                    "confidence": 0.9,
                    "fields": {"plant_name": "monstera", "action": "water"},
                    "links": [],
                }
            ],
            "unmatched_text": None,
            "needs_clarification": False,
            "clarifying_question": None,
        }
        self.usage = usage or TokenUsage(
            input_tokens=1000,
            output_tokens=200,
            model="deepseek-chat",
            tier="routine",
            provider="fake_llm",
        )
        self.raise_exc = raise_exc
        self.calls: list[dict[str, Any]] = []

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        model: str | None = None,
        tier: str | None = None,
    ) -> CompletionResult:
        self.calls.append({"tier": tier, "model": model, "system": system[:40]})
        if self.raise_exc:
            raise RuntimeError("boom")
        usage = TokenUsage(
            input_tokens=self.usage.input_tokens,
            output_tokens=self.usage.output_tokens,
            model=model or self.usage.model,
            tier=tier or self.usage.tier,
            provider=self.name,
        )
        return CompletionResult(data=self.data, usage=usage)


def test_select_model_tier_routine_default():
    assert (
        select_model_tier(
            l1_confidence=0.9,
            l1_reason="escalate_structured_or_long",
            text="watered the monstera this morning after breakfast",
        )
        == "routine"
    )


def test_select_model_tier_sota_on_low_confidence():
    assert (
        select_model_tier(
            l1_confidence=0.4,
            l1_reason="no_match",
            text="something ambiguous about life",
        )
        == "sota"
    )


def test_select_model_tier_sota_on_multi_pack():
    assert (
        select_model_tier(
            l1_confidence=0.5,
            l1_reason="multi_pack",
            text="watered monstera and baked a loaf",
        )
        == "sota"
    )


def test_select_model_tier_sota_on_rule_override():
    assert (
        select_model_tier(
            l1_confidence=0.95,
            l1_reason="escalate_structured_or_long",
            text="schema change please",
            rule_tiers=["sota"],
        )
        == "sota"
    )


def test_select_model_tier_sota_on_correction():
    assert (
        select_model_tier(
            l1_confidence=0.9,
            l1_reason="escalate_structured_or_long",
            text="actually that was wrong, should have been rye",
        )
        == "sota"
    )


def test_select_model_tier_sota_on_structural():
    assert (
        select_model_tier(
            l1_confidence=0.9,
            l1_reason="escalate_structured_or_long",
            text="update the recipe title",
            structural=True,
        )
        == "sota"
    )


def test_pricing_glm_openrouter_alias():
    glm = lookup_price("z-ai/glm-5.2")
    assert glm is not None
    assert glm == lookup_price("glm-5.2")

    cost = estimate_cost_usd(
        model="z-ai/glm-5.2", input_tokens=1_000_000, output_tokens=0
    )
    assert abs(cost - 0.798) < 1e-9
    assert estimate_cost_usd(model="z-ai/glm-5.2", input_tokens=33, output_tokens=25) > 0

    assert tier_for_model("z-ai/glm-5.2") == "routine"


def test_pricing_deepseek_and_claude():
    ds = lookup_price("deepseek-chat")
    assert ds is not None
    cl = lookup_price("claude-sonnet-4-6")
    assert cl is not None
    # SOTA rates should be higher per token than routine
    assert cl.input_per_million > ds.input_per_million

    cost = estimate_cost_usd(
        model="deepseek-chat", input_tokens=1_000_000, output_tokens=0
    )
    assert abs(cost - 0.14) < 1e-9

    cost_sota = estimate_cost_usd(
        model="claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0
    )
    assert abs(cost_sota - 3.0) < 1e-9

    assert tier_for_model("deepseek-chat") == "routine"
    assert tier_for_model("claude-sonnet-4-6") == "sota"


def test_token_derived_cost_gt_zero_when_usage_present(workspace: Workspace):
    ensure_migrated(workspace.ledger_db, "ledger")
    registry = PackRegistry(workspace)
    registry.activate_bundled("plants")
    fake = _FakeLLM(
        usage=TokenUsage(
            input_tokens=10_000,
            output_tokens=2_000,
            model="deepseek-chat",
            tier="routine",
            provider="fake_llm",
        )
    )
    router = Router(workspace, registry=registry, llm=fake, cost_cap=1.0)
    # Ambiguous / long text forces L2 escalate
    result = router.route_text(
        "please interpret this unstructured plant note that is definitely long enough "
        "to force the L2 path rather than a simple L1-only short care event"
    )
    assert result.interpreter == "fake_llm"
    assert result.cost_usd > 0
    expected = estimate_cost_usd(
        model="deepseek-chat", input_tokens=10_000, output_tokens=2_000
    )
    assert abs(result.cost_usd - expected) < 1e-12
    assert result.usage is not None
    assert result.usage.input_tokens == 10_000
    assert fake.calls, "fake LLM should have been invoked"
    assert fake.calls[0]["tier"] in {"routine", "sota"}


def test_cost_guard_daily_trips_to_heuristic(workspace: Workspace):
    ensure_migrated(workspace.ledger_db, "ledger")
    registry = PackRegistry(workspace)
    registry.activate_bundled("plants")
    fake = _FakeLLM()
    router = Router(workspace, registry=registry, llm=fake, cost_cap=0.0001)
    router.cost.record(
        provider="test",
        model="deepseek-chat",
        input_tokens=1,
        output_tokens=1,
        cost_usd=1.0,
        tier="routine",
    )
    assert router.cost.allow_llm() is False
    result = router.route_text(
        "please interpret this unstructured plant note that is definitely long enough "
        "to force the L2 path rather than a simple L1-only short care event"
    )
    assert result.interpreter == "rules_only_cost_guard"
    assert result.cost_usd == 0.0
    assert not fake.calls


def test_per_tier_budget_trips_sota_to_heuristic(workspace: Workspace):
    ensure_migrated(workspace.ledger_db, "ledger")
    registry = PackRegistry(workspace)
    registry.activate_bundled("plants")
    fake = _FakeLLM(
        usage=TokenUsage(
            input_tokens=100,
            output_tokens=50,
            model="claude-sonnet-4-6",
            tier="sota",
            provider="fake_llm",
        )
    )
    guard_cfg = CostGuardConfig(
        daily_usd_cap=1.0,
        tier_caps={"routine": 0.5, "sota": 0.0001},
    )
    router = Router(workspace, registry=registry, llm=fake, cost_cap=1.0)
    router.cost = CostGuard(workspace.ledger_db, guard_cfg)
    # Exhaust sota budget only
    router.cost.record(
        provider="anthropic",
        model="claude-sonnet-4-6",
        input_tokens=10,
        output_tokens=10,
        cost_usd=0.5,
        tier="sota",
    )
    assert router.cost.allow_llm(tier="sota") is False
    assert router.cost.allow_llm(tier="routine") is True

    # Correction text → sota tier selection → guard trips → heuristic
    result = router.route_text(
        "actually that plant note was wrong and should have been a monstera watering"
    )
    assert result.model_tier == "sota"
    assert result.interpreter == "rules_only_cost_guard"
    assert not fake.calls


def test_tiered_provider_routes_to_backends():
    routine = _FakeLLM(
        usage=TokenUsage(input_tokens=1, output_tokens=1, model="deepseek-chat")
    )
    sota = _FakeLLM(
        usage=TokenUsage(input_tokens=2, output_tokens=2, model="claude-sonnet-4-6")
    )
    # Mark as having keys so has_live_keys works
    routine.api_key = "r"  # type: ignore[attr-defined]
    sota.api_key = "s"  # type: ignore[attr-defined]
    tiered = TieredLLMProvider(routine=routine, sota=sota)
    assert tiered.has_live_keys()

    r = tiered.complete_json(system="s", user="u", tier="routine")
    assert r.usage.tier == "routine"
    assert routine.calls and routine.calls[0]["tier"] == "routine"
    assert not sota.calls

    s = tiered.complete_json(system="s", user="u", tier="sota")
    assert s.usage.tier == "sota"
    assert sota.calls and sota.calls[0]["tier"] == "sota"


def test_heuristic_still_default_offline(workspace: Workspace):
    registry = PackRegistry(workspace)
    registry.activate_bundled("plants")
    router = Router(workspace, registry=registry, llm=HeuristicProvider())
    result = router.route_text("watered the monstera")
    assert result.spans
    assert result.interpreter in {"heuristic", "rules"}
    assert result.cost_usd == 0.0
