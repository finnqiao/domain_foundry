"""Held-out acceptance and seamless create contracts (S1.5 / hobby reliability).

All model-backed cases use a deterministic provider double that returns
shortlists (not full pack dumps). No test reaches a real API endpoint.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.llm.provider import CompletionResult, LLMProvider, TokenUsage
from domain_foundry_core.wizard import blueprint as bp
from domain_foundry_core.wizard.acceptance import (
    acceptance_run,
    load_suite,
    select_cases,
)
from domain_foundry_core.wizard.shortlist import analog_few_shots
from tests.conftest import land_wizard

SUITE = Path("examples/heldout/wizard_hobby_suite.jsonl")
REVIEW_8 = [case for case in load_suite(SUITE) if "review-8" in (case.get("tags") or [])]


def _shortlist_for_goal(goal: str) -> dict[str, Any]:
    shots = analog_few_shots(goal)
    data = copy.deepcopy(shots[0]["shortlist"])
    kws = bp.keywords(goal)
    data["domain"] = bp.slugify(kws[0] if kws else goal)
    data["title"] = (goal[:1].upper() + goal[1:]) if goal else data["title"]
    data["description"] = f"Track: {goal}"
    return data


class DeterministicDesignProvider(LLMProvider):
    """Cassette-like provider: shortlist design + simple route JSON."""

    name = "tiered"

    def has_live_keys(self) -> bool:
        return True

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        model: str | None = None,
        tier: str | None = None,
    ) -> CompletionResult:
        usage = TokenUsage(
            input_tokens=10,
            output_tokens=10,
            model=model or "claude-opus-5",
            tier=tier,
            provider=self.name,
        )
        if "Route this capture" in user:
            context = json.loads(user.split("CONTEXT_JSON:", 1)[1])
            pack = context["packs"][0]
            object_type = next(iter(pack["objects"]))
            return CompletionResult(
                data={
                    "captures": [
                        {
                            "domain": pack["name"],
                            "object_type": object_type,
                            "operation": "create",
                            "span": context["text"],
                            "confidence": 0.95,
                            "fields": {},
                            "links": [],
                        }
                    ],
                    "unmatched_text": None,
                    "needs_clarification": False,
                    "clarifying_question": None,
                },
                usage=usage,
            )

        prompt = json.loads(user)
        return CompletionResult(
            data=_shortlist_for_goal(prompt["GOAL"]),
            usage=usage,
        )


def test_suite_carries_the_eight_review_cases():
    assert len(REVIEW_8) == 8
    captures = {case["capture"] for case in REVIEW_8}
    assert "sent a tough V5 on the overhang today, crux was the heel hook" in captures
    assert "V60 Ethiopian, 15g in and 250g out, tasted like blueberry" in captures


@pytest.mark.parametrize("case", REVIEW_8, ids=lambda case: case["id"])
def test_heuristic_mode_surfaces_review_failures(workspace, monkeypatch, case):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    monkeypatch.setenv("DOMAIN_FOUNDRY_LLM", "heuristic")
    api = HarnessAPI(workspace.home)
    api.init()

    turn = land_wizard(api, case["goal"])
    assert turn.get("designer") is None
    assert turn["design_mode"] in {"scaffold", "atlas", "starter"}
    assert turn["state"] == "test_drive"
    assert turn.get("pack", {}).get("name") or turn.get("domain")

    acceptance = turn.get("acceptance") or {}
    if acceptance.get("covered"):
        assert "is live (v" not in turn["message"]


def test_seamless_create_with_key_skips_model_confirm(workspace, monkeypatch):
    """Submitting the sentence is the confirm — no sota/routine/scaffold fork."""
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    monkeypatch.setenv("DOMAIN_FOUNDRY_SOTA_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("DOMAIN_FOUNDRY_ROUTINE_API_KEY", "sk-test-not-real")
    provider = DeterministicDesignProvider()
    monkeypatch.setattr(
        "domain_foundry_core.wizard.engine.build_tiered_provider",
        lambda home=None: provider,
    )
    api = HarnessAPI(workspace.home)
    api.init()

    turn = land_wizard(api, "track my bouldering sessions")
    assert turn["state"] == "test_drive"
    assert turn["awaiting"] == "capture"
    assert turn["design_mode"] == "llm"
    assert turn.get("shortlist")
    assert turn["pack"]["name"]
    assert "expert" not in turn


def test_llm_design_acceptance_and_status_flip(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    monkeypatch.setenv("DOMAIN_FOUNDRY_SOTA_API_KEY", "sk-test-not-real")
    provider = DeterministicDesignProvider()
    monkeypatch.setattr(
        "domain_foundry_core.wizard.engine.build_tiered_provider",
        lambda home=None: provider,
    )
    api = HarnessAPI(workspace.home)
    api.init()

    activated = land_wizard(api, "track my bouldering sessions")
    assert activated["design_mode"] == "llm"
    assert activated["designer_model"]
    assert activated["state"] == "test_drive"
    assert activated["acceptance"]["accuracy"] >= 0.90
    assert activated["status"] == "scaffold"

    captured = api.wizard_reply(activated["session_id"], "bouldering session on the wall")
    assert captured["status"] == "live"
    status_path = Path(activated["pack"]["path"]) / "foundry_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "live"
    assert status["real_captures"] == 1


def test_heldout_miss_installs_with_needs_repair_banner(workspace, monkeypatch):
    """Held-out miss is a banner, not a blocking repair gate."""
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    provider = DeterministicDesignProvider()
    monkeypatch.setattr(
        "domain_foundry_core.wizard.engine.build_tiered_provider",
        lambda home=None: provider,
    )
    monkeypatch.setattr(
        "domain_foundry_core.wizard.engine.acceptance_run",
        lambda pack_dir, cases, llm=None: {
            "total": 1,
            "passed": 0,
            "accuracy": 0.0,
            "failures": [
                {
                    "capture": "a phrase that should route",
                    "routed_domain": "_unfiled",
                    "expected_object": "session",
                }
            ],
            "heuristic": {"passed": 0, "accuracy": 0.0, "failures": []},
            "provider": "tiered",
            "provider_live": True,
            "covered": True,
        },
    )
    api = HarnessAPI(workspace.home)
    api.init()

    turn = land_wizard(api, "track my bouldering sessions")
    assert turn["design_mode"] == "llm"
    assert turn["state"] == "test_drive"
    assert turn.get("needs_repair") is True
    assert turn.get("pack", {}).get("name")


def test_acceptance_selects_only_matching_goal_cases(tmp_path):
    cases = load_suite(SUITE)
    selected = select_cases("track my cycling rides", cases)
    assert [case["id"] for case in selected] == ["ho_cycling_1"]

    draft = tmp_path / "draft"
    bp.write_pack(bp.build_blueprint("track my cycling rides"), draft)
    report = acceptance_run(draft, selected)
    assert report["covered"] is True
    assert report["total"] == 1
    assert report["provider"] == "heuristic"
