"""Mesh P2: SRS quiz skeleton — due-first queue + grade → review_event."""

from __future__ import annotations

from pathlib import Path

import pytest

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.ledger.migrate import ensure_migrated
from domain_foundry_core.mesh.expert import ExpertRunner
from domain_foundry_core.mesh.outbound import OutboundQueue
from domain_foundry_core.mesh.quiz import QuizSession
from domain_foundry_core.mesh.schedules import ScheduleRunStore
from domain_foundry_core.mesh.sessions import DomainSessionStore
from domain_foundry_core.packs.schema_compiler import table_name
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_ro, connect_rw

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def jp_home(workspace: Workspace) -> Workspace:
    api = HarnessAPI(workspace.home)
    api.init()
    api.pack_add(REPO / "packs" / "japanese", force=True)
    return workspace


def _seed_vocab(ws: Workspace, cards: list[dict]) -> list[str]:
    api = HarnessAPI(ws.home)
    api.packs.reload()
    api.packs.ensure_schemas_applied()
    uids: list[str] = []
    for card in cards:
        result = api.apply_operation(
            domain="japanese",
            operation="create",
            object_type="jp_vocab",
            fields=card,
            channel="test",
            actor="test",
        )
        assert result["ok"], result
        assert result["object_uid"]
        uids.append(result["object_uid"])
    return uids


def test_session_schedule_outbound_tables(jp_home: Workspace):
    ensure_migrated(jp_home.ledger_db, "ledger")
    sessions = DomainSessionStore(jp_home)
    s = sessions.start("japanese", "quiz", state={"cards": [], "index": 0})
    assert sessions.get_active("japanese", session_type="quiz") is not None
    sessions.save_state(s.id, {"cards": [], "index": 1, "correct": 0})
    sessions.complete(s.id)
    assert sessions.get_active("japanese", session_type="quiz") is None

    schedules = ScheduleRunStore(jp_home)
    run = schedules.record_fire(
        "japanese",
        "daily_review",
        next_due_at="2026-07-23T09:00:00Z",
        result={"ok": True},
    )
    assert run.fire_count == 1
    assert schedules.get("japanese", "daily_review") is not None

    outbound = OutboundQueue(jp_home)
    msg = outbound.enqueue(
        origin_domain="japanese",
        text="You have 3 cards due.",
        channel="telegram",
        destination="default",
    )
    assert msg.status == "pending"
    claimed = outbound.claim_batch(limit=10)
    assert len(claimed) == 1
    assert claimed[0].id == msg.id
    outbound.ack(msg.id)
    assert outbound.claim_batch(limit=10) == []


def test_due_first_queue_orders_due_before_new(jp_home: Workspace):
    # frozen_clock is 2026-07-16; seed one due, one future, two new.
    uids = _seed_vocab(
        jp_home,
        [
            {
                "word": "due_old",
                "meaning": "old due",
                "ease_factor": 2.5,
                "interval_days": 1,
                "reps": 1,
                "lapses": 0,
                "next_review": "2026-07-10",
            },
            {
                "word": "due_recent",
                "meaning": "recent due",
                "ease_factor": 2.5,
                "interval_days": 1,
                "reps": 1,
                "lapses": 0,
                "next_review": "2026-07-15",
            },
            {
                "word": "future",
                "meaning": "not due",
                "ease_factor": 2.5,
                "interval_days": 10,
                "reps": 3,
                "lapses": 0,
                "next_review": "2026-08-01",
            },
            {"word": "new_a", "meaning": "new a"},
            {"word": "new_b", "meaning": "new b"},
        ],
    )
    quiz = QuizSession(jp_home)
    queue = quiz.build_due_first_queue(include_grammar=False)
    prompts = [c.prompt for c in queue]
    assert prompts[:2] == ["due_old", "due_recent"]
    assert "future" not in prompts
    assert "new_a" in prompts and "new_b" in prompts
    assert all(c.due for c in queue[:2])
    assert uids  # seeded


def test_grade_writes_review_event_via_apply(jp_home: Workspace):
    _seed_vocab(
        jp_home,
        [
            {
                "word": "食べる",
                "meaning": "to eat",
                "ease_factor": 2.5,
                "interval_days": 0,
                "reps": 0,
            }
        ],
    )
    api = HarnessAPI(jp_home.home)
    started = api.quiz_start(limit=1, include_grammar=False)
    assert started["total"] == 1
    assert started["prompt"] == "食べる"

    graded = api.quiz_grade("good", session_id=started["session_id"])
    assert graded["done"] is True
    assert graded["review_event_uid"]
    assert graded["details"]["algorithm"] == "sm2"
    assert graded["details"]["next_interval_days"] == 1.0

    # Card updated
    tname = table_name("japanese", "jp_vocab")
    conn = connect_rw(jp_home.domains_db)
    try:
        row = conn.execute(
            f"SELECT reps, interval_days, ease_factor, next_review FROM {tname} WHERE object_uid = ?",
            (graded["card_uid"],),
        ).fetchone()
        assert int(row["reps"]) == 1
        assert float(row["interval_days"]) == 1.0
        assert float(row["ease_factor"]) == pytest.approx(2.5)
        assert row["next_review"] == "2026-07-17"  # frozen clock 2026-07-16 + 1d
    finally:
        conn.close()

    # review_event row present with algorithm=sm2
    ev_table = table_name("japanese", "review_event")
    conn = connect_ro(jp_home.domains_db)
    try:
        ev = conn.execute(
            f"SELECT grade, algorithm, next_interval_days FROM {ev_table} WHERE object_uid = ?",
            (graded["review_event_uid"],),
        ).fetchone()
        assert ev["grade"] == "good"
        assert ev["algorithm"] == "sm2"
        assert float(ev["next_interval_days"]) == 1.0
    finally:
        conn.close()


def test_again_hard_good_easy_handlers(jp_home: Workspace):
    _seed_vocab(
        jp_home,
        [
            {"word": f"w{i}", "meaning": f"m{i}"}
            for i in range(4)
        ],
    )
    api = HarnessAPI(jp_home.home)
    started = api.quiz_start(limit=4, include_grammar=False)
    sid = started["session_id"]
    for grade in ("again", "hard", "good", "easy"):
        receipt = api.quiz_grade(grade, session_id=sid)
        assert receipt["grade"] == grade
        assert receipt["review_event_uid"]
    assert receipt["done"] is True
    assert receipt["total"] == 4

    ev_table = table_name("japanese", "review_event")
    conn = connect_ro(jp_home.domains_db)
    try:
        grades = [
            r[0]
            for r in conn.execute(
                f"SELECT grade FROM {ev_table} ORDER BY id ASC"
            ).fetchall()
        ]
        assert grades == ["again", "hard", "good", "easy"]
        algos = {
            r[0]
            for r in conn.execute(f"SELECT algorithm FROM {ev_table}").fetchall()
        }
        assert algos == {"sm2"}
    finally:
        conn.close()


def test_schedule_stub_enqueues_outbound_and_starts_session(jp_home: Workspace):
    _seed_vocab(jp_home, [{"word": "朝", "meaning": "morning"}])
    quiz = QuizSession(jp_home)
    session, outbound_id = quiz.start_from_schedule("daily_review")
    assert session.status == "active"
    assert outbound_id
    run = ScheduleRunStore(jp_home).get("japanese", "daily_review")
    assert run is not None and run.fire_count == 1
    claimed = OutboundQueue(jp_home).claim_batch(limit=5)
    assert len(claimed) == 1
    assert claimed[0].id == outbound_id
    assert "cards due" in claimed[0].text.lower() or "Japanese" in claimed[0].text
    assert claimed[0].prefixed_text().startswith("[japanese]")


def test_expert_quiz_grade_path(jp_home: Workspace):
    _seed_vocab(jp_home, [{"word": "水", "meaning": "water"}])
    # Stickiness/barge-in is P5 — enqueue quiz turns directly onto the japanese
    # inbox (as Concierge will once sticky routing lands).
    from domain_foundry_core.mesh.inbox import DomainInbox
    from domain_foundry_core.mesh.journal import InboxJournal

    journal = InboxJournal(jp_home)
    inbox = DomainInbox(jp_home)
    runner = ExpertRunner(domain="japanese", workspace=jp_home)

    j1 = journal.append("quiz me on 1", channel="mesh-test", source_ref="qz-start", actor="u1")
    inbox.enqueue(
        "japanese",
        journal_id=j1.id,
        payload={"text": "quiz me on 1", "channel": "mesh-test", "actor": "u1"},
    )
    msg = runner.process_one()
    assert msg is not None
    done = runner.inbox.get(msg.id)
    assert done is not None and done.reply is not None
    assert done.reply.get("kind") == "quiz_start"
    assert done.reply.get("prompt") == "水"

    j2 = journal.append("good", channel="mesh-test", source_ref="qz-g1", actor="u1")
    inbox.enqueue(
        "japanese",
        journal_id=j2.id,
        payload={"text": "good", "channel": "mesh-test", "actor": "u1"},
    )
    msg2 = runner.process_one()
    assert msg2 is not None
    done2 = runner.inbox.get(msg2.id)
    assert done2 is not None and done2.reply is not None
    assert done2.reply.get("kind") == "quiz_grade"
    assert done2.reply.get("grade") == "good"
    assert done2.reply.get("review_event_uid")
    assert done2.reply.get("done") is True


def test_session_resume_after_restart(jp_home: Workspace):
    _seed_vocab(
        jp_home,
        [{"word": "一", "meaning": "1"}, {"word": "二", "meaning": "2"}],
    )
    api = HarnessAPI(jp_home.home)
    started = api.quiz_start(limit=2, include_grammar=False)
    api.quiz_grade("good", session_id=started["session_id"])

    # New API instance = Expert restart
    api2 = HarnessAPI(jp_home.home)
    nxt = api2.quiz_next()
    assert nxt["active"] is True
    assert nxt["prompt"] == "二"
    assert nxt["index"] == 1
