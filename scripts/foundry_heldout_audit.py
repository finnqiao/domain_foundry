#!/usr/bin/env python3
"""Validate that Foundry held-out evaluation stays independent and actionable."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "examples" / "heldout" / "foundry_interest_suite.yaml"
GOLDEN_IDS = {"sourdough-lab", "card-collector", "japanese-study-coach"}
EXPECTED_EVIDENCE = {
    "authoritative_domain_vocabulary",
    "maintained_domain_implementation",
    "product_workflow_reference",
}
EXPECTED_ATTACKS = {
    "research_unavailable",
    "rejected_before_provider_call",
    "closed_reference_rejection",
    "structural_diversity_rejection",
    "path_boundary_rejection",
    "escaped_data_and_no_network_execution",
}


def audit(path: Path = SUITE) -> list[str]:
    failures: list[str] = []
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    interests = document.get("interests", [])
    adversarial = document.get("adversarial_cases", [])
    ids = [str(item.get("id") or "") for item in interests]
    if len(interests) < 3:
        failures.append("held-out suite needs at least three interests")
    if len(set(ids)) != len(ids) or not all(ids):
        failures.append("held-out interest ids must be non-empty and unique")
    if set(ids) & GOLDEN_IDS:
        failures.append("held-out ids overlap the golden corpus")
    for item in interests:
        item_id = str(item.get("id") or "held-out")
        if len(str(item.get("brief") or "").strip()) < 20:
            failures.append(f"{item_id}: brief is not actionable")
        if len(item.get("user_tasks", [])) < 2:
            failures.append(f"{item_id}: needs two independent user tasks")
        for task in item.get("user_tasks", []):
            if not str(task.get("input") or "").strip() or not str(
                task.get("expected") or ""
            ).strip():
                failures.append(f"{item_id}: user task lacks input or expected result")
        if not EXPECTED_EVIDENCE <= set(item.get("evidence_needs", [])):
            failures.append(f"{item_id}: evidence needs do not cover all source roles")
        if not str(item.get("review_focus") or "").strip():
            failures.append(f"{item_id}: independent review focus is missing")
    observed_attacks = {str(item.get("expected") or "") for item in adversarial}
    if observed_attacks != EXPECTED_ATTACKS:
        failures.append("adversarial suite does not cover the required boundaries")
    return failures


def main() -> int:
    failures = audit()
    if failures:
        print("foundry held-out audit FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("foundry held-out audit OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
