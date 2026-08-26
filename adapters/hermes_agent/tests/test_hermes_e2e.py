"""End-to-end proof of the hermes-agent adapter's tool surface.

Drives the exact ``Tool`` objects hermes-agent invokes (``build_tools`` bound to
the in-process ``LocalHarnessClient``) through the full loop:

    new_domain -> wizard_reply(looks) -> wizard_reply(build it) -> capture
    -> query -> correct -> review

Offline and deterministic (heuristic router). Run standalone to print the
transcript used as the tutorial's Hermes proof snapshot:

    python adapters/hermes_agent/tests/test_hermes_e2e.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("DOMAIN_FOUNDRY_LLM", "heuristic")

from domain_foundry_hermes_agent import LocalHarnessClient  # noqa: E402
from domain_foundry_hermes_agent.plugin import build_tools  # noqa: E402

GOAL = "i collect pokemon cards"
PICK = "a dex of the cards i own with photos"
BUILD = "build it"
CAP = "pulled a holographic Charizard from a 151 booster, NM"
CORR = "that Charizard was LP not NM"


def _is_cards_domain(name: str | None) -> bool:
    token = (name or "").lower()
    return "pokemon" in token or "card" in token


def _looks_have_html(turn: dict) -> bool:
    return any("html" in (item or {}) for item in (turn.get("looks") or []))


def _run(echo: bool = False):
    home = tempfile.mkdtemp(prefix="df_hermes_")
    client = LocalHarnessClient(home)
    tools = {t.name: t for t in build_tools(client)}

    def call(name, **kw):
        out = tools[name](**kw)
        if echo:
            import json

            print(f"\n### {name}({kw})\n{json.dumps(out, indent=2)[:600]}")
        return out

    turn = call("domain_foundry_new_domain", goal_text=GOAL)
    sid = turn["session_id"]
    if "domain_foundry_wizard_reply" in tools:
        looks = call("domain_foundry_wizard_reply", session_id=sid, text=PICK)
        activated = call("domain_foundry_wizard_reply", session_id=sid, text=BUILD)
    else:
        looks = client.wizard_reply(sid, PICK)
        activated = client.wizard_reply(sid, BUILD)
    domain = activated.get("domain") or ((activated.get("pack") or {}).get("name"))
    cap = call("domain_foundry_capture", text=CAP)
    routed = (cap.get("routed") or [{}])[0]
    routed_domain = routed.get("domain") or domain
    q = call("domain_foundry_query", domain=routed_domain)
    asked = call("domain_foundry_ask", question="what did I log?", domain=routed_domain)
    corr = call("domain_foundry_correct", text=CORR)
    rev = call("domain_foundry_review_list")
    return {
        "new_domain": turn,
        "looks": looks,
        "activated": activated,
        "capture": cap,
        "query": q,
        "ask": asked,
        "correct": corr,
        "review": rev,
        "client": client,
    }


def test_hermes_adapter_end_to_end():
    r = _run()
    ideas = " ".join(
        i.get("title") or ""
        for i in ((r["new_domain"].get("neighborhood") or {}).get("ideas") or [])
    ).lower()
    assert r["new_domain"].get("state") == "fork"
    assert "card dex" in ideas
    assert r["looks"].get("state") == "looks"
    assert _looks_have_html(r["looks"]) is False
    assert r["looks"].get("looks")
    assert all("html" not in item for item in r["looks"]["looks"])
    domain = r["activated"].get("domain") or ((r["activated"].get("pack") or {}).get("name"))
    assert _is_cards_domain(domain)
    assert r["activated"].get("state") in {"test_drive", "repair"}
    routed = (r["capture"].get("routed") or [{}])[0]
    assert _is_cards_domain(routed.get("domain"))
    assert r["capture"]["status"] == "applied"
    assert len(r["query"]["rows"]) >= 1
    assert r["ask"].get("answer")
    assert r["correct"]["applied"] is True
    assert bool(r["correct"].get("eval_case_id")) is True
    # The amend must actually change the canonical record — an empty field set
    # used to report applied=true while changing nothing.
    assert r["correct"]["details"]["fields"] == {"notes": "LP"}


if __name__ == "__main__":
    _run(echo=True)
    print("\n\nHermes adapter E2E OK")
    sys.exit(0)
