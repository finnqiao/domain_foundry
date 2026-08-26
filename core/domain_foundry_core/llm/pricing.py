"""Per-model token pricing for cost metering (Phase 1).

Rates are USD per 1M tokens, snapshotted from provider docs (2026-08).
"""

from __future__ import annotations

from dataclasses import dataclass

# (input_per_m, output_per_m) — official docs snapshots
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # DeepSeek (routine tier) — api-docs.deepseek.com
    "deepseek-chat": (0.14, 0.28),
    "deepseek-reasoner": (0.14, 0.28),
    "deepseek-v4-flash": (0.14, 0.28),
    "deepseek-v4-pro": (0.435, 0.87),
    # Anthropic Claude — platform.claude.com pricing.
    # Haiku is the suggested *routine* model, the rest are sota candidates.
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-6-20250414": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-opus-4-5": (5.00, 25.00),
    "claude-fable-5": (10.00, 50.00),
    "claude-mythos-5": (10.00, 50.00),
    # OpenAI current defaults plus legacy receipt support.
    "gpt-5.6-luna": (0.20, 1.20),
    "gpt-5.6-terra": (2.00, 12.00),
    "gpt-5.6-sol": (5.00, 30.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    # Z.ai GLM (routine tier via OpenRouter) — openrouter.ai pricing
    "glm-5.2": (0.798, 2.508),
}

# Alias map: strip provider prefixes / date suffixes loosely
_ALIASES: dict[str, str] = {
    "deepseek/deepseek-chat": "deepseek-chat",
    "deepseek/deepseek-v4-flash": "deepseek-v4-flash",
    "anthropic/claude-sonnet-4-6": "claude-sonnet-4-6",
    "anthropic/claude-opus-4-8": "claude-opus-4-8",
    "anthropic/claude-opus-5": "claude-opus-5",
    "anthropic/claude-sonnet-5": "claude-sonnet-5",
    "anthropic/claude-haiku-4-5": "claude-haiku-4-5",
    "z-ai/glm-5.2": "glm-5.2",
}

# Claude families that sit on the routine side when chosen for it. Everything
# else Claude-shaped is treated as sota. Only used to attribute *legacy*
# cost_ledger rows written before the tier column existed — current writes
# record the tier explicitly, so this never overrides a real answer.
_ROUTINE_CLAUDE_PREFIXES = ("claude-haiku",)


@dataclass(frozen=True)
class ModelPrice:
    input_per_million: float
    output_per_million: float


def normalize_model_id(model: str | None) -> str:
    raw = (model or "").strip().lower()
    if not raw:
        return ""
    if raw in _ALIASES:
        return _ALIASES[raw]
    # anthropic/claude-sonnet-4-6 → claude-sonnet-4-6
    if "/" in raw:
        raw = raw.rsplit("/", 1)[-1]
    return raw


def lookup_price(model: str | None) -> ModelPrice | None:
    key = normalize_model_id(model)
    if not key:
        return None
    if key in _MODEL_PRICING:
        inp, out = _MODEL_PRICING[key]
        return ModelPrice(inp, out)
    # Prefix match for dated variants (claude-sonnet-4-6-YYYYMMDD)
    for known, rates in _MODEL_PRICING.items():
        if key.startswith(known):
            return ModelPrice(rates[0], rates[1])
    return None


def estimate_cost_usd(
    *,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Return USD cost from token counts × per-model rates. 0.0 if unknown."""
    price = lookup_price(model)
    if price is None:
        return 0.0
    inp = max(0, int(input_tokens or 0))
    out = max(0, int(output_tokens or 0))
    return (inp * price.input_per_million + out * price.output_per_million) / 1_000_000.0


def tier_for_model(model: str | None) -> str | None:
    """Best-effort tier for a model id, for legacy rows with no tier recorded.

    Under bring-your-own-key a model's tier is a *user choice*, not a property
    of its name — Haiku is the suggested routine model while Opus is sota, and a
    user is free to invert that. Current writes record the tier explicitly; this
    only guesses for pre-tier-column ledger rows.
    """
    key = normalize_model_id(model)
    if not key:
        return None
    if key.startswith(_ROUTINE_CLAUDE_PREFIXES):
        return "routine"
    if key.startswith("deepseek") or key.startswith("gpt-") or key.startswith("glm"):
        return "routine"
    if key.startswith("claude"):
        return "sota"
    return None
