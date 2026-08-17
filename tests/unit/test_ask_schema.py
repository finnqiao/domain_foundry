"""Ask plans are closed over the installed pack catalog."""

import pytest

from domain_foundry_core.ask.schema import AskAggregate, AskPlan, AskPlanError, validate_plan


@pytest.fixture
def catalog():
    return {
        "sourdough": {
            "bake": {"hydration": "number", "loaf_name": "text"},
            "starter": {"name": "text"},
        },
        "plants": {"care_event": {"days": "integer"}},
    }


def test_rejects_unknown_references(catalog):
    with pytest.raises(AskPlanError):
        validate_plan(AskPlan(intent="list", domain="unknown"), catalog)
    with pytest.raises(AskPlanError):
        validate_plan(
            AskPlan(intent="list", domain="sourdough", object_type="nope"), catalog
        )


def test_rejects_invalid_aggregates(catalog):
    with pytest.raises(AskPlanError):
        validate_plan(
            AskPlan(
                intent="aggregate",
                domain="sourdough",
                object_type="bake",
                aggregate=AskAggregate(op="avg", field="loaf_name"),
            ),
            catalog,
        )
    with pytest.raises(AskPlanError):
        validate_plan(AskPlan(intent="aggregate", aggregate=AskAggregate(op="count")), catalog)


def test_accepts_and_resolves_valid_plans(catalog):
    plan = validate_plan(
        AskPlan(
            intent="aggregate",
            domain="sourdough",
            object_type="bake",
            aggregate=AskAggregate(op="avg", field="hydration"),
        ),
        catalog,
    )
    assert plan.domain == "sourdough"

    unique = validate_plan(AskPlan(intent="list", object_type="care_event"), catalog)
    assert unique.domain == "plants"
