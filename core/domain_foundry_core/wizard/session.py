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

from domain_foundry_core.clock import now_iso
from domain_foundry_core.ids import new_ulid
from domain_foundry_core.paths import Workspace

# State machine (plan §6.1): goal → model confirmation (when a live provider is
# configured) → proposal/interview → generate → held-out acceptance →
# test-drive or bounded repair → hardening. Generate and acceptance remain one
# persisted transition from the caller's point of view.
STATES = (
    "fork",              # atlas neighborhood; pick/refine/expand/commit
    "looks",             # HTML sketch per idea; critique then accept
    "elicit",            # unindexed/invented: two sentences in the user's words
    "schema_preview",    # optional YAML/schema look before activate
    "model_confirm",     # live keys present: confirm the design model first
    "interview",         # proposal made, questions pending
    "test_drive",        # pack generated + activated; awaiting sample captures
    "repair",            # held-out acceptance failed; failures are visible
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
    design_mode: str = "scaffold"       # "llm" | "scaffold"
    designer_model: str | None = None
    # Set when an LLM design was attempted but a labeled scaffold was installed.
    design_fallback_reason: str | None = None
    acceptance: dict[str, Any] = field(default_factory=dict)
    repair_rounds: int = 0              # completed repair rounds, capped at 3
    real_captures: int = 0              # applied captures made in this wizard
    atlas_cursor: str | None = None
    selected_ideas: list[str] = field(default_factory=list)
    selected_jobs: list[str] = field(default_factory=list)
    neighborhood: dict[str, Any] = field(default_factory=dict)
    schema_preview: dict[str, Any] = field(default_factory=dict)
    looks: list[dict[str, Any]] = field(default_factory=list)
    selected_look_id: str | None = None
    look_job_hints: list[str] = field(default_factory=list)
    ingest_blob: str = ""
    # Sentences the user said they would log, verbatim and in order. The first
    # shapes the design; the second is held out of the shortlist, the examples
    # and the compiled rules, then replayed through the real router after
    # activation. Empty means elicitation was skipped or never offered.
    elicited_samples: list[str] = field(default_factory=list)
    elicit_prompts: int = 0             # elicitation turns already spoken
    # ADR-010 bridge. ``bridge_tier`` is how this pack's research was sourced —
    # one of reviewed_corpus / live_search / model_knowledge / fallback_demo —
    # and is stamped into the pack's own metadata. ``bridge_fallback_reason``
    # is set whenever the bridge was eligible and did not deliver, so a
    # misconfigured provider can never look identical to having no key.
    bridge_tier: str | None = None
    bridge_spec_id: str | None = None
    bridge_fallback_reason: str | None = None
    # The release path has a softer renderer and a stricter first-use gate.
    # Legacy ``new-domain`` sessions keep their existing contract.
    release_mode: bool = False

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

    def looks_dir(self, session_id: str) -> Path:
        return self.root / session_id / "looks"

    def new(self, goal: str, *, test_drive: int = 5) -> WizardSession:
        self.root.mkdir(parents=True, exist_ok=True)
        ts = now_iso()
        session = WizardSession(
            session_id=f"wz_{new_ulid()}",
            state="fork",
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
