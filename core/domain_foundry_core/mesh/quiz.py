"""Japanese quiz session — due-first queue, new-card rate, SM-2 grades.

Anki-parity mechanics: learning-aware SM-2 scheduler, configurable new-card
introduction rate, daily schedule evaluator, and review_event writes through
the HarnessAPI apply path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from domain_foundry_core.apply.engine import ApplyEngine, OperationSpec
from domain_foundry_core.clock import now, today_utc
from domain_foundry_core.mesh.outbound import OutboundQueue
from domain_foundry_core.mesh.schedules import ScheduleEvaluator, ScheduleRunStore
from domain_foundry_core.mesh.sessions import DomainSession, DomainSessionStore
from domain_foundry_core.mesh.srs import (
    GRADES,
    CardState,
    Grade,
    Scheduler,
    SM2Scheduler,
    card_state_from_row,
)
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.packs.schema_compiler import table_name
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_ro, connect_rw

GRADE_ALIASES: dict[str, Grade] = {
    "again": "again",
    "a": "again",
    "1": "again",
    "hard": "hard",
    "h": "hard",
    "2": "hard",
    "good": "good",
    "g": "good",
    "3": "good",
    "easy": "easy",
    "e": "easy",
    "4": "easy",
}

_QUIZ_START_RE = re.compile(
    r"^\s*(quiz(?:\s+me)?(?:\s+on\s+\d+)?|start\s+quiz|/quiz)\b",
    re.IGNORECASE,
)

DEFAULT_NEW_CARD_LIMIT = 20


@dataclass(frozen=True)
class QuizCard:
    object_uid: str
    object_type: str  # jp_vocab | jp_grammar
    prompt: str
    answer: str | None
    due: bool
    state: CardState


@dataclass
class GradeReceipt:
    session_id: str
    card_uid: str
    grade: Grade
    review_event_uid: str | None
    card_updated: bool
    done: bool
    next_card: QuizCard | None
    correct: int
    index: int
    total: int
    details: dict[str, Any]


def new_card_limit_from_pack(registry: PackRegistry, domain: str = "japanese") -> int:
    """Read ``new_card_limit`` from agent.yaml quiz session enter actions."""
    pack = registry.get(domain)
    if pack is None or pack.agent is None:
        return DEFAULT_NEW_CARD_LIMIT
    for session in pack.agent.sessions:
        if session.id != "quiz":
            continue
        for step in session.enter:
            if step.get("action") == "build_due_first_queue":
                raw = step.get("new_card_limit")
                if raw is not None:
                    return max(0, int(raw))
    return DEFAULT_NEW_CARD_LIMIT


class QuizSession:
    """Due-first SRS quiz over japanese jp_vocab (+ optional jp_grammar)."""

    SESSION_TYPE = "quiz"
    DOMAIN = "japanese"
    CARD_TYPES = ("jp_vocab", "jp_grammar")

    def __init__(
        self,
        workspace: Workspace | None = None,
        *,
        scheduler: Scheduler | None = None,
        registry: PackRegistry | None = None,
        new_card_limit: int | None = None,
    ) -> None:
        self.ws = workspace or Workspace()
        self.scheduler = scheduler or SM2Scheduler()
        self.registry = registry or PackRegistry(self.ws)
        self.engine = ApplyEngine(self.ws, registry=self.registry)
        self.sessions = DomainSessionStore(self.ws)
        self.schedules = ScheduleRunStore(self.ws)
        self.outbound = OutboundQueue(self.ws)
        self.new_card_limit = (
            DEFAULT_NEW_CARD_LIMIT if new_card_limit is None else max(0, int(new_card_limit))
        )
        if new_card_limit is None:
            self.new_card_limit = new_card_limit_from_pack(self.registry, self.DOMAIN)

    # ------------------------------------------------------------------ start

    def start(
        self,
        *,
        user_id: str = "default",
        limit: int | None = None,
        include_grammar: bool = True,
        filter_text: str | None = None,
        new_card_limit: int | None = None,
    ) -> DomainSession:
        """Open a quiz session with a due-first card queue."""
        rate = self.new_card_limit if new_card_limit is None else max(0, int(new_card_limit))
        cards = self.build_due_first_queue(
            limit=limit,
            include_grammar=include_grammar,
            filter_text=filter_text,
            new_card_limit=rate,
        )
        due_n = sum(1 for c in cards if c.due)
        new_n = len(cards) - due_n
        state = {
            "cards": [
                {
                    "object_uid": c.object_uid,
                    "object_type": c.object_type,
                    "prompt": c.prompt,
                    "answer": c.answer,
                    "due": c.due,
                }
                for c in cards
            ],
            "index": 0,
            "correct": 0,
            "grades": [],
            "filter_text": filter_text,
            "new_card_limit": rate,
            "due_count": due_n,
            "new_count": new_n,
        }
        session = self.sessions.start(
            self.DOMAIN,
            self.SESSION_TYPE,
            user_id=user_id,
            state=state,
        )
        return session

    def start_from_schedule(
        self,
        schedule_id: str = "daily_review",
        *,
        user_id: str = "default",
        channel: str = "telegram",
        at: datetime | None = None,
    ) -> tuple[DomainSession | None, str | None, dict[str, Any]]:
        """Evaluate daily schedule idempotently; enqueue outbound quiz prompt on fire."""
        evaluator = ScheduleEvaluator(self.ws, registry=self.registry)
        results = evaluator.evaluate_domain(
            self.DOMAIN,
            at=at,
            fire=True,
            user_id=user_id,
            channel=channel,
        )
        match = next((r for r in results if r.schedule_id == schedule_id), None)
        if match is None:
            return None, None, {"fired": False, "skipped_reason": "no_schedule"}
        info = {
            "fired": match.fired,
            "skipped_reason": match.skipped_reason,
            "window_id": match.window_id,
            "next_due_at": match.next_due_at,
            "result": match.result,
        }
        if not match.fired or not match.result:
            return None, None, info
        session_id = match.result.get("session_id")
        outbound_id = match.result.get("outbound_id")
        session = self.sessions.get(session_id) if session_id else None
        return session, outbound_id, info

    # ------------------------------------------------------------------ queue

    def build_due_first_queue(
        self,
        *,
        limit: int | None = None,
        include_grammar: bool = True,
        filter_text: str | None = None,
        as_of: str | None = None,
        new_card_limit: int | None = None,
    ) -> list[QuizCard]:
        """Due reviews first (oldest next_review), then new cards (rate-capped)."""
        as_of = as_of or today_utc()
        rate = self.new_card_limit if new_card_limit is None else max(0, int(new_card_limit))
        types = self.CARD_TYPES if include_grammar else ("jp_vocab",)
        due: list[QuizCard] = []
        new: list[QuizCard] = []
        conn = connect_ro(self.ws.domains_db)
        try:
            for otype in types:
                tname = table_name(self.DOMAIN, otype)
                # Table may not exist yet if pack schema not applied.
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (tname,),
                ).fetchone()
                if not exists:
                    continue
                title_col = "word" if otype == "jp_vocab" else "form"
                meaning_col = "meaning"
                rows = conn.execute(
                    f"""
                    SELECT *
                    FROM {tname}
                    WHERE tombstoned = 0
                    ORDER BY id ASC
                    """
                ).fetchall()
                for row in rows:
                    data = dict(row)
                    prompt = str(data.get(title_col) or "")
                    answer = data.get(meaning_col)
                    if filter_text and filter_text.lower() not in prompt.lower() and (
                        not answer or filter_text.lower() not in str(answer).lower()
                    ):
                        continue
                    state = card_state_from_row(data)
                    is_due = bool(state.next_review and state.next_review <= as_of)
                    is_new = (
                        state.reps == 0
                        and not state.next_review
                        and not state.last_reviewed
                        and not is_due
                    )
                    card = QuizCard(
                        object_uid=str(data["object_uid"]),
                        object_type=otype,
                        prompt=prompt,
                        answer=str(answer) if answer is not None else None,
                        due=is_due,
                        state=state,
                    )
                    if is_due:
                        due.append(card)
                    elif is_new:
                        new.append(card)
        finally:
            conn.close()

        due.sort(key=lambda c: (c.state.next_review or "", c.object_uid))
        queue = due + new[:rate]
        if limit is not None:
            queue = queue[: max(0, int(limit))]
        return queue

    # ------------------------------------------------------------------ grade

    def current_card(self, session: DomainSession | None = None, *, user_id: str = "default") -> QuizCard | None:
        session = session or self.sessions.get_active(
            self.DOMAIN, user_id=user_id, session_type=self.SESSION_TYPE
        )
        if session is None:
            return None
        cards = session.state.get("cards") or []
        index = int(session.state.get("index") or 0)
        if index >= len(cards):
            return None
        meta = cards[index]
        row = self._load_card_row(str(meta["object_type"]), str(meta["object_uid"]))
        state = card_state_from_row(row) if row else CardState()
        return QuizCard(
            object_uid=str(meta["object_uid"]),
            object_type=str(meta["object_type"]),
            prompt=str(meta.get("prompt") or ""),
            answer=meta.get("answer"),
            due=bool(meta.get("due")),
            state=state,
        )

    def grade(
        self,
        grade: Grade | str,
        *,
        session_id: str | None = None,
        user_id: str = "default",
        at: datetime | None = None,
    ) -> GradeReceipt:
        """Grade the current card: SM-2 → update card + append review_event via apply."""
        parsed = parse_grade(grade)
        session = (
            self.sessions.get(session_id)
            if session_id
            else self.sessions.get_active(
                self.DOMAIN, user_id=user_id, session_type=self.SESSION_TYPE
            )
        )
        if session is None:
            raise RuntimeError("no active quiz session")
        if session.status != "active":
            raise RuntimeError(f"quiz session is {session.status}")

        cards = list(session.state.get("cards") or [])
        index = int(session.state.get("index") or 0)
        if index >= len(cards):
            self.sessions.complete(session.id)
            return GradeReceipt(
                session_id=session.id,
                card_uid="",
                grade=parsed,
                review_event_uid=None,
                card_updated=False,
                done=True,
                next_card=None,
                correct=int(session.state.get("correct") or 0),
                index=index,
                total=len(cards),
                details={"note": "already_complete"},
            )

        meta = cards[index]
        card_uid = str(meta["object_uid"])
        object_type = str(meta["object_type"])
        row = self._load_card_row(object_type, card_uid)
        if row is None:
            raise RuntimeError(f"card not found: {card_uid}")

        when = at or now()
        result = self.scheduler.review(card_state_from_row(row), parsed, when)

        # Apply path: update card SM-2 fields, then append review_event.
        update = self.engine.apply_spec(
            OperationSpec(
                domain=self.DOMAIN,
                operation="update",
                object_type=object_type,
                object_uid=card_uid,
                payload=result.card_update_fields(),
                channel="quiz",
            ),
            actor="quiz",
            actor_channel="quiz",
        )
        if not update.ok:
            raise RuntimeError(f"card update failed: {update.error}")

        created = self.engine.apply_spec(
            OperationSpec(
                domain=self.DOMAIN,
                operation="create",
                object_type="review_event",
                payload=result.review_event_fields(card_uid=card_uid),
                channel="quiz",
            ),
            actor="quiz",
            actor_channel="quiz",
        )
        if not created.ok:
            raise RuntimeError(f"review_event create failed: {created.error}")

        correct = int(session.state.get("correct") or 0)
        if parsed in {"good", "easy"}:
            correct += 1
        grades = list(session.state.get("grades") or [])
        grades.append(
            {
                "card_uid": card_uid,
                "grade": parsed,
                "review_event_uid": created.object_uid,
                "interval_days": result.next_interval_days,
            }
        )
        index += 1
        new_state = {
            **session.state,
            "index": index,
            "correct": correct,
            "grades": grades,
        }
        done = index >= len(cards)
        if done:
            self.sessions.save_state(session.id, new_state)
            self.sessions.complete(session.id)
            next_card = None
        else:
            session = self.sessions.save_state(session.id, new_state)
            next_card = self.current_card(session)

        return GradeReceipt(
            session_id=session.id,
            card_uid=card_uid,
            grade=parsed,
            review_event_uid=created.object_uid,
            card_updated=True,
            done=done,
            next_card=next_card,
            correct=correct,
            index=index,
            total=len(cards),
            details={
                "prev_interval_days": result.prev_interval_days,
                "next_interval_days": result.next_interval_days,
                "ease_factor": result.state.ease_factor,
                "algorithm": result.algorithm,
                "learning_step": result.state.learning_step,
            },
        )

    # ------------------------------------------------------------------ helpers

    def _load_card_row(self, object_type: str, object_uid: str) -> dict[str, Any] | None:
        tname = table_name(self.DOMAIN, object_type)
        conn = connect_rw(self.ws.domains_db)
        try:
            row = conn.execute(
                f"SELECT * FROM {tname} WHERE object_uid = ? AND tombstoned = 0",
                (object_uid,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def parse_grade(raw: Grade | str) -> Grade:
    key = str(raw).strip().lower()
    if key in GRADE_ALIASES:
        return GRADE_ALIASES[key]
    raise ValueError(f"unknown grade {raw!r}; expected one of {GRADES}")


def looks_like_quiz_start(text: str) -> bool:
    return bool(_QUIZ_START_RE.search(text or ""))


def looks_like_grade(text: str) -> bool:
    return str(text or "").strip().lower() in GRADE_ALIASES


def quiz_stats(workspace: Workspace, *, domain: str = "japanese") -> dict[str, Any]:
    """Read-only aggregates over review_event (+ due/new card counts)."""
    from collections import Counter

    from domain_foundry_core.clock import today_utc

    ev_table = table_name(domain, "review_event")
    vocab_table = table_name(domain, "jp_vocab")
    as_of = today_utc()
    out: dict[str, Any] = {
        "domain": domain,
        "as_of": as_of,
        "review_count": 0,
        "grade_distribution": {},
        "algorithm_distribution": {},
        "due_count": 0,
        "new_count": 0,
        "reviewed_today": 0,
    }
    if not workspace.domains_db.exists():
        return out
    conn = connect_ro(workspace.domains_db)
    try:
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (ev_table,)
        ).fetchone():
            rows = conn.execute(
                f"""
                SELECT grade, algorithm, reviewed_at
                FROM {ev_table}
                WHERE tombstoned = 0
                """
            ).fetchall()
            grades = Counter(str(r["grade"] or "") for r in rows)
            algos = Counter(str(r["algorithm"] or "") for r in rows)
            out["review_count"] = len(rows)
            out["grade_distribution"] = dict(grades)
            out["algorithm_distribution"] = dict(algos)
            out["reviewed_today"] = sum(
                1
                for r in rows
                if str(r["reviewed_at"] or "").startswith(as_of)
            )
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (vocab_table,)
        ).fetchone():
            due = conn.execute(
                f"""
                SELECT count(*) FROM {vocab_table}
                WHERE tombstoned = 0
                  AND next_review IS NOT NULL
                  AND next_review <= ?
                """,
                (as_of,),
            ).fetchone()
            new = conn.execute(
                f"""
                SELECT count(*) FROM {vocab_table}
                WHERE tombstoned = 0
                  AND reps = 0
                  AND (next_review IS NULL OR next_review = '')
                  AND (last_reviewed IS NULL OR last_reviewed = '')
                """
            ).fetchone()
            out["due_count"] = int(due[0] or 0)
            out["new_count"] = int(new[0] or 0)
    finally:
        conn.close()
    return out
