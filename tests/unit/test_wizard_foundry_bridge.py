"""ADR-010: the FoundrySpec → ShortlistModel projection, and its one-way import.

Every spec the repository ships — three hand-authored goldens and five showcase
builds — must project into a shortlist the existing wizard runtime accepts. That
is a stronger gate than a hand-written fixture: the goldens were written before
the bridge existed, so nothing about them was shaped to make this pass.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from domain_foundry_core.foundry.loader import load_foundry_spec, load_golden_specs
from domain_foundry_core.foundry.models import FoundrySpec
from domain_foundry_core.wizard.bridge import choose_objects, spec_to_shortlist
from domain_foundry_core.wizard.shortlist import (
    RULE_TERM_CAP,
    ShortlistModel,
    compile_shortlist,
    generic_shape_warnings,
    lint_shortlist,
    rule_terms_for_object,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SHOWCASE = REPO_ROOT / "examples" / "showcase"
FOUNDRY_PACKAGE = REPO_ROOT / "core" / "domain_foundry_core" / "foundry"


def _showcase_specs() -> list[FoundrySpec]:
    return [load_foundry_spec(path) for path in sorted(SHOWCASE.glob("*/spec.yaml"))]


def _all_specs() -> list[FoundrySpec]:
    return [*load_golden_specs(), *_showcase_specs()]


def _spec_ids() -> list[str]:
    return [spec.id for spec in _all_specs()]


def _by_id(spec_id: str) -> FoundrySpec:
    return next(spec for spec in _all_specs() if spec.id == spec_id)


def _rule_terms(shortlist: ShortlistModel, obj: str) -> list[str]:
    examples_by_obj: dict[str, list[str]] = {name: [] for name in shortlist.objects}
    fields_by_obj: dict[str, list[object]] = {name: [] for name in shortlist.objects}
    for example in shortlist.examples:
        examples_by_obj.setdefault(example.object, []).append(example.text)
        for value in (example.fields or {}).values():
            if isinstance(value, str) and value.strip():
                fields_by_obj.setdefault(example.object, []).append(value.strip())
    return rule_terms_for_object(
        shortlist,
        obj,
        primary=shortlist.objects[0],
        examples_by_obj=examples_by_obj,
        fields_by_obj=fields_by_obj,
    )


# --------------------------------------------------------------------------- #
# The import direction
# --------------------------------------------------------------------------- #


def test_foundry_never_imports_wizard() -> None:
    """The coupling is one-way, and this is the only thing that keeps it so.

    ``wizard`` may import ``foundry``: the wizard escalates into the pipeline.
    The reverse would make the pipeline unusable on its own and would close a
    cycle through two packages that both define a spec model.
    """
    offenders: list[str] = []
    for path in sorted(FOUNDRY_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if "wizard" in name.split("."):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} → {name}")
    assert not offenders, "foundry must never import wizard: " + "; ".join(offenders)


# --------------------------------------------------------------------------- #
# The projection, against every spec in the repository
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("spec_id", _spec_ids())
def test_every_shipped_spec_projects_to_a_clean_shortlist(spec_id: str) -> None:
    spec = _by_id(spec_id)
    shortlist = spec_to_shortlist(spec)

    warnings: list[str] = []
    errors = lint_shortlist(shortlist, goal=spec.research.interest, warnings=warnings)
    assert errors == [], f"{spec_id}: {errors}"
    assert warnings == [], f"{spec_id}: {warnings}"


@pytest.mark.parametrize("spec_id", _spec_ids())
def test_no_projection_produces_the_generic_shape_warning(spec_id: str) -> None:
    """The failure this whole projection exists to avoid.

    A pack whose routing rule is only its own object and domain name knows no
    word its owner would type, and its first real sentence will not route.
    """
    shortlist = spec_to_shortlist(_by_id(spec_id))
    shaped = [
        warning
        for warning in generic_shape_warnings(shortlist)
        if "no interest vocabulary" in warning
    ]
    assert shaped == [], f"{spec_id}: {shaped}"


@pytest.mark.parametrize("spec_id", _spec_ids())
def test_projection_compiles_through_the_existing_blueprint_gate(spec_id: str) -> None:
    """Nothing about the runtime changed, so the existing compiler must accept it."""
    spec = _by_id(spec_id)
    blueprint = compile_shortlist(spec_to_shortlist(spec), goal=spec.research.interest)

    assert list(blueprint["objects"]) == spec_to_shortlist(spec).objects
    assert len(blueprint["examples"]) >= 8
    assert {example["object"] for example in blueprint["examples"]} == set(blueprint["objects"])
    for rule in blueprint["rules"]:
        assert rule["object"] in blueprint["objects"]


@pytest.mark.parametrize("spec_id", _spec_ids())
def test_projection_is_deterministic(spec_id: str) -> None:
    spec = _by_id(spec_id)
    assert spec_to_shortlist(spec).model_dump() == spec_to_shortlist(spec).model_dump()


@pytest.mark.parametrize("spec_id", _spec_ids())
def test_shortlist_respects_the_runtime_budgets(spec_id: str) -> None:
    shortlist = spec_to_shortlist(_by_id(spec_id))

    assert 1 <= len(shortlist.objects) <= 3
    assert 3 <= len(shortlist.fields) <= 16
    for obj in shortlist.objects:
        fields = [field for field in shortlist.fields if field.object == obj]
        assert 0 < len(fields) <= 8, obj
        assert len([f for f in fields if f.role == "identity"]) == 1, obj
        # Rule slots are a budget; blowing past the cap silently drops the tail.
        assert len(_rule_terms(shortlist, obj)) >= 3, obj


# --------------------------------------------------------------------------- #
# Real domain vocabulary, not the shape of the wizard
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("spec_id", "expected"),
    [
        ("sourdough-lab", {"hydration", "levain", "crumb", "flour"}),
        ("lifting-log", {"squat", "5x5", "deload", "rpe"}),
        ("whisky-tasting", {"peat", "dram", "iodine", "neat"}),
        ("ham-radio", {"qso", "ft8", "lotw", "20m"}),
        ("aquarium-tank", {"nitrite", "nitrate", "cycling", "ammonia"}),
        ("lego-builds", {"moc", "piece", "millennium", "falcon"}),
        ("card-collector", {"purchase", "condition", "grade", "printing"}),
        ("japanese-study-coach", {"recognition", "prompt", "reading", "expression"}),
    ],
)
def test_projection_carries_the_interest_s_own_words(spec_id: str, expected: set[str]) -> None:
    """A projection that lost the jargon would still lint clean and be useless."""
    shortlist = spec_to_shortlist(_by_id(spec_id))
    vocabulary = {term.lower() for term in [*shortlist.jargon, *shortlist.vocabulary]}
    missing = expected - vocabulary
    assert not missing, f"{spec_id} lost {sorted(missing)}; kept {sorted(vocabulary)}"


def test_jargon_is_not_flooded_with_record_keys_and_timestamps() -> None:
    """Synthetic record ids are the machine's strings, not the owner's words."""
    for spec in _all_specs():
        for term in spec_to_shortlist(spec).jargon:
            assert "://" not in term, f"{spec.id}: {term}"
            assert not term.count("-") >= 2 or not any(
                chunk.isdigit() and len(chunk) >= 4 for chunk in term.split("-")
            ), f"{spec.id}: {term} looks like a record id"


def test_primary_object_follows_the_spec_s_own_routing_expectation() -> None:
    """Where a spec says which object a sentence lands in, the projection agrees."""
    assert choose_objects(_by_id("lifting-log"))[0].id == "set_entry"
    assert choose_objects(_by_id("whisky-tasting"))[0].id == "dram"
    assert choose_objects(_by_id("ham-radio"))[0].id == "qso"
    assert choose_objects(_by_id("lego-builds"))[0].id == "build_project"


def test_event_entity_wins_when_no_routing_case_names_one() -> None:
    """ADR-010's default: the event entity is usually what gets logged."""
    primary = choose_objects(_by_id("sourdough-lab"))[0]
    assert primary.id == "feeding"
    assert primary.kind == "event"


def test_routing_cases_become_verbatim_examples() -> None:
    spec = _by_id("lifting-log")
    shortlist = spec_to_shortlist(spec)
    texts = {example.text for example in shortlist.examples}
    for case in spec.evaluation.cases:
        if case.kind == "routing":
            assert case.input in texts


def test_foreign_keys_and_ordering_columns_are_not_projected_as_vocabulary() -> None:
    """``session_id`` on a set is wiring; ``load_kg`` is what the owner types."""
    shortlist = spec_to_shortlist(_by_id("lifting-log"))
    names = {field.name for field in shortlist.fields if field.object == "set_entry"}

    assert "session_id" not in names
    assert "exercise_id" not in names
    assert "order_index" not in names
    assert {"load_kg", "reps"} <= names


def test_units_and_enum_values_survive_the_projection() -> None:
    shortlist = spec_to_shortlist(_by_id("sourdough-lab"))
    by_name = {field.name: field for field in shortlist.fields}

    assert by_name["flour_mass_g"].unit == "g"
    assert by_name["flour_mass_g"].role == "measure"
    status = by_name["status"]
    assert status.type == "enum"
    assert status.values and "reviewed" in status.values


def test_only_one_when_field_per_object_so_nothing_else_becomes_required() -> None:
    """``compile_shortlist`` makes every when-field required with a default.

    A spec entity carries several timestamps — ``target_bake_at`` alongside
    ``baked_at`` — and projecting them all would make a bake unfileable without
    filling in dates the owner does not have yet.
    """
    for spec in _all_specs():
        shortlist = spec_to_shortlist(spec)
        for obj in shortlist.objects:
            whens = [
                field
                for field in shortlist.fields
                if field.object == obj and (field.role == "when" or field.type == "datetime")
            ]
            assert len(whens) <= 1, f"{spec.id}.{obj}: {[f.name for f in whens]}"


def test_rule_terms_stay_inside_the_bounded_budget_for_the_primary_object() -> None:
    """The cap is a budget: everything past it is silently dropped."""
    for spec in _all_specs():
        shortlist = spec_to_shortlist(spec)
        primary = shortlist.objects[0]
        head = _rule_terms(shortlist, primary)[:RULE_TERM_CAP]
        # Whatever else it spends slots on, the interest's own words come first.
        assert any(term.lower() in {j.lower() for j in shortlist.jargon} for term in head), spec.id
