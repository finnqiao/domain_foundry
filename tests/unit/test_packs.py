from __future__ import annotations

from pathlib import Path

import pytest

from domain_foundry_core.packs.loader import PackValidationError, load_pack
from domain_foundry_core.packs.schema_compiler import compile_ddl, field_contract

REPO = Path(__file__).resolve().parents[2]

PHASE2_PACKS = ("japanese", "health", "dev", "food")
GEO_FIELDS = ("lat", "lng", "place_id", "place_name")
SM2_FIELDS = ("ease_factor", "interval_days", "reps", "lapses", "next_review", "learning_step")


def test_load_plants_and_sourdough():
    for name in ("plants", "sourdough"):
        pack = load_pack(REPO / "packs" / name, validate=True)
        assert pack.name == name
        assert len(pack.routing.examples) >= 8
        ddl = compile_ddl(pack)
        assert f"{name}__" in ddl
        contract = field_contract(pack)
        assert contract


def test_phase2_packs_load_and_compile():
    expected_objects = {
        "japanese": {"jp_vocab", "jp_grammar", "review_event"},
        "health": {"supplement", "medication", "fitness", "lab", "fasting"},
        "dev": {"decision", "gotcha", "session", "pattern"},
        "food": {
            "idea",
            "recipe",
            "cook",
            "dining",
            "observation",
            "coffee_note",
            "dining_note",
            "drink_note",
            "food_note",
            "recipe_attempt",
        },
    }
    for name in PHASE2_PACKS:
        pack = load_pack(REPO / "packs" / name, validate=True)
        assert pack.name == name
        assert set(pack.objects) == expected_objects[name]
        ddl = compile_ddl(pack)
        for obj in expected_objects[name]:
            assert f"{name}__{obj}" in ddl
        contract = field_contract(pack)
        assert set(contract) == expected_objects[name]


def test_japanese_sm2_and_review_event_fields():
    pack = load_pack(REPO / "packs" / "japanese", validate=True)
    for card in ("jp_vocab", "jp_grammar"):
        fields = pack.objects[card].fields
        for fname in SM2_FIELDS:
            assert fname in fields, f"{card} missing {fname}"
    review = pack.objects["review_event"].fields
    for fname in ("grade", "reviewed_at", "prev_interval_days", "next_interval_days", "algorithm"):
        assert fname in review
    # Routing must use correct 日本語 glyph; malformed 日语 only in negatives/docs
    blob = (REPO / "packs" / "japanese" / "routing.yaml").read_text(encoding="utf-8")
    assert "日本語" in blob
    assert "日语" in blob
    # Positive rules/examples must not use the bad glyph
    rules_and_examples = blob.split("negative_examples:")[0]
    assert "日语" not in rules_and_examples


def test_food_v2_parity_and_geo_fields():
    pack = load_pack(REPO / "packs" / "food", validate=True)
    for venue in ("dining", "coffee_note", "dining_note", "drink_note"):
        fields = pack.objects[venue].fields
        for fname in GEO_FIELDS:
            assert fname in fields, f"{venue} missing geo field {fname}"
            assert fields[fname].required is False
    recipe = pack.objects["recipe"].fields
    assert "lifecycle_stage" in recipe
    assert "ease_factor" not in recipe  # food must not grow SRS fields


def test_travel_pack_parity_lat_lng_and_event_log():
    pack = load_pack(REPO / "packs" / "travel", validate=True)
    assert set(pack.objects) >= {"trip", "timeline_item", "booking", "event_log"}
    trip = pack.objects["trip"].fields
    assert "slug" in trip
    assert "primary_destination" in trip
    assert "placeholder" in (trip["status"].values or [])
    item = pack.objects["timeline_item"].fields
    for fname in ("lat", "lng", "location_name", "trip_id", "item_type_canonical"):
        assert fname in item, f"timeline_item missing {fname}"
        assert item[fname].required is False
    assert item["lat"].type == "number"
    assert item["lng"].type == "number"
    event = pack.objects["event_log"].fields
    for fname in ("event_type", "event_json", "trip_id", "timeline_item_id", "noted_at", "created_by"):
        assert fname in event, f"event_log missing {fname}"
    assert "created_at" not in event  # substrate owns created_at/updated_at
    assert pack.agent is not None
    assert pack.agent.name == "travel"
    assert "capture" in pack.agent.tools
    ddl = compile_ddl(pack)
    assert "travel__event_log" in ddl
    assert "lat" in ddl and "lng" in ddl


def test_travel_ui_actions_and_checklist_view_are_declarative():
    pack = load_pack(REPO / "packs" / "travel", validate=True)
    actions = {
        (action.object_type, action.operation, tuple(action.fields))
        for action in pack.policy.ui_actions
    }
    assert ("packing_item", "update", ("packed",)) in actions
    assert ("booking", "update", ("status",)) in actions
    assert pack.policy.allows_ui_action(
        object_type="packing_item", operation="update", fields={"packed": True}
    )
    assert not pack.policy.allows_ui_action(
        object_type="packing_item",
        operation="update",
        fields={"packed": True, "notes": "not declared"},
    )
    assert not pack.policy.allows_ui_action(
        object_type="packing_item", operation="delete", fields={}
    )

    packing = next(view for view in pack.projections.app["views"] if view["id"] == "packing")
    assert packing["block"] == "list"
    assert packing["object"] == "packing_item"
    assert packing["config"]["group_by"] == "category"
    assert packing["config"]["actions"] == [
        {
            "id": "toggle-packed",
            "label": "Packed",
            "operation": "update",
            "fields": ["packed"],
            "field": "packed",
        }
    ]
    assert pack.projections.app["accent"] == "#2e6f95"


def test_phase3_agent_yaml_surface():
    for name in ("japanese", "food", "travel"):
        pack = load_pack(REPO / "packs" / name, validate=True)
        assert pack.agent is not None
        assert pack.agent.name == name
        assert pack.agent.tools
        assert isinstance(pack.agent.sessions, list)
        assert isinstance(pack.agent.schedules, list)


def test_japanese_interactive_sessions_schedules_for_expert():
    pack = load_pack(REPO / "packs" / "japanese", validate=True)
    assert pack.manifest.interpretation == "interactive"
    assert pack.agent is not None
    quiz = next(s for s in pack.agent.sessions if s.id == "quiz")
    assert "quiz_grade" in quiz.turn
    assert quiz.state.get("cards") == []
    daily = next(s for s in pack.agent.schedules if s.id == "daily_review")
    assert daily.cron == "0 9 * * *"
    assert "start_session(quiz)" in daily.action
    assert "quiz_grade" in pack.agent.tools
    assert pack.agent.autonomy.get("quiz") == "interactive"


def test_slice3_capabilities_are_declared_and_compatible():
    sourdough = load_pack(REPO / "packs" / "sourdough", validate=True)
    assert set(sourdough.capabilities) == {"derived_metrics", "media", "compare"}
    assert sourdough.compatibility.capabilities["derived_metrics"] == ">=1,<2"
    metric_ids = {
        metric["id"] for metric in sourdough.capabilities["derived_metrics"]["metrics"]
    }
    assert {"hydration_percent", "hydration_delta", "bulk_hours_delta"} <= metric_ids
    assert sourdough.capabilities["media"]["galleries"][0]["source"] == "capture_attachments"
    compare = sourdough.capabilities["compare"]["comparisons"][0]
    assert compare["object"] == "bake"
    assert set(compare["metrics"]) <= metric_ids
    assert {view["block"] for view in sourdough.projections.app["views"]} >= {
        "gallery",
        "compare",
    }
    assert set(sourdough.operations["bake"]) >= {"create", "update", "correct"}
    assert (REPO / "packs" / "sourdough" / "evals" / "fixtures.jsonl").is_file()

    japanese = load_pack(REPO / "packs" / "japanese", validate=True)
    assert {"imports", "sessions", "schedules"} <= set(japanese.capabilities)
    mapping = japanese.capabilities["imports"]["mappings"][0]
    assert mapping["id"] == "japanese_cards"
    assert {entity["object_type"] for entity in mapping["entities"]} == {
        "jp_vocab",
        "jp_grammar",
    }
    assert japanese.capabilities["schedules"]["missed_run_policy"] == "next_window"
    assert (REPO / "packs" / "japanese" / "evals" / "import_fixture").is_dir()


def test_unknown_or_new_capability_version_is_rejected(tmp_path: Path):
    import shutil

    src = REPO / "packs" / "sourdough"
    dest = tmp_path / "sourdough"
    shutil.copytree(src, dest)
    capabilities = dest / "capabilities.yaml"
    capabilities.write_text(
        capabilities.read_text(encoding="utf-8").replace("version: 1", "version: 2", 1),
        encoding="utf-8",
    )
    with pytest.raises(PackValidationError, match="newer than supported"):
        load_pack(dest, validate=True)


def test_template_fails_until_renamed_examples_ok():
    # template is valid as-is (≥8 examples)
    pack = load_pack(REPO / "packs" / "_template", validate=True)
    assert pack.name == "example"


def test_invalid_pack_too_few_examples(tmp_path: Path):
    src = REPO / "packs" / "_template"
    dest = tmp_path / "bad"
    import shutil

    shutil.copytree(src, dest)
    routing = dest / "routing.yaml"
    text = routing.read_text(encoding="utf-8")
    # wipe examples
    routing.write_text(
        "rules: []\nexamples:\n  - text: only one\n    expect: {}\nnegative_examples: []\n",
        encoding="utf-8",
    )
    with pytest.raises(PackValidationError):
        load_pack(dest, validate=True)
    _ = text
