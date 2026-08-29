"""Domain Pack data models (packs-are-data, ADR-004)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

InterpretationMode = Literal["simple", "structured", "interactive"]
AutonomyLevel = Literal["auto", "interactive", "review"]
FieldType = Literal[
    "text",
    "number",
    "integer",
    "boolean",
    "date",
    "datetime",
    "duration",
    "enum",
    "attachment",
    "location",
]


class PackImport(BaseModel):
    """One object borrowed from another pack, declared in ``pack.yaml``.

    The borrowed object keeps its own pack's table. Nothing is copied.
    """

    model_config = ConfigDict(populate_by_name=True)

    from_pack: str = Field(validation_alias=AliasChoices("from", "from_pack"))
    object: str
    as_name: str | None = Field(default=None, validation_alias=AliasChoices("as", "as_name"))

    @property
    def local_name(self) -> str:
        return self.as_name or self.object

    @property
    def target(self) -> str:
        return f"{self.from_pack}.{self.object}"


class PackManifest(BaseModel):
    name: str
    version: str
    title: str
    description: str = ""
    author: str = ""
    license: str = "MIT"
    core_compat: str = ">=0.1,<2"
    aliases: list[str] = Field(default_factory=list)
    interpretation: InterpretationMode = "simple"
    # Packs are data-only by default.  These are narrow, user-facing
    # declarations rather than an escape hatch for arbitrary capabilities.
    # The loader rejects anything outside its allow-list before installation.
    permissions: list[str] = Field(default_factory=list)
    # Composition (optional, declarative). ``extends`` names one pack this pack
    # builds on; ``imports`` names objects it borrows from other packs.
    extends: str | None = None
    imports: list[PackImport] = Field(default_factory=list)


class FieldSpec(BaseModel):
    type: FieldType
    required: bool = False
    default: Any = None
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    values: list[str] | None = None
    allow_other: bool = False
    long: bool = False
    many: bool = False


class LinkSpec(BaseModel):
    to: str
    cardinality: str = "many_to_one"

    @property
    def target_pack(self) -> str | None:
        """The pack half of ``to``, or None when the link is same-pack shorthand."""
        pack, sep, obj = self.to.partition(".")
        return pack if sep and obj else None

    @property
    def target_object(self) -> str:
        pack, sep, obj = self.to.partition(".")
        return obj if sep and obj else pack


def link_column(link_name: str) -> str:
    """The column that carries a link, holding the target row's ``object_uid``."""
    return f"{link_name}_uid"


class ObjectSpec(BaseModel):
    title_field: str | None = None
    fields: dict[str, FieldSpec] = Field(default_factory=dict)
    links: dict[str, LinkSpec] = Field(default_factory=dict)


class ImportedObject(BaseModel):
    """A resolved :class:`PackImport`. The object stays owned by its own pack."""

    local_name: str
    pack: str
    object: str
    spec: ObjectSpec

    @property
    def target(self) -> str:
        return f"{self.pack}.{self.object}"


class RoutingRule(BaseModel):
    match: str
    object: str
    confidence_boost: float = 0.0
    operation: str = "create"
    # Optional LLM tier override when this rule matches and L2 is invoked.
    # "sota" for schema-affecting / architectural / ambiguous interpretations.
    tier: str | None = None


class RoutingExample(BaseModel):
    text: str
    expect: dict[str, Any] = Field(default_factory=dict)


class RoutingSpec(BaseModel):
    rules: list[RoutingRule] = Field(default_factory=list)
    examples: list[RoutingExample] = Field(default_factory=list)
    negative_examples: list[RoutingExample | dict[str, Any]] = Field(default_factory=list)
    llm_hints: str = ""


class PolicyRow(BaseModel):
    operation: str | None = None
    min_confidence: float | None = None
    action: str = "auto_apply"
    match: dict[str, Any] | None = None
    object_type: str | None = None
    channel: str | None = None


class UIActionSpec(BaseModel):
    """A field-exact action that the first-party UI may invoke."""

    object_type: str
    operation: str
    fields: list[str] = Field(default_factory=list)


class PolicySpec(BaseModel):
    defaults: list[PolicyRow] = Field(default_factory=list)
    fallback: str = "unfiled_card"
    ui_actions: list[UIActionSpec] = Field(default_factory=list)

    def allows_ui_action(
        self, *, object_type: str, operation: str, fields: dict[str, Any] | None
    ) -> bool:
        """Require an exact declared object/operation/field combination."""
        requested = set(fields or {})
        return any(
            action.object_type == object_type
            and action.operation == operation
            and requested == set(action.fields)
            for action in self.ui_actions
        )


class AppView(BaseModel):
    id: str
    title: str
    block: str
    object: str | None = None
    objects: list[str] | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class ProjectionsSpec(BaseModel):
    app: dict[str, Any] = Field(default_factory=dict)
    markdown: dict[str, Any] = Field(default_factory=dict)


class PackCompatibility(BaseModel):
    """Compatibility claims for declarative capabilities.

    Capability versions are intentionally separate from ``core_compat``: a
    pack can load on the same core while asking for a capability that an older
    shell cannot render.
    """

    core: str | None = None
    capabilities: dict[str, str] = Field(default_factory=dict)


class AgentSessionSpec(BaseModel):
    """Multi-turn session machine (mesh P2+). Defined now; unused until P4."""

    id: str
    goal: str = ""
    state: dict[str, Any] = Field(default_factory=dict)
    enter: list[dict[str, Any]] = Field(default_factory=list)
    turn: str = ""
    exit: list[dict[str, Any]] = Field(default_factory=list)


class AgentScheduleSpec(BaseModel):
    """Proactive schedule trigger (mesh P2+). Defined now; unused until P4."""

    id: str
    cron: str = ""
    when: str = ""
    action: str = ""
    message: str = ""


class AgentSpec(BaseModel):
    """Per-pack agent manifest (`agent.yaml`) — mesh P1 surface."""

    name: str
    persona: str = ""
    tools: list[str] = Field(default_factory=list)
    autonomy: dict[str, AutonomyLevel | str] = Field(default_factory=dict)
    sessions: list[AgentSessionSpec] = Field(default_factory=list)
    schedules: list[AgentScheduleSpec] = Field(default_factory=list)


class DomainPack(BaseModel):
    root: Path
    manifest: PackManifest
    objects: dict[str, ObjectSpec]
    routing: RoutingSpec
    operations: dict[str, list[str]]
    policy: PolicySpec
    projections: ProjectionsSpec
    capabilities: dict[str, dict[str, Any]] = Field(default_factory=dict)
    compatibility: PackCompatibility = Field(default_factory=PackCompatibility)
    agent: AgentSpec | None = None
    # Composition results, filled in by the loader.
    inherits: list[str] = Field(default_factory=list)
    imports: dict[str, ImportedObject] = Field(default_factory=dict)
    # Link targets in packs that are not installed here. Recorded, not an error.
    soft_dependencies: list[str] = Field(default_factory=list)

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def version(self) -> str:
        return self.manifest.version

    @property
    def extends(self) -> str | None:
        return self.manifest.extends

    def link_target(self, link: LinkSpec) -> tuple[str, str]:
        """The (pack, object) a link points at, resolving imports and shorthand."""
        pack = link.target_pack
        obj = link.target_object
        if pack is None:
            imported = self.imports.get(obj)
            if imported is not None:
                return imported.pack, imported.object
            return self.name, obj
        return pack, obj
