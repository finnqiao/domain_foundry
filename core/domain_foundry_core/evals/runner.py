"""Eval replay skeleton — fixture routing accuracy with cassettes (P2)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from domain_foundry_core.llm.provider import HeuristicProvider, LLMProvider
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace
from domain_foundry_core.routing.router import Router


@dataclass
class CaseScore:
    case_id: str
    ok: bool
    expected: dict[str, Any]
    actual: list[dict[str, Any]]
    detail: str = ""


@dataclass
class EvalReport:
    total: int = 0
    correct: int = 0
    scores: list[CaseScore] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return (self.correct / self.total) if self.total else 0.0

    def by_tag(self) -> dict[str, tuple[int, int]]:
        out: dict[str, tuple[int, int]] = {}
        for s in self.scores:
            tags = s.expected.get("tags") or ["untagged"]
            for tag in tags:
                c, t = out.get(tag, (0, 0))
                out[tag] = (c + (1 if s.ok else 0), t + 1)
        return out


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    return cases


def score_case(case: dict[str, Any], spans: list[dict[str, Any]]) -> CaseScore:
    case_id = str(case.get("id") or case.get("raw_text", "")[:40])
    expected = case.get("expected") or {}
    kind = expected.get("kind") or "captures"

    if kind == "negative":
        # Correct if no real domain capture (unfiled/ledger ok) OR empty
        real = [s for s in spans if s.get("domain") not in {None, "_unfiled", "_ledger"}]
        ok = len(real) == 0
        return CaseScore(case_id, ok, expected, spans, "negative" if ok else "false_positive")

    want_list = expected.get("captures") or []
    if not want_list and expected.get("domain"):
        want_list = [expected]

    if not want_list:
        ok = True
        return CaseScore(case_id, ok, expected, spans, "empty_expect")

    # Each expected capture must match some actual on domain+object+operation
    remaining = list(spans)
    matched = 0
    for want in want_list:
        found_idx = None
        for i, got in enumerate(remaining):
            if want.get("domain") and got.get("domain") != want.get("domain"):
                continue
            if want.get("object_type") and got.get("object_type") != want.get("object_type"):
                # allow expect.object alias
                pass
            obj = want.get("object_type") or want.get("object")
            if obj and got.get("object_type") != obj:
                continue
            op = want.get("operation")
            if op and got.get("operation") != op:
                continue
            # optional field checks
            fields = want.get("fields") or {}
            got_fields = got.get("fields") or {}
            fields_ok = True
            for fk, fv in fields.items():
                if fk not in got_fields:
                    fields_ok = False
                    break
                if isinstance(fv, (int, float)) and isinstance(got_fields[fk], (int, float)):
                    if abs(float(fv) - float(got_fields[fk])) > 0.01:
                        fields_ok = False
                        break
                elif str(got_fields[fk]).lower() != str(fv).lower():
                    fields_ok = False
                    break
            if not fields_ok:
                continue
            found_idx = i
            break
        if found_idx is None:
            return CaseScore(case_id, False, expected, spans, f"missing {want}")
        remaining.pop(found_idx)
        matched += 1

    ok = matched == len(want_list)
    # For multi-domain, also require at least as many real spans
    if expected.get("require_link"):
        # presence of 2+ domains is enough for skeleton
        domains = {s.get("domain") for s in spans}
        ok = ok and len(domains) >= 2
    return CaseScore(case_id, ok, expected, spans, "ok" if ok else "partial")


def run_eval(
    cases_path: Path,
    *,
    workspace: Workspace | None = None,
    packs: list[str] | None = None,
    llm: LLMProvider | None = None,
) -> EvalReport:
    ws = workspace or Workspace()
    ws.ensure_layout()
    registry = PackRegistry(ws)
    # Activate requested bundled packs into workspace
    for name in packs or ["plants", "sourdough"]:
        try:
            registry.activate_bundled(name)
        except FileExistsError:
            pass
        except Exception:
            # already present via discovery
            registry.reload()
    registry.ensure_schemas_applied()

    router = Router(ws, registry=registry, llm=llm or HeuristicProvider(), cost_cap=999)
    cases = load_cases(cases_path)
    report = EvalReport()
    for case in cases:
        text = case["raw_text"]
        result = router.route_text(text, channel=case.get("channel") or "cli")
        spans = [
            {
                "domain": s.domain,
                "object_type": s.object_type,
                "operation": s.operation,
                "confidence": s.confidence,
                "fields": s.fields,
                "links": s.links,
                "disposition": s.disposition,
            }
            for s in result.spans
        ]
        scored = score_case(case, spans)
        report.scores.append(scored)
        report.total += 1
        if scored.ok:
            report.correct += 1
    return report
