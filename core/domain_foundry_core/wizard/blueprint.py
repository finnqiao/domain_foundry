"""Proposal generator: goal statement → provisional pack blueprint.

The blueprint is a plain (JSON-serializable) dict so wizard sessions persist
trivially. `build_blueprint` picks a rich archetype when the goal matches a
known passion, otherwise falls back to a generic activity-log builder that
still produces a pack which routes its own examples.

Everything the generator emits obeys the pack authoring style guide
(`docs/PACK_AUTHORING.md`): snake_case fields, explicit units, enums biased to
``allow_other``, and events-vs-regimens separation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

# Words that never help name a domain / never belong in routing keywords.
_STOPWORDS = {
    "a", "an", "the", "my", "our", "your", "his", "her", "their", "of", "for",
    "to", "in", "on", "and", "or", "with", "about", "want", "wanna", "like",
    "would", "i", "we", "im", "i'm", "keep", "track", "tracking", "tracker",
    "log", "logging", "logs", "journal", "journaling", "record", "recording",
    "note", "notes", "app", "manage", "managing", "monitor", "monitoring",
    "day", "daily", "weekly", "help", "me", "please", "some", "how", "when",
    "journey", "progress", "history", "over", "time", "each", "every", "this",
    "that", "new", "build", "create", "make", "started", "starting", "start",
}

# Safe negative examples — dev/admin chatter that must not match any pack rule.
_NEGATIVE_POOL = [
    "deploy the release candidate tonight",
    "please review the pull request",
    "the cloud invoice is overdue",
    "schedule a standup meeting",
    "rotate the api credentials",
    "the ci pipeline turned red",
]

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, *, fallback: str = "journal") -> str:
    slug = _SLUG_RE.sub("_", (text or "").strip().lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    if not slug or not slug[0].isalpha():
        slug = f"d_{slug}" if slug else fallback
    slug = slug[:40].rstrip("_")
    if len(slug) < 2:
        slug = fallback
    return slug


def keywords(goal: str) -> list[str]:
    raw = re.findall(r"[a-zA-Z][a-zA-Z0-9']*", (goal or "").lower())
    out: list[str] = []
    for w in raw:
        if w in _STOPWORDS or len(w) < 3:
            continue
        if w not in out:
            out.append(w)
    return out


# --------------------------------------------------------------------------- #
# Archetype library. Each archetype is a spec dict consumed by _blueprint_from
# to produce a full blueprint. Examples deliberately keep object vocabularies
# disjoint so each example routes to exactly one object.
# --------------------------------------------------------------------------- #

_ARCHETYPES: list[dict[str, Any]] = [
    {
        "keys": ["sourdough", "bread", "baking", "bake", "loaf", "levain"],
        "domain": "sourdough",
        "title": "Sourdough Journey",
        "description": "Track starters, bakes, and what each loaf teaches you.",
        "interpretation": "structured",
        "icon": "🍞",
        "objects": {
            "bake": {
                "title_field": "loaf_name",
                "fields": {
                    "loaf_name": {"type": "text", "required": True},
                    "baked_at": {"type": "datetime", "required": True, "default": "capture_time"},
                    "flour_mix": {"type": "text"},
                    "hydration": {"type": "number", "unit": "percent", "min": 40, "max": 120},
                    "bulk_hours": {"type": "number", "unit": "hours"},
                    "result": {"type": "enum", "values": ["dense", "decent", "good", "great"], "allow_other": True},
                    "notes": {"type": "text", "long": True},
                },
                "operations": ["create", "update", "correct", "delete"],
            },
            "starter": {
                "title_field": "name",
                "fields": {
                    "name": {"type": "text", "required": True},
                    "status": {"type": "enum", "values": ["active", "dormant", "retired"], "allow_other": True},
                    "notes": {"type": "text", "long": True},
                },
                "operations": ["create", "update", "correct", "delete"],
            },
        },
        "rules": [
            {"match": r"(bak(?:e|ed|ing)|loaf|boule|batard|crumb|hydration|oven\s*spring|proof)", "object": "bake", "confidence_boost": 0.1},
            {"match": r"(starter|levain|\bfed\b|feed(?:ing)?)", "object": "starter", "confidence_boost": 0.12},
        ],
        "examples": [
            ("baked a country loaf at 75% hydration", "bake"),
            ("80% hydration batard with an open crumb", "bake"),
            ("great oven spring on today's boule", "bake"),
            ("proofed the dough overnight then baked", "bake"),
            ("sourdough loaf came out dense", "bake"),
            ("baked a rye loaf this morning", "bake"),
            ("hydration was 72 on this bake", "bake"),
            ("crumb was airy and glossy", "bake"),
            ("fed the rye starter", "starter"),
            ("levain doubled in four hours", "starter"),
            ("feeding the starter before bed", "starter"),
            ("starter smells pleasantly sour", "starter"),
        ],
        "hints": "Hydration is baker's percentage. Feeding/levain activity is the starter, not a bake.",
        "unit_options": {"hydration": ["percent", "grams"]},
    },
    {
        "keys": ["run", "running", "ran", "jog", "jogging", "marathon", "5k", "10k"],
        "domain": "running",
        "title": "Running Log",
        "description": "Log runs with distance, effort, and how they felt.",
        "interpretation": "simple",
        "icon": "🏃",
        "objects": {
            "run": {
                "title_field": "title",
                "fields": {
                    "title": {"type": "text", "required": True},
                    "ran_at": {"type": "datetime", "required": True, "default": "capture_time"},
                    "distance_km": {"type": "number", "unit": "km", "min": 0, "max": 500},
                    "duration_min": {"type": "number", "unit": "minutes"},
                    "effort": {"type": "enum", "values": ["easy", "steady", "hard", "race"], "allow_other": True},
                    "notes": {"type": "text", "long": True},
                },
                "operations": ["create", "update", "correct", "delete"],
            }
        },
        "rules": [
            {"match": r"(ran\b|run(?:ning)?\b|jog(?:ged|ging)?|marathon|\d+\s*k\b|miles?\b|tempo|treadmill|interval)", "object": "run", "confidence_boost": 0.1},
        ],
        "examples": [
            ("ran 5k this morning", "run"),
            ("easy run of 8km", "run"),
            ("long run today, 21km", "run"),
            ("tempo run at the track", "run"),
            ("jogged around the park", "run"),
            ("ran a 10k race", "run"),
            ("treadmill run for 30 minutes", "run"),
            ("morning run felt great", "run"),
            ("did an interval run", "run"),
            ("ran 3 miles after work", "run"),
            ("recovery run, legs tired", "run"),
            ("half marathon training run", "run"),
        ],
        "hints": "Distances default to kilometres. A 'race' effort implies a hard event.",
        "unit_options": {"distance_km": ["km", "miles"]},
    },
    {
        "keys": ["read", "reading", "book", "books", "novel", "reader"],
        "domain": "reading",
        "title": "Reading Log",
        "description": "Track books, chapters, and reactions as you read.",
        "interpretation": "simple",
        "icon": "📚",
        "objects": {
            "reading_log": {
                "title_field": "title",
                "fields": {
                    "title": {"type": "text", "required": True},
                    "logged_at": {"type": "datetime", "required": True, "default": "capture_time"},
                    "pages": {"type": "integer", "unit": "pages"},
                    "status": {"type": "enum", "values": ["reading", "finished", "abandoned"], "allow_other": True},
                    "rating": {"type": "enum", "values": ["meh", "good", "great"], "allow_other": True},
                    "notes": {"type": "text", "long": True},
                },
                "operations": ["create", "update", "correct", "delete"],
            }
        },
        "rules": [
            {"match": r"(read(?:ing)?\b|book\b|novel|chapter|\bpages?\b|audiobook|kindle|reread|memoir)", "object": "reading_log", "confidence_boost": 0.1},
        ],
        "examples": [
            ("reading a new sci-fi novel", "reading_log"),
            ("finished the book last night", "reading_log"),
            ("read two chapters today", "reading_log"),
            ("started a new book", "reading_log"),
            ("50 pages into the memoir", "reading_log"),
            ("listening to an audiobook on my commute", "reading_log"),
            ("reread an old favorite", "reading_log"),
            ("book club pick this month", "reading_log"),
            ("reading before bed", "reading_log"),
            ("halfway through the novel", "reading_log"),
            ("finished chapter twelve", "reading_log"),
            ("picked up a fantasy book", "reading_log"),
        ],
        "hints": "A reading_log entry is one reading session or status update, not the book itself.",
        "unit_options": {},
    },
    {
        "keys": ["coffee", "espresso", "brew", "brewing", "pourover", "cafe", "beans"],
        "domain": "coffee",
        "title": "Coffee Brews",
        "description": "Dial in brews: method, beans, and how the cup tasted.",
        "interpretation": "simple",
        "icon": "☕",
        "objects": {
            "brew": {
                "title_field": "title",
                "fields": {
                    "title": {"type": "text", "required": True},
                    "brewed_at": {"type": "datetime", "required": True, "default": "capture_time"},
                    "method": {"type": "enum", "values": ["espresso", "pourover", "aeropress", "cold_brew", "french_press"], "allow_other": True},
                    "dose_g": {"type": "number", "unit": "grams"},
                    "rating": {"type": "enum", "values": ["off", "ok", "good", "excellent"], "allow_other": True},
                    "notes": {"type": "text", "long": True},
                },
                "operations": ["create", "update", "correct", "delete"],
            }
        },
        "rules": [
            {"match": r"(coffee|espresso|latte|pour\s*over|brew(?:ed|ing)?|cappuccino|americano|\bbeans?\b|grind|v60|aeropress|cold\s*brew)", "object": "brew", "confidence_boost": 0.1},
        ],
        "examples": [
            ("pulled a great espresso shot", "brew"),
            ("brewed a pourover this morning", "brew"),
            ("tried new single origin beans", "brew"),
            ("made a latte with oat milk", "brew"),
            ("cold brew steeping overnight", "brew"),
            ("dialed in the grind for espresso", "brew"),
            ("aeropress recipe today", "brew"),
            ("v60 brew with a light roast", "brew"),
            ("cappuccino at the local cafe", "brew"),
            ("americano to start the day", "brew"),
            ("ground fresh beans for coffee", "brew"),
            ("brewed coffee tasted fruity", "brew"),
        ],
        "hints": "Each brew is one cup or shot. Dose is in grams of dry coffee.",
        "unit_options": {},
    },
    {
        "keys": ["workout", "gym", "lift", "lifting", "exercise", "fitness", "training", "strength"],
        "domain": "workouts",
        "title": "Workout Log",
        "description": "Log training sessions, movements, and effort.",
        "interpretation": "simple",
        "icon": "🏋️",
        "objects": {
            "workout": {
                "title_field": "title",
                "fields": {
                    "title": {"type": "text", "required": True},
                    "trained_at": {"type": "datetime", "required": True, "default": "capture_time"},
                    "focus": {"type": "text"},
                    "effort": {"type": "enum", "values": ["light", "moderate", "hard", "max"], "allow_other": True},
                    "notes": {"type": "text", "long": True},
                },
                "operations": ["create", "update", "correct", "delete"],
            }
        },
        "rules": [
            {"match": r"(workout|\bgym\b|lift(?:ed|ing)?|bench|squat|deadlift|dumbbell|\breps?\b|\bsets?\b|exercise|cardio|trained)", "object": "workout", "confidence_boost": 0.1},
        ],
        "examples": [
            ("leg day at the gym", "workout"),
            ("benched three sets of five", "workout"),
            ("did squats and deadlifts", "workout"),
            ("morning workout done", "workout"),
            ("upper body lifting session", "workout"),
            ("hit a new deadlift number", "workout"),
            ("dumbbell rows felt strong", "workout"),
            ("cardio and core workout", "workout"),
            ("trained shoulders today", "workout"),
            ("quick gym session after work", "workout"),
            ("full body workout this evening", "workout"),
            ("added extra reps on the bench", "workout"),
        ],
        "hints": "A workout is one training session; effort captures perceived intensity.",
        "unit_options": {},
    },
]


def find_archetype(goal: str) -> dict[str, Any] | None:
    low = (goal or "").lower()
    best: tuple[int, dict[str, Any]] | None = None
    for arch in _ARCHETYPES:
        score = sum(1 for k in arch["keys"] if re.search(rf"\b{re.escape(k)}\b", low))
        if score and (best is None or score > best[0]):
            best = (score, arch)
    return best[1] if best else None


def _generic_spec(goal: str) -> dict[str, Any]:
    kws = keywords(goal)
    subject = kws[0] if kws else "journal"
    domain = slugify(subject)
    # Build routing keywords from the top goal words (+ light plural handling).
    kw_terms: list[str] = []
    for w in kws[:4]:
        kw_terms.append(re.escape(w))
        if not w.endswith("s"):
            kw_terms.append(re.escape(w) + "s")
    if not kw_terms:
        kw_terms = ["log", "logged", "entry"]
    rule_match = "(" + "|".join(dict.fromkeys(kw_terms)) + r"|\blog\b|\bentry\b)"

    title_kw = subject.capitalize()
    examples = [
        (f"logged {subject} today", "entry"),
        (f"{subject} went really well", "entry"),
        (f"made progress on {subject}", "entry"),
        (f"notes on today's {subject}", "entry"),
        (f"tracking {subject} this week", "entry"),
        (f"another {subject} entry", "entry"),
        (f"{subject} update for the record", "entry"),
        (f"recorded a {subject} session", "entry"),
        (f"quick {subject} note", "entry"),
        (f"{subject} milestone reached", "entry"),
        (f"reflecting on {subject}", "entry"),
        (f"{subject} log entry", "entry"),
    ]
    return {
        "keys": [],
        "domain": domain,
        "title": f"{title_kw} Log",
        "description": f"Track your {subject} over time.",
        "interpretation": "simple",
        "icon": "🗒️",
        "objects": {
            "entry": {
                "title_field": "title",
                "fields": {
                    "title": {"type": "text", "required": True},
                    "logged_at": {"type": "datetime", "required": True, "default": "capture_time"},
                    "rating": {"type": "enum", "values": ["low", "medium", "high"], "allow_other": True},
                    "amount": {"type": "number"},
                    "notes": {"type": "text", "long": True},
                },
                "operations": ["create", "update", "correct", "delete"],
            }
        },
        "rules": [{"match": rule_match, "object": "entry", "confidence_boost": 0.1}],
        "examples": examples,
        "hints": f"Each entry is one {subject} observation or session.",
        "unit_options": {},
    }


def _safe_negatives(spec: dict[str, Any]) -> list[str]:
    compiled = [re.compile(r["match"], re.IGNORECASE) for r in spec["rules"]]
    out: list[str] = []
    for cand in _NEGATIVE_POOL:
        if not any(p.search(cand) for p in compiled):
            out.append(cand)
        if len(out) >= 3:
            break
    while len(out) < 2:
        out.append(f"unrelated administrative chatter number {len(out) + 1}")
    return out


def _interview_questions(spec: dict[str, Any]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for field, options in (spec.get("unit_options") or {}).items():
        if len(options) >= 2:
            questions.append({
                "id": f"unit_{field}",
                "prompt": f"What unit should '{field}' use?",
                "kind": "choice",
                "options": options,
                "applies_to": f"unit:{field}",
                "default": options[0],
            })
    questions.append({
        "id": "cadence",
        "prompt": "Do you log this per event, or a daily summary?",
        "kind": "choice",
        "options": ["per_event", "daily"],
        "applies_to": "cadence",
        "default": "per_event",
    })
    questions.append({
        "id": "view",
        "prompt": "Do you care more about browsing a timeline or searching entries?",
        "kind": "choice",
        "options": ["timeline", "search"],
        "applies_to": "view",
        "default": "timeline",
    })
    questions.append({
        "id": "privacy",
        "prompt": "Should new entries wait for your confirmation before saving?",
        "kind": "yesno",
        "options": ["no", "yes"],
        "applies_to": "privacy",
        "default": "no",
    })
    return questions[:6]


def _default_views(spec: dict[str, Any]) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    for obj_name, obj in spec["objects"].items():
        date_field = next(
            (f for f, fs in obj["fields"].items() if fs.get("type") == "datetime"),
            None,
        )
        block = "timeline" if date_field else "list"
        config: dict[str, Any] = {}
        if date_field:
            config["date_field"] = date_field
        views.append({
            "id": obj_name + "s",
            "title": obj_name.replace("_", " ").title(),
            "block": block,
            "object": obj_name,
            "config": config,
        })
    return views


def build_agent_spec(blueprint: dict[str, Any]) -> dict[str, Any]:
    """Build an ``AgentSpec``-compatible dict for a pack blueprint.

    Emits persona/tools/autonomy plus empty sessions/schedules stubs so every
    wizard-created domain is mesh-ready (mesh P4).
    """
    domain = str(blueprint["domain"])
    title = str(blueprint.get("title") or domain)
    description = str(blueprint.get("description") or "").strip()
    persona = (
        f"You are the user's {title} partner. {description} "
        f"You capture and query {domain} data without blocking other domains."
    ).strip()
    return {
        "name": domain,
        "persona": persona,
        "tools": ["capture", "query", "correct"],
        "autonomy": {"capture": "auto"},
        "sessions": [],
        "schedules": [],
    }


def _blueprint_from(spec: dict[str, Any], goal: str) -> dict[str, Any]:
    examples = [
        {"text": t, "object": o, "operation": "create"} for (t, o) in spec["examples"]
    ]
    blueprint = {
        "archetype": spec.get("domain") if spec.get("keys") else "generic",
        "goal": goal,
        "domain": spec["domain"],
        "title": spec["title"],
        "description": spec["description"],
        "interpretation": spec["interpretation"],
        "icon": spec["icon"],
        "markdown_folder": spec["title"].split()[0],
        "objects": spec["objects"],
        "rules": [
            {"match": r["match"], "object": r["object"],
             "confidence_boost": r.get("confidence_boost", 0.1),
             "operation": r.get("operation", "create")}
            for r in spec["rules"]
        ],
        "examples": examples,
        "negatives": _safe_negatives(spec),
        "llm_hints": spec.get("hints", ""),
        "views": _default_views(spec),
        "unit_options": spec.get("unit_options") or {},
        "questions": _interview_questions(spec),
        "policy": {
            "defaults": [
                {"operation": "create", "min_confidence": 0.8, "action": "auto_apply"},
                {"operation": "update", "min_confidence": 0.85, "action": "auto_apply"},
                {"operation": "correct", "action": "auto_apply"},
                {"operation": "delete", "action": "review"},
            ],
            "fallback": "unfiled_card",
        },
    }
    blueprint["agent"] = build_agent_spec(blueprint)
    return blueprint


def build_blueprint(goal: str) -> dict[str, Any]:
    """Return a provisional pack blueprint (JSON-serializable) for a goal."""
    spec = find_archetype(goal) or _generic_spec(goal)
    return _blueprint_from(spec, goal)


def apply_answer(blueprint: dict[str, Any], answers: dict[str, str]) -> dict[str, Any]:
    """Apply parsed interview answers to a blueprint (units, views, privacy)."""
    for key, value in answers.items():
        value = (value or "").strip().lower()
        if key.startswith("unit:"):
            field = key.split(":", 1)[1]
            for obj in blueprint["objects"].values():
                if field in obj["fields"]:
                    obj["fields"][field]["unit"] = value
        elif key == "view" and value == "search":
            for view in blueprint["views"]:
                view["block"] = "search" if view["block"] == "timeline" else view["block"]
        elif key == "privacy" and value in {"yes", "y", "true", "private"}:
            for row in blueprint["policy"]["defaults"]:
                if row.get("operation") == "create":
                    row["action"] = "confirm"
        elif key == "cadence":
            blueprint.setdefault("meta", {})["cadence"] = value
    return blueprint


def parse_answers(text: str, questions: list[dict[str, Any]]) -> dict[str, str]:
    """Map a free-form / key=value reply onto interview answer keys.

    Interview is optional (the promise is a working app from ordinary language,
    not a form): unrecognised or empty replies keep defaults.
    """
    text = (text or "").strip()
    answers: dict[str, str] = {}
    low = text.lower()
    if low in {"", "skip", "defaults", "default", "use defaults", "next", "go"}:
        return answers

    # Explicit key=value pairs win.
    for m in re.finditer(r"([a-z_:]+)\s*=\s*([a-z0-9_]+)", low):
        answers[m.group(1)] = m.group(2)

    for q in questions:
        applies = q["applies_to"]
        if applies in answers or q["id"] in answers:
            if q["id"] in answers and applies not in answers:
                answers[applies] = answers.pop(q["id"])
            continue
        for opt in q.get("options") or []:
            if re.search(rf"\b{re.escape(opt)}\b", low):
                answers[applies] = opt
                break
    if re.search(r"\b(private|confirm|ask me first|require confirmation)\b", low):
        answers["privacy"] = "yes"
    return answers


# --------------------------------------------------------------------------- #
# Rendering: blueprint dict → pack file dicts → on-disk YAML directory.
# --------------------------------------------------------------------------- #

_CORE_COMPAT = ">=0.1,<2"


def render_files(blueprint: dict[str, Any], *, version: str = "0.1.0") -> dict[str, Any]:
    """Return pack YAML files (incl. ``agent.yaml``) as YAML-ready dicts."""
    objects = blueprint["objects"]
    pack_yaml = {
        "name": blueprint["domain"],
        "version": version,
        "title": blueprint["title"],
        "description": blueprint["description"],
        "author": "domain_foundry wizard",
        "license": "MIT",
        "core_compat": _CORE_COMPAT,
        "interpretation": blueprint["interpretation"],
        "aliases": [],
    }
    schema_yaml = {
        "objects": {
            name: {
                "title_field": obj["title_field"],
                "fields": obj["fields"],
            }
            for name, obj in objects.items()
        }
    }
    routing_yaml = {
        "rules": [
            {"match": r["match"], "object": r["object"], "confidence_boost": r["confidence_boost"]}
            for r in blueprint["rules"]
        ],
        "examples": [
            {
                "text": ex["text"],
                "expect": _example_expect(ex),
            }
            for ex in blueprint["examples"]
        ],
        "negative_examples": [{"text": t} for t in blueprint["negatives"]],
        "llm_hints": blueprint["llm_hints"],
    }
    operations_yaml = {name: obj["operations"] for name, obj in objects.items()}
    policy_yaml = {
        "defaults": blueprint["policy"]["defaults"],
        "fallback": blueprint["policy"]["fallback"],
    }
    projections_yaml = {
        "app": {"icon": blueprint["icon"], "views": blueprint["views"]},
        "markdown": {"folder": blueprint["markdown_folder"], "note_template": None},
    }
    agent = blueprint.get("agent") or build_agent_spec(blueprint)
    # Keep name aligned if the wizard renamed the domain for uniqueness.
    agent = {**agent, "name": blueprint["domain"]}
    return {
        "pack.yaml": pack_yaml,
        "schema.yaml": schema_yaml,
        "routing.yaml": routing_yaml,
        "operations.yaml": operations_yaml,
        "policy.yaml": policy_yaml,
        "projections.yaml": projections_yaml,
        "agent.yaml": {"agent": agent},
    }


def _example_expect(ex: dict[str, Any]) -> dict[str, Any]:
    expect: dict[str, Any] = {"object": ex["object"], "operation": ex.get("operation", "create")}
    if ex.get("fields"):
        expect["fields"] = ex["fields"]
    return expect


def write_pack(blueprint: dict[str, Any], dest: Path, *, version: str = "0.1.0") -> Path:
    """Write blueprint pack files into ``dest`` and return the directory."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    files = render_files(blueprint, version=version)
    for filename, content in files.items():
        (dest / filename).write_text(
            yaml.safe_dump(content, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    return dest
