"""Bring-your-own-key provider registry.

Domain Foundry does not ship a model choice — you bring a key and pick. This
module is the table the onboarding flow (``domain-foundry setup``) offers, and
the source of the per-tier defaults that :mod:`domain_foundry_core.llm.provider`
falls back to when neither the environment nor the config file says otherwise.

Two things live here:

* :class:`ProviderSpec` — one row per provider: which wire dialect it speaks,
  where it lives, which env vars conventionally hold its key, and a *suggested*
  routine/sota pair. Suggestions are starting points, not policy; the user
  overrides either tier at setup time or with ``DOMAIN_FOUNDRY_*_MODEL``.
* :func:`anthropic_request_caps` — the per-model request-shape facts that a
  BYO harness cannot guess. Current Claude models **reject** ``temperature``
  (HTTP 400), only some accept ``output_config.effort``, and only some accept
  native ``output_config.format`` structured outputs. Sending an unsupported
  parameter is a hard failure, and in a capture path a hard failure degrades to
  keyword-only routing — so the shape is resolved up front rather than
  discovered in production.

The tier split this feeds:

    routine  every capture's routing + field extraction — high volume, low stakes
    sota     corrections, structural/schema-affecting ops, low-confidence and
             multi-domain fan-out — rare, high stakes

See :func:`domain_foundry_core.llm.provider.select_model_tier` for the
escalation policy that decides which of the two a given call gets.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

# Wire dialects. "anthropic" → POST {base}/v1/messages with x-api-key.
# "openai" → POST {base}/chat/completions with a Bearer token. Anything a user
# points us at that is not an Anthropic host speaks the OpenAI-compatible shape.
DIALECT_ANTHROPIC = "anthropic"
DIALECT_OPENAI = "openai"


@dataclass(frozen=True)
class ProviderSpec:
    """One BYO provider option offered at setup."""

    id: str
    label: str
    dialect: str
    base_url: str | None
    # Env vars that conventionally hold this provider's key, in *detection*
    # precedence order — a DF-specific override beats the vendor's own name.
    api_key_envs: tuple[str, ...]
    routine_model: str | None
    sota_model: str | None
    # The env var to *recommend* when nothing is set yet. Deliberately separate
    # from api_key_envs: detection wants the DF-specific override first, but a
    # user should be told to export the name their other tools already use, not
    # a Domain-Foundry-only one.
    canonical_key_env: str | None = None
    # Where a user gets a key. Shown by setup; never fetched.
    signup_url: str | None = None
    notes: str = ""
    # True when this provider needs no key at all (offline / local).
    keyless: bool = False

    @property
    def needs_key(self) -> bool:
        return not self.keyless


# Ordered as setup presents them. Every network default is checked against the
# time-bounded official-source record in release/provider-compatibility.yaml;
# request-contract tests cover the first-party dialect differences. A provider
# can rename a model at any time, so the aggregate release gate expires that
# compatibility evidence after 30 days instead of treating these aliases as
# timeless constants.
_PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        id="anthropic",
        label="Anthropic (Claude)",
        dialect=DIALECT_ANTHROPIC,
        base_url="https://api.anthropic.com",
        api_key_envs=("DOMAIN_FOUNDRY_SOTA_API_KEY", "ANTHROPIC_API_KEY"),
        canonical_key_env="ANTHROPIC_API_KEY",
        # Haiku for the high-volume routing/extraction path, Opus for the calls
        # that change a schema or rewrite a canonical record.
        routine_model="claude-haiku-4-5",
        sota_model="claude-opus-5",
        signup_url="https://console.anthropic.com/settings/keys",
        notes="One key covers both tiers.",
    ),
    ProviderSpec(
        id="openai",
        label="OpenAI",
        dialect=DIALECT_OPENAI,
        base_url="https://api.openai.com/v1",
        api_key_envs=("OPENAI_API_KEY",),
        canonical_key_env="OPENAI_API_KEY",
        routine_model="gpt-5.6-luna",
        sota_model="gpt-5.6-sol",
        signup_url="https://platform.openai.com/api-keys",
        notes="Luna handles high-volume work; Sol handles schema and design work.",
    ),
    ProviderSpec(
        id="deepseek",
        label="DeepSeek",
        dialect=DIALECT_OPENAI,
        base_url="https://api.deepseek.com",
        api_key_envs=("DOMAIN_FOUNDRY_ROUTINE_API_KEY", "DEEPSEEK_API_KEY"),
        canonical_key_env="DEEPSEEK_API_KEY",
        routine_model="deepseek-v4-flash",
        sota_model="deepseek-v4-pro",
        signup_url="https://platform.deepseek.com/api_keys",
        notes="Cheapest per capture; weaker on json_schema adherence.",
    ),
    ProviderSpec(
        id="openrouter",
        label="OpenRouter (many models, one key)",
        dialect=DIALECT_OPENAI,
        base_url="https://openrouter.ai/api/v1",
        api_key_envs=("OPENROUTER_API_KEY",),
        canonical_key_env="OPENROUTER_API_KEY",
        routine_model="z-ai/glm-5.2",
        sota_model="anthropic/claude-opus-5",
        signup_url="https://openrouter.ai/keys",
        notes="Mix providers across tiers; prefix models with the vendor.",
    ),
    ProviderSpec(
        id="local",
        label="Local / self-hosted (Ollama, llama.cpp, vLLM)",
        dialect=DIALECT_OPENAI,
        base_url="http://127.0.0.1:11434/v1",
        api_key_envs=("DOMAIN_FOUNDRY_LLM_API_KEY",),
        canonical_key_env="DOMAIN_FOUNDRY_LLM_API_KEY",
        routine_model=None,
        sota_model=None,
        notes="Nothing leaves your machine. Set the model to whatever you serve.",
        keyless=True,
    ),
    ProviderSpec(
        id="none",
        label="No model — keyword rules only (offline)",
        dialect=DIALECT_OPENAI,
        base_url=None,
        api_key_envs=(),
        routine_model=None,
        sota_model=None,
        notes="Captures are still never dropped, but routing is rules-only.",
        keyless=True,
    ),
)

_BY_ID = {p.id: p for p in _PROVIDERS}


def all_providers() -> tuple[ProviderSpec, ...]:
    """Every provider option, in the order setup presents them."""
    return _PROVIDERS


def get_provider(provider_id: str | None) -> ProviderSpec | None:
    """Look up a provider by id (case-insensitive)."""
    if not provider_id:
        return None
    return _BY_ID.get(provider_id.strip().lower())


def provider_ids() -> tuple[str, ...]:
    return tuple(p.id for p in _PROVIDERS)


def is_anthropic_base(base_url: str | None) -> bool:
    """True when a base URL speaks the Anthropic Messages API.

    Only anthropic.com hosts get the ``/v1/messages`` + ``x-api-key`` shape.
    Anything else a user points at — OpenRouter, Groq, a local llama.cpp — is
    OpenAI-compatible, which is what the docs promise.
    """
    from urllib.parse import urlparse

    if not base_url:
        return False
    return "anthropic" in urlparse(base_url).netloc.lower()


def is_deepseek_base(base_url: str | None) -> bool:
    """True only for DeepSeek's first-party OpenAI-compatible API."""
    if not base_url:
        return False
    return urlparse(base_url).netloc.lower() == "api.deepseek.com"


def is_openai_base(base_url: str | None) -> bool:
    """True only for OpenAI's first-party API, not compatible gateways."""
    if not base_url:
        return False
    return urlparse(base_url).netloc.lower() == "api.openai.com"


# ---------------------------------------------------------------------------
# Anthropic per-model request shape
# ---------------------------------------------------------------------------

# Models that *accept* temperature/top_p/top_k. Sampling params were removed
# starting with Opus 4.7 and return HTTP 400 there; Opus 4.6, Sonnet 4.6,
# Haiku 4.5 and older still take them. This is an accept-list rather than a
# reject-list on purpose: an unrecognised model is far likelier to be newer
# (sampling removed) than older, and guessing wrong here 400s the call.
_ACCEPTS_SAMPLING: tuple[str, ...] = (
    "claude-opus-4-6",
    "claude-opus-4-5",
    "claude-opus-4-1",
    "claude-opus-4-0",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5",
    "claude-sonnet-4-0",
    "claude-haiku-4-5",
    "claude-3-",
)

# Models accepting output_config.effort. Errors on Sonnet 4.5 and Haiku 4.5.
_SUPPORTS_EFFORT: tuple[str, ...] = (
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-opus-4-5",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
)

# Models accepting native structured outputs via output_config.format.
# Deliberately narrower than _SUPPORTS_EFFORT — Opus 4.6/4.7 and Sonnet 4.6
# take effort but are not on the structured-outputs list.
_SUPPORTS_JSON_SCHEMA: tuple[str, ...] = (
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-5",
    "claude-opus-4-1",
    "claude-sonnet-5",
    "claude-haiku-4-5",
)

# Thinking is on by default on Opus 5 and shares the max_tokens budget with the
# response, so a budget sized for "just the JSON" truncates mid-answer.
_THINKS_BY_DEFAULT: tuple[str, ...] = (
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-sonnet-5",
)


@dataclass(frozen=True)
class AnthropicCaps:
    """Request-shape facts for one Anthropic model id."""

    rejects_sampling_params: bool
    supports_effort: bool
    supports_json_schema: bool
    thinks_by_default: bool


def _matches(model: str, prefixes: tuple[str, ...]) -> bool:
    return any(model == p or model.startswith(p) for p in prefixes)


def anthropic_request_caps(model: str | None) -> AnthropicCaps:
    """Resolve the request shape for an Anthropic model id.

    Unknown ids get the *conservative* shape: assume sampling params are
    rejected (the current-generation behaviour, and the failure mode that
    silently downgrades a capture to keyword routing), and assume the optional
    niceties are unavailable. A newer model than this table knows about is far
    more likely to have dropped sampling params than to have restored them.
    """
    key = (model or "").strip().lower()
    if "/" in key:  # anthropic/claude-opus-5 via a gateway
        key = key.rsplit("/", 1)[-1]
    if not key:
        return AnthropicCaps(True, False, False, False)
    return AnthropicCaps(
        rejects_sampling_params=not _matches(key, _ACCEPTS_SAMPLING),
        supports_effort=_matches(key, _SUPPORTS_EFFORT),
        supports_json_schema=_matches(key, _SUPPORTS_JSON_SCHEMA),
        thinks_by_default=_matches(key, _THINKS_BY_DEFAULT),
    )
