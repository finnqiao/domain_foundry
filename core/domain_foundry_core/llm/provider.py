"""LLM provider abstraction with cassette record/replay and model tiers.

Bring your own key. Nothing here hard-codes a provider choice: what a tier
resolves to comes from the environment first, then the workspace config file
that ``domain-foundry setup`` writes, then the provider registry's suggestion
(:mod:`domain_foundry_core.llm.providers`).

  routine → every capture's routing + field extraction (high volume, low stakes)
  sota    → corrections, structural/schema ops, low-confidence and multi-domain
            fan-out (rare, high stakes)

The ``DEFAULT_*`` constants below are the last-resort fallback for an install
with neither env vars nor a config file, and are kept as module attributes
because adapters and tests import them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

import httpx

from domain_foundry_core.config import LLMConfig, TierSettings, load_llm_config
from domain_foundry_core.llm.providers import (
    anthropic_request_caps,
    get_provider,
    is_anthropic_base,
    is_deepseek_base,
    is_openai_base,
)

ModelTier = Literal["routine", "sota"]

DEFAULT_ROUTINE_MODEL = "deepseek-v4-flash"
DEFAULT_SOTA_MODEL = "claude-opus-5"
DEFAULT_ROUTINE_BASE_URL = "https://api.deepseek.com"
DEFAULT_SOTA_BASE_URL = "https://api.anthropic.com"

# Enough room for the JSON plus, on models where thinking is on by default,
# the thinking that shares the same budget. A budget sized for "just the JSON"
# truncates mid-answer on Opus 5.
_ANTHROPIC_MAX_TOKENS = 8192

# Legacy key env vars honoured per tier, after the tier-specific
# DOMAIN_FOUNDRY_{TIER}_API_KEY. Kept so existing installs keep working.
_LEGACY_KEY_ENVS: dict[str, tuple[str, ...]] = {
    "routine": ("DEEPSEEK_API_KEY", "DOMAIN_FOUNDRY_LLM_API_KEY"),
    "sota": ("ANTHROPIC_API_KEY",),
}


class LLMError(RuntimeError):
    pass


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    model: str | None = None
    tier: str | None = None
    provider: str | None = None

    @property
    def total_tokens(self) -> int:
        return int(self.input_tokens or 0) + int(self.output_tokens or 0)


@dataclass
class CompletionResult:
    data: dict[str, Any]
    usage: TokenUsage = field(default_factory=TokenUsage)


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        model: str | None = None,
        tier: str | None = None,
    ) -> CompletionResult:
        """Return parsed JSON object plus token usage from the model."""


class HeuristicProvider(LLMProvider):
    """Deterministic offline interpreter used when no API key / cost guard trips."""

    name = "heuristic"

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        model: str | None = None,
        tier: str | None = None,
    ) -> CompletionResult:
        # The router passes structured context in the user message as JSON after a marker.
        marker = "CONTEXT_JSON:"
        if marker not in user:
            data = {
                "captures": [],
                "unmatched_text": user,
                "needs_clarification": False,
                "clarifying_question": None,
            }
        else:
            ctx_raw = user.split(marker, 1)[1].strip()
            ctx = json.loads(ctx_raw)
            data = _heuristic_interpret(ctx)
        return CompletionResult(
            data=data,
            usage=TokenUsage(model=model or "heuristic", tier=tier, provider=self.name),
        )


def _heuristic_interpret(ctx: dict[str, Any]) -> dict[str, Any]:
    text = ctx.get("text") or ""
    packs = ctx.get("packs") or []
    l1_hits = ctx.get("l1_hits") or []

    # Split into clauses for multi-domain fan-out
    clauses = _split_clauses(text)
    captures: list[dict[str, Any]] = []
    used: set[str] = set()

    full_text = text
    # Only clause-split when L1 already saw multiple packs (fan-out).
    multi = len({h.get("pack") for h in l1_hits}) > 1
    work_clauses = clauses if multi else ([text.strip()] if text.strip() else [])

    for clause in work_clauses:
        best = None
        best_score = 0
        for pack in packs:
            for rule in pack.get("rules") or []:
                try:
                    if re.search(rule["match"], clause, re.IGNORECASE):
                        # Keep boost as a float — int(10 * 0.15) == int(10 * 0.1)
                        # so feedback rules used to tie with the overlapping generic rule.
                        score = 2.0 + 10.0 * float(rule.get("confidence_boost") or 0)
                        obj = rule.get("object")
                        op = rule.get("operation") or "create"
                        candidate = {
                            "domain": pack["name"],
                            "object_type": obj,
                            "operation": op,
                            "span": clause.strip(),
                            "confidence": 0.86,
                            "fields": _extract_fields(full_text, pack, obj),
                            "links": [],
                        }
                        if score > best_score:
                            best_score = score
                            best = candidate
                except re.error:
                    continue
        if best and best["span"] not in used:
            used.add(best["span"])
            captures.append(best)

    # If clause split failed but L1 had hits, emit one capture per pack from L1
    if not captures and l1_hits:
        seen_packs: set[str] = set()
        for hit in l1_hits:
            if hit["pack"] in seen_packs:
                continue
            seen_packs.add(hit["pack"])
            pack = next((p for p in packs if p["name"] == hit["pack"]), None)
            fields = _extract_fields(text, pack, hit["object_type"]) if pack else {}
            captures.append(
                {
                    "domain": hit["pack"],
                    "object_type": hit["object_type"],
                    "operation": hit.get("operation") or "create",
                    "span": text,
                    "confidence": 0.8,
                    "fields": fields,
                    "links": [],
                }
            )

    # Cross-domain links when 2+ domains
    domains = {c["domain"] for c in captures}
    if len(domains) >= 2:
        ordered = list(captures)
        for i in range(len(ordered) - 1):
            ordered[i].setdefault("links", []).append(
                {
                    "to_domain": ordered[i + 1]["domain"],
                    "relation": "co_occurred_with",
                }
            )

    unmatched = None
    if not captures:
        unmatched = text

    return {
        "captures": captures,
        "unmatched_text": unmatched,
        "needs_clarification": False,
        "clarifying_question": None,
    }


def _split_clauses(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!;])\s+|\s+\band\b\s+|;\s+", text.strip(), flags=re.IGNORECASE)
    parts = [p.strip() for p in parts if p and p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def _extract_fields(text: str, pack: dict[str, Any] | None, object_type: str | None) -> dict[str, Any]:
    """Back-compat: schema fields only. Residue is attached on CaptureSpan."""
    from domain_foundry_core.extract import extract_fields

    fields, _residue = extract_fields(text, pack, object_type)
    return fields


def _usage_from_openai(payload: dict[str, Any], *, model: str, tier: str | None) -> TokenUsage:
    usage = payload.get("usage") or {}
    return TokenUsage(
        input_tokens=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
        output_tokens=int(
            usage.get("completion_tokens") or usage.get("output_tokens") or 0
        ),
        model=model,
        tier=tier,
        provider="openai_compatible",
    )


def _usage_from_anthropic(payload: dict[str, Any], *, model: str, tier: str | None) -> TokenUsage:
    usage = payload.get("usage") or {}
    return TokenUsage(
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        model=model,
        tier=tier,
        provider="anthropic",
    )


class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        default_model: str | None = None,
        default_tier: str = "routine",
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get("DOMAIN_FOUNDRY_LLM_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self.api_key = (
            api_key
            or os.environ.get("DOMAIN_FOUNDRY_LLM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        self.default_model = (
            default_model
            or os.environ.get("DOMAIN_FOUNDRY_LLM_MODEL")
            or "gpt-5.6-luna"
        )
        self.default_tier = default_tier
        # Reasoners and design calls routinely exceed 60s; a short timeout
        # looks like "the model couldn't design" and falls back to a scaffold.
        self.timeout = 180.0 if default_tier == "sota" else 60.0

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        model: str | None = None,
        tier: str | None = None,
    ) -> CompletionResult:
        if not self.api_key:
            raise LLMError("no API key configured")
        model = model or self.default_model
        resolved_tier = tier or self.default_tier
        deepseek_api = is_deepseek_base(self.base_url)
        system_role = "developer" if is_openai_base(self.base_url) else "system"
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": system_role, "content": system},
                {"role": "user", "content": user},
            ],
        }
        if deepseek_api:
            # V4 defaults to thinking. Keep the high-volume path fast and make
            # the stronger design/correction tier's intent explicit.
            body["thinking"] = {
                "type": "disabled" if resolved_tier == "routine" else "enabled"
            }
            if resolved_tier == "sota":
                body["reasoning_effort"] = "high"

        if schema and not deepseek_api:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "route", "schema": schema, "strict": False},
            }
        else:
            body["response_format"] = {"type": "json_object"}

        try:
            r = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
                timeout=self.timeout,
            )
            r.raise_for_status()
            payload = r.json()
            content = payload["choices"][0]["message"]["content"]
            return CompletionResult(
                data=_parse_json_content(content),
                usage=_usage_from_openai(payload, model=model, tier=resolved_tier),
            )
        except Exception as first:
            # prompted-JSON fallback + retry once
            body.pop("response_format", None)
            body["messages"] = [
                {
                    "role": system_role,
                    "content": system + "\nRespond with a single JSON object only.",
                },
                {"role": "user", "content": user},
            ]
            try:
                r = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=body,
                    timeout=self.timeout,
                )
                r.raise_for_status()
                payload = r.json()
                content = payload["choices"][0]["message"]["content"]
                return CompletionResult(
                    data=_parse_json_content(content),
                    usage=_usage_from_openai(payload, model=model, tier=resolved_tier),
                )
            except Exception as second:
                raise LLMError(f"LLM failed: {first}; retry: {second}") from second


class AnthropicProvider(LLMProvider):
    """Claude via Anthropic Messages API (sota tier)."""

    name = "anthropic"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        default_model: str | None = None,
        effort: str | None = None,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get("DOMAIN_FOUNDRY_SOTA_BASE_URL")
            or DEFAULT_SOTA_BASE_URL
        ).rstrip("/")
        self.api_key = (
            api_key
            or os.environ.get("DOMAIN_FOUNDRY_SOTA_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
        )
        self.default_model = (
            default_model
            or os.environ.get("DOMAIN_FOUNDRY_SOTA_MODEL")
            or DEFAULT_SOTA_MODEL
        )
        # Sota calls are important but small — a routing decision or a
        # correction, not long-horizon work. Medium is the balance point on
        # current models; override for a harder or cheaper posture.
        self.effort = (
            effort or os.environ.get("DOMAIN_FOUNDRY_SOTA_EFFORT") or "medium"
        ).strip().lower()

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        model: str | None = None,
        tier: str | None = None,
    ) -> CompletionResult:
        if not self.api_key:
            raise LLMError("no Anthropic API key configured")
        model = model or self.default_model
        resolved_tier = tier or "sota"
        # Ask for JSON explicitly; Anthropic has no response_format=json_object
        # equivalent for all models — prompt + parse is the portable path.
        sys = system
        if schema:
            sys = (
                system
                + "\nRespond with a single JSON object matching this schema:\n"
                + json.dumps(schema)
            )
        else:
            sys = system + "\nRespond with a single JSON object only."

        # Current Claude models REJECT temperature/top_p/top_k with HTTP 400,
        # and only some accept output_config.effort. Sending an unsupported
        # parameter is a hard failure, and the router catches LLM failures into
        # the keyword heuristic — so a wrong shape here does not look like an
        # error, it looks like "the user set no key". Resolve the shape up front.
        caps = anthropic_request_caps(model)
        base_body: dict[str, Any] = {
            "model": model,
            # Thinking is on by default on current models and shares this budget
            # with the response, so size it for both.
            "max_tokens": _ANTHROPIC_MAX_TOKENS,
            "system": sys,
            "messages": [{"role": "user", "content": user}],
        }
        body = dict(base_body)
        if not caps.rejects_sampling_params:
            body["temperature"] = 0
        if caps.supports_effort:
            body["output_config"] = {"effort": self.effort}

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        def _post(payload_body: dict[str, Any]) -> CompletionResult:
            r = httpx.post(
                f"{self.base_url}/v1/messages",
                headers=headers,
                json=payload_body,
                timeout=90.0,
            )
            r.raise_for_status()
            payload = r.json()
            # A safety classifier can decline with HTTP 200 and no content;
            # surface that as an error rather than an empty-JSON parse failure.
            if payload.get("stop_reason") == "refusal":
                raise LLMError("Anthropic declined the request (stop_reason=refusal)")
            content = _anthropic_text(payload)
            return CompletionResult(
                data=_parse_json_content(content),
                usage=_usage_from_anthropic(payload, model=model, tier=resolved_tier),
            )

        try:
            return _post(body)
        except Exception as first:
            # Retry with the minimal body only on 400 — a rejected *parameter*.
            # Under BYO the user can point a tier at a model newer or older than
            # the capability table knows, so a shape rejection should degrade
            # rather than fail the capture. Anything else (401 auth, 429 rate
            # limit, 5xx) is not fixed by dropping optional params, and retrying
            # it just doubles the latency and the noise in the error.
            shape_rejected = (
                isinstance(first, httpx.HTTPStatusError)
                and first.response.status_code == 400
            )
            if shape_rejected and body != base_body:
                try:
                    return _post(base_body)
                except Exception as second:
                    raise LLMError(
                        f"Anthropic LLM failed: {_brief(first)}; "
                        f"minimal retry: {_brief(second)}"
                    ) from second
            raise LLMError(f"Anthropic LLM failed: {_brief(first)}") from first


def _brief(exc: BaseException) -> str:
    """One-line error text.

    httpx bakes a multi-line MDN link into HTTPStatusError, which turns a single
    failed probe into a wall of text. Keep the status and the API's own message,
    drop the tutorial.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        detail = ""
        try:
            payload = exc.response.json()
            if isinstance(payload, dict):
                err = payload.get("error")
                if isinstance(err, dict) and err.get("message"):
                    detail = f": {err['message']}"
        except Exception:  # noqa: BLE001 - body may be empty or not JSON
            detail = ""
        return f"HTTP {exc.response.status_code}{detail}"
    text = str(exc).strip().splitlines()
    return text[0] if text else type(exc).__name__


def _anthropic_text(payload: dict[str, Any]) -> str:
    blocks = payload.get("content") or []
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
        elif isinstance(block, str):
            parts.append(block)
    return "\n".join(parts)


class TieredLLMProvider(LLMProvider):
    """Routes complete_json calls to routine (DeepSeek) or sota (Claude) backends."""

    name = "tiered"

    def __init__(
        self,
        *,
        routine: LLMProvider | None = None,
        sota: LLMProvider | None = None,
        routine_model: str | None = None,
        sota_model: str | None = None,
        home: Path | None = None,
    ) -> None:
        # Resolve both tiers through the BYO merge (env > config > registry) so
        # a model chosen at setup is honoured, not just one exported in the env.
        cfg = load_llm_config(home)
        routine_settings = resolve_tier_settings("routine", config=cfg)
        sota_settings = resolve_tier_settings("sota", config=cfg)
        if routine_model:
            routine_settings = replace(routine_settings, model=routine_model)
        if sota_model:
            sota_settings = replace(sota_settings, model=sota_model)

        self.routine_model = routine_settings.model or DEFAULT_ROUTINE_MODEL
        self.sota_model = sota_settings.model or DEFAULT_SOTA_MODEL
        self.routine = routine or _build_tier_provider("routine", routine_settings)
        self.sota = sota or _build_tier_provider("sota", sota_settings)

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        model: str | None = None,
        tier: str | None = None,
    ) -> CompletionResult:
        resolved = (tier or "routine").lower()
        if resolved not in {"routine", "sota"}:
            resolved = "routine"
        provider, default_model = self._provider_for(resolved)
        result = provider.complete_json(
            system=system,
            user=user,
            schema=schema,
            model=model or default_model,
            tier=resolved,
        )
        result.usage.tier = resolved
        if not result.usage.model:
            result.usage.model = model or default_model
        if not result.usage.provider:
            result.usage.provider = getattr(provider, "name", self.name)
        return result

    def _provider_for(self, resolved: str) -> tuple[LLMProvider, str]:
        """Pick the backend for a tier, degrading across tiers before heuristic.

        Most single-key setups (the documented OpenRouter recipe, a local
        gateway) configure only the routine tier. ``_select_tier`` sends every
        no-match capture to ``sota``, so without this a fully-configured user
        would still get heuristic routing on exactly the captures that need a
        model. Prefer the requested tier; fall back to whichever tier is live.
        """
        want, other = (
            ((self.sota, self.sota_model), (self.routine, self.routine_model))
            if resolved == "sota"
            else ((self.routine, self.routine_model), (self.sota, self.sota_model))
        )
        if _is_live(want[0]) or not _is_live(other[0]):
            return want
        return other

    def has_live_keys(self) -> bool:
        return _is_live(self.routine) or _is_live(self.sota)


def _env(name: str) -> str | None:
    raw = os.environ.get(name)
    return raw.strip() or None if raw else None


def resolve_tier_settings(
    tier: str,
    *,
    home: Path | None = None,
    config: LLMConfig | None = None,
) -> TierSettings:
    """Merge env > config file > provider-registry default for one tier.

    This is the single place BYO settings are resolved. Environment variables
    keep absolute precedence so an install that predates the config file — or a
    CI job that exports vars — behaves exactly as it did before.
    """
    cfg = config if config is not None else load_llm_config(home)
    tier_key = "sota" if tier == "sota" else "routine"
    cfg_tier = cfg.sota if tier_key == "sota" else cfg.routine
    spec = get_provider(cfg.provider)
    prefix = f"DOMAIN_FOUNDRY_{tier_key.upper()}"

    default_model = DEFAULT_SOTA_MODEL if tier_key == "sota" else DEFAULT_ROUTINE_MODEL
    spec_model = None
    if spec is not None:
        spec_model = spec.sota_model if tier_key == "sota" else spec.routine_model
    model = (
        _env(f"{prefix}_MODEL")
        or cfg_tier.model
        or spec_model
        # The legacy single-endpoint var only ever steered the routine side.
        or (_env("DOMAIN_FOUNDRY_LLM_MODEL") if tier_key == "routine" else None)
        or default_model
    )

    default_base = (
        DEFAULT_SOTA_BASE_URL if tier_key == "sota" else DEFAULT_ROUTINE_BASE_URL
    )
    base_url = (
        _env(f"{prefix}_BASE_URL")
        or (_env("DOMAIN_FOUNDRY_LLM_BASE_URL") if tier_key == "routine" else None)
        or cfg_tier.base_url
        or (spec.base_url if spec is not None else None)
        or default_base
    )

    # Key: tier-specific var, then the provider's conventional vars, then the
    # legacy per-tier vars, then whatever env var the config file names, and
    # only last the key stored inline in the config file.
    candidates: list[str] = [f"{prefix}_API_KEY"]
    if spec is not None:
        candidates += [e for e in spec.api_key_envs if e not in candidates]
    candidates += [
        e for e in _LEGACY_KEY_ENVS.get(tier_key, ()) if e not in candidates
    ]
    if cfg_tier.api_key_env and cfg_tier.api_key_env not in candidates:
        candidates.append(cfg_tier.api_key_env)
    api_key = next((v for v in (_env(name) for name in candidates) if v), None)
    api_key = api_key or cfg_tier.api_key

    return TierSettings(
        model=model,
        base_url=base_url,
        api_key_env=cfg_tier.api_key_env,
        api_key=api_key,
    )


def _build_tier_provider(tier: str, settings: TierSettings) -> LLMProvider:
    """Build the client for a tier, or the heuristic when it has no key."""
    if not settings.api_key:
        return HeuristicProvider()
    base = settings.base_url or (
        DEFAULT_SOTA_BASE_URL if tier == "sota" else DEFAULT_ROUTINE_BASE_URL
    )
    model = settings.model or (
        DEFAULT_SOTA_MODEL if tier == "sota" else DEFAULT_ROUTINE_MODEL
    )
    if is_anthropic_base(base):
        return AnthropicProvider(
            base_url=base, api_key=settings.api_key, default_model=model
        )
    # Anything that is not an Anthropic host speaks the OpenAI-compatible shape.
    # This is what makes "point the sota tier at OpenRouter" work instead of
    # POSTing {base}/v1/messages and 404ing.
    return OpenAICompatibleProvider(
        base_url=base,
        api_key=settings.api_key,
        default_model=model,
        default_tier=tier,
    )


def _build_routine_provider(model: str) -> LLMProvider:
    settings = resolve_tier_settings("routine")
    if model:
        settings = TierSettings(
            model=model,
            base_url=settings.base_url,
            api_key_env=settings.api_key_env,
            api_key=settings.api_key,
        )
    return _build_tier_provider("routine", settings)


def _is_live(provider: LLMProvider) -> bool:
    """A provider that can actually reach a model (configured, not heuristic)."""
    return not isinstance(provider, HeuristicProvider) and bool(
        getattr(provider, "api_key", None)
    )


def _is_anthropic_base(base_url: str) -> bool:
    """Back-compat alias for :func:`providers.is_anthropic_base`."""
    return is_anthropic_base(base_url)


def _build_sota_provider(model: str) -> LLMProvider:
    settings = resolve_tier_settings("sota")
    if model:
        settings = TierSettings(
            model=model,
            base_url=settings.base_url,
            api_key_env=settings.api_key_env,
            api_key=settings.api_key,
        )
    return _build_tier_provider("sota", settings)


def select_model_tier(
    *,
    l1_confidence: float,
    l1_reason: str,
    text: str,
    rule_tiers: list[str | None] | None = None,
    structural: bool = False,
) -> ModelTier:
    """Choose routine vs sota for an L2 interpretation call.

    Escalates to sota when:
    - any matching routing rule declares ``tier: sota``
    - low L1 confidence / no_match / multi_pack
    - correction-like text
    - structural / schema-affecting operations flagged by the caller
    """
    for t in rule_tiers or []:
        if t and str(t).lower() == "sota":
            return "sota"
    if structural:
        return "sota"
    if _looks_like_correction(text):
        return "sota"
    if l1_reason in {"no_match", "multi_pack"}:
        return "sota"
    if l1_confidence < 0.7:
        return "sota"
    return "routine"


_CORRECTION_RE = re.compile(
    r"\b(no,?\s+that|actually|undo|should (?:be|have been)|not\s+\d+|wrong|correct(?:ion)?)\b",
    re.IGNORECASE,
)


def _looks_like_correction(text: str) -> bool:
    return bool(_CORRECTION_RE.search(text or ""))


class CassetteProvider(LLMProvider):
    """Wraps an inner provider with prompt-hash cassette store."""

    name = "cassette"

    def __init__(
        self,
        inner: LLMProvider,
        store_dir: Path,
        *,
        mode: str = "replay",  # replay | record | live
    ) -> None:
        self.inner = inner
        self.store_dir = store_dir
        self.mode = mode
        self.store_dir.mkdir(parents=True, exist_ok=True)
        # Observability for the eval gate + nightly drift report.
        self.hits: int = 0
        self.misses: int = 0
        self.recorded: int = 0
        self.drift: list[dict[str, Any]] = []

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        model: str | None = None,
        tier: str | None = None,
    ) -> CompletionResult:
        key = _prompt_hash(system, user, schema, tier=tier, model=model)
        path = self.store_dir / f"{key}.json"
        cached_data: dict[str, Any] | None = None
        cached_usage: TokenUsage | None = None
        if path.exists():
            blob = json.loads(path.read_text(encoding="utf-8"))
            cached_data = blob.get("response")
            if isinstance(blob.get("usage"), dict):
                u = blob["usage"]
                cached_usage = TokenUsage(
                    input_tokens=int(u.get("input_tokens") or 0),
                    output_tokens=int(u.get("output_tokens") or 0),
                    model=u.get("model") or model,
                    tier=u.get("tier") or tier,
                    provider=u.get("provider"),
                )

        # Pure replay: serve from cassette when present.
        if self.mode == "replay" and cached_data is not None:
            self.hits += 1
            return CompletionResult(
                data=cached_data,
                usage=cached_usage
                or TokenUsage(model=model, tier=tier, provider="cassette"),
            )

        self.misses += 1
        result = self.inner.complete_json(
            system=system, user=user, schema=schema, model=model, tier=tier
        )
        if self.mode in {"record", "live"}:
            # Drift detection: a live re-record whose response differs from the
            # committed cassette is a signal the pinned model has moved.
            if self.mode == "live" and cached_data is not None and cached_data != result.data:
                self.drift.append(
                    {
                        "key": key,
                        "user": _normalize(user)[:200],
                        "recorded": cached_data,
                        "live": result.data,
                    }
                )
            path.write_text(
                json.dumps(
                    {
                        "system": system,
                        "user": user,
                        "response": result.data,
                        "usage": {
                            "input_tokens": result.usage.input_tokens,
                            "output_tokens": result.usage.output_tokens,
                            "model": result.usage.model,
                            "tier": result.usage.tier,
                            "provider": result.usage.provider,
                        },
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.recorded += 1
        return result

    def drift_report(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "hits": self.hits,
            "misses": self.misses,
            "recorded": self.recorded,
            "drift_count": len(self.drift),
            "drift": self.drift,
        }


def _prompt_hash(
    system: str,
    user: str,
    schema: dict[str, Any] | None,
    *,
    tier: str | None = None,
    model: str | None = None,
) -> str:
    payload = json.dumps(
        {
            "system": _normalize(system),
            "user": _normalize(user),
            "schema": schema,
            "tier": tier,
            "model": model,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _parse_json_content(content: str) -> dict[str, Any]:
    content = (content or "").strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            raise
        return json.loads(m.group(0))


def is_heuristic_provider(llm: LLMProvider) -> bool:
    if isinstance(llm, HeuristicProvider):
        return True
    if isinstance(llm, CassetteProvider) and isinstance(llm.inner, HeuristicProvider):
        return True
    if isinstance(llm, TieredLLMProvider):
        return not llm.has_live_keys()
    if isinstance(llm, CassetteProvider) and isinstance(llm.inner, TieredLLMProvider):
        return not llm.inner.has_live_keys()
    return False


def build_eval_provider(
    cassette_dir: Path, *, live_llm: bool = False
) -> CassetteProvider:
    """Provider for the eval runner.

    Default (CI/PR): cassette *replay* over a deterministic heuristic inner, so
    the corpus is free and reproducible. ``live_llm=True`` (nightly) wraps the
    real tiered API provider and re-records in ``live`` mode, surfacing drift vs
    the committed cassettes. Falls back to the heuristic when no API key is
    present so the nightly job degrades gracefully instead of hard-failing.
    """
    if live_llm:
        real = build_tiered_provider()
        inner: LLMProvider = real if real.has_live_keys() else HeuristicProvider()
        mode = "live" if real.has_live_keys() else "replay"
    else:
        inner = HeuristicProvider()
        mode = "replay"
    return CassetteProvider(inner, cassette_dir, mode=mode)


def build_tiered_provider(home: Path | None = None) -> TieredLLMProvider:
    return TieredLLMProvider(home=home)


_LIVE_MODES = {"live", "tiered", "1", "true", "on"}
_OFF_MODES = {"off", "heuristic", "0", "false"}


def resolve_llm_mode(home: Path | None = None, *, config: LLMConfig | None = None) -> str:
    """Decide live vs heuristic: env ``DOMAIN_FOUNDRY_LLM``, else config, else off.

    Without the config leg, completing ``setup`` — key and all — would change
    nothing: every capture would still route on keyword rules until the user
    separately exported ``DOMAIN_FOUNDRY_LLM=live``. A setup flow that writes a
    file nothing reads is worse than no setup flow.
    """
    env_mode = _env("DOMAIN_FOUNDRY_LLM")
    if env_mode:
        return env_mode.lower()
    cfg = config if config is not None else load_llm_config(home)
    if cfg.mode:
        return cfg.mode.lower()
    return "heuristic"


def get_default_provider(
    *, cassette_dir: Path | None = None, home: Path | None = None
) -> LLMProvider:
    cfg = load_llm_config(home)
    mode = resolve_llm_mode(home, config=cfg)
    if mode in _OFF_MODES:
        inner: LLMProvider = HeuristicProvider()
    elif mode in _LIVE_MODES:
        tiered = build_tiered_provider(home)
        inner = tiered if tiered.has_live_keys() else HeuristicProvider()
    else:
        # Legacy single OpenAI-compatible endpoint
        inner = OpenAICompatibleProvider()
        if not inner.api_key:
            inner = HeuristicProvider()
    if cassette_dir is not None:
        cassette_mode = os.environ.get("DOMAIN_FOUNDRY_CASSETTE", "replay")
        return CassetteProvider(inner, cassette_dir, mode=cassette_mode)
    return inner
