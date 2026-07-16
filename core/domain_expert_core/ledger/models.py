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


class HealthReport(BaseModel):
    ok: bool
    ledger: StoreHealth
    domains: StoreHealth
    entry_counts: dict[str, int] = Field(default_factory=dict)
    last_capture_at: str | None = None
