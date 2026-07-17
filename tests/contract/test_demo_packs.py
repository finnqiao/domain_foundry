"""Demo/reference pack gates (plan §11 P8).

Both packs must validate and route their committed fixtures green (≥25 each) in
deterministic cassette-free replay, including the travel pack's cross-domain
dining↔trip links.
"""

from __future__ import annotations

from pathlib import Path

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.evals.runner import run_eval
from domain_foundry_core.packs.loader import bundled_packs_root

REPO = Path(__file__).resolve().parents[2]
FOOD_FIXTURES = REPO / "packs" / "food" / "evals" / "fixtures.jsonl"
TRAVEL_FIXTURES = REPO / "packs" / "travel" / "evals" / "fixtures.jsonl"


def _count(path: Path) -> int:
    return sum(
        1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    )


def test_food_pack_validates(workspace):
    api = HarnessAPI(workspace.home)
    api.init()
    api.pack_add(bundled_packs_root() / "food", force=True)
    assert api.pack_validate("food") == []


def test_travel_pack_validates(workspace):
    api = HarnessAPI(workspace.home)
    api.init()
    api.pack_add(bundled_packs_root() / "travel", force=True)
    assert api.pack_validate("travel") == []


def test_food_fixtures_route_green(workspace):
    assert _count(FOOD_FIXTURES) >= 25
    report = run_eval(FOOD_FIXTURES, workspace=workspace, packs=["food"])
    assert report.total >= 25
    assert report.accuracy >= 0.96, [
        (s.case_id, s.detail) for s in report.scores if not s.ok
    ]


def test_travel_fixtures_route_green_with_cross_domain(workspace):
    assert _count(TRAVEL_FIXTURES) >= 25
    # Travel + food both active so dining↔trip cross-domain fixtures fan out.
    report = run_eval(TRAVEL_FIXTURES, workspace=workspace, packs=["food", "travel"])
    assert report.total >= 25
    assert report.accuracy >= 0.96, [
        (s.case_id, s.detail) for s in report.scores if not s.ok
    ]
    # The cross-domain fixtures must actually produce a link across two domains.
    cross = [s for s in report.scores if "cross" in (s.expected.get("tags") or [])]
    assert cross, "expected cross-domain fixtures present"
    for s in cross:
        domains = {c.get("domain") for c in s.actual}
        assert {"food", "travel"} <= domains, (s.case_id, s.actual)
