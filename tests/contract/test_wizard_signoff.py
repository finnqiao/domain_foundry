"""A domain sentence is not a goodbye.

The test-drive turn used to end the session on any message containing "done",
"finished" or "complete" anywhere in it. Three of the fifty interest goals open
their first real note with exactly that word — "finished the sleeve, blocking
tonight", "finished The Left Hand of Darkness" — so the wizard answered "Happy
tracking!" and routed nothing at all. The user watched their first note vanish,
which is worse than an unfiled card.
"""

from __future__ import annotations

import pytest
from tests.conftest import land_wizard

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.wizard.engine import is_session_signoff


@pytest.mark.parametrize(
    "text",
    [
        "done",
        "Done.",
        "finished",
        "that's all",
        "all set",
        "ok, done for now",
        "I'm done",
        "all done, thanks",
        "nothing else",
    ],
)
def test_a_bare_signoff_still_ends_the_session(text: str) -> None:
    assert is_session_signoff(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "finished the sleeve, blocking tonight, merino DK",
        "finished The Left Hand of Darkness, reread later maybe",
        "finished the Millennium Falcon MOC, 3800 pieces, missing 2 tiles",
        "done with the 5x5 block, deload next week",
        "complete rebuild of the carburettor",
        "all set up the new tank, parameters look fine",
    ],
)
def test_a_sentence_that_carries_content_is_never_a_signoff(text: str) -> None:
    assert is_session_signoff(text) is False


@pytest.mark.parametrize(
    ("goal", "sentence"),
    [
        ("knitting projects", "finished the sleeve, blocking tonight, merino DK"),
        ("books I read", "finished The Left Hand of Darkness, reread later maybe"),
    ],
)
def test_test_drive_captures_a_domain_sentence_that_opens_with_finished(
    workspace, monkeypatch, goal: str, sentence: str
) -> None:
    monkeypatch.setenv("DOMAIN_FOUNDRY_LLM", "heuristic")
    api = HarnessAPI(workspace.home)
    api.init()
    turn = land_wizard(api, goal, reply="1")
    sid = turn["session_id"]

    reply = api.wizard_reply(sid, sentence)

    assert reply.get("done") is not True, reply.get("message")
    assert reply.get("capture", {}).get("routed"), reply.get("message")


def test_test_drive_still_closes_on_a_bare_done(workspace, monkeypatch) -> None:
    monkeypatch.setenv("DOMAIN_FOUNDRY_LLM", "heuristic")
    api = HarnessAPI(workspace.home)
    api.init()
    turn = land_wizard(api, "knitting projects", reply="1")
    reply = api.wizard_reply(turn["session_id"], "done")
    assert reply.get("done") is True
