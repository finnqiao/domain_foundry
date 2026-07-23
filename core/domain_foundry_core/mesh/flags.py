"""Concierge UX + mesh observability feature flags (mesh P3 / P5).

Each behavior is independently gated so it can ship dark until its contract
test is green. Env vars accept 1/true/on/yes (case-insensitive) to enable and
0/false/off/no to disable. UX defaults are ON — sensible for the scripted UX
suite and for production once green. Depth alerts default OFF (opt-in).
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


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# Public flag names (returned to operators / CONVERGENCE_LOG).
FLAG_STICKINESS = "DOMAIN_FOUNDRY_MESH_STICKINESS"
FLAG_BARGE_IN = "DOMAIN_FOUNDRY_MESH_BARGE_IN"
FLAG_NOT_MINE = "DOMAIN_FOUNDRY_MESH_NOT_MINE"
FLAG_SWITCH = "DOMAIN_FOUNDRY_MESH_SWITCH"
FLAG_STICKY_TTL_S = "DOMAIN_FOUNDRY_MESH_STICKY_TTL_S"
FLAG_BARGE_IN_MIN_CONF = "DOMAIN_FOUNDRY_MESH_BARGE_IN_MIN_CONF"

# Phase 8 observability — queue-depth threshold → Concierge outbound alert.
FLAG_DEPTH_ALERT = "DOMAIN_FOUNDRY_MESH_DEPTH_ALERT"
FLAG_DEPTH_ALERT_THRESHOLD = "DOMAIN_FOUNDRY_MESH_DEPTH_ALERT_THRESHOLD"
FLAG_DEPTH_ALERT_CHANNEL = "DOMAIN_FOUNDRY_MESH_DEPTH_ALERT_CHANNEL"
FLAG_DEPTH_ALERT_DESTINATION = "DOMAIN_FOUNDRY_MESH_DEPTH_ALERT_DESTINATION"

DEFAULT_STICKY_TTL_S = 900.0  # 15 minutes
DEFAULT_BARGE_IN_MIN_CONF = 0.85
DEFAULT_DEPTH_ALERT_THRESHOLD = 50


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


@dataclass(frozen=True)
class MeshObservabilityFlags:
    """Gates for queue-depth threshold alerts (mesh P5 / Phase 8)."""

    depth_alert: bool = False
    depth_alert_threshold: int = DEFAULT_DEPTH_ALERT_THRESHOLD
    depth_alert_channel: str = "telegram"
    depth_alert_destination: str = "ops"

    @classmethod
    def from_env(cls) -> MeshObservabilityFlags:
        return cls(
            depth_alert=_env_bool(FLAG_DEPTH_ALERT, False),
            depth_alert_threshold=max(
                1, _env_int(FLAG_DEPTH_ALERT_THRESHOLD, DEFAULT_DEPTH_ALERT_THRESHOLD)
            ),
            depth_alert_channel=os.environ.get(FLAG_DEPTH_ALERT_CHANNEL, "telegram")
            or "telegram",
            depth_alert_destination=os.environ.get(
                FLAG_DEPTH_ALERT_DESTINATION, "ops"
            )
            or "ops",
        )


# Alias used in docs / commit messages.
UX_FLAG_NAMES = (
    FLAG_STICKINESS,
    FLAG_BARGE_IN,
    FLAG_NOT_MINE,
    FLAG_SWITCH,
)

OBS_FLAG_NAMES = (
    FLAG_DEPTH_ALERT,
    FLAG_DEPTH_ALERT_THRESHOLD,
)
