"""End-to-end proof of the hermes-agent adapter's tool surface.

Drives the exact ``Tool`` objects hermes-agent invokes (``build_tools`` bound to
the in-process ``LocalHarnessClient``) through the full loop:

    new_domain -> wizard_reply(skip) -> capture -> query -> correct -> review

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

    turn = call("domain_foundry_new_domain", goal_text="track my bouldering climbing sessions")
    sid = turn["session_id"]
    # wizard_reply is exposed as a tool on the adapter; fall back to the client.
    if "domain_foundry_wizard_reply" in tools:
        activated = call("domain_foundry_wizard_reply", session_id=sid, text="skip")
    else:
        activated = client.wizard_reply(sid, "skip")
    cap = call("domain_foundry_capture", text="good bouldering session at the gym, felt strong")
    q = call("domain_foundry_query", domain="bouldering")
    # Offline (no model), corrections resolve through the deterministic
    # "<field> was <x> not <y>" form. A vaguer phrasing needs L2 — asserting on
    # one here would pass on an *empty* amend rather than a real one.
    corr = call("domain_foundry_correct", text="actually the rating was moderate not hard")
    rev = call("domain_foundry_review_list")
    return {"new_domain": turn, "activated": activated, "capture": cap,
            "query": q, "correct": corr, "review": rev, "client": client}


def test_hermes_adapter_end_to_end():
    r = _run()
    assert r["new_domain"]["domain"] == "bouldering"
    routed = (r["capture"].get("routed") or [{}])[0]
    assert routed["domain"] == "bouldering"
    assert r["capture"]["status"] == "applied"
    assert len(r["query"]["rows"]) >= 1
    assert r["correct"]["applied"] is True
    assert bool(r["correct"].get("eval_case_id")) is True
    # The amend must actually change the canonical record — an empty field set
    # used to report applied=true while changing nothing.
    assert r["correct"]["details"]["fields"] == {"rating": "moderate"}


if __name__ == "__main__":
    _run(echo=True)
    print("\n\nHermes adapter E2E OK")
    sys.exit(0)
