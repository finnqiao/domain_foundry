"""ULID helpers (ADR-003)."""

from __future__ import annotations

from ulid import ULID

from domain_foundry_core.clock import now


def new_ulid() -> str:
    """Return a new ULID string, seeded from the injectable clock when possible."""
    try:
        return str(ULID.from_datetime(now()))
    except Exception:
        return str(ULID())


def canonical_uid(domain: str, object_type: str, ulid: str | None = None) -> str:
    return f"{domain}:{object_type}:{ulid or new_ulid()}"
