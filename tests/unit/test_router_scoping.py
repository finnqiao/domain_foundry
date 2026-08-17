"""Interactive routing hints constrain the candidate pack set."""

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.llm.provider import HeuristicProvider
from domain_foundry_core.routing.router import Router
from domain_foundry_core.security.store import connect_ro


def _ready(workspace) -> HarnessAPI:
    api = HarnessAPI(workspace.home)
    api.init()
    api.packs.activate_bundled("sourdough")
    api.packs.activate_bundled("plants")
    api.packs.reload()
    api.router = Router(workspace, registry=api.packs, llm=HeuristicProvider())
    return api


def _domains(result) -> set[str]:
    return {span.domain for span in result.spans}


def test_only_domains_never_routes_outside_scope(workspace):
    api = _ready(workspace)
    result = api.router.route_text(
        "watered the monstera, soil was dry", only_domains=["sourdough"]
    )
    assert _domains(result) <= {"sourdough", "_unfiled", "_ledger"}


def test_scope_preserves_matching_and_unknown_hints_fall_back(workspace):
    api = _ready(workspace)
    text = "fed the rye starter"
    global_result = api.router.route_text(text)
    scoped_result = api.router.route_text(text, only_domains=["sourdough"])
    stale_result = api.router.route_text(text, only_domains=["not_installed"])
    def shape(result):
        return [
            (span.domain, span.object_type, span.operation) for span in result.spans
        ]
    assert shape(scoped_result) == shape(global_result)
    assert shape(stale_result) == shape(global_result)


def test_scoped_miss_still_persists_an_unfiled_card(workspace):
    api = _ready(workspace)
    receipt = api.capture(
        "zzz unrelated administrative chatter",
        channel="web",
        domain_hint="sourdough",
    )
    assert receipt.status == "unfiled"
    conn = connect_ro(workspace.ledger_db)
    try:
        row = conn.execute(
            "SELECT status FROM unfiled_card WHERE entry_id = ?",
            (receipt.entry_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None and row["status"] == "open"
