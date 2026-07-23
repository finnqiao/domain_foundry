"""Domain Pack data models (packs-are-data, ADR-004)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

InterpretationMode = Literal["simple", "structured"]
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


class ObjectSpec(BaseModel):
    title_field: str | None = None
    fields: dict[str, FieldSpec] = Field(default_factory=dict)
    links: dict[str, LinkSpec] = Field(default_factory=dict)


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


class PolicySpec(BaseModel):
    defaults: list[PolicyRow] = Field(default_factory=list)
    fallback: str = "unfiled_card"


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


class DomainPack(BaseModel):
    root: Path
    manifest: PackManifest
    objects: dict[str, ObjectSpec]
    routing: RoutingSpec
    operations: dict[str, list[str]]
    policy: PolicySpec
    projections: ProjectionsSpec

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def version(self) -> str:
        return self.manifest.version
