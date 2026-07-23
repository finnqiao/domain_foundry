"""Phase 2 vault re-projection: unmanaged bytes must stay identical."""

from __future__ import annotations

from pathlib import Path

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.llm.provider import HeuristicProvider
from domain_foundry_core.paths import Workspace
from domain_foundry_core.projections.markdown import (
    content_managed_section,
    merge_managed_markdown,
    preview_managed_write,
    unmanaged_preserved,
    unmanaged_text,
    write_managed_note,
)
from domain_foundry_core.projections.reproject import HERMES_FOLDER_MAP, VaultReprojector
from domain_foundry_core.routing.router import Router


def _ready(workspace: Workspace) -> HarnessAPI:
    api = HarnessAPI(workspace.home)
    api.init()
    api.packs.activate_bundled("sourdough")
    api.router = Router(workspace, registry=api.packs, llm=HeuristicProvider())
    return api


def test_unmanaged_text_strips_only_managed_regions():
    free = "USER HEADER\n\n"
    managed = content_managed_section("bake:X", "# Loaf\n- H: 70%", object_uid="X")
    free2 = "\n\nMY FOOTER\n"
    full = free + managed + free2
    assert unmanaged_text(full) == free + free2
    assert "%%managed" not in unmanaged_text(full)
    assert "MY FOOTER" in unmanaged_text(full)


def test_preview_managed_write_unmanaged_invariant():
    existing = (
        "KEEP ME\n\n"
        + content_managed_section("bake:A", "# A v1", object_uid="A")
        + "\n\nALSO KEEP\n"
    )
    rendered = content_managed_section("bake:A", "# A v2\n- Hydration: 80%", object_uid="A")
    preview = preview_managed_write(existing, rendered)
    assert preview["unmanaged_unchanged"] is True
    assert preview["content_changed"] is True
    assert preview["unmanaged_before"] == unmanaged_text(existing)
    assert "KEEP ME" in preview["merged"]
    assert "ALSO KEEP" in preview["merged"]
    assert "# A v2" in preview["merged"]
    assert "# A v1" not in preview["merged"]


def test_reproject_dry_run_then_apply_preserves_unmanaged(workspace: Workspace, tmp_path: Path):
    api = _ready(workspace)
    receipt = api.capture(
        "baked a 75% hydration country loaf, bulk 5h, came out great",
        channel="cli",
        source_ref="reproj-1",
    )
    assert receipt.status == "applied"

    vault = tmp_path / "obsidian_vault"
    # Pre-seed a note path that will receive managed content, with free-zone text.
    # Folder follows pack default "Sourdough" (not in Hermes map).
    seed_dir = vault / "Sourdough" / "bake"
    seed_dir.mkdir(parents=True)
    # Discover the planned slug by dry-running first against empty vault.
    dry = VaultReprojector(
        workspace,
        vault=vault,
        registry=api.packs,
        folder_map={},  # keep pack folder "Sourdough"
        domains=["sourdough"],
    ).run(apply=False)
    assert dry.unmanaged_ok
    assert dry.dry_run is True
    assert dry.applied is False
    creates = [n for n in dry.notes if n.would_create]
    assert creates, "expected at least one planned note"

    # Seed free-zone text into the first planned path, then re-run.
    target_rel = creates[0].rel_path
    target = vault / target_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "MY PRIVATE TASTING NOTES\n\ndo not touch\n",
        encoding="utf-8",
    )
    seed_text = target.read_text(encoding="utf-8")

    dry2 = VaultReprojector(
        workspace,
        vault=vault,
        registry=api.packs,
        folder_map={},
        domains=["sourdough"],
    ).run(apply=False)
    hit = next(n for n in dry2.notes if n.rel_path == target_rel)
    assert hit.unmanaged_unchanged is True
    assert hit.action == "update"

    applied = VaultReprojector(
        workspace,
        vault=vault,
        registry=api.packs,
        folder_map={},
        domains=["sourdough"],
    ).run(apply=True)
    assert applied.applied is True
    assert applied.unmanaged_ok
    final = target.read_text(encoding="utf-8")
    assert unmanaged_preserved(seed_text, final)
    assert "%%managed:start" in final
    assert "MY PRIVATE TASTING NOTES" in final
    assert f"[[entry:{receipt.entry_id}]]" in final


def test_hermes_folder_map_used_for_convergence_packs():
    assert HERMES_FOLDER_MAP["japanese"] == "06_Japanese"
    assert HERMES_FOLDER_MAP["food"] == "05_Food_Drink"
    assert HERMES_FOLDER_MAP["health"] == "07_Health"
    assert HERMES_FOLDER_MAP["dev"] == "12_Dev"


def test_merge_roundtrip_unmanaged_bytes_identical():
    """Contract: any managed re-render leaves unmanaged bytes byte-identical."""
    free_a = "α-header\nline2\n"
    free_b = "\nβ-footer café\n"
    v1 = content_managed_section("obj:1", "body v1", object_uid="1")
    v2 = content_managed_section("obj:1", "body v2\nmore", object_uid="1")
    existing = free_a + v1 + free_b
    merged = merge_managed_markdown(existing, v2)
    assert unmanaged_text(merged) == unmanaged_text(existing) == free_a + free_b
