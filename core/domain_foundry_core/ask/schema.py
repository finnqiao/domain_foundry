"""Validated plans for the read-only Ask pipeline.

The planner may produce only this closed vocabulary. Execution compiles it to
the existing parameterized search, object-row, and aggregate read surfaces;
models never receive a SQL interface.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class AskTimeRange(BaseModel):
    since: str | None = None
    until: str | None = None


class AskAggregate(BaseModel):
    op: Literal["count", "sum", "avg", "min", "max"]
    field: str | None = None


class AskPlan(BaseModel):
    intent: Literal["lookup", "list", "aggregate"]
    domain: str | None = None
    object_type: str | None = None
    text_query: str | None = None
    time_range: AskTimeRange | None = None
    aggregate: AskAggregate | None = None
    limit: int = Field(default=20, ge=1, le=100)

    @field_validator("text_query")
    @classmethod
    def _trim(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None


class AskPlanError(ValueError):
    """A model plan is malformed or references data outside the live catalog."""


# {domain: {object_type: {field_name: field_type}}}
Catalog = dict[str, dict[str, dict[str, str]]]


def build_catalog(registry: Any) -> Catalog:
    """Build the planner allow-list from the installed pack schemas."""
    catalog: Catalog = {}
    for pack in registry.list():
        catalog[pack.name] = {
            object_name: {
                field_name: (field_spec.type or "text")
                for field_name, field_spec in obj.fields.items()
            }
            for object_name, obj in pack.objects.items()
        }
    return catalog


_NUMERIC_TYPES = {"number", "integer"}


def validate_plan(plan: AskPlan, catalog: Catalog) -> AskPlan:
    """Validate all schema references and resolve a unique object owner."""
    if plan.domain is not None and plan.domain not in catalog:
        raise AskPlanError(f"unknown domain {plan.domain!r}")

    if plan.object_type is not None:
        if plan.domain is None:
            owners = [
                domain
                for domain, objects in catalog.items()
                if plan.object_type in objects
            ]
            if len(owners) != 1:
                raise AskPlanError(
                    f"object_type {plan.object_type!r} needs a domain"
                )
            plan = plan.model_copy(update={"domain": owners[0]})
        elif plan.object_type not in catalog[plan.domain]:
            raise AskPlanError(
                f"unknown object_type {plan.object_type!r} in {plan.domain!r}"
            )

    if plan.aggregate is not None:
        if plan.intent != "aggregate":
            raise AskPlanError("aggregate requires intent=aggregate")
        if plan.domain is None or plan.object_type is None:
            raise AskPlanError("aggregate requires domain and object_type")
        aggregate = plan.aggregate
        if aggregate.op != "count":
            fields = catalog[plan.domain][plan.object_type]
            if not aggregate.field or aggregate.field not in fields:
                raise AskPlanError(f"unknown aggregate field {aggregate.field!r}")
            if fields[aggregate.field] not in _NUMERIC_TYPES:
                raise AskPlanError(
                    f"{aggregate.field!r} is not numeric ({fields[aggregate.field]})"
                )

    if plan.intent == "aggregate" and plan.aggregate is None:
        raise AskPlanError("intent=aggregate requires an aggregate spec")
    return plan
