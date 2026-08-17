"""Pydantic contract for wizard blueprint dictionaries.

The heuristic builder and the model-backed designer both produce the same
JSON-shaped blueprint.  Validate that shape before the renderer writes a pack
so malformed model output can never become an installed domain.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
Operation = Literal["create", "update", "correct", "delete"]

_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class _BlueprintPart(BaseModel):
    """Reject fields outside the documented blueprint shape."""

    model_config = ConfigDict(extra="forbid")


class FieldSpec(_BlueprintPart):
    type: FieldType
    required: bool = False
    default: str | None = None
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    values: list[str] | None = None
    allow_other: bool | None = None
    long: bool | None = None

    @model_validator(mode="after")
    def _enum_needs_values(self) -> FieldSpec:
        if self.type == "enum" and not self.values:
            raise ValueError("enum field requires values")
        if self.type != "enum" and self.values:
            raise ValueError("only enum fields may declare values")
        return self


class LinkRef(_BlueprintPart):
    to: str
    cardinality: str = "many_to_one"


class ObjectSpec(_BlueprintPart):
    title_field: str
    fields: dict[str, FieldSpec]
    operations: list[Operation] = Field(
        default_factory=lambda: ["create", "update", "correct", "delete"]
    )
    links: dict[str, LinkRef] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _title_field_exists(self) -> ObjectSpec:
        if self.title_field not in self.fields:
            raise ValueError(f"title_field {self.title_field!r} not in fields")
        for name in self.fields:
            if not _IDENT_RE.match(name):
                raise ValueError(f"bad field name {name!r}")
        return self


class RuleSpec(_BlueprintPart):
    match: str
    object: str
    confidence_boost: float = Field(default=0.1, ge=0.0, le=0.5)
    operation: Operation = "create"

    @field_validator("match")
    @classmethod
    def _compiles(cls, value: str) -> str:
        re.compile(value)
        return value


class ExampleSpec(_BlueprintPart):
    text: str
    object: str
    operation: Operation = "create"
    fields: dict[str, Any] | None = None


class ViewSpec(_BlueprintPart):
    id: str
    title: str
    block: str
    object: str
    config: dict[str, Any] = Field(default_factory=dict)


class QuestionSpec(_BlueprintPart):
    id: str
    prompt: str
    kind: Literal["choice", "yesno"]
    options: list[str]
    applies_to: str
    default: str


class PolicyRule(_BlueprintPart):
    operation: str
    min_confidence: float | None = None
    action: Literal["auto_apply", "confirm", "review"]


class PolicySpec(_BlueprintPart):
    defaults: list[PolicyRule]
    fallback: str = "unfiled_card"


class BlueprintModel(_BlueprintPart):
    """The complete dict consumed by ``wizard.blueprint.write_pack``."""

    archetype: str | None = None
    goal: str
    domain: str
    title: str
    description: str
    interpretation: Literal["simple", "structured"]
    icon: str
    markdown_folder: str
    objects: dict[str, ObjectSpec]
    rules: list[RuleSpec]
    examples: list[ExampleSpec] = Field(min_length=8)
    negatives: list[str] = Field(min_length=2)
    llm_hints: str = ""
    views: list[ViewSpec]
    unit_options: dict[str, list[str]] = Field(default_factory=dict)
    questions: list[QuestionSpec] = Field(default_factory=list, max_length=6)
    policy: PolicySpec
    agent: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None
    capabilities: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _cross_references(self) -> BlueprintModel:
        if not _SLUG_RE.match(self.domain):
            raise ValueError(f"domain {self.domain!r} is not a slug")
        if not self.objects:
            raise ValueError("at least one object required")
        for rule in self.rules:
            if rule.object not in self.objects:
                raise ValueError(f"rule targets unknown object {rule.object!r}")
        for example in self.examples:
            if example.object not in self.objects:
                raise ValueError(f"example targets unknown object {example.object!r}")
        for view in self.views:
            if view.object not in self.objects:
                raise ValueError(f"view {view.id!r} targets unknown object {view.object!r}")
        covered = {example.object for example in self.examples}
        if covered != set(self.objects):
            missing = set(self.objects) - covered
            raise ValueError(f"objects without examples: {missing}")
        return self


def validate_blueprint(blueprint: dict[str, Any]) -> dict[str, Any]:
    """Validate and return a JSON-serializable normalized blueprint dict."""

    # Omit optional ``None`` values: pack models use concrete booleans for
    # ``allow_other``/``long`` and apply their own defaults when those keys are
    # absent.
    return BlueprintModel.model_validate(blueprint).model_dump(
        mode="python", exclude_none=True
    )


__all__ = [
    "BlueprintModel",
    "ExampleSpec",
    "FieldSpec",
    "ObjectSpec",
    "PolicyRule",
    "PolicySpec",
    "QuestionSpec",
    "RuleSpec",
    "ViewSpec",
    "validate_blueprint",
]
