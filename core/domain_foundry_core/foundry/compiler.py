"""Compile one FoundrySpec into an owned, evidence-backed application bundle."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from domain_foundry_core.clock import now_iso

from .loader import DEFAULT_PRINCIPLES, DEFAULT_REGISTRY
from .models import (
    BESPOKE_ALLOWED_PROPERTIES,
    BESPOKE_CSS_BUDGET_BYTES,
    BESPOKE_FORBIDDEN_SUBSTRINGS,
    DENSITY_SCALE_LABELS,
    SIGNATURE_ELEMENT_LABELS,
    TYPOGRAPHY_STACK_LABELS,
    EntitySpec,
    FoundrySpec,
    RelationshipSpec,
)

_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_SQL_TYPES = {
    "text": "TEXT",
    "integer": "INTEGER",
    "number": "REAL",
    "boolean": "INTEGER",
    "date": "TEXT",
    "datetime": "TEXT",
    "duration": "REAL",
    "enum": "TEXT",
    "attachment": "TEXT",
    "location": "TEXT",
    "json": "TEXT",
}
_ON_DELETE = {
    "restrict": "RESTRICT",
    "cascade": "CASCADE",
    "set_null": "SET NULL",
    "archive": "RESTRICT",
}
COMPILER_VERSION = "domain-foundry-core/foundry-spec-1.1"
DEFAULT_RUNTIME = Path(__file__).with_name("runtime.js")


@dataclass(frozen=True)
class BuildArtifact:
    root: Path
    app: Path
    schema: Path
    spec: Path
    evidence: Path
    receipt: Path


class FoundryCompiler:
    """Deep module: validated spec in, complete owned bundle out."""

    def compile(
        self,
        spec: FoundrySpec,
        destination: Path,
        *,
        generated_at: str | None = None,
    ) -> BuildArtifact:
        destination = destination.resolve()
        if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
            raise FileExistsError(f"refusing to overwrite existing destination: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent)
        )

        try:
            generated_at = generated_at or now_iso()
            spec_json = spec.model_dump_json(indent=2)
            evidence_json = json.dumps(self.knowledge_snapshot(spec), indent=2, ensure_ascii=False)
            files = {
                "foundry-spec.json": spec_json + "\n",
                "schema.sql": self.compile_ddl(spec),
                "app.html": self.render_app(spec),
                "evidence.json": evidence_json + "\n",
                "README.md": self.render_readme(spec),
            }
            for name, content in files.items():
                (staging / name).write_text(content, encoding="utf-8")

            hashes = {
                name: hashlib.sha256(content.encode("utf-8")).hexdigest()
                for name, content in files.items()
            }
            receipt_payload = {
                "spec_id": spec.id,
                "spec_version": spec.spec_version,
                "generated_at": generated_at,
                "compiler": COMPILER_VERSION,
                "artifacts": hashes,
                "sources": spec.source_ids,
                "principles": spec.principle_ids,
                "generation": spec.generation.model_dump(mode="json") if spec.generation else None,
                # Lifted out of the nested receipt so pack metadata and UI copy
                # can read the tier without knowing the receipt's shape.
                "evidence_tier": spec.evidence_tier,
                "evidence_label": spec.evidence_tier_label,
                # What the build actually rendered, and where each choice came
                # from. A dropped bespoke layer is recorded here, never silent.
                "experience": self.experience_plan(spec).for_receipt(),
            }
            (staging / "build-receipt.json").write_text(
                json.dumps(receipt_payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            if destination.exists():
                destination.rmdir()
            os.replace(staging, destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        receipt = destination / "build-receipt.json"
        return BuildArtifact(
            root=destination,
            app=destination / "app.html",
            schema=destination / "schema.sql",
            spec=destination / "foundry-spec.json",
            evidence=destination / "evidence.json",
            receipt=receipt,
        )

    def knowledge_snapshot(self, spec: FoundrySpec) -> dict[str, Any]:
        registry = yaml.safe_load(DEFAULT_REGISTRY.read_text(encoding="utf-8")) or {}
        sources = [
            source
            for source in registry.get("sources", [])
            if source.get("id") in set(spec.source_ids)
        ]
        registered_ids = {str(source.get("id")) for source in sources}
        sources.extend(
            source.model_dump(mode="json")
            for source in spec.source_snapshots
            if source.id not in registered_ids
        )
        wanted_principles = set(spec.principle_ids)
        principles: list[dict[str, Any]] = []
        for path in sorted(DEFAULT_PRINCIPLES.glob("*.yaml")):
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            principles.extend(
                item
                for item in document.get("principles", [])
                if item.get("id") in wanted_principles
            )
        return {
            "snapshot_version": 1,
            "spec_id": spec.id,
            "sources": sources,
            "principles": principles,
            "citations": [item.model_dump(mode="json") for item in spec.evidence],
            "derivations": [item.model_dump(mode="json") for item in spec.derivations],
        }

    def compile_ddl(self, spec: FoundrySpec) -> str:
        prefix = self._sql_ident(spec.id.replace("-", "_"))
        entity_by_id = {entity.id: entity for entity in spec.domain.entities}
        inline_relationships: dict[str, list[RelationshipSpec]] = {}
        association_relationships: list[RelationshipSpec] = []
        for relationship in spec.domain.relationships:
            if relationship.cardinality in {"many_to_one", "one_to_one"}:
                inline_relationships.setdefault(relationship.from_entity, []).append(relationship)
            else:
                association_relationships.append(relationship)

        lines = [
            "-- generated from FoundrySpec 1.0; do not edit in place",
            "PRAGMA foreign_keys = ON;",
            "PRAGMA journal_mode = WAL;",
            "",
        ]
        for entity in spec.domain.entities:
            table = self._table(prefix, entity.id)
            columns = [
                "row_id INTEGER PRIMARY KEY AUTOINCREMENT",
                "object_uid TEXT NOT NULL UNIQUE",
                "captured_at TEXT NOT NULL",
                "updated_at TEXT NOT NULL",
                "tombstoned INTEGER NOT NULL DEFAULT 0 CHECK (tombstoned IN (0, 1))",
            ]
            for field in entity.fields:
                name = self._sql_ident(field.name)
                sql_type = _SQL_TYPES[field.type]
                required = " NOT NULL" if field.required else ""
                checks: list[str] = []
                if field.type == "boolean":
                    checks.append(f"{name} IN (0, 1)")
                if field.type == "enum" and field.values:
                    values = ", ".join(self._sql_literal(value) for value in field.values)
                    checks.append(f"{name} IN ({values})")
                if field.type == "json":
                    json_check = f"json_valid({name})"
                    checks.append(
                        json_check if field.required else f"{name} IS NULL OR {json_check}"
                    )
                suffix = f" CHECK ({' AND '.join(checks)})" if checks else ""
                columns.append(f"{name} {sql_type}{required}{suffix}")

            identity = ", ".join(self._sql_ident(name) for name in entity.identity)
            columns.append(f"CONSTRAINT uq_{entity.id}_identity UNIQUE ({identity})")
            for constraint in spec.domain.constraints:
                if constraint.entity != entity.id:
                    continue
                cname = self._sql_ident(constraint.id)
                fields = ", ".join(self._sql_ident(name) for name in constraint.fields)
                if constraint.kind == "unique":
                    columns.append(f"CONSTRAINT {cname} UNIQUE ({fields})")
                elif constraint.kind == "check" and constraint.expression:
                    columns.append(
                        f"CONSTRAINT {cname} CHECK ({self._safe_check(constraint.expression, entity)})"
                    )

            for relationship in inline_relationships.get(entity.id, []):
                target = entity_by_id[relationship.to_entity]
                local_field = self._relationship_field(entity, target)
                target_field = self._sql_ident(target.identity[0])
                target_table = self._table(prefix, target.id)
                columns.append(
                    f"CONSTRAINT {self._sql_ident(relationship.id)} "
                    f"FOREIGN KEY ({local_field}) REFERENCES {target_table}({target_field}) "
                    f"ON DELETE {_ON_DELETE[relationship.on_delete]}"
                )

            lines.append(f"CREATE TABLE IF NOT EXISTS {table} (")
            lines.append("    " + ",\n    ".join(columns))
            lines.append(");")
            lines.append(
                f"CREATE INDEX IF NOT EXISTS ix_{table}_captured_at ON {table}(captured_at);"
            )
            lines.append("")

        for relationship in association_relationships:
            from_table = self._table(prefix, relationship.from_entity)
            to_table = self._table(prefix, relationship.to_entity)
            join_table = self._table(prefix, f"rel_{relationship.id}")
            lines.extend(
                [
                    f"CREATE TABLE IF NOT EXISTS {join_table} (",
                    "    from_uid TEXT NOT NULL,",
                    "    to_uid TEXT NOT NULL,",
                    "    captured_at TEXT NOT NULL,",
                    "    provenance_json TEXT NOT NULL CHECK (json_valid(provenance_json)),",
                    f"    FOREIGN KEY (from_uid) REFERENCES {from_table}(object_uid) ON DELETE RESTRICT,",
                    f"    FOREIGN KEY (to_uid) REFERENCES {to_table}(object_uid) ON DELETE RESTRICT,",
                    "    PRIMARY KEY (from_uid, to_uid)",
                    ");",
                    "",
                ]
            )

        for index in spec.domain.indexes:
            table = self._table(prefix, index.entity)
            fields = ", ".join(self._sql_ident(name) for name in index.fields)
            unique = "UNIQUE " if index.unique else ""
            lines.append(
                f"CREATE {unique}INDEX IF NOT EXISTS {self._sql_ident(index.id)} "
                f"ON {table}({fields});"
            )
        lines.append("")
        return "\n".join(lines)

    def render_app(self, spec: FoundrySpec) -> str:
        plan = self.experience_plan(spec)
        app_payload = spec.model_dump(mode="json")
        app_payload["_source_records"] = self.knowledge_snapshot(spec)["sources"]
        app_payload["_render"] = plan.for_runtime()
        payload = json.dumps(app_payload, ensure_ascii=False).replace("</", "<\\/")
        runtime = DEFAULT_RUNTIME.read_text(encoding="utf-8").replace("</", "<\\/")
        document = _DOCUMENT_HEAD + self.render_stylesheet(spec, plan) + _DOCUMENT_TAIL
        body_attrs = (
            f'data-world="{_html_text(spec.experience.visual_world.id)}" '
            f'data-topology="{plan.topology}" data-density="{plan.density_scale}" '
            f'data-type-stack="{plan.typography_stack}"'
        )
        return (
            document.replace("__TITLE__", _html_text(spec.title))
            .replace("__BODY_ATTRS__", body_attrs)
            .replace("__SPEC_JSON__", payload)
            .replace("__RUNTIME_JS__", runtime)
        )

    def experience_plan(self, spec: FoundrySpec) -> ExperiencePlan:
        """Resolve the spec's experience fields into things the build renders.

        Where the spec names a value, that value is used. Where it only
        describes one in prose, the prose is mapped onto the named set and the
        mapping is written into the build receipt, so nobody has to guess which
        it was.
        """
        return _resolve_experience(spec)

    def render_stylesheet(self, spec: FoundrySpec, plan: ExperiencePlan | None = None) -> str:
        """Compose the app's CSS from the parts this build actually needs."""
        plan = plan or self.experience_plan(spec)
        parts = [
            _RESET_CSS,
            _token_block(plan),
            _BASE_SHELL_CSS,
            _DENSITY_CSS[plan.density_scale],
            _TOPOLOGY_CSS[plan.topology],
        ]
        if plan.signature_elements:
            parts.append(_SIGNATURE_FRAME_CSS)
            parts.extend(_SIGNATURE_CSS[name] for name in plan.signature_elements)
        parts.append(_RESPONSIVE_CSS)
        parts.append(_TOPOLOGY_NARROW_CSS[plan.topology])
        if plan.signature_elements:
            parts.append(_SIGNATURE_NARROW_CSS)
        parts.append(_RESPONSIVE_CLOSE)
        parts.append(_MOTION_CSS)
        if plan.bespoke_css:
            parts.append(plan.bespoke_css)
        return "".join(parts)

    def render_readme(self, spec: FoundrySpec) -> str:
        parent = spec.remix.parent_spec
        parentage = f"\n            Forked from {parent}.\n" if parent else ""
        return textwrap.dedent(
            f"""\
            # {spec.title}

            This application was compiled from `foundry-spec.json`. Its preview
            and final local application are the same `app.html` artifact.
{parentage}
            Research for this build is **{spec.evidence_tier_label}**.

            ## Open

            Open `app.html` directly in a modern browser. New records, immutable
            prior versions, and receipts are stored in browser local storage.
            **Export data** creates a complete JSON backup; **Restore backup**
            validates the spec identity before replacing local state.

            ## Data model

            `schema.sql` is SQLite DDL with identities, constraints, foreign
            keys, relationship tables, and workload-derived indexes. Apply it
            to a new database with foreign keys enabled.

            ## Ownership

            - `foundry-spec.json` — complete product and derivation contract
            - `evidence.json` — frozen source, principle, citation, and derivation snapshot
            - `build-receipt.json` — artifact hashes and compiler identity
            - `schema.sql` — executable local data model
            - `app.html` — self-contained local application, correction history,
              and validated JSON export/restore

            Generated output is MIT-licensed with Domain Foundry unless an
            evidence or dependency record states otherwise. Reference-only
            sources informed facts and patterns; their code and imagery are not
            copied into this bundle.
            """
        )

    @staticmethod
    def _relationship_field(entity: EntitySpec, target: EntitySpec) -> str:
        fields = {field.name for field in entity.fields}
        candidates = [f"{target.id}_id", target.identity[0]]
        for candidate in candidates:
            if candidate in fields:
                return FoundryCompiler._sql_ident(candidate)
        raise ValueError(
            f"relationship from {entity.id} to {target.id} needs a local identity field"
        )

    @staticmethod
    def _safe_check(expression: str, entity: EntitySpec) -> str:
        if any(token in expression for token in (";", "--", "/*", "*/")):
            raise ValueError("unsafe check expression")
        if not re.fullmatch(r"[A-Za-z0-9_ .<>=!()+\-*/'\"]+", expression):
            raise ValueError("unsupported check expression")
        words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression))
        allowed = {field.name for field in entity.fields} | {"AND", "OR", "NOT", "NULL"}
        unknown = {word for word in words if word not in allowed and word.upper() not in allowed}
        if unknown:
            raise ValueError(f"check expression uses unknown identifiers: {sorted(unknown)}")
        return expression

    @staticmethod
    def _sql_ident(value: str) -> str:
        if not _IDENT_RE.fullmatch(value):
            raise ValueError(f"unsafe SQL identifier: {value!r}")
        return value

    @staticmethod
    def _table(prefix: str, entity: str) -> str:
        return FoundryCompiler._sql_ident(f"{prefix}__{entity}")

    @staticmethod
    def _sql_literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# From spec fields to a rendered app (Lane B2 to B6).
#
# The spec writes some of its look as a named value and some of it as a
# sentence. Both reach pixels. Where only a sentence exists, the words below
# map it onto the named set, and the receipt records that it was mapped rather
# than chosen, so nobody reads a guess as a decision.
# ---------------------------------------------------------------------------

_TYPOGRAPHY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("rounded_humanist", ("humanist", "rounded", "friendly", "warm sans", "soft")),
    ("reading_serif", ("serif", "text face", "reading", "literate", "editorial", "book")),
    ("data_sans", ("grotesk", "numeral", "condensed", "tabular", "data", "table", "sans")),
    ("mono_forward", ("monospac", "mono", "terminal", "typewriter", "code")),
)

_DENSITY_HINTS: dict[str, tuple[str, ...]] = {
    "airy": ("spacious", "airy", "generous", "singular", "sparse", "roomy", "one at a time"),
    "bench": ("bench", "working", "balanced", "room to read", "moderate"),
    "dense": ("dense", "packed", "compact", "scan", "many rows", "tight"),
}

_SIGNATURE_HINTS: dict[str, tuple[str, ...]] = {
    "progress_bar": (
        "progress",
        "countdown",
        "remaining",
        "time left",
        "timer",
        "horizon",
        "interval",
        "elapsed",
        "tide",
    ),
    "life_list": (
        "life list",
        "checklist",
        "collected",
        "found",
        "seen",
        "tally",
        "roster",
        "catalog",
        "everything you",
    ),
    "comparison_strip": ("compare", "comparison", "side by side", "versus", "strip", "formula"),
    "timeline_rail": ("timeline", "rail", "trail", "chronolog", "history", "sequence", "curve"),
    "gap_grid": ("grid", "gap", "missing", "slot", "binder", "board", "matrix", "set completion"),
}

_TOKEN_PROPERTIES: dict[str, str] = {
    "background": "--bg",
    "surface": "--surface",
    "text": "--ink",
    "muted": "--muted",
    "accent": "--accent",
    "accent_alt": "--accent-alt",
    "border": "--border",
    "focus": "--focus",
    "danger": "--danger",
}

# The only custom properties a bespoke layer may name.
_BESPOKE_TOKENS = frozenset(
    {
        *_TOKEN_PROPERTIES.values(),
        "--radius",
        "--shadow",
        "--gap",
        "--pad",
        "--row-pad",
        "--font-body",
        "--font-mono",
        "--span",
        "--collapse-order",
        "--tile-span",
        "--tile-rows",
    }
)

_NARROW_WORDS = ("phone", "mobile", "small screen", "narrow", "handheld")
_PAGED_WORDS = ("paged", "swipe", "carousel", "horizontally", "scroll")


@dataclass(frozen=True)
class ExperiencePlan:
    """Everything the build decided about how this app looks and behaves."""

    topology: str
    typography_stack: str
    typography_source: str
    density_scale: str
    density_source: str
    signature_elements: tuple[str, ...]
    signature_source: str
    tokens: dict[str, Any]
    token_overrides: dict[str, str]
    collapse: dict[str, dict[str, Any]]
    keyboard: dict[str, Any]
    look_id: str | None
    bespoke_css: str | None
    bespoke_rejections: tuple[str, ...]

    def for_runtime(self) -> dict[str, Any]:
        """The half the app's own script needs to build its DOM."""
        return {
            "topology": self.topology,
            "typography_stack": self.typography_stack,
            "typography_label": TYPOGRAPHY_STACK_LABELS[self.typography_stack],
            "density_scale": self.density_scale,
            "density_label": DENSITY_SCALE_LABELS[self.density_scale],
            "signature_elements": list(self.signature_elements),
            "signature_labels": [
                SIGNATURE_ELEMENT_LABELS[name] for name in self.signature_elements
            ],
            "collapse": self.collapse,
            "keyboard": self.keyboard,
        }

    def for_receipt(self) -> dict[str, Any]:
        """The half a reader needs to see what was chosen and what was mapped."""
        return {
            "topology": self.topology,
            "typography_stack": self.typography_stack,
            "typography_stack_from": self.typography_source,
            "density_scale": self.density_scale,
            "density_scale_from": self.density_source,
            "signature_elements": list(self.signature_elements),
            "signature_elements_from": self.signature_source,
            "look_id": self.look_id,
            "token_overrides": dict(self.token_overrides),
            "bespoke_layer": "rendered" if self.bespoke_css else "none",
            "bespoke_rejections": list(self.bespoke_rejections),
        }


def _first_hint(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint in text for hint in hints)


def _map_typography(world: Any) -> str:
    text = f"{world.typography} {world.mood}".casefold()
    for name, hints in _TYPOGRAPHY_HINTS:
        if _first_hint(text, hints):
            return name
    return "system_default"


def _map_density(world: Any) -> str:
    text = f"{world.density} {world.layout_principle} {world.mood}".casefold()
    scores = {
        name: sum(text.count(hint) for hint in hints) for name, hints in _DENSITY_HINTS.items()
    }
    best = max(scores.values())
    if best == 0:
        return "bench"
    # Ties break on where the first matching word appears, so the same prose
    # always resolves to the same scale.
    candidates = [name for name, score in scores.items() if score == best]
    if len(candidates) == 1:
        return candidates[0]
    positions = {
        name: min(text.find(hint) for hint in _DENSITY_HINTS[name] if hint in text)
        for name in candidates
    }
    return min(sorted(candidates), key=lambda name: positions[name])


def _map_signature_elements(world: Any) -> tuple[str, ...]:
    text = " ".join(world.signature_elements).casefold()
    chosen = [name for name, hints in _SIGNATURE_HINTS.items() if _first_hint(text, hints)]
    return tuple(sorted(chosen))[:5]


def _collapse_plan(spec: FoundrySpec) -> dict[str, dict[str, Any]]:
    """Turn the spec's responsive sentences into an order regions collapse in.

    The sentence about small screens names the parts that come first. Anything
    it names keeps that order on a narrow screen; anything it does not falls in
    behind, most important part first.
    """
    narrow_lines = [
        line.casefold()
        for line in spec.experience.responsive_strategy
        if _first_hint(line.casefold(), _NARROW_WORDS)
    ]
    # One clause is one instruction. A clause that says something is paged
    # pages the parts that clause names, and nothing else.
    clauses: list[str] = []
    for line in narrow_lines:
        clauses.extend(clause.strip() for clause in re.split(r"[.;]", line) if clause.strip())
    emphasis_rank = {"primary": 0, "secondary": 1, "support": 2}
    plan: dict[str, dict[str, Any]] = {}
    for view in spec.experience.views:
        mentioned: list[tuple[int, int, str]] = []
        unmentioned: list[tuple[int, str]] = []
        paged: set[str] = set()
        for region in view.regions:
            words = [
                word
                for word in (
                    *region.title.casefold().split(),
                    region.kind,
                    *region.id.replace("_", " ").split(),
                )
                if len(word) > 3
            ]
            found = False
            for index, clause in enumerate(clauses):
                hits = [clause.find(word) for word in words if word in clause]
                if not hits:
                    continue
                found = True
                mentioned.append((index, min(hits), region.id))
                if _first_hint(clause, _PAGED_WORDS):
                    paged.add(region.id)
                break
            if not found:
                unmentioned.append((emphasis_rank[region.emphasis], region.id))
        order: list[str] = [region_id for *_, region_id in sorted(mentioned)]
        order.extend(region_id for _, region_id in sorted(unmentioned))
        for index, region_id in enumerate(order):
            plan[f"{view.id}:{region_id}"] = {
                "order": index,
                "paged": region_id in paged,
            }
    return plan


def _keyboard_plan(spec: FoundrySpec) -> dict[str, Any]:
    """Turn the spec's keyboard sentences into keys the app really handles."""
    lines = [line.casefold() for line in spec.experience.accessibility.keyboard_model]
    joined = " ".join(lines)
    if "focus to status" in joined or "focus to the status" in joined:
        focus_after_capture = "status"
    elif "returns focus to the changed" in joined or "focus to the changed value" in joined:
        focus_after_capture = "record"
    else:
        focus_after_capture = "main"
    return {
        "arrow_navigation": "arrow key" in joined or "arrow keys" in joined,
        "escape_returns_to_main": "escape" in joined,
        "space_reveals": "space" in joined and "reveal" in joined,
        "focus_after_capture": focus_after_capture,
        "model": list(spec.experience.accessibility.keyboard_model),
        "patterns": list(spec.experience.accessibility.patterns),
        "manual_checks": list(spec.experience.accessibility.manual_checks),
        "target": spec.experience.accessibility.target,
    }


def _resolve_experience(spec: FoundrySpec) -> ExperiencePlan:
    world = spec.experience.visual_world
    look = spec.look

    topology = spec.experience.navigation.topology
    if look and look.topology:
        topology = look.topology

    if look and look.typography_stack:
        typography, typography_source = look.typography_stack, "chosen on the review page"
    elif world.typography_stack:
        typography, typography_source = world.typography_stack, "named in the spec"
    else:
        typography, typography_source = _map_typography(world), "mapped from the spec's description"

    if look and look.density_scale:
        density, density_source = look.density_scale, "chosen on the review page"
    elif world.density_scale:
        density, density_source = world.density_scale, "named in the spec"
    else:
        density, density_source = _map_density(world), "mapped from the spec's description"

    if look and look.signature_elements:
        signature = tuple(dict.fromkeys(look.signature_elements))
        signature_source = "chosen on the review page"
    elif world.signature_element_ids:
        signature = tuple(dict.fromkeys(world.signature_element_ids))
        signature_source = "named in the spec"
    else:
        signature = _map_signature_elements(world)
        signature_source = "mapped from the spec's description"

    tokens = world.tokens.model_dump(mode="json")
    overrides = dict(look.token_overrides) if look else {}
    for name, value in overrides.items():
        tokens[name] = int(value) if name == "radius_px" else value

    bespoke_layer = (look.bespoke if look and look.bespoke else None) or world.bespoke
    bespoke_css: str | None = None
    rejections: tuple[str, ...] = ()
    if bespoke_layer is not None:
        bespoke_css, problems = sanitize_bespoke_css(bespoke_layer.css)
        rejections = tuple(problems)

    return ExperiencePlan(
        topology=topology,
        typography_stack=typography,
        typography_source=typography_source,
        density_scale=density,
        density_source=density_source,
        signature_elements=signature,
        signature_source=signature_source,
        tokens=tokens,
        token_overrides=overrides,
        collapse=_collapse_plan(spec),
        keyboard=_keyboard_plan(spec),
        look_id=look.look_id if look else None,
        bespoke_css=bespoke_css,
        bespoke_rejections=rejections,
    )


_BESPOKE_SELECTOR_RE = re.compile(r"^[a-z0-9 .\-_\[\]=\"']+$")
_BESPOKE_VALUE_RE = re.compile(r"^[A-Za-z0-9 .,%#()\-_/+*'\"]+$")
_BESPOKE_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_BESPOKE_COLOUR_RE = re.compile(r"#[0-9A-Fa-f]{3,8}\b|\b(?:rgba?|hsla?|color|color-mix)\(")
_BESPOKE_FONT_SIZE_RE = re.compile(
    r"var\(--[a-z0-9\-]+\)|(?:0?\.[5-9][0-9]*|[12](?:\.[0-9]+)?|3)(?:rem|em)|(?:[5-9][0-9]|1[0-9]{2})%"
)


def sanitize_bespoke_css(css: str) -> tuple[str | None, list[str]]:
    """Check a per-app CSS layer against the envelope, all or nothing.

    Anything outside the envelope drops the whole layer. The app is still
    built, and the reasons are written into the build receipt.
    """
    problems: list[str] = []
    if len(css.encode("utf-8")) > BESPOKE_CSS_BUDGET_BYTES:
        problems.append(f"the layer is over the {BESPOKE_CSS_BUDGET_BYTES} byte budget")
    lowered = css.casefold()
    for banned in BESPOKE_FORBIDDEN_SUBSTRINGS:
        if banned in lowered:
            problems.append(f"the layer uses {banned}, which is never allowed")
    if "@" in css:
        problems.append("the layer uses an at-rule, and only plain rules are allowed")
    if "/*" in css or "*/" in css:
        problems.append("the layer uses a comment, and only plain rules are allowed")

    blocks = _BESPOKE_RULE_RE.findall(css)
    if not blocks:
        problems.append("the layer has no complete rule to render")
    if _BESPOKE_RULE_RE.sub("", css).strip():
        problems.append("the layer has text outside a rule")

    rules: list[str] = []
    for raw_selector, body in blocks:
        selector = " ".join(raw_selector.split())
        if (
            "#" in selector
            or "*" in selector
            or not _BESPOKE_SELECTOR_RE.match(selector.casefold())
        ):
            problems.append(f"the selector '{selector}' is not one a layer may target")
            continue
        declarations: list[str] = []
        for declaration in body.split(";"):
            if not declaration.strip():
                continue
            name, separator, value = declaration.partition(":")
            name = name.strip().casefold()
            value = " ".join(value.split())
            if not separator or not value:
                problems.append(f"'{declaration.strip()}' is not a property and a value")
                continue
            if name not in BESPOKE_ALLOWED_PROPERTIES:
                problems.append(f"'{name}' is not a property a layer may set")
                continue
            if not _BESPOKE_VALUE_RE.match(value):
                problems.append(f"the value for '{name}' uses characters a layer may not use")
                continue
            if _BESPOKE_COLOUR_RE.search(value):
                problems.append(f"'{name}' sets a colour directly; use one of the app's tokens")
                continue
            for token in re.findall(r"var\(\s*(--[a-z0-9\-]+)", value):
                if token not in _BESPOKE_TOKENS:
                    problems.append(f"'{token}' is not one of the app's tokens")
            if name == "font-size" and not _BESPOKE_FONT_SIZE_RE.fullmatch(value):
                problems.append("font-size has to stay inside the app's type scale")
                continue
            declarations.append(f"{name}: {value};")
        if declarations:
            scoped = selector if selector.startswith(".app") else f".app {selector}"
            rules.append(f"    {scoped} {{ {' '.join(declarations)} }}\n")

    if problems:
        return None, sorted(dict.fromkeys(problems))
    if not rules:
        return None, ["the layer had nothing to render"]
    return "".join(rules), []


def _token_block(plan: ExperiencePlan) -> str:
    lines = ["    :root {"]
    for name, custom_property in _TOKEN_PROPERTIES.items():
        lines.append(f"      {custom_property}: {plan.tokens[name]};")
    lines.append(f"      --radius: {plan.tokens['radius_px']}px;")
    lines.append("      --shadow: 0 14px 40px rgba(32, 28, 22, .12);")
    lines.append(f"      --font-body: {_TYPOGRAPHY_STACKS[plan.typography_stack]};")
    lines.append(f"      --font-mono: {_MONO_STACK};")
    lines.append("      font-family: var(--font-body);")
    lines.append("    }")
    return "\n".join(lines) + "\n"


def _html_text(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# The stylesheet, in parts (Lane B1, docs/rebuild-plan-2026-08-28).
#
# Every app used to share one CSS string, so every app looked the same. The
# parts below are composed per build: the shell every app shares, the colour
# tokens, the layout for the chosen topology, and the narrow-screen and motion
# rules that close the sheet.
# ---------------------------------------------------------------------------

_DOCUMENT_HEAD = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
  <title>__TITLE__</title>
  <style>
"""

_RESET_CSS = r"""    * { box-sizing: border-box; }
"""

_BASE_SHELL_CSS = r"""    html { background: var(--bg); color: var(--ink); }
    body { margin: 0; min-height: 100vh; background: var(--bg); }
    button, input, select, textarea { font: inherit; }
    button { min-height: 44px; cursor: pointer; }
    button:disabled { cursor: not-allowed; opacity: .58; }
    button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible {
      outline: 3px solid var(--focus); outline-offset: 3px;
    }
    .skip { position: fixed; left: 1rem; top: -5rem; z-index: 20; background: var(--ink); color: var(--surface); padding: .7rem 1rem; }
    .skip:focus { top: 1rem; }
    .app { min-height: 100vh; display: grid; grid-template-columns: minmax(210px, 260px) 1fr; }
    .rail { min-height: 100vh; padding: 2rem 1.25rem; border-right: 1px solid var(--border); background: color-mix(in srgb, var(--surface) 72%, var(--bg)); position: sticky; top: 0; align-self: start; }
    .brand { margin: 0 0 2.5rem; font-size: clamp(1.6rem, 3vw, 2.5rem); line-height: .98; letter-spacing: -.035em; max-width: 8ch; }
    .world { color: var(--muted); line-height: 1.45; margin: -.9rem 0 2rem; }
    .view-nav { display: grid; gap: .25rem; }
    .view-nav button { text-align: left; padding: .7rem .8rem; border: 0; border-radius: calc(var(--radius) - 3px); color: var(--ink); background: transparent; }
    .view-nav button:hover { background: var(--surface); }
    .view-nav button[aria-current="page"] { background: var(--ink); color: var(--surface); }
    .rail-foot { margin-top: 2.5rem; font-size: .82rem; color: var(--muted); }
    main { min-width: 0; padding: clamp(1.25rem, 4vw, 3.75rem); }
    .topbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 2rem; padding-bottom: 2rem; border-bottom: 1px solid var(--border); }
    .topbar h1 { margin: 0; font-size: clamp(2.4rem, 7vw, 5.7rem); line-height: .92; letter-spacing: -.04em; max-width: 11ch; text-wrap: balance; }
    .topbar p { max-width: 65ch; color: var(--muted); }
    .toolbar { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: .55rem; }
    .button { border: 1px solid var(--border); background: var(--surface); color: var(--ink); border-radius: calc(var(--radius) - 2px); padding: .65rem .9rem; }
    .button:hover { border-color: var(--ink); }
    .button.primary { background: var(--accent); color: #fff; border-color: transparent; }
    .button.danger { color: var(--danger); }
    .view-head { margin: 3.5rem 0 2rem; display: grid; grid-template-columns: minmax(0, 1fr) minmax(220px, 32rem); gap: 2rem; align-items: end; }
    .view-head h2 { margin: 0; font-size: clamp(2rem, 5vw, 4rem); line-height: 1; letter-spacing: -.035em; }
    .view-head p { margin: 0; color: var(--muted); max-width: 70ch; }
    .regions { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 1rem; }
    .region { grid-column: span var(--span); min-width: 0; padding: clamp(1rem, 2.4vw, 2rem); background: var(--surface); border-radius: var(--radius); box-shadow: var(--shadow); }
    .region.support { background: transparent; box-shadow: none; border: 1px solid var(--border); }
    .region h3 { margin: 0 0 1.4rem; font-size: 1.1rem; }
    .region-meta { color: var(--muted); font-size: .78rem; margin: -.9rem 0 1.4rem; }
    .record-list { list-style: none; margin: 0; padding: 0; display: grid; gap: .7rem; }
    .record { padding: .85rem 0; border-top: 1px solid var(--border); min-width: 0; }
    .record:first-child { border-top: 0; padding-top: 0; }
    .record strong { display: block; font-size: 1.05rem; margin-bottom: .25rem; }
    .record-select { width: 100%; min-height: 0; padding: .45rem; margin: -.45rem; border: 0; border-radius: calc(var(--radius) - 4px); background: transparent; color: inherit; text-align: start; }
    .record-select:hover { background: color-mix(in srgb, var(--accent) 7%, transparent); }
    .record-select[aria-pressed="true"] { background: color-mix(in srgb, var(--accent) 12%, transparent); outline: 1px solid var(--accent); }
    .record dl, .detail-grid { margin: .6rem 0 0; display: grid; grid-template-columns: minmax(7rem, .7fr) minmax(0, 1.3fr); gap: .3rem .8rem; }
    dt { color: var(--muted); } dd { margin: 0; overflow-wrap: anywhere; }
    .canvas-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(105px, 1fr)); gap: .65rem; }
    .slot { aspect-ratio: .72; padding: .65rem; background: color-mix(in srgb, var(--accent) 8%, var(--surface)); border: 1px solid var(--border); border-radius: calc(var(--radius) - 3px); display: flex; flex-direction: column; justify-content: space-between; }
    .slot.empty { background: transparent; border-style: dashed; color: var(--muted); }
    .slot-number { font-variant-numeric: tabular-nums; font-size: .75rem; color: var(--muted); }
    .session-card { min-height: 20rem; display: grid; place-items: center; text-align: center; padding: 3rem 1rem; }
    .session-card .cue { font-size: clamp(2.7rem, 9vw, 7rem); line-height: 1; letter-spacing: -.03em; }
    .session-answer { margin-top: 2rem; font-size: 1.15rem; }
    .measure { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
    .timeline { border-inline-start: 1px solid var(--accent-alt); padding-inline-start: 1rem; }
    .timeline .record { position: relative; }
    .timeline .record::before { content: ""; position: absolute; width: 9px; height: 9px; border-radius: 50%; background: var(--accent-alt); inset-inline-start: calc(-1rem - 5px); top: 1.1rem; }
    .timeline time { display: block; color: var(--muted); font-size: .78rem; margin-bottom: .35rem; }
    .chart-figure { margin: 0; }
    .chart-figure svg { display: block; width: 100%; min-height: 220px; overflow: visible; }
    .chart-grid { stroke: var(--border); stroke-width: 1; }
    .chart-area { fill: color-mix(in srgb, var(--accent) 14%, transparent); }
    .chart-line { fill: none; stroke: var(--accent); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
    .chart-point { fill: var(--surface); stroke: var(--accent); stroke-width: 3; }
    .chart-figure figcaption { color: var(--muted); font-size: .82rem; margin-top: .7rem; }
    .data-table-wrap { max-width: 100%; overflow-x: auto; }
    .data-table { width: 100%; border-collapse: collapse; font-size: .9rem; }
    .data-table th, .data-table td { padding: .65rem .7rem; border-bottom: 1px solid var(--border); text-align: start; vertical-align: top; overflow-wrap: anywhere; }
    .data-table th { color: var(--muted); font-size: .76rem; font-weight: 650; }
    .data-table tbody tr[aria-selected="true"] { background: color-mix(in srgb, var(--accent) 10%, transparent); }
    .data-table tbody tr { cursor: pointer; }
    .shelf-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: .8rem; }
    .shelf-item { min-height: 8rem; padding: 1rem; border: 1px solid var(--border); border-radius: calc(var(--radius) - 3px); background: color-mix(in srgb, var(--surface) 84%, var(--accent-alt)); color: var(--ink); text-align: start; }
    .shelf-item[aria-pressed="true"] { outline: 2px solid var(--accent); outline-offset: 2px; }
    .shelf-item small { display: block; color: var(--muted); margin-top: .7rem; }
    .workbench { display: grid; grid-template-columns: minmax(0, .8fr) minmax(0, 1.2fr); gap: 1rem; }
    .workbench aside { border-inline-end: 1px solid var(--border); padding-inline-end: 1rem; }
    .explanation { max-width: 68ch; }
    .explanation strong { display: block; margin-bottom: .55rem; }
    .storage-note { color: var(--muted); font-size: .78rem; margin: .8rem 0 0; }
    .empty-state { min-height: 12rem; display: grid; align-content: center; justify-items: start; gap: .75rem; color: var(--muted); }
    .empty-state p { max-width: 45ch; margin: 0; }
    .view-actions { display: flex; flex-wrap: wrap; gap: .6rem; margin-top: 1.2rem; }
    .status { min-height: 1.5rem; margin-top: 1rem; color: var(--ink); font-weight: 650; }
    .error { min-height: 1.5rem; margin-top: .35rem; color: var(--danger); font-weight: 650; }
    dialog { width: min(680px, calc(100vw - 2rem)); max-height: calc(100vh - 2rem); border: 0; border-radius: var(--radius); padding: 0; color: var(--ink); background: var(--surface); box-shadow: 0 24px 80px rgba(0,0,0,.28); }
    dialog::backdrop { background: rgba(18, 17, 14, .68); }
    .dialog-inner { padding: clamp(1.2rem, 4vw, 2.5rem); }
    .dialog-head { display: flex; justify-content: space-between; gap: 1rem; align-items: start; }
    .dialog-head h2 { margin: 0; font-size: 2rem; letter-spacing: -.03em; }
    .icon-button { width: 44px; padding: 0; border: 1px solid var(--border); border-radius: 50%; background: transparent; }
    .form-grid { margin-top: 1.5rem; display: grid; gap: 1rem; }
    label { display: grid; gap: .35rem; font-weight: 650; }
    label small { color: var(--muted); font-weight: 400; }
    input, select, textarea { width: 100%; min-height: 44px; padding: .65rem .7rem; border: 1px solid var(--border); border-radius: calc(var(--radius) - 3px); background: var(--bg); color: var(--ink); }
    textarea { min-height: 7rem; resize: vertical; }
    .dialog-actions { margin-top: 1.5rem; display: flex; justify-content: flex-end; gap: .6rem; }
    .evidence-item { padding: 1rem 0; border-top: 1px solid var(--border); }
    .evidence-item a { color: var(--accent-alt); }
    .visually-hidden { position: absolute !important; width: 1px !important; height: 1px !important; padding: 0 !important; margin: -1px !important; overflow: hidden !important; clip: rect(0, 0, 0, 0) !important; white-space: nowrap !important; border: 0 !important; }
"""

_TOPOLOGY_CSS: dict[str, str] = {
    "hub": r"""    body[data-topology="hub"] main { max-width: 100rem; }
    body[data-topology="hub"] .hub-overview { display: grid; grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr)); gap: var(--gap); margin: 2.5rem 0 0; }
    body[data-topology="hub"] .hub-card { display: grid; align-content: start; gap: .45rem; text-align: start; padding: var(--pad); border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); color: var(--ink); }
    body[data-topology="hub"] .hub-card[aria-current="page"] { background: var(--ink); color: var(--surface); border-color: var(--ink); }
    body[data-topology="hub"] .hub-card[aria-current="page"] small { color: var(--surface); }
    body[data-topology="hub"] .hub-card strong { font-size: 1.15rem; }
    body[data-topology="hub"] .hub-card small { color: var(--muted); line-height: 1.45; }
    body[data-topology="hub"] .regions { align-items: start; }
""",
    "workflow": r"""    body[data-topology="workflow"] .workflow-track { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(20rem, 1fr); gap: var(--gap); overflow-x: auto; padding-bottom: .8rem; align-items: start; }
    body[data-topology="workflow"] .workflow-stage { display: grid; gap: .8rem; align-content: start; list-style: none; }
    body[data-topology="workflow"] .workflow-step { display: flex; align-items: center; gap: .6rem; color: var(--muted); font-size: .8rem; }
    body[data-topology="workflow"] .workflow-index { width: 1.9rem; height: 1.9rem; display: grid; place-items: center; border-radius: 50%; border: 1px solid var(--border); background: var(--surface); font-variant-numeric: tabular-nums; }
    body[data-topology="workflow"] .workflow-stage .region { grid-column: auto; height: 100%; }
    body[data-topology="workflow"] .workflow-track::after { content: ""; }
""",
    "split": r"""    body[data-topology="split"] .split { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, .85fr); gap: var(--gap); align-items: start; }
    body[data-topology="split"] .split-index, body[data-topology="split"] .split-detail { display: grid; gap: var(--gap); align-content: start; min-width: 0; }
    body[data-topology="split"] .split-detail { position: sticky; top: 1.5rem; }
    body[data-topology="split"] .split .region { grid-column: auto; }
    body[data-topology="split"] .split-detail .region { background: color-mix(in srgb, var(--surface) 93%, var(--accent-alt)); }
""",
    "canvas": r"""    body[data-topology="canvas"] .canvas-board { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: var(--gap); align-items: start; }
    body[data-topology="canvas"] .canvas-tile { grid-column: span var(--tile-span, 3); grid-row: span var(--tile-rows, 1); min-width: 0; }
    body[data-topology="canvas"] .canvas-tile .region { height: 100%; grid-column: auto; }
    body[data-topology="canvas"] .canvas-position { display: block; color: var(--muted); font-size: .72rem; font-variant-numeric: tabular-nums; letter-spacing: .08em; text-transform: uppercase; margin-bottom: .35rem; }
""",
    "session": r"""    body[data-topology="session"] .app { grid-template-columns: 1fr; }
    body[data-topology="session"] .rail { min-height: auto; position: static; border-right: 0; border-bottom: 1px solid var(--border); display: grid; grid-template-columns: auto 1fr; gap: 2rem; padding: 1rem clamp(1rem, 4vw, 3rem); align-items: center; }
    body[data-topology="session"] .brand { margin: 0; max-width: none; font-size: 1.15rem; }
    body[data-topology="session"] .world, body[data-topology="session"] .rail-foot { display: none; }
    body[data-topology="session"] .view-nav { display: flex; justify-content: flex-end; overflow-x: auto; }
    body[data-topology="session"] main { width: min(1100px, 100%); margin: auto; }
    body[data-topology="session"] .session-stage { display: grid; gap: var(--gap); }
""",
}

# What each topology does when the screen gets narrow. Only the block for the
# topology this app uses is written into the file.
_TOPOLOGY_NARROW_CSS: dict[str, str] = {
    "hub": r"""      body[data-topology="hub"] .hub-overview { grid-template-columns: 1fr; }
""",
    "workflow": r"""      body[data-topology="workflow"] .workflow-track { grid-auto-flow: row; grid-auto-columns: auto; overflow-x: visible; }
""",
    "split": r"""      body[data-topology="split"] .split { grid-template-columns: 1fr; }
      body[data-topology="split"] .split-detail { position: static; }
""",
    "canvas": r"""      body[data-topology="canvas"] .canvas-board { grid-template-columns: 1fr; }
      body[data-topology="canvas"] .canvas-tile { grid-column: 1 / -1; }
""",
    "session": r"""      body[data-topology="session"] .rail { display: block; padding: 1rem; }
      body[data-topology="session"] .brand { margin-bottom: .8rem; }
      body[data-topology="session"] .view-nav { justify-content: flex-start; max-width: calc(100vw - 2rem); }
""",
}

# How much room the layout gives each thing. One block per density; only the
# chosen one is written into the file.
_DENSITY_CSS: dict[str, str] = {
    "airy": r"""    html { font-size: 106.25%; }
    :root { --gap: 1.6rem; --pad: clamp(1.35rem, 3vw, 2.4rem); --row-pad: 1.1rem; }
    .regions { gap: var(--gap); }
    .region { padding: var(--pad); }
    .record { padding-block: var(--row-pad); }
    .record-list { gap: 1rem; }
    .view-head { margin-block: 4rem 2.4rem; }
""",
    "bench": r"""    :root { --gap: 1.1rem; --pad: clamp(1rem, 2.4vw, 2rem); --row-pad: .85rem; }
    .regions { gap: var(--gap); }
    .region { padding: var(--pad); }
    .record { padding-block: var(--row-pad); }
    .record-list { gap: .7rem; }
""",
    "dense": r"""    html { font-size: 93.75%; }
    :root { --gap: .6rem; --pad: clamp(.7rem, 1.6vw, 1.15rem); --row-pad: .5rem; }
    .regions { gap: var(--gap); }
    .region { padding: var(--pad); }
    .record { padding-block: var(--row-pad); }
    .record-list { gap: .35rem; }
    .region h3 { margin-bottom: .85rem; }
    .view-head { margin-block: 2.2rem 1.2rem; }
    .data-table th, .data-table td { padding: .4rem .5rem; }
""",
}

# The renderable motifs. A build carries the CSS only for the motifs its spec
# actually asks for.
_SIGNATURE_CSS: dict[str, str] = {
    "progress_bar": r"""    .signature-progress { display: grid; gap: .4rem; width: min(100%, 26rem); margin-top: 1rem; }
    .signature-progress .bar { height: .6rem; border-radius: 999px; background: color-mix(in srgb, var(--accent) 18%, var(--surface)); border: 1px solid var(--border); overflow: hidden; }
    .signature-progress .bar span { display: block; height: 100%; background: var(--accent); }
    .signature-progress .bar-label { color: var(--muted); font-size: .78rem; }
""",
    "life_list": r"""    .signature-life-list ol { list-style: none; margin: 0; padding: 0; display: grid; gap: .3rem; }
    .signature-life-list li { display: flex; justify-content: space-between; gap: .8rem; padding: .35rem 0; border-top: 1px solid var(--border); }
    .signature-life-list li:first-child { border-top: 0; }
    .signature-life-list .count { color: var(--muted); font-variant-numeric: tabular-nums; }
""",
    "comparison_strip": r"""    .signature-comparison .pair { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--gap); }
    .signature-comparison .pair > div { min-width: 0; padding: .8rem; border: 1px solid var(--border); border-radius: calc(var(--radius) - 3px); }
    .signature-comparison .changed { background: color-mix(in srgb, var(--accent) 10%, transparent); }
""",
    "timeline_rail": r"""    .signature-timeline ol { list-style: none; margin: 0; padding: 0 0 0 1rem; border-inline-start: 2px solid var(--accent-alt); display: grid; gap: .7rem; }
    .signature-timeline li { position: relative; }
    .signature-timeline li::before { content: ""; position: absolute; inset-inline-start: calc(-1rem - 5px); top: .45rem; width: 8px; height: 8px; border-radius: 50%; background: var(--accent-alt); }
    .signature-timeline time { display: block; color: var(--muted); font-size: .76rem; }
""",
    "gap_grid": r"""    .signature-gap-grid .cells { display: grid; grid-template-columns: repeat(auto-fill, minmax(3.4rem, 1fr)); gap: .3rem; }
    .signature-gap-grid .cell { min-height: 2.4rem; display: grid; place-items: center; border: 1px solid var(--border); border-radius: calc(var(--radius) - 4px); font-size: .74rem; font-variant-numeric: tabular-nums; background: color-mix(in srgb, var(--accent) 12%, var(--surface)); }
    .signature-gap-grid .cell.missing { background: transparent; border-style: dashed; color: var(--muted); }
""",
}

_SIGNATURE_FRAME_CSS = r"""    .signature { border: 1px solid var(--border); border-radius: var(--radius); padding: var(--pad); background: var(--surface); }
    .signature h2 { margin: 0 0 .8rem; font-size: .95rem; letter-spacing: .04em; text-transform: uppercase; color: var(--muted); }
    .signature-panel { display: grid; gap: var(--gap); align-content: start; }
    .signature-strip { display: grid; gap: var(--gap); margin-bottom: var(--gap); }
    .with-signature-panel { display: grid; grid-template-columns: minmax(0, 1fr) minmax(16rem, 22rem); gap: var(--gap); align-items: start; }
    .signature-note { color: var(--muted); margin: 0; }
"""

_SIGNATURE_NARROW_CSS = r"""      .with-signature-panel { grid-template-columns: 1fr; }
      .signature-comparison .pair { grid-template-columns: 1fr; }
"""

# Curated system-font stacks. The app never reaches the network, so every stack
# is a list of faces the machine already has.
_TYPOGRAPHY_STACKS: dict[str, str] = {
    "reading_serif": (
        '"Iowan Old Style", "Palatino Linotype", Palatino, Georgia, '
        '"Hiragino Mincho ProN", "Yu Mincho", serif'
    ),
    "data_sans": (
        '"Helvetica Neue", "Segoe UI", Roboto, "Hiragino Kaku Gothic ProN", system-ui, sans-serif'
    ),
    "mono_forward": (
        'ui-monospace, "SFMono-Regular", Menlo, Consolas, "Liberation Mono", monospace'
    ),
    "rounded_humanist": (
        '"Avenir Next", Avenir, "Segoe UI", ui-rounded, "Hiragino Maru Gothic ProN", sans-serif'
    ),
    "system_default": ('system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'),
}

_MONO_STACK = 'ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace'

_RESPONSIVE_CSS = r"""    @media (max-width: 820px) {
      .app { grid-template-columns: 1fr; min-width: 0; width: 100%; }
      .rail { min-width: 0; width: 100%; max-width: 100vw; min-height: auto; position: static; border-right: 0; border-bottom: 1px solid var(--border); padding: 1rem; overflow: hidden; }
      .brand { max-width: none; margin: 0 0 .3rem; font-size: 1.4rem; }
      .world, .rail-foot { display: none; }
      .view-nav { display: flex; min-width: 0; width: 100%; max-width: calc(100vw - 2rem); overflow-x: auto; padding-bottom: .2rem; }
      .view-nav button { flex: 0 0 auto; }
      main { min-width: 0; width: 100%; }
      .topbar, .view-head { grid-template-columns: 1fr; display: grid; }
      .toolbar { justify-content: flex-start; }
      .region { grid-column: 1 / -1 !important; }
      .record dl, .detail-grid { grid-template-columns: 1fr; }
      .workbench { grid-template-columns: 1fr; }
      .workbench aside { border-inline-end: 0; border-bottom: 1px solid var(--border); padding-inline-end: 0; padding-bottom: 1rem; }
      .region { order: var(--collapse-order, 50); }
      .region[data-narrow="paged"] .record-list, .region[data-narrow="paged"] .canvas-grid, .region[data-narrow="paged"] .shelf-grid { grid-auto-flow: column; grid-auto-columns: minmax(13rem, 1fr); grid-template-columns: none; overflow-x: auto; padding-bottom: .5rem; }
"""

_RESPONSIVE_CLOSE = r"""    }
"""

_MOTION_CSS = r"""    @media (prefers-reduced-motion: no-preference) {
      .region { animation: resolve-in 420ms cubic-bezier(.16,1,.3,1) both; }
      @keyframes resolve-in { from { opacity: .6; transform: translateY(8px); filter: blur(3px); } to { opacity: 1; transform: none; filter: none; } }
    }
"""

_DOCUMENT_TAIL = r"""  </style>
</head>
<body __BODY_ATTRS__>
  <a class="skip" href="#main">Skip to application</a>
  <div id="app"></div>
  <dialog id="capture-dialog" aria-labelledby="capture-title"><div class="dialog-inner" id="capture-content"></div></dialog>
  <dialog id="evidence-dialog" aria-labelledby="evidence-title"><div class="dialog-inner" id="evidence-content"></div></dialog>
  <script type="application/json" id="foundry-spec">__SPEC_JSON__</script>
  <script>
__RUNTIME_JS__
  </script>
</body>
</html>
"""


__all__ = ["BuildArtifact", "FoundryCompiler"]
