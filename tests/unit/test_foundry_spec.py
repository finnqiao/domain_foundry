from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from domain_foundry_core.foundry.loader import DEFAULT_GOLDENS, load_foundry_spec, load_golden_specs
from domain_foundry_core.foundry.models import FoundrySpec


def test_foundry_spec_json_schema_exposes_the_full_product_contract() -> None:
    schema = FoundrySpec.model_json_schema()
    properties = schema["properties"]
    assert {
        "research",
        "evidence",
        "concepts",
        "remix",
        "domain",
        "experience",
        "implementation",
        "evaluation",
        "derivations",
    } <= properties.keys()


def test_foundry_spec_forbids_prompt_shaped_extra_fields() -> None:
    assert FoundrySpec.model_config.get("extra") == "forbid"


def test_three_golden_specs_are_deep_and_structurally_distinct() -> None:
    specs = load_golden_specs()
    assert {spec.id for spec in specs} == {
        "card-collector",
        "japanese-study-coach",
        "sourdough-lab",
    }

    assert len({spec.experience.visual_world.id for spec in specs}) == 3
    assert len({spec.experience.navigation.topology for spec in specs}) == 3
    assert len({spec.experience.navigation.primary_view for spec in specs}) == 3
    assert len({tuple(entity.id for entity in spec.domain.entities) for spec in specs}) == 3

    for spec in specs:
        assert len(spec.concepts) == 3
        assert len(spec.domain.entities) >= 6
        assert len(spec.domain.relationships) >= 5
        assert len(spec.domain.workloads) >= 4
        assert len(spec.experience.views) >= 4
        assert len(spec.evaluation.cases) >= 6
        assert any(item.startswith("DE-") for item in spec.principle_ids)
        assert any(item.startswith("UX-") for item in spec.principle_ids)
        assert any(item.startswith("SE-") for item in spec.principle_ids)


def test_golden_specs_do_not_use_generator_authored_evaluation_cases() -> None:
    for spec in load_golden_specs():
        assert {case.authored_by for case in spec.evaluation.cases} <= {
            "domain_expert",
            "user",
            "independent_reviewer",
            "standard",
        }


def test_build_local_source_snapshot_closes_an_external_reference(tmp_path: Path) -> None:
    raw = yaml.safe_load((DEFAULT_GOLDENS / "sourdough-lab.foundry.yaml").read_text())
    raw["source_ids"].append("external_bread_reference")
    raw["source_snapshots"] = [
        {
            "id": "external_bread_reference",
            "title": "Bread reference",
            "publisher": "Example publisher",
            "url": "https://example.com/bread",
            "kind": "product_reference",
            "tier": "product_reference",
            "license": "unknown-reference",
            "allowed_uses": ["reference_facts", "paraphrase"],
            "status": "reference_only",
            "retrieved_at": "2026-08-19",
            "freshness_days": 90,
            "topics": ["sourdough"],
        }
    ]
    path = tmp_path / "external.foundry.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    spec = load_foundry_spec(path)
    assert spec.source_snapshots[0].id == "external_bread_reference"


def test_foundry_spec_rejects_cosmetic_concept_variants() -> None:
    raw = yaml.safe_load((DEFAULT_GOLDENS / "sourdough-lab.foundry.yaml").read_text())
    base = raw["concepts"][0]
    for index, concept in enumerate(raw["concepts"]):
        concept["primary_loop"] = base["primary_loop"]
        concept["primary_affordance"] = base["primary_affordance"]
        concept["workflow_ids"] = base["workflow_ids"]
        concept["title"] = f"Cosmetic variant {index}"

    with pytest.raises(ValidationError, match="concepts must differ"):
        FoundrySpec.model_validate(raw)


def test_foundry_spec_rejects_an_action_the_runtime_cannot_execute() -> None:
    raw = yaml.safe_load((DEFAULT_GOLDENS / "sourdough-lab.foundry.yaml").read_text())
    raw["experience"]["views"][0]["actions"][0]["operation"] = "magic_prediction"

    with pytest.raises(ValidationError, match="create.*update.*correct.*reveal"):
        FoundrySpec.model_validate(raw)


def test_view_contract_cannot_reach_an_undeclared_entity_or_workload() -> None:
    raw = yaml.safe_load((DEFAULT_GOLDENS / "sourdough-lab.foundry.yaml").read_text())
    raw["experience"]["views"][0]["actions"][0]["entity"] = "recipe"

    with pytest.raises(ValidationError, match="entity outside its view"):
        FoundrySpec.model_validate(raw)

    raw = yaml.safe_load((DEFAULT_GOLDENS / "sourdough-lab.foundry.yaml").read_text())
    raw["experience"]["views"][0]["regions"][0]["workload_id"] = "w_plan_bake"

    with pytest.raises(ValidationError, match="workload outside its view"):
        FoundrySpec.model_validate(raw)
