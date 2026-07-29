"""Pydantic models for ledger receipts and health."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

EntryStatus = Literal["applied", "review", "ledger_only", "unfiled"]
ProjectionStatus = Literal["refreshed", "pending", "n/a"]


class RoutedSpan(BaseModel):
    domain: str | None = None
    object_type: str | None = None
    operation: str | None = None
    disposition: str = "ledger_only"
    confidence: float | None = None


class CaptureReceipt(BaseModel):
    entry_id: str
    capture_event_id: str
    status: EntryStatus
    routed: list[RoutedSpan] = Field(default_factory=list)
    projection_status: ProjectionStatus = "n/a"
    idempotent_replay: bool = False
    summary: str | None = None
    # Set when L2 was attempted and the model call failed; the capture still
    # lands (never-drop), but the user needs to know routing was degraded.
    llm_error: str | None = None


class EntryRow(BaseModel):
    id: str
    capture_event_id: str
    status: EntryStatus
    domain: str | None = None
    object_type: str | None = None
    operation: str | None = None
    routing_confidence: float | None = None
    fallback_tier: str | None = None
    summary: str | None = None
    raw_text: str | None = None
    channel: str | None = None
    created_at: str
    updated_at: str


class StoreHealth(BaseModel):
    path: str
    exists: bool
    ok: bool
    integrity: str
    fk_violations: list[dict[str, Any]] = Field(default_factory=list)
    schema_version: int = 0


class ProjectionLagReport(BaseModel):
    pending: int = 0
    failed: int = 0
    oldest_pending_age_seconds: float | None = None
    oldest_pending_at: str | None = None
    by_adapter: dict[str, Any] = Field(default_factory=dict)


class HealthReport(BaseModel):
    ok: bool
    ledger: StoreHealth
    domains: StoreHealth
    entry_counts: dict[str, int] = Field(default_factory=dict)
    last_capture_at: str | None = None
    projection_lag: ProjectionLagReport = Field(default_factory=ProjectionLagReport)
    # Change requests that failed to apply. Nothing is lost (the raw entry and
    # the error are both in the ledger), but they have no approval row, so they
    # never show up in `review list` — health is the only place a user can see
    # that a capture is stuck.
    failed_change_requests: int = 0
    warnings: list[str] = Field(default_factory=list)
