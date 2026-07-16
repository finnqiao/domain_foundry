"""Resumable wizard session persistence (channel-agnostic, JSON on disk).

Sessions live under ``<home>/wizard/<session_id>.json`` so a conversation can
be driven from chat, CLI, or the app shell and resumed across process restarts.
The draft pack under construction lives beside it at
``<home>/wizard/<session_id>/draft/``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from domain_expert_core.clock import now_iso
from domain_expert_core.ids import new_ulid
from domain_expert_core.paths import Workspace

# State machine (plan §6.1): goal → proposal → interview → generate → dry-run
# → test-drive → hardening. Persisted states below collapse generate+dry-run
# into the transition that produces `test_drive`.
STATES = (
    "interview",         # proposal made, questions pending
    "test_drive",        # pack generated + activated; awaiting sample captures
    "hardening_confirm", # NL edit parsed into a diff; awaiting confirm
    "done",
    "failed",
)


@dataclass
class WizardSession:
    session_id: str
    state: str
    goal: str
    created_at: str
    updated_at: str
    blueprint: dict[str, Any] = field(default_factory=dict)
    questions: list[dict[str, Any]] = field(default_factory=list)
    answers: dict[str, str] = field(default_factory=dict)
    domain: str | None = None
    pack_version: str = "0.1.0"
    pack_path: str | None = None
    activated: bool = False
    dry_run: dict[str, Any] = field(default_factory=dict)
    test_drive_remaining: int = 5
    captured_entries: list[str] = field(default_factory=list)
    pending_edit: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WizardSession:
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in allowed})


class WizardSessionStore:
    def __init__(self, workspace: Workspace) -> None:
        self.ws = workspace
        self.root = workspace.home / "wizard"

    def _path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.json"

    def draft_dir(self, session_id: str) -> Path:
        return self.root / session_id / "draft"

    def new(self, goal: str, *, test_drive: int = 5) -> WizardSession:
        self.root.mkdir(parents=True, exist_ok=True)
        ts = now_iso()
        session = WizardSession(
            session_id=f"wz_{new_ulid()}",
            state="interview",
            goal=goal,
            created_at=ts,
            updated_at=ts,
            test_drive_remaining=test_drive,
        )
        self.save(session)
        return session

    def save(self, session: WizardSession) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        session.updated_at = now_iso()
        self._path(session.session_id).write_text(
            json.dumps(session.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load(self, session_id: str) -> WizardSession | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        return WizardSession.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.stem for p in self.root.glob("wz_*.json"))
