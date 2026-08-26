"""Phase 8 / mesh P4 — wizard scaffolds agent.yaml + Expert hot-register."""

from __future__ import annotations

from pathlib import Path

import yaml
from tests.conftest import land_wizard

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.mesh.supervisor import Supervisor
from domain_foundry_core.packs.loader import load_pack
from domain_foundry_core.packs.models import AgentSpec
from domain_foundry_core.wizard.blueprint import build_agent_spec, build_blueprint, write_pack

REPO = Path(__file__).resolve().parents[2]


def test_blueprint_emits_agent_yaml(tmp_path):
    bp = build_blueprint("I want to track my sourdough journey")
    assert "agent" in bp
    agent = AgentSpec.model_validate(bp["agent"])
    assert agent.name == "sourdough"
    assert "capture" in agent.tools
    assert agent.autonomy.get("capture") == "auto"
    assert agent.sessions == []
    assert agent.schedules == []

    dest = write_pack(bp, tmp_path / "sourdough")
    agent_path = dest / "agent.yaml"
    assert agent_path.is_file()
    raw = yaml.safe_load(agent_path.read_text(encoding="utf-8"))
    assert "agent" in raw
    loaded = load_pack(dest, validate=True)
    assert loaded.agent is not None
    assert loaded.agent.name == "sourdough"


def test_wizard_creates_pack_and_agent_yaml(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()

    turn = land_wizard(api, "keep a coffee brewing log")
    assert turn["state"] == "test_drive", turn.get("message")

    name = turn["pack"]["name"]
    pack = api.packs.get(name)
    assert pack is not None
    assert pack.agent is not None
    assert pack.agent.name == name
    assert (pack.root / "agent.yaml").is_file()
    # Hobby turns omit expert stub; mesh still has the registration.
    assert "expert" not in turn
    registered = Supervisor(workspace).list_registered()
    assert name in registered


def test_activate_pack_registers_expert(workspace, monkeypatch):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()

    for name in ("plants", "sourdough", "health", "dev"):
        out = api.activate_pack(name)
        assert out["name"] == name
        assert out["agent"]["name"] == name
        assert out["expert"]["registered"] == "config_only"
        pack = api.packs.get(name)
        assert pack is not None and pack.agent is not None

    registered = Supervisor(workspace).list_registered()
    for name in ("plants", "sourdough", "health", "dev"):
        assert name in registered

    # CLI-equivalent harness hook.
    again = api.register_expert("plants")
    assert again["registered"] == "config_only"


def test_bundled_remaining_domains_have_agent_yaml():
    for name in ("plants", "sourdough", "health", "dev"):
        pack = load_pack(REPO / "packs" / name, validate=True)
        assert pack.agent is not None, name
        AgentSpec.model_validate(pack.agent.model_dump())


def test_dive_log_wizard_path_produces_pack_and_agent(workspace, monkeypatch):
    """Exit gate: 'create a dive-log domain' → pack + agent.yaml (+ Expert register)."""
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()

    turn = land_wizard(api, "create a dive-log domain")
    assert turn["state"] == "test_drive"
    domain = turn["proposal"]["domain"]
    assert "dive" in domain

    assert turn["dry_run"]["accuracy"] >= 0.95

    name = turn["pack"]["name"]
    pack = api.packs.get(name)
    assert pack is not None
    assert pack.agent is not None
    assert (pack.root / "agent.yaml").is_file()
    assert "expert" not in turn
    assert name in Supervisor(workspace).list_registered()
    assert build_agent_spec({"domain": name, "title": name, "description": "x"})["name"] == name


def test_register_expert_is_honest_about_process_state(workspace, monkeypatch):
    """Blocker #5: registration must not read as success-running."""
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    out = api.activate_pack("sourdough")
    expert = out["expert"]
    assert expert["registered"] == "config_only"
    assert expert["running"] is False
    assert "NOT running" in expert["note"]
    assert expert["launchd"] == "stubbed"
