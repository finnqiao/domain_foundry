"""Phase 5 Concierge UX: stickiness, barge-in, not_mine, switch.

Each behavior is gated by ConciergeUXFlags / DOMAIN_FOUNDRY_MESH_* env vars.
The scripted conversation enables all four (defaults ON) and asserts the
full interleaving path from the mesh design §5.3.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.mesh.concierge import Concierge
from domain_foundry_core.mesh.expert import ExpertRunner
from domain_foundry_core.mesh.flags import (
    FLAG_BARGE_IN,
    FLAG_NOT_MINE,
    FLAG_STICKINESS,
    FLAG_SWITCH,
    ConciergeUXFlags,
)
from domain_foundry_core.mesh.inbox import DomainInbox, InboxMessage
from domain_foundry_core.mesh.sessions import DomainSessionStore
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_ro

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def ux_home(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    """japanese + food packs; all four UX flags ON (sensible test defaults)."""
    for flag in (FLAG_STICKINESS, FLAG_BARGE_IN, FLAG_NOT_MINE, FLAG_SWITCH):
        monkeypatch.setenv(flag, "1")
    api = HarnessAPI(workspace.home)
    api.init()
    for name in ("japanese", "food"):
        api.pack_add(REPO / "packs" / name, force=True)
    return workspace


def _route(concierge: Concierge, text: str, *, ref: str, actor: str = "u1"):
    record = concierge.ingest(
        text, channel="mesh-ux", source_ref=ref, actor=actor
    )
    # Re-read via a drain-style classify: route_one already ran.
    # Pull reason from the inbox payload.
    assert record.domain_inbox_id
    msg = DomainInbox(concierge.ws).get(record.domain_inbox_id)
    assert msg is not None
    return record, msg


def test_flags_default_sensible_for_tests(monkeypatch: pytest.MonkeyPatch):
    for flag in (FLAG_STICKINESS, FLAG_BARGE_IN, FLAG_NOT_MINE, FLAG_SWITCH):
        monkeypatch.delenv(flag, raising=False)
    flags = ConciergeUXFlags.from_env()
    assert flags.stickiness and flags.barge_in and flags.not_mine and flags.switch


def test_stickiness_flag_gates_ambiguous_followups(
    ux_home: Workspace, monkeypatch: pytest.MonkeyPatch
):
    sessions = DomainSessionStore(ux_home)
    sessions.start("japanese", "quiz", user_id="u1")

    monkeypatch.setenv(FLAG_STICKINESS, "0")
    off = Concierge(ux_home, flags=ConciergeUXFlags.from_env())
    _record, msg = _route(off, "B", ref="sticky-off-1")
    # Without stickiness, a bare "B" should not be forced to japanese.
    assert msg.payload.get("route_reason") != "sticky"

    monkeypatch.setenv(FLAG_STICKINESS, "1")
    on = Concierge(ux_home, flags=ConciergeUXFlags.from_env())
    # Bare Latin tokens stay ambiguous under L1 (unlike はい which may L1-hit japanese).
    record2, msg2 = _route(on, "ok", ref="sticky-on-1")
    assert record2.routed_domain == "japanese"
    assert msg2.payload.get("route_reason") == "sticky"


def test_scripted_conversation_all_four_ux_behaviors(ux_home: Workspace):
    """Exit gate: sticky → barge-in (session lives) → sticky → not_mine → switch."""
    flags = ConciergeUXFlags.from_env()
    assert flags.stickiness and flags.barge_in and flags.not_mine and flags.switch

    concierge = Concierge(ux_home, flags=flags)
    sessions = DomainSessionStore(ux_home)
    inbox = DomainInbox(ux_home)

    # --- Setup: active japanese quiz session (stickiness attractor) ---
    quiz = sessions.start(
        "japanese",
        "quiz",
        user_id="u1",
        state={"cards": ["水"], "index": 0},
    )
    assert quiz.status == "active"

    # 1) Stickiness: ambiguous follow-up sticks to japanese.
    r1, m1 = _route(concierge, "B", ref="ux-sticky-1")
    assert r1.routed_domain == "japanese"
    assert m1.payload["route_reason"] == "sticky"
    assert m1.payload["sticky_session_id"] == quiz.id

    sticky_after = sessions.get(quiz.id)
    assert sticky_after is not None and sticky_after.status == "active"

    # 2) Barge-in: high-confidence food hit overrides stickiness WITHOUT killing quiz.
    r2, m2 = _route(
        concierge,
        "recipe idea: miso glazed eggplant with sesame",
        ref="ux-barge-1",
    )
    assert r2.routed_domain == "food"
    assert m2.payload["route_reason"] == "barge_in"
    assert m2.payload["sticky_domain"] == "japanese"
    still = sessions.get(quiz.id)
    assert still is not None and still.status == "active"

    # Explicit marker barge-in also works.
    r2b, m2b = _route(concierge, "[food] leftover curry for lunch", ref="ux-barge-2")
    assert r2b.routed_domain == "food"
    assert m2b.payload["route_reason"] == "barge_in"
    assert sessions.get(quiz.id).status == "active"  # type: ignore[union-attr]

    # 3) Stickiness resumes: next ambiguous answer returns to japanese quiz.
    r3, m3 = _route(concierge, "next", ref="ux-sticky-2")
    assert r3.routed_domain == "japanese"
    assert m3.payload["route_reason"] == "sticky"

    # 4) not_mine: mis-route to japanese → Expert bounce → Concierge re-routes
    #    excluding bouncer → routing_correction + eval_case recorded.
    # Force a sticky route of food-ish prose into japanese by temporarily
    # classifying via stickiness (ambiguous JP chars), then bounce.
    # Use process_hook to bounce a deliberately sticky-routed message.
    r4, m4 = _route(concierge, "うん", ref="ux-notmine-seed")
    assert r4.routed_domain == "japanese"

    def bounce_hook(domain: str, msg: InboxMessage) -> dict:
        # Simulate Expert realizing this isn't a quiz answer / vocab.
        if "miso soup leftover" in str(msg.payload.get("text") or ""):
            return {"kind": "not_mine", "status": "not_mine", "domain": domain}
        return {
            "kind": "quiz_turn",
            "status": "ok",
            "domain": domain,
            "reply_text": "ok",
        }

    # Inject a message onto japanese that clearly belongs to food, then bounce.
    from domain_foundry_core.mesh.journal import InboxJournal

    journal = InboxJournal(ux_home)
    j = journal.append(
        "miso soup leftover from dinner",
        channel="mesh-ux",
        source_ref="ux-notmine-1",
        actor="u1",
    )
    # Sticky-attract into japanese (ambiguous-ish short food note without strong
    # recipe markers under sticky session) — enqueue directly as the mis-route.
    bad = inbox.enqueue(
        "japanese",
        journal_id=j.id,
        payload={
            "text": j.raw_text,
            "channel": "mesh-ux",
            "actor": "u1",
            "journal_id": j.id,
            "route_reason": "sticky",
            "sticky_session_id": quiz.id,
            "sticky_domain": "japanese",
        },
    )
    journal.mark_routed(j.id, domain="japanese", domain_inbox_id=bad.id)

    jp_expert = ExpertRunner(
        domain="japanese", workspace=ux_home, process_hook=bounce_hook, flags=flags
    )
    # Drain earlier sticky/quiz turns so we reach the deliberate mis-route.
    bounced = False
    for _ in range(20):
        processed = jp_expert.process_one()
        if processed is None:
            break
        if processed.id == bad.id:
            bounced = True
            assert jp_expert.stats.last_not_mine_correction_id
            assert jp_expert.stats.last_not_mine_reroute_domain == "food"
            break
    assert bounced, "not_mine mis-route was never processed by japanese Expert"

    # Locate the corrected food inbox row by journal_id (other food msgs may be pending).
    conn = connect_ro(ux_home.ledger_db)
    try:
        food_row = conn.execute(
            """
            SELECT id FROM domain_inbox
            WHERE journal_id = ? AND domain = 'food'
            ORDER BY enqueued_at DESC LIMIT 1
            """,
            (j.id,),
        ).fetchone()
        assert food_row is not None
        rerouted_id = food_row["id"]

        corr = conn.execute(
            "SELECT * FROM routing_correction WHERE journal_id = ?", (j.id,)
        ).fetchone()
        assert corr is not None
        assert corr["bounced_domain"] == "japanese"
        assert corr["routed_domain"] == "food"
        assert corr["reason_code"] == "not_mine"
        assert corr["eval_case_id"]
        ce = conn.execute(
            "SELECT * FROM correction_event WHERE reason_code = 'not_mine' "
            "AND target_id = ?",
            (j.id,),
        ).fetchone()
        assert ce is not None
        ev = conn.execute(
            "SELECT * FROM eval_case WHERE id = ?", (corr["eval_case_id"],)
        ).fetchone()
        assert ev is not None
        assert ev["source"] == "not_mine"
    finally:
        conn.close()

    # Process only the rerouted message: drain earlier barge-ins first.
    food_expert = ExpertRunner(domain="food", workspace=ux_home, flags=flags)
    found = False
    for _ in range(10):
        food_msg = food_expert.process_one()
        if food_msg is None:
            break
        if food_msg.id == rerouted_id:
            found = True
            done = inbox.get(food_msg.id)
            assert done is not None and done.status == "done"
            assert done.reply and done.reply.get("entry_id")
            break
    assert found, "rerouted food message was not processed"

    # Quiz session still alive through not_mine.
    assert sessions.get(quiz.id).status == "active"  # type: ignore[union-attr]

    # 5) Switch: force sticky domain to food; ambiguous follow-ups stick there.
    r5, m5 = _route(concierge, "switch to food", ref="ux-switch-1")
    assert r5.routed_domain == "food"
    assert m5.payload["route_reason"] == "switch"
    paused = sessions.get(quiz.id)
    assert paused is not None and paused.status == "paused"
    food_sticky = sessions.get_sticky(user_id="u1", ttl_s=flags.sticky_ttl_s)
    assert food_sticky is not None and food_sticky.domain == "food"

    r6, m6 = _route(concierge, "ok", ref="ux-switch-sticky")
    assert r6.routed_domain == "food"
    assert m6.payload["route_reason"] == "sticky"

    # Origin-tagged outbound still works (polish hook from Phase 3).
    out = food_expert.enqueue_reply(
        text="logged leftover soup",
        channel="mesh-ux",
        destination="u1",
    )
    assert out.prefixed_text().startswith("[food]")
