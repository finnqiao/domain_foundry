"""Per-model token pricing for cost metering (Phase 1).

Rates are USD per 1M tokens, snapshotted from provider docs (2026-07).
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
    # Anthropic Claude (sota tier) — platform.claude.com pricing
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-6-20250414": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    # OpenAI fallbacks (legacy OpenAICompatibleProvider)
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
    "z-ai/glm-5.2": "glm-5.2",
}


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
    """Map a model id to routine/sota when recognizable."""
    key = normalize_model_id(model)
    if not key:
        return None
    if key.startswith("deepseek") or key.startswith("gpt-") or key.startswith("glm"):
        return "routine"
    if key.startswith("claude"):
        return "sota"
    return None
