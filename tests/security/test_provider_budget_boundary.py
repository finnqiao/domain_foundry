"""Independent black-box billing checks. All HTTP is synthetic and local."""

import sqlite3

import httpx
import pytest

from domain_foundry_core.ledger.migrate import init_workspace
from domain_foundry_core.llm import provider as llm
from domain_foundry_core.paths import Workspace


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(tmp_path))
    for k in ["DAILY", "ROUTINE", "SOTA"]:
        monkeypatch.setenv(f"DOMAIN_FOUNDRY_{k}_COST_CAP", "1")
    init_workspace(tmp_path)
    return Workspace(tmp_path).ledger_db


def ledger_rows(path, table):
    with sqlite3.connect(path) as c:
        c.row_factory = sqlite3.Row
        return [dict(row) for row in c.execute(f"SELECT * FROM {table}")]


def provider(kind, model=None):
    if kind == "openai":
        return llm.OpenAICompatibleProvider(
            api_key="synthetic-only",
            default_model=model or "gpt-4o-mini",
            base_url="https://api.openai.com/v1",
        )
    return llm.AnthropicProvider(
        api_key="synthetic-only",
        default_model=model or "claude-haiku-4-5",
        base_url="https://api.anthropic.com",
    )


def response(kind, url, *, usage=True, valid=True):
    text = "{}" if valid else "this is not json"
    body = (
        {"choices": [{"message": {"content": text}}]}
        if kind == "openai"
        else {"content": [{"type": "text", "text": text}]}
    )
    if usage:
        body["usage"] = (
            {"prompt_tokens": 11, "completion_tokens": 7}
            if kind == "openai"
            else {"input_tokens": 11, "output_tokens": 7}
        )
    return httpx.Response(200, json=body, request=httpx.Request("POST", url))


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
def test_pre_dispatch_hold_and_explicit_output_cap(kind, monkeypatch, isolated_workspace):
    seen = []

    def post(url, **kwargs):
        rows = ledger_rows(isolated_workspace, "cost_reservation")
        assert any(row["status"] == "held" and row["amount_usd"] > 0 for row in rows), (
            "paid POST lacks durable reservation"
        )
        body = kwargs["json"]
        ceiling = body.get("max_completion_tokens", body.get("max_tokens"))
        assert isinstance(ceiling, int) and not isinstance(ceiling, bool) and ceiling > 0, (
            "paid POST lacks enforced output ceiling"
        )
        seen.append(body)
        return response(kind, url)

    monkeypatch.setattr(httpx, "post", post)
    provider(kind).complete_json(system="synthetic", user="synthetic")
    assert len(seen) == 1
    assert sum(row["cost_usd"] for row in ledger_rows(isolated_workspace, "cost_ledger")) > 0


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
@pytest.mark.parametrize(
    "model", ["completely-unpriced", "gpt-4o-mini-unpriced", "claude-haiku-4-5-unpriced"]
)
def test_unknown_exact_model_never_dispatches(kind, model, monkeypatch):
    seen = []

    def post(url, **kwargs):
        seen.append(url)
        return response(kind, url)

    monkeypatch.setattr(httpx, "post", post)
    try:
        provider(kind, model).complete_json(system="synthetic", user="synthetic")
    except Exception:
        pass
    assert not seen, "unknown model dispatched paid HTTP"


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
def test_unavailable_ledger_never_dispatches(kind, monkeypatch, isolated_workspace):
    isolated_workspace.unlink()
    seen = []
    monkeypatch.setattr(httpx, "post", lambda url, **kw: seen.append(url) or response(kind, url))
    try:
        provider(kind).complete_json(system="synthetic", user="synthetic")
    except Exception:
        pass
    assert not seen, "missing ledger dispatched paid HTTP"


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
def test_missing_usage_retains_positive_hold(kind, monkeypatch, isolated_workspace):
    monkeypatch.setattr(httpx, "post", lambda url, **kw: response(kind, url, usage=False))
    try:
        provider(kind).complete_json(system="synthetic", user="synthetic")
    except Exception:
        pass
    rows = ledger_rows(isolated_workspace, "cost_reservation")
    assert any(row["status"] == "held" and row["amount_usd"] > 0 for row in rows), (
        "missing usage discarded the billing liability"
    )


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
def test_successful_billable_http_with_bad_json_is_not_free(kind, monkeypatch, isolated_workspace):
    seen = []

    def post(url, **kwargs):
        seen.append(url)
        return response(kind, url, valid=False)

    monkeypatch.setattr(httpx, "post", post)
    try:
        provider(kind).complete_json(system="synthetic", user="synthetic")
    except Exception:
        pass
    assert seen
    rows = ledger_rows(isolated_workspace, "cost_ledger")
    assert len(rows) == len(seen), "parse failure hid known billed usage"
    assert all(row["cost_usd"] > 0 for row in rows)


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
def test_timeout_leaves_every_dispatched_attempt_held(kind, monkeypatch, isolated_workspace):
    seen = []

    def post(url, **kwargs):
        seen.append(url)
        raise httpx.ReadTimeout("synthetic timeout")

    monkeypatch.setattr(httpx, "post", post)
    try:
        provider(kind).complete_json(system="synthetic", user="synthetic")
    except Exception:
        pass
    assert seen
    rows = ledger_rows(isolated_workspace, "cost_reservation")
    assert len([r for r in rows if r["status"] == "held"]) == len(seen), (
        "timeout or retry escaped durable accounting"
    )


def test_router_explicit_cap_is_an_admission_limit(monkeypatch, isolated_workspace):
    from domain_foundry_core.packs.registry import PackRegistry
    from domain_foundry_core.routing.router import Router

    ws = Workspace(isolated_workspace.parent.parent)
    registry = PackRegistry(ws)
    registry.activate_bundled("plants")
    seen = []
    monkeypatch.setattr(
        httpx, "post", lambda url, **kw: seen.append(url) or response("openai", url)
    )
    router = Router(ws, registry=registry, llm=provider("openai"), cost_cap=0.000001)
    router.route_text(
        "please interpret this unstructured plant note that is definitely long enough to force the L2 path rather than a simple L1-only short care event"
    )
    assert not seen, "explicit Router cost_cap was bypassed by transport default budget"


def test_explicit_provider_home_controls_actual_ledger(tmp_path, monkeypatch, isolated_workspace):
    other = tmp_path / "explicit-other"
    init_workspace(other)
    selected = Workspace(other).ledger_db
    monkeypatch.setattr(httpx, "post", lambda url, **kw: response("openai", url))
    real = llm.OpenAICompatibleProvider(
        api_key="synthetic-only",
        default_model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        home=other,
    )
    real.complete_json(system="synthetic", user="synthetic")
    assert len(ledger_rows(selected, "cost_ledger")) == 1
    assert ledger_rows(isolated_workspace, "cost_ledger") == []


def test_capture_live_then_cassette_replay_never_double_bills(
    tmp_path, monkeypatch, isolated_workspace
):
    from domain_foundry_core.api.harness import HarnessAPI

    api = HarnessAPI(tmp_path)
    api.init()
    api.packs.activate_bundled("plants")
    cached = llm.CassetteProvider(provider("openai"), tmp_path / "review-cassettes", mode="record")
    api.router.llm = cached
    seen = []
    monkeypatch.setattr(
        httpx, "post", lambda url, **kw: seen.append(url) or response("openai", url)
    )
    text = "please interpret this unstructured plant note that is definitely long enough to force the L2 path rather than a simple L1-only short care event"
    one = api.captures.capture(text, channel="cli", source_ref="synthetic-1")
    first = api.router.route_entry(one.entry_id, text)
    assert len(seen) == 1
    assert len(ledger_rows(isolated_workspace, "cost_ledger")) == 1, "live call double-accounted"
    cached.mode = "replay"
    two = api.captures.capture(text, channel="cli", source_ref="synthetic-2")
    second = api.router.route_entry(two.entry_id, text)
    assert len(seen) == 1
    assert len(ledger_rows(isolated_workspace, "cost_ledger")) == 1, (
        "replay charged historical usage again"
    )
    assert first.cost_usd > 0
    assert second.cost_usd == 0, "replay cost UI must not claim new paid spend"


def test_parallel_paid_attempts_do_not_overbook(monkeypatch, isolated_workspace):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setenv("DOMAIN_FOUNDRY_DAILY_COST_CAP", "0.009")
    seen = []
    lock = threading.Lock()

    def post(url, **kwargs):
        with lock:
            seen.append(url)
        raise httpx.ReadTimeout("synthetic timeout")

    monkeypatch.setattr(httpx, "post", post)

    def run(_):
        try:
            provider("openai").complete_json(system="synthetic", user="synthetic")
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(run, range(24)))
    assert len(seen) == 1, "parallel requests escaped reservation cap"
    rows = ledger_rows(isolated_workspace, "cost_reservation")
    assert len(rows) == 1 and rows[0]["status"] == "held"


@pytest.mark.parametrize(
    "url,dialect,model,limits",
    [
        (
            "https://api.openai.com/v1/chat/completions",
            "unknown-dialect",
            "gpt-4o-mini",
            {"max_completion_tokens": 128},
        ),
        (
            "https://api.openai.com:8443/v1/chat/completions",
            "openai_compatible",
            "gpt-4o-mini",
            {"max_completion_tokens": 128},
        ),
        (
            "https://api.openai.com/v1/unknown",
            "openai_compatible",
            "gpt-4o-mini",
            {"max_completion_tokens": 128},
        ),
        (
            "https://api.openai.com/v1/chat/completions?unexpected=1",
            "openai_compatible",
            "gpt-4o-mini",
            {"max_completion_tokens": 128},
        ),
        (
            "https://api.openai.com/v1/chat/completions",
            "anthropic",
            "claude-haiku-4-5",
            {"max_tokens": 128},
        ),
        ("https://api.anthropic.com/v1/messages", "anthropic", "gpt-4o-mini", {"max_tokens": 128}),
        (
            "https://api.deepseek.com/chat/completions",
            "openai_compatible",
            "gpt-4o-mini",
            {"max_tokens": 128},
        ),
        (
            "https://api.openai.com/v1/chat/completions",
            "openai_compatible",
            "gpt-4o-mini",
            {"max_completion_tokens": 128, "max_tokens": 16384},
        ),
    ],
)
def test_unapproved_transport_shapes_cannot_dispatch(
    url, dialect, model, limits, monkeypatch, isolated_workspace
):
    from domain_foundry_core.llm.budget import post_json

    seen = []
    monkeypatch.setattr(
        httpx, "post", lambda target, **kw: seen.append(target) or response("openai", target)
    )
    body = {"model": model, "messages": [{"role": "user", "content": "synthetic"}], **limits}
    try:
        post_json(
            url,
            headers={"Authorization": "synthetic-only"},
            body=body,
            timeout=1,
            home=isolated_workspace.parent.parent,
            tier="routine",
            dialect=dialect,
        )
    except Exception:
        pass
    assert not seen, "transport schema / billing assumptions were not validated before dispatch"


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
@pytest.mark.parametrize("bad", [None, -1, True, 1.5, "12"])
def test_malformed_usage_cannot_release_any_hold(kind, bad, monkeypatch, isolated_workspace):
    seen = []

    def post(url, **kwargs):
        seen.append(url)
        result = response(kind, url)
        payload = result.json()
        payload["usage"]["prompt_tokens" if kind == "openai" else "input_tokens"] = bad
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    try:
        provider(kind).complete_json(system="synthetic", user="synthetic")
    except Exception:
        pass
    assert seen
    rows = ledger_rows(isolated_workspace, "cost_reservation")
    assert len(rows) == len(seen) and all(r["status"] == "held" for r in rows)
    assert ledger_rows(isolated_workspace, "cost_ledger") == []


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
def test_reported_usage_overrun_latches_future_dispatch(kind, monkeypatch, isolated_workspace):
    seen = []

    def post(url, **kwargs):
        seen.append(url)
        payload = response(kind, url).json()
        payload["usage"]["completion_tokens" if kind == "openai" else "output_tokens"] = 100000
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    provider(kind).complete_json(system="synthetic", user="synthetic")
    assert len(seen) == 1
    assert ledger_rows(isolated_workspace, "cost_reservation")[0]["status"] == "overrun"
    try:
        provider(kind).complete_json(system="synthetic", user="synthetic")
    except Exception:
        pass
    assert len(seen) == 1


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
def test_settlement_storage_error_retains_all_dispatched_liability(
    kind, monkeypatch, isolated_workspace
):
    with sqlite3.connect(isolated_workspace) as conn:
        conn.execute(
            "CREATE TRIGGER review_settlement_failure BEFORE INSERT ON cost_ledger BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END"
        )
    seen = []
    monkeypatch.setattr(httpx, "post", lambda url, **kw: seen.append(url) or response(kind, url))
    try:
        provider(kind).complete_json(system="synthetic", user="synthetic")
    except Exception:
        pass
    assert seen
    rows = ledger_rows(isolated_workspace, "cost_reservation")
    assert len(rows) == len(seen) and all(r["status"] == "held" for r in rows)
    assert ledger_rows(isolated_workspace, "cost_ledger") == []
