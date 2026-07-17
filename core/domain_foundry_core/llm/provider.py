"""LLM provider abstraction with cassette record/replay (P2 skeleton)."""

from __future__ import annotations

import hashlib
import json
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx


class LLMError(RuntimeError):
    pass


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
    ) -> dict[str, Any]:
        """Return parsed JSON object from the model."""


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
    ) -> dict[str, Any]:
        # The router passes structured context in the user message as JSON after a marker.
        marker = "CONTEXT_JSON:"
        if marker not in user:
            return {
                "captures": [],
                "unmatched_text": user,
                "needs_clarification": False,
                "clarifying_question": None,
            }
        ctx_raw = user.split(marker, 1)[1].strip()
        ctx = json.loads(ctx_raw)
        return _heuristic_interpret(ctx)


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


class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        default_model: str = "gpt-4o-mini",
    ) -> None:
        self.base_url = (base_url or os.environ.get("DOMAIN_FOUNDRY_LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key or os.environ.get("DOMAIN_FOUNDRY_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.default_model = default_model or os.environ.get("DOMAIN_FOUNDRY_LLM_MODEL") or "gpt-4o-mini"

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise LLMError("no API key configured")
        model = model or self.default_model
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
            content = r.json()["choices"][0]["message"]["content"]
            return _parse_json_content(content)
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
                content = r.json()["choices"][0]["message"]["content"]
                return _parse_json_content(content)
            except Exception as second:
                raise LLMError(f"LLM failed: {first}; retry: {second}") from second


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
    ) -> dict[str, Any]:
        key = _prompt_hash(system, user, schema)
        path = self.store_dir / f"{key}.json"
        cached: dict[str, Any] | None = None
        if path.exists():
            cached = json.loads(path.read_text(encoding="utf-8")).get("response")

        # Pure replay: serve from cassette when present.
        if self.mode == "replay" and cached is not None:
            self.hits += 1
            return cached

        self.misses += 1
        result = self.inner.complete_json(
            system=system, user=user, schema=schema, model=model
        )
        if self.mode in {"record", "live"}:
            # Drift detection: a live re-record whose response differs from the
            # committed cassette is a signal the pinned model has moved.
            if self.mode == "live" and cached is not None and cached != result:
                self.drift.append(
                    {
                        "key": key,
                        "user": _normalize(user)[:200],
                        "recorded": cached,
                        "live": result,
                    }
                )
            path.write_text(
                json.dumps(
                    {"system": system, "user": user, "response": result},
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


def _prompt_hash(system: str, user: str, schema: dict[str, Any] | None) -> str:
    payload = json.dumps(
        {"system": _normalize(system), "user": _normalize(user), "schema": schema},
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


def build_eval_provider(
    cassette_dir: Path, *, live_llm: bool = False
) -> CassetteProvider:
    """Provider for the eval runner.

    Default (CI/PR): cassette *replay* over a deterministic heuristic inner, so
    the corpus is free and reproducible. ``live_llm=True`` (nightly) wraps the
    real API provider and re-records in ``live`` mode, surfacing drift vs the
    committed cassettes. Falls back to the heuristic when no API key is present
    so the nightly job degrades gracefully instead of hard-failing.
    """
    if live_llm:
        real = OpenAICompatibleProvider()
        inner: LLMProvider = real if real.api_key else HeuristicProvider()
        mode = "live" if real.api_key else "replay"
    else:
        inner = HeuristicProvider()
        mode = "replay"
    return CassetteProvider(inner, cassette_dir, mode=mode)


def get_default_provider(*, cassette_dir: Path | None = None) -> LLMProvider:
    mode = os.environ.get("DOMAIN_FOUNDRY_LLM", "heuristic").lower()
    if mode in {"off", "heuristic", "0", "false"}:
        inner: LLMProvider = HeuristicProvider()
    else:
        inner = OpenAICompatibleProvider()
    if cassette_dir is not None:
        cassette_mode = os.environ.get("DOMAIN_FOUNDRY_CASSETTE", "replay")
        return CassetteProvider(inner, cassette_dir, mode=cassette_mode)
    return inner
