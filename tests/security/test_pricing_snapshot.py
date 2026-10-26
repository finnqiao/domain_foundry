"""Current documented prices govern paid admission, not historical aliases."""

import sqlite3

import httpx
import pytest

from domain_foundry_core.ledger.migrate import init_workspace
from domain_foundry_core.llm.budget import BudgetAdmissionError, exact_price, post_json
from domain_foundry_core.paths import Workspace


@pytest.mark.parametrize(
    ("base", "model", "response_model", "rates"),
    [
        ("https://api.deepseek.com", "deepseek-flash", "deepseek-flash", (0.30, 1.20)),
        ("https://api.deepseek.com", "deepseek-v4-flash", "deepseek-flash", (0.30, 1.20)),
        ("https://api.deepseek.com", "deepseek-v4-pro", "deepseek-v4-pro", (1.32, 3.96)),
        ("https://openrouter.ai/api/v1", "z-ai/glm-5.2", "z-ai/glm-5.2", (2.31, 8.0)),
        ("https://openrouter.ai/api/v1", "anthropic/claude-opus-5", "anthropic/claude-opus-5", (20.0, 50.0)),
    ],
)
def test_current_peak_and_gateway_maxima_are_reserved_before_dispatch(
    tmp_path, monkeypatch, base, model, response_model, rates
):
    monkeypatch.setenv("DOMAIN_FOUNDRY_DAILY_COST_CAP", "2")
    monkeypatch.setenv("DOMAIN_FOUNDRY_SOTA_COST_CAP", "2")
    init_workspace(tmp_path)
    ledger = Workspace(tmp_path).ledger_db
    url = base + "/chat/completions"
    price = exact_price(model, url)
    assert (price.input_per_million, price.output_per_million) == rates
    calls = []

    def dispatch(request_url, **kwargs):
        calls.append(request_url)
        with sqlite3.connect(ledger) as conn:
            amount, status = conn.execute("SELECT amount_usd, status FROM cost_reservation").fetchone()
        assert status == "held"
        assert amount >= 8192 * rates[1] / 1_000_000
        return httpx.Response(
            200,
            request=httpx.Request("POST", request_url),
            json={"model": response_model, "usage": {"prompt_tokens": 100, "completion_tokens": 50}},
        )

    monkeypatch.setattr(httpx, "post", dispatch)
    payload = post_json(
        url, headers={}, body={"model": model, "max_tokens": 8192,
                              "messages": [{"role": "user", "content": "synthetic-only"}]},
        timeout=1, home=tmp_path, tier="sota", dialect="openai_compatible",
    )
    assert calls == [url]
    assert payload["_domain_foundry_cost_usd"] == pytest.approx((100 * rates[0] + 50 * rates[1]) / 1_000_000)
    with sqlite3.connect(ledger) as conn:
        assert conn.execute("SELECT status FROM cost_reservation").fetchone()[0] == "settled"


@pytest.mark.parametrize(
    ("url", "model"),
    [
        ("https://api.deepseek.com/chat/completions", "deepseek-chat"),
        ("https://api.deepseek.com/chat/completions", "deepseek-reasoner"),
        ("https://api.deepseek.com/chat/completions", "deepseek-flash-unreviewed"),
        ("https://openrouter.ai/api/v1/chat/completions", "anthropic/claude-sonnet-5"),
        ("https://eu.openrouter.ai/api/v1/chat/completions", "deepseek/deepseek-v4-flash"),
        ("https://openrouter.ai/api/v1/chat/completions", "z-ai/glm-5.2:fast"),
    ],
)
def test_retired_or_unreviewed_routes_never_dispatch(tmp_path, monkeypatch, url, model):
    calls = []
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(BudgetAdmissionError):
        post_json(
            url, headers={}, body={"model": model, "max_tokens": 8192,
                                  "messages": [{"role": "user", "content": "synthetic-only"}]},
            timeout=1, home=tmp_path, tier="sota", dialect="openai_compatible",
        )
    assert calls == []
