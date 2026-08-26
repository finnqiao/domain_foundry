"""Load FoundrySpec documents and validate their knowledge references."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from .models import FoundrySpec

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = Path(__file__).resolve().parent


def _checkout_or_packaged(checkout: Path, packaged: Path) -> Path:
    return checkout if checkout.exists() else packaged


DEFAULT_REGISTRY = _checkout_or_packaged(
    REPO_ROOT / "knowledge" / "source-registry.yaml",
    PACKAGE_ROOT / "_knowledge" / "source-registry.yaml",
)
DEFAULT_PRINCIPLES = _checkout_or_packaged(
    REPO_ROOT / "knowledge" / "principles",
    PACKAGE_ROOT / "_knowledge" / "principles",
)
DEFAULT_GOLDENS = _checkout_or_packaged(
    REPO_ROOT / "examples" / "golden",
    PACKAGE_ROOT / "_golden",
)


def _mapping(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping")
    return data


def knowledge_ids(
    registry_path: Path = DEFAULT_REGISTRY, principles_dir: Path = DEFAULT_PRINCIPLES
) -> tuple[set[str], set[str]]:
    registry = _mapping(registry_path)
    source_ids = {
        item["id"]
        for item in registry.get("sources", [])
        if item.get("status") in {"approved", "reference_only"}
    }
    principle_ids: set[str] = set()
    for path in principles_dir.glob("*.yaml"):
        principle_ids.update(item["id"] for item in _mapping(path).get("principles", []))
    return source_ids, principle_ids


def load_foundry_spec(
    path: Path,
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    principles_dir: Path = DEFAULT_PRINCIPLES,
) -> FoundrySpec:
    spec = FoundrySpec.model_validate(_mapping(path))
    known_sources, known_principles = knowledge_ids(registry_path, principles_dir)
    known_sources.update(source.id for source in spec.source_snapshots)
    missing_sources = set(spec.source_ids) - known_sources
    if missing_sources:
        raise ValueError(f"{path}: unknown or unusable sources {sorted(missing_sources)}")
    missing_principles = set(spec.principle_ids) - known_principles
    if missing_principles:
        raise ValueError(f"{path}: unknown principles {sorted(missing_principles)}")
    return spec


def load_golden_specs(root: Path = DEFAULT_GOLDENS) -> list[FoundrySpec]:
    return [load_foundry_spec(path) for path in sorted(root.glob("*.foundry.yaml"))]


def dump_foundry_spec(spec: FoundrySpec, path: Path) -> None:
    """Atomically publish a new YAML representation of a validated spec."""

    if path.exists():
        raise FileExistsError(f"refusing to overwrite FoundrySpec: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


__all__ = ["dump_foundry_spec", "knowledge_ids", "load_foundry_spec", "load_golden_specs"]
