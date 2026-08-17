"""Conformance tests for the hermes-agent adapter (plan §11 P8; ADR-006).

Drives a scripted agent session — capture → correct → review — twice: once
through the **in-process** ``LocalHarnessClient`` (legal only while this
adapter passes the Gate-1 conformance suite, see Slice 1), and once through
the HTTP ``DomainExpertClient`` running against the real FastAPI app via
``TestClient`` — the seed of Gate-1's HTTPDriver.
"""

from __future__ import annotations

from domain_foundry_hermes_agent import LocalHarnessClient, build_tools
from domain_foundry_hermes_agent.plugin import (
    CAPTURE_FIRST_GUIDANCE,
    SUPPORTED_HERMES_AGENT,
    register,
)

from domain_foundry_core.api.harness import HarnessAPI


class _FakeCtx:
    """Minimal stand-in for a hermes-agent plugin context."""

    def __init__(self, home: str | None = None) -> None:
        self.config = {"home": home, "token": None}
        self.registered: list[dict] = []
        self.system_prompt: str | None = None

    def register_tool(self, *, name, description, parameters, handler) -> None:
        self.registered.append(
            {"name": name, "description": description, "parameters": parameters, "handler": handler}
        )

    def add_system_prompt(self, text: str) -> None:
        self.system_prompt = text


def _local_client(workspace) -> LocalHarnessClient:
    setup = HarnessAPI(workspace.home)
    setup.init()
    setup.packs.activate_bundled("sourdough")
    # No FastAPI app, no TestClient, no port 8787: the whole session below
    # runs with zero HTTP — that is the mesh P0 exit criterion.
    return LocalHarnessClient(workspace.home)


def test_scripted_capture_correct_review_session(workspace):
    client = _local_client(workspace)
    tools = {t.name: t for t in build_tools(client)}
    assert set(tools) >= {
        "domain_foundry_capture",
        "domain_foundry_query",
        "domain_foundry_ask",
        "domain_foundry_correct",
        "domain_foundry_review_list",
        "domain_foundry_review_resolve",
        "domain_foundry_new_domain",
        "domain_foundry_wizard_reply",
        "domain_foundry_atlas_search",
        "domain_foundry_inspect_pack",
        "domain_foundry_suggest",
        "domain_foundry_apply_pack_edit",
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
    """The corrected value is durably visible via the in-process read surface."""
    client = _local_client(workspace)
    tools = {t.name: t for t in build_tools(client)}
    tools["domain_foundry_capture"](
        text="baked a 75% hydration country loaf, bulk 5h, came out great",
        source_ref="hermes-2",
    )
    tools["domain_foundry_correct"](text="that bake was 80% hydration not 75")

    api = HarnessAPI(workspace.home)
    rowset = api.block_view_data("sourdough", "bakes")
    uids = [
        str(row.get("object_uid") or row.get("uid") or row.get("id"))
        for row in rowset.get("rows", [])
        if row.get("object_uid") or row.get("uid") or row.get("id")
    ]
    assert uids, f"no bake rows found: {rowset}"
    detail = api.object_detail("sourdough", "bake", uids[0])
    assert float(detail["fields"]["hydration"]) == 80.0


def test_http_surface_serves_reads_and_writes(workspace):
    """The FastAPI app serves the same read/write contract as the SPA."""
    from fastapi.testclient import TestClient

    from domain_foundry_core.api.app import create_app

    client = _local_client(workspace)
    tools = {t.name: t for t in build_tools(client)}
    tools["domain_foundry_capture"](
        text="baked a 75% hydration country loaf, bulk 5h",
        source_ref="hermes-3",
    )
    with TestClient(create_app(workspace.home)) as tc:
        r = tc.get("/api/query", params={"domain": "sourdough"})
        assert r.status_code == 200
        assert r.json()["rows"]
        posted = tc.post("/api/capture", json={"text": "fed the rye starter", "channel": "web"})
        assert posted.status_code == 200


def test_http_driver_capture_correct_review_journey(workspace):
    """Gate-1 seed: DomainExpertClient drives the same journey over real HTTP."""
    from domain_foundry_hermes_agent import DomainExpertClient
    from fastapi.testclient import TestClient

    from domain_foundry_core.api.app import create_app

    setup = HarnessAPI(workspace.home)
    setup.init()
    setup.packs.activate_bundled("sourdough")

    app = create_app(workspace.home, enable_drain_loop=False)
    client = DomainExpertClient(session=TestClient(app))

    # 1. CAPTURE over HTTP — routed to sourdough.bake, auto-applied.
    cap = client.capture(
        "baked a 75% hydration country loaf, bulk 5h, came out great",
        source_ref="hermes-http-1",
    )
    assert cap["status"] == "applied"
    assert any(r["domain"] == "sourdough" for r in cap["routed"])

    # 2. QUERY over HTTP.
    assert client.query(domain="sourdough")["rows"]

    # 3. CORRECT over HTTP — NL amendment lands a revision.
    corrected = client.correct(text="that bake was 80% hydration not 75")
    assert corrected.get("error") is None
    assert corrected["applied"] is True or corrected["revision"] is not None

    # 4. REVIEW over HTTP — queue + stats + (if pending) a resolve round-trip.
    review = client.review_list(include_diff=True)
    assert "items" in review
    stats = client.review_stats()
    assert "pending" in stats
    for item in review["items"]:
        approval_id = item.get("approval_id") or item.get("id")
        if approval_id:
            res = client.review_resolve(approval_id, decision="approved")
            assert res.get("error") is None
            break


def test_register_wires_tools_and_guidance(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    monkeypatch.delenv("DOMAIN_FOUNDRY_URL", raising=False)
    HarnessAPI(workspace.home).init()

    ctx = _FakeCtx()
    result = register(ctx)  # no injected client: default resolution = in-process
    assert isinstance(result.client, LocalHarnessClient)
    assert result.supported_hermes_agent == SUPPORTED_HERMES_AGENT
    names = {t.name for t in result.tools}
    assert names >= {
        "domain_foundry_capture",
        "domain_foundry_query",
        "domain_foundry_ask",
        "domain_foundry_correct",
        "domain_foundry_review_list",
        "domain_foundry_review_resolve",
        "domain_foundry_new_domain",
        "domain_foundry_wizard_reply",
        "domain_foundry_atlas_search",
        "domain_foundry_inspect_pack",
        "domain_foundry_suggest",
        "domain_foundry_apply_pack_edit",
    }
    assert {r["name"] for r in ctx.registered} == names
    assert ctx.system_prompt == CAPTURE_FIRST_GUIDANCE
    # A registered handler actually works end-to-end, with no server running.
    capture = next(r for r in ctx.registered if r["name"] == "domain_foundry_capture")
    receipt = capture["handler"](text="fed the rye starter")
    assert "entry_id" in receipt


def test_explicit_url_still_selects_http_client(workspace, monkeypatch):
    from domain_foundry_hermes_agent import DomainExpertClient

    monkeypatch.setenv("DOMAIN_FOUNDRY_URL", "http://127.0.0.1:8787")
    ctx = _FakeCtx()
    result = register(ctx)
    assert isinstance(result.client, DomainExpertClient)


def test_supported_version_range_declared():
    assert SUPPORTED_HERMES_AGENT.startswith(">=")
    assert "<" in SUPPORTED_HERMES_AGENT
