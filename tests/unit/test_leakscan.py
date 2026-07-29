from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from domain_foundry_core.packs.loader import discover_pack_dirs
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import ENV_PACKS_PATH, overlay_pack_dirs

REPO = Path(__file__).resolve().parents[2]


def _load_leakscan() -> Any:
    """Load the script as a module. Untyped by nature — it is exec'd
    from a path, so its constants (ROOT/CORE/ALLOWLIST) are not visible
    to a type checker. Returning Any documents that rather than hiding it."""
    script = REPO / "scripts" / "leakscan.py"
    spec = importlib.util.spec_from_file_location("leakscan", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _minimal_pack(dest: Path, name: str) -> Path:
    """Copy the template pack and rename it for overlay tests."""
    src = REPO / "packs" / "_template"
    shutil.copytree(src, dest)
    pack_yaml = dest / "pack.yaml"
    text = pack_yaml.read_text(encoding="utf-8")
    text = text.replace("name: example", f"name: {name}", 1)
    pack_yaml.write_text(text, encoding="utf-8")
    agent_yaml = dest / "agent.yaml"
    if agent_yaml.exists():
        agent_text = agent_yaml.read_text(encoding="utf-8")
        agent_text = agent_text.replace("name: example", f"name: {name}", 1)
        agent_yaml.write_text(agent_text, encoding="utf-8")
    return dest


def test_overlay_pack_dirs_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    catalog = tmp_path / "private_packs"
    pack = _minimal_pack(catalog / "private_demo", "private_demo")
    monkeypatch.setenv(ENV_PACKS_PATH, str(catalog))
    dirs = overlay_pack_dirs()
    assert dirs == [catalog.resolve()]
    found = discover_pack_dirs(dirs)
    assert pack.resolve() in found


def test_overlay_accepts_single_pack_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pack = _minimal_pack(tmp_path / "solo", "solo")
    monkeypatch.setenv(ENV_PACKS_PATH, str(pack))
    found = discover_pack_dirs(overlay_pack_dirs())
    assert found == [pack.resolve()]


def test_registry_loads_overlay_packs(
    workspace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    catalog = tmp_path / "overlay"
    _minimal_pack(catalog / "overlay_only", "overlay_only")
    monkeypatch.setenv(ENV_PACKS_PATH, str(catalog))
    reg = PackRegistry(workspace)
    pack = reg.get("overlay_only")
    assert pack is not None
    assert pack.root.parent == catalog.resolve()


def test_overlay_shadows_workspace_pack(
    workspace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    # Install template-as-plants into workspace, then overlay a different plants pack.
    from domain_foundry_core.packs.loader import install_pack

    install_pack(REPO / "packs" / "plants", workspace.packs_dir, force=True)
    overlay = tmp_path / "overlay"
    shadowed = _minimal_pack(overlay / "plants", "plants")
    # Keep enough routing examples for validate=True (template already has them).
    monkeypatch.setenv(ENV_PACKS_PATH, str(overlay))
    reg = PackRegistry(workspace)
    pack = reg.get("plants")
    assert pack is not None
    assert pack.root.resolve() == shadowed.resolve()


def test_leakscan_rejects_fake_sqlite(tmp_path: Path):
    """Guard the guard: a tracked sqlite must fail leakscan when present in a repo."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.check_call(["git", "init", "-b", "main"], cwd=repo)
    bad = repo / "secret.sqlite"
    bad.write_bytes(b"SQLite format 3\x00fake")
    subprocess.check_call(["git", "add", "secret.sqlite"], cwd=repo)

    ls = _load_leakscan()
    original = ls.ROOT
    try:
        ls.ROOT = repo
        errors = ls.scan()
    finally:
        ls.ROOT = original
    assert any("blocked database file" in e for e in errors)


def test_leakscan_catches_planted_fake_secret(tmp_path: Path):
    """Planted API-key shape outside allowlisted paths must fail the scan."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.check_call(["git", "init", "-b", "main"], cwd=repo)
    planted = repo / "notes" / "leak.txt"
    planted.parent.mkdir(parents=True)
    planted.write_text(
        "do not commit sk-abcdefghijklmnopqrstuvwxyz0123456789\n",
        encoding="utf-8",
    )
    subprocess.check_call(["git", "add", "notes/leak.txt"], cwd=repo)

    ls = _load_leakscan()
    original = ls.ROOT
    try:
        ls.ROOT = repo
        errors = ls.scan()
    finally:
        ls.ROOT = original
    assert any("pattern=api_key_shape" in e for e in errors)


def test_leakscan_clean_oss_tree_expectation():
    """The Domain Foundry working tree should be clean for personal-string heuristics."""
    ls = _load_leakscan()
    errors = ls.scan()
    assert errors == [], f"unexpected leakscan findings: {errors}"
