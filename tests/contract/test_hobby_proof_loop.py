"""End-to-end hobby reliability: starters + shortlist design + residue."""

from __future__ import annotations

import copy
import json
from typing import Any

from tests.conftest import land_wizard

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.llm.provider import CompletionResult, LLMProvider, TokenUsage
from domain_foundry_core.wizard import blueprint as bp
from domain_foundry_core.wizard.shortlist import analog_few_shots


class ShortlistDesignProvider(LLMProvider):
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
            input_tokens=8,
            output_tokens=8,
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
        goal = prompt["GOAL"]
        data = copy.deepcopy(analog_few_shots(goal)[0]["shortlist"])
        kws = bp.keywords(goal)
        data["domain"] = bp.slugify(kws[0] if kws else goal)
        data["title"] = goal[:80]
        return CompletionResult(data=data, usage=usage)


def test_proof_loop_starters_and_new_interest(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()

    # Starters without a key.
    plants = land_wizard(api, "track my houseplants")
    assert plants["design_mode"] == "starter"
    assert plants["pack"]["name"] == "plants"
    assert "expert" not in plants

    dough = land_wizard(api, "I want to track my sourdough journey")
    assert dough["design_mode"] == "starter"
    assert dough["pack"]["name"] == "sourdough"

    origami = land_wizard(api, "track my origami")
    assert origami["design_mode"] in {"scaffold", "atlas"}
    assert origami["state"] == "test_drive"

    # Capture on starter → ask cites prose → correct → export keeps residue path.
    receipt = api.capture(
        "baked a 75% hydration country loaf with the dutch oven",
        channel="cli",
    )
    assert receipt.status == "applied"
    assert any(s.domain == "sourdough" for s in receipt.routed)

    ask = api.ask("what loaf did I bake?", domain="sourdough")
    blob = json.dumps(ask if isinstance(ask, dict) else ask).lower()
    if isinstance(ask, dict):
        blob = json.dumps(ask).lower()
    else:
        blob = str(ask).lower()
    assert "country loaf" in blob or "hydration" in blob

    # New interest with provider double → shortlist land.
    provider = ShortlistDesignProvider()
    monkeypatch.setattr(
        "domain_foundry_core.wizard.engine.build_tiered_provider",
        lambda home=None: provider,
    )
    monkeypatch.setenv("DOMAIN_FOUNDRY_SOTA_API_KEY", "sk-test-not-real")
    api2 = HarnessAPI(workspace.home)
    boulder = land_wizard(api2, "track my bouldering sessions")
    assert boulder["design_mode"] == "llm"
    assert boulder["state"] == "test_drive"
    assert boulder.get("shortlist")
    assert "expert" not in boulder

    # Residue → export + hardening suggestion.
    for _ in range(3):
        api.capture(
            "baked a batard with the dutch oven again",
            channel="cli",
        )
    suggestion = api.wizard.suggest_hardening("sourdough", threshold=2)
    assert suggestion is None or suggestion.get("domain") == "sourdough"

    exported = api.export_data(domain="sourdough")
    assert exported["format"] == "domain-foundry-export/1"
    # raw_text never drops; residue may appear on interpretation-backed rows.
    bakes = exported["domains"]["sourdough"]["objects"]["bake"]
    assert bakes
    assert any(
        "country loaf" in (item.get("raw_text") or "")
        or "dutch" in json.dumps(item.get("residue") or {}).lower()
        for item in bakes
    )


def test_cli_capture_receipt_is_human(workspace, monkeypatch):
    from typer.testing import CliRunner

    from domain_foundry_core.cli import app

    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    api.activate_pack("sourdough")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["--home", str(workspace.home), "capture", "baked a country loaf"],
    )
    assert result.exit_code == 0, result.output
    assert "Saved to" in result.output
    assert "expert" not in result.output.lower()

    as_json = runner.invoke(
        app,
        ["--home", str(workspace.home), "capture", "--json", "baked another loaf"],
    )
    assert as_json.exit_code == 0
    payload = json.loads(as_json.output)
    assert payload["status"] in {"applied", "review", "unfiled", "ledger_only"}
