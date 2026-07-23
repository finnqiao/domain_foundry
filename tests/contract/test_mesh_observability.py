"""Phase 8 mesh observability: DLQ list/retry + queue-depth Concierge alerts."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from domain_foundry_core.api.app import create_app
from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.mesh.concierge import Concierge
from domain_foundry_core.mesh.expert import ExpertRunner
from domain_foundry_core.mesh.flags import MeshObservabilityFlags
from domain_foundry_core.mesh.inbox import DomainInbox
from domain_foundry_core.mesh.observability import (
    ALERT_KIND_QUEUE_DEPTH,
    DeadLetterQueue,
    MeshObservability,
)
from domain_foundry_core.mesh.outbound import OutboundQueue
from domain_foundry_core.mesh.supervisor import Supervisor
from domain_foundry_core.paths import Workspace

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def mesh_home(workspace: Workspace) -> Workspace:
    api = HarnessAPI(workspace.home)
    api.init()
    for name in ("japanese", "food"):
        api.pack_add(REPO / "packs" / name, force=True)
    return workspace


def test_inbox_poison_lands_in_dlq_and_retries(mesh_home: Workspace):
    concierge = Concierge(mesh_home)
    record = concierge.ingest(
        "新しい単語: 毒 means poison",
        channel="cli",
        source_ref="dlq-poison-1",
    )
    assert record.domain_inbox_id

    def boom(domain, msg):  # noqa: ANN001, ARG001
        raise RuntimeError("simulated poison")

    expert = ExpertRunner("japanese", mesh_home, process_hook=boom)
    with pytest.raises(RuntimeError, match="simulated poison"):
        expert.process_one()

    inbox = DomainInbox(mesh_home)
    dead = inbox.get(record.domain_inbox_id)
    assert dead is not None
    assert dead.status == "dead"
    assert dead.error and "poison" in dead.error

    dlq = DeadLetterQueue(mesh_home)
    listed = dlq.list(domain="japanese", queue="inbox")
    assert any(e.id == dead.id and e.queue == "inbox" for e in listed)

    retried = dlq.retry(dead.id)
    assert retried is not None
    assert retried.status == "pending"
    assert retried.queue == "inbox"

    refreshed = inbox.get(dead.id)
    assert refreshed is not None
    assert refreshed.status == "pending"
    assert refreshed.error is None

    # Second pass succeeds after retry.
    ok = ExpertRunner(
        "japanese",
        mesh_home,
        process_hook=lambda d, m: {"status": "ok", "domain": d},
    )
    processed = ok.process_one()
    assert processed is not None
    assert processed.id == dead.id
    assert inbox.get(dead.id).status == "done"  # type: ignore[union-attr]


def test_outbound_dead_list_and_retry(workspace: Workspace):
    HarnessAPI(workspace.home).init()
    q = OutboundQueue(workspace, max_attempts=1)
    msg = q.enqueue(
        origin_domain="food",
        text="delivery probe",
        channel="telegram",
        destination="chat-dlq",
    )
    claimed = q.claim_batch()
    assert len(claimed) == 1
    dead = q.fail(claimed[0].id, "permanent fail")
    assert dead is not None
    assert dead.status == "dead"

    dlq = DeadLetterQueue(workspace)
    listed = dlq.list(queue="outbound")
    assert any(e.id == msg.id and e.queue == "outbound" for e in listed)

    retried = dlq.retry(msg.id)
    assert retried is not None
    assert retried.status == "pending"
    assert retried.attempts == 0

    batch = q.claim_batch()
    assert len(batch) == 1
    assert batch[0].id == msg.id


def test_mesh_status_includes_health_enrichment(mesh_home: Workspace):
    concierge = Concierge(mesh_home)
    concierge.ingest("漢字 health probe", channel="cli", source_ref="health-1")
    ExpertRunner(
        "japanese",
        mesh_home,
        process_hook=lambda d, m: {"status": "ok"},
    ).process_one()

    status = Supervisor(mesh_home).status()
    assert "japanese" in status.domains or status.inbox_by_domain
    assert "inbox_pending" in status.queue_depths
    assert "outbound_dead" in status.dlq or "inbox_dead" in status.dlq
    jp_child = next(c for c in status.children if c["domain"] == "japanese")
    assert "last_processed_at" in jp_child
    assert "error_rate" in jp_child
    assert jp_child["last_processed_at"] is not None
    assert jp_child["error_rate"] == 0.0

    api = HarnessAPI(mesh_home.home)
    payload = api.mesh_status()
    assert payload["queue_depths"]["inbox_pending"] >= 0
    assert "domains" in payload


def test_queue_depth_alert_enqueues_when_flag_on(mesh_home: Workspace):
    concierge = Concierge(mesh_home)
    # Enqueue enough pending japanese messages to breach a low threshold.
    for i in range(3):
        concierge.ingest(
            f"新しい単語: card-{i}",
            channel="cli",
            source_ref=f"depth-{i}",
        )

    flags = MeshObservabilityFlags(
        depth_alert=True,
        depth_alert_threshold=2,
        depth_alert_channel="telegram",
        depth_alert_destination="ops-chat",
    )
    obs = MeshObservability(mesh_home, flags=flags)
    first = obs.maybe_enqueue_depth_alert()
    assert len(first) == 1
    alert = first[0]
    assert alert.status == "pending"
    assert "queue depth alert" in alert.text
    assert alert.destination == "ops-chat"
    assert alert.payload is not None
    assert alert.payload.get("alert_kind") == ALERT_KIND_QUEUE_DEPTH
    assert alert.payload.get("alert_domain") == "japanese"
    assert int(alert.payload.get("pending_depth") or 0) >= 2

    # Dedup: second check while alert still pending does not enqueue again.
    second = obs.maybe_enqueue_depth_alert()
    assert second == []

    # Flag off → quiet.
    quiet = MeshObservability(
        mesh_home, flags=MeshObservabilityFlags(depth_alert=False, depth_alert_threshold=1)
    )
    assert quiet.maybe_enqueue_depth_alert() == []

    # Harness helper path.
    api = HarnessAPI(mesh_home.home)
    # Ack the pending alert so a fresh one can fire via harness.
    OutboundQueue(mesh_home).ack(alert.id)
    via_api = api.mesh_check_depth_alerts(flags=flags)
    assert len(via_api) == 1
    assert "queue depth alert" in via_api[0]["text"]


def test_mesh_read_only_api_endpoints(mesh_home: Workspace):
    concierge = Concierge(mesh_home)
    record = concierge.ingest(
        "新しい単語: API",
        channel="cli",
        source_ref="api-dlq-1",
    )

    def boom(domain, msg):  # noqa: ANN001, ARG001
        raise RuntimeError("api poison")

    with pytest.raises(RuntimeError):
        ExpertRunner("japanese", mesh_home, process_hook=boom).process_one()

    client = TestClient(create_app(mesh_home.home, enable_drain_loop=False))
    status = client.get("/api/mesh/status")
    assert status.status_code == 200
    body = status.json()
    assert "queue_depths" in body
    assert "domains" in body

    dlq = client.get("/api/mesh/dlq", params={"queue": "inbox", "domain": "japanese"})
    assert dlq.status_code == 200
    entries = dlq.json()["entries"]
    assert any(e["id"] == record.domain_inbox_id for e in entries)

    listed = HarnessAPI(mesh_home.home).mesh_dlq_list(queue="inbox")
    assert any(e["id"] == record.domain_inbox_id for e in listed["entries"])
    retried = HarnessAPI(mesh_home.home).mesh_dlq_retry(record.domain_inbox_id)  # type: ignore[arg-type]
    assert retried.get("status") == "pending"
