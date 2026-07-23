"""Importer result / reconciliation report models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

OutcomeKind = Literal[
    "imported",
    "skipped_existing",
    "skipped_invalid",
    "failed",
    "would_import",  # dry-run
]


@dataclass
class RecordOutcome:
    entity: str
    source_ref: str | None
    source_id: Any
    kind: OutcomeKind
    reason: str | None = None
    capture_event_id: str | None = None
    entry_id: str | None = None
    object_uid: str | None = None


@dataclass
class ReconciliationReport:
    """Source vs imported vs skipped — hard gate for migration fidelity."""

    mapping_name: str
    channel: str
    dry_run: bool
    source_total: int = 0
    imported: int = 0
    would_import: int = 0
    skipped_existing: int = 0
    skipped_invalid: int = 0
    failed: int = 0
    outcomes: list[RecordOutcome] = field(default_factory=list)
    by_entity: dict[str, dict[str, int]] = field(default_factory=dict)

    def record(self, outcome: RecordOutcome) -> None:
        self.outcomes.append(outcome)
        bucket = self.by_entity.setdefault(
            outcome.entity,
            {
                "source": 0,
                "imported": 0,
                "would_import": 0,
                "skipped_existing": 0,
                "skipped_invalid": 0,
                "failed": 0,
            },
        )
        bucket["source"] += 1
        if outcome.kind == "imported":
            self.imported += 1
            bucket["imported"] += 1
        elif outcome.kind == "would_import":
            self.would_import += 1
            bucket["would_import"] += 1
        elif outcome.kind == "skipped_existing":
            self.skipped_existing += 1
            bucket["skipped_existing"] += 1
        elif outcome.kind == "skipped_invalid":
            self.skipped_invalid += 1
            bucket["skipped_invalid"] += 1
        elif outcome.kind == "failed":
            self.failed += 1
            bucket["failed"] += 1

    @property
    def accounted_for(self) -> int:
        return (
            self.imported
            + self.would_import
            + self.skipped_existing
            + self.skipped_invalid
            + self.failed
        )

    @property
    def complete(self) -> bool:
        """True when every source row is classified (parity gate)."""
        return self.source_total == self.accounted_for and self.failed == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_name": self.mapping_name,
            "channel": self.channel,
            "dry_run": self.dry_run,
            "source_total": self.source_total,
            "imported": self.imported,
            "would_import": self.would_import,
            "skipped_existing": self.skipped_existing,
            "skipped_invalid": self.skipped_invalid,
            "failed": self.failed,
            "accounted_for": self.accounted_for,
            "complete": self.complete,
            "by_entity": self.by_entity,
            "outcomes": [asdict(o) for o in self.outcomes],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Reconciliation — {self.mapping_name}",
            "",
            f"- channel: `{self.channel}`",
            f"- dry_run: {self.dry_run}",
            f"- source_total: {self.source_total}",
            f"- imported: {self.imported}",
            f"- would_import: {self.would_import}",
            f"- skipped_existing: {self.skipped_existing}",
            f"- skipped_invalid: {self.skipped_invalid}",
            f"- failed: {self.failed}",
            f"- accounted_for: {self.accounted_for}/{self.source_total}",
            f"- complete: {self.complete}",
            "",
            "## By entity",
            "",
        ]
        for name, counts in sorted(self.by_entity.items()):
            lines.append(
                f"- **{name}**: source={counts['source']} "
                f"imported={counts['imported']} would={counts['would_import']} "
                f"existing={counts['skipped_existing']} "
                f"invalid={counts['skipped_invalid']} failed={counts['failed']}"
            )
        skips = [o for o in self.outcomes if o.kind in {"skipped_invalid", "failed"}]
        if skips:
            lines.extend(["", "## Skipped / failed detail", ""])
            for o in skips:
                lines.append(
                    f"- `{o.source_ref or o.source_id}` ({o.kind}): {o.reason or 'n/a'}"
                )
        return "\n".join(lines) + "\n"
