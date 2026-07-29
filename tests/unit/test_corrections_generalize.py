"""Corrections must work on a *generated* domain, not just the bundled packs.

The regex intent parser only knows sourdough vocabulary (hydration, bulk hours).
On a wizard-generated domain it resolves no fields — which used to report
``applied: true`` and append an eval case asserting the unchanged values were
right.
"""

from __future__ import annotations

from typing import Any

import pytest

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.llm.provider import CompletionResult, LLMProvider, TokenUsage


class _FieldPickerLLM(LLMProvider):
    """Stands in for the model that resolves 'medium, not low' → rating=medium."""

    name = "fake"
    api_key = "sk-test"

    def __init__(self, fields: dict[str, Any]) -> None:
        self.fields = fields
        self.calls = 0

    def complete_json(self, *, system, user, schema=None, model=None, tier=None):
        self.calls += 1
        if "correction" in user:
            data: dict[str, Any] = {"fields": self.fields}
        else:
            data = {
                "captures": [
                    {
                        "domain": "cocktails",
                        "object_type": "entry",
                        "operation": "create",
                        "confidence": 0.95,
                        "fields": {"title": "espresso martini", "rating": "low"},
                    }
                ],
                "unmatched_text": None,
                "needs_clarification": False,
                "clarifying_question": None,
            }
        return CompletionResult(
            data=data,
            usage=TokenUsage(input_tokens=10, output_tokens=5, model="fake", tier=tier),
        )


@pytest.fixture
def cocktails(tmp_path):
    api = HarnessAPI(tmp_path)
    api.init()
    sess = api.new_domain("keep notes on the cocktails I make and drink")
    api.wizard_reply(sess["session_id"], "skip")
    return api


def _seed(api: HarnessAPI, llm: LLMProvider) -> None:
    api.router.llm = llm
    api.capture("the espresso martini I ordered was way too sweet")


def test_nl_correction_amends_a_generated_domain(cocktails, monkeypatch):
    llm = _FieldPickerLLM({"rating": "medium"})
    _seed(cocktails, llm)
    monkeypatch.setattr(
        "domain_foundry_core.llm.provider.get_default_provider", lambda **kw: llm
    )

    receipt = cocktails.correct("actually the espresso martini was medium, not low")

    assert receipt["error"] is None, receipt
    assert receipt["applied"] is True
    assert receipt["details"]["fields"] == {"rating": "medium"}
    assert receipt["eval_case_id"]


def test_unresolvable_correction_reports_error_not_success(cocktails, monkeypatch):
    llm = _FieldPickerLLM({})  # model can't tell which field either
    _seed(cocktails, llm)
    monkeypatch.setattr(
        "domain_foundry_core.llm.provider.get_default_provider", lambda **kw: llm
    )

    receipt = cocktails.correct("hmm, that one wasn't quite right")

    assert receipt["applied"] is False
    assert "could not tell which field" in (receipt["error"] or "")
    # No eval case: a no-op must never enter the corpus that proves improvement.
    assert receipt["eval_case_id"] is None
