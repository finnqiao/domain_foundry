"""Load shipped atlas YAML plus an optional home overlay."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from domain_foundry_core.atlas.models import AtlasEdge, AtlasGraph, AtlasNode


def bundled_atlas_root() -> Path:
    """Repo ``atlas/`` in a checkout, or wheel-bundled data."""
    repo = Path(__file__).resolve().parents[3] / "atlas"
    if repo.is_dir():
        return repo
    return Path(__file__).resolve().parent / "_bundled"


def _yaml_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("*.yaml") if not p.name.startswith("_"))


def _parse_file(path: Path) -> tuple[list[AtlasNode], list[AtlasEdge]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: atlas file must be a mapping")
    nodes = [AtlasNode.model_validate(item) for item in raw.get("nodes") or []]
    edges = [AtlasEdge.model_validate(item) for item in raw.get("edges") or []]
    return nodes, edges


def load_atlas(overlay: Path | None = None) -> AtlasGraph:
    """Merge shipped files, then overlay files (same id wins)."""
    by_id: dict[str, AtlasNode] = {}
    edges: list[AtlasEdge] = []
    seen_edge: set[tuple[str, str, str]] = set()

    def _ingest(nodes: list[AtlasNode], more_edges: list[AtlasEdge]) -> None:
        for node in nodes:
            by_id[node.id] = node
        for edge in more_edges:
            key = (edge.source, edge.target, edge.rel)
            if key not in seen_edge:
                seen_edge.add(key)
                edges.append(edge)

    for path in _yaml_files(bundled_atlas_root()):
        _ingest(*_parse_file(path))
    if overlay is not None:
        for path in _yaml_files(Path(overlay)):
            _ingest(*_parse_file(path))
    return AtlasGraph(list(by_id.values()), edges)


def validate_atlas(graph: AtlasGraph) -> list[str]:
    """Structural checks used by tests and ``pack validate``-style atlas lint."""
    errors: list[str] = []
    for edge in graph.edges:
        if edge.source not in graph.nodes:
            errors.append(f"edge from unknown {edge.source}")
        if edge.target not in graph.nodes:
            errors.append(f"edge to unknown {edge.target}")
    for node in graph.nodes.values():
        if node.kind == "idea":
            if not node.jobs:
                errors.append(f"idea {node.id} has no jobs")
            if node.provenance is None:
                errors.append(f"idea {node.id} missing provenance")
        elif node.jobs:
            errors.append(f"{node.kind} {node.id} should not declare jobs")
    return errors


def graph_stats(graph: AtlasGraph) -> dict[str, Any]:
    return {
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "buckets": sum(1 for n in graph.nodes.values() if n.kind == "bucket"),
        "practices": sum(1 for n in graph.nodes.values() if n.kind == "practice"),
        "ideas": sum(1 for n in graph.nodes.values() if n.kind == "idea"),
    }
