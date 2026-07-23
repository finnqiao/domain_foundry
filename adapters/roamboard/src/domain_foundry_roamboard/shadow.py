"""Shadow diff: private travel.sqlite (RO) vs DomainFoundry travel query."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_ro

DEFAULT_TRAVEL_DB = (
    Path.home() / "HermesWorkspace" / "travel" / "data" / "travel.sqlite"
)


@dataclass
class ShadowCounts:
    trips: int = 0
    timeline_items: int = 0
    event_log: int = 0


@dataclass
class ShadowReport:
    generated_at: str
    travel_db: str
    df_home: str
    private: ShadowCounts
    foundry: ShadowCounts
    diffs: list[dict[str, Any]] = field(default_factory=list)
    trip_slug_only_private: list[str] = field(default_factory=list)
    trip_slug_only_foundry: list[str] = field(default_factory=list)
    report_dir: str | None = None
    notes: list[str] = field(default_factory=list)
    private_trip_samples: list[dict[str, Any]] = field(default_factory=list)
    foundry_trip_samples: list[dict[str, Any]] = field(default_factory=list)

    @property
    def zero_diff(self) -> bool:
        hard_diffs = [d for d in self.diffs if not d.get("soft")]
        return (
            not hard_diffs
            and not self.trip_slug_only_private
            and not self.trip_slug_only_foundry
            and self.private.trips == self.foundry.trips
            and self.private.timeline_items == self.foundry.timeline_items
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
    except sqlite3.Error:
        return 0
    return int(row["n"] if isinstance(row, sqlite3.Row) else row[0])


def _private_snapshot(
    travel_db: Path,
) -> tuple[ShadowCounts, set[str], list[dict[str, Any]]]:
    """Read travel.sqlite RO — never mutate."""
    conn = connect_ro(travel_db)
    try:
        counts = ShadowCounts(
            trips=_table_count(conn, "trips"),
            timeline_items=_table_count(conn, "timeline_items"),
            event_log=_table_count(conn, "event_log"),
        )
        slugs: set[str] = set()
        samples: list[dict[str, Any]] = []
        try:
            slugs = {
                str(r["slug"])
                for r in conn.execute(
                    "SELECT slug FROM trips WHERE slug IS NOT NULL AND slug != ''"
                )
            }
            samples = [
                {
                    "slug": r["slug"],
                    "name": r["name"],
                    "status": r["status"],
                    "start_date": r["start_date"],
                    "end_date": r["end_date"],
                }
                for r in conn.execute(
                    "SELECT slug, name, status, start_date, end_date FROM trips "
                    "ORDER BY start_date, id LIMIT 50"
                )
            ]
        except sqlite3.Error:
            # Incomplete / fixture schema — counts still useful.
            pass
        return counts, slugs, samples
    finally:
        conn.close()


def _foundry_snapshot(
    api: HarnessAPI,
) -> tuple[ShadowCounts, set[str], list[dict[str, Any]]]:
    """Read DF travel domain tables (not just entry summaries)."""
    domains_db = api.workspace.domains_db
    if not domains_db.exists():
        return ShadowCounts(), set(), []

    conn = connect_ro(domains_db)
    try:
        trips = _table_count(conn, "travel__trip")
        items = _table_count(conn, "travel__timeline_item")
        events = _table_count(conn, "travel__event_log")
        slugs: set[str] = set()
        samples: list[dict[str, Any]] = []
        try:
            for r in conn.execute(
                "SELECT slug, name, status, start_date, end_date FROM travel__trip "
                "WHERE COALESCE(tombstoned, 0) = 0 "
                "ORDER BY start_date, object_uid LIMIT 50"
            ):
                slug = str(r["slug"] or "").strip()
                if slug:
                    slugs.add(slug)
                samples.append(
                    {
                        "slug": slug or None,
                        "name": r["name"],
                        "status": r["status"],
                        "start_date": r["start_date"],
                        "end_date": r["end_date"],
                    }
                )
            # Full slug set (beyond sample limit).
            for r in conn.execute(
                "SELECT slug FROM travel__trip "
                "WHERE COALESCE(tombstoned, 0) = 0 "
                "AND slug IS NOT NULL AND slug != ''"
            ):
                slugs.add(str(r["slug"]))
        except sqlite3.Error:
            # Pack schema not applied yet — fall back to entry counts.
            trip_rows = api.query(domain="travel", object_type="trip", limit=500)
            item_rows = api.query(
                domain="travel", object_type="timeline_item", limit=2000
            )
            event_rows = api.query(domain="travel", object_type="event_log", limit=5000)
            return (
                ShadowCounts(
                    trips=len(trip_rows),
                    timeline_items=len(item_rows),
                    event_log=len(event_rows),
                ),
                set(),
                [],
            )
        return ShadowCounts(trips=trips, timeline_items=items, event_log=events), slugs, samples
    finally:
        conn.close()


def run_shadow(
    home: Path | str,
    *,
    travel_db: Path | str | None = None,
    write: bool = True,
) -> ShadowReport:
    """Compare private travel.sqlite (RO) to DF travel objects; write report dir."""
    ws = Workspace(Path(home).expanduser())
    ws.ensure_layout()
    api = HarnessAPI(ws.home)
    api.init()
    try:
        api.packs.activate_bundled("travel")
    except Exception:
        pass

    db_path = Path(travel_db or DEFAULT_TRAVEL_DB).expanduser()
    notes: list[str] = [
        "Private travel.sqlite opened read-only (file:?mode=ro).",
        "Old Roamboard launchd agents are NOT modified by this shadow run.",
        "7-day zero-diff gate and production cutover remain manual.",
    ]

    private_counts = ShadowCounts()
    private_slugs: set[str] = set()
    private_samples: list[dict[str, Any]] = []
    if not db_path.exists():
        notes.append(f"travel.sqlite missing at {db_path}; private counts are zero")
    else:
        private_counts, private_slugs, private_samples = _private_snapshot(db_path)

    foundry_counts, foundry_slugs, foundry_samples = _foundry_snapshot(api)
    only_private = sorted(private_slugs - foundry_slugs)
    only_foundry = sorted(foundry_slugs - private_slugs)
    diffs: list[dict[str, Any]] = []
    if private_counts.trips != foundry_counts.trips:
        diffs.append(
            {
                "kind": "count_mismatch",
                "entity": "trip",
                "private": private_counts.trips,
                "foundry": foundry_counts.trips,
            }
        )
    if private_counts.timeline_items != foundry_counts.timeline_items:
        diffs.append(
            {
                "kind": "count_mismatch",
                "entity": "timeline_item",
                "private": private_counts.timeline_items,
                "foundry": foundry_counts.timeline_items,
            }
        )
    # event_log is append-only and often denser on the private side; soft diff.
    if private_counts.event_log != foundry_counts.event_log:
        diffs.append(
            {
                "kind": "count_mismatch",
                "entity": "event_log",
                "private": private_counts.event_log,
                "foundry": foundry_counts.event_log,
                "soft": True,
            }
        )

    report = ShadowReport(
        generated_at=_now_iso(),
        travel_db=str(db_path),
        df_home=str(ws.home),
        private=private_counts,
        foundry=foundry_counts,
        diffs=diffs,
        trip_slug_only_private=only_private,
        trip_slug_only_foundry=only_foundry,
        notes=notes,
        private_trip_samples=private_samples,
        foundry_trip_samples=foundry_samples,
    )

    if write:
        out_dir = ws.home / "shadow" / "roamboard" / _now_stamp()
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "diff.json").write_text(
            json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (out_dir / "SUMMARY.md").write_text(_markdown_summary(report), encoding="utf-8")
        report.report_dir = str(out_dir)

    return report


def _markdown_summary(report: ShadowReport) -> str:
    lines = [
        "# Roamboard shadow diff",
        "",
        f"- generated_at: `{report.generated_at}`",
        f"- travel_db (RO): `{report.travel_db}`",
        f"- df_home: `{report.df_home}`",
        "",
        "## Counts",
        "",
        "| entity | private | foundry |",
        "|---|---:|---:|",
        f"| trip | {report.private.trips} | {report.foundry.trips} |",
        f"| timeline_item | {report.private.timeline_items} | {report.foundry.timeline_items} |",
        f"| event_log | {report.private.event_log} | {report.foundry.event_log} |",
        "",
        f"- zero_diff (trips+items+slugs): **{report.zero_diff}**",
        "",
        "## Slug deltas",
        "",
        f"- only_private ({len(report.trip_slug_only_private)}): "
        + (", ".join(report.trip_slug_only_private[:20]) or "—"),
        f"- only_foundry ({len(report.trip_slug_only_foundry)}): "
        + (", ".join(report.trip_slug_only_foundry[:20]) or "—"),
        "",
        "## Notes",
        "",
    ]
    for note in report.notes:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)
