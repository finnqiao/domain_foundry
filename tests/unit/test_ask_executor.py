"""Ask execution uses only parameterized canonical/search read surfaces."""

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.ask.executor import execute
from domain_foundry_core.ask.schema import AskAggregate, AskPlan
from domain_foundry_core.llm.provider import HeuristicProvider
from domain_foundry_core.routing.router import Router


def _ready(workspace) -> HarnessAPI:
    api = HarnessAPI(workspace.home)
    api.init()
    api.packs.activate_bundled("sourdough")
    api.packs.reload()
    api.router = Router(workspace, registry=api.packs, llm=HeuristicProvider())
    api.capture("baked a 75% hydration country loaf", channel="eval")
    api.capture("baked an 80% hydration rye batard", channel="eval")
    return api


def test_aggregate_and_canonical_search(workspace):
    api = _ready(workspace)
    aggregate = execute(
        AskPlan(
            intent="aggregate",
            domain="sourdough",
            object_type="bake",
            aggregate=AskAggregate(op="count"),
        ),
        api.workspace,
        api.packs,
    )
    assert aggregate.aggregate and aggregate.aggregate["value"] == 2
    assert len(aggregate.sources) <= 5

    search = execute(
        AskPlan(
            intent="list",
            domain="sourdough",
            object_type="bake",
            text_query="hydration",
        ),
        api.workspace,
        api.packs,
    )
    assert search.sources
    assert all(source.object_uid for source in search.sources)


def test_empty_and_unsafe_fts_queries_are_read_only(workspace):
    api = _ready(workspace)
    empty = execute(AskPlan(intent="list"), api.workspace, api.packs)
    assert empty.empty is True

    unsafe = execute(
        AskPlan(intent="list", text_query='"; DROP TABLE sourdough__bake; --'),
        api.workspace,
        api.packs,
    )
    assert unsafe.empty is True or isinstance(unsafe.sources, list)
    assert api.block_data.object_rows("sourdough", "bake")
