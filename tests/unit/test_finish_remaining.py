"""Weekly triage nudge + capture-time geo hints + x_radar pack."""

from __future__ import annotations

from pathlib import Path

from domain_foundry_core.geo.capture_hints import enrich_venue_fields, extract_place_hint
from domain_foundry_core.mesh.outbound import OutboundQueue
from domain_foundry_core.mesh.triage_nudge import maybe_fire_weekly_triage
from domain_foundry_core.packs.loader import load_pack
from domain_foundry_core.paths import Workspace

REPO = Path(__file__).resolve().parents[2]


def test_extract_place_hint_from_at_phrase():
    assert extract_place_hint("flat white at Onibus Nakameguro") == "Onibus Nakameguro"
    assert "River Station" in (extract_place_hint("dinner at River Station Grill, duck") or "")


def test_enrich_venue_fields_place_name_only_no_network():
    fields = enrich_venue_fields(
        object_type="dining",
        fields={},
        raw_text="dinner at River Station Grill",
        geocode=False,
    )
    assert fields.get("place_name") == "River Station Grill"
    assert fields.get("lat") is None


def test_x_radar_pack_loads():
    pack = load_pack(REPO / "packs" / "x_radar", validate=True)
    assert pack.name == "x_radar"
    assert set(pack.objects) >= {"signal", "person"}
    assert pack.agent is not None


def test_weekly_triage_idempotent(tmp_path: Path):
    from domain_foundry_core.api.harness import HarnessAPI

    home = tmp_path / "home"
    api = HarnessAPI(home)
    api.init()
    ws = Workspace(home)
    first = maybe_fire_weekly_triage(ws, force=True)
    assert first["fired"] is True
    second = maybe_fire_weekly_triage(ws, force=False)
    assert second["fired"] is False
    assert second["skipped_reason"] == "already_fired_this_week"
    pending = OutboundQueue(ws).depth()
    assert int(pending.get("pending", 0)) >= 1
