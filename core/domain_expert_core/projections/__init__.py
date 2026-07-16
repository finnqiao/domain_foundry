"""ProjectionCoordinator + adapters (P4)."""

from domain_expert_core.projections.blockdata import (
    BlockDataAdapter,
    BlockDataError,
    BlockDataService,
)
from domain_expert_core.projections.coordinator import (
    DEFAULT_ADAPTERS,
    DrainReport,
    ProjectionCoordinator,
    ProjectionDrainLoop,
    enqueue_projection,
    projection_lag,
    projection_status_for_change_request,
    schedule_projections,
)
from domain_expert_core.projections.markdown import (
    MarkdownAdapter,
    merge_managed_markdown,
    write_managed_note,
)

__all__ = [
    "DEFAULT_ADAPTERS",
    "BlockDataAdapter",
    "BlockDataError",
    "BlockDataService",
    "DrainReport",
    "MarkdownAdapter",
    "ProjectionCoordinator",
    "ProjectionDrainLoop",
    "enqueue_projection",
    "merge_managed_markdown",
    "projection_lag",
    "projection_status_for_change_request",
    "schedule_projections",
    "write_managed_note",
]
