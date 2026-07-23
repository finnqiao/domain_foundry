"""ProjectionCoordinator + adapters (P4)."""

from domain_foundry_core.projections.blockdata import (
    BlockDataAdapter,
    BlockDataError,
    BlockDataService,
)
from domain_foundry_core.projections.coordinator import (
    DEFAULT_ADAPTERS,
    DrainReport,
    ProjectionCoordinator,
    ProjectionDrainLoop,
    enqueue_projection,
    projection_lag,
    projection_status_for_change_request,
    schedule_projections,
)
from domain_foundry_core.projections.geojson import (
    GEOJSON_ADAPTER,
    GeoJsonAdapter,
    build_food_venues_collection,
    food_venues_path,
    row_to_feature,
)
from domain_foundry_core.projections.markdown import (
    MarkdownAdapter,
    merge_managed_markdown,
    preview_managed_write,
    unmanaged_preserved,
    unmanaged_text,
    write_managed_note,
)
from domain_foundry_core.projections.reproject import (
    HERMES_FOLDER_MAP,
    ReprojectReport,
    VaultReprojector,
)

__all__ = [
    "DEFAULT_ADAPTERS",
    "GEOJSON_ADAPTER",
    "HERMES_FOLDER_MAP",
    "BlockDataAdapter",
    "BlockDataError",
    "BlockDataService",
    "DrainReport",
    "GeoJsonAdapter",
    "MarkdownAdapter",
    "ProjectionCoordinator",
    "ProjectionDrainLoop",
    "ReprojectReport",
    "VaultReprojector",
    "build_food_venues_collection",
    "enqueue_projection",
    "food_venues_path",
    "merge_managed_markdown",
    "preview_managed_write",
    "projection_lag",
    "projection_status_for_change_request",
    "row_to_feature",
    "schedule_projections",
    "unmanaged_preserved",
    "unmanaged_text",
    "write_managed_note",
]
