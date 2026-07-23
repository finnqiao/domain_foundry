"""Weekly triage / queue-depth nudge for Concierge (Phase 8 R5).

Emits a single outbound message summarizing mesh queue depths + DLQ when the
weekly window fires. Idempotent via ``schedule_run`` (domain=concierge,
schedule_id=weekly_triage) keyed by ISO week.
"""

from __future__ import annotations

import os
from typing import Any

from domain_foundry_core.clock import now
from domain_foundry_core.mesh.flags import MeshObservabilityFlags
from domain_foundry_core.mesh.observability import MeshObservability
from domain_foundry_core.mesh.outbound import OutboundQueue
from domain_foundry_core.mesh.schedules import ScheduleRunStore
from domain_foundry_core.packs.models import AgentScheduleSpec
from domain_foundry_core.paths import Workspace

WEEKLY_TRIAGE_SCHEDULE = AgentScheduleSpec(
    id="weekly_triage",
    cron="0 10 * * 1",  # Monday 10:00 — week gate is ISO week, not cron parser
    when="",
    action="triage_nudge",
    message=(
        "Weekly triage: inbox_pending={pending} dlq={dlq} "
        "depth_alert_enabled={alert}. Review mesh status / DLQ when depth climbs."
    ),
)


def maybe_fire_weekly_triage(
    workspace: Workspace,
    *,
    force: bool = False,
    channel: str | None = None,
    destination: str | None = None,
) -> dict[str, Any]:
    """Fire the weekly triage outbound if due (or ``force``).

    ``ScheduleEvaluator`` only parses daily ``M H * * *`` crons; for weekly we
    gate on ISO week stored in ``schedule_run.last_result.week_id`` so we only
    enqueue once per UTC week unless ``force``.
    """
    store = ScheduleRunStore(workspace)
    flags = MeshObservabilityFlags.from_env()
    health = MeshObservability(workspace, flags=flags).health()
    pending = int(health.queue_depths.get("inbox_pending", 0) or 0)
    dlq = int(health.dlq.get("total", 0) or 0)
    if dlq == 0:
        dlq = int(health.queue_depths.get("inbox_dead", 0) or 0) + int(
            health.queue_depths.get("outbound_dead", 0) or 0
        )
    alert = bool(flags.depth_alert)

    week_id = now().strftime("%G-W%V")
    row = store.get("concierge", WEEKLY_TRIAGE_SCHEDULE.id)
    if not force and row and (row.last_result or {}).get("week_id") == week_id:
        return {
            "fired": False,
            "skipped_reason": "already_fired_this_week",
            "week_id": week_id,
        }

    text = WEEKLY_TRIAGE_SCHEDULE.message.format(
        pending=pending, dlq=dlq, alert=alert
    )
    ch = channel or flags.depth_alert_channel or os.environ.get(
        "DOMAIN_FOUNDRY_MESH_DEPTH_ALERT_CHANNEL", "telegram"
    )
    dest = destination or flags.depth_alert_destination or os.environ.get(
        "DOMAIN_FOUNDRY_MESH_DEPTH_ALERT_DESTINATION", "ops"
    )
    OutboundQueue(workspace).enqueue(
        origin_domain="concierge",
        text=text,
        channel=ch,
        destination=dest,
        payload={
            "kind": "weekly_triage",
            "week_id": week_id,
            "pending": pending,
            "dlq": dlq,
        },
    )
    store.record_fire(
        "concierge",
        WEEKLY_TRIAGE_SCHEDULE.id,
        next_due_at=None,
        result={
            "week_id": week_id,
            "pending": pending,
            "dlq": dlq,
            "alert": alert,
        },
    )
    return {
        "fired": True,
        "week_id": week_id,
        "pending": pending,
        "dlq": dlq,
        "message": text,
    }
