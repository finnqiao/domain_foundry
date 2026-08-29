"""Seed: turn what you already keep into the data the app is born with.

One verb reads a spreadsheet, a folder of notes, an export from another app, a
mail export, or a page you trust, works out what each column means, shows you a
preview, and writes nothing until you say ``--apply``.

Three rules hold everywhere in here:

* Sources are read only. Nothing is moved, renamed, or written back.
* Dry run is the default. ``--apply`` is the only path that writes.
* Every row carries where it came from. A personal upload is marked personal and
  never becomes shareable, whatever anyone sets later.
"""

from __future__ import annotations

from domain_foundry_core.seed.apply import SeedApplyResult, apply_seed
from domain_foundry_core.seed.brief import (
    SEED_ASK,
    SEED_DECLINE_WORDS,
    seed_artifact_lines,
    seed_brief_inputs,
)
from domain_foundry_core.seed.mapping import (
    ColumnMapping,
    ColumnRole,
    RepeatedList,
    SeedMapping,
    infer_mapping,
    load_seed_mapping,
    save_seed_mapping,
)
from domain_foundry_core.seed.models import (
    SeedDocument,
    SeedRead,
    SeedSummary,
    SeedTable,
    summarize,
)
from domain_foundry_core.seed.preview import render_preview, write_preview
from domain_foundry_core.seed.readers import SeedReadError, read_seed

__all__ = [
    "SEED_ASK",
    "SEED_DECLINE_WORDS",
    "ColumnMapping",
    "ColumnRole",
    "RepeatedList",
    "SeedApplyResult",
    "SeedDocument",
    "SeedMapping",
    "SeedRead",
    "SeedReadError",
    "SeedSummary",
    "SeedTable",
    "apply_seed",
    "infer_mapping",
    "load_seed_mapping",
    "read_seed",
    "render_preview",
    "save_seed_mapping",
    "seed_artifact_lines",
    "seed_brief_inputs",
    "summarize",
    "write_preview",
]
