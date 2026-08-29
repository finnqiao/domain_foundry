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


# Build targets a spec may name and the foundry can actually produce. The
# `standalone_react` member stays in the model so older specs still load and
# round-trip, but choosing it fails here with a plain sentence instead of
# building something the repo cannot build. See the rebuild plan, Lane A2.
BUILDABLE_TARGETS = frozenset({"foundry_runtime"})

UNBUILDABLE_TARGET_MESSAGE = {
    "standalone_react": (
        "This spec asks to be built as a standalone React app, which is not "
        "available yet. Change the target to foundry_runtime to build the app "
        "you own."
    )
}


def check_targets_are_buildable(spec: FoundrySpec, label: str = "this spec") -> None:
    """Fail closed when nothing in the target list can be built.

    A spec may still list ``standalone_react`` alongside ``foundry_runtime``:
    that spec builds, because the runtime target is there. A spec that names
    only unbuildable targets stops here with a sentence a person can act on,
    rather than quietly building something else.
    """

    targets = list(spec.implementation.targets)
    if any(target in BUILDABLE_TARGETS for target in targets):
        return
    message = next(
        (
            UNBUILDABLE_TARGET_MESSAGE[target]
            for target in targets
            if target in UNBUILDABLE_TARGET_MESSAGE
        ),
        f"This spec asks for {', '.join(targets)}, which is not available yet. "
        "Change the target to foundry_runtime to build the app you own.",
    )
    raise ValueError(f"{label}: {message}")


def load_foundry_spec(
    path: Path,
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    principles_dir: Path = DEFAULT_PRINCIPLES,
) -> FoundrySpec:
    spec = FoundrySpec.model_validate(_mapping(path))
    check_targets_are_buildable(spec, str(path))
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


__all__ = [
    "check_targets_are_buildable",
    "dump_foundry_spec",
    "knowledge_ids",
    "load_foundry_spec",
    "load_golden_specs",
]
