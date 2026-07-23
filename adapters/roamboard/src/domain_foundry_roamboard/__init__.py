"""Roamboard → DomainFoundry travel sync adapter (Phase 7, shadow-ready).

Import Roamboard feed / patch shapes into DF travel objects via in-process
``HarnessAPI`` (same pattern as hermes-agent ``LocalHarnessClient``). Shadow
mode diffs private ``travel.sqlite`` (read-only) against DF query outcomes
under ``{DF_HOME}/shadow/roamboard/``. Does **not** flip production launchd.
"""

from __future__ import annotations

from domain_foundry_roamboard.shadow import ShadowReport, run_shadow
from domain_foundry_roamboard.sync import SyncMode, SyncReport, sync_roamboard

__all__ = [
    "ShadowReport",
    "SyncMode",
    "SyncReport",
    "run_shadow",
    "sync_roamboard",
]

__version__ = "0.1.0"
