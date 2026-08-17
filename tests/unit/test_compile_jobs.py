"""compile_jobs forces catalog+event, gallery, map, and links for pokedex jobs."""

from __future__ import annotations

from domain_foundry_core.atlas.loader import load_atlas
from domain_foundry_core.packs.loader import load_pack
from domain_foundry_core.wizard.blueprint import write_pack
from domain_foundry_core.wizard.jobs import compile_jobs, shortlist_for_ideas


def test_pokedex_jobs_emit_catalog_gallery_map_and_link(tmp_path):
    graph = load_atlas()
    idea = graph.get("diving.marine_naturalism.species_pokedex")
    assert idea is not None
    shortlist = shortlist_for_ideas([idea], goal="remember the animals")
    blueprint = compile_jobs(
        shortlist,
        goal="remember the animals",
        jobs=list(idea.jobs),
        domain_hint="species",
    )
    assert len(blueprint["objects"]) >= 2
    views = {v["block"] for v in blueprint["views"]}
    assert "gallery" in views
    assert "map" in views
    linked = any(obj.get("links") for obj in blueprint["objects"].values())
    assert linked
    dest = write_pack(blueprint, tmp_path / "species")
    pack = load_pack(dest, validate=True)
    assert "photos" in (pack.capabilities.get("media") or {}) or pack.capabilities.get("media")
    assert any(obj.links for obj in pack.objects.values())
