"""Idea atlas: topic graph of buckets, practices, and app ideas.

The wizard queries this index. Core does not branch on a domain name.
"""

from __future__ import annotations

from domain_foundry_core.atlas.loader import bundled_atlas_root, load_atlas
from domain_foundry_core.atlas.models import JOBS, AtlasEdge, AtlasGraph, AtlasNode
from domain_foundry_core.atlas.query import neighborhood_for, query_neighborhood

__all__ = [
    "JOBS",
    "AtlasEdge",
    "AtlasGraph",
    "AtlasNode",
    "bundled_atlas_root",
    "load_atlas",
    "neighborhood_for",
    "query_neighborhood",
]
