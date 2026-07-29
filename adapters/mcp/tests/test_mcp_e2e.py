"""End-to-end MCP contract test.

Launches ``domain-foundry-mcp`` over stdio exactly as Claude Desktop / Cursor do,
then drives the full loop through real MCP ``tools/call`` requests:

    new_domain -> wizard_reply(skip) -> capture -> query -> correct -> review -> health

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

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


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
                {"goal": "track my bouldering climbing sessions"},
            )
            turn = _unwrap(r)
            sid = turn["session_id"]
            log("new_domain", {"session_id": sid, "state": turn.get("state"),
                               "domain": turn.get("domain")})

            r = await session.call_tool(
                "domain_foundry_wizard_reply", {"session_id": sid, "text": "skip"}
            )
            activated = _unwrap(r)
            log("wizard_reply(skip)", {"state": activated.get("state"),
                                       "domain": activated.get("domain")})

            r = await session.call_tool(
                "domain_foundry_capture",
                {"text": "good bouldering session at the gym, felt strong"},
            )
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
                "domain_foundry_correct",
                {"text": "actually the rating was moderate not hard"},
            )
            corr = _unwrap(r)
            log("correct", {"action": corr.get("action"),
                            "applied": corr.get("applied"),
                            "eval_case": bool(corr.get("eval_case_id"))})

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
    assert steps["new_domain"]["domain"] == "bouldering"
    assert steps["wizard_reply(skip)"]["state"] == "test_drive"
    assert steps["capture"]["domain"] == "bouldering"
    assert steps["capture"]["status"] == "applied"
    assert steps["query"]["rows"] >= 1
    assert steps["correct"]["applied"] is True
    assert steps["correct"]["eval_case"] is True
    assert steps["health"]["ok"] is True


if __name__ == "__main__":
    out = asyncio.run(_run(tempfile.mkdtemp(prefix="df_mcp_"), echo=True))
    print("\n\nMCP E2E OK —", len(out), "steps")
    sys.exit(0)
