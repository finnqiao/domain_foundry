from __future__ import annotations

from pathlib import Path

import pytest

from domain_foundry_core.packs.loader import PackValidationError, load_pack
from domain_foundry_core.packs.schema_compiler import compile_ddl, field_contract

REPO = Path(__file__).resolve().parents[2]

PHASE2_PACKS = ("japanese", "health", "dev", "food")
GEO_FIELDS = ("lat", "lng", "place_id", "place_name")
SM2_FIELDS = ("ease_factor", "interval_days", "reps", "lapses", "next_review")


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
