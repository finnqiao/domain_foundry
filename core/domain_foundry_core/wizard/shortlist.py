"""Shortlist-first domain design.

The model names 5–8 key fields a person would actually log. The harness
compiles that shortlist into a full pack blueprint. Later captures slot-fill
against those fields only; leftovers become residue JSON.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from domain_foundry_core.wizard import blueprint as bp
from domain_foundry_core.wizard.models import validate_blueprint

FieldRole = Literal["identity", "when", "measure", "enum", "note", "text", "attachment", "location"]
FieldType = Literal[
    "text",
    "number",
    "integer",
    "boolean",
    "date",
    "datetime",
    "enum",
    "attachment",
    "location",
]

_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_GENERIC_OBJECTS = frozenset({"entry", "log", "item"})
_GENERIC_FIELDS = frozenset({"title", "logged_at", "rating", "amount", "notes"})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShortlistField(_Strict):
    name: str
    type: FieldType
    role: FieldRole
    object: str
    unit: str | None = None
    values: list[str] | None = None
    required: bool = False

    @field_validator("name", "object")
    @classmethod
    def _ident(cls, value: str) -> str:
        if not _IDENT_RE.match(value):
            raise ValueError(f"bad identifier {value!r}")
        return value

    @model_validator(mode="after")
    def _enum_values(self) -> ShortlistField:
        if self.type == "enum" and not self.values:
            raise ValueError(f"enum field {self.name!r} needs values")
        if self.role == "enum" and self.type != "enum":
            # Coerce role hint into type when the model is sloppy.
            object.__setattr__(self, "type", "enum")
        return self


class ShortlistExample(_Strict):
    text: str
    object: str
    fields: dict[str, Any] = Field(default_factory=dict)


class ShortlistModel(_Strict):
    """The only LLM judgment at create time."""

    domain: str
    title: str
    description: str
    objects: list[str] = Field(min_length=1, max_length=3)
    fields: list[ShortlistField] = Field(min_length=3, max_length=16)
    jargon: list[str] = Field(default_factory=list)
    examples: list[ShortlistExample] = Field(min_length=8)
    negatives: list[str] = Field(default_factory=list)

    @field_validator("domain")
    @classmethod
    def _domain_slug(cls, value: str) -> str:
        return bp.slugify(value)

    @model_validator(mode="after")
    def _shape(self) -> ShortlistModel:
        if not self.objects:
            raise ValueError("at least one object required")
        for obj in self.objects:
            if not _IDENT_RE.match(obj):
                raise ValueError(f"bad object name {obj!r}")
            if obj in _GENERIC_OBJECTS and len(self.objects) == 1:
                raise ValueError(f"sole object must not be generic {obj!r}")
        by_obj: dict[str, list[ShortlistField]] = {o: [] for o in self.objects}
        for field in self.fields:
            if field.object not in by_obj:
                raise ValueError(f"field {field.name} targets unknown object {field.object}")
            by_obj[field.object].append(field)
        for obj, fields in by_obj.items():
            if not fields:
                raise ValueError(f"object {obj} has no fields")
            if len(fields) > 8:
                raise ValueError(f"object {obj} has more than 8 fields")
            identities = [f for f in fields if f.role == "identity"]
            if len(identities) != 1:
                raise ValueError(f"object {obj} needs exactly one identity field")
        names = {f.name for f in self.fields}
        if names <= _GENERIC_FIELDS or names == {"title", "rating", "amount", "notes"} | (
            {"logged_at"} & names
        ):
            if names.issubset(_GENERIC_FIELDS):
                raise ValueError("shortlist looks like the generic entry/rating/amount log")
        for ex in self.examples:
            if ex.object not in by_obj:
                raise ValueError(f"example targets unknown object {ex.object}")
        return self


class DesignLintError(ValueError):
    """Shortlist or compiled blueprint failed the anti-template lint."""


def lint_shortlist(shortlist: ShortlistModel | dict[str, Any], *, goal: str = "") -> list[str]:
    """Return lint error strings (empty = ok)."""
    if isinstance(shortlist, dict):
        try:
            shortlist = ShortlistModel.model_validate(shortlist)
        except Exception as exc:
            return [str(exc)]

    errors: list[str] = []
    goal_words = set(bp.keywords(goal)) | {shortlist.domain}
    hobby_tokens = {w.lower() for w in goal_words if len(w) >= 3}
    hobby_tokens.add(shortlist.domain.lower())

    if len(shortlist.objects) == 1 and shortlist.objects[0] in _GENERIC_OBJECTS:
        errors.append(f"sole object is generic: {shortlist.objects[0]}")

    field_names = {f.name for f in shortlist.fields}
    if field_names.issubset(_GENERIC_FIELDS):
        errors.append("fields are the generic title/rating/amount/notes set")

    for obj in shortlist.objects:
        obj_fields = [f for f in shortlist.fields if f.object == obj]
        id_fields = [f for f in obj_fields if f.role == "identity"]
        if len(id_fields) != 1:
            errors.append(f"{obj}: need exactly one identity field")
        elif id_fields[0].name == "title" and not _titled_work(goal, shortlist):
            # Allow title for books/films; reject for session logs.
            if not any(f.name not in _GENERIC_FIELDS for f in obj_fields):
                errors.append(f"{obj}: identity is weak 'title' without specific fields")

    jargon = [j for j in shortlist.jargon if j and j.lower() not in hobby_tokens]
    if len(jargon) < 2 and len(shortlist.jargon) < 3:
        errors.append("jargon list needs interest-specific terms beyond the interest name")

    no_hobby = 0
    for ex in shortlist.examples:
        low = ex.text.lower()
        if not any(re.search(rf"\b{re.escape(t)}\b", low) for t in hobby_tokens if t):
            no_hobby += 1
    if no_hobby < 3:
        errors.append(f"need ≥3 examples without the interest name (have {no_hobby})")

    identity_by_obj = {
        obj: next(f.name for f in shortlist.fields if f.object == obj and f.role == "identity")
        for obj in shortlist.objects
        if any(f.object == obj and f.role == "identity" for f in shortlist.fields)
    }
    id_in_examples = False
    for ex in shortlist.examples:
        want = identity_by_obj.get(ex.object)
        if want and want in (ex.fields or {}):
            id_in_examples = True
            break
    if not id_in_examples:
        errors.append("identity field never appears in example fields")

    return errors


def _titled_work(goal: str, shortlist: ShortlistModel) -> bool:
    low = f"{goal} {shortlist.title} {shortlist.description}".lower()
    return bool(re.search(r"\b(book|reading|novel|film|movie|show|album|watchlist)\b", low))


def compile_shortlist(
    shortlist: ShortlistModel | dict[str, Any],
    *,
    goal: str,
) -> dict[str, Any]:
    """Compile a shortlist into a BlueprintModel-compatible dict."""
    if isinstance(shortlist, dict):
        shortlist = ShortlistModel.model_validate(shortlist)

    errors = lint_shortlist(shortlist, goal=goal)
    if errors:
        raise DesignLintError("; ".join(errors))

    objects: dict[str, Any] = {}
    for obj_name in shortlist.objects:
        fields_in = [f for f in shortlist.fields if f.object == obj_name]
        identity = next(f for f in fields_in if f.role == "identity")
        fields: dict[str, Any] = {}
        has_when = False
        for f in fields_in:
            spec: dict[str, Any] = {"type": f.type}
            if f.required or f.role == "identity":
                spec["required"] = True
            if f.unit:
                spec["unit"] = f.unit
            if f.values:
                spec["values"] = f.values
                spec["allow_other"] = True
            if f.role == "when" or f.type == "datetime":
                spec.setdefault("default", "capture_time")
                spec["required"] = True
                has_when = True
            if f.role == "note" or (f.type == "text" and f.name == "notes"):
                spec["long"] = True
            fields[f.name] = spec
        if not has_when:
            when_name = "logged_at" if "logged_at" not in fields else "noted_at"
            fields[when_name] = {
                "type": "datetime",
                "required": True,
                "default": "capture_time",
            }
        objects[obj_name] = {
            "title_field": identity.name,
            "fields": fields,
            "operations": ["create", "update", "correct", "delete"],
        }

    examples = [
        {
            "text": ex.text,
            "object": ex.object,
            "operation": "create",
            "fields": dict(ex.fields or {}),
        }
        for ex in shortlist.examples
    ]
    rules = _rules_for_objects(shortlist)
    _anchor_examples(rules, examples)
    negatives = list(shortlist.negatives) or [
        "deploy the release candidate tonight",
        "please review the pull request",
        "schedule a standup meeting",
    ]

    views = _views_from_objects(objects)
    blueprint = {
        "archetype": "llm",
        "goal": goal,
        "domain": shortlist.domain,
        "title": shortlist.title,
        "description": shortlist.description,
        "interpretation": "structured" if len(objects) > 1 else "simple",
        "icon": "✨",
        "markdown_folder": shortlist.title.split()[0] if shortlist.title else shortlist.domain,
        "objects": objects,
        "rules": rules,
        "examples": examples,
        "negatives": negatives[:5],
        "llm_hints": (
            f"Key fields: {', '.join(f.name for f in shortlist.fields)}. "
            f"Jargon: {', '.join(shortlist.jargon[:8])}."
        ),
        "views": views,
        "unit_options": {},
        "questions": [],
        "policy": {
            "defaults": [
                {"operation": "create", "min_confidence": 0.8, "action": "auto_apply"},
                {"operation": "update", "min_confidence": 0.85, "action": "auto_apply"},
                {"operation": "correct", "action": "auto_apply"},
                {"operation": "delete", "action": "review"},
            ],
            "fallback": "unfiled_card",
        },
        "meta": {
            "shortlist": [f.model_dump(exclude_none=True) for f in shortlist.fields],
        },
    }
    blueprint["agent"] = bp.build_agent_spec(blueprint)
    return validate_blueprint(blueprint)


def _tokens(text: str) -> list[str]:
    return [
        w.lower()
        for w in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text or "")
        if w.lower() not in bp._STOPWORDS
    ]


def _rules_for_objects(shortlist: ShortlistModel) -> list[dict[str, Any]]:
    """One L1 rule per object, from *that* object's vocabulary — not the domain name.

    Stamping the domain (and all jargon) onto every object makes every example
    match every object. Dry-run then fails at ~50% because the heuristic picks
    the first object. Keep shared jargon on a single primary object.
    """
    rules: list[dict[str, Any]] = []
    primary = shortlist.objects[0]
    examples_by_obj: dict[str, list[str]] = {o: [] for o in shortlist.objects}
    for ex in shortlist.examples:
        examples_by_obj.setdefault(ex.object, []).append(ex.text)

    for obj_name in shortlist.objects:
        terms: list[str] = [
            obj_name.replace("_", " "),
            obj_name,
        ]
        for f in shortlist.fields:
            if f.object != obj_name:
                continue
            terms.append(f.name.replace("_", " "))
            terms.extend((f.values or [])[:6])
        blob = " ".join(examples_by_obj.get(obj_name) or []).lower()
        for j in shortlist.jargon:
            if j and j.lower() in blob:
                terms.append(j)
        for text in examples_by_obj.get(obj_name) or []:
            terms.extend(tok for tok in _tokens(text) if len(tok) >= 4)
        if obj_name == primary or len(shortlist.objects) == 1:
            terms.append(shortlist.domain)
            terms.extend(j for j in shortlist.jargon if j)
        unique = list(dict.fromkeys(t.strip() for t in terms if t and t.strip()))
        if not unique:
            unique = [shortlist.domain]
        rules.append(
            {
                "match": "(" + "|".join(re.escape(t) for t in unique[:24]) + ")",
                "object": obj_name,
                "confidence_boost": 0.12 if obj_name == primary else 0.1,
                "operation": "create",
            }
        )
    return rules


def _anchor_examples(
    rules: list[dict[str, Any]], examples: list[dict[str, Any]]
) -> None:
    """Give each self-example a high-boost token so dry-run can pick the right object."""
    other_blobs: dict[str, str] = {}
    for ex in examples:
        other_blobs.setdefault(ex["object"], "")
        other_blobs[ex["object"]] += " " + (ex["text"] or "").lower()

    extra: list[dict[str, Any]] = []
    for ex in examples:
        text = ex.get("text") or ""
        obj = ex.get("object")
        if not text or not obj:
            continue
        matching = _matching_objects(rules + extra, text)
        if matching == {obj}:
            continue
        anchor = _example_anchor(text, obj, other_blobs)
        if not anchor:
            continue
        extra.append(
            {
                "match": re.escape(anchor),
                "object": obj,
                "confidence_boost": 0.25,
                "operation": "create",
            }
        )
    rules.extend(extra)


def _matching_objects(rules: list[dict[str, Any]], text: str) -> set[str]:
    matched: set[str] = set()
    for rule in rules:
        try:
            if re.search(rule["match"], text, re.IGNORECASE):
                matched.add(str(rule["object"]))
        except re.error:
            continue
    return matched


def _example_anchor(text: str, obj: str, blobs: dict[str, str]) -> str | None:
    tokens = [t for t in _tokens(text) if len(t) >= 4]
    for tok in sorted(tokens, key=len, reverse=True):
        elsewhere = " ".join(v for k, v in blobs.items() if k != obj)
        if tok not in elsewhere:
            return tok
    if tokens:
        return max(tokens, key=len)
    words = re.findall(r"[A-Za-z]{3,}", text)
    if len(words) >= 2:
        return f"{words[0]} {words[1]}"
    return words[0] if words else None


def _views_from_objects(objects: dict[str, Any]) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    for obj_name, obj in objects.items():
        fields = obj.get("fields") or {}
        date_field = next(
            (n for n, s in fields.items() if s.get("type") == "datetime"),
            None,
        )
        has_location = any(
            s.get("type") == "location" or n in {"lat", "lng", "location"} for n, s in fields.items()
        )
        has_attachment = any(s.get("type") == "attachment" for s in fields.values())
        measures = [n for n, s in fields.items() if s.get("type") in {"number", "integer"}]
        if has_location:
            views.append(
                {
                    "id": f"{obj_name}_map",
                    "title": f"{obj_name.replace('_', ' ').title()} map",
                    "block": "map",
                    "object": obj_name,
                    "config": {},
                }
            )
        if has_attachment:
            att = next(n for n, s in fields.items() if s.get("type") == "attachment")
            views.append(
                {
                    "id": f"{obj_name}_gallery",
                    "title": "Gallery",
                    "block": "gallery",
                    "object": obj_name,
                    "config": {"gallery": att},
                }
            )
        if date_field:
            views.append(
                {
                    "id": bp._pluralize(obj_name),
                    "title": obj_name.replace("_", " ").title(),
                    "block": "timeline",
                    "object": obj_name,
                    "config": {"date_field": date_field},
                }
            )
        else:
            views.append(
                {
                    "id": bp._pluralize(obj_name),
                    "title": obj_name.replace("_", " ").title(),
                    "block": "list",
                    "object": obj_name,
                    "config": {},
                }
            )
        if len(measures) >= 2:
            views.append(
                {
                    "id": f"{obj_name}_stats",
                    "title": "Stats",
                    "block": "stats",
                    "object": obj_name,
                    "config": {
                        "measures": [{"field": m, "agg": "trend"} for m in measures[:3]],
                    },
                }
            )
    return views


def shortlist_schema() -> dict[str, Any]:
    return ShortlistModel.model_json_schema()


def analog_few_shots(goal: str) -> list[dict[str, Any]]:
    """Pick two shortlist-shaped analogs by goal smell — never the generic log."""
    low = (goal or "").lower()
    plants = {
        "goal": "track my houseplants",
        "shortlist": {
            "domain": "plants",
            "title": "Plant Care",
            "description": "Watering, repotting, and observations for houseplants.",
            "objects": ["plant", "care_event"],
            "fields": [
                {"name": "plant_name", "type": "text", "role": "identity", "object": "plant", "required": True},
                {"name": "species", "type": "text", "role": "text", "object": "plant"},
                {"name": "status", "type": "enum", "role": "enum", "object": "plant",
                 "values": ["thriving", "ok", "struggling", "dormant"]},
                {"name": "plant_name", "type": "text", "role": "identity", "object": "care_event", "required": True},
                {"name": "action", "type": "enum", "role": "enum", "object": "care_event",
                 "values": ["water", "fertilize", "repot", "prune", "mist", "observe"]},
                {"name": "noted_at", "type": "datetime", "role": "when", "object": "care_event"},
                {"name": "soil_moisture", "type": "enum", "role": "enum", "object": "care_event",
                 "values": ["dry", "damp", "wet"]},
                {"name": "notes", "type": "text", "role": "note", "object": "care_event"},
            ],
            "jargon": ["monstera", "pothos", "repot", "mist", "soil", "yellowing"],
            "examples": [
                {"text": "watered the monstera", "object": "care_event",
                 "fields": {"plant_name": "monstera", "action": "water"}},
                {"text": "repotted the fiddle leaf", "object": "care_event",
                 "fields": {"plant_name": "fiddle leaf", "action": "repot"}},
                {"text": "new leaf on the pothos", "object": "care_event",
                 "fields": {"plant_name": "pothos", "action": "observe"}},
                {"text": "soil was bone dry", "object": "care_event",
                 "fields": {"action": "observe", "soil_moisture": "dry", "plant_name": "plant"}},
                {"text": "misted the fern this morning", "object": "care_event",
                 "fields": {"plant_name": "fern", "action": "mist"}},
                {"text": "added a calathea to the shelf", "object": "plant",
                 "fields": {"plant_name": "calathea", "status": "ok"}},
                {"text": "snake plant is thriving by the window", "object": "plant",
                 "fields": {"plant_name": "snake plant", "status": "thriving"}},
                {"text": "fertilized after watering", "object": "care_event",
                 "fields": {"action": "fertilize", "plant_name": "plant"}},
                {"text": "yellowing leaves on the lower stems", "object": "care_event",
                 "fields": {"action": "observe", "plant_name": "plant", "notes": "yellowing leaves"}},
                {"text": "zz plant looking dormant for winter", "object": "plant",
                 "fields": {"plant_name": "zz plant", "status": "dormant"}},
            ],
            "negatives": ["deploy the release candidate tonight", "schedule a standup meeting"],
        },
    }
    sourdough = {
        "goal": "track my sourdough baking",
        "shortlist": {
            "domain": "sourdough",
            "title": "Sourdough Journey",
            "description": "Track starters, bakes, and what each loaf teaches you.",
            "objects": ["bake", "starter"],
            "fields": [
                {"name": "loaf_name", "type": "text", "role": "identity", "object": "bake", "required": True},
                {"name": "baked_at", "type": "datetime", "role": "when", "object": "bake"},
                {"name": "hydration", "type": "number", "role": "measure", "object": "bake", "unit": "percent"},
                {"name": "flour_mix", "type": "text", "role": "text", "object": "bake"},
                {"name": "bulk_hours", "type": "number", "role": "measure", "object": "bake", "unit": "hours"},
                {"name": "result", "type": "enum", "role": "enum", "object": "bake",
                 "values": ["dense", "decent", "good", "great"]},
                {"name": "notes", "type": "text", "role": "note", "object": "bake"},
                {"name": "name", "type": "text", "role": "identity", "object": "starter", "required": True},
                {"name": "status", "type": "enum", "role": "enum", "object": "starter",
                 "values": ["active", "dormant", "retired"]},
            ],
            "jargon": ["boule", "batard", "levain", "crumb", "bulk ferment", "oven spring"],
            "examples": [
                {"text": "baked a 75% hydration country loaf", "object": "bake",
                 "fields": {"loaf_name": "country loaf", "hydration": 75}},
                {"text": "80% hydration batard, bulk 4 hours", "object": "bake",
                 "fields": {"loaf_name": "batard", "hydration": 80, "bulk_hours": 4}},
                {"text": "fed the rye starter", "object": "starter",
                 "fields": {"name": "rye starter"}},
                {"text": "great oven spring on today's boule", "object": "bake",
                 "fields": {"loaf_name": "boule", "result": "great"}},
                {"text": "crumb was open and glossy", "object": "bake",
                 "fields": {"loaf_name": "loaf", "result": "great"}},
                {"text": "levain doubled in four hours", "object": "starter",
                 "fields": {"name": "levain", "status": "active"}},
                {"text": "sandwich loaf at 70% came out dense", "object": "bake",
                 "fields": {"loaf_name": "sandwich loaf", "hydration": 70, "result": "dense"}},
                {"text": "starter went dormant after vacation", "object": "starter",
                 "fields": {"name": "starter", "status": "dormant"}},
                {"text": "20% rye mix with good oven spring", "object": "bake",
                 "fields": {"flour_mix": "20% rye", "result": "good", "loaf_name": "rye loaf"}},
                {"text": "bulk fermented 6h then shaped", "object": "bake",
                 "fields": {"bulk_hours": 6, "loaf_name": "loaf"}},
            ],
            "negatives": ["deploy the release candidate tonight", "the cloud invoice is overdue"],
        },
    }
    session = {
        "goal": "track my climbing sessions",
        "shortlist": {
            "domain": "climbing",
            "title": "Climbing Log",
            "description": "Sends, attempts, and grades at the gym or crag.",
            "objects": ["session"],
            "fields": [
                {"name": "route_name", "type": "text", "role": "identity", "object": "session", "required": True},
                {"name": "climbed_at", "type": "datetime", "role": "when", "object": "session"},
                {"name": "grade", "type": "text", "role": "measure", "object": "session"},
                {"name": "gym", "type": "text", "role": "text", "object": "session"},
                {"name": "result", "type": "enum", "role": "enum", "object": "session",
                 "values": ["send", "flash", "attempt", "project"]},
                {"name": "notes", "type": "text", "role": "note", "object": "session"},
            ],
            "jargon": ["heel hook", "crux", "flash", "send", "overhang", "volume", "climb", "boulder", "route"],
            "examples": [
                {"text": "sent a tough V5 on the overhang, crux was the heel hook",
                 "object": "session",
                 "fields": {"route_name": "overhang", "grade": "V5", "result": "send",
                            "notes": "crux was the heel hook"}},
                {"text": "flashed the blue route after two attempts",
                 "object": "session",
                 "fields": {"route_name": "blue route", "result": "flash"}},
                {"text": "worked the slab climb project for an hour",
                 "object": "session",
                 "fields": {"route_name": "slab project", "result": "project"}},
                {"text": "V4 send at the cave",
                 "object": "session",
                 "fields": {"grade": "V4", "result": "send", "route_name": "cave", "gym": "cave"}},
                {"text": "heel hook finally stuck on the volume",
                 "object": "session",
                 "fields": {"route_name": "volume", "notes": "heel hook"}},
                {"text": "attempted the red overhang three times",
                 "object": "session",
                 "fields": {"route_name": "red overhang", "result": "attempt"}},
                {"text": "easy warmups then a hard crux move on the route",
                 "object": "session",
                 "fields": {"route_name": "warmups", "notes": "hard crux move"}},
                {"text": "new personal best send on the campus board",
                 "object": "session",
                 "fields": {"route_name": "campus board", "result": "send"}},
                {"text": "dyno on the yellow climb felt clean",
                 "object": "session",
                 "fields": {"route_name": "yellow problem", "result": "send"}},
                {"text": "session at Brooklyn Boulders, mostly volume work",
                 "object": "session",
                 "fields": {"gym": "Brooklyn Boulders", "route_name": "volume work"}},
            ],
            "negatives": ["please review the pull request", "rotate the api credentials"],
        },
    }

    if re.search(r"\b(plant|garden|water|repot|houseplant)\b", low):
        return [plants, sourdough]
    if re.search(r"\b(climb|bould\w*|route|v\d|send|crag)\b", low):
        return [session, plants]
    if re.search(r"\b(bake|bread|sourdough|loaf)\b", low):
        return [sourdough, plants]
    if re.search(r"\b(guitar|music|practice|session|run|workout)\b", low):
        return [session, sourdough]
    return [plants, sourdough]


__all__ = [
    "DesignLintError",
    "ShortlistField",
    "ShortlistModel",
    "analog_few_shots",
    "compile_shortlist",
    "lint_shortlist",
    "shortlist_schema",
]
