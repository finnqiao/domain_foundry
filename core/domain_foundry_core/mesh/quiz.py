"""Japanese quiz session skeleton — due-first queue + SM-2 grade handlers.

Full Anki UX (learning steps, new-card rate UI, vault dashboard) is partial;
this pass wires durable sessions, due-first ordering, and review_event writes
through the HarnessAPI apply path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from domain_foundry_core.apply.engine import ApplyEngine, OperationSpec
from domain_foundry_core.clock import now, today_utc
from domain_foundry_core.mesh.outbound import OutboundQueue
from domain_foundry_core.mesh.schedules import ScheduleRunStore
from domain_foundry_core.mesh.sessions import DomainSession, DomainSessionStore
from domain_foundry_core.mesh.srs import (
    GRADES,
    CardState,
    Grade,
    SM2Scheduler,
    Scheduler,
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
        new_card_limit: int = 20,
    ) -> None:
        self.ws = workspace or Workspace()
        self.scheduler = scheduler or SM2Scheduler()
        self.registry = registry or PackRegistry(self.ws)
        self.engine = ApplyEngine(self.ws, registry=self.registry)
        self.sessions = DomainSessionStore(self.ws)
        self.schedules = ScheduleRunStore(self.ws)
        self.outbound = OutboundQueue(self.ws)
        self.new_card_limit = new_card_limit

    # ------------------------------------------------------------------ start

    def start(
        self,
        *,
        user_id: str = "default",
        limit: int | None = None,
        include_grammar: bool = True,
        filter_text: str | None = None,
    ) -> DomainSession:
        """Open a quiz session with a due-first card queue."""
        cards = self.build_due_first_queue(
            limit=limit,
            include_grammar=include_grammar,
            filter_text=filter_text,
        )
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
    ) -> tuple[DomainSession, str | None]:
        """Daily 09:00 stub: record schedule fire, start quiz, enqueue outbound nudge."""
        session = self.start(user_id=user_id)
        due_count = len(session.state.get("cards") or [])
        body = f"You have {due_count} Japanese cards due. Want to review now?"
        outbound = self.outbound.enqueue(
            origin_domain=self.DOMAIN,
            text=body,
            channel=channel,
            destination=user_id,
            payload={"schedule_id": schedule_id, "session_id": session.id, "count": due_count},
        )
        self.schedules.record_fire(
            self.DOMAIN,
            schedule_id,
            next_due_at=None,  # Expert cron evaluator fills next window later
            result={"session_id": session.id, "outbound_id": outbound.id, "count": due_count},
        )
        return session, outbound.id

    # ------------------------------------------------------------------ queue

    def build_due_first_queue(
        self,
        *,
        limit: int | None = None,
        include_grammar: bool = True,
        filter_text: str | None = None,
        as_of: str | None = None,
    ) -> list[QuizCard]:
        """Due reviews first (oldest next_review), then new cards (capped)."""
        as_of = as_of or today_utc()
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
                    SELECT object_uid, {title_col} AS prompt, {meaning_col} AS answer,
                           ease_factor, interval_days, reps, lapses,
                           next_review, last_reviewed
                    FROM {tname}
                    WHERE tombstoned = 0
                    ORDER BY id ASC
                    """
                ).fetchall()
                for row in rows:
                    prompt = str(row["prompt"] or "")
                    answer = row["answer"]
                    if filter_text and filter_text.lower() not in prompt.lower() and (
                        not answer or filter_text.lower() not in str(answer).lower()
                    ):
                        continue
                    state = card_state_from_row(dict(row))
                    is_new = state.reps == 0 and not state.next_review
                    is_due = bool(
                        state.next_review and state.next_review <= as_of
                    )
                    card = QuizCard(
                        object_uid=str(row["object_uid"]),
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
        queue = due + new[: self.new_card_limit]
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
