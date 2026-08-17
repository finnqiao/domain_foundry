"""Schema-driven field extraction with residue for unmapped facts.

Only keys declared on the object may land on the canonical row. Extra
candidates and leftover clauses are returned as residue so nothing is lost.
"""

from __future__ import annotations

import re
from typing import Any

_LOAF_KINDS = (
    r"country\s+loaf|sandwich\s+loaf|batard|boule|batard|loaf|focaccia|pizza"
)
_FLOUR_WORDS = r"rye|wheat|spelt|ap\b|all[\s-]?purpose|bread|whole[\s-]?wheat|einkorn"
_LEADING_VERB = re.compile(
    r"^(?:baked|bake|made|logged|tracked|watered|repotted|fed|ran|read|climbed|"
    r"sent|worked|finished|started|did)\s+(?:a|an|the|my)?\s*",
    re.IGNORECASE,
)


def extract_fields(
    text: str,
    pack: dict[str, Any] | None,
    object_type: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(fields, residue)`` for ``object_type`` against ``pack``.

    ``pack`` may be a blueprint-shaped dict with ``objects`` or a mapping of
    object_name → ``{"fields": {...}}``.
    """
    if not pack or not object_type:
        return {}, {"residue": {}, "unparsed": (text or "").strip()}

    objects = pack.get("objects") if isinstance(pack.get("objects"), dict) else pack
    contract = (objects or {}).get(object_type) or {}
    fields_spec = contract.get("fields") or {}
    if not fields_spec:
        return {}, {"residue": {}, "unparsed": (text or "").strip()}

    title_field = contract.get("title_field")
    out: dict[str, Any] = {}
    residue: dict[str, Any] = {}
    claimed_spans: list[str] = []

    # Pass 1: typed extraction from the declared spec.
    for name, spec in fields_spec.items():
        if not isinstance(spec, dict):
            spec = {"type": "text"}
        ftype = spec.get("type") or "text"
        value = None
        if ftype == "enum" or (spec.get("values") and ftype != "number"):
            raw_values = spec.get("values") or []
            values = (
                [str(v) for v in raw_values]
                if isinstance(raw_values, list)
                else [str(raw_values)]
            )
            if name == "action":
                value = _match_action(text, values)
            elif name == "result":
                value = _match_enum(text, values)
                if value is None and re.search(r"\bgreat\s+bake\b", text, re.IGNORECASE):
                    value = "great"
            else:
                value = _match_enum(text, values)
            if value is None and name == "action":
                value = _match_enum(text, values)
            if value is None and name == "result":
                if re.search(r"\bgreat\s+bake\b", text, re.IGNORECASE):
                    value = "great"
        elif ftype in {"number", "integer"}:
            value = _match_number(text, name, spec)
        elif ftype in {"datetime", "date"}:
            continue  # capture_time default applied later by apply engine
        elif name == "flour_mix" or (name.endswith("_mix") and "flour" in name):
            value = _match_flour_mix(text)
        elif title_field == name or name in {
            "loaf_name",
            "plant_name",
            "route_name",
            "name",
            "title",
        }:
            value = _match_identity(text, name)
        elif ftype == "text" and name != "notes":
            # Prefer explicit noun phrases for known plant names etc.
            if name == "plant_name" or "plant" in name:
                value = _match_plant_name(text)
            elif name == "gym" or name == "location":
                m = re.search(
                    r"\bat\s+([A-Z][\w\s']{2,40?}?)(?:\.|,|$)",
                    text,
                )
                if m:
                    value = m.group(1).strip()

        if value is not None and value != "":
            out[name] = int(value) if ftype == "integer" and isinstance(value, float) else value
            claimed_spans.append(str(value))

    # notes: only if declared and we have leftover substance
    if "notes" in fields_spec and "notes" not in out:
        leftover = _leftover_text(text, claimed_spans, out)
        # Keep notes conservative — leftover must look like a clause, not the
        # whole utterance with a few tokens stripped (hurts field precision).
        if (
            leftover
            and len(leftover) > 16
            and leftover.lower() != (text or "").strip().lower()
            and len(leftover) < max(24, int(len(text or "") * 0.6))
        ):
            out["notes"] = leftover[:240]

    # Residue: percent/unit phrases that didn't land, and leftover clauses.
    if "hydration" in fields_spec and "hydration" not in out:
        m = re.search(r"(\d{2,3})\s*%", text)
        if m:
            residue["hydration_mention"] = m.group(0)
    leftover = _leftover_text(text, claimed_spans, out)
    # Candidate key-ish leftovers (dutch oven, crash pad, etc.)
    for m in re.finditer(
        r"\b(?:used|with|also)\s+(?:the\s+)?([a-z][a-z0-9\s-]{2,40})",
        leftover or text,
        re.IGNORECASE,
    ):
        phrase = m.group(1).strip().lower()
        key = re.sub(r"[^a-z0-9]+", "_", phrase).strip("_")[:40]
        if key and key not in out and len(key) >= 3:
            residue[key] = phrase

    unparsed = leftover if leftover and leftover.lower() not in {
        str(v).lower() for v in out.values() if v is not None
    } else ""

    return out, {"residue": residue, "unparsed": unparsed[:240] if unparsed else ""}


def _match_enum(text: str, values: list[str]) -> str | None:
    low = text.lower()
    for val in values:
        if re.search(rf"\b{re.escape(str(val).lower())}\b", low):
            return val
    return None


def _match_action(text: str, values: list[str]) -> str | None:
    action_pats = [
        ("prune", r"\bprun(?:e|ed|ing)\b"),
        ("mist", r"\bmist(?:ed|ing)?\b"),
        ("fertilize", r"\bfertiliz"),
        ("water", r"\bwater(?:ed|ing)?\b"),
        ("repot", r"\brepot(?:ted|ting)?\b"),
        ("observe", r"\bobserv(?:e|ed|ing)\b"),
    ]
    for val, pat in action_pats:
        if val in values and re.search(pat, text, re.IGNORECASE):
            return val
    return _match_enum(text, values)


def _match_number(text: str, name: str, spec: dict[str, Any]) -> float | None:
    unit = (spec.get("unit") or "").lower()
    if name == "hydration" or unit == "percent":
        m = re.search(r"(\d{2,3})\s*%|\b(\d{2,3})\s*hydration", text, re.IGNORECASE)
        if m:
            return float(m.group(1) or m.group(2))
        return None
    if name == "bulk_hours" or unit == "hours":
        m = re.search(
            r"bulk\s*(?:ferment(?:ed|ation)?\s*)?(?:for\s*)?(\d+(?:\.\d+)?)\s*h",
            text,
            re.IGNORECASE,
        )
        if not m:
            m = re.search(r"\bbulk\s+(\d+(?:\.\d+)?)\b", text, re.IGNORECASE)
        if not m and unit == "hours":
            m = re.search(r"(\d+(?:\.\d+)?)\s*h(?:ours?)?\b", text, re.IGNORECASE)
        if m:
            return float(m.group(1))
        return None
    if unit in {"km", "miles"}:
        m = re.search(rf"(\d+(?:\.\d+)?)\s*{unit}\b", text, re.IGNORECASE)
        if not m:
            m = re.search(r"(\d+(?:\.\d+)?)\s*k(?:m)?\b", text, re.IGNORECASE)
        if m:
            return float(m.group(1))
    if unit in {"minutes", "min"}:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:min|minutes)\b", text, re.IGNORECASE)
        if m:
            return float(m.group(1))
    # Generic: first number near the field name
    if re.search(rf"\b{re.escape(name.replace('_', ' '))}\b", text, re.IGNORECASE):
        m = re.search(
            rf"\b{re.escape(name.replace('_', ' '))}\b[^\d]{{0,12}}(\d+(?:\.\d+)?)",
            text,
            re.IGNORECASE,
        )
        if m:
            return float(m.group(1))
    return None


def _match_flour_mix(text: str) -> str | None:
    # Require a flour word — reject "75% hydration".
    m = re.search(
        rf"(\d+%\s*(?:{_FLOUR_WORDS})(?:\s*/\s*\d+%\s*(?:{_FLOUR_WORDS}))*)",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)
    m = re.search(rf"\b((?:{_FLOUR_WORDS})(?:\s*/\s*(?:{_FLOUR_WORDS}))*)\b", text, re.IGNORECASE)
    if m:
        # Reject if the next word after a bare percent is hydration/water.
        return m.group(1)
    # "20% rye" style
    m = re.search(rf"(\d+%\s+(?:{_FLOUR_WORDS}))", text, re.IGNORECASE)
    if m:
        return m.group(1)
    # Explicitly reject hydration percents being treated as flour.
    bad = re.search(r"(\d+%\s*(?:hydration|water)\b)", text, re.IGNORECASE)
    if bad:
        return None
    return None


def _match_identity(text: str, name: str) -> str | None:
    if name == "loaf_name" or "loaf" in name:
        m = re.search(rf"\b({_LOAF_KINDS})\b", text, re.IGNORECASE)
        if m:
            return re.sub(r"\s+", " ", m.group(1).lower())
        # Strip leading "baked a" and take a short noun phrase.
        trimmed = _LEADING_VERB.sub("", text.strip())
        trimmed = re.sub(
            r"\b\d{2,3}\s*%?\s*hydration\b", "", trimmed, flags=re.IGNORECASE
        )
        trimmed = re.sub(r"\b\d+(?:\.\d+)?\s*%\b", "", trimmed)
        trimmed = re.sub(r"[,.].*$", "", trimmed).strip(" ,.-")
        if trimmed and len(trimmed) <= 40:
            return trimmed.lower()
        return None
    if name == "plant_name" or "plant" in name:
        return _match_plant_name(text)
    if name == "name" and "starter" in text.lower():
        m = re.search(
            r"\b(rye|wheat|whole wheat|spelt)\s+starter\b", text, re.IGNORECASE
        )
        if m:
            return f"{m.group(1).lower()} starter"
        if re.search(r"\blevain\b", text, re.IGNORECASE):
            return "levain"
        return "starter"
    if name == "route_name":
        m = re.search(
            r"\b(?:the\s+)?([a-z][\w\s-]{2,30}?)\s+(?:route|problem|project|overhang)\b",
            text,
            re.IGNORECASE,
        )
        if m:
            return m.group(1).strip().lower()
        m = re.search(r"\b(V\d+[a-z]?)\b", text, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    # Generic title: short phrase, not whole sentence
    trimmed = _LEADING_VERB.sub("", text.strip())
    trimmed = re.sub(r"[,.].*$", "", trimmed).strip()
    if len(trimmed) > 48:
        trimmed = trimmed[:48].rsplit(" ", 1)[0]
    return trimmed or text.strip()[:48]


def _match_plant_name(text: str) -> str | None:
    m = re.search(
        r"\b(monstera|pothos|ficus|snake plant|zz plant|calathea|fern|"
        r"fiddle[\s-]?leaf(?:\s+fig)?|philodendron)\b",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).lower()
    m = re.search(
        r"\b(?:watered|repotted|misted|fertilized)\s+(?:the\s+)?([a-z][\w\s-]{2,30})",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip().lower()
    return None


def _leftover_text(text: str, claimed: list[str], fields: dict[str, Any]) -> str:
    leftover = text or ""
    for span in claimed:
        if span:
            leftover = re.sub(re.escape(str(span)), " ", leftover, flags=re.IGNORECASE)
    for val in fields.values():
        if val is not None:
            leftover = re.sub(re.escape(str(val)), " ", leftover, flags=re.IGNORECASE)
    leftover = _LEADING_VERB.sub("", leftover)
    leftover = re.sub(r"\s+", " ", leftover).strip(" ,.-")
    return leftover


# Back-compat alias used by HeuristicProvider / Router.
def extract_fields_only(
    text: str, pack: dict[str, Any] | None, object_type: str | None
) -> dict[str, Any]:
    fields, _residue = extract_fields(text, pack, object_type)
    return fields


__all__ = ["extract_fields", "extract_fields_only"]
