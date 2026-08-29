"""Writing the seed in, through the machinery that already keeps the receipts.

Nothing new is invented here. The rows go through the same importer the
``import`` command uses, so every seeded record gets a capture event, an entry,
a canonical object, a revision, and a source link, and corrections work on them
afterwards exactly as they do on anything typed in by hand.

Two things this adds on top:

* Every row's ``source_ref`` starts ``seed:<seed id>:``, and the channel says
  whether the seed was something the user keeps or a page they pointed at. That
  is the row-level marking the sharing line rests on.
* A record of the seed itself is kept in the workspace, so later stages can say
  which records came from which source without re-reading the file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from domain_foundry_core.clock import now_iso
from domain_foundry_core.foundry.models import SeedProvenance
from domain_foundry_core.migrations.importers import (
    DictSource,
    GenericImporter,
    MappingConfig,
)
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace
from domain_foundry_core.seed.mapping import SeedMapping
from domain_foundry_core.seed.models import SeedRead

# Where the record of each seed lives inside the workspace.
SEEDS_DIRNAME = "seeds"

# The importer needs a stable id per row. The seed pipeline makes one.
ROW_ID_FIELD = "_seed_row_id"
READ_AT_FIELD = "_seed_read_at"


class SeedApplyError(RuntimeError):
    """Raised when a seed cannot be written, with the fix in the message."""


@dataclass
class SeedApplyResult:
    """What the seed did, or would do."""

    seed_id: str
    dry_run: bool
    source_total: int = 0
    written: int = 0
    would_write: int = 0
    already_present: int = 0
    skipped: int = 0
    failed: int = 0
    reasons: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """True when every source row was accounted for and none failed."""

        accounted = self.written + self.would_write + self.already_present + self.skipped
        return accounted == self.source_total and self.failed == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed_id": self.seed_id,
            "dry_run": self.dry_run,
            "source_total": self.source_total,
            "written": self.written,
            "would_write": self.would_write,
            "already_present": self.already_present,
            "skipped": self.skipped,
            "failed": self.failed,
            "complete": self.complete,
            "reasons": list(self.reasons),
        }


def seed_records(read: SeedRead, mapping: SeedMapping) -> list[dict[str, Any]]:
    """Turn the read rows into importer records, with a stable id on each.

    Row ids come from position in the file, so reading the same file twice
    produces the same ids, which is what makes applying twice a no-op.
    """

    table = read.primary_table
    if table is None:
        return []
    read_at = read.provenance.retrieved_at or now_iso()
    records: list[dict[str, Any]] = []
    for position, row in enumerate(table.rows, start=1):
        record: dict[str, Any] = {
            ROW_ID_FIELD: f"{position:06d}",
            READ_AT_FIELD: read_at,
        }
        for column in mapping.mapped_columns:
            record[column.column] = row.values.get(column.column)
        records.append(record)
    return records


def apply_seed(
    workspace: Workspace,
    read: SeedRead,
    mapping: SeedMapping,
    *,
    dry_run: bool = True,
    registry: PackRegistry | None = None,
) -> SeedApplyResult:
    """Run the seed. Dry run by default, which is the whole point of the default."""

    records = seed_records(read, mapping)
    if not records:
        return SeedApplyResult(seed_id=mapping.seed_id, dry_run=dry_run)

    registry = registry or PackRegistry(workspace)
    _check_target(registry, mapping)

    config = MappingConfig.model_validate(mapping.to_importer_mapping())
    source = DictSource({mapping.object_type: records})
    report = GenericImporter(workspace, config, registry=registry, dry_run=dry_run).run(source)

    result = SeedApplyResult(
        seed_id=mapping.seed_id,
        dry_run=dry_run,
        source_total=report.source_total,
        written=report.imported,
        would_write=report.would_import,
        already_present=report.skipped_existing,
        skipped=report.skipped_invalid,
        failed=report.failed,
        reasons=sorted(
            {
                outcome.reason
                for outcome in report.outcomes
                if outcome.kind in {"skipped_invalid", "failed"} and outcome.reason
            }
        ),
    )
    if not dry_run:
        record_seed(workspace, read.provenance, mapping, result)
    return result


def _check_target(registry: PackRegistry, mapping: SeedMapping) -> None:
    """Say plainly when the seed has nowhere to land yet."""

    registry.reload()
    pack = registry.get(mapping.domain) or registry.get_by_alias(mapping.domain)
    if pack is None:
        raise SeedApplyError(
            f"There is no app called {mapping.domain!r} to seed yet. Build it first, "
            "then seed it, or pass --domain with the name of one you already have."
        )
    if mapping.object_type not in pack.objects:
        known = ", ".join(sorted(pack.objects)) or "nothing yet"
        raise SeedApplyError(
            f"{mapping.domain!r} has no table called {mapping.object_type!r}. "
            f"It has: {known}. Pass --object-type with one of those, or edit the mapping."
        )
    obj = pack.objects[mapping.object_type]
    unknown = [c.field_name for c in mapping.mapped_columns if c.field_name not in obj.fields]
    if unknown and len(unknown) == len(mapping.mapped_columns):
        raise SeedApplyError(
            f"None of the columns match the fields in {mapping.object_type!r}: "
            f"{', '.join(sorted(obj.fields))}. Edit the mapping so the field names line up."
        )


# ------------------------------------------------------------------ seed records


def seeds_dir(workspace: Workspace) -> Path:
    return workspace.home / SEEDS_DIRNAME


def record_seed(
    workspace: Workspace,
    provenance: SeedProvenance,
    mapping: SeedMapping,
    result: SeedApplyResult,
) -> Path:
    """Keep a note of the seed itself, so later stages know what came from where."""

    folder = seeds_dir(workspace)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{provenance.id}.json"
    payload = {
        "provenance": provenance.model_dump(mode="json"),
        "shareable": provenance.shareable,
        "domain": mapping.domain,
        "object_type": mapping.object_type,
        "channel": mapping.channel,
        "source_ref_prefix": f"seed:{provenance.id}:",
        "applied_at": now_iso(),
        "result": result.as_dict(),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_seed_records(workspace: Workspace) -> list[dict[str, Any]]:
    """Every seed applied into this workspace, newest name order."""

    folder = seeds_dir(workspace)
    if not folder.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return out


def seed_provenances(workspace: Workspace) -> list[SeedProvenance]:
    """The provenance of every seed in this workspace, ready for a brief."""

    out: list[SeedProvenance] = []
    for record in load_seed_records(workspace):
        raw = record.get("provenance")
        if isinstance(raw, dict):
            out.append(SeedProvenance.model_validate(raw))
    return out
