"""Job alphabet and compile_jobs: idea jobs → pack blueprint.

Pattern cards live on atlas idea nodes. This module is the compiler.
"""

from __future__ import annotations

import re
from typing import Any

from domain_foundry_core.atlas.models import JOBS, AtlasNode
from domain_foundry_core.wizard import blueprint as bp
from domain_foundry_core.wizard.models import validate_blueprint
from domain_foundry_core.wizard.shortlist import (
    IDLE_CHATTER,
    ROUTING_STOP,
    ShortlistExample,
    ShortlistField,
    ShortlistModel,
    compile_shortlist,
    seed_terms,
)
from domain_foundry_core.wizard.shortlist import (
    analog_few_shots as _legacy_analog_few_shots,
)

_CATALOG_HINT = re.compile(
    r"\b(added|add|new|acquired|bought|shelf|binder|catalog|dex|collection|list)\b",
    re.I,
)

_CATALOG_EVENT_JOBS = frozenset({"catalog", "event_log"})


def shortlist_for_ideas(
    ideas: list[AtlasNode] | list[dict[str, Any]],
    *,
    goal: str,
    seed: str = "",
) -> ShortlistModel:
    """Deterministic shortlist from chosen idea jobs (no-key / fallback path).

    ``seed`` is the first sentence the user said they would log, verbatim. It is
    the only source of real domain vocabulary available offline for an interest
    the atlas does not cover, so it goes in as a routing example, as jargon, and
    as identity values. The *second* elicited sentence never reaches here, and
    that is what makes replaying it after activation an honest check.
    """
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

    jargon = _jargon(ideas, goal, seed=seed)
    examples = _examples(ideas, objects, identity, goal, seed=seed)
    negatives = [
        # Near-miss lines from the atlas first: they are the ones a generic
        # negative pool would never think of. Idle chatter stays ahead of the
        # dev-admin filler so the bounded list always keeps one.
        *_negative_examples(ideas)[:2],
        *IDLE_CHATTER,
    ]
    return ShortlistModel(
        domain=domain,
        title=title,
        description=_description(ideas, goal),
        objects=objects,
        fields=fields,
        jargon=jargon,
        vocabulary=_vocabulary(ideas),
        llm_hints=_atlas_hints(ideas),
        examples=examples,
        negatives=list(dict.fromkeys(negatives)),
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
        # The rules were built from the shortlist's slug. Renaming the pack
        # without teaching it its own new name leaves "cocktail" unroutable in
        # a pack called cocktail.
        _teach_domain_term(blueprint, domain_hint)
    blueprint = _apply_job_requirements(blueprint, jobs)
    blueprint["meta"] = {
        **(blueprint.get("meta") or {}),
        "jobs": jobs,
    }
    return validate_blueprint(blueprint)


def _teach_domain_term(blueprint: dict[str, Any], domain_hint: str) -> None:
    """Add the renamed pack's own word to its primary rule."""
    from domain_foundry_core.wizard.shortlist import _is_filler_term, term_pattern

    rules = blueprint.get("rules") or []
    objects = list(blueprint.get("objects") or {})
    if not rules or not objects:
        return
    term = str(domain_hint).strip()
    if not term or _is_filler_term(term):
        return
    pattern = term_pattern(term)
    if not pattern:
        return
    primary = objects[0]
    for rule in rules:
        if rule.get("object") != primary:
            continue
        match = str(rule.get("match") or "")
        if pattern in match:
            return
        if match.startswith("(") and match.endswith(")"):
            rule["match"] = f"({pattern}|{match[1:-1]})"
        else:
            rule["match"] = f"({pattern}|{match})"
        return


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


def _node_attr(idea: Any, name: str) -> Any:
    if isinstance(idea, AtlasNode):
        return getattr(idea, name, None)
    return (idea or {}).get(name)


def _vocabulary(ideas: list[Any]) -> list[str]:
    """The atlas's own words for this interest, best node first."""
    out: list[str] = []
    for idea in ideas:
        for term in _node_attr(idea, "vocabulary") or []:
            text = str(term).strip()
            if text and not _filler_phrase(text):
                out.append(text)
    return list(dict.fromkeys(out))[:24]


def _routing_examples(ideas: list[Any]) -> list[tuple[str, str]]:
    """``(text, placeholder)`` pairs; placeholder is ``catalog`` or ``event``."""
    out: list[tuple[str, str]] = []
    for idea in ideas:
        for item in _node_attr(idea, "routing_examples") or []:
            if isinstance(item, dict):
                text, slot = str(item.get("text") or ""), str(item.get("object") or "event")
            else:
                text, slot = str(getattr(item, "text", "")), str(getattr(item, "object", "event"))
            text = text.strip()
            if text:
                out.append((text, "catalog" if slot == "catalog" else "event"))
    return out


def _negative_examples(ideas: list[Any]) -> list[str]:
    out: list[str] = []
    for idea in ideas:
        for item in _node_attr(idea, "negative_examples") or []:
            text = str(item).strip()
            if text:
                out.append(text)
    return list(dict.fromkeys(out))


def _atlas_hints(ideas: list[Any]) -> str:
    parts = [str(_node_attr(i, "llm_hints") or "").strip() for i in ideas]
    return " ".join(p for p in parts if p)


def _atlas_measure(ideas: list[Any]) -> tuple[str, str] | None:
    for idea in ideas:
        measure = _node_attr(idea, "measure")
        if not measure:
            continue
        if isinstance(measure, dict):
            name, unit = str(measure.get("name") or ""), str(measure.get("unit") or "")
        else:
            name, unit = str(getattr(measure, "name", "")), str(getattr(measure, "unit", ""))
        if name:
            return name, unit
    return None


def _measure_name(ideas: list[Any]) -> str:
    atlas = _atlas_measure(ideas)
    if atlas:
        return bp.slugify(atlas[0])
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
    atlas = _atlas_measure(ideas)
    if atlas:
        return atlas[1]
    name = _measure_name(ideas)
    return {
        "sac": "L/min",
        "hydration": "percent",
        "amount": "g",
        "depth": "m",
        "minutes": "minutes",
    }.get(name, "count")



_TRAILING_NOISE = frozenset(
    {
        "to",
        "from",
        "with",
        "on",
        "at",
        "in",
        "of",
        "for",
        "and",
        "or",
        "the",
        "a",
        "an",
        "was",
        "were",
        "is",
        "it",
        "as",
        "by",
    }
)


def _jargon(ideas: list[Any], goal: str, *, seed: str = "") -> list[str]:
    # The user's own words come first: for an interest the atlas does not
    # cover they are the only real vocabulary in the room, and the bounded
    # list must not spend its slots on "shelf" and "photos" before reaching
    # them.
    out: list[str] = list(seed_terms(seed))
    for idea in ideas:
        extra = idea.jargon if isinstance(idea, AtlasNode) else idea.get("jargon") or []
        out.extend(str(j) for j in extra)
        aliases = idea.aliases if isinstance(idea, AtlasNode) else idea.get("aliases") or []
        out.extend(str(a) for a in aliases)
        example = idea.example if isinstance(idea, AtlasNode) else idea.get("example")
        if example:
            for tok in re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b", str(example)):
                if tok.lower() not in ROUTING_STOP and tok.lower() not in bp._STOPWORDS:
                    out.append(tok)
    if len(out) < 3:
        out.extend(bp.keywords(goal)[:4])
    return list(dict.fromkeys(j for j in out if j and not _filler_phrase(j)))[:12]


def _filler_phrase(term: str) -> bool:
    parts = re.findall(r"[a-z0-9]+", (term or "").lower())
    if not parts:
        return True
    return all(p in ROUTING_STOP or p in bp._STOPWORDS or len(p) < 3 for p in parts)


def _hobby_tokens(goal: str, objects: list[str]) -> set[str]:
    hobby = {w.lower() for w in bp.keywords(goal) if len(w) >= 3}
    hobby.update(o.replace("_", " ").lower() for o in objects)
    hobby.update(o.lower() for o in objects)
    return hobby


def _lacks_hobby(text: str, hobby: set[str]) -> bool:
    low = (text or "").lower()
    return not any(re.search(rf"\b{re.escape(h)}\b", low) for h in hobby if h)


def _sample_lines(ideas: list[Any], *, seed: str = "") -> list[str]:
    # The elicited sentence first: it is the only line here a real person
    # actually typed, so it anchors both the examples and the identity values.
    # Routing examples next: they are written to be routed, the single
    # ``example`` string is written to be read.
    samples: list[str] = [seed.strip()] if seed.strip() else []
    samples.extend(text for text, _ in _routing_examples(ideas))
    for idea in ideas:
        ex = idea.example if isinstance(idea, AtlasNode) else idea.get("example")
        if not ex:
            continue
        for line in str(ex).splitlines():
            for part in line.split(";"):
                part = part.strip()
                if part:
                    samples.append(part)
    return list(dict.fromkeys(samples))


def _identity_values(samples: list[str], identity: str, jargon: list[str]) -> list[str]:
    found: list[str] = []
    noise = ROUTING_STOP | bp._STOPWORDS | _TRAILING_NOISE | {"alpha", "beta", "gamma"}
    for sample in samples:
        for word in re.findall(r"\b[A-Z][a-zA-Z0-9]{2,}\b", sample):
            if word.lower() not in noise:
                found.append(word)
        for match in re.finditer(r"\b(?:a|an|the)\s+([a-z][a-z]+)\b", sample):
            noun = match.group(1)
            if noun not in noise:
                found.append(noun)
    values: list[str] = []
    for item in found:
        if item not in values:
            values.append(item)
    if values:
        return values
    for term in jargon:
        if not _filler_phrase(term) and term.lower() not in noise:
            return [term]
    label = identity.replace("_", " ")
    return [label] if label.lower() not in {"alpha", "beta", "gamma"} else ["entry"]


def _spare_terms(samples: list[str], jargon: list[str], hobby: set[str]) -> list[str]:
    """Hobby language that does not include the interest name (lint + idle-safe)."""
    out: list[str] = []
    for term in jargon:
        if _filler_phrase(term):
            continue
        if not _lacks_hobby(term, hobby):
            continue
        out.append(term)
    for sample in samples:
        for tok in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", sample):
            low = tok.lower()
            if low in hobby or low in ROUTING_STOP or low in bp._STOPWORDS:
                continue
            out.append(tok)
    return list(dict.fromkeys(out))


def _fallback_samples(identity: str, jargon: list[str], goal: str) -> list[str]:
    label = identity.replace("_", " ")
    terms = [j for j in jargon if not _filler_phrase(j)]
    if not terms:
        terms = [k for k in bp.keywords(goal) if k not in ROUTING_STOP][:4]
    if not terms:
        terms = [label]
    out: list[str] = []
    for term in terms[:8]:
        if term.lower() == label.lower():
            out.append(term)
        elif " " in term:
            out.append(f"{label}, {term}")
        else:
            out.append(f"{term} {label}".strip())
    return out or [label]


def _pick_object(text: str, objects: list[str], index: int, catalog_taken: bool) -> str:
    if len(objects) == 1:
        return objects[0]
    if not catalog_taken and (index == 0 or _CATALOG_HINT.search(text or "")):
        return objects[0]
    return objects[-1]


def _tautology(text: str) -> bool:
    parts = re.findall(r"[a-z0-9]+", (text or "").lower())
    n = len(parts)
    if n >= 2 and n % 2 == 0 and parts[: n // 2] == parts[n // 2 :]:
        return True
    return False


def _examples(
    ideas: list[Any],
    objects: list[str],
    identity: str,
    goal: str,
    *,
    seed: str = "",
) -> list[ShortlistExample]:
    catalog_obj = objects[0]
    event_obj = objects[-1]
    hobby = _hobby_tokens(goal, objects)
    jargon = _jargon(ideas, goal, seed=seed)
    samples = _sample_lines(ideas, seed=seed) or _fallback_samples(identity, jargon, goal)
    values = _identity_values(samples, identity, jargon)
    spare = _spare_terms(samples, jargon, hobby)
    rows: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    def add(text: str, obj: str, val: str) -> None:
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        key = cleaned.lower()
        if not cleaned or key in seen or _tautology(cleaned):
            return
        seen.add(key)
        rows.append((cleaned, obj, val))

    # The atlas says where its own routing examples belong; guessing from a
    # keyword ("added") sends "added a super to hive 2" to the wrong object.
    placed = {
        text.strip().lower(): (catalog_obj if slot == "catalog" else event_obj)
        for text, slot in _routing_examples(ideas)
    }
    # The elicited sentence sits at index 0, where the generic rule would post
    # it to the catalog whatever it says. Its own verb knows better: "added a
    # 1948 airmail" is a catalog line, "threw three bowls" is an event.
    if seed.strip():
        placed[seed.strip().lower()] = catalog_obj if _CATALOG_HINT.search(seed) else event_obj
    catalog_taken = False
    for i, sample in enumerate(samples):
        obj = placed.get(sample.strip().lower()) or _pick_object(sample, objects, i, catalog_taken)
        if obj == catalog_obj:
            catalog_taken = True
        add(sample, obj, values[min(i, len(values) - 1)])

    catalog_val = values[0]
    event_val = values[-1]
    catalog_blob = " ".join(text for text, obj, _ in rows if obj == catalog_obj).lower()
    event_spare = [t for t in spare if t.lower() not in catalog_blob]

    def _shown(val: str, fallback: str) -> str:
        if _lacks_hobby(str(val), hobby) and str(val).lower() not in catalog_blob:
            return str(val)
        if _lacks_hobby(fallback, hobby):
            return fallback
        return fallback

    for i in range(0, max(len(event_spare), 1)):
        if not event_spare:
            break
        if i + 1 < len(event_spare):
            add(f"{event_spare[i]} {event_spare[i + 1]}", event_obj, event_val)
        else:
            add(event_spare[i], event_obj, event_val)
        if sum(1 for text, _, _ in rows if _lacks_hobby(text, hobby)) >= 3:
            break

    for i, term in enumerate(event_spare):
        obj = catalog_obj if len(objects) > 1 and i == 0 and not catalog_taken else event_obj
        if obj == catalog_obj:
            catalog_taken = True
        val = catalog_val if obj == catalog_obj else event_val
        shown = _shown(val, term)
        if " " in term:
            add(f"{shown} {term}", obj, val)
        elif term.lower() == shown.lower():
            add(term, obj, val)
        else:
            add(f"{term} {shown}", obj, val)
        if len(rows) >= 10:
            break

    n = 0
    while sum(1 for text, _, _ in rows if _lacks_hobby(text, hobby)) < 3 and event_spare:
        a = event_spare[n % len(event_spare)]
        b = event_spare[(n + 1) % len(event_spare)]
        n += 1
        if a.lower() == b.lower():
            add(a, event_obj, event_val)
        else:
            add(f"{a} {b}", event_obj, event_val)
        if n > 12:
            break

    catalog_blob = " ".join(text for text, obj, _ in rows if obj == catalog_obj).lower()
    event_terms = [
        j
        for j in jargon
        if " " not in j
        and not _filler_phrase(j)
        and j.lower() not in catalog_blob
        and j.lower() not in hobby
    ]
    if not event_terms:
        event_terms = [t for t in event_spare if t.lower() not in catalog_blob]
    for term in event_terms:
        shown = _shown(event_val, term)
        if term.lower() == shown.lower():
            add(term, event_obj, event_val)
        else:
            add(f"{term} {shown}", event_obj, event_val)
        if len(rows) >= 10:
            break

    pad = [
        j
        for j in (*event_spare, *spare, *jargon)
        if not _filler_phrase(j) and j.lower() not in hobby
    ]
    if len(objects) > 1:
        pad = [j for j in pad if j.lower() not in catalog_blob]
    pad = list(dict.fromkeys(pad))
    for i, a in enumerate(pad):
        for b in pad[i + 1 :]:
            add(f"{a} {b}", event_obj, event_val)
            if len(rows) >= 10:
                break
        if len(rows) >= 10:
            break
    for term in pad:
        add(term, event_obj, event_val)
        if len(rows) >= 10:
            break

    if len(objects) > 1 and not any(obj == catalog_obj for _, obj, _ in rows):
        add(f"added {catalog_val} to the catalog", catalog_obj, catalog_val)

    examples = [
        ShortlistExample(text=text, object=obj, fields={identity: val})
        for text, obj, val in rows[:10]
    ]
    if len(objects) > 1 and not any(ex.object == catalog_obj for ex in examples):
        examples.append(
            ShortlistExample(
                text=f"added {catalog_val} to the catalog",
                object=catalog_obj,
                fields={identity: catalog_val},
            )
        )
    if len(examples) < 8 and pad:
        extra = 0
        while len(examples) < 8 and extra < len(pad):
            term = pad[extra]
            extra += 1
            examples.append(
                ShortlistExample(
                    text=term,
                    object=event_obj,
                    fields={identity: event_val},
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
            seed = next(
                (
                    (ex.get("fields") or {}).get(identity)
                    for ex in data["examples"]
                    if (ex.get("fields") or {}).get(identity)
                    and str((ex.get("fields") or {}).get(identity)).lower()
                    not in {"alpha", "beta", "gamma"}
                ),
                identity.replace("_", " "),
            )
            data["examples"].append(
                {
                    "text": f"added {seed} to the catalog",
                    "object": catalog,
                    "fields": {identity: seed},
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
