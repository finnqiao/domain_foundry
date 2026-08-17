"""Schema-driven extract + residue (hobby reliability extract gate)."""

from __future__ import annotations

import json
from pathlib import Path

from domain_foundry_core.extract import extract_fields
from domain_foundry_core.packs.loader import load_pack

REPO = Path(__file__).resolve().parents[2]


def _pack_dict(name: str) -> dict:
    pack = load_pack(REPO / "packs" / name, validate=True)
    return {
        "objects": {
            oname: {
                "title_field": obj.title_field,
                "fields": {
                    fname: f.model_dump() if hasattr(f, "model_dump") else dict(f)
                    for fname, f in obj.fields.items()
                },
            }
            for oname, obj in pack.objects.items()
        }
    }


def test_sourdough_country_loaf_hydration_not_flour_mix():
    pack = _pack_dict("sourdough")
    text = "baked a 75% hydration country loaf, bulk 5h, came out great"
    fields, residue = extract_fields(text, pack, "bake")
    assert fields.get("hydration") == 75
    assert fields.get("bulk_hours") == 5
    assert fields.get("result") == "great"
    assert "flour_mix" not in fields or fields.get("flour_mix") in (None, "")
    assert "country" in str(fields.get("loaf_name") or "").lower() or "loaf" in str(
        fields.get("loaf_name") or ""
    ).lower()
    assert isinstance(residue.get("residue"), dict)


def test_sourdough_rye_mix_lands_in_flour_mix():
    pack = _pack_dict("sourdough")
    text = "baked a boule with 20% rye, good oven spring"
    fields, _residue = extract_fields(text, pack, "bake")
    assert "rye" in str(fields.get("flour_mix") or "").lower()
    assert fields.get("result") == "good"


def test_plants_monstera_watering():
    pack = _pack_dict("plants")
    text = "watered the monstera, soil still damp"
    fields, _residue = extract_fields(text, pack, "care_event")
    assert fields.get("plant_name", "").lower() == "monstera"
    assert fields.get("action") == "water"
    assert fields.get("soil_moisture") == "damp"


def test_plants_fixtures_slot_fill():
    pack = _pack_dict("plants")
    path = REPO / "packs" / "plants" / "evals" / "fixtures.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        capture = (case.get("expected") or {}).get("captures") or [{}]
        obj = capture[0].get("object_type") or "care_event"
        expected_fields = capture[0].get("fields") or {}
        fields, _ = extract_fields(case["raw_text"], pack, obj)
        for key, expected in expected_fields.items():
            assert str(fields.get(key)).lower() == str(expected).lower(), (
                case["id"],
                key,
                fields,
            )


def test_unknown_fact_becomes_residue_not_wrong_slot():
    pack = _pack_dict("sourdough")
    text = "baked a country loaf with the dutch oven"
    fields, residue = extract_fields(text, pack, "bake")
    assert "dutch" not in str(fields.get("flour_mix") or "").lower()
    assert "dutch" not in str(fields.get("hydration") or "").lower()
    inner = residue.get("residue") or {}
    assert any("dutch" in str(v).lower() or "dutch" in k for k, v in inner.items()) or (
        "dutch" in str(residue.get("unparsed") or "").lower()
    )
