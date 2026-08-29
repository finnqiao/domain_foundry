"""The one shape every reader produces, and the summary built from it.

These are working types for the seed pipeline. The type that travels outside it
is ``SeedProvenance`` from ``foundry/models.py``, which is where the rule about
personal uploads never being shareable is enforced.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from domain_foundry_core.foundry.models import SeedProvenance

# What a cell can hold once a reader has typed it.
CellValue = str | int | float | bool | None

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?")


@dataclass(frozen=True)
class SeedRow:
    """One row, keyed by column name, plus where in the source it sat."""

    index: int
    values: dict[str, CellValue]

    def get(self, column: str) -> CellValue:
        return self.values.get(column)


@dataclass
class SeedTable:
    """Rows that share a set of columns: a sheet, a csv, a mailbox, a folder."""

    name: str
    columns: list[str]
    rows: list[SeedRow] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def column_values(self, column: str) -> list[CellValue]:
        return [row.values.get(column) for row in self.rows]

    def sample(self, limit: int = 5) -> list[dict[str, CellValue]]:
        """A few rows, for a preview or for a bounded model call.

        Never the whole file. The cap is the point.
        """

        return [dict(row.values) for row in self.rows[: max(0, limit)]]


@dataclass
class SeedDocument:
    """A page read for reference, not for records.

    A field guide is not a table of the user's sightings. It is something to
    cite. Keeping the two apart is what lets the app say which is which.
    """

    title: str
    text: str
    location: str | None = None
    headings: list[str] = field(default_factory=list)


@dataclass
class SeedRead:
    """Everything one source gave us, with its provenance already stamped."""

    provenance: SeedProvenance
    tables: list[SeedTable] = field(default_factory=list)
    documents: list[SeedDocument] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return sum(table.row_count for table in self.tables)

    @property
    def primary_table(self) -> SeedTable | None:
        """The biggest table, which is the one a person means."""

        if not self.tables:
            return None
        return max(self.tables, key=lambda table: table.row_count)


@dataclass
class RepeatedValues:
    """A column whose values come back again and again: places, species, kinds."""

    column: str
    distinct: int
    values: list[str]

    def as_line(self) -> str:
        shown = ", ".join(self.values[:6])
        if len(self.values) > 6:
            shown += ", and more"
        return f"{self.distinct} in {self.column}: {shown}"


@dataclass
class SeedSummary:
    """What the seed says about the practice, in a form other stages can read."""

    label: str
    kind: str
    row_count: int
    columns: list[str]
    repeated: list[RepeatedValues] = field(default_factory=list)
    date_range: tuple[str, str] | None = None
    documents: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "kind": self.kind,
            "row_count": self.row_count,
            "columns": list(self.columns),
            "repeated": [
                {"column": item.column, "distinct": item.distinct, "values": item.values}
                for item in self.repeated
            ],
            "date_range": list(self.date_range) if self.date_range else None,
            "documents": list(self.documents),
        }


def _looks_like_date(value: CellValue) -> bool:
    return isinstance(value, str) and bool(_DATE_RE.match(value.strip()))


def _looks_like_number(value: CellValue) -> bool:
    if not isinstance(value, str):
        return False
    try:
        float(value.strip())
    except ValueError:
        return False
    return True


def summarize(read: SeedRead, *, max_repeated_values: int = 40) -> SeedSummary:
    """Describe a read: how many rows, which columns, what repeats, what span.

    This is the summary that reaches the brief, so it holds shapes and counts,
    never a dump of the rows themselves.
    """

    table = read.primary_table
    columns = list(table.columns) if table else []
    repeated: list[RepeatedValues] = []
    date_range: tuple[str, str] | None = None

    if table and table.row_count:
        for column in table.columns:
            values = [v for v in table.column_values(column) if isinstance(v, str) and v.strip()]
            if not values:
                continue
            if all(_looks_like_date(v) for v in values):
                ordered = sorted(v.strip() for v in values)
                if date_range is None:
                    date_range = (ordered[0], ordered[-1])
                continue
            if all(_looks_like_number(v) for v in values):
                # Numbers repeat by chance, not because they are a list.
                continue
            counts = Counter(v.strip() for v in values)
            distinct = len(counts)
            if distinct < 2 or distinct > max_repeated_values:
                continue
            # A repeated list is a column people reuse, not one they fill in fresh.
            if distinct * 2 > len(values):
                continue
            repeated.append(
                RepeatedValues(
                    column=column,
                    distinct=distinct,
                    values=[name for name, _ in counts.most_common()],
                )
            )

    return SeedSummary(
        label=read.provenance.label,
        kind=read.provenance.kind,
        row_count=read.row_count,
        columns=columns,
        repeated=repeated,
        date_range=date_range,
        documents=[doc.title for doc in read.documents],
    )
