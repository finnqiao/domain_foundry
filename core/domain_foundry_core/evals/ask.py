"""Replay the grounded Ask corpus against isolated temporary workspaces."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.evals.runner import load_cases
from domain_foundry_core.llm.provider import HeuristicProvider, build_eval_provider
from domain_foundry_core.routing.router import Router
from domain_foundry_core.security.store import connect_ro


def run_ask_eval(
    cases_path: Path,
    *,
    live_llm: bool = False,
    cassette_dir: Path | None = None,
) -> dict[str, Any]:
    """Run JSONL Ask cases and return a compact accuracy report."""
    cases = load_cases(cases_path)
    failures: list[dict[str, Any]] = []
    passed = 0
    cassette_reports: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="domain-foundry-ask-eval-") as raw_home:
        for case in cases:
            home = Path(raw_home) / str(case.get("id") or "case")
            api = HarnessAPI(home)
            api.init()
            for pack_name in case.get("setup", {}).get("packs") or []:
                api.packs.activate_bundled(str(pack_name))
            api.packs.reload()
            # Setup captures must be deterministic and must not consume the
            # model budget used to evaluate the answerer.
            api.router = Router(
                api.workspace,
                registry=api.packs,
                llm=HeuristicProvider(),
                cost_cap=999,
            )
            captures = [
                api.capture(str(text), channel="eval")
                for text in case.get("setup", {}).get("captures") or []
            ]
            provider = build_eval_provider(
                cassette_dir or (home / "cassettes"), live_llm=live_llm
            )
            response = api.ask(
                str(case.get("question") or ""),
                domain=case.get("domain"),
                _llm=provider,
            )
            reasons = _score_case(api, case, captures, response)
            if reasons:
                failures.append(
                    {"id": case.get("id"), "reasons": reasons, "response": response}
                )
            else:
                passed += 1
            cassette_reports.append(provider.drift_report())

    total = len(cases)
    return {
        "total": total,
        "passed": passed,
        "accuracy": (passed / total) if total else 0.0,
        "failures": failures,
        "cassette": {
            "drift_count": sum(report.get("drift_count", 0) for report in cassette_reports),
            "cases": cassette_reports,
        },
    }


def default_ask_cases_path() -> Path:
    return Path(__file__).resolve().parents[3] / "examples" / "synthetic" / "ask_eval.jsonl"


def _score_case(
    api: HarnessAPI,
    case: dict[str, Any],
    captures: list[Any],
    response: dict[str, Any],
) -> list[str]:
    expected = case.get("expect") or {}
    reasons: list[str] = []
    modes = expected.get("mode") or []
    if isinstance(modes, str):
        modes = [modes]
    if modes and response.get("mode") not in modes:
        reasons.append(f"mode {response.get('mode')!r} not in {modes!r}")

    answer = str(response.get("answer") or "")
    answer_lower = answer.lower()
    refusal = response.get("mode") == "refusal" or "don't have that" in answer_lower
    if bool(expected.get("refusal")) != refusal:
        reasons.append(f"refusal={refusal}, expected={bool(expected.get('refusal'))}")

    needles = [str(item).lower() for item in expected.get("answer_contains_any") or []]
    if needles and not any(needle in answer_lower for needle in needles):
        reasons.append(f"answer contains none of {needles!r}")
    forbidden = [str(item).lower() for item in expected.get("answer_must_not_contain") or []]
    for needle in forbidden:
        if needle in answer_lower:
            reasons.append(f"answer contains forbidden text {needle!r}")

    citations = response.get("citations") or []
    minimum = int(expected.get("min_citations") or 0)
    if len(citations) < minimum:
        reasons.append(f"{len(citations)} citations, expected at least {minimum}")

    target_index = expected.get("cited_capture_index")
    if target_index is not None:
        try:
            target_text = str(case.get("setup", {}).get("captures", [])[int(target_index)])
        except (IndexError, TypeError, ValueError):
            reasons.append(f"invalid cited_capture_index {target_index!r}")
        else:
            if not any(_citation_matches(api, citation, target_text) for citation in citations):
                reasons.append("no citation resolves to the expected setup capture")

    if expected.get("no_false_action"):
        if re.search(
            r"\b(deleted|removed|changed|updated|saved|created|filed)\b",
            answer_lower,
        ):
            reasons.append("answer claims a mutation on a read-only surface")
    return reasons


def _citation_matches(api: HarnessAPI, citation: dict[str, Any], target_text: str) -> bool:
    entry_id = citation.get("entry_id")
    if not entry_id and citation.get("object_uid"):
        detail = api.object_detail(
            str(citation.get("domain") or ""),
            str(citation.get("object_type") or ""),
            str(citation["object_uid"]),
        )
        capture = detail.get("capture") if isinstance(detail, dict) else None
        entry_id = capture.get("entry_id") if isinstance(capture, dict) else None
    if not entry_id:
        return False
    conn = connect_ro(api.workspace.ledger_db)
    try:
        row = conn.execute(
            """
            SELECT c.raw_text
            FROM entry e JOIN capture_event c ON c.id = e.capture_event_id
            WHERE e.id = ?
            """,
            (entry_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return False
    return str(row["raw_text"] or "").strip().lower() == target_text.strip().lower()
