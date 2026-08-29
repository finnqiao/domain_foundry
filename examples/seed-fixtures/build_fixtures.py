#!/usr/bin/env python3
"""Rebuild every seed fixture in this folder from one deterministic source.

Run it with ``python examples/seed-fixtures/build_fixtures.py``. The output is
byte-stable: the same seed, the same row order, the same zip timestamps. The
files it writes are committed, so tests never depend on running this first.

The tidepool log is the acceptance fixture for the story: 214 rows with a date,
a place, a species, a count, and a note, across seven places and nine species.
Nothing here is a real person's record. It is made up on purpose.
"""

from __future__ import annotations

import csv
import json
import random
import zipfile
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent

ROW_TARGET = 214

PLACES = [
    "Pillar Point",
    "Fitzgerald Reef",
    "Duxbury Reef",
    "Bodega Head",
    "Pescadero Point",
    "Moss Beach",
    "Bean Hollow",
]

SPECIES = [
    "ochre sea star",
    "giant green anemone",
    "purple urchin",
    "hermit crab",
    "gumboot chiton",
    "opalescent nudibranch",
    "bat star",
    "black turban snail",
    "six-armed sea star",
]

# Notes are written fresh each time, the way a person writes them, so this
# column reads as free text rather than as a list of set values.
NOTE_OPENERS = [
    "",
    "",
    "low tide, calm water",
    "wind picked up on the way back",
    "clustered under the ledge",
    "first one I have seen here",
    "water very clear",
    "tucked into the mussel bed",
    "counted twice to be sure",
    "same pool as last visit",
    "raining, cut the visit short",
    "fog all morning",
    "kelp piled up across the bench",
    "sun out, pools warm",
]

NOTE_TAILS = [
    "",
    "will come back on the next spring tide",
    "photo taken",
    "shell was chipped on one side",
    "surge made it hard to count",
    "next to the anemone patch",
    "smaller than the ones further north",
    "second pool from the path",
    "one looked freshly moulted",
]

# Excel stores a date as days since this day. The offset is the 1900 leap-year
# bug baked into the format; every reader has to know it.
EXCEL_EPOCH = date(1899, 12, 30)

# Fixed timestamp for every zip member so the .xlsx is byte-stable.
ZIP_TIME = (2026, 8, 28, 0, 0, 0)

HEADERS = ["Date", "Place", "Species", "Count", "Notes"]


def _note(rng: random.Random) -> str:
    opener = rng.choice(NOTE_OPENERS)
    tail = rng.choice(NOTE_TAILS)
    if opener and tail:
        return f"{opener}, {tail}"
    return opener or tail


def build_rows() -> list[dict[str, object]]:
    """The 214 sightings, in visit order."""

    rng = random.Random(20260828)
    rows: list[dict[str, object]] = []
    day = date(2024, 3, 9)
    place_cycle = 0
    while len(rows) < ROW_TARGET:
        # Visits cluster around spring low tides, roughly every couple of weeks.
        day = day + timedelta(days=rng.choice([12, 13, 14, 15, 16, 27, 28, 29]))
        place = PLACES[place_cycle % len(PLACES)]
        place_cycle += 1
        wanted = rng.randint(3, 8)
        seen = rng.sample(SPECIES, k=min(wanted, len(SPECIES)))
        for name in seen:
            if len(rows) >= ROW_TARGET:
                break
            rows.append(
                {
                    "Date": day.isoformat(),
                    "Place": place,
                    "Species": name,
                    "Count": rng.randint(1, 40),
                    "Notes": _note(rng),
                }
            )
    missing_places = set(PLACES) - {str(r["Place"]) for r in rows}
    missing_species = set(SPECIES) - {str(r["Species"]) for r in rows}
    if missing_places or missing_species:
        raise SystemExit(f"fixture lost coverage: {missing_places} {missing_species}")
    return rows


# --------------------------------------------------------------------------- csv


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(rows: list[dict[str, object]], path: Path) -> None:
    lines = [
        json.dumps(
            {
                "id": f"obs-{index + 1:04d}",
                "observed_on": row["Date"],
                "place": row["Place"],
                "species": row["Species"],
                "count": row["Count"],
                "notes": row["Notes"],
            },
            sort_keys=True,
        )
        for index, row in enumerate(rows)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# -------------------------------------------------------------------------- xlsx


def _excel_serial(value: str) -> int:
    return (date.fromisoformat(value) - EXCEL_EPOCH).days


def _shared_strings(rows: list[dict[str, object]]) -> tuple[list[str], dict[str, int]]:
    order: list[str] = []
    index: dict[str, int] = {}
    for text in [*HEADERS, *(str(r["Place"]) for r in rows), *(str(r["Species"]) for r in rows)]:
        if text not in index:
            index[text] = len(order)
            order.append(text)
    return order, index


def write_xlsx(rows: list[dict[str, object]], path: Path) -> None:
    """Write a real .xlsx with the stdlib: a zip of XML, nothing more.

    Dates go in as Excel serial numbers with a date format, because that is what
    a spreadsheet app actually writes and the reader has to cope with it.
    """

    shared, shared_index = _shared_strings(rows)

    cells: list[str] = []
    header_cells = "".join(
        f'<c r="{chr(65 + col)}1" t="s"><v>{shared_index[name]}</v></c>'
        for col, name in enumerate(HEADERS)
    )
    cells.append(f'<row r="1">{header_cells}</row>')
    for number, row in enumerate(rows, start=2):
        parts = [
            f'<c r="A{number}" s="1"><v>{_excel_serial(str(row["Date"]))}</v></c>',
            f'<c r="B{number}" t="s"><v>{shared_index[str(row["Place"])]}</v></c>',
            f'<c r="C{number}" t="s"><v>{shared_index[str(row["Species"])]}</v></c>',
            f'<c r="D{number}"><v>{int(row["Count"])}</v></c>',
        ]
        note = str(row["Notes"])
        if note:
            # Inline strings on purpose: a reader that only knows the shared
            # table would silently drop this column.
            parts.append(f'<c r="E{number}" t="inlineStr"><is><t>{escape(note)}</t></is></c>')
        cells.append(f'<row r="{number}">{"".join(parts)}</row>')

    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(cells)}</sheetData></worksheet>"
    )
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(shared)}" uniqueCount="{len(shared)}">'
        + "".join(f"<si><t>{escape(text)}</t></si>" for text in shared)
        + "</sst>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sightings" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="0"/>'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        "</cellXfs></styleSheet>"
    )

    members = {
        "[Content_Types].xml": content_types,
        "_rels/.rels": root_rels,
        "xl/workbook.xml": workbook,
        "xl/_rels/workbook.xml.rels": workbook_rels,
        "xl/worksheets/sheet1.xml": sheet,
        "xl/sharedStrings.xml": shared_xml,
        "xl/styles.xml": styles,
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in members.items():
            info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, text)


# ------------------------------------------------------------------- other kinds


def write_ambiguous(path: Path) -> None:
    """A file nobody can honestly map. The point is that we say so."""

    rows = [
        {"a": "1", "b": "x", "c": "", "d": "q"},
        {"a": "2", "b": "y", "c": "", "d": "q"},
        {"a": "3", "b": "z", "c": "", "d": "r"},
        {"a": "4", "b": "x", "c": "", "d": "r"},
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["a", "b", "c", "d"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_mbox(rows: list[dict[str, object]], path: Path) -> None:
    picks = rows[:6]
    blocks = []
    for index, row in enumerate(picks, start=1):
        note = str(row["Notes"]) or "nothing else to add"
        blocks.append(
            "From tidepools@example.invalid Sat Jan  1 00:00:00 2026\n"
            f"From: June <june@example.invalid>\n"
            f"To: me@example.invalid\n"
            f"Subject: {row['Place']} on {row['Date']}\n"
            f"Date: Sat, 1 Jan 2026 0{index}:00:00 +0000\n"
            f"Message-ID: <tidepool-{index}@example.invalid>\n"
            "\n"
            f"Saw {row['Count']} {row['Species']} at {row['Place']}. {note}.\n"
        )
    path.write_text("\n".join(blocks), encoding="utf-8")


def write_notes(rows: list[dict[str, object]], folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows[:3], start=1):
        note = str(row["Notes"]) or "quiet visit"
        (folder / f"visit-{index}.md").write_text(
            f"# {row['Place']}, {row['Date']}\n\n"
            f"Counted {row['Count']} {row['Species']}. {note}.\n",
            encoding="utf-8",
        )


FIELD_GUIDE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Rocky shore field guide: sea stars and anemones</title>
  <style>body { font-family: system-ui; }</style>
  <script>console.log("this should never reach the extracted text");</script>
</head>
<body>
  <h1>Rocky shore field guide: sea stars and anemones</h1>
  <p>A short reference for the middle and low intertidal zones of the eastern
  Pacific. Written for people who walk the rocks at low tide and want to name
  what they find.</p>
  <h2>Ochre sea star</h2>
  <p>Five thick arms, orange or purple, usually on wave-exposed rock in the
  middle intertidal. Numbers dropped sharply after 2013 and have been recovering
  unevenly since.</p>
  <h2>Giant green anemone</h2>
  <p>Broad green column, often in surge channels and tide pools. The green comes
  from algae living in the tissue, so shaded animals look paler.</p>
  <h2>Purple urchin</h2>
  <p>Sits in a hollow it grinds into the rock. Where sea star numbers fall,
  urchin numbers often rise.</p>
  <h2>How to record a visit</h2>
  <p>Note the date, the place, what you saw, and roughly how many. A count you
  are unsure of is still worth writing down as long as you say so.</p>
  <footer><p>Licence: unknown. Check with the publisher before reusing.</p></footer>
</body>
</html>
"""


def main() -> None:
    rows = build_rows()
    write_csv(rows, HERE / "tidepool-log.csv")
    write_xlsx(rows, HERE / "tidepool-log.xlsx")
    write_jsonl(rows, HERE / "tidepool-observations.jsonl")
    write_ambiguous(HERE / "ambiguous.csv")
    write_mbox(rows, HERE / "tidepool-mail.mbox")
    write_notes(rows, HERE / "tidepool-notes")
    (HERE / "field-guide.html").write_text(FIELD_GUIDE, encoding="utf-8")
    print(f"wrote {len(rows)} rows across the tidepool fixtures in {HERE}")


if __name__ == "__main__":
    main()
