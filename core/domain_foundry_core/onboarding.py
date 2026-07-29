"""Onboarding logic for ``domain-foundry setup`` — bring your own key.

Kept separate from the CLI so every step is testable without a TTY: the CLI
does prompting and printing, this module does detection, assembly, probing and
status. Two audiences, one flow:

* **From scratch** — the interactive path walks provider → key → models → a live
  probe → what to do first, and writes the answers to the workspace config.
* **Already seasoned** — the same entry point takes flags and skips every
  question, and exits early when the environment is already complete. Expert
  setups that live in a dotfile keep working untouched; env vars still win over
  anything written here.

The probe matters more than it looks. Without it a wrong key or a renamed model
surfaces as *silence* — the router catches LLM failures into the keyword
heuristic, so captures keep succeeding with quietly worse routing. Validating at
setup time is what turns that into an error the user can act on.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from domain_foundry_core.config import (
    LLMConfig,
    TierSettings,
    config_path,
    load_llm_config,
)
from domain_foundry_core.llm.providers import (
    ProviderSpec,
    all_providers,
    get_provider,
)

# What a newcomer can do first, in the order setup offers them. Each maps to a
# real command so the flow can either run it or print it verbatim.
NEXT_STEPS: tuple[tuple[str, str, str], ...] = (
    (
        "pack",
        "Start from a ready-made log (food, plants, sourdough, travel)",
        "domain-foundry pack add food",
    ),
    (
        "new",
        "Describe a log in your own words and have one built",
        'domain-foundry new-domain "track my sourdough journey"',
    ),
    (
        "ingest",
        "Pull in notes you already have (a folder, an Obsidian vault)",
        "domain-foundry ingest ~/Notes --dry-run",
    ),
    (
        "import",
        "Attach a structured source (SQLite table, JSON/JSONL export)",
        "domain-foundry import --mapping my_mapping.yaml --sqlite ~/old-app.sqlite --dry-run",
    ),
)


@dataclass(frozen=True)
class DetectedKey:
    """An API key already present in the environment."""

    provider_id: str
    env_name: str

    @property
    def label(self) -> str:
        spec = get_provider(self.provider_id)
        return spec.label if spec else self.provider_id


def detect_env_keys() -> list[DetectedKey]:
    """Providers whose conventional key env var is already set.

    Ordered as the registry orders providers, so the suggestion a user sees
    first is stable rather than dependent on dict iteration.
    """
    found: list[DetectedKey] = []
    for spec in all_providers():
        for env_name in spec.api_key_envs:
            value = os.environ.get(env_name)
            if value and value.strip():
                found.append(DetectedKey(provider_id=spec.id, env_name=env_name))
                break
    return found


def suggest_provider() -> ProviderSpec | None:
    """The provider to preselect: the first whose key is already in the env."""
    detected = detect_env_keys()
    if not detected:
        return None
    return get_provider(detected[0].provider_id)


def build_config(
    *,
    provider_id: str,
    routine_model: str | None = None,
    sota_model: str | None = None,
    api_key_env: str | None = None,
    api_key: str | None = None,
) -> LLMConfig:
    """Assemble an :class:`LLMConfig` from answers (or flags).

    Unspecified models fall back to the provider's suggestion. A provider that
    needs no key ("local", "none") yields ``mode="heuristic"`` when it also has
    no models, so the config records honestly that routing is rules-only.
    """
    spec = get_provider(provider_id)
    if spec is None:
        raise ValueError(
            f"unknown provider {provider_id!r}; "
            f"expected one of {', '.join(p.id for p in all_providers())}"
        )

    resolved_routine = routine_model or spec.routine_model
    resolved_sota = sota_model or spec.sota_model
    # Keep the two tiers independent but do not leave one dead: a provider with
    # only one suggested model serves both tiers from it.
    if resolved_routine and not resolved_sota:
        resolved_sota = resolved_routine
    if resolved_sota and not resolved_routine:
        resolved_routine = resolved_sota

    key_env = api_key_env
    if key_env is None and spec.needs_key:
        # Respect a var the user already exports; otherwise recommend the name
        # their other tools use rather than a Domain-Foundry-only one.
        key_env = next(
            (e for e in spec.api_key_envs if os.environ.get(e)),
            spec.canonical_key_env
            or (spec.api_key_envs[0] if spec.api_key_envs else None),
        )

    live = spec.id != "none" and bool(resolved_routine or resolved_sota)
    tier = TierSettings(
        base_url=spec.base_url,
        api_key_env=key_env,
        api_key=api_key,
    )
    return LLMConfig(
        provider=spec.id,
        mode="live" if live else "heuristic",
        routine=TierSettings(
            model=resolved_routine,
            base_url=tier.base_url,
            api_key_env=tier.api_key_env,
            api_key=tier.api_key,
        ),
        sota=TierSettings(
            model=resolved_sota,
            base_url=tier.base_url,
            api_key_env=tier.api_key_env,
            api_key=tier.api_key,
        ),
    )


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a single live call against one tier."""

    tier: str
    ok: bool
    model: str | None
    detail: str

    @property
    def symbol(self) -> str:
        return "ok" if self.ok else "FAILED"


def probe_tier(
    tier: str,
    *,
    home: Path | None = None,
    config: LLMConfig | None = None,
) -> ProbeResult:
    """Make one cheap real call against a tier and report what happened.

    Deliberately not schema-constrained and deliberately tiny: the question is
    only "does this key reach this model and come back as JSON", which is
    exactly the failure that otherwise hides behind heuristic fallback.
    """
    from domain_foundry_core.llm.provider import (
        HeuristicProvider,
        _build_tier_provider,
        resolve_tier_settings,
    )

    settings = resolve_tier_settings(tier, home=home, config=config)
    provider = _build_tier_provider(tier, settings)
    if isinstance(provider, HeuristicProvider):
        return ProbeResult(
            tier=tier,
            ok=False,
            model=settings.model,
            detail="no API key resolved — this tier would use keyword rules only",
        )
    try:
        result = provider.complete_json(
            system=(
                "You are a configuration probe. Reply with a single JSON object "
                'exactly: {"ok": true}'
            ),
            user='Reply with {"ok": true}',
            tier=tier,
        )
    except Exception as exc:  # noqa: BLE001 - report any transport/API failure
        return ProbeResult(
            tier=tier,
            ok=False,
            model=settings.model,
            detail=f"{type(exc).__name__}: {exc}",
        )
    model = result.usage.model or settings.model
    if not isinstance(result.data, dict):
        return ProbeResult(
            tier=tier, ok=False, model=model, detail="response was not a JSON object"
        )
    return ProbeResult(tier=tier, ok=True, model=model, detail="reachable")


def resolved_status(home: Path | None = None) -> dict[str, object]:
    """Where every effective LLM setting comes from, with keys redacted.

    This is the ``--show`` output and the thing to paste into a bug report.
    """
    from domain_foundry_core.llm.provider import resolve_tier_settings

    cfg = load_llm_config(home)
    path = config_path(home)
    out: dict[str, object] = {
        "config_file": str(path),
        "config_file_exists": path.exists(),
        "provider": cfg.provider,
        "mode": cfg.mode,
        "detected_env_keys": [
            {"provider": d.provider_id, "env": d.env_name} for d in detect_env_keys()
        ],
    }
    for tier in ("routine", "sota"):
        settings = resolve_tier_settings(tier, home=home, config=cfg)
        out[tier] = {
            "model": settings.model,
            "base_url": settings.base_url,
            "api_key_env": settings.api_key_env,
            "api_key_present": bool(settings.api_key),
            "live": settings.configured,
        }
    return out


def is_already_configured(home: Path | None = None) -> bool:
    """True when both tiers can already reach a model without asking anything."""
    from domain_foundry_core.llm.provider import resolve_tier_settings

    cfg = load_llm_config(home)
    return all(
        resolve_tier_settings(tier, home=home, config=cfg).configured
        for tier in ("routine", "sota")
    )
