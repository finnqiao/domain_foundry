"""Layer-1 zero-token rules engine (plan §7.1)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from domain_expert_core.packs.models import DomainPack


@dataclass
class L1Hit:
    pack: str
    object_type: str
    operation: str
    pattern: str
    rule_index: int
    boost: float


@dataclass
class L1Result:
    hits: list[L1Hit] = field(default_factory=list)
    confidence: float = 0.0
    packs_matched: list[str] = field(default_factory=list)
    escalate: bool = True
    reason: str = ""


class L1Matcher:
    def __init__(
        self,
        packs: list[DomainPack],
        *,
        demotions: dict[tuple[str, int], float] | None = None,
    ) -> None:
        self.packs = packs
        self.demotions = demotions or {}
        self._compiled: list[tuple[DomainPack, int, re.Pattern[str], str, str, float]] = []
        for pack in packs:
            for idx, rule in enumerate(pack.routing.rules):
                try:
                    pat = re.compile(rule.match, re.IGNORECASE)
                except re.error:
                    continue
                self._compiled.append(
                    (pack, idx, pat, rule.object, rule.operation, rule.confidence_boost)
                )

    def match(self, text: str) -> L1Result:
        text = text or ""
        hits: list[L1Hit] = []
        for pack, idx, pat, obj, op, boost in self._compiled:
            if pat.search(text):
                hits.append(
                    L1Hit(
                        pack=pack.name,
                        object_type=obj,
                        operation=op,
                        pattern=pat.pattern,
                        rule_index=idx,
                        boost=boost,
                    )
                )

        packs_matched = sorted({h.pack for h in hits})
        result = L1Result(hits=hits, packs_matched=packs_matched)

        if not hits:
            result.confidence = 0.3
            result.escalate = True
            result.reason = "no_match"
            return result

        if len(packs_matched) > 1:
            result.confidence = 0.5
            result.escalate = True
            result.reason = "multi_pack"
            return result

        # exactly one pack
        pack_name = packs_matched[0]
        pack = next(p for p in self.packs if p.name == pack_name)
        base = 0.85
        boost = max((h.boost for h in hits if h.pack == pack_name), default=0.0)
        conf = min(0.99, base + boost)
        for h in hits:
            cap = self.demotions.get((h.pack, h.rule_index))
            if cap is not None:
                conf = min(conf, cap)
        result.confidence = conf

        short = len(text.strip()) < 280
        simple = pack.manifest.interpretation == "simple"
        l1_only = (
            conf >= 0.85
            and simple
            and short
            and not _looks_like_correction(text)
        )
        result.escalate = not l1_only
        result.reason = "l1_only" if l1_only else "escalate_structured_or_long"
        return result


_CORRECTION_RE = re.compile(
    r"\b(no,?\s+that|actually|undo|should (?:be|have been)|not\s+\d+|wrong|correct(?:ion)?)\b",
    re.IGNORECASE,
)


def _looks_like_correction(text: str) -> bool:
    return bool(_CORRECTION_RE.search(text or ""))
