"""End-to-end MCP contract test.

Launches ``domain-foundry-mcp`` over stdio exactly as Claude Desktop / Cursor do,
then drives the full loop through real MCP ``tools/call`` requests:

    new_domain -> wizard_reply(looks) -> wizard_reply(build it) -> capture
    -> query -> correct -> review -> health

Offline and deterministic (heuristic router, no API key). Run standalone to print
the transcript used as the tutorial's MCP proof snapshot:

    python adapters/mcp/tests/test_mcp_e2e.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from typing import Any

import pytest

# The MCP SDK is this adapter's own dependency, not a core one. Skip rather than
# error at collection so `pytest` on a plain checkout still works; CI installs it
# so the proof genuinely runs there (see .github/workflows/ci.yml).
pytest.importorskip("mcp", reason="pip install 'mcp>=1.2.0' to run the MCP proof")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

GOAL = "i collect pokemon cards"
PICK = "a dex of the cards i own with photos"
BUILD = "build it"
CAP = "pulled a holographic Charizard from a 151 booster, NM"
CORR = "that Charizard was LP not NM"


def _unwrap(result: Any) -> Any:
    """Return the tool's structured payload from a CallToolResult."""
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        # FastMCP wraps non-dict returns under {"result": ...}; ours are dicts.
        return structured.get("result", structured)
    content = getattr(result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    return None


def _looks_have_html(turn: dict[str, Any]) -> bool:
    return any("html" in (item or {}) for item in (turn.get("looks") or []))


def _is_cards_domain(name: str | None) -> bool:
    token = (name or "").lower()
    return "pokemon" in token or "card" in token


async def _run(home: str, echo: bool = False) -> list[tuple[str, Any]]:
    # Launch via ``python -m`` so the test does not depend on the console script
    # being on PATH. Real MCP clients use ``command: domain-foundry-mcp`` (README).
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "domain_foundry_mcp.server", "--home", home],
        env={**os.environ, "DOMAIN_FOUNDRY_LLM": "heuristic"},
    )
    transcript: list[tuple[str, Any]] = []

    def log(label: str, payload: Any) -> None:
        transcript.append((label, payload))
        if echo:
            print(f"\n### {label}\n{json.dumps(payload, indent=2)[:900]}")

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            log("tools/list", [t.name for t in tools.tools])

            r = await session.call_tool(
                "domain_foundry_new_domain",
                {"goal": GOAL},
            )
            turn = _unwrap(r)
            sid = turn["session_id"]
            log("new_domain", {
                "session_id": sid,
                "state": turn.get("state"),
                "domain": turn.get("domain"),
                "ideas": [
                    i.get("title")
                    for i in ((turn.get("neighborhood") or {}).get("ideas") or [])
                ],
            })

            r = await session.call_tool(
                "domain_foundry_wizard_reply", {"session_id": sid, "text": PICK}
            )
            looks = _unwrap(r)
            log("wizard_reply(looks)", {
                "state": looks.get("state"),
                "looks": [
                    {k: v for k, v in (item or {}).items() if k != "html"}
                    for item in (looks.get("looks") or [])
                ],
                "html_in_payload": _looks_have_html(looks),
            })

            r = await session.call_tool(
                "domain_foundry_wizard_reply", {"session_id": sid, "text": BUILD}
            )
            activated = _unwrap(r)
            log("wizard_reply(build it)", {
                "state": activated.get("state"),
                "domain": activated.get("domain")
                or ((activated.get("pack") or {}).get("name")),
            })

            r = await session.call_tool("domain_foundry_capture", {"text": CAP})
            cap = _unwrap(r)
            routed = (cap.get("routed") or [{}])[0]
            log("capture", {"status": cap.get("status"),
                            "domain": routed.get("domain"),
                            "object_type": routed.get("object_type"),
                            "confidence": routed.get("confidence")})

            r = await session.call_tool(
                "domain_foundry_query", {"domain": routed.get("domain")}
            )
            rows = _unwrap(r).get("rows", [])
            log("query", {"rows": len(rows),
                          "first": (rows[0].get("raw_text") if rows else None)})

            r = await session.call_tool(
                "domain_foundry_ask",
                {"question": "what did I log?", "domain": routed.get("domain")},
            )
            asked = _unwrap(r)
            log("ask", {"mode": asked.get("mode"), "has_answer": bool(asked.get("answer"))})

            r = await session.call_tool(
                "domain_foundry_correct",
                {"text": CORR},
            )
            corr = _unwrap(r)
            log("correct", {"action": corr.get("action"),
                            "applied": corr.get("applied"),
                            "eval_case": bool(corr.get("eval_case_id")),
                            "fields": (corr.get("details") or {}).get("fields")})

            r = await session.call_tool("domain_foundry_review_list", {})
            log("review_list", {"pending": len(_unwrap(r).get("items", []))})

            r = await session.call_tool("domain_foundry_health", {})
            log("health", {"ok": _unwrap(r).get("ok")})

    return transcript


def test_mcp_end_to_end() -> None:
    home = tempfile.mkdtemp(prefix="df_mcp_")
    transcript = asyncio.run(_run(home))
    steps = dict(transcript)

    assert "domain_foundry_capture" in steps["tools/list"]
    assert "domain_foundry_ask" in steps["tools/list"]
    assert "domain_foundry_activate_pack" in steps["tools/list"]
    assert "domain_foundry_export" in steps["tools/list"]
    assert steps["ask"]["has_answer"] is True
    assert steps["new_domain"].get("state") == "fork"
    ideas = " ".join(steps["new_domain"].get("ideas") or []).lower()
    assert "card dex" in ideas
    assert steps["wizard_reply(looks)"]["state"] == "looks"
    assert steps["wizard_reply(looks)"]["html_in_payload"] is False
    assert steps["wizard_reply(looks)"]["looks"]
    assert all("html" not in item for item in steps["wizard_reply(looks)"]["looks"])
    domain = steps["wizard_reply(build it)"]["domain"]
    assert _is_cards_domain(domain)
    assert steps["wizard_reply(build it)"]["state"] in {"test_drive", "repair"}
    assert _is_cards_domain(steps["capture"]["domain"])
    assert steps["capture"]["status"] == "applied"
    assert steps["query"]["rows"] >= 1
    assert "Charizard" in (steps["query"]["first"] or "")
    assert steps["correct"]["applied"] is True
    assert steps["correct"]["eval_case"] is True
    assert (steps["correct"].get("fields") or {}).get("notes") == "LP"
    assert steps["health"]["ok"] is True


if __name__ == "__main__":
    out = asyncio.run(_run(tempfile.mkdtemp(prefix="df_mcp_"), echo=True))
    print("\n\nMCP E2E OK —", len(out), "steps")
    sys.exit(0)
