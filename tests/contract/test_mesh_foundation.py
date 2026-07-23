"""Mesh P1 foundation: journal survival, route→enqueue, serial-within-domain."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.ledger.migrate import ensure_migrated, read_schema_version
from domain_foundry_core.mesh.concierge import Concierge
from domain_foundry_core.mesh.expert import ExpertRunner
from domain_foundry_core.mesh.inbox import DomainInbox
from domain_foundry_core.mesh.journal import InboxJournal
from domain_foundry_core.mesh.supervisor import Supervisor
from domain_foundry_core.packs.loader import load_pack
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_ro

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def mesh_home(workspace: Workspace) -> Workspace:
    """Initialized workspace with japanese + food packs installed."""
    api = HarnessAPI(workspace.home)
    api.init()
    for name in ("japanese", "food"):
        api.pack_add(REPO / "packs" / name, force=True)
    return workspace


def test_mesh_migration_creates_tables(workspace: Workspace):
    version = ensure_migrated(workspace.ledger_db, "ledger")
    assert version >= 7
    assert read_schema_version(workspace.ledger_db) >= 7
    conn = connect_ro(workspace.ledger_db)
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "inbox_journal" in tables
        assert "domain_inbox" in tables
        assert "outbound_queue" in tables
        assert "domain_session" in tables
        assert "schedule_run" in tables
    finally:
        conn.close()


def test_journal_survives_without_routing(workspace: Workspace):
    """Kill-Concierge mid-flight invariant: message is durable after append."""
    journal = InboxJournal(workspace)
    record = journal.append(
        "学ぶ means to learn",
        channel="telegram",
        source_ref="tg-survival-1",
    )
    assert record.status == "pending"
    assert record.idempotent_replay is False

    # Simulate Concierge death: new client, same DB — row still there.
    journal2 = InboxJournal(workspace)
    pending = journal2.list_pending()
    assert len(pending) == 1
    assert pending[0].id == record.id
    assert pending[0].raw_text.startswith("学ぶ")

    replay = journal2.append(
        "ignored body",
        channel="telegram",
        source_ref="tg-survival-1",
    )
    assert replay.idempotent_replay is True
    assert replay.id == record.id
    assert journal2.counts().get("pending") == 1


def test_route_enqueue_marks_journal_routed(mesh_home: Workspace):
    concierge = Concierge(mesh_home)
    record = concierge.ingest(
        "新しい単語: 勉強 means study",
        channel="cli",
        source_ref="route-1",
    )
    assert record.status == "routed"
    assert record.routed_domain == "japanese"
    assert record.domain_inbox_id

    inbox = DomainInbox(mesh_home)
    msg = inbox.get(record.domain_inbox_id)
    assert msg is not None
    assert msg.domain == "japanese"
    assert msg.status == "pending"
    assert msg.payload["text"].startswith("新しい単語")

    depths = inbox.depth("japanese")
    assert depths.get("pending") == 1


def test_food_route_enqueue(mesh_home: Workspace):
    concierge = Concierge(mesh_home)
    record = concierge.ingest(
        "recipe idea: miso glazed eggplant with sesame",
        channel="cli",
        source_ref="food-1",
    )
    assert record.status == "routed"
    assert record.routed_domain == "food"


def test_expert_dequeue_capture_ack(mesh_home: Workspace):
    concierge = Concierge(mesh_home)
    record = concierge.ingest(
        "vocab: 食べる to eat",
        channel="mesh-test",
        source_ref="expert-1",
    )
    runner = ExpertRunner(domain="japanese", workspace=mesh_home)
    msg = runner.process_one()
    assert msg is not None
    assert msg.id == record.domain_inbox_id
    assert runner.stats.processed == 1

    done = DomainInbox(mesh_home).get(msg.id)
    assert done is not None
    assert done.status == "done"
    assert done.reply is not None
    assert done.reply.get("entry_id")


def test_serial_within_domain_concurrent_across(mesh_home: Workspace):
    """§8 invariant: serial within a domain; concurrent across domains."""
    concierge = Concierge(mesh_home)
    for i in range(3):
        concierge.ingest(
            f"日本語 vocab card {i}: word-{i}",
            channel="mesh-test",
            source_ref=f"jp-serial-{i}",
        )
    for i in range(2):
        concierge.ingest(
            f"recipe attempt {i}: dish-{i}",
            channel="mesh-test",
            source_ref=f"food-serial-{i}",
        )

    # Serial within domain: a claimed message stays processing; next claim is different.
    inbox = DomainInbox(mesh_home)
    first = inbox.claim_next("japanese")
    second = inbox.claim_next("japanese")
    assert first is not None and second is not None
    assert first.id != second.id
    assert first.status == "processing"
    assert second.status == "processing"
    # No third claim while two are processing — one pending remains.
    third = inbox.claim_next("japanese")
    assert third is not None  # third of three
    assert inbox.claim_next("japanese") is None
    for msg in (first, second, third):
        inbox.ack(msg.id, reply={"serial": True})

    # Concurrent across domains: japanese + food hooks overlap in wall time.
    jp_active = threading.Event()
    food_active = threading.Event()
    overlap = threading.Event()
    barrier = threading.Barrier(2)

    def jp_hook(domain: str, msg):  # noqa: ANN001
        jp_active.set()
        if food_active.is_set():
            overlap.set()
        barrier.wait(timeout=2)
        time.sleep(0.02)
        return {"ok": True, "domain": domain}

    def food_hook(domain: str, msg):  # noqa: ANN001
        food_active.set()
        if jp_active.is_set():
            overlap.set()
        barrier.wait(timeout=2)
        time.sleep(0.02)
        return {"ok": True, "domain": domain}

    jp = ExpertRunner(domain="japanese", workspace=mesh_home, process_hook=jp_hook)
    food = ExpertRunner(domain="food", workspace=mesh_home, process_hook=food_hook)
    # Re-enqueue one each for the concurrency probe.
    concierge.ingest("日本語 overlap probe", channel="mesh-test", source_ref="jp-ov")
    concierge.ingest("recipe overlap probe", channel="mesh-test", source_ref="food-ov")

    t1 = threading.Thread(target=lambda: jp.process_one(), daemon=True)
    t2 = threading.Thread(target=lambda: food.process_one(), daemon=True)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert not t1.is_alive() and not t2.is_alive()
    assert overlap.is_set(), "expected japanese and food experts to run concurrently"
    assert jp.stats.processed == 1 and food.stats.processed == 1


def test_supervisor_status_shape(mesh_home: Workspace):
    Concierge(mesh_home).ingest("quick jp note 漢字", channel="cli", source_ref="st-1")
    status = Supervisor(mesh_home).status()
    assert status.home == str(mesh_home.home)
    assert "routed" in status.journal or "pending" in status.journal
    assert any(c["domain"] == "japanese" for c in status.children)
    assert isinstance(status.outbound, dict)
    assert status.notes
    assert any("outbound_queue" in n for n in status.notes)


def test_agent_yaml_loads_for_japanese_and_food():
    for name in ("japanese", "food"):
        pack = load_pack(REPO / "packs" / name, validate=True)
        assert pack.agent is not None
        assert pack.agent.name == name
        assert pack.agent.persona
        assert "capture" in pack.agent.tools
        # sessions/schedules fields exist (may be empty for food)
        assert isinstance(pack.agent.sessions, list)
        assert isinstance(pack.agent.schedules, list)
    jp = load_pack(REPO / "packs" / "japanese", validate=True)
    assert jp.agent is not None
    assert any(s.id == "quiz" for s in jp.agent.sessions)
    assert any(s.id == "daily_review" for s in jp.agent.schedules)
