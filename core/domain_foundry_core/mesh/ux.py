"""Concierge UX helpers — switch parsing, barge-in markers, ambiguity."""

from __future__ import annotations

import re
from dataclasses import dataclass

from domain_foundry_core.routing.router import RouteResult

# Explicit domain tags that barge into another domain without killing sticky.
_MARKER_RE = re.compile(
    r"(?:^|\s)(?:\[(?P<bracked>[a-z][a-z0-9_-]{1,31})\]|"
    r"(?P<label>japanese|food|health|dev|travel|plants|sourdough|general)\s*:)",
    re.IGNORECASE,
)

# Force sticky domain (switch command / NL).
_SWITCH_RE = re.compile(
    r"^\s*(?:"
    r"/switch\s+(?P<slash>[a-z][a-z0-9_-]{1,31})"
    r"|switch\s+to\s+(?P<to>[a-z][a-z0-9_-]{1,31})"
    r"|(?:talk|focus)\s+(?:to\s+)?(?P<talk>[a-z][a-z0-9_-]{1,31})"
    r"|actually,?\s+(?:let'?s\s+)?(?:log|do|open)\s+(?:a\s+)?"
    r"(?P<nl>japanese|food|health|dev|travel|plants|quiz)"
    r")\s*$",
    re.IGNORECASE,
)

_AMBIGUOUS_MAX_CONF = 0.72
_FALLBACK_DOMAINS = {"_unfiled", "_ledger", "general"}


@dataclass(frozen=True)
class SwitchIntent:
    domain: str
    raw: str


@dataclass(frozen=True)
class ClassifyDecision:
    domain: str
    confidence: float | None
    interpreter: str | None
    reason: str  # classify | sticky | barge_in | switch | not_mine_reroute
    sticky_session_id: str | None = None
    sticky_domain: str | None = None


def parse_switch(text: str) -> SwitchIntent | None:
    m = _SWITCH_RE.match((text or "").strip())
    if not m:
        return None
    domain = (
        m.group("slash")
        or m.group("to")
        or m.group("talk")
        or m.group("nl")
        or ""
    ).lower()
    if domain == "quiz":
        domain = "japanese"
    if not domain:
        return None
    return SwitchIntent(domain=domain, raw=text)


def parse_barge_marker(text: str) -> str | None:
    m = _MARKER_RE.search(text or "")
    if not m:
        return None
    return (m.group("bracked") or m.group("label") or "").lower() or None


def primary_span(
    result: RouteResult, *, exclude: set[str] | None = None
) -> tuple[str, float | None]:
    """Pick best real domain span, optionally excluding a bounced domain."""
    exclude = exclude or set()
    real = [
        s
        for s in result.spans
        if s.domain not in _FALLBACK_DOMAINS and s.domain not in exclude
    ]
    if real:
        primary = max(real, key=lambda s: s.confidence)
        return primary.domain, primary.confidence
    # Fallbacks still respect exclude.
    for s in result.spans:
        if s.domain not in exclude:
            dom = s.domain
            if dom.startswith("_"):
                dom = "general"
            return dom, s.confidence
    return "general", None


def is_ambiguous(result: RouteResult, *, sticky_domain: str | None = None) -> bool:
    """True when follow-up should stick rather than trust the classifier."""
    real = [s for s in result.spans if s.domain not in _FALLBACK_DOMAINS]
    if not real:
        return True
    primary = max(real, key=lambda s: s.confidence)
    if primary.confidence < _AMBIGUOUS_MAX_CONF:
        return True
    # Multi-pack low-ish signal: stick if sticky matches one of them.
    packs = {s.domain for s in real}
    if len(packs) > 1 and sticky_domain and sticky_domain in packs:
        if primary.confidence < 0.9:
            return True
    return False


def is_high_confidence_barge(
    result: RouteResult,
    *,
    sticky_domain: str,
    min_confidence: float,
) -> tuple[str, float] | None:
    """Return (domain, conf) when L1/classifier clearly hits a non-sticky domain."""
    domain, conf = primary_span(result)
    if domain in _FALLBACK_DOMAINS or domain == sticky_domain:
        return None
    if conf is None or conf < min_confidence:
        return None
    return domain, conf
