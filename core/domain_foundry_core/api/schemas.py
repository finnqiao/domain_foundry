"""Request bodies for the HTTP write seam (ADR-006).

Field names and optionality mirror what the shipped clients already send:

- the SPA (``app/src/lib/api.ts``): ``{text, channel:"web"}`` captures,
  ``correct`` bodies with a forced ``channel:"web"``, ``{name}`` activation,
  ``{decision, note}`` resolves, ``{approval_ids, decision}`` bulk resolves.
- the hermes-agent HTTP client
  (``adapters/hermes_agent/src/domain_foundry_hermes_agent/client.py``):
  the same operations with explicit ``null`` for every optional field, plus
  ``{goal_text, test_drive}`` / ``{text}`` wizard bodies.

Every optional field therefore defaults to ``None`` (explicit nulls must
validate). Decision vocabulary: the SPA sends ``approve``/``deny`` while the
executor requires ``approved``/``denied``/``expired``
(``apply/executor.py::resolve_approval``); ``normalized_decision()`` maps the
SPA forms so both dialects are legal at the HTTP boundary.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator

from domain_foundry_core.foundry.models import RemixFragment

_DECISION_ALIASES = {
    "approve": "approved",
    "deny": "denied",
    "expire": "expired",
}


class CaptureBody(BaseModel):
    text: str
    channel: str = "web"
    domain_hint: str | None = None
    source_ref: str | None = None
    attachments: list[dict[str, Any]] | None = None
    actor: str | None = None


class CorrectBody(BaseModel):
    text: str | None = None
    entry_id: str | None = None
    object_uid: str | None = None
    action: str | None = None
    fields: dict[str, Any] | None = None
    merge_into_uid: str | None = None
    target_domain: str | None = None
    channel: str = "web"


class ActivateBody(BaseModel):
    name: str


class PackSourceBody(BaseModel):
    source: str = Field(min_length=1)


class PackInstallBody(PackSourceBody):
    force: bool = False


class PackRollbackBody(BaseModel):
    name: str = Field(min_length=1)
    backup: str | None = None


class PackExportBody(BaseModel):
    name: str = Field(min_length=1)
    destination: str = Field(min_length=1)


class PackNameBody(BaseModel):
    name: str = Field(min_length=1)


class _DecisionMixin(BaseModel):
    decision: str
    note: str | None = None
    resolver: str = "user"

    def normalized_decision(self) -> str:
        return _DECISION_ALIASES.get(self.decision, self.decision)


class ResolveBody(_DecisionMixin):
    pass


class BulkResolveBody(_DecisionMixin):
    approval_ids: list[str]


class DrainBody(BaseModel):
    adapters: list[str] | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class ApplyBody(BaseModel):
    domain: str
    operation: str
    object_type: str
    fields: dict[str, Any] = Field(default_factory=dict)
    object_uid: str | None = None
    entry_id: str | None = None


class RoamboardPreviewBody(BaseModel):
    feed_path: str = Field(min_length=1)


class RoamboardCommitBody(RoamboardPreviewBody):
    preview_token: str = Field(min_length=1)


class PackImportPreviewBody(BaseModel):
    domain: str
    mapping_id: str
    source_path: str | None = None


class PackImportCommitBody(PackImportPreviewBody):
    preview_token: str = Field(min_length=1)


class QuizStartBody(BaseModel):
    domain: str = "japanese"
    user_id: str = "default"
    limit: int | None = Field(default=None, ge=1, le=100)
    include_grammar: bool = True
    filter_text: str | None = None
    new_card_limit: int | None = Field(default=None, ge=0, le=100)


class QuizGradeBody(BaseModel):
    domain: str = "japanese"
    grade: str
    session_id: str | None = None
    user_id: str = "default"


class ScheduleStatusBody(BaseModel):
    status: str


class HardeningBody(BaseModel):
    text: str = Field(min_length=1)


class WizardBody(BaseModel):
    goal_text: str
    test_drive: int = Field(default=5, ge=0, le=50)
    # Only the new /api/create surface enables the release renderer and
    # first-use policy.  /api/wizard remains a compatibility endpoint.
    release: bool = False


class WizardReplyBody(BaseModel):
    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


FoundryText = Annotated[str, Field(min_length=1, max_length=2_000)]


class FoundryAcceptanceTaskBody(BaseModel):
    input: FoundryText
    expected: FoundryText


class FoundryProposeBody(BaseModel):
    goal: str = Field(min_length=3, max_length=4_000)
    artifacts: list[FoundryText] = Field(default_factory=list, max_length=20)
    constraints: list[FoundryText] = Field(default_factory=list, max_length=20)
    acceptance_tasks: list[FoundryAcceptanceTaskBody] = Field(min_length=2, max_length=10)
    web_research: bool = True


class FoundryCompleteBody(BaseModel):
    selected_concept: str = Field(min_length=1, max_length=120)
    fragments: list[RemixFragment] = Field(default_factory=list, max_length=10)
    user_decisions: list[FoundryText] = Field(min_length=1, max_length=10)


class AtlasSearchBody(BaseModel):
    goal: str = Field(min_length=1)
    cursor_id: str | None = None


class PackEditBody(BaseModel):
    text: str = Field(min_length=1)
    confirm: bool = False
