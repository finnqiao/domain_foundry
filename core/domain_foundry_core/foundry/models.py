"""Typed intermediate representation for evidence-backed generated apps.

The FoundrySpec is the test surface shared by research, schema design,
experience design, preview, runtime compilation, export, and evaluation. It is
deliberately stricter than a Domain Pack: a pack is a safe runtime artifact;
this spec also records why that artifact should exist and how its quality is
proved.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ScalarType = Literal[
    "text",
    "integer",
    "number",
    "boolean",
    "date",
    "datetime",
    "duration",
    "enum",
    "attachment",
    "location",
    "json",
]
UserText = Annotated[str, Field(min_length=1, max_length=2_000)]
EntityKind = Literal["canonical", "owned", "event", "state", "observation", "reference"]
Cardinality = Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]
DeleteBehavior = Literal["restrict", "cascade", "set_null", "archive"]
ViewState = Literal[
    "first_use",
    "populated",
    "loading",
    "empty",
    "error",
    "partial",
    "conflict",
    "offline",
    "correction",
]

# ADR-010. How a spec's research was sourced, stamped rather than implied.
EvidenceTier = Literal["reviewed_corpus", "live_search", "model_knowledge", "fallback_demo"]

EVIDENCE_TIER_LABELS: dict[str, str] = {
    "reviewed_corpus": "from reviewed sources",
    "live_search": "from web search results, for reference only, not reviewed",
    "model_knowledge": "from the model's own knowledge, not from verified sources",
    "fallback_demo": "built from your own words, no research was run",
}

# The remix decision the bridge records when it asks for a single concept.
# ``FoundrySpec`` will not accept a one-concept spec that does not say this,
# so the relaxation can never be silent.
SOLE_CONCEPT_DECISION = "wizard-auto: sole concept"


# ---------------------------------------------------------------------------
# Rebuild contracts, 2026-08-28 (docs/rebuild-plan-2026-08-28/00-OVERVIEW.md).
#
# Phase 0 lands every type the seven lanes code against, so the lanes can run in
# parallel without editing this file again. After Phase 0 this module is frozen
# for the rebuild kit: a lane that needs a change files it with the integrator.
# ---------------------------------------------------------------------------

# The five layouts. Named here so Lane B, Lane C, and Lane F can all refer to
# the same set instead of repeating the literal.
NavigationTopology = Literal["hub", "workflow", "split", "canvas", "session"]

# A named, curated system-font stack. The owned app has no network, so a stack
# is a list of fonts already on the machine, never a download.
TypographyStack = Literal[
    "reading_serif",
    "data_sans",
    "mono_forward",
    "rounded_humanist",
    "system_default",
]

TYPOGRAPHY_STACK_LABELS: dict[str, str] = {
    "reading_serif": "a serif made for reading long entries",
    "data_sans": "a compact sans for tables and numbers",
    "mono_forward": "a monospace look for logs and codes",
    "rounded_humanist": "a soft, friendly sans",
    "system_default": "whatever your device already uses",
}

# How much room the layout gives each thing.
DensityScale = Literal["airy", "bench", "dense"]

DENSITY_SCALE_LABELS: dict[str, str] = {
    "airy": "lots of room, one thing at a time",
    "bench": "a working bench: room to read, room to act",
    "dense": "packed, for scanning many rows at once",
}

# The bounded vocabulary of renderable motifs. Lane B ships one runtime
# renderer per member; anything outside this set is prose for nobody.
SignatureElement = Literal[
    "progress_bar",
    "life_list",
    "comparison_strip",
    "timeline_rail",
    "gap_grid",
]

SIGNATURE_ELEMENT_LABELS: dict[str, str] = {
    "progress_bar": "a bar across the top showing how much time or progress is left",
    "life_list": "a side panel listing everything you have found so far",
    "comparison_strip": "a strip that puts two records side by side",
    "timeline_rail": "a rail down the side showing when things happened",
    "gap_grid": "a grid that shows what you have and what is still missing",
}

# Where a seeded record came from. Personal uploads never leave the machine.
SeedSourceKind = Literal["personal_upload", "public_link"]

SEED_SOURCE_LABELS: dict[str, str] = {
    "personal_upload": "something you keep: a file, a folder, an export",
    "public_link": "a page you pointed at",
}

# The bespoke CSS envelope (Lane B5). The sanitizer lives in the compiler; the
# budget and the allowlist live here so the audit and the tests share one truth.
BESPOKE_CSS_BUDGET_BYTES = 8_192

BESPOKE_ALLOWED_PROPERTIES: frozenset[str] = frozenset(
    {
        "align-items",
        "align-self",
        "aspect-ratio",
        "background",
        "background-color",
        "border",
        "border-bottom",
        "border-color",
        "border-left",
        "border-radius",
        "border-right",
        "border-style",
        "border-top",
        "border-width",
        "box-shadow",
        "color",
        "column-gap",
        "display",
        "flex",
        "flex-direction",
        "flex-wrap",
        "font-size",
        "font-style",
        "font-variant-numeric",
        "font-weight",
        "gap",
        "grid-area",
        "grid-auto-flow",
        "grid-column",
        "grid-row",
        "grid-template-areas",
        "grid-template-columns",
        "grid-template-rows",
        "justify-content",
        "justify-self",
        "letter-spacing",
        "line-height",
        "margin",
        "margin-block",
        "margin-bottom",
        "margin-inline",
        "margin-left",
        "margin-right",
        "margin-top",
        "max-width",
        "min-height",
        "min-width",
        "opacity",
        "order",
        "outline",
        "outline-offset",
        "overflow",
        "padding",
        "padding-block",
        "padding-bottom",
        "padding-inline",
        "padding-left",
        "padding-right",
        "padding-top",
        "position",
        "row-gap",
        "text-align",
        "text-decoration",
        "text-transform",
        "width",
    }
)

# Anything on this list ends a build's bespoke layer, no exceptions. The layer
# is dropped, the rejection is written into the receipt, and the build carries
# on without it.
BESPOKE_FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    "@import",
    "url(",
    "expression(",
    "javascript:",
    "</style",
    "<script",
    "\\",
    "behavior:",
    "-moz-binding",
    "image-set(",
    "element(",
)

# A spec id, and therefore a fork parent reference (Lane G4).
SPEC_ID_PATTERN = r"^[a-z][a-z0-9-]{0,119}$"


def evidence_tier_label(tier: str | None) -> str:
    """Copy a pack or a UI can show verbatim. Never guesses upward."""
    if not tier:
        return EVIDENCE_TIER_LABELS["fallback_demo"]
    return EVIDENCE_TIER_LABELS.get(tier, f"from an unrecognised evidence tier ({tier})")


class SpecPart(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BespokeLayer(SpecPart):
    """Per-app CSS the model may write, inside an envelope the compiler checks.

    The compiler is the enforcer. This type records what was asked for; a layer
    that breaks the envelope is rejected at build time and the rejection is
    written into the receipt, so a dropped layer is never silent.
    """

    css: str = Field(min_length=1, max_length=BESPOKE_CSS_BUDGET_BYTES)
    rationale: UserText
    scope: Literal["app"] = "app"

    @model_validator(mode="after")
    def stays_inside_the_envelope(self) -> BespokeLayer:
        lowered = self.css.casefold()
        for banned in BESPOKE_FORBIDDEN_SUBSTRINGS:
            if banned in lowered:
                raise ValueError(f"bespoke css may not contain {banned!r}")
        if len(self.css.encode("utf-8")) > BESPOKE_CSS_BUDGET_BYTES:
            raise ValueError(f"bespoke css is over the {BESPOKE_CSS_BUDGET_BYTES} byte budget")
        return self


class BorrowedFragment(SpecPart):
    """A named piece the user liked in one concept and wants in another."""

    from_concept: str = Field(min_length=1, max_length=120)
    piece: UserText
    reason: UserText | None = None


class LookBinding(SpecPart):
    """What the user approved on the review page, in a shape the build reads.

    This is the answer to the discarded-mockup problem: Lane C writes it, Lane B
    compiles it. Every field is optional except the look it came from, so a
    partly marked page still binds what it does say.
    """

    look_id: str = Field(min_length=1, max_length=120)
    concept_id: str | None = Field(default=None, max_length=120)
    topology: NavigationTopology | None = None
    typography_stack: TypographyStack | None = None
    density_scale: DensityScale | None = None
    token_overrides: dict[str, str] = Field(default_factory=dict, max_length=20)
    signature_elements: list[SignatureElement] = Field(default_factory=list, max_length=5)
    borrowed_fragments: list[BorrowedFragment] = Field(default_factory=list, max_length=10)
    bespoke: BespokeLayer | None = None
    notes: list[UserText] = Field(default_factory=list, max_length=40)
    approved_at: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def overrides_are_real_tokens(self) -> LookBinding:
        known = set(VisualTokens.model_fields)
        unknown = set(self.token_overrides) - known
        if unknown:
            raise ValueError(f"unknown token overrides: {sorted(unknown)}")
        for name, value in self.token_overrides.items():
            if name == "radius_px":
                if not value.isdigit() or not 0 <= int(value) <= 24:
                    raise ValueError("radius_px must be a whole number from 0 to 24")
                continue
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
                raise ValueError(f"{name} must be a colour like #E39A2D, got {value!r}")
        return self


class SeedProvenance(SpecPart):
    """Where one seeded batch of records came from, and whether it can travel.

    The rule the whole sharing line rests on: shapes and public links can
    travel, your records never do. A personal upload is not shareable, and
    setting it so is a validation error rather than a setting someone can flip.
    """

    id: str = Field(min_length=1, max_length=120)
    kind: SeedSourceKind
    label: UserText
    location: str | None = Field(default=None, max_length=2_000)
    retrieved_at: str | None = Field(default=None, max_length=40)
    license: str | None = Field(default=None, max_length=200)
    row_count: int | None = Field(default=None, ge=0)
    columns: list[str] = Field(default_factory=list, max_length=200)

    @property
    def shareable(self) -> bool:
        """Only a public link can ever be offered for sharing."""

        return self.kind == "public_link"

    @model_validator(mode="after")
    def personal_stays_home(self) -> SeedProvenance:
        if self.kind == "personal_upload" and self.license is not None:
            raise ValueError("a personal upload does not carry a license; it is the user's own")
        if self.kind == "public_link" and not self.location:
            raise ValueError("a public link must record where it came from")
        return self


class TraitEdge(SpecPart):
    """One "if this, then that" rule: a trait of a practice, and what it means
    the app should be shaped like.

    Authored edges cite the knowledge base. Detected edges name the seed they
    were read off. Neither may claim both origins at once.
    """

    id: str = Field(min_length=1, max_length=120)
    trait: UserText
    consequence: UserText
    origin: Literal["authored", "detected"] = "authored"
    topology: NavigationTopology | None = None
    signature_elements: list[SignatureElement] = Field(default_factory=list, max_length=5)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    seed_ids: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def says_where_it_came_from(self) -> TraitEdge:
        if self.origin == "authored" and not self.evidence_ids:
            raise ValueError("an authored trait edge must cite evidence")
        if self.origin == "detected" and not (self.seed_ids or self.evidence_ids):
            raise ValueError("a detected trait edge must name the seed it was read off")
        return self


class ResearchBrief(SpecPart):
    interest: str
    desired_outcome: str
    practice: list[str] = Field(min_length=2)
    existing_artifacts: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    usage_context: list[str] = Field(min_length=1)
    first_value: str
    # What the user already keeps, seeded in through Lane E.
    seeds: list[SeedProvenance] = Field(default_factory=list, max_length=50)
    # What the shape of the practice implies about the shape of the app (Lane F).
    traits: list[TraitEdge] = Field(default_factory=list, max_length=30)


class EvidenceCitation(SpecPart):
    id: str
    source_id: str
    claim: str
    use: Literal["fact", "pattern", "constraint", "inspiration"]
    locator: str | None = None


class SourceSnapshot(SpecPart):
    """A build-local source absent from the maintained repository registry."""

    id: str
    title: str
    publisher: str
    url: str | None = Field(default=None, pattern=r"^https://")
    kind: str
    tier: Literal[
        "authoritative",
        "reviewed_implementation",
        "research",
        "product_reference",
        "domain_exemplar",
        "model_knowledge",
    ]
    license: str
    allowed_uses: list[
        Literal[
            "reference_facts",
            "paraphrase",
            "inspect_code",
            "inspect_schema",
            "inspect_examples",
        ]
    ] = Field(min_length=1)
    status: Literal["approved", "reference_only"]
    origin: Literal["reviewed_registry", "live_search", "model_recall"] | None = None
    retrieved_at: str
    freshness_days: int = Field(ge=1)
    topics: list[str] = Field(min_length=1)
    content_digest: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    reviewed_by: str | None = None

    @model_validator(mode="after")
    def provenance_is_unmistakable(self) -> SourceSnapshot:
        """Model recall may never dress itself up as a retrieved source.

        ``url`` became optional so this tier could exist without inventing one —
        inventing a URL is exactly what the pipeline forbids the model to do —
        so every other tier is now required to carry one explicitly.
        """
        if self.tier == "model_knowledge":
            if self.origin != "model_recall":
                raise ValueError("a model_knowledge source must set origin=model_recall")
            if self.status != "reference_only":
                raise ValueError("a model_knowledge source is never approved")
            if self.url is not None:
                raise ValueError("model recall has no URL; it was not retrieved from anywhere")
        else:
            if self.url is None:
                raise ValueError(f"source {self.id} must cite the URL it was retrieved from")
            if self.origin == "model_recall":
                raise ValueError("origin=model_recall requires tier=model_knowledge")
        return self


class GenerationStageReceipt(SpecPart):
    stage: Literal["research_plan", "evidence", "concepts", "domain", "experience", "delivery"]
    provider: str | None = None
    model: str | None = None
    input_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class GenerationReceipt(SpecPart):
    origin: Literal["model_assisted", "manual_golden"]
    pipeline_version: str
    generated_at: str
    stages: list[GenerationStageReceipt] = Field(default_factory=list)
    # Absent on the hand-authored goldens, which predate the tier and were not
    # produced by retrieval at all.
    evidence_tier: EvidenceTier | None = None


class ProductConcept(SpecPart):
    id: str
    title: str
    thesis: str
    primary_loop: str
    primary_affordance: str
    differentiator: str
    feature_boundary: list[str] = Field(min_length=2)
    tradeoffs: list[str] = Field(min_length=1)
    workflow_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class RemixFragment(SpecPart):
    kind: Literal["workflow", "schema", "interaction", "visual_system", "concept"]
    from_concept: str = Field(min_length=1, max_length=120)
    fragment: UserText
    reason: UserText
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class RemixSelection(SpecPart):
    selected_concept: str = Field(min_length=1, max_length=120)
    # The spec this one was forked from. `fork` (Lane G4) is the only writer;
    # everything else leaves it alone.
    parent_spec: str | None = Field(default=None, max_length=240)
    fragments: list[RemixFragment] = Field(default_factory=list, max_length=10)
    user_decisions: list[UserText] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def parent_is_a_spec_id(self) -> RemixSelection:
        if self.parent_spec is not None and not re.fullmatch(SPEC_ID_PATTERN, self.parent_spec):
            raise ValueError(
                f"parent_spec must be a spec id like 'sourdough-lab', got {self.parent_spec!r}"
            )
        return self


class FieldSpec(SpecPart):
    name: str
    type: ScalarType
    description: str
    required: bool = False
    unit: str | None = None
    values: list[str] | None = None
    sensitive: bool = False
    evidence_ids: list[str] = Field(default_factory=list)


class EntitySpec(SpecPart):
    id: str
    title: str
    kind: EntityKind
    description: str
    identity: list[str] = Field(min_length=1)
    lifecycle: list[str] = Field(min_length=1)
    fields: list[FieldSpec] = Field(min_length=2)
    evidence_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def identity_fields_exist(self) -> EntitySpec:
        field_names = {field.name for field in self.fields}
        missing = set(self.identity) - field_names
        if missing:
            raise ValueError(f"identity fields do not exist: {sorted(missing)}")
        return self


class RelationshipSpec(SpecPart):
    id: str
    from_entity: str
    to_entity: str
    cardinality: Cardinality
    required: bool = False
    on_delete: DeleteBehavior = "restrict"
    description: str
    evidence_ids: list[str] = Field(min_length=1)


class ConstraintSpec(SpecPart):
    id: str
    entity: str
    kind: Literal["required", "unique", "check", "foreign_key", "state_transition"]
    fields: list[str] = Field(min_length=1)
    expression: str | None = None
    reason: str
    evidence_ids: list[str] = Field(min_length=1)


class IndexSpec(SpecPart):
    id: str
    entity: str
    fields: list[str] = Field(min_length=1)
    unique: bool = False
    reason: str
    workload_ids: list[str] = Field(min_length=1)


class WorkloadSpec(SpecPart):
    id: str
    question: str
    kind: Literal["read", "write", "analysis"]
    entities: list[str] = Field(min_length=1)
    filters: list[str] = Field(default_factory=list)
    sort: list[str] = Field(default_factory=list)
    expected_scale: str
    acceptance: str
    evidence_ids: list[str] = Field(min_length=1)


class TransitionSpec(SpecPart):
    from_state: str
    action: str
    to_state: str


class StateMachineSpec(SpecPart):
    id: str
    entity: str
    field: str
    states: list[str] = Field(min_length=2)
    transitions: list[TransitionSpec] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class DomainModel(SpecPart):
    entities: list[EntitySpec] = Field(min_length=4)
    relationships: list[RelationshipSpec] = Field(min_length=2)
    constraints: list[ConstraintSpec] = Field(min_length=2)
    indexes: list[IndexSpec] = Field(min_length=1)
    workloads: list[WorkloadSpec] = Field(min_length=3)
    state_machines: list[StateMachineSpec] = Field(default_factory=list)
    sample_records: dict[str, list[dict[str, Any]]]
    temporal_policy: list[str] = Field(min_length=1)
    privacy_policy: list[str] = Field(min_length=1)


class VisualWorld(SpecPart):
    id: str
    name: str
    mood: str
    typography: str
    color_strategy: str
    layout_principle: str
    density: str
    signature_elements: list[str] = Field(min_length=2)
    avoid: list[str] = Field(min_length=1)
    tokens: VisualTokens
    # The renderable half of the three prose fields above. Lane B reads these;
    # where they are absent it maps the prose onto them and says so.
    typography_stack: TypographyStack | None = None
    density_scale: DensityScale | None = None
    signature_element_ids: list[SignatureElement] = Field(default_factory=list, max_length=5)
    # Per-app CSS inside a checked envelope (Lane B5). Optional: a spec without
    # one builds exactly as it did before.
    bespoke: BespokeLayer | None = None


class VisualTokens(SpecPart):
    background: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    surface: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    text: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    muted: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    accent: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    accent_alt: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    border: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    focus: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    danger: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    radius_px: int = Field(ge=0, le=24)


class NavigationSpec(SpecPart):
    topology: NavigationTopology
    primary_view: str
    persistent_regions: list[str] = Field(default_factory=list)


class ViewAction(SpecPart):
    id: str
    label: str
    operation: Literal["create", "update", "correct", "reveal"]
    entity: str
    consequence: str


class ViewRegion(SpecPart):
    id: str
    kind: Literal[
        "chart",
        "timeline",
        "form",
        "media",
        "comparison",
        "canvas",
        "inspector",
        "catalog",
        "ledger",
        "session",
        "explanation",
        "workbench",
        "shelf",
        "table",
    ]
    title: str
    entity: str
    workload_id: str
    emphasis: Literal["primary", "secondary", "support"]
    span: int = Field(ge=3, le=12)


class ViewSpec(SpecPart):
    id: str
    title: str
    purpose: str
    layout: str
    entities: list[str] = Field(min_length=1)
    workload_ids: list[str] = Field(min_length=1)
    states: list[ViewState] = Field(min_length=3)
    regions: list[ViewRegion] = Field(min_length=1)
    actions: list[ViewAction] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def local_contract_is_closed(self) -> ViewSpec:
        region_ids = [region.id for region in self.regions]
        action_ids = [action.id for action in self.actions]
        if len(set(region_ids)) != len(region_ids):
            raise ValueError("region ids must be unique within a view")
        if len(set(action_ids)) != len(action_ids):
            raise ValueError("action ids must be unique within a view")
        declared_entities = set(self.entities)
        declared_workloads = set(self.workload_ids)
        for region in self.regions:
            if region.entity not in declared_entities:
                raise ValueError(f"region {region.id} uses an entity outside its view")
            if region.workload_id not in declared_workloads:
                raise ValueError(f"region {region.id} uses a workload outside its view")
        for action in self.actions:
            if action.entity not in declared_entities:
                raise ValueError(f"action {action.id} uses an entity outside its view")
        return self


class FlowStep(SpecPart):
    view: str
    action: str
    result: str


class FlowSpec(SpecPart):
    id: str
    title: str
    trigger: str
    steps: list[FlowStep] = Field(min_length=2)
    success: str


class AccessibilitySpec(SpecPart):
    target: Literal["WCAG-2.2-AA"] = "WCAG-2.2-AA"
    patterns: list[str] = Field(min_length=1)
    keyboard_model: list[str] = Field(min_length=1)
    manual_checks: list[str] = Field(min_length=1)


class ExperienceSpec(SpecPart):
    mode: Literal["operate"] = "operate"
    visual_world: VisualWorld
    navigation: NavigationSpec
    views: list[ViewSpec] = Field(min_length=3)
    flows: list[FlowSpec] = Field(min_length=2)
    responsive_strategy: list[str] = Field(min_length=2)
    accessibility: AccessibilitySpec


class ImplementationSpec(SpecPart):
    targets: list[Literal["foundry_runtime", "standalone_react"]] = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    imports: list[str] = Field(default_factory=list)
    exports: list[str] = Field(min_length=1)
    migrations: list[str] = Field(min_length=1)
    permissions: list[str] = Field(default_factory=list)
    adapter_seams: list[str] = Field(min_length=1)


class EvaluationCase(SpecPart):
    id: str
    kind: Literal["schema", "workload", "routing", "task", "accessibility", "security"]
    input: str
    expected: str
    authored_by: Literal["domain_expert", "user", "independent_reviewer", "standard"]


class EvaluationSpec(SpecPart):
    cases: list[EvaluationCase] = Field(min_length=6)
    release_thresholds: dict[str, str] = Field(min_length=1)


class Derivation(SpecPart):
    output_path: str
    decision: str
    evidence_ids: list[str] = Field(default_factory=list)
    user_decision: str | None = None

    @model_validator(mode="after")
    def has_justification(self) -> Derivation:
        if not self.evidence_ids and not self.user_decision:
            raise ValueError("a derivation needs evidence_ids or user_decision")
        return self


class FoundrySpec(SpecPart):
    spec_version: Literal["1.0"] = "1.0"
    id: str
    title: str
    generation: GenerationReceipt | None = None
    source_ids: list[str] = Field(min_length=3)
    source_snapshots: list[SourceSnapshot] = Field(default_factory=list)
    principle_ids: list[str] = Field(min_length=6)
    research: ResearchBrief
    evidence: list[EvidenceCitation] = Field(min_length=4)
    # Three, or one with the reason on the record. See ADR-010: the three-way
    # choice exists so a person can compare real alternatives, and a
    # conversational create has no surface to compare them on.
    concepts: list[ProductConcept] = Field(min_length=1, max_length=3)
    remix: RemixSelection
    domain: DomainModel
    experience: ExperienceSpec
    implementation: ImplementationSpec
    evaluation: EvaluationSpec
    derivations: list[Derivation] = Field(min_length=4)
    # What the user approved on the review page (Lane C). Absent until they
    # approve one; present, it binds the build.
    look: LookBinding | None = None

    @model_validator(mode="after")
    def references_are_closed(self) -> FoundrySpec:
        snapshot_ids = {item.id for item in self.source_snapshots}
        if len(snapshot_ids) != len(self.source_snapshots):
            raise ValueError("source snapshot ids must be unique")
        if not snapshot_ids <= set(self.source_ids):
            raise ValueError("source snapshots must be declared in source_ids")
        evidence_ids = {item.id for item in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            raise ValueError("evidence ids must be unique")
        unknown_sources = {item.source_id for item in self.evidence} - set(self.source_ids)
        if unknown_sources:
            raise ValueError(f"evidence uses undeclared sources: {sorted(unknown_sources)}")

        concept_count = len(self.concepts)
        if concept_count not in {1, 3}:
            raise ValueError("a spec carries three comparable concepts, or one declared sole one")
        if concept_count == 1 and SOLE_CONCEPT_DECISION not in self.remix.user_decisions:
            raise ValueError(
                f"a single-concept spec must record {SOLE_CONCEPT_DECISION!r} "
                "in remix.user_decisions"
            )
        concept_ids = {concept.id for concept in self.concepts}
        if len(concept_ids) != concept_count:
            raise ValueError("concept ids must be unique")
        concept_signatures = {
            (
                concept.primary_loop.casefold().strip(),
                concept.primary_affordance.casefold().strip(),
                tuple(sorted(concept.workflow_ids)),
            )
            for concept in self.concepts
        }
        if len(concept_signatures) != concept_count:
            raise ValueError(
                "concepts must differ in primary loop, affordance, and workflow structure"
            )
        if self.remix.selected_concept not in concept_ids:
            raise ValueError("selected concept does not exist")
        for fragment in self.remix.fragments:
            if fragment.from_concept not in concept_ids:
                raise ValueError(f"remix fragment uses unknown concept {fragment.from_concept}")
        self._check_evidence("concept", self.concepts, evidence_ids)

        entity_by_id = {entity.id: entity for entity in self.domain.entities}
        if len(entity_by_id) != len(self.domain.entities):
            raise ValueError("entity ids must be unique")
        if set(self.domain.sample_records) != set(entity_by_id):
            raise ValueError("sample_records must cover every entity exactly")
        for entity_id, records in self.domain.sample_records.items():
            if not records:
                raise ValueError(f"sample_records for {entity_id} must not be empty")
            entity = entity_by_id[entity_id]
            field_names = {field.name for field in entity.fields}
            required = {field.name for field in entity.fields if field.required}
            for record in records:
                unknown = set(record) - field_names
                missing = required - record.keys()
                if unknown or missing:
                    raise ValueError(
                        f"sample record for {entity_id} has unknown={sorted(unknown)} "
                        f"missing={sorted(missing)}"
                    )
        workload_ids = {workload.id for workload in self.domain.workloads}
        if len(workload_ids) != len(self.domain.workloads):
            raise ValueError("workload ids must be unique")
        relationship_ids = {item.id for item in self.domain.relationships}
        constraint_ids = {item.id for item in self.domain.constraints}
        index_ids = {item.id for item in self.domain.indexes}
        if len(relationship_ids) != len(self.domain.relationships):
            raise ValueError("relationship ids must be unique")
        if len(constraint_ids) != len(self.domain.constraints):
            raise ValueError("constraint ids must be unique")
        if len(index_ids) != len(self.domain.indexes):
            raise ValueError("index ids must be unique")
        for relationship in self.domain.relationships:
            self._require_entities(entity_by_id, relationship.from_entity, relationship.to_entity)
        for constraint in self.domain.constraints:
            self._require_entities(entity_by_id, constraint.entity)
            fields = {field.name for field in entity_by_id[constraint.entity].fields}
            missing = set(constraint.fields) - fields
            if missing:
                raise ValueError(
                    f"constraint {constraint.id} uses unknown fields {sorted(missing)}"
                )
        for index in self.domain.indexes:
            self._require_entities(entity_by_id, index.entity)
            fields = {field.name for field in entity_by_id[index.entity].fields}
            missing = set(index.fields) - fields
            if missing:
                raise ValueError(f"index {index.id} uses unknown fields {sorted(missing)}")
            if not set(index.workload_ids) <= workload_ids:
                raise ValueError(f"index {index.id} uses unknown workload")
        for workload in self.domain.workloads:
            self._require_entities(entity_by_id, *workload.entities)
        for machine in self.domain.state_machines:
            self._require_entities(entity_by_id, machine.entity)
            if machine.field not in {field.name for field in entity_by_id[machine.entity].fields}:
                raise ValueError(f"state machine {machine.id} uses unknown field")

        view_ids = {view.id for view in self.experience.views}
        if len(view_ids) != len(self.experience.views):
            raise ValueError("view ids must be unique")
        flow_ids = {flow.id for flow in self.experience.flows}
        if len(flow_ids) != len(self.experience.flows):
            raise ValueError("flow ids must be unique")
        if self.experience.navigation.primary_view not in view_ids:
            raise ValueError("navigation primary_view does not exist")
        for view in self.experience.views:
            self._require_entities(entity_by_id, *view.entities)
            if not set(view.workload_ids) <= workload_ids:
                raise ValueError(f"view {view.id} uses unknown workload")
            for region in view.regions:
                self._require_entities(entity_by_id, region.entity)
                if region.workload_id not in workload_ids:
                    raise ValueError(f"region {region.id} uses unknown workload")
            for action in view.actions:
                self._require_entities(entity_by_id, action.entity)
        for flow in self.experience.flows:
            for step in flow.steps:
                if step.view not in view_ids:
                    raise ValueError(f"flow {flow.id} uses unknown view {step.view}")

        cited_groups = [
            self.evidence,
            self.concepts,
            self.domain.entities,
            self.domain.relationships,
            self.domain.constraints,
            self.domain.workloads,
            self.domain.state_machines,
            self.experience.views,
            self.derivations,
        ]
        for group in cited_groups[1:]:
            self._check_evidence("spec item", group, evidence_ids)
        return self

    @property
    def evidence_tier(self) -> EvidenceTier | None:
        """How this spec's research was sourced, or ``None`` if unstamped."""
        return self.generation.evidence_tier if self.generation else None

    @property
    def evidence_tier_label(self) -> str:
        """The sentence a pack's metadata and the UI show the owner."""
        return evidence_tier_label(self.evidence_tier)

    @staticmethod
    def _require_entities(entities: dict[str, EntitySpec], *entity_ids: str) -> None:
        missing = set(entity_ids) - entities.keys()
        if missing:
            raise ValueError(f"unknown entities: {sorted(missing)}")

    @staticmethod
    def _check_evidence(label: str, items: Sequence[object], known: set[str]) -> None:
        for item in items:
            refs = set(getattr(item, "evidence_ids", []))
            unknown = refs - known
            if unknown:
                item_id = getattr(item, "id", label)
                raise ValueError(f"{item_id} uses unknown evidence: {sorted(unknown)}")


__all__ = [
    "BESPOKE_ALLOWED_PROPERTIES",
    "BESPOKE_CSS_BUDGET_BYTES",
    "BESPOKE_FORBIDDEN_SUBSTRINGS",
    "DENSITY_SCALE_LABELS",
    "EVIDENCE_TIER_LABELS",
    "SEED_SOURCE_LABELS",
    "SIGNATURE_ELEMENT_LABELS",
    "SOLE_CONCEPT_DECISION",
    "SPEC_ID_PATTERN",
    "TYPOGRAPHY_STACK_LABELS",
    "BespokeLayer",
    "BorrowedFragment",
    "DensityScale",
    "EvidenceTier",
    "FoundrySpec",
    "LookBinding",
    "NavigationTopology",
    "SeedProvenance",
    "SeedSourceKind",
    "SignatureElement",
    "TraitEdge",
    "TypographyStack",
    "evidence_tier_label",
]
