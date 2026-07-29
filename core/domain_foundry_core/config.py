"""Persisted workspace config (``~/.domain_foundry/config.toml``).

Domain Foundry was env-var-only before this: every LLM setting came from
``DOMAIN_FOUNDRY_*`` in the environment. That works for an expert with a
dotfile, but it leaves a guided setup nowhere to put the user's answers — the
flow would have to end with "now export these six variables yourself", which is
exactly the un-guided experience.

So settings resolve in three layers, most specific first:

1. **Environment** — ``DOMAIN_FOUNDRY_*``. Unchanged, still wins. An existing
   install with exported vars behaves exactly as before this file existed.
2. **Config file** — what ``domain-foundry setup`` wrote.
3. **Provider registry defaults** — :mod:`domain_foundry_core.llm.providers`.

**Secrets.** By default the file records *which env var holds the key*
(``api_key_env``), not the key itself, and setup verifies that var is set. A
user who wants the convenience of a stored key opts in explicitly, and then the
file is written ``0600`` and the key lands under ``api_key``. Nothing here ever
writes a key the caller did not pass, and :func:`redacted_llm_config` is what
diagnostics print.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from domain_foundry_core.paths import default_home

CONFIG_FILENAME = "config.toml"


def config_path(home: Path | None = None) -> Path:
    """Location of the config file for a workspace."""
    return (home or default_home()) / CONFIG_FILENAME


@dataclass(frozen=True)
class TierSettings:
    """Resolved settings for one model tier (routine or sota)."""

    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    api_key: str | None = None

    @property
    def configured(self) -> bool:
        """True when this tier can actually reach a model.

        Requires a resolved key, not merely the *name* of an env var — an
        ``api_key_env`` pointing at an unset variable is a promise, not a
        credential, and treating it as configured is what would let setup report
        success while every capture silently fell back to keyword rules.
        """
        return bool(self.model and self.api_key)


@dataclass(frozen=True)
class LLMConfig:
    """The persisted half of the LLM setup."""

    provider: str | None = None
    # "live" → use the configured models. "heuristic" → keyword rules only.
    mode: str | None = None
    routine: TierSettings = TierSettings()
    sota: TierSettings = TierSettings()

    @property
    def is_configured(self) -> bool:
        return bool(self.provider) and self.provider != "none"


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _tier_from_table(table: Any) -> TierSettings:
    if not isinstance(table, dict):
        return TierSettings()
    return TierSettings(
        model=_as_str(table.get("model")),
        base_url=_as_str(table.get("base_url")),
        api_key_env=_as_str(table.get("api_key_env")),
        api_key=_as_str(table.get("api_key")),
    )


def load_raw(home: Path | None = None) -> dict[str, Any]:
    """Parse the config file, or return ``{}`` when absent/unreadable.

    A malformed config must not brick the CLI — a user who hand-edits the file
    and fluffs the TOML should get their env-var/default behaviour back plus a
    fixable error, not a traceback on every command.
    """
    path = config_path(home)
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_llm_config(home: Path | None = None) -> LLMConfig:
    """Read the ``[llm]`` section. Env vars are *not* applied here."""
    llm = load_raw(home).get("llm")
    if not isinstance(llm, dict):
        return LLMConfig()
    return LLMConfig(
        provider=_as_str(llm.get("provider")),
        mode=_as_str(llm.get("mode")),
        routine=_tier_from_table(llm.get("routine")),
        sota=_tier_from_table(llm.get("sota")),
    )


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _toml_escape(value: str) -> str:
    out = value.replace("\\", "\\\\").replace('"', '\\"')
    return out.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def _toml_kv(key: str, value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return f'{key} = "{_toml_escape(value)}"'


def _tier_block(name: str, tier: TierSettings, *, store_keys: bool) -> list[str]:
    lines = [f"[llm.{name}]"]
    for key, value in (
        ("model", tier.model),
        ("base_url", tier.base_url),
        ("api_key_env", tier.api_key_env),
    ):
        rendered = _toml_kv(key, value)
        if rendered:
            lines.append(rendered)
    if store_keys:
        rendered = _toml_kv("api_key", tier.api_key)
        if rendered:
            lines.append(rendered)
    lines.append("")
    return lines


def render_llm_config(cfg: LLMConfig, *, store_keys: bool = False) -> str:
    """Serialize an :class:`LLMConfig` to TOML text."""
    lines = [
        "# Domain Foundry workspace config.",
        "# Written by `domain-foundry setup`. Environment variables override",
        "# everything here; delete a value to fall back to the provider default.",
        "",
        "[llm]",
    ]
    for key, value in (("provider", cfg.provider), ("mode", cfg.mode)):
        rendered = _toml_kv(key, value)
        if rendered:
            lines.append(rendered)
    lines.append("")
    lines += _tier_block("routine", cfg.routine, store_keys=store_keys)
    lines += _tier_block("sota", cfg.sota, store_keys=store_keys)
    return "\n".join(lines).rstrip() + "\n"


def save_llm_config(
    cfg: LLMConfig,
    home: Path | None = None,
    *,
    store_keys: bool = False,
) -> Path:
    """Write the ``[llm]`` section to disk.

    ``store_keys=False`` (the default) drops ``api_key`` from both tiers, so a
    key that was only ever passed in memory does not land on disk. When keys
    *are* stored the file is chmod ``0600`` before the secret is written, so it
    is never briefly world-readable.
    """
    path = config_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render_llm_config(cfg, store_keys=store_keys)

    # Create/truncate with tight permissions *before* writing a secret.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
    if not store_keys:
        # No secret in the file; relax to the user's normal umask behaviour so
        # it reads like an ordinary config file.
        try:
            os.chmod(path, 0o644)
        except OSError:
            pass
    return path


def redacted_llm_config(cfg: LLMConfig) -> LLMConfig:
    """Copy with inline keys masked — safe for diagnostics and logs."""
    mask = "***"
    return replace(
        cfg,
        routine=replace(cfg.routine, api_key=mask if cfg.routine.api_key else None),
        sota=replace(cfg.sota, api_key=mask if cfg.sota.api_key else None),
    )
