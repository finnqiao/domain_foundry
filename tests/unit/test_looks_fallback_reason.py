"""A designer that fails must say so, not quietly hand back a template.

`generate_look` catches everything from the LLM designer and degrades to the
built-in template. That is the right behaviour — a look is never worth losing a
session over — but it used to be silent, so a misconfigured or failing designer
endpoint was indistinguishable from having no key at all. That is the exact
confusion the project's own docs call its most dangerous failure mode.
"""

from __future__ import annotations

from typing import Any

from domain_foundry_core.wizard.looks import generate_look

IDEA: dict[str, Any] = {
    "id": "food.fermentation.bake_lab",
    "title": "Sourdough / bake lab",
    "pitch": "Hydration, bulk, crumb.",
    "jobs": ["lab", "event_log"],
    "jargon": ["levain", "bulk", "crumb"],
}


class _Boom:
    name = "exploding-designer"

    def complete_json(self, **_: Any) -> Any:
        raise RuntimeError("endpoint refused the connection")


class _Empty:
    name = "silent-designer"

    def complete_json(self, **_: Any) -> Any:
        return {"html": "   "}


class _Working:
    name = "good-designer"

    def complete_json(self, **_: Any) -> Any:
        return {"html": "<main><h1>Bake lab</h1></main>"}


def test_no_designer_configured_is_not_a_failure() -> None:
    """The plain offline path is a choice, so it carries no reason."""
    look = generate_look(IDEA, samples="baked a 75% hydration loaf", llm=None)
    assert look["model"] == "template"
    assert look.get("fallback_reason") is None
    assert look["html"]


def test_a_raising_designer_records_what_went_wrong() -> None:
    look = generate_look(IDEA, samples="baked a 75% hydration loaf", llm=_Boom())
    assert look["model"] == "template", "must still return a usable look"
    reason = look.get("fallback_reason")
    assert reason and "RuntimeError" in reason
    assert "endpoint refused the connection" in reason


def test_a_designer_returning_no_html_still_records_a_reason() -> None:
    """A designer that answers with nothing usable is reported, not swallowed.

    The reason names missing HTML rather than the `empty_llm_html` sentinel:
    `_sota_html` validates its own output and raises first, so the exception path
    reports it. Either string is honest; asserting the sentinel here would pin an
    implementation detail instead of the contract.
    """
    look = generate_look(IDEA, samples="baked a 75% hydration loaf", llm=_Empty())
    assert look["model"] == "template"
    reason = look.get("fallback_reason")
    assert reason, "a configured designer that delivered nothing must say so"
    assert "no HTML" in reason or reason == "empty_llm_html"


def test_a_working_designer_leaves_no_reason_behind() -> None:
    look = generate_look(IDEA, samples="baked a 75% hydration loaf", llm=_Working())
    assert look["model"] == "good-designer"
    assert look.get("fallback_reason") is None
    assert "Bake lab" in look["html"]
