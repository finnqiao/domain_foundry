"""Job alphabet and compile_jobs: idea jobs → pack blueprint.

Pattern cards live on atlas idea nodes. This module is the compiler.
"""

from __future__ import annotations

import copy
from typing import Any

from domain_foundry_core.atlas.models import JOBS, AtlasNode
from domain_foundry_core.wizard import blueprint as bp
from domain_foundry_core.wizard.models import validate_blueprint
from domain_foundry_core.wizard.shortlist import (
    ShortlistExample,
    ShortlistField,
    ShortlistModel,
    compile_shortlist,
    analog_few_shots as _legacy_analog_few_shots,
)

_CATALOG_EVENT_JOBS = frozenset({"catalog", "event_log"})


def shortlist_for_ideas(
    ideas: list[AtlasNode] | list[dict[str, Any]],
    *,
    goal: str,
) -> ShortlistModel:
    """Deterministic shortlist from chosen idea jobs (no-key / fallback path)."""
    jobs = _union_jobs(ideas)
    identity = _identity_hint(ideas, goal)
    domain = _domain_slug(ideas, goal)
    title = _title(ideas, goal)
    catalog_name, event_name = _object_names(jobs, identity)
    if "catalog" in jobs and ("event_log" in jobs or "lab" in jobs or "improvement" in jobs):
        objects = [catalog_name, event_name]
    elif "catalog" in jobs:
        objects = [catalog_name]
    else:
        objects = [event_name]

    fields: list[ShortlistField] = []
    for obj in objects:
        is_catalog = len(objects) > 1 and obj == catalog_name
        fields.append(
            ShortlistField(
                name=identity,
                type="text",
                role="identity",
                object=obj,
                required=True,
            )
        )
        if not is_catalog:
            fields.append(
                ShortlistField(
                    name="noted_at",
                    type="datetime",
                    role="when",
                    object=obj,
                )
            )
        if "improvement" in jobs and not is_catalog:
            fields.append(
                ShortlistField(
                    name=_measure_name(ideas),
                    type="number",
                    role="measure",
                    object=obj,
                    unit=_measure_unit(ideas),
                )
            )
        if "atlas" in jobs and not is_catalog:
            fields.append(
                ShortlistField(
                    name="location",
                    type="location",
                    role="location",
                    object=obj,
                )
            )
        if "media_dex" in jobs and not is_catalog:
            fields.append(
                ShortlistField(
                    name="photos",
                    type="attachment",
                    role="attachment",
                    object=obj,
                )
            )
        fields.append(
            ShortlistField(
                name="notes",
                type="text",
                role="note",
                object=obj,
            )
        )

    jargon = _jargon(ideas, goal)
    examples = _examples(ideas, objects, identity, goal)
    return ShortlistModel(
        domain=domain,
        title=title,
        description=_description(ideas, goal),
        objects=objects,
        fields=fields,
        jargon=jargon,
        examples=examples,
        negatives=[
            "deploy the release candidate tonight",
            "please review the pull request",
            "schedule a standup meeting",
        ],
    )


def compile_jobs(
    shortlist: ShortlistModel | dict[str, Any],
    *,
    goal: str,
    jobs: list[str],
    domain_hint: str | None = None,
) -> dict[str, Any]:
    """Compile a shortlist, then force object pattern, views, and capabilities."""
    jobs = [j for j in jobs if j in JOBS]
    if isinstance(shortlist, dict):
        shortlist = ShortlistModel.model_validate(shortlist)
    shortlist = _ensure_object_pattern(shortlist, jobs, goal)
    blueprint = compile_shortlist(shortlist, goal=goal)
    if domain_hint:
        blueprint["domain"] = bp.slugify(domain_hint)
        agent = blueprint.get("agent")
        if isinstance(agent, dict):
            agent["name"] = blueprint["domain"]
    blueprint = _apply_job_requirements(blueprint, jobs)
    blueprint["meta"] = {
        **(blueprint.get("meta") or {}),
        "jobs": jobs,
    }
    return validate_blueprint(blueprint)


def analog_few_shots(goal: str) -> list[dict[str, Any]]:
    """Prefer atlas analog packs; fall back to the legacy plants/sourdough pair."""
    try:
        from domain_foundry_core.atlas.query import query_neighborhood

        nb = query_neighborhood(goal)
        shots: list[dict[str, Any]] = []
        for card in nb.get("ideas") or []:
            pack = card.get("analog_pack")
            if not pack:
                continue
            node = AtlasNode.model_validate(
                {
                    "id": card["id"],
                    "kind": "idea",
                    "title": card["title"],
                    "jobs": card.get("jobs") or ["event_log"],
                    "provenance": card.get("provenance") or "foundry",
                    "analog_pack": pack,
                    "domain_slug": card.get("domain_slug"),
                    "identity_hint": card.get("identity_hint"),
                    "example": card.get("example") or "",
                    "pitch": card.get("pitch") or "",
                    "aliases": card.get("aliases") or [],
                }
            )
            sl = shortlist_for_ideas([node], goal=goal)
            shots.append({"goal": goal, "shortlist": sl.model_dump(exclude_none=True)})
            if len(shots) >= 2:
                return shots
        if shots:
            extra = _legacy_analog_few_shots(goal)
            return shots + extra[: 2 - len(shots)]
    except Exception:
        pass
    return _legacy_analog_few_shots(goal)


def _union_jobs(ideas: list[Any]) -> list[str]:
    out: list[str] = []
    for idea in ideas:
        jobs = idea.jobs if isinstance(idea, AtlasNode) else list(idea.get("jobs") or [])
        for job in jobs:
            if job in JOBS and job not in out:
                out.append(job)
    if not out:
        out = ["event_log"]
    return out


def _as_node(idea: Any) -> dict[str, Any]:
    if isinstance(idea, AtlasNode):
        return idea.model_dump()
    return dict(idea)


def _identity_hint(ideas: list[Any], goal: str) -> str:
    for idea in ideas:
        hint = idea.identity_hint if isinstance(idea, AtlasNode) else idea.get("identity_hint")
        if hint:
            return str(hint)
    kws = bp.keywords(goal)
    if kws:
        return bp.slugify(kws[0]) + "_name"
    return "name"


def _domain_slug(ideas: list[Any], goal: str) -> str:
    for idea in ideas:
        slug = idea.domain_slug if isinstance(idea, AtlasNode) else idea.get("domain_slug")
        if slug:
            return bp.slugify(str(slug))
    kws = bp.keywords(goal)
    return bp.slugify(kws[0] if kws else goal or "interest")


def _title(ideas: list[Any], goal: str) -> str:
    if len(ideas) == 1:
        title = ideas[0].title if isinstance(ideas[0], AtlasNode) else ideas[0].get("title")
        if title:
            return str(title)
    return (goal[:1].upper() + goal[1:]) if goal else "Interest"


def _description(ideas: list[Any], goal: str) -> str:
    pitches = []
    for idea in ideas:
        pitch = idea.pitch if isinstance(idea, AtlasNode) else idea.get("pitch")
        if pitch:
            pitches.append(str(pitch))
    return " ".join(pitches) or f"Track: {goal}"


def _object_names(jobs: list[str], identity: str) -> tuple[str, str]:
    base = identity.replace("_name", "") or "item"
    if base in {"entry", "log", "item", "title"}:
        base = "record"
    catalog = base if base.endswith("s") is False else base.rstrip("s")
    if catalog in {"species"}:
        return "species", "sighting"
    if catalog in {"recipe"}:
        return "recipe", "cook"
    if catalog in {"plant"}:
        return "plant", "care_event"
    if "catalog" in jobs and "event_log" in jobs:
        return catalog, f"{catalog}_event"
    return catalog, catalog


def _measure_name(ideas: list[Any]) -> str:
    blob = " ".join(
        str(ideas[i].title if isinstance(ideas[i], AtlasNode) else ideas[i].get("title") or "")
        for i in range(len(ideas))
    ).lower()
    if "sac" in blob or "air" in blob:
        return "sac"
    if "hydrat" in blob:
        return "hydration"
    if "calorie" in blob or "protein" in blob or "macro" in blob:
        return "amount"
    if "depth" in blob:
        return "depth"
    if "pace" in blob or "run" in blob:
        return "minutes"
    return "value"


def _measure_unit(ideas: list[Any]) -> str:
    name = _measure_name(ideas)
    return {
        "sac": "L/min",
        "hydration": "percent",
        "amount": "g",
        "depth": "m",
        "minutes": "minutes",
    }.get(name, "count")


def _jargon(ideas: list[Any], goal: str) -> list[str]:
    out: list[str] = []
    for idea in ideas:
        extra = idea.jargon if isinstance(idea, AtlasNode) else idea.get("jargon") or []
        out.extend(str(j) for j in extra)
        aliases = idea.aliases if isinstance(idea, AtlasNode) else idea.get("aliases") or []
        out.extend(str(a) for a in aliases)
    if len(out) < 3:
        out.extend(bp.keywords(goal)[:4])
    # Ensure some terms survive lint (not just the domain name).
    out.extend(["session", "notes", "logged"])
    return list(dict.fromkeys(j for j in out if j))[:12]


def _examples(
    ideas: list[Any],
    objects: list[str],
    identity: str,
    goal: str,
) -> list[ShortlistExample]:
    examples: list[ShortlistExample] = []
    event_obj = objects[-1]
    catalog_obj = objects[0]
    samples = []
    for idea in ideas:
        ex = idea.example if isinstance(idea, AtlasNode) else idea.get("example")
        if ex:
            samples.append(str(ex))
    if not samples:
        samples = [
            f"logged a new {identity.replace('_', ' ')} today",
            "tried again this morning and it went better",
            "same place as last time, felt smoother",
        ]
    fillers = [
        "tried the usual method again",
        "noted it after the session",
        "kept a short note for next time",
        "repeated the same setup",
        "compared it to last week",
        "marked it as worth repeating",
        "skipped the extra step this round",
        "captured a quick photo of the result",
    ]
    # Fillers must not contain the domain slug or goal keywords (lint).
    texts = fillers[:8]
    if samples:
        texts = samples[:2] + fillers[:8]
    for i, text in enumerate(texts[:10]):
        obj = event_obj if i or len(objects) == 1 else catalog_obj
        fields: dict[str, Any] = {identity: "alpha"}
        examples.append(ShortlistExample(text=text, object=obj, fields=fields))
    if len(objects) > 1 and not any(ex.object == catalog_obj for ex in examples):
        examples.append(
            ShortlistExample(
                text="added another one to the shelf",
                object=catalog_obj,
                fields={identity: "beta"},
            )
        )
    return examples


def _ensure_object_pattern(
    shortlist: ShortlistModel, jobs: list[str], goal: str
) -> ShortlistModel:
    data = shortlist.model_dump()
    if "catalog" in jobs and "event_log" in jobs and len(data["objects"]) < 2:
        identity = next(
            (f["name"] for f in data["fields"] if f.get("role") == "identity"),
            "name",
        )
        catalog, event = _object_names(jobs, identity)
        data["objects"] = [catalog, event]
        # Retarget existing fields onto the event object; clone identity onto catalog.
        for field in data["fields"]:
            if field.get("object") not in data["objects"]:
                field["object"] = event
        catalog_fields = [
            {**f, "object": catalog}
            for f in data["fields"]
            if f.get("role") in {"identity", "text", "enum", "note", "attachment"}
        ]
        if not any(f.get("object") == catalog and f.get("role") == "identity" for f in catalog_fields):
            catalog_fields.insert(
                0,
                {
                    "name": identity,
                    "type": "text",
                    "role": "identity",
                    "object": catalog,
                    "required": True,
                },
            )
        event_fields = [f for f in data["fields"] if f.get("object") == event]
        if not any(f.get("role") == "identity" and f.get("object") == event for f in event_fields):
            event_fields.insert(
                0,
                {
                    "name": identity,
                    "type": "text",
                    "role": "identity",
                    "object": event,
                    "required": True,
                },
            )
        data["fields"] = catalog_fields + event_fields
        for ex in data["examples"]:
            if ex.get("object") not in data["objects"]:
                ex["object"] = event
        if not any(ex.get("object") == catalog for ex in data["examples"]):
            data["examples"].append(
                {
                    "text": f"added a new {identity.replace('_', ' ')} to the list",
                    "object": catalog,
                    "fields": {identity: identity.replace("_", " ")},
                }
            )
        data = ShortlistModel.model_validate(data).model_dump()
    return ShortlistModel.model_validate(data)


def _apply_job_requirements(blueprint: dict[str, Any], jobs: list[str]) -> dict[str, Any]:
    objects = blueprint["objects"]
    domain = blueprint["domain"]
    obj_names = list(objects)
    catalog = obj_names[0]
    event = obj_names[-1]
    views = list(blueprint.get("views") or [])
    capabilities: dict[str, Any] = {}
    compat: dict[str, str] = {}

    def _ensure_field(obj: str, name: str, spec: dict[str, Any]) -> None:
        fields = objects[obj].setdefault("fields", {})
        if name not in fields:
            fields[name] = spec

    def _has_view(block: str) -> bool:
        return any(v.get("block") == block for v in views)

    if "atlas" in jobs:
        target = event if event in objects else catalog
        _ensure_field(target, "lat", {"type": "number"})
        _ensure_field(target, "lng", {"type": "number"})
        if not _has_view("map"):
            views.append(
                {
                    "id": f"{target}_map",
                    "title": "Map",
                    "block": "map",
                    "object": target,
                    "config": {},
                }
            )
    if "media_dex" in jobs:
        target = event if event in objects else catalog
        _ensure_field(target, "photos", {"type": "attachment"})
        if not _has_view("gallery"):
            views.append(
                {
                    "id": f"{target}_gallery",
                    "title": "Gallery",
                    "block": "gallery",
                    "object": target,
                    "config": {"gallery": "photos"},
                }
            )
        capabilities["media"] = {
            "version": 1,
            "galleries": [
                {
                    "id": "photos",
                    "title": "Gallery",
                    "object": target,
                    "field": "photos",
                    "source": "capture_attachments",
                    "accept": ["image/jpeg", "image/png", "image/webp"],
                }
            ],
        }
        compat["media"] = ">=1,<2"
    if "improvement" in jobs:
        target = event if event in objects else catalog
        measures = [
            n
            for n, spec in (objects[target].get("fields") or {}).items()
            if spec.get("type") in {"number", "integer"}
        ]
        if not measures:
            _ensure_field(target, "value", {"type": "number", "unit": "count"})
            measures = ["value"]
        metric_id = f"{measures[0]}_delta"
        capabilities["derived_metrics"] = {
            "version": 1,
            "object": target,
            "metrics": [
                {
                    "id": metric_id,
                    "label": f"{measures[0].replace('_', ' ').title()} Δ",
                    "expression": f"{measures[0]} - previous.{measures[0]}",
                    "fields": [measures[0]],
                    "unit": "delta",
                    "precision": 1,
                }
            ],
        }
        compat["derived_metrics"] = ">=1,<2"
        identity = objects[target].get("title_field") or next(iter(objects[target]["fields"]))
        capabilities["compare"] = {
            "version": 1,
            "comparisons": [
                {
                    "id": f"{target}_compare",
                    "title": "Compare",
                    "object": target,
                    "label_field": identity,
                    "metrics": [metric_id],
                }
            ],
        }
        compat["compare"] = ">=1,<2"
        if not _has_view("compare"):
            views.append(
                {
                    "id": f"{target}_compare",
                    "title": "Compare",
                    "block": "compare",
                    "object": target,
                    "config": {"comparison": f"{target}_compare"},
                }
            )
        if not any(v.get("block") == "stats" for v in views):
            views.append(
                {
                    "id": f"{target}_stats",
                    "title": "Stats",
                    "block": "stats",
                    "object": target,
                    "config": {"measures": [{"field": measures[0], "agg": "trend"}]},
                }
            )
    if "graph" in jobs and len(obj_names) >= 2:
        event_obj = objects[event]
        links = event_obj.setdefault("links", {})
        links.setdefault(
            catalog,
            {"to": f"{domain}.{catalog}", "cardinality": "many_to_one"},
        )
        if not any(v.get("id") == "related" for v in views):
            views.append(
                {
                    "id": "related",
                    "title": "Related",
                    "block": "list",
                    "object": event,
                    "config": {"group_by": catalog},
                }
            )
    elif "catalog" in jobs and "event_log" in jobs and len(obj_names) >= 2:
        event_obj = objects[event]
        links = event_obj.setdefault("links", {})
        links.setdefault(
            catalog,
            {"to": f"{domain}.{catalog}", "cardinality": "many_to_one"},
        )
    if "plan" in jobs:
        target = event if event in objects else catalog
        date_field = next(
            (n for n, s in (objects[target].get("fields") or {}).items() if s.get("type") in {"datetime", "date"}),
            None,
        )
        if date_field and not any(v.get("block") == "planner" for v in views):
            views.append(
                {
                    "id": f"{target}_plan",
                    "title": "Plan",
                    "block": "planner",
                    "object": target,
                    "config": {"date_field": date_field},
                }
            )
    if "lab" in jobs and "compare" not in capabilities:
        # Lab without improvement still gets a list grouped for comparison.
        target = event if event in objects else catalog
        if not any(v.get("id", "").endswith("lab") for v in views):
            views.append(
                {
                    "id": f"{target}_lab",
                    "title": "Lab",
                    "block": "list",
                    "object": target,
                    "config": {},
                }
            )

    blueprint["views"] = views
    if capabilities:
        blueprint["capabilities"] = {
            "compatibility": {"core": ">=0.1,<2", "capabilities": compat},
            "capabilities": capabilities,
        }
    return blueprint


# Re-export for tests that patch analog_few_shots via wizard.jobs.
legacy_analog_few_shots = _legacy_analog_few_shots
copy.copy  # keep import used if we later clone templates
