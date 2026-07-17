"""Conformance test for the hermes-agent adapter (plan §11 P8).

Drives a scripted agent session — capture → correct → review — through the
adapter's tools against a *live* in-process FastAPI stack (Starlette TestClient),
exercising the exact HTTP client the plugin ships. Also checks `register(ctx)`
wiring and the pinned hermes-agent version range.
"""

from __future__ import annotations

from domain_foundry_hermes_agent import DomainExpertClient, build_tools
from domain_foundry_hermes_agent.plugin import (
    CAPTURE_FIRST_GUIDANCE,
    SUPPORTED_HERMES_AGENT,
    register,
)
from fastapi.testclient import TestClient

from domain_foundry_core.api.app import create_app
from domain_foundry_core.api.harness import HarnessAPI


class _FakeCtx:
    """Minimal stand-in for a hermes-agent plugin context."""

    def __init__(self, base_url: str) -> None:
        self.config = {"base_url": base_url, "token": None}
        self.registered: list[dict] = []
        self.system_prompt: str | None = None

    def register_tool(self, *, name, description, parameters, handler) -> None:
        self.registered.append(
            {"name": name, "description": description, "parameters": parameters, "handler": handler}
        )

    def add_system_prompt(self, text: str) -> None:
        self.system_prompt = text


def _live_client(workspace) -> tuple[TestClient, DomainExpertClient]:
    setup = HarnessAPI(workspace.home)
    setup.init()
    setup.packs.activate_bundled("sourdough")
    tc = TestClient(create_app(workspace.home))
    return tc, DomainExpertClient(session=tc)


def test_scripted_capture_correct_review_session(workspace):
    tc, client = _live_client(workspace)
    with tc:
        tools = {t.name: t for t in build_tools(client)}
        assert set(tools) == {
            "domain_foundry_capture",
            "domain_foundry_query",
            "domain_foundry_correct",
            "domain_foundry_review_list",
            "domain_foundry_review_resolve",
            "domain_foundry_new_domain",
            "domain_foundry_wizard_reply",
        }

        # 1. CAPTURE — verbatim message routed to sourdough.bake, auto-applied.
        cap = tools["domain_foundry_capture"](
            text="baked a 75% hydration country loaf, bulk 5h, came out great",
            source_ref="hermes-1",
        )
        assert cap["status"] == "applied"
        assert any(r["domain"] == "sourdough" for r in cap["routed"])

        # 2. QUERY — read-only, the bake is visible.
        rows = tools["domain_foundry_query"](domain="sourdough")["rows"]
        assert rows, "expected the captured bake to be queryable"

        # 3. CORRECT — one-message NL amendment; a new revision lands.
        corrected = tools["domain_foundry_correct"](
            text="that bake was 80% hydration not 75"
        )
        assert corrected.get("error") is None
        assert corrected["action"] in {"amend", "correct"}
        assert corrected["applied"] is True or corrected["revision"] is not None

        # 4. REVIEW — queue + SLO counters are reachable through the adapter.
        review = tools["domain_foundry_review_list"](include_diff=True)
        assert "items" in review
        stats = client.review_stats()
        assert "pending" in stats

        # Resolve any queued item to prove the resolve tool round-trips.
        for item in review["items"]:
            approval_id = item.get("approval_id") or item.get("id")
            if approval_id:
                res = tools["domain_foundry_review_resolve"](
                    approval_id=approval_id, decision="approved"
                )
                assert res.get("error") is None
                break


def test_correction_reflected_in_canonical_object(workspace):
    """The corrected value is durably visible via the read surface."""
    tc, client = _live_client(workspace)
    with tc:
        tools = {t.name: t for t in build_tools(client)}
        tools["domain_foundry_capture"](
            text="baked a 75% hydration country loaf, bulk 5h, came out great",
            source_ref="hermes-2",
        )
        tools["domain_foundry_correct"](text="that bake was 80% hydration not 75")

        # Find the canonical bake uid and confirm hydration == 80 via detail API.
        r = tc.get("/api/blocks/sourdough/bakes/data")
        assert r.status_code == 200
        rowset = r.json()
        uids: list[str] = []
        for row in rowset.get("rows", []):
            uid = row.get("object_uid") or row.get("uid") or row.get("id")
            if uid:
                uids.append(str(uid))
        assert uids, f"no bake rows found: {rowset}"
        detail = tc.get(f"/api/objects/sourdough/bake/{uids[0]}").json()
        assert float(detail["fields"]["hydration"]) == 80.0


def test_register_wires_tools_and_guidance(workspace):
    tc, _ = _live_client(workspace)
    with tc:
        ctx = _FakeCtx(base_url="http://testserver")
        # Inject the live session so register()'s client talks to the app.
        result = register(ctx, client=DomainExpertClient(session=tc))
        assert result.supported_hermes_agent == SUPPORTED_HERMES_AGENT
        assert len(result.tools) == 7
        assert len(ctx.registered) == 7
        assert ctx.system_prompt == CAPTURE_FIRST_GUIDANCE
        # A registered handler actually works end-to-end.
        capture = next(r for r in ctx.registered if r["name"] == "domain_foundry_capture")
        receipt = capture["handler"](text="fed the rye starter")
        assert "entry_id" in receipt


def test_supported_version_range_declared():
    assert SUPPORTED_HERMES_AGENT.startswith(">=")
    assert "<" in SUPPORTED_HERMES_AGENT
