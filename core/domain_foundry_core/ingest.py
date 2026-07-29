"""Bolt-on ingestion: pull existing notes / logs / folders into your foundries.

Domain Foundry is a *layer*, not a rewrite. This reads files you already have —
an Obsidian vault, a folder of markdown notes, a log file — **read-only**, and
runs each entry through the normal capture → route path. Nothing is moved or
modified at the source; captures are idempotent on ``(channel, source_ref)`` so
re-running is a safe no-op, and the router files each note into whichever foundry
fits (or leaves it as an unfiled card — never dropped).

Two ways to aim it:

* **Let the models pick** (default): every note is routed by content into the
  best-matching active domain. Run ``--dry-run`` first to see where things land
  without writing anything.
* **A particular foundry**: activate the domain you care about first; matching
  notes file into it, the rest stay unfiled for later.

This is the unstructured on-ramp. For a structured source with a known schema (a
SQLite table, a JSON export), use the mapping-driven
:mod:`domain_foundry_core.migrations.importers` framework instead.
"""

from __future__ import annotations

import hashlib
import time
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Text-ish files worth ingesting as captures. Binary/asset files are skipped.
TEXT_SUFFIXES = {
    ".md", ".markdown", ".mdown", ".txt", ".text", ".log", ".org", ".rst",
}


def iter_records(
    path: Path | str, *, glob: str | None = None, split: str = "file"
) -> Iterator[tuple[str, str]]:
    """Yield ``(source_ref, text)`` for each note/entry under ``path`` (read-only).

    ``split="file"`` → one capture per file (notes). ``split="lines"`` → one per
    non-empty line (append-only logs / journals).
    """
    root = Path(path).expanduser()
    if root.is_file():
        files = [root]
        base = root.parent
    else:
        pattern = glob or "*"
        files = sorted(
            f for f in root.rglob(pattern)
            if f.is_file() and f.suffix.lower() in TEXT_SUFFIXES
        )
        base = root
    for f in files:
        rel = f.relative_to(base).as_posix()
        try:
            raw = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if split == "lines":
            for i, line in enumerate(raw.splitlines(), start=1):
                s = line.strip()
                if s:
                    yield f"{rel}#L{i}", s
        else:
            s = raw.strip()
            if s:
                # short hash of content keeps the ref stable but lets an edited
                # note re-import as a new capture rather than silently masking it.
                digest = hashlib.sha256(s.encode("utf-8")).hexdigest()[:8]
                yield f"{rel}#{digest}", s


@dataclass
class IngestReport:
    path: str
    channel: str
    split: str
    dry_run: bool
    scanned: int = 0
    captured: int = 0
    skipped_existing: int = 0
    review: int = 0
    unfiled: int = 0
    filtered_out: int = 0
    by_domain: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "channel": self.channel,
            "split": self.split,
            "dry_run": self.dry_run,
            "scanned": self.scanned,
            "captured": self.captured,
            "skipped_existing": self.skipped_existing,
            "review": self.review,
            "unfiled": self.unfiled,
            "filtered_out": self.filtered_out,
            "by_domain": dict(sorted(self.by_domain.items(), key=lambda kv: -kv[1])),
        }


def ingest(
    api: Any,
    path: Path | str,
    *,
    channel: str = "folder-import",
    glob: str | None = None,
    split: str = "file",
    dry_run: bool = False,
    limit: int | None = None,
    only: str | None = None,
) -> IngestReport:
    """Ingest a folder/file of existing notes into the harness (non-destructive).

    ``api`` is a ``HarnessAPI``. With ``dry_run`` the source is only *routed*
    (no writes) so you can preview where notes would land. With ``only`` set to a
    domain slug, only notes that route to that foundry are pulled in; everything
    else is left entirely untouched (not even an unfiled card) — this is how you
    pull a mixed folder into one particular domain context.
    """
    report = IngestReport(path=str(path), channel=channel, split=split, dry_run=dry_run)
    report.filtered_out = 0
    by_domain: Counter[str] = Counter()
    for source_ref, text in iter_records(path, glob=glob, split=split):
        if limit is not None and report.scanned >= limit:
            break
        report.scanned += 1
        if dry_run or only is not None:
            # Route read-only to decide (preview, and/or the --only filter).
            result = api.router.route_text(text, channel=channel)
            spans = result.spans or []
            dom = spans[0].domain if spans else "_unfiled"
            if only is not None and dom != only:
                report.filtered_out += 1
                continue
            if dry_run:
                if dom == "_unfiled":
                    report.unfiled += 1
                else:
                    by_domain[dom] += 1
                continue
        receipt = api.capture(text, channel=channel, source_ref=source_ref)
        if getattr(receipt, "idempotent_replay", False):
            report.skipped_existing += 1
            continue
        report.captured += 1
        routed = receipt.routed or []
        dom = routed[0].domain if routed else "_unfiled"
        status = receipt.status
        if status == "review":
            report.review += 1
        if dom == "_unfiled" or status == "unfiled":
            report.unfiled += 1
        else:
            by_domain[dom] += 1
    report.by_domain = dict(by_domain)
    return report


def watch(
    api: Any,
    path: Path | str,
    *,
    interval: float = 30.0,
    rounds: int | None = None,
    sleeper: Callable[[float], None] | None = None,
    channel: str = "folder-import",
    glob: str | None = None,
    split: str = "file",
    only: str | None = None,
) -> Iterator[IngestReport]:
    """Re-scan a folder on an interval, pulling in only what's new each round.

    Because ingest is idempotent on ``(channel, source_ref)``, a re-scan captures
    only files added or changed since last time. Yields one report per round.
    ``rounds`` bounds the loop (``None`` = forever); ``sleeper`` is injectable for
    tests. Never runs dry — watching implies committing.
    """
    _sleep = sleeper or time.sleep
    done = 0
    while rounds is None or done < rounds:
        yield ingest(
            api, path, channel=channel, glob=glob, split=split, only=only, dry_run=False
        )
        done += 1
        if rounds is not None and done >= rounds:
            break
        _sleep(interval)
