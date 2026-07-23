"""LLM provider abstraction with cassette record/replay and model tiers.

Tiers (Phase 1):
  routine → deepseek-chat (OpenAI-compatible)
  sota    → Claude via Anthropic Messages API
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx

ModelTier = Literal["routine", "sota"]

DEFAULT_ROUTINE_MODEL = "deepseek-chat"
DEFAULT_SOTA_MODEL = "claude-sonnet-4-6"
DEFAULT_ROUTINE_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_SOTA_BASE_URL = "https://api.anthropic.com"


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
                        score = 2 + int(10 * float(rule.get("confidence_boost") or 0))
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
    if not pack or not object_type:
        return {}
    contract = (pack.get("objects") or {}).get(object_type) or {}
    fields_spec = contract.get("fields") or {}
    out: dict[str, Any] = {}

    # hydration percent
    if "hydration" in fields_spec:
        m = re.search(r"(\d{2,3})\s*%|\b(\d{2,3})\s*hydration", text, re.IGNORECASE)
        if m:
            out["hydration"] = float(m.group(1) or m.group(2))

    if "bulk_hours" in fields_spec:
        m = re.search(
            r"bulk\s*(?:ferment(?:ed|ation)?\s*)?(?:for\s*)?(\d+(?:\.\d+)?)\s*h",
            text,
            re.IGNORECASE,
        )
        if not m:
            m = re.search(r"\bbulk\s+(\d+(?:\.\d+)?)\b", text, re.IGNORECASE)
        if m:
            out["bulk_hours"] = float(m.group(1))

    if "result" in fields_spec:
        for val in (fields_spec["result"].get("values") or []):
            if re.search(rf"\b{re.escape(val)}\b", text, re.IGNORECASE):
                out["result"] = val
                break
        if "result" not in out and re.search(r"\bgreat\s+bake\b", text, re.IGNORECASE):
            out["result"] = "great"

    if "loaf_name" in fields_spec or "title" in fields_spec:
        key = "loaf_name" if "loaf_name" in fields_spec else "title"
        # use short text as title
        out[key] = text.strip()[:80]

    if "plant_name" in fields_spec:
        m = re.search(
            r"\b(monstera|pothos|ficus|snake plant|zz plant|calathea|fern)\b",
            text,
            re.IGNORECASE,
        )
        if m:
            out["plant_name"] = m.group(1).lower()
        else:
            out["plant_name"] = text.strip()[:60]

    if "action" in fields_spec:
        action_pats = [
            ("prune", r"\bprun(?:e|ed|ing)\b"),
            ("mist", r"\bmist(?:ed|ing)?\b"),
            ("fertilize", r"\bfertiliz"),
            ("water", r"\bwater(?:ed|ing)?\b"),
            ("repot", r"\brepot(?:ted|ting)?\b"),
            ("observe", r"\bobserv(?:e|ed|ing)\b"),
        ]
        for val, pat in action_pats:
            if re.search(pat, text, re.IGNORECASE):
                out["action"] = val
                break
        if "action" not in out:
            for val in (fields_spec["action"].get("values") or []):
                if re.search(rf"\b{re.escape(val)}\b", text, re.IGNORECASE):
                    out["action"] = val
                    break

    if "flour_mix" in fields_spec:
        m = re.search(r"(\d+%\s*\w+(?:\s*/\s*\d+%\s*\w+)*)", text, re.IGNORECASE)
        if m:
            out["flour_mix"] = m.group(1)
        elif re.search(r"\brye\b", text, re.IGNORECASE):
            out["flour_mix"] = "rye"

    if "name" in fields_spec and "starter" in (object_type or ""):
        m = re.search(r"\b(rye|wheat|whole wheat|spelt)\s+starter\b", text, re.IGNORECASE)
        if m:
            out["name"] = f"{m.group(1).lower()} starter"

    if "notes" in fields_spec and "notes" not in out:
        out["notes"] = text.strip()

    return out


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
        default_model: str = "gpt-4o-mini",
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
            or "gpt-4o-mini"
        )
        self.default_tier = default_tier

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
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }
        if schema:
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
                timeout=60.0,
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
                    "role": "system",
                    "content": system + "\nRespond with a single JSON object only.",
                },
                {"role": "user", "content": user},
            ]
            try:
                r = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=body,
                    timeout=60.0,
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

        body: dict[str, Any] = {
            "model": model,
            "max_tokens": 4096,
            "temperature": 0,
            "system": sys,
            "messages": [{"role": "user", "content": user}],
        }
        try:
            r = httpx.post(
                f"{self.base_url}/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=body,
                timeout=90.0,
            )
            r.raise_for_status()
            payload = r.json()
            content = _anthropic_text(payload)
            return CompletionResult(
                data=_parse_json_content(content),
                usage=_usage_from_anthropic(payload, model=model, tier=resolved_tier),
            )
        except Exception as exc:
            raise LLMError(f"Anthropic LLM failed: {exc}") from exc


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
    ) -> None:
        self.routine_model = (
            routine_model
            or os.environ.get("DOMAIN_FOUNDRY_ROUTINE_MODEL")
            or DEFAULT_ROUTINE_MODEL
        )
        self.sota_model = (
            sota_model
            or os.environ.get("DOMAIN_FOUNDRY_SOTA_MODEL")
            or DEFAULT_SOTA_MODEL
        )
        self.routine = routine or _build_routine_provider(self.routine_model)
        self.sota = sota or _build_sota_provider(self.sota_model)

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
        provider = self.sota if resolved == "sota" else self.routine
        default_model = self.sota_model if resolved == "sota" else self.routine_model
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

    def has_live_keys(self) -> bool:
        live_routine = not isinstance(self.routine, HeuristicProvider) and bool(
            getattr(self.routine, "api_key", None)
        )
        live_sota = not isinstance(self.sota, HeuristicProvider) and bool(
            getattr(self.sota, "api_key", None)
        )
        return live_routine or live_sota


def _build_routine_provider(model: str) -> LLMProvider:
    key = (
        os.environ.get("DOMAIN_FOUNDRY_ROUTINE_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("DOMAIN_FOUNDRY_LLM_API_KEY")
    )
    base = (
        os.environ.get("DOMAIN_FOUNDRY_ROUTINE_BASE_URL")
        or os.environ.get("DOMAIN_FOUNDRY_LLM_BASE_URL")
        or DEFAULT_ROUTINE_BASE_URL
    )
    if not key:
        return HeuristicProvider()
    return OpenAICompatibleProvider(
        base_url=base,
        api_key=key,
        default_model=model,
        default_tier="routine",
    )


def _build_sota_provider(model: str) -> LLMProvider:
    key = (
        os.environ.get("DOMAIN_FOUNDRY_SOTA_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
    )
    if not key:
        return HeuristicProvider()
    return AnthropicProvider(api_key=key, default_model=model)


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


def build_tiered_provider() -> TieredLLMProvider:
    return TieredLLMProvider()


def get_default_provider(*, cassette_dir: Path | None = None) -> LLMProvider:
    mode = os.environ.get("DOMAIN_FOUNDRY_LLM", "heuristic").lower()
    if mode in {"off", "heuristic", "0", "false"}:
        inner: LLMProvider = HeuristicProvider()
    elif mode in {"live", "tiered", "1", "true", "on"}:
        tiered = build_tiered_provider()
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
