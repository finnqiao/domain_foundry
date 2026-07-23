"""Phase 3 / mesh P1 exit gates: HOL isolation timing + kill-9 journal survival.

Production exit narrative (plan): Food Expert busy ~30s; a japanese capture is
acked < 1s and applied concurrently. CI uses an injectable Food delay (~2–5s)
instead of a full 30s wall clock — same overlap invariant, suite stays fast.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.mesh.concierge import Concierge
from domain_foundry_core.mesh.expert import ExpertRunner
from domain_foundry_core.mesh.inbox import DomainInbox
from domain_foundry_core.mesh.journal import InboxJournal
from domain_foundry_core.paths import Workspace

REPO = Path(__file__).resolve().parents[2]

# Injectable stand-in for a long Food turn. Production exit cites ~30s; CI uses
# a short busy window so the suite stays under ~10s while still proving that
# japanese ack+apply overlap the Food busy interval (HOL isolation).
FOOD_BUSY_S = 2.5
JP_ACK_BUDGET_S = 1.0


@pytest.fixture
def mesh_home(workspace: Workspace) -> Workspace:
    api = HarnessAPI(workspace.home)
    api.init()
    for name in ("japanese", "food"):
        api.pack_add(REPO / "packs" / name, force=True)
    return workspace


def test_food_busy_japanese_ack_and_apply_concurrent(mesh_home: Workspace):
    """HOL exit: japanese acked+applied while Food Expert is still busy."""
    concierge = Concierge(mesh_home)
    food_rec = concierge.ingest(
        "recipe attempt: slow braise with miso glaze",
        channel="mesh-exit",
        source_ref="food-busy-1",
    )
    assert food_rec.routed_domain == "food"

    food_started = threading.Event()
    food_finished = threading.Event()
    jp_done_while_food_busy = threading.Event()
    food_errors: list[BaseException] = []

    def food_hook(domain: str, msg):  # noqa: ANN001
        assert domain == "food"
        food_started.set()
        time.sleep(FOOD_BUSY_S)
        food_finished.set()
        return {"ok": True, "busy_s": FOOD_BUSY_S, "msg_id": msg.id}

    food = ExpertRunner(domain="food", workspace=mesh_home, process_hook=food_hook)
    food_thread = threading.Thread(target=lambda: _run_food(food, food_errors), daemon=True)
    food_thread.start()
    assert food_started.wait(timeout=2.0), "Food Expert never became busy"

    # Concierge must not wait on Food — journal+route+enqueue is the "ack".
    t0 = time.monotonic()
    jp_rec = concierge.ingest(
        "新しい単語: 並行 means concurrent",
        channel="mesh-exit",
        source_ref="jp-during-food-1",
    )
    ack_elapsed = time.monotonic() - t0
    assert jp_rec.status == "routed"
    assert jp_rec.routed_domain == "japanese"
    assert ack_elapsed < JP_ACK_BUDGET_S, (
        f"japanese Concierge ack took {ack_elapsed:.3f}s (budget {JP_ACK_BUDGET_S}s); "
        "Food busy must not head-of-line block the Concierge"
    )
    assert not food_finished.is_set(), "Food finished before japanese ack — busy window too short"

    # Japanese Expert applies concurrently (real HarnessAPI capture, no slow hook).
    jp = ExpertRunner(domain="japanese", workspace=mesh_home)
    t1 = time.monotonic()
    jp_msg = jp.process_one()
    apply_elapsed = time.monotonic() - t1
    assert jp_msg is not None
    assert jp_msg.id == jp_rec.domain_inbox_id
    assert apply_elapsed < JP_ACK_BUDGET_S, (
        f"japanese Expert apply took {apply_elapsed:.3f}s (budget {JP_ACK_BUDGET_S}s)"
    )
    assert not food_finished.is_set(), "Food finished before japanese apply — no concurrency proof"
    jp_done_while_food_busy.set()

    done = DomainInbox(mesh_home).get(jp_msg.id)
    assert done is not None and done.status == "done"
    assert done.reply is not None and done.reply.get("entry_id")

    food_thread.join(timeout=FOOD_BUSY_S + 2.0)
    assert not food_thread.is_alive()
    assert not food_errors
    assert food.stats.processed == 1
    assert food_finished.is_set()
    assert jp_done_while_food_busy.is_set()
    assert jp.stats.processed == 1


def _run_food(runner: ExpertRunner, errors: list[BaseException]) -> None:
    try:
        runner.process_one()
    except BaseException as exc:  # noqa: BLE001 — surface to parent thread
        errors.append(exc)


def test_kill_concierge_mid_message_journal_survives_and_routes(mesh_home: Workspace):
    """kill -9 Concierge after journal append / before route → restart drains it."""
    # Append commits; omitting route simulates process death before route_one runs
    # (a real kill -9 would not execute mark_failed in route_one's except handler).
    dying = Concierge(mesh_home)
    record = dying.ingest(
        "学ぶ means to learn — kill-9 survival probe",
        channel="telegram",
        source_ref="tg-kill9-1",
        route=False,
    )
    assert record.status == "pending"
    assert record.idempotent_replay is False
    journal_id = record.id
    del dying  # Concierge process gone; durable state is SQLite only.

    journal = InboxJournal(mesh_home)
    pending = journal.list_pending()
    assert len(pending) == 1
    assert pending[0].id == journal_id
    assert DomainInbox(mesh_home).depth("japanese").get("pending", 0) == 0

    # Restart: fresh Concierge tails the journal and completes routing.
    restarted = Concierge(mesh_home)
    results = restarted.drain()
    assert len(results) == 1
    assert results[0].journal_id == journal_id
    assert results[0].domain == "japanese"

    routed = journal.get(journal_id)
    assert routed is not None
    assert routed.status == "routed"
    assert routed.routed_domain == "japanese"
    assert routed.domain_inbox_id == results[0].inbox_id

    # Message processes after restart (Expert drain).
    runner = ExpertRunner(domain="japanese", workspace=mesh_home)
    msg = runner.process_one()
    assert msg is not None
    assert msg.id == results[0].inbox_id
    assert runner.stats.processed == 1
    done = DomainInbox(mesh_home).get(msg.id)
    assert done is not None and done.status == "done"
    assert done.reply is not None and done.reply.get("entry_id")
