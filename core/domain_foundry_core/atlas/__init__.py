"""Idea atlas: topic graph of buckets, practices, and app ideas.

The wizard queries this index. Core does not branch on a domain name.
"""

from __future__ import annotations

from domain_foundry_core.atlas.loader import bundled_atlas_root, load_atlas
from domain_foundry_core.atlas.models import JOBS, AtlasEdge, AtlasGraph, AtlasNode
from domain_foundry_core.atlas.query import neighborhood_for, query_neighborhood
from domain_foundry_core.atlas.traits import (
    StructuralOption,
    TraitGraph,
    TraitRule,
    detect_traits,
    load_trait_graph,
    structural_options,
    validate_trait_graph,
)

__all__ = [
    "JOBS",
    "AtlasEdge",
    "AtlasGraph",
    "AtlasNode",
    "StructuralOption",
    "TraitGraph",
    "TraitRule",
    "bundled_atlas_root",
    "detect_traits",
    "load_atlas",
    "load_trait_graph",
    "neighborhood_for",
    "query_neighborhood",
    "structural_options",
    "validate_trait_graph",
]
