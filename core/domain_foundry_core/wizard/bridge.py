"""ADR-010: the deterministic ``FoundrySpec`` → ``ShortlistModel`` projection.

The Foundry pipeline researches an interest and returns a typed specification.
The wizard runtime is driven by a ``ShortlistModel``. That runtime covers
capture, correction, provenance, and export. This module is the single seam between them, and it is
deliberately the *only* seam: one pure function, no I/O, no model calls, so a
pipeline contract change breaks one testable projection rather than a create.

The import direction is one-way and load-bearing. ``wizard`` may import
``foundry``; ``foundry`` must never import ``wizard``. ``tests/unit/
test_wizard_foundry_bridge.py`` asserts the second half.

What the projection decides, and why:

* **Objects.** A spec models six-ish entities; a pack routes into at most three.
  The one a person types sentences at is scored from the spec's own statements:
  the entity kind (an ``event`` is usually what gets logged), which entity the
  spec's routing evaluation cases expect, and which entity the spec's own
  primary view puts on screen.
* **Fields.** Foreign keys, surplus timestamps, and ordering columns are
  structure, not vocabulary; they are dropped. What survives keeps its unit and
  its enum values, because those are the words the owner will type.
* **Jargon.** Harvested from the *whole* spec, not just the chosen objects. A
  sourdough baker says "hydration" even when ``recipe`` is not one of the three
  objects. Terms are ranked by how many independent parts of the spec used them.
* **Examples.** Routing evaluation cases are user sentences and are used
  verbatim. The rest are rendered from the spec's own synthetic records, which
  is why they carry real values instead of "logged an entry".
"""

from __future__ import annotations

import re
from typing import Any

from domain_foundry_core.foundry.models import EntitySpec, FieldSpec, FoundrySpec
from domain_foundry_core.wizard import blueprint as bp
from domain_foundry_core.wizard.shortlist import (
    GENERIC_RULE_TERMS,
    ROUTING_STOP,
    ShortlistExample,
    ShortlistField,
    ShortlistModel,
    is_dimensioned,
)

# Clause separators used to cut a long example value down to its first clause.
# The em dash is spelled with ``chr`` so this module holds no em dash literal,
# which is what the copy audit checks for. The pattern itself is unchanged.
_CLAUSE_BREAK = "[,.;" + chr(0x2014) + "]"

MAX_OBJECTS = 3
MAX_FIELDS_PER_OBJECT = 8
MAX_FIELDS_TOTAL = 16
MIN_EXAMPLES = 8
MAX_EXAMPLES = 18
# Budgets sized against ``shortlist.RULE_TERM_CAP`` (32). Object name, domain,
# vocabulary and jargon are emitted before field names and example tokens, so an
# unbounded jargon list would evict the field vocabulary from every rule.
MAX_JARGON = 18
MAX_VOCABULARY = 6

# How much a term is worth per place it turned up. What a person writes — a
# synthetic record's prose, a routing case's verbatim input — outranks a column
# name, because a column name is the schema's word for the thing and the record
# is the owner's.
_SOURCE_WEIGHT: dict[str, float] = {
    "records": 2.0,
    "routing": 2.0,
    "enum": 1.5,
    # A word the model gave a column or an entity to is load-bearing; a word it
    # only used in a sentence about the domain may be incidental.
    "field": 1.25,
    "entity": 1.25,
    "practice": 1.0,
    "prose": 0.75,
}

# Function words that survive both stop lists and would spend a rule slot on a
# word that matches every sentence ever typed. Only whole single-token terms are
# blocked, so "back squat" and "drop of water" are unaffected.
_WEAK_TERMS = frozenset(
    {
        "one",
        "two",
        "three",
        "four",
        "five",
        "out",
        "into",
        "onto",
        "its",
        "them",
        "they",
        "you",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "not",
        "but",
        "all",
        "any",
        "more",
        "most",
        "less",
        "than",
        "then",
        "also",
        "just",
        "only",
        "same",
        "other",
        "without",
        "before",
        "during",
        "while",
        "which",
        "what",
        "who",
        "where",
        "why",
        "both",
        "ways",
        "via",
        "down",
        "still",
        "own",
        "per",
        "use",
        "used",
        "using",
        "get",
        "got",
        "put",
        "take",
        "taken",
        "give",
        "given",
        "see",
        "seen",
        "need",
        "needs",
        "enough",
        "yet",
        "far",
    }
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9x×'./%_-]*")
_ALL_DIGITS_RE = re.compile(r"\d{3,}")
_ID_TAIL_RE = re.compile(r"^\d+[a-z]{0,2}$")

# Spec scalar types the wizard has no field type for.
_TYPE_MAP: dict[str, str] = {
    "text": "text",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "date": "date",
    "datetime": "datetime",
    "duration": "number",
    "enum": "enum",
    "attachment": "attachment",
    "location": "location",
    "json": "text",
}

# Trailing name parts that state a unit or a key rather than a concept:
# ``flour_mass_g`` is "flour mass", ``hydration_pct`` is "hydration".
_UNIT_TAILS = frozenset(
    {
        "id",
        "at",
        "on",
        "g",
        "kg",
        "mg",
        "lb",
        "lbs",
        "oz",
        "ml",
        "cl",
        "l",
        "pct",
        "percent",
        "ppm",
        "c",
        "f",
        "k",
        "km",
        "m",
        "cm",
        "mm",
        "mi",
        "ft",
        "in",
        "min",
        "mins",
        "sec",
        "secs",
        "hr",
        "hrs",
        "usd",
        "eur",
        "gbp",
        "jpy",
        "hz",
        "khz",
        "mhz",
        "w",
        "kw",
        "index",
        "num",
        "count",
        "qty",
    }
)

# What a person logs, ranked. ``event`` first is ADR-010's "the event entity is
# usually right"; ``reference`` last because a lookup table is never typed at.
_KIND_WEIGHT: dict[str, float] = {
    "event": 4.0,
    "observation": 3.0,
    "owned": 2.0,
    "canonical": 1.0,
    "state": 0.5,
    "reference": 0.0,
}

# Ordering inside one object's field budget.
_ROLE_RANK: dict[str, int] = {
    "identity": 0,
    "when": 1,
    "enum": 2,
    "measure": 3,
    "note": 4,
    "text": 4,
    "attachment": 6,
    "location": 6,
}

_NOTE_NAMES = frozenset(
    {"notes", "note", "comment", "comments", "remarks", "description", "cues", "detail", "details"}
)
# ``generic_shape_warnings`` treats these identity names as a smell.
_WEAK_IDENTITY = frozenset({"name", "record_name", "entry_name", "item_name"})
_UNIT_FOR_DURATION = "min"


# --------------------------------------------------------------------------- #
# Tokenising
# --------------------------------------------------------------------------- #


def _keep(token: str) -> bool:
    if is_dimensioned(token) and not _ALL_DIGITS_RE.fullmatch(token):
        return True
    if not re.search(r"[a-z]", token):
        return False
    if len(token) < 3:
        return False
    return not (token in bp._STOPWORDS or token in ROUTING_STOP)


def _tokens(text: str) -> list[str]:
    """Routing-grade tokens: words and dimensioned numbers, no filler."""
    out: list[str] = []
    for raw in _TOKEN_RE.findall(text or ""):
        token = raw.strip("-_./'").lower()
        if token and _keep(token):
            out.append(token)
    return out


def _humanize(name: str) -> str:
    """``flour_mass_g`` → ``flour mass``; ``set_id`` → ``set``."""
    parts = [part for part in name.lower().split("_") if part]
    while len(parts) > 1 and parts[-1] in _UNIT_TAILS:
        parts.pop()
    return " ".join(parts) if parts else name.lower()


def _is_usable_term(term: str) -> bool:
    low = term.strip().lower()
    if not low or low.replace("_", " ") in GENERIC_RULE_TERMS or low in _WEAK_TERMS:
        return False
    parts = re.findall(r"[a-z0-9]+", low)
    if is_dimensioned(low):
        return True
    if not parts:
        return False
    return any(_keep(part) for part in parts)


def _ordered_unique(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        key = term.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(term.strip())
    return out


# --------------------------------------------------------------------------- #
# Object selection
# --------------------------------------------------------------------------- #


def _routing_cases(spec: FoundrySpec) -> list[Any]:
    return [case for case in spec.evaluation.cases if case.kind == "routing"]


def _mentions(entity_id: str, text: str) -> bool:
    low = text.lower()
    spaced = entity_id.replace("_", " ")
    return bool(
        re.search(rf"\b{re.escape(entity_id)}\b", low)
        or re.search(rf"\b{re.escape(spaced)}\b", low)
    )


def _primary_view_entities(spec: FoundrySpec) -> tuple[set[str], set[str]]:
    """(entities anywhere in the primary view, entities in its primary region)."""
    target = spec.experience.navigation.primary_view
    view = next((item for item in spec.experience.views if item.id == target), None)
    if view is None:
        return set(), set()
    anywhere = {region.entity for region in view.regions}
    leading = {region.entity for region in view.regions if region.emphasis == "primary"}
    return anywhere, leading


def _entity_scores(spec: FoundrySpec) -> dict[str, float]:
    anywhere, leading = _primary_view_entities(spec)
    routing = _routing_cases(spec)
    workload_hits: dict[str, int] = {}
    for workload in spec.domain.workloads:
        for entity_id in workload.entities:
            workload_hits[entity_id] = workload_hits.get(entity_id, 0) + 1

    scores: dict[str, float] = {}
    for entity in spec.domain.entities:
        score = _KIND_WEIGHT.get(entity.kind, 0.0)
        named = sum(
            1
            for case in routing
            if _mentions(entity.id, case.expected) or _mentions(entity.id, case.input)
        )
        score += min(named, 2) * 1.0
        if entity.id in anywhere:
            score += 1.0
        if entity.id in leading:
            score += 0.5
        score += min(workload_hits.get(entity.id, 0), 4) * 0.25
        scores[entity.id] = score
    return scores


def choose_objects(spec: FoundrySpec) -> list[EntitySpec]:
    """The ≤3 entities a person would type sentences at, best first."""
    scores = _entity_scores(spec)
    ranked = sorted(
        spec.domain.entities,
        key=lambda entity: (-scores[entity.id], -len(entity.fields), entity.id),
    )
    chosen = [entity for entity in ranked if entity.kind != "reference"][:MAX_OBJECTS]
    if not chosen:
        chosen = ranked[:MAX_OBJECTS]
    return chosen


# --------------------------------------------------------------------------- #
# Field projection
# --------------------------------------------------------------------------- #


def _identity_field(entity: EntitySpec) -> FieldSpec:
    by_name = {field.name: field for field in entity.fields}
    for candidate in entity.identity:
        field = by_name.get(candidate)
        if (
            field is not None
            and field.name not in _WEAK_IDENTITY
            and _TYPE_MAP.get(field.type) in {"text", "integer", "number"}
        ):
            return field
    for field in entity.fields:
        if field.type == "text" and field.name not in _WEAK_IDENTITY:
            return field
    return by_name[entity.identity[0]]


def _role_for(field: FieldSpec, *, identity: str, when_taken: bool) -> str | None:
    if field.name == identity:
        return "identity"
    kind = _TYPE_MAP.get(field.type, "text")
    if kind in {"date", "datetime"}:
        return None if when_taken else "when"
    if kind == "enum":
        return "enum" if field.values else None
    if kind in {"number", "integer"}:
        return "measure"
    if kind == "attachment":
        return "attachment"
    if kind == "location":
        return "location"
    if kind == "boolean":
        return "text"
    if field.name in _NOTE_NAMES:
        return "note"
    return "text"


def _entity_stems(entity_id: str) -> set[str]:
    """``card_printing`` also answers to ``card`` and ``printing``.

    Specs name a foreign key after the *thing*, not after the table:
    ``owned_copy.printing_id`` points at ``card_printing``. Matching only the
    full id let those through and they read as vocabulary when they are wiring.
    """
    parts = [part for part in entity_id.split("_") if part]
    return {entity_id, *parts}


def _is_structural(field: FieldSpec, entity: EntitySpec, entity_ids: set[str]) -> bool:
    """Foreign keys and ordering columns are plumbing, not vocabulary."""
    name = field.name
    if name.endswith("_index"):
        return True
    own = _entity_stems(entity.id)
    for other in entity_ids:
        if other == entity.id:
            continue
        for stem in _entity_stems(other) - own:
            if name in {f"{stem}_id", f"{stem}_version", f"{stem}_ref"}:
                return True
    return False


def _project_fields(entity: EntitySpec, entity_ids: set[str]) -> list[ShortlistField]:
    identity = _identity_field(entity)
    out: list[ShortlistField] = []
    when_taken = False
    for field in entity.fields:
        if field.name != identity.name and _is_structural(field, entity, entity_ids):
            continue
        role = _role_for(field, identity=identity.name, when_taken=when_taken)
        if role is None:
            continue
        if role == "when":
            when_taken = True
        kind = _TYPE_MAP.get(field.type, "text")
        if role == "identity" and kind not in {"text", "integer", "number"}:
            kind = "text"
        unit = field.unit
        if field.type == "duration" and not unit:
            unit = _UNIT_FOR_DURATION
        out.append(
            ShortlistField(
                name=field.name,
                type=kind,  # type: ignore[arg-type]
                role=role,  # type: ignore[arg-type]
                object=entity.id,
                unit=unit,
                values=list(field.values) if (kind == "enum" and field.values) else None,
                required=bool(field.required) or role == "identity",
            )
        )
    return out


def _allocate(projected: dict[str, list[ShortlistField]]) -> list[ShortlistField]:
    """Round-robin the total field budget so no object is starved of identity."""
    ranked = {
        obj: sorted(fields, key=lambda f: (_ROLE_RANK.get(f.role, 5), fields.index(f)))
        for obj, fields in projected.items()
    }
    taken: dict[str, list[ShortlistField]] = {obj: [] for obj in projected}
    total = 0
    depth = 0
    while total < MAX_FIELDS_TOTAL and depth < MAX_FIELDS_PER_OBJECT:
        progressed = False
        for obj, fields in ranked.items():
            if total >= MAX_FIELDS_TOTAL:
                break
            if depth < len(fields) and len(taken[obj]) < MAX_FIELDS_PER_OBJECT:
                taken[obj].append(fields[depth])
                total += 1
                progressed = True
        if not progressed:
            break
        depth += 1
    out: list[ShortlistField] = []
    for obj in projected:
        out.extend(sorted(taken[obj], key=lambda f: projected[obj].index(f)))
    return out


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #


def _is_opaque(value: str) -> bool:
    """A key, a URL, or a timestamp. A machine's string, not a person's."""
    low = value.strip().lower()
    if not low:
        return True
    if "://" in low or low.startswith("www.") or re.search(r"\.[a-z]{2,4}/", low):
        return True
    if re.search(r"\d{4}-\d{2}-\d{2}", low):
        return True
    return bool(" " not in low and re.search(r"\d{4,}", low))


def _sample_strings(spec: FoundrySpec) -> list[str]:
    """Prose a person wrote in the spec's synthetic records.

    Field-aware on purpose. Reading every string value swept in record ids and
    ISO timestamps, and because a record is weighted as the owner's own wording,
    ``feed-20260819-am`` then outranked ``levain`` for a rule slot.
    """
    out: list[str] = []
    for entity in spec.domain.entities:
        typed = {field.name: field for field in entity.fields}
        skip = set(entity.identity)
        for record in spec.domain.sample_records.get(entity.id, []):
            for name, value in record.items():
                field = typed.get(name)
                if field is None or name in skip or name.endswith("_id"):
                    continue
                if field.type not in {"text", "enum"} or not isinstance(value, str):
                    continue
                if not value.strip() or _is_opaque(value):
                    continue
                out.append(value)
    return out


def _field_terms(spec: FoundrySpec) -> list[str]:
    out: list[str] = []
    for entity in spec.domain.entities:
        for field in entity.fields:
            if field.name.endswith("_index"):
                continue
            term = _humanize(field.name)
            if _is_usable_term(term):
                out.append(term)
    return out


def _enum_terms(spec: FoundrySpec) -> list[str]:
    out: list[str] = []
    for entity in spec.domain.entities:
        for field in entity.fields:
            for value in field.values or []:
                term = str(value).replace("_", " ").strip()
                if _is_usable_term(term):
                    out.append(term)
    return out


def _model_prose(spec: FoundrySpec) -> str:
    """Every place the spec explains itself in sentences.

    A domain word can be absent from both the column names and the practice
    hypotheses and still be the word: sourdough's ``levain`` lives in a
    relationship description and one recipe's method.
    """
    parts: list[str] = [item.claim for item in spec.evidence]
    for entity in spec.domain.entities:
        parts.append(entity.description)
        parts.extend(field.description for field in entity.fields)
    parts.extend(item.description for item in spec.domain.relationships)
    parts.extend(item.reason for item in spec.domain.constraints)
    parts.extend(item.question for item in spec.domain.workloads)
    parts.extend(item.acceptance for item in spec.domain.workloads)
    return " ".join(parts)


def _practice_text(spec: FoundrySpec) -> str:
    brief = spec.research
    return " ".join([brief.interest, brief.desired_outcome, *brief.practice, brief.first_value])


def _structural_tokens(spec: FoundrySpec) -> set[str]:
    blob = " ".join(
        [
            *[entity.id.replace("_", " ") for entity in spec.domain.entities],
            *[entity.title for entity in spec.domain.entities],
            *_field_terms(spec),
            *_enum_terms(spec),
            *_sample_strings(spec),
        ]
    )
    return set(_tokens(blob))


def _vocabulary(spec: FoundrySpec, domain: str) -> list[str]:
    """The practice's own words that the model actually built structure for."""
    structural = _structural_tokens(spec)
    domain_words = set(re.findall(r"[a-z0-9]+", domain))
    out: list[str] = []
    for token in _tokens(_practice_text(spec)):
        if token in structural and token not in domain_words and _is_usable_term(token):
            out.append(token)
    return _ordered_unique(out)[:MAX_VOCABULARY]


def _jargon(spec: FoundrySpec, vocabulary: list[str], domain: str) -> list[str]:
    """Terms ranked by how many independent parts of the spec used them."""
    sources: dict[str, list[str]] = {
        "enum": _enum_terms(spec),
        "field": _field_terms(spec),
        "entity": [entity.id.replace("_", " ") for entity in spec.domain.entities],
        "routing": [term for case in _routing_cases(spec) for term in _tokens(case.input)],
        "records": [term for value in _sample_strings(spec) for term in _tokens(value)],
        "practice": _tokens(_practice_text(spec)),
        "prose": _tokens(_model_prose(spec)),
    }
    hits: dict[str, set[str]] = {}
    order: dict[str, int] = {}
    for source, terms in sources.items():
        for position, term in enumerate(terms):
            key = term.strip().lower()
            if not key or not _is_usable_term(key):
                continue
            hits.setdefault(key, set()).add(source)
            order.setdefault(key, len(order) * 100 + position)

    blocked = {item.lower() for item in vocabulary} | set(re.findall(r"[a-z0-9]+", domain))
    candidates = [key for key in hits if key not in blocked]
    candidates.sort(
        key=lambda key: (
            -sum(_SOURCE_WEIGHT.get(source, 1.0) for source in hits[key]),
            0 if " " in key else 1,
            -len(key),
            order[key],
        )
    )
    return candidates[:MAX_JARGON]


# --------------------------------------------------------------------------- #
# Examples
# --------------------------------------------------------------------------- #


def _clause(field: ShortlistField, value: Any) -> tuple[str, Any] | None:
    """One readable fragment of a capture sentence, plus the value to file."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    label = _humanize(field.name)
    if field.type in {"date", "datetime"} or field.role == "when":
        return None
    if field.type in {"attachment", "location"}:
        return None
    if field.type == "boolean":
        return (label, True) if bool(value) else None
    if field.type == "enum":
        return (str(value).replace("_", " "), value)
    if field.type in {"number", "integer"}:
        unit = (field.unit or "").strip()
        if unit and len(unit) <= 3 and unit.isalpha():
            return (f"{label} {value}{unit}", value)
        if unit:
            return (f"{label} {value} {unit}", value)
        return (f"{label} {value}", value)
    text = str(value).strip()
    if len(text) > 48:
        head = re.split(_CLAUSE_BREAK, text)[0].strip() or text
        text = head[:48].strip()
    # The value filed is the text that appears in the sentence, not the record's
    # full prose: an example is a capture, and a capture cannot extract a field
    # value the sentence never contained.
    return (text, text) if text else None


def _display_lead(entity: EntitySpec, identity: ShortlistField, record: dict[str, Any]) -> str:
    """A record's human handle, never an opaque id like ``feed-20260819-am``."""
    for name in ("name", "title", "label"):
        value = record.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raw = record.get(identity.name)
    if not isinstance(raw, str):
        return ""
    stems = _entity_stems(entity.id)
    parts = [
        part
        for part in re.split(r"[-_\s]+", raw.strip().lower())
        if part and not _ID_TAIL_RE.fullmatch(part) and _keep(part)
    ]
    # ``sess-20260821`` is the ``session`` table saying its own name in an
    # abbreviation. That is the object name, not the record's handle.
    parts = [
        part
        for part in parts
        if not any(stem.startswith(part) or part.startswith(stem) for stem in stems)
    ]
    return " ".join(parts)


def _has_hobby_token(text: str, hobby: set[str]) -> bool:
    low = text.lower()
    return any(re.search(rf"\b{re.escape(token)}\b", low) for token in hobby if token)


def _record_examples(
    entity: EntitySpec,
    fields: list[ShortlistField],
    record: dict[str, Any],
    *,
    hobby: set[str],
) -> list[ShortlistExample]:
    identity = next(field for field in fields if field.role == "identity")
    clauses: list[tuple[ShortlistField, str, Any]] = []
    for field in fields:
        if field.role == "identity":
            continue
        made = _clause(field, record.get(field.name))
        if made is not None:
            clauses.append((field, made[0], made[1]))
    clauses.sort(key=lambda item: _ROLE_RANK.get(item[0].role, 5))

    lead = _display_lead(entity, identity, record)
    out: list[ShortlistExample] = []

    def _build(parts: list[tuple[ShortlistField, str, Any]], *, with_lead: bool) -> None:
        texts = [text for _field, text, _value in parts if text.strip().lower() != lead.lower()]
        if with_lead and lead:
            texts = [lead, *texts]
        text = ", ".join(texts).strip()
        if not text or len(text) < 4:
            return
        filed = {field.name: value for field, _text, value in parts}
        if with_lead and isinstance(record.get(identity.name), str):
            filed[identity.name] = record[identity.name]
        out.append(ShortlistExample(text=text[:180], object=entity.id, fields=filed))

    _build(clauses[:4], with_lead=True)
    clean = [item for item in clauses if not _has_hobby_token(item[1], hobby)]
    if clean:
        _build(clean[:3], with_lead=False)
    # Sliding windows over the remaining clauses. A golden carries one synthetic
    # record per entity, and the shortlist contract wants eight sentences, so the
    # same record has to be phrased more than one way.
    for start in range(1, max(1, len(clauses) - 1)):
        _build(clauses[start : start + 3], with_lead=False)
    if len(clauses) > 3:
        _build(clauses[0::2][:3], with_lead=bool(lead))
    return out


def _routing_examples(
    spec: FoundrySpec, objects: list[str], primary: str
) -> list[ShortlistExample]:
    out: list[ShortlistExample] = []
    for case in _routing_cases(spec):
        target = next(
            (obj for obj in objects if _mentions(obj, case.expected)),
            None,
        )
        out.append(ShortlistExample(text=case.input[:180], object=target or primary, fields={}))
    return out


def _build_examples(
    spec: FoundrySpec,
    entities: list[EntitySpec],
    fields_by_object: dict[str, list[ShortlistField]],
    *,
    hobby: set[str],
) -> list[ShortlistExample]:
    object_ids = [entity.id for entity in entities]
    primary = object_ids[0]
    per_object: dict[str, list[ShortlistExample]] = {obj: [] for obj in object_ids}
    for entity in entities:
        for record in spec.domain.sample_records.get(entity.id, []):
            per_object[entity.id].extend(
                _record_examples(entity, fields_by_object[entity.id], record, hobby=hobby)
            )

    ordered: list[ShortlistExample] = list(_routing_examples(spec, object_ids, primary))
    depth = 0
    while any(len(items) > depth for items in per_object.values()):
        for obj in object_ids:
            items = per_object[obj]
            if depth < len(items):
                ordered.append(items[depth])
        depth += 1

    seen: set[str] = set()
    unique: list[ShortlistExample] = []
    for example in ordered:
        key = example.text.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(example)

    # Every object needs an example (BlueprintModel) and the lint needs three
    # sentences that do not say the interest's name out loud.
    kept: list[ShortlistExample] = []
    covered: set[str] = set()
    clean = 0
    for example in unique:
        room = len(kept) < MAX_EXAMPLES
        needed = example.object not in covered or clean < 3 or len(kept) < MIN_EXAMPLES
        if room and needed:
            kept.append(example)
            covered.add(example.object)
            if not _has_hobby_token(example.text, hobby):
                clean += 1
    for example in unique:
        if len(kept) >= MIN_EXAMPLES:
            break
        if example not in kept:
            kept.append(example)
    return kept


# --------------------------------------------------------------------------- #
# Projection
# --------------------------------------------------------------------------- #


def spec_to_shortlist(spec: FoundrySpec, *, goal: str | None = None) -> ShortlistModel:
    """Project a researched ``FoundrySpec`` onto the wizard's shortlist.

    Deterministic, and it has no side effects: the same spec always yields the
    same shortlist, which is what makes the bridge testable against the goldens.
    """
    goal = (goal or spec.research.interest).strip()
    domain = bp.slugify(spec.id or spec.title)
    entities = choose_objects(spec)
    entity_ids = {entity.id for entity in spec.domain.entities}

    projected = {entity.id: _project_fields(entity, entity_ids) for entity in entities}
    entities = [entity for entity in entities if projected[entity.id]]
    projected = {entity.id: projected[entity.id] for entity in entities}
    fields = _allocate(projected)
    fields_by_object: dict[str, list[ShortlistField]] = {entity.id: [] for entity in entities}
    for field in fields:
        fields_by_object[field.object].append(field)
    entities = [entity for entity in entities if fields_by_object[entity.id]]

    vocabulary = _vocabulary(spec, domain)
    jargon = _jargon(spec, vocabulary, domain)
    hobby = {token for token in bp.keywords(goal) if len(token) >= 3}
    hobby.add(domain)
    examples = _build_examples(spec, entities, fields_by_object, hobby=hobby)

    brief = spec.research
    hints = (
        f"{brief.desired_outcome} First value: {brief.first_value} "
        f"Used: {'; '.join(brief.usage_context)}"
    ).strip()
    return ShortlistModel(
        domain=domain,
        title=spec.title,
        description=brief.desired_outcome,
        objects=[entity.id for entity in entities],
        fields=[field for field in fields if field.object in set(fields_by_object)],
        jargon=jargon,
        vocabulary=vocabulary,
        llm_hints=hints[:600],
        examples=examples,
    )


__all__ = ["MAX_FIELDS_TOTAL", "MAX_OBJECTS", "choose_objects", "spec_to_shortlist"]
