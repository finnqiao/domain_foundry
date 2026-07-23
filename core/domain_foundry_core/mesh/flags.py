"""Concierge UX feature flags (mesh P3).

Each behavior is independently gated so it can ship dark until its contract
test is green. Env vars accept 1/true/on/yes (case-insensitive) to enable and
0/false/off/no to disable. Defaults are ON — sensible for the scripted UX
suite and for production once green.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "on", "yes"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# Public flag names (returned to operators / CONVERGENCE_LOG).
FLAG_STICKINESS = "DOMAIN_FOUNDRY_MESH_STICKINESS"
FLAG_BARGE_IN = "DOMAIN_FOUNDRY_MESH_BARGE_IN"
FLAG_NOT_MINE = "DOMAIN_FOUNDRY_MESH_NOT_MINE"
FLAG_SWITCH = "DOMAIN_FOUNDRY_MESH_SWITCH"
FLAG_STICKY_TTL_S = "DOMAIN_FOUNDRY_MESH_STICKY_TTL_S"
FLAG_BARGE_IN_MIN_CONF = "DOMAIN_FOUNDRY_MESH_BARGE_IN_MIN_CONF"

DEFAULT_STICKY_TTL_S = 900.0  # 15 minutes
DEFAULT_BARGE_IN_MIN_CONF = 0.85


@dataclass(frozen=True)
class ConciergeUXFlags:
    """Independent gates for stickiness / barge-in / not_mine / switch."""

    stickiness: bool = True
    barge_in: bool = True
    not_mine: bool = True
    switch: bool = True
    sticky_ttl_s: float = DEFAULT_STICKY_TTL_S
    barge_in_min_confidence: float = DEFAULT_BARGE_IN_MIN_CONF

    @classmethod
    def from_env(cls) -> ConciergeUXFlags:
        return cls(
            stickiness=_env_bool(FLAG_STICKINESS, True),
            barge_in=_env_bool(FLAG_BARGE_IN, True),
            not_mine=_env_bool(FLAG_NOT_MINE, True),
            switch=_env_bool(FLAG_SWITCH, True),
            sticky_ttl_s=_env_float(FLAG_STICKY_TTL_S, DEFAULT_STICKY_TTL_S),
            barge_in_min_confidence=_env_float(
                FLAG_BARGE_IN_MIN_CONF, DEFAULT_BARGE_IN_MIN_CONF
            ),
        )


# Alias used in docs / commit messages.
UX_FLAG_NAMES = (
    FLAG_STICKINESS,
    FLAG_BARGE_IN,
    FLAG_NOT_MINE,
    FLAG_SWITCH,
)
