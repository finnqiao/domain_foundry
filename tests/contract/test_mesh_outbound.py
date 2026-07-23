"""Durable outbound_queue: survival across restart + retry backoff + origin tags."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.clock import set_clock
from domain_foundry_core.ledger.migrate import ensure_migrated, read_schema_version
from domain_foundry_core.mesh.concierge import Concierge
from domain_foundry_core.mesh.expert import ExpertRunner
from domain_foundry_core.mesh.outbound import (
    OutboundQueue,
    backoff_seconds,
    domain_prefix,
)
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_ro

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def mesh_home(workspace: Workspace) -> Workspace:
    api = HarnessAPI(workspace.home)
    api.init()
    for name in ("japanese", "food"):
        api.pack_add(REPO / "packs" / name, force=True)
    return workspace


def test_outbound_migration_creates_table(workspace: Workspace):
    version = ensure_migrated(workspace.ledger_db, "ledger")
    assert version >= 6
    assert read_schema_version(workspace.ledger_db) >= 6
    conn = connect_ro(workspace.ledger_db)
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(outbound_queue)").fetchall()
        }
    finally:
        conn.close()
    assert "outbound_queue" in tables
    assert {
        "id",
        "origin_domain",
        "payload_json",
        "status",
        "attempts",
        "next_attempt_at",
        "created_at",
    }.issubset(cols)


def test_outbound_survives_process_restart(workspace: Workspace):
    """Enqueue in one client; new process (new OutboundQueue) still sees it."""
    q1 = OutboundQueue(workspace)
    msg = q1.enqueue(
        origin_domain="japanese",
        text="Due: 学ぶ",
        channel="telegram",
        destination="chat-42",
    )
    assert msg.status == "pending"
    assert msg.attempts == 0

    # Simulate process restart: drop the client, open a fresh one on same DB.
    del q1
    q2 = OutboundQueue(workspace)
    surviving = q2.get(msg.id)
    assert surviving is not None
    assert surviving.text == "Due: 学ぶ"
    assert surviving.origin_domain == "japanese"
    assert surviving.status == "pending"

    claimed = q2.claim_batch(limit=5)
    assert len(claimed) == 1
    assert claimed[0].id == msg.id
    assert claimed[0].status == "delivering"
    assert claimed[0].attempts == 1
    assert claimed[0].prefixed_text() == "[japanese] Due: 学ぶ"

    q2.ack(claimed[0].id)
    done = q2.get(msg.id)
    assert done is not None
    assert done.status == "delivered"
    assert q2.claim_batch() == []


def test_outbound_fail_retries_with_backoff(workspace: Workspace, frozen_clock):
    q = OutboundQueue(workspace, max_attempts=3, backoff_base_s=10.0)
    msg = q.enqueue(
        origin_domain="food",
        text="Logged shoyu ramen",
        channel="telegram",
        destination="chat-7",
    )
    batch = q.claim_batch()
    assert len(batch) == 1
    assert batch[0].prefixed_text() == "[food] Logged shoyu ramen"

    failed = q.fail(batch[0].id, "telegram 429")
    assert failed is not None
    assert failed.status == "pending"
    assert failed.attempts == 1
    assert failed.last_error == "telegram 429"
    # attempts=1 → 10s backoff; still frozen at T0 → not claimable yet
    assert backoff_seconds(1, base_s=10.0) == 10.0
    assert q.claim_batch() == []

    # Advance past next_attempt_at.
    later = frozen_clock + timedelta(seconds=11)
    set_clock(lambda: later)
    retry = q.claim_batch()
    assert len(retry) == 1
    assert retry[0].id == msg.id
    assert retry[0].attempts == 2

    q.fail(retry[0].id, "still flaky")
    # attempts=2 → 20s from `later`
    assert q.claim_batch() == []
    even_later = later + timedelta(seconds=21)
    set_clock(lambda: even_later)
    third = q.claim_batch()
    assert len(third) == 1
    assert third[0].attempts == 3

    dead = q.fail(third[0].id, "give up")
    assert dead is not None
    assert dead.status == "dead"
    set_clock(lambda: even_later + timedelta(hours=1))
    assert q.claim_batch() == []


def test_expert_and_concierge_enqueue_origin_tags(mesh_home: Workspace):
    concierge = Concierge(mesh_home)
    jp = concierge.enqueue_reply(
        origin_domain="japanese",
        text="Quiz: 何？",
        channel="telegram",
        destination="tg-1",
    )
    food = concierge.enqueue_reply(
        origin_domain="food",
        text="Got it — too salty.",
        channel="telegram",
        destination="tg-1",
    )
    assert jp.prefixed_text().startswith("[japanese]")
    assert food.prefixed_text().startswith("[food]")
    assert domain_prefix("japanese") == "[japanese]"

    # Expert path: process_hook returns outbound_text → durable enqueue.
    record = concierge.ingest(
        "新しい単語: 勉強 means study",
        channel="telegram",
        source_ref="out-expert-1",
        actor="tg-user-9",
    )
    assert record.routed_domain == "japanese"

    def hook(domain, msg):
        return {
            "status": "ok",
            "outbound_text": f"Captured in {domain}",
            "destination": "tg-user-9",
        }

    expert = ExpertRunner("japanese", mesh_home, process_hook=hook)
    processed = expert.process_one()
    assert processed is not None
    assert expert.stats.last_outbound_id is not None

    q = OutboundQueue(mesh_home)
    out = q.get(expert.stats.last_outbound_id)
    assert out is not None
    assert out.origin_domain == "japanese"
    assert out.prefixed_text() == "[japanese] Captured in japanese"
    assert out.destination == "tg-user-9"

    # Direct Expert.enqueue_reply for proactive/scheduler use.
    nudge = expert.enqueue_reply(
        text="3 cards due",
        channel="telegram",
        destination="tg-user-9",
    )
    assert nudge.prefixed_text() == "[japanese] 3 cards due"
