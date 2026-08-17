"""Walk the idea atlas from residue so co-build proposes a neighbor idea."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from domain_foundry_core.atlas.loader import load_atlas
from domain_foundry_core.atlas.models import AtlasGraph, AtlasNode
from domain_foundry_core.atlas.query import _best_node, _content_tokens, score_node
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_ro


def suggest_neighbor(
    workspace: Workspace,
    domain: str,
    *,
    overlay: Path | None = None,
    threshold: int = 3,
) -> dict[str, Any] | None:
    """If captures cluster toward an adjacent / expands_to idea, propose it."""
    graph = load_atlas(overlay)
    pack_hint = _pack_atlas_hint(workspace, domain)
    cursor = _cursor_for_pack(graph, domain, pack_hint)
    if cursor is None:
        return None
    candidates = _neighbor_ideas(graph, cursor, pack_hint.get("atlas_ideas") or [])
    if not candidates:
        return None
    blob = _capture_blob(workspace, domain)
    if not blob.strip():
        return None
    tokens = _content_tokens(blob)
    ranked: list[tuple[int, AtlasNode]] = []
    for idea in candidates:
        score = score_node(idea, tokens, blob)
        for term in idea.jargon + idea.aliases + [idea.title]:
            needle = term.lower()
            if len(needle) >= 3 and needle in blob:
                score += 4
        ranked.append((score, idea))
    ranked.sort(key=lambda pair: (-pair[0], pair[1].id))
    best_score, idea = ranked[0]
    if best_score < threshold:
        return None
    practice = graph.parents(idea.id)
    practice_title = practice[0].title if practice else cursor.title
    analog = ""
    if idea.world_analogs:
        analog = f" — like {idea.world_analogs[0].name}"
    edit = _apply_edit_for(idea)
    return {
        "domain": domain,
        "kind": "neighbor_idea",
        "idea_id": idea.id,
        "jobs": list(idea.jobs),
        "apply_edit": edit,
        "count": best_score,
        "reason_code": f"atlas:{idea.id}",
        "suggestion": (
            f"You've mentioned things that belong in {idea.title.lower()} "
            f"({practice_title} is next to this log){analog}. "
            f"Add {idea.title.lower()}?"
        ),
    }


def _pack_atlas_hint(workspace: Workspace, domain: str) -> dict[str, Any]:
    from domain_foundry_core.packs.registry import PackRegistry

    registry = PackRegistry(workspace)
    pack = registry.get(domain)
    hint: dict[str, Any] = {
        "title": pack.manifest.title if pack else domain,
        "description": pack.manifest.description if pack else "",
        "objects": list(pack.objects) if pack else [],
        "atlas_ideas": [],
        "atlas_cursor": None,
    }
    if pack is None:
        return hint
    status_path = pack.root / "foundry_status.json"
    if status_path.is_file():
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        hint["atlas_ideas"] = list(data.get("atlas_ideas") or [])
        hint["atlas_cursor"] = data.get("atlas_cursor")
    return hint


def _cursor_for_pack(
    graph: AtlasGraph, domain: str, hint: dict[str, Any]
) -> AtlasNode | None:
    if hint.get("atlas_cursor"):
        node = graph.get(str(hint["atlas_cursor"]))
        if node is not None:
            return node
    for idea_id in hint.get("atlas_ideas") or []:
        idea = graph.get(str(idea_id))
        if idea is not None:
            parents = graph.parents(idea.id)
            return parents[0] if parents else idea
    for node in graph.nodes.values():
        if node.domain_slug == domain or node.id.split(".")[-1] == domain:
            if node.kind == "idea":
                parents = graph.parents(node.id)
                return parents[0] if parents else node
            return node
    blob = f"{domain} {hint.get('title') or ''} {hint.get('description') or ''}"
    return _best_node(graph, blob)


def _neighbor_ideas(
    graph: AtlasGraph, cursor: AtlasNode, selected: list[str]
) -> list[AtlasNode]:
    seen: set[str] = set(selected)
    out: list[AtlasNode] = []

    def _add(node: AtlasNode) -> None:
        if node.id in seen:
            return
        seen.add(node.id)
        if node.kind == "idea":
            out.append(node)
        else:
            for child in graph.ideas_at(node.id):
                if child.id not in seen:
                    seen.add(child.id)
                    out.append(child)

    seeds = [cursor]
    for idea_id in selected:
        node = graph.get(idea_id)
        if node is not None:
            seeds.append(node)
            seeds.extend(graph.parents(node.id))
    for seed in seeds:
        for node in graph.expands_to(seed.id):
            _add(node)
        for node in graph.adjacent(seed.id):
            _add(node)
        if seed.kind == "practice":
            for parent in graph.parents(seed.id):
                for sib in graph.practices_at(parent.id):
                    if sib.id != seed.id:
                        _add(sib)
    return out


def _capture_blob(workspace: Workspace, domain: str) -> str:
    """Recent capture text, including unfiled cards — residue often never routes."""
    parts: list[str] = []
    conn = connect_ro(workspace.ledger_db)
    try:
        try:
            rows = conn.execute(
                """
                SELECT c.raw_text AS raw_text, e.summary AS summary
                FROM entry e
                JOIN capture_event c ON c.id = e.capture_event_id
                ORDER BY e.created_at DESC
                LIMIT 80
                """,
            ).fetchall()
            for row in rows:
                parts.append(str(row["raw_text"] or ""))
                parts.append(str(row["summary"] or ""))
        except Exception:
            pass
        try:
            cap_rows = conn.execute(
                """
                SELECT raw_text FROM capture_event
                ORDER BY created_at DESC
                LIMIT 40
                """,
            ).fetchall()
            parts.extend(str(row["raw_text"] or "") for row in cap_rows)
        except Exception:
            pass
        try:
            cr_rows = conn.execute(
                """
                SELECT payload_json FROM change_request
                WHERE domain = ?
                ORDER BY created_at DESC
                LIMIT 80
                """,
                (domain,),
            ).fetchall()
        except Exception:
            cr_rows = []
        for row in cr_rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except Exception:
                continue
            residue = payload.get("residue") or {}
            parts.append(json.dumps(residue))
            parts.append(str(payload.get("raw_text") or ""))
    finally:
        conn.close()
    return " ".join(parts).lower()


def _apply_edit_for(idea: AtlasNode) -> str:
    """NL hardening text that add_object / add_capability can parse."""
    if "catalog" in idea.jobs:
        name = (idea.identity_hint or "name").replace("_name", "") or "item"
        return f"add a {name} object"
    if "media_dex" in idea.jobs:
        return "add a media capability"
    if "atlas" in idea.jobs:
        return "add a map capability"
    if idea.identity_hint:
        return f"identity should be {idea.identity_hint}"
    return f"add a {idea.domain_slug or 'record'} object"
