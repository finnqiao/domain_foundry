"""Held-out acceptance for generated wizard packs.

The pack's own routing examples remain useful as a renderer/self-consistency
check, but they are not evidence that a new domain understands its user.  This
module scores independently authored cases and always records the deterministic
heuristic result alongside a configured-provider result.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from domain_foundry_core.llm.provider import (
    HeuristicProvider,
    LLMProvider,
    is_heuristic_provider,
)
from domain_foundry_core.packs.loader import load_pack
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace
from domain_foundry_core.routing.router import Router
from domain_foundry_core.wizard.blueprint import keywords

ACCEPTANCE_THRESHOLD = 0.90


def load_suite(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL suite, allowing full-line ``#`` comments."""

    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid held-out JSON on line {line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"held-out case on line {line_number} must be an object")
        if not isinstance(value.get("capture"), str) or not value["capture"].strip():
            raise ValueError(f"held-out case on line {line_number} needs capture text")
        cases.append(value)
    return cases


def select_cases(goal: str, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select cases whose goal key is represented by the wizard goal.

    Keys are intentionally loose enough to match singular/plural forms (for
    example ``dream`` and ``dreams``), while still requiring whole keyword
    overlap for multi-word keys.
    """

    goal_words = set(keywords(goal))
    out: list[dict[str, Any]] = []
    for case in cases:
        raw_key = str(case.get("goal_key") or "").strip().lower()
        if not raw_key:
            continue
        key_words = set(keywords(raw_key)) or {
            word for word in raw_key.replace("_", " ").split() if word
        }
        matches = bool(key_words & goal_words)
        if not matches:
            matches = any(
                key == word or key in word or word in key
                for key in key_words
                for word in goal_words
            )
        if matches:
            out.append(case)
    return out


def _route_cases(
    pack_dir: Path,
    cases: list[dict[str, Any]],
    provider: LLMProvider,
) -> tuple[int, list[dict[str, Any]]]:
    """Route cases in a fresh registry containing only the generated pack."""

    tmp = Path(tempfile.mkdtemp(prefix="wiz_accept_"))
    try:
        ws = Workspace(tmp)
        registry = PackRegistry(ws)
        registry.add(pack_dir, force=True)
        pack = registry.get(load_pack(pack_dir, validate=True).name)
        if pack is None:  # pragma: no cover - registry.add/reload invariant
            raise RuntimeError("generated pack was not registered for acceptance")
        router = Router(ws, registry=registry, llm=provider, cost_cap=999)
        passed = 0
        failures: list[dict[str, Any]] = []
        for case in cases:
            result = router.route_text(case["capture"], channel="acceptance")
            top = next(
                (
                    span
                    for span in result.spans
                    if span.domain not in {"_unfiled", "_ledger"}
                    and span.disposition not in {"unfiled", "ledger_only"}
                ),
                None,
            )
            expect = case.get("expect") or {}
            should_route = bool(expect.get("routes", True))
            expected_object = expect.get("object_type")
            ok = (
                (top is not None and top.domain == pack.name)
                if should_route
                else top is None
            ) and (expected_object is None or (top is not None and top.object_type == expected_object))
            if ok:
                passed += 1
                continue
            failures.append(
                {
                    "id": case.get("id"),
                    "capture": case["capture"],
                    "routed_domain": top.domain if top else "_unfiled",
                    "routed_object": top.object_type if top else None,
                    "routed_disposition": top.disposition if top else "unfiled",
                    "expected_routes": should_route,
                    "expected_object": expected_object,
                }
            )
        return passed, failures
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def acceptance_run(
    pack_dir: Path,
    cases: list[dict[str, Any]],
    llm: LLMProvider | None = None,
) -> dict[str, Any]:
    """Score held-out captures against only ``pack_dir``.

    No cases means ``covered=False`` and an explicit non-pass.  With no live
    provider, the heuristic score is the deterministic score.  A configured
    provider is replayable through the existing provider/cassette abstraction;
    routing itself still has the router's safe heuristic fallback on provider
    errors.
    """

    if not cases:
        return {
            "total": 0,
            "passed": 0,
            "accuracy": 0.0,
            "failures": [],
            "heuristic": None,
            "provider": None,
            "provider_live": False,
            "covered": False,
        }

    load_pack(pack_dir, validate=True)
    heuristic_passed, heuristic_failures = _route_cases(
        pack_dir, cases, HeuristicProvider()
    )

    provider_live = llm is not None and not is_heuristic_provider(llm)
    if llm is not None and not is_heuristic_provider(llm):
        passed, failures = _route_cases(pack_dir, cases, llm)
        provider_name = getattr(llm, "name", "llm")
    else:
        passed, failures = heuristic_passed, heuristic_failures
        provider_name = "heuristic"

    total = len(cases)
    return {
        "total": total,
        "passed": passed,
        "accuracy": passed / total,
        "failures": failures,
        "heuristic": {
            "passed": heuristic_passed,
            "accuracy": heuristic_passed / total,
            "failures": heuristic_failures,
        },
        "provider": provider_name,
        "provider_live": provider_live,
        "covered": True,
    }


__all__ = [
    "ACCEPTANCE_THRESHOLD",
    "acceptance_run",
    "load_suite",
    "select_cases",
]
