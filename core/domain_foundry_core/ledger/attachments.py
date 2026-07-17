"""Content-addressed attachment storage under ~/.domain_foundry/attachments/."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from domain_foundry_core.security.paths import safe_join
from domain_foundry_core.security.redact import redact_secrets


def store_attachment(
    attachments_dir: Path,
    data: bytes,
    *,
    filename: str | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    """Write bytes under sha256 prefix; return metadata for capture_event.attachments_json."""
    attachments_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    rel = f"{digest[:2]}/{digest}"
    dest = safe_join(attachments_dir, rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        dest.write_bytes(data)
    meta = {
        "sha256": digest,
        "path": rel,
        "size": len(data),
        "filename": redact_secrets(filename) if filename else None,
        "content_type": content_type,
    }
    return meta


def attachments_to_json(items: list[dict[str, Any]] | None) -> str | None:
    if not items:
        return None
    return json.dumps(items, separators=(",", ":"), ensure_ascii=False)
