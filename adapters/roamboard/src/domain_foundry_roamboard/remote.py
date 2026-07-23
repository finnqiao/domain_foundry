"""Optional live Roamboard / Supabase fetch (env-based; no secrets in repo)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

# Prefer the existing Hermes↔Roamboard sync token; Supabase anon/service keys
# are an alternate path for store reads when configured.
ENV_SYNC_TOKEN = "ROAMBOARD_SYNC_TOKEN"
ENV_SYNC_URL = "ROAMBOARD_SYNC_URL"
ENV_SUPABASE_URL = "ROAMBOARD_SUPABASE_URL"
ENV_SUPABASE_KEY = "ROAMBOARD_SUPABASE_KEY"

DEFAULT_SYNC_URL = "https://roamboard.vercel.app/api/sync/hermes"


def live_creds_present() -> bool:
    """True when either sync-token or Supabase URL+key are available."""
    if os.environ.get(ENV_SYNC_TOKEN):
        return True
    return bool(os.environ.get(ENV_SUPABASE_URL) and os.environ.get(ENV_SUPABASE_KEY))


def pending_patches_url() -> str:
    base = os.environ.get(ENV_SYNC_URL, DEFAULT_SYNC_URL)
    return base.replace("/api/sync/hermes", "/api/hermes/pending-patches")


def fetch_pending_patches(*, timeout: float = 30.0) -> list[dict[str, Any]]:
    """GET pending patch bundles from the Roamboard sync API.

    Requires ``ROAMBOARD_SYNC_TOKEN``. Raises ``RuntimeError`` when creds are
    missing so callers can skip live smoke without failing the unit suite.
    """
    token = os.environ.get(ENV_SYNC_TOKEN)
    if not token:
        raise RuntimeError(f"{ENV_SYNC_TOKEN} is not set; live pull skipped")
    request = urllib.request.Request(
        pending_patches_url(),
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"pending-patches HTTP {exc.code}: {body[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"pending-patches network error: {exc}") from exc
    bundles = payload.get("bundles") or []
    if not isinstance(bundles, list):
        return []
    return [dict(b) for b in bundles if isinstance(b, dict)]


def fetch_supabase_store(*, timeout: float = 30.0) -> dict[str, Any] | None:
    """Optional: read a Roamboard store JSON from Supabase REST (when configured).

    Expects ``ROAMBOARD_SUPABASE_URL`` + ``ROAMBOARD_SUPABASE_KEY`` and a
    ``roamboard_store`` table with a ``payload`` JSON column. Returns None when
    the table is empty.
    """
    base = os.environ.get(ENV_SUPABASE_URL)
    key = os.environ.get(ENV_SUPABASE_KEY)
    if not base or not key:
        raise RuntimeError(
            f"{ENV_SUPABASE_URL} and {ENV_SUPABASE_KEY} required for Supabase pull"
        )
    url = f"{base.rstrip('/')}/rest/v1/roamboard_store?select=payload&limit=1"
    request = urllib.request.Request(
        url,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            rows = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"supabase HTTP {exc.code}: {body[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"supabase network error: {exc}") from exc
    if not rows:
        return None
    payload = rows[0].get("payload") if isinstance(rows[0], dict) else None
    if isinstance(payload, str):
        return json.loads(payload)
    if isinstance(payload, dict):
        return payload
    return None
