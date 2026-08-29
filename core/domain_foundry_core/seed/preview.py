"""The page you read before anything is written.

It says what was read, what each column will become in plain words, a few real
rows in their new shape, what was left out, and the exact number of records that
will be written if you run it again with ``--apply``.

The renderer is a plug. Today it draws a plain HTML table. When the review
package lands, its renderer takes the same ``SeedPreview`` and returns the same
kind of string, and nothing else in the seed pipeline changes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any

from domain_foundry_core.seed.mapping import ROLE_LABELS, SeedMapping
from domain_foundry_core.seed.models import SeedRead, SeedSummary, summarize

PREVIEW_FILENAME = "seed-preview.html"

# How many real rows the preview shows. Enough to recognise, not a data dump.
SAMPLE_ROWS = 8

SHARING_LINE = (
    "Shapes and public links can travel. Your records never do. "
    "Anything read from a file you keep stays on this machine."
)


@dataclass
class SeedPreview:
    """Everything the preview page needs, with no HTML in it.

    This is the hand-off shape. A different renderer can take this and draw the
    same facts however it likes.
    """

    title: str
    summary: SeedSummary
    mapping: SeedMapping
    sample_rows: list[dict[str, Any]] = field(default_factory=list)
    documents: list[dict[str, str]] = field(default_factory=list)
    will_write: int = 0
    already_present: int = 0
    shareable: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def personal(self) -> bool:
        return self.summary.kind == "personal_upload"


# A renderer takes the preview and returns a whole HTML page.
PreviewRenderer = Callable[[SeedPreview], str]


def build_preview(
    read: SeedRead,
    mapping: SeedMapping | None = None,
    *,
    will_write: int | None = None,
    already_present: int = 0,
    notes: list[str] | None = None,
) -> SeedPreview:
    """Gather the facts. Nothing here reads the source again or writes anything."""

    summary = summarize(read)
    table = read.primary_table
    samples: list[dict[str, Any]] = []
    if table is not None and mapping is not None:
        for row in table.rows[:SAMPLE_ROWS]:
            shaped: dict[str, Any] = {}
            for column in mapping.mapped_columns:
                shaped[column.field_name] = row.values.get(column.column)
            samples.append(shaped)
    elif table is not None:
        samples = table.sample(SAMPLE_ROWS)

    documents = [
        {
            "title": doc.title,
            "location": doc.location or "",
            "excerpt": doc.text[:600],
        }
        for doc in read.documents
    ]

    planned = will_write if will_write is not None else (table.row_count if table else 0)
    return SeedPreview(
        title=f"Seed preview: {read.provenance.label}",
        summary=summary,
        mapping=mapping
        or SeedMapping(
            seed_id=read.provenance.id,
            label=read.provenance.label,
            source=read.provenance.location,
            domain="",
            object_type="",
            table="",
            row_count=0,
        ),
        sample_rows=samples,
        documents=documents,
        will_write=planned,
        already_present=already_present,
        shareable=read.provenance.shareable,
        notes=[*read.notes, *(notes or [])],
    )


def render_preview(preview: SeedPreview, *, renderer: PreviewRenderer | None = None) -> str:
    """Draw the preview page. Swap ``renderer`` to change how it looks."""

    return (renderer or plain_table_renderer)(preview)


def write_preview(
    preview: SeedPreview,
    destination: Path,
    *,
    renderer: PreviewRenderer | None = None,
) -> Path:
    """Write the page next to wherever the caller wants it."""

    path = Path(destination)
    if path.is_dir():
        path = path / PREVIEW_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_preview(preview, renderer=renderer), encoding="utf-8")
    return path


# --------------------------------------------------------------- plain renderer


def plain_table_renderer(preview: SeedPreview) -> str:
    """A plain HTML page: headings, tables, no scripts, no network."""

    mapping = preview.mapping
    summary = preview.summary
    parts: list[str] = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape(preview.title)}</title>",
        "<style>"
        "body{font-family:system-ui,sans-serif;margin:2rem;max-width:60rem;line-height:1.5}"
        "table{border-collapse:collapse;margin:1rem 0;width:100%}"
        "th,td{border:1px solid #ccc;padding:.4rem .6rem;text-align:left;vertical-align:top}"
        "th{background:#f4f4f4}"
        "code{background:#f4f4f4;padding:0 .2rem}"
        "</style></head><body>",
        f"<h1>{escape(preview.title)}</h1>",
    ]

    kind_line = (
        "This is something you keep, so it stays on this machine."
        if preview.personal
        else "This is a page you pointed at, so it can be shared later if you say yes."
    )
    parts.append(f"<p>{escape(kind_line)}</p>")
    parts.append(f"<p>{escape(SHARING_LINE)}</p>")

    parts.append("<h2>What I read</h2><ul>")
    parts.append(f"<li>{summary.row_count} rows</li>")
    if summary.columns:
        cols = ", ".join(escape(c) for c in summary.columns)
        parts.append(f"<li>columns: {cols}</li>")
    if summary.date_range:
        first, last = summary.date_range
        parts.append(f"<li>dates from {escape(first)} to {escape(last)}</li>")
    for item in summary.repeated:
        parts.append(f"<li>{escape(item.as_line())}</li>")
    for name in summary.documents:
        parts.append(f"<li>reference page: {escape(name)}</li>")
    parts.append("</ul>")

    if mapping.columns:
        parts.append("<h2>What I will do with each column</h2>")
        parts.append(f"<p>{escape(mapping.sentence())}</p>")
        parts.append(
            "<table><thead><tr><th>Column</th><th>Becomes</th><th>Stored as</th>"
            "<th>Why</th></tr></thead><tbody>"
        )
        for column in mapping.columns:
            becomes = ROLE_LABELS.get(column.role, column.role)
            stored = column.field_name if column.mapped else "left out"
            parts.append(
                "<tr>"
                f"<td>{escape(column.column)}</td>"
                f"<td>{escape(becomes)}</td>"
                f"<td><code>{escape(stored)}</code></td>"
                f"<td>{escape(column.reason)}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")

    if mapping.lists:
        parts.append("<h2>Lists I found</h2><ul>")
        for item in mapping.lists:
            shown = ", ".join(escape(v) for v in item.values[:12])
            if len(item.values) > 12:
                shown += ", and more"
            parts.append(f"<li>{item.distinct} in {escape(item.column)}: {shown}</li>")
        parts.append("</ul>")

    if preview.sample_rows:
        parts.append("<h2>A few of your rows, in their new shape</h2>")
        headers = list(preview.sample_rows[0])
        head = "".join(f"<th>{escape(h)}</th>" for h in headers)
        parts.append(f"<table><thead><tr>{head}</tr></thead><tbody>")
        for row in preview.sample_rows:
            cells = "".join(
                f"<td>{escape('' if row.get(h) is None else str(row.get(h)))}</td>" for h in headers
            )
            parts.append(f"<tr>{cells}</tr>")
        parts.append("</tbody></table>")

    unmapped = mapping.unmapped_columns
    parts.append("<h2>What I left out</h2>")
    if unmapped:
        parts.append("<ul>")
        for name in unmapped:
            parts.append(f"<li>{escape(name)}</li>")
        parts.append("</ul>")
        parts.append(
            "<p>Edit the mapping file and run the seed again with "
            "<code>--mapping</code> if you want these in.</p>"
        )
    else:
        parts.append("<p>Nothing. Every column has a home.</p>")

    if preview.documents:
        parts.append("<h2>Reference pages</h2>")
        for doc in preview.documents:
            parts.append(f"<h3>{escape(doc['title'])}</h3>")
            if doc["location"]:
                parts.append(f"<p>{escape(doc['location'])}</p>")
            parts.append(f"<p>{escape(doc['excerpt'])}</p>")
        parts.append(
            "<p>Pages are kept as something to cite. No rows were taken from them, "
            "and the licence is unknown until someone checks it.</p>"
        )

    parts.append("<h2>What happens if you apply this</h2><ul>")
    parts.append(f"<li>{preview.will_write} records will be written</li>")
    if preview.already_present:
        parts.append(f"<li>{preview.already_present} are already here and will be left alone</li>")
    parts.append("<li>the file you pointed at is not changed, moved, or renamed</li>")
    parts.append("</ul>")

    if preview.notes:
        parts.append("<h2>Notes</h2><ul>")
        for note in preview.notes:
            parts.append(f"<li>{escape(note)}</li>")
        parts.append("</ul>")

    parts.append("</body></html>")
    return "\n".join(parts)
