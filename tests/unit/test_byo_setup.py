"""Bring-your-own-key setup: provider registry, config precedence, request shape.

The load-bearing case here is the Anthropic request shape. Current Claude models
reject ``temperature`` with HTTP 400, and the router catches LLM failures into
the keyword heuristic — so a wrong shape does not surface as an error, it
surfaces as quietly worse routing that looks identical to "no key configured".
These tests pin the shape per model.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import httpx
import pytest

from domain_foundry_core.config import (
    LLMConfig,
    TierSettings,
    config_path,
    load_llm_config,
    redacted_llm_config,
    save_llm_config,
)
from domain_foundry_core.llm.provider import (
    AnthropicProvider,
    HeuristicProvider,
    LLMError,
    TieredLLMProvider,
    resolve_tier_settings,
)
from domain_foundry_core.llm.providers import (
    all_providers,
    anthropic_request_caps,
    is_anthropic_base,
)
from domain_foundry_core.onboarding import (
    build_config,
    detect_env_keys,
    is_already_configured,
    probe_tier,
    resolved_status,
)

_KEY_ENVS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENROUTER_API_KEY",
    "DOMAIN_FOUNDRY_SOTA_API_KEY",
    "DOMAIN_FOUNDRY_ROUTINE_API_KEY",
    "DOMAIN_FOUNDRY_LLM_API_KEY",
    "DOMAIN_FOUNDRY_SOTA_MODEL",
    "DOMAIN_FOUNDRY_ROUTINE_MODEL",
    "DOMAIN_FOUNDRY_SOTA_BASE_URL",
    "DOMAIN_FOUNDRY_ROUTINE_BASE_URL",
    "DOMAIN_FOUNDRY_LLM_BASE_URL",
    "DOMAIN_FOUNDRY_LLM_MODEL",
    "DOMAIN_FOUNDRY_SOTA_EFFORT",
    "DOMAIN_FOUNDRY_LLM",
    "DOMAIN_FOUNDRY_CASSETTE",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No inherited provider config — otherwise a dev machine's real key leaks in."""
    for name in _KEY_ENVS:
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Provider registry / request-shape capabilities
# ---------------------------------------------------------------------------


def test_registry_has_stable_ids_and_anthropic_first() -> None:
    ids = [p.id for p in all_providers()]
    assert ids[0] == "anthropic", "setup preselects the first entry; keep it stable"
    assert "none" in ids, "an offline / no-model choice must always be offerable"
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize(
    "model,rejects_sampling",
    [
        ("claude-opus-5", True),
        ("claude-opus-4-8", True),
        ("claude-opus-4-7", True),
        ("claude-sonnet-5", True),
        ("claude-fable-5", True),
        # Older models still accept sampling params.
        ("claude-haiku-4-5", False),
        ("claude-opus-4-6", False),
        ("claude-sonnet-4-6", False),
        ("claude-sonnet-4-5", False),
    ],
)
def test_sampling_param_support_per_model(model: str, rejects_sampling: bool) -> None:
    assert anthropic_request_caps(model).rejects_sampling_params is rejects_sampling


def test_unknown_model_gets_the_conservative_shape() -> None:
    """An unrecognised model is likelier newer than older.

    Guessing "accepts sampling" on a future model 400s every sota call, and the
    router would swallow it into keyword routing. Default to the safe shape.
    """
    caps = anthropic_request_caps("claude-opus-9")
    assert caps.rejects_sampling_params is True
    assert caps.supports_effort is False
    assert caps.supports_json_schema is False


def test_gateway_prefixed_model_ids_resolve() -> None:
    """OpenRouter-style ids must not read as unknown models."""
    assert anthropic_request_caps("anthropic/claude-opus-5").rejects_sampling_params
    assert anthropic_request_caps("anthropic/claude-haiku-4-5").supports_json_schema


def test_effort_is_narrower_than_people_assume() -> None:
    # Haiku 4.5 errors on effort; Opus 5 takes it.
    assert anthropic_request_caps("claude-opus-5").supports_effort is True
    assert anthropic_request_caps("claude-haiku-4-5").supports_effort is False


def test_is_anthropic_base_discriminates_gateways() -> None:
    assert is_anthropic_base("https://api.anthropic.com")
    assert not is_anthropic_base("https://openrouter.ai/api/v1")
    assert not is_anthropic_base("http://127.0.0.1:11434/v1")
    assert not is_anthropic_base(None)


# ---------------------------------------------------------------------------
# Config file
# ---------------------------------------------------------------------------


def test_config_round_trip(tmp_path: Path) -> None:
    cfg = build_config(provider_id="anthropic")
    save_llm_config(cfg, tmp_path)
    loaded = load_llm_config(tmp_path)
    assert loaded.provider == "anthropic"
    assert loaded.mode == "live"
    assert loaded.routine.model == "claude-haiku-4-5"
    assert loaded.sota.model == "claude-opus-5"


def test_key_is_not_written_by_default(tmp_path: Path) -> None:
    cfg = build_config(provider_id="anthropic", api_key="sk-ant-secret-value")
    path = save_llm_config(cfg, tmp_path, store_keys=False)
    text = path.read_text(encoding="utf-8")
    assert "sk-ant-secret-value" not in text
    assert load_llm_config(tmp_path).sota.api_key is None
    # It still records *where* to find the key.
    assert load_llm_config(tmp_path).sota.api_key_env == "ANTHROPIC_API_KEY"


def test_stored_key_is_chmod_600(tmp_path: Path) -> None:
    cfg = build_config(provider_id="anthropic", api_key="sk-ant-secret-value")
    path = save_llm_config(cfg, tmp_path, store_keys=True)
    assert "sk-ant-secret-value" in path.read_text(encoding="utf-8")
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, f"secret file should be 0600, got {oct(mode)}"


def test_malformed_config_does_not_brick_the_cli(tmp_path: Path) -> None:
    config_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    config_path(tmp_path).write_text("this is not [valid toml", encoding="utf-8")
    assert load_llm_config(tmp_path) == LLMConfig()


def test_redaction_masks_inline_keys() -> None:
    cfg = build_config(provider_id="anthropic", api_key="sk-ant-secret")
    red = redacted_llm_config(cfg)
    assert red.sota.api_key == "***"
    assert red.routine.api_key == "***"


# ---------------------------------------------------------------------------
# Resolution precedence: env > config file > registry default
# ---------------------------------------------------------------------------


def test_env_beats_config_file(tmp_path: Path, clean_env: None, monkeypatch) -> None:
    save_llm_config(build_config(provider_id="anthropic"), tmp_path)
    monkeypatch.setenv("DOMAIN_FOUNDRY_SOTA_MODEL", "claude-sonnet-5")
    settings = resolve_tier_settings("sota", home=tmp_path)
    assert settings.model == "claude-sonnet-5"


def test_config_file_beats_registry_default(tmp_path: Path, clean_env: None) -> None:
    save_llm_config(build_config(provider_id="deepseek"), tmp_path)
    routine = resolve_tier_settings("routine", home=tmp_path)
    assert routine.model == "deepseek-chat"
    assert routine.base_url == "https://api.deepseek.com/v1"
    # The sota tier follows the chosen provider, not a hard-coded Anthropic default.
    assert resolve_tier_settings("sota", home=tmp_path).model == "deepseek-reasoner"


def test_registry_default_when_nothing_configured(tmp_path: Path, clean_env: None) -> None:
    settings = resolve_tier_settings("sota", home=tmp_path)
    assert settings.model == "claude-opus-5"


def test_config_named_env_var_supplies_the_key(
    tmp_path: Path, clean_env: None, monkeypatch
) -> None:
    cfg = build_config(provider_id="anthropic", api_key_env="MY_CUSTOM_KEY_VAR")
    save_llm_config(cfg, tmp_path)
    monkeypatch.setenv("MY_CUSTOM_KEY_VAR", "sk-ant-from-custom-var")
    assert resolve_tier_settings("sota", home=tmp_path).api_key == "sk-ant-from-custom-var"


def test_tiered_provider_honours_config_file(tmp_path: Path, clean_env: None, monkeypatch) -> None:
    """Regression: TieredLLMProvider used to resolve models from env|DEFAULT only.

    A model chosen at setup has to actually be used, otherwise the whole
    onboarding flow writes a file nothing reads.
    """
    save_llm_config(build_config(provider_id="anthropic"), tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    tiered = TieredLLMProvider(home=tmp_path)
    assert tiered.routine_model == "claude-haiku-4-5"
    assert tiered.sota_model == "claude-opus-5"


def test_legacy_env_only_install_still_works(tmp_path: Path, clean_env: None, monkeypatch) -> None:
    """No config file at all — the pre-existing env-var contract is unchanged."""
    monkeypatch.setenv("DOMAIN_FOUNDRY_ROUTINE_API_KEY", "sk-routine")
    monkeypatch.setenv("DOMAIN_FOUNDRY_ROUTINE_MODEL", "deepseek-chat")
    monkeypatch.setenv("DOMAIN_FOUNDRY_ROUTINE_BASE_URL", "https://api.deepseek.com/v1")
    assert not config_path(tmp_path).exists()
    routine = resolve_tier_settings("routine", home=tmp_path)
    assert routine.model == "deepseek-chat"
    assert routine.api_key == "sk-routine"
    assert routine.configured


# ---------------------------------------------------------------------------
# Anthropic request shape
# ---------------------------------------------------------------------------


class _Capture:
    """Record the request body httpx would have posted."""

    def __init__(self, *, status: int = 200, body: dict[str, Any] | None = None) -> None:
        self.status = status
        self.body = body or {
            "content": [{"type": "text", "text": '{"ok": true}'}],
            "usage": {"input_tokens": 5, "output_tokens": 3},
        }
        self.requests: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> httpx.Response:
        self.requests.append(kwargs.get("json") or {})
        request = httpx.Request("POST", url)
        return httpx.Response(self.status, json=self.body, request=request)


def _run(monkeypatch: pytest.MonkeyPatch, capture: _Capture, model: str) -> None:
    monkeypatch.setattr(httpx, "post", capture)
    AnthropicProvider(api_key="sk-test", default_model=model).complete_json(
        system="s", user="u", tier="sota"
    )


def test_opus5_request_omits_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bug this whole change exists for: temperature is a 400 on Opus 5."""
    cap = _Capture()
    _run(monkeypatch, cap, "claude-opus-5")
    body = cap.requests[0]
    assert "temperature" not in body
    assert "top_p" not in body
    assert "top_k" not in body


def test_haiku_request_keeps_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    """Haiku still accepts it, and determinism is worth having on the hot path."""
    cap = _Capture()
    _run(monkeypatch, cap, "claude-haiku-4-5")
    assert cap.requests[0]["temperature"] == 0


def test_effort_only_sent_where_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _Capture()
    _run(monkeypatch, cap, "claude-opus-5")
    assert cap.requests[0]["output_config"] == {"effort": "medium"}

    cap = _Capture()
    _run(monkeypatch, cap, "claude-haiku-4-5")
    assert "output_config" not in cap.requests[0], "effort errors on Haiku 4.5"


def test_effort_is_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOMAIN_FOUNDRY_SOTA_EFFORT", "high")
    cap = _Capture()
    _run(monkeypatch, cap, "claude-opus-5")
    assert cap.requests[0]["output_config"] == {"effort": "high"}


def test_max_tokens_has_headroom_for_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    """Thinking is on by default on Opus 5 and shares the max_tokens budget."""
    cap = _Capture()
    _run(monkeypatch, cap, "claude-opus-5")
    assert cap.requests[0]["max_tokens"] >= 8192


def test_400_retries_without_optional_params(monkeypatch: pytest.MonkeyPatch) -> None:
    """A shape rejection should degrade, not fail the capture."""
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        body = kwargs.get("json") or {}
        calls.append(body)
        request = httpx.Request("POST", url)
        if "output_config" in body:
            return httpx.Response(400, json={"error": {"message": "bad param"}}, request=request)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": '{"ok": true}'}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            request=request,
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    result = AnthropicProvider(api_key="sk", default_model="claude-opus-5").complete_json(
        system="s", user="u", tier="sota"
    )
    assert result.data == {"ok": True}
    assert len(calls) == 2
    assert "output_config" not in calls[1]


def test_401_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auth failures are not fixed by dropping params; retrying doubles latency."""
    cap = _Capture(status=401, body={"error": {"message": "invalid x-api-key"}})
    monkeypatch.setattr(httpx, "post", cap)
    with pytest.raises(LLMError) as excinfo:
        AnthropicProvider(api_key="sk-bad", default_model="claude-opus-5").complete_json(
            system="s", user="u", tier="sota"
        )
    assert len(cap.requests) == 1
    # And the message stays one readable line, not an httpx MDN dump.
    assert "401" in str(excinfo.value)
    assert "\n" not in str(excinfo.value)


def test_refusal_is_surfaced_not_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A classifier decline is HTTP 200 with no content — do not read it as JSON."""
    cap = _Capture(body={"stop_reason": "refusal", "content": [], "usage": {}})
    monkeypatch.setattr(httpx, "post", cap)
    with pytest.raises(LLMError, match="refusal"):
        AnthropicProvider(api_key="sk", default_model="claude-opus-5").complete_json(
            system="s", user="u", tier="sota"
        )


# ---------------------------------------------------------------------------
# Onboarding helpers
# ---------------------------------------------------------------------------


def test_build_config_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="unknown provider"):
        build_config(provider_id="not-a-provider")


def test_offline_provider_records_heuristic_mode() -> None:
    cfg = build_config(provider_id="none")
    assert cfg.mode == "heuristic"
    assert not cfg.routine.configured


def test_single_model_provider_fills_both_tiers() -> None:
    cfg = build_config(provider_id="anthropic", routine_model="claude-haiku-4-5", sota_model=None)
    assert cfg.sota.model  # never leave a tier dead
    assert cfg.routine.model == "claude-haiku-4-5"


def test_detect_env_keys_finds_and_orders(clean_env: None, monkeypatch) -> None:
    assert detect_env_keys() == []
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    detected = [d.provider_id for d in detect_env_keys()]
    # Registry order, not env order — the suggestion must be deterministic.
    assert detected == ["anthropic", "deepseek"]


def test_probe_reports_heuristic_when_no_key(tmp_path: Path, clean_env: None) -> None:
    cfg = build_config(provider_id="anthropic")
    result = probe_tier("sota", home=tmp_path, config=cfg)
    assert result.ok is False
    assert "keyword rules" in result.detail


def test_probe_reports_transport_failure(
    tmp_path: Path, clean_env: None, monkeypatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-bad")

    def boom(url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("dns went away")

    monkeypatch.setattr(httpx, "post", boom)
    result = probe_tier("sota", home=tmp_path, config=build_config(provider_id="anthropic"))
    assert result.ok is False
    assert "dns went away" in result.detail


def test_probe_succeeds_on_json_object(tmp_path: Path, clean_env: None, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-good")
    monkeypatch.setattr(httpx, "post", _Capture())
    result = probe_tier("sota", home=tmp_path, config=build_config(provider_id="anthropic"))
    assert result.ok is True
    assert result.model == "claude-opus-5"


def test_is_already_configured_gates_the_interview(
    tmp_path: Path, clean_env: None, monkeypatch
) -> None:
    assert not is_already_configured(tmp_path)
    save_llm_config(build_config(provider_id="anthropic"), tmp_path)
    assert not is_already_configured(tmp_path), "no key yet"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    assert is_already_configured(tmp_path)


def test_resolved_status_never_leaks_a_key(
    tmp_path: Path, clean_env: None, monkeypatch
) -> None:
    secret = "sk-ant-super-secret-value"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    save_llm_config(build_config(provider_id="anthropic"), tmp_path)
    status = resolved_status(tmp_path)
    assert secret not in json.dumps(status)
    assert status["sota"]["api_key_present"] is True  # type: ignore[index]


def test_probe_uses_the_tier_it_was_asked_about(
    tmp_path: Path, clean_env: None, monkeypatch
) -> None:
    """Routine and sota can be different models; the probe must not conflate them."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-good")
    cap = _Capture()
    monkeypatch.setattr(httpx, "post", cap)
    cfg = build_config(provider_id="anthropic")
    assert probe_tier("routine", home=tmp_path, config=cfg).model == "claude-haiku-4-5"
    assert probe_tier("sota", home=tmp_path, config=cfg).model == "claude-opus-5"
    assert cap.requests[0]["model"] == "claude-haiku-4-5"
    assert cap.requests[1]["model"] == "claude-opus-5"


def test_heuristic_provider_is_what_offline_resolves_to(
    tmp_path: Path, clean_env: None
) -> None:
    from domain_foundry_core.llm.provider import _build_tier_provider

    settings = TierSettings(model="claude-opus-5", base_url="https://api.anthropic.com")
    assert isinstance(_build_tier_provider("sota", settings), HeuristicProvider)


def test_non_anthropic_base_builds_openai_client(clean_env: None) -> None:
    """Pointing a tier at a gateway must not POST {base}/v1/messages."""
    from domain_foundry_core.llm.provider import (
        OpenAICompatibleProvider,
        _build_tier_provider,
    )

    settings = TierSettings(
        model="anthropic/claude-opus-5",
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-or",
    )
    assert isinstance(_build_tier_provider("sota", settings), OpenAICompatibleProvider)


# ---------------------------------------------------------------------------
# The capture path actually honours what setup wrote
# ---------------------------------------------------------------------------


def _configured_home(tmp_path: Path) -> Path:
    """A workspace whose config is complete: provider, models, and a stored key."""
    from dataclasses import replace as dc_replace

    cfg = build_config(provider_id="anthropic")
    cfg = dc_replace(
        cfg,
        routine=dc_replace(cfg.routine, api_key="sk-stored"),
        sota=dc_replace(cfg.sota, api_key="sk-stored"),
    )
    save_llm_config(cfg, tmp_path, store_keys=True)
    return tmp_path


def test_config_mode_live_reaches_the_capture_path(tmp_path: Path, clean_env: None) -> None:
    """Regression: completing setup used to change nothing.

    `get_default_provider` read only the DOMAIN_FOUNDRY_LLM env var, so a user
    who finished setup — key stored, probe green — still got keyword-only
    routing on every capture. A setup flow that writes a file nothing reads is
    worse than no setup flow at all.
    """
    from domain_foundry_core.llm.provider import (
        get_default_provider,
        is_heuristic_provider,
    )

    home = _configured_home(tmp_path)
    provider = get_default_provider(home=home)
    assert not is_heuristic_provider(provider), "config mode=live must go live"


def test_env_llm_mode_still_overrides_config(tmp_path: Path, clean_env: None, monkeypatch) -> None:
    from domain_foundry_core.llm.provider import (
        get_default_provider,
        is_heuristic_provider,
    )

    home = _configured_home(tmp_path)
    monkeypatch.setenv("DOMAIN_FOUNDRY_LLM", "heuristic")
    assert is_heuristic_provider(get_default_provider(home=home))


def test_no_config_and_no_env_stays_heuristic(tmp_path: Path, clean_env: None) -> None:
    """The safe default is unchanged: nothing configured means no spend."""
    from domain_foundry_core.llm.provider import (
        get_default_provider,
        is_heuristic_provider,
    )

    assert is_heuristic_provider(get_default_provider(home=tmp_path))


def test_explicit_home_reads_that_workspaces_config(
    tmp_path: Path, clean_env: None, monkeypatch
) -> None:
    """`--home /elsewhere` must read /elsewhere/config.toml, not the default one."""
    from dataclasses import replace as dc_replace

    from domain_foundry_core.llm.provider import TieredLLMProvider

    other = tmp_path / "other-workspace"
    other.mkdir()
    cfg = build_config(provider_id="anthropic")
    cfg = dc_replace(cfg, sota=dc_replace(cfg.sota, model="claude-sonnet-5"))
    save_llm_config(cfg, other)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")

    assert TieredLLMProvider(home=other).sota_model == "claude-sonnet-5"
    # A different workspace with no config falls back to the registry default.
    assert TieredLLMProvider(home=tmp_path).sota_model == "claude-opus-5"


def test_router_threads_its_workspace_home(tmp_path: Path, clean_env: None) -> None:
    """The Router must not resolve config from the process-default home."""
    from domain_foundry_core.ledger.migrate import ensure_migrated
    from domain_foundry_core.llm.provider import is_heuristic_provider
    from domain_foundry_core.paths import Workspace
    from domain_foundry_core.routing.router import Router

    home = _configured_home(tmp_path)
    ws = Workspace(home)
    ws.ensure_layout()
    ensure_migrated(ws.ledger_db, "ledger")
    ensure_migrated(ws.domains_db, "domains")
    assert not is_heuristic_provider(Router(ws).llm)


def test_resolve_llm_mode_precedence(tmp_path: Path, clean_env: None, monkeypatch) -> None:
    from domain_foundry_core.llm.provider import resolve_llm_mode

    assert resolve_llm_mode(tmp_path) == "heuristic"
    save_llm_config(build_config(provider_id="anthropic"), tmp_path)
    assert resolve_llm_mode(tmp_path) == "live"
    monkeypatch.setenv("DOMAIN_FOUNDRY_LLM", "off")
    assert resolve_llm_mode(tmp_path) == "off"


def test_offline_provider_config_does_not_go_live(tmp_path: Path, clean_env: None) -> None:
    from domain_foundry_core.llm.provider import (
        get_default_provider,
        is_heuristic_provider,
    )

    save_llm_config(build_config(provider_id="none"), tmp_path)
    assert is_heuristic_provider(get_default_provider(home=tmp_path))
