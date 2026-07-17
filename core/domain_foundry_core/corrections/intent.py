"""Correction intent detection + lightweight NL field patch parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

CORRECTION_INTENT_RE = re.compile(
    r"\b("
    r"actually|correction|correct(?:ed|ion)?|was wrong|were wrong|"
    r"should have been|should be|not\s+\S+\s+but|"
    r"undo(?:\s+that)?|merge\s+those|moved?\s+.+\s+from\s+.+\s+to|"
    r"that\s+\w+\s+was|was\s+\d+|not\s+\d+"
    r")\b",
    re.I,
)

UNDO_RE = re.compile(r"\bundo(\s+that|\s+last|\s+the\s+last)?\b", re.I)
MERGE_RE = re.compile(r"\bmerge\b", re.I)
MOVE_RE = re.compile(
    r"\b(?:move|should be under|belongs? (?:in|under)|re-?route)\b", re.I
)
MARK_WRONG_RE = re.compile(r"\b(wrong|incorrect|bad)\b.*\b(without|don't know|unsure)\b", re.I)

# "80% hydration not 75" / "was 80% not 75" / "hydration was 80 not 75"
HYDRATION_RE = re.compile(
    r"(?:hydration\s+)?(?:was\s+)?(\d+(?:\.\d+)?)\s*%?\s*(?:hydration\s+)?not\s+(\d+(?:\.\d+)?)",
    re.I,
)
FIELD_WAS_RE = re.compile(
    r"\b([a-z_][a-z0-9_]*)\s+was\s+(\d+(?:\.\d+)?%?|\w+)\s+not\s+(\d+(?:\.\d+)?%?|\w+)",
    re.I,
)
WAS_N_NOT_M = re.compile(
    r"\bwas\s+(\d+(?:\.\d+)?)\s*%?\s+not\s+(\d+(?:\.\d+)?)",
    re.I,
)


@dataclass
class ParsedCorrection:
    action: str  # amend | move | merge | undo | mark_wrong
    fields: dict[str, Any]
    target_domain: str | None = None
    reason_code: str = "user_correction"
    raw_text: str = ""


def has_correction_intent(text: str) -> bool:
    return bool(CORRECTION_INTENT_RE.search(text or ""))


def parse_correction_text(text: str) -> ParsedCorrection:
    text = (text or "").strip()
    if UNDO_RE.search(text):
        return ParsedCorrection(action="undo", fields={}, reason_code="undo", raw_text=text)
    if MARK_WRONG_RE.search(text):
        return ParsedCorrection(
            action="mark_wrong", fields={}, reason_code="mark_wrong", raw_text=text
        )
    if MERGE_RE.search(text):
        return ParsedCorrection(action="merge", fields={}, reason_code="merge", raw_text=text)
    if MOVE_RE.search(text):
        # crude domain extract: "under travel" / "to plants"
        m = re.search(r"\b(?:under|to|into)\s+([a-z][a-z0-9_]*)\b", text, re.I)
        return ParsedCorrection(
            action="move",
            fields={},
            target_domain=m.group(1).lower() if m else None,
            reason_code="move",
            raw_text=text,
        )

    fields: dict[str, Any] = {}
    m = HYDRATION_RE.search(text)
    if m:
        fields["hydration"] = float(m.group(1))
    m2 = FIELD_WAS_RE.search(text)
    if m2:
        fname = m2.group(1).lower()
        right = m2.group(2).rstrip("%")
        fields[fname] = _num_or_str(right)
    if not fields:
        m3 = WAS_N_NOT_M.search(text)
        if m3 and "hydration" in text.lower():
            fields["hydration"] = float(m3.group(1))
        elif m3 and ("bulk" in text.lower() or "hour" in text.lower()):
            fields["bulk_hours"] = float(m3.group(1))
        elif m3:
            # generic numeric amend — caller may map
            fields["_value"] = float(m3.group(1))
            fields["_wrong"] = float(m3.group(2))

    # result enums
    for result in ("dense", "decent", "good", "great"):
        if re.search(rf"\b(?:result\s+)?(?:was|is)\s+{result}\b", text, re.I):
            fields["result"] = result

    return ParsedCorrection(
        action="amend",
        fields=fields,
        reason_code="amend_fields",
        raw_text=text,
    )


def _num_or_str(value: str) -> Any:
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value
