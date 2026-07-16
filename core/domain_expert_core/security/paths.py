"""Path-traversal safety for vault/attachment writes."""

from __future__ import annotations

from pathlib import Path


class PathSafetyError(ValueError):
    pass


def safe_join(base: Path, rel: str) -> Path:
    """Join `rel` under `base`, rejecting absolute paths and `..` escapes."""
    if rel is None:
        raise PathSafetyError("empty path")
    rel = str(rel).strip()
    if not rel:
        raise PathSafetyError("empty path")
    p = Path(rel)
    if p.is_absolute():
        raise PathSafetyError(f"absolute paths are not allowed: {rel!r}")
    if any(part == ".." for part in p.parts):
        raise PathSafetyError(f"path traversal ('..') not allowed: {rel!r}")
    base_resolved = base.resolve()
    resolved = (base_resolved / p).resolve()
    if base_resolved != resolved and base_resolved not in resolved.parents:
        raise PathSafetyError(f"path escapes {base_resolved}: {rel!r}")
    return resolved
