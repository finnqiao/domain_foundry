"""Readers: every kind of thing a person already keeps, into one shape.

Only the standard library is used here. A spreadsheet is a zip of XML, a mail
export is a mailbox, a page is text inside tags. Keeping it to the standard
library keeps the tool local and keeps installing it painless.

Sources are opened read only. Nothing here writes, moves, or renames anything.
"""

from __future__ import annotations

import csv
import json
import mailbox
import re
import zipfile
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

from domain_foundry_core.clock import now_iso
from domain_foundry_core.foundry.models import SeedProvenance
from domain_foundry_core.ingest import iter_records as iter_note_records
from domain_foundry_core.seed.models import (
    CellValue,
    SeedDocument,
    SeedRead,
    SeedRow,
    SeedTable,
)

# What we know how to open, said the way the error message says it.
TABLE_SUFFIXES = {".xlsx", ".csv", ".tsv", ".json", ".jsonl", ".ndjson"}
MAIL_SUFFIXES = {".mbox"}
PAGE_SUFFIXES = {".html", ".htm"}

SUPPORTED_HELP = (
    "a spreadsheet (.xlsx), a csv or tsv, a JSON or JSONL export, "
    "a mail export (.mbox), a folder of notes, or a page saved as .html"
)

# The seed pipeline caps how much of a page it keeps as reference text.
MAX_DOCUMENT_CHARS = 20_000
# A cell longer than this is almost certainly a paste, not a value.
MAX_CELL_CHARS = 2_000

_SPREADSHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_CELL_REF_RE = re.compile(r"^([A-Z]+)(\d+)$")
_EXCEL_EPOCH = date(1899, 12, 30)
# Number formats Excel treats as dates. 14 to 22 and 45 to 47 are the built-ins.
_DATE_NUMFMT_IDS = frozenset({14, 15, 16, 17, 18, 19, 20, 21, 22, 45, 46, 47})


class SeedReadError(RuntimeError):
    """Raised when a source cannot be read, with a message that names the fix."""


# --------------------------------------------------------------------- entry point


def read_seed(
    source: str | Path,
    *,
    label: str | None = None,
    seed_id: str | None = None,
    license_note: str | None = None,
    fetch: bool = False,
) -> SeedRead:
    """Read one source and stamp it with where it came from.

    A web address is a public link: it records the address, the date it was
    read, and that the licence is unknown until someone checks. Everything else
    is a personal upload: it stays on this machine and is never offered for
    sharing.
    """

    text_source = str(source)
    if _is_url(text_source):
        return _read_url(
            text_source, label=label, seed_id=seed_id, license_note=license_note, fetch=fetch
        )

    path = Path(text_source).expanduser()
    if not path.exists():
        raise SeedReadError(
            f"I could not find {path}. Point me at {SUPPORTED_HELP}, or a web address."
        )

    name = label or path.name
    ident = seed_id or _slug(path.stem)

    if path.is_dir():
        return _read_notes_folder(path, ident=ident, label=name)

    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        tables = _read_xlsx(path)
    elif suffix in {".csv", ".tsv"}:
        tables = [_read_delimited(path)]
    elif suffix in {".json", ".jsonl", ".ndjson"}:
        tables = [_read_json(path)]
    elif suffix in MAIL_SUFFIXES:
        tables = [_read_mbox(path)]
    elif suffix in PAGE_SUFFIXES:
        # A page is named by its own title unless the caller said otherwise.
        return _read_html_file(path, ident=ident, label=label, license_note=license_note)
    else:
        raise SeedReadError(
            f"I do not know how to read {path.name}. I can read {SUPPORTED_HELP}, or a web address."
        )

    provenance = SeedProvenance(
        id=ident,
        kind="personal_upload",
        label=name,
        location=str(path),
        retrieved_at=now_iso(),
        row_count=sum(table.row_count for table in tables),
        columns=list(tables[0].columns)[:200] if tables else [],
    )
    return SeedRead(provenance=provenance, tables=tables)


# --------------------------------------------------------------------------- xlsx


def _read_xlsx(path: Path) -> list[SeedTable]:
    """Read a spreadsheet the way the format actually works: a zip of XML."""

    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise SeedReadError(
            f"{path.name} is not a readable spreadsheet. Save it again as .xlsx, "
            "or export it as a csv."
        ) from exc

    with archive:
        names = set(archive.namelist())
        shared = _xlsx_shared_strings(archive) if "xl/sharedStrings.xml" in names else []
        date_styles = _xlsx_date_styles(archive) if "xl/styles.xml" in names else set()
        sheets = _xlsx_sheet_names(archive) if "xl/workbook.xml" in names else []

        sheet_parts = sorted(n for n in names if n.startswith("xl/worksheets/sheet"))
        if not sheet_parts:
            raise SeedReadError(f"{path.name} has no sheets in it.")

        tables: list[SeedTable] = []
        for position, part in enumerate(sheet_parts):
            title = sheets[position] if position < len(sheets) else f"sheet{position + 1}"
            grid = _xlsx_sheet_grid(archive.read(part), shared=shared, date_styles=date_styles)
            table = _grid_to_table(title, grid)
            if table is not None:
                tables.append(table)

    if not tables:
        raise SeedReadError(
            f"{path.name} opened but every sheet was empty. I need a header row "
            "and at least one row under it."
        )
    return tables


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    out: list[str] = []
    for item in root.findall(f"{_SPREADSHEET_NS}si"):
        out.append(_xlsx_text(item))
    return out


def _xlsx_text(node: ElementTree.Element) -> str:
    """Join every text run under an <si> or an <is>, rich text included."""

    parts = [t.text or "" for t in node.iter(f"{_SPREADSHEET_NS}t")]
    return "".join(parts)


def _xlsx_date_styles(archive: zipfile.ZipFile) -> set[int]:
    """Style indexes whose number format means "this is a date"."""

    root = ElementTree.fromstring(archive.read("xl/styles.xml"))
    custom_date_ids: set[int] = set()
    for fmt in root.iter(f"{_SPREADSHEET_NS}numFmt"):
        code = (fmt.get("formatCode") or "").lower()
        raw_id = fmt.get("numFmtId")
        if raw_id is None:
            continue
        if any(token in code for token in ("yy", "dd", "mmm")) and "[" not in code:
            custom_date_ids.add(int(raw_id))
    known = _DATE_NUMFMT_IDS | custom_date_ids

    styles: set[int] = set()
    cell_xfs = root.find(f"{_SPREADSHEET_NS}cellXfs")
    if cell_xfs is None:
        return styles
    for index, xf in enumerate(cell_xfs.findall(f"{_SPREADSHEET_NS}xf")):
        raw = xf.get("numFmtId")
        if raw is not None and int(raw) in known:
            styles.add(index)
    return styles


def _xlsx_sheet_names(archive: zipfile.ZipFile) -> list[str]:
    root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    return [
        sheet.get("name") or f"sheet{index + 1}"
        for index, sheet in enumerate(root.iter(f"{_SPREADSHEET_NS}sheet"))
    ]


def _xlsx_sheet_grid(
    payload: bytes, *, shared: list[str], date_styles: set[int]
) -> list[list[CellValue]]:
    root = ElementTree.fromstring(payload)
    grid: list[list[CellValue]] = []
    for row in root.iter(f"{_SPREADSHEET_NS}row"):
        cells: list[CellValue] = []
        for cell in row.findall(f"{_SPREADSHEET_NS}c"):
            column = _column_index(cell.get("r"))
            if column is None:
                column = len(cells)
            while len(cells) < column:
                cells.append(None)
            cells.append(_xlsx_cell_value(cell, shared=shared, date_styles=date_styles))
        grid.append(cells)
    return grid


def _xlsx_cell_value(
    cell: ElementTree.Element, *, shared: list[str], date_styles: set[int]
) -> CellValue:
    kind = cell.get("t")
    if kind == "s":
        node = cell.find(f"{_SPREADSHEET_NS}v")
        if node is None or node.text is None:
            return None
        try:
            return shared[int(node.text)]
        except (ValueError, IndexError):
            return None
    if kind == "inlineStr":
        node = cell.find(f"{_SPREADSHEET_NS}is")
        return _xlsx_text(node) if node is not None else None
    if kind == "str":
        node = cell.find(f"{_SPREADSHEET_NS}v")
        return node.text if node is not None else None
    if kind == "b":
        node = cell.find(f"{_SPREADSHEET_NS}v")
        return bool(node is not None and (node.text or "0").strip() == "1")

    node = cell.find(f"{_SPREADSHEET_NS}v")
    if node is None or node.text is None or not node.text.strip():
        return None
    raw = node.text.strip()
    style = cell.get("s")
    if style is not None and int(style) in date_styles:
        return _excel_serial_to_iso(raw)
    try:
        number = float(raw)
    except ValueError:
        return raw
    return int(number) if number.is_integer() else number


def _excel_serial_to_iso(raw: str) -> str:
    """Turn a spreadsheet date serial into a plain date.

    Spreadsheets count days from 1899-12-30 because of a leap-year bug the
    format kept for compatibility. Anything that is not a number comes back
    untouched rather than guessed at.
    """

    try:
        serial = float(raw)
    except ValueError:
        return raw
    whole = int(serial)
    fraction = serial - whole
    stamp = datetime.combine(_EXCEL_EPOCH + timedelta(days=whole), datetime.min.time())
    stamp = stamp + timedelta(seconds=round(fraction * 86_400))
    if stamp.hour or stamp.minute or stamp.second:
        return stamp.isoformat(timespec="seconds")
    return stamp.date().isoformat()


def _column_index(ref: str | None) -> int | None:
    if not ref:
        return None
    match = _CELL_REF_RE.match(ref)
    if not match:
        return None
    letters = match.group(1)
    value = 0
    for char in letters:
        value = value * 26 + (ord(char) - 64)
    return value - 1


# ---------------------------------------------------------------------- csv / tsv


def _read_delimited(path: Path) -> SeedTable:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        grid: list[list[CellValue]] = [
            [_number_or_text(_clean_cell(cell)) for cell in row] for row in reader
        ]
    table = _grid_to_table(path.stem, grid)
    if table is None:
        raise SeedReadError(
            f"{path.name} has no rows I can read. I need a header row and at "
            "least one row under it."
        )
    return table


# --------------------------------------------------------------------- json lines


def _read_json(path: Path) -> SeedTable:
    text = path.read_text(encoding="utf-8")
    records: list[dict[str, Any]]
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        records = []
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SeedReadError(
                    f"{path.name} line {number} is not valid JSON: {exc.msg}."
                ) from exc
            if not isinstance(obj, dict):
                raise SeedReadError(
                    f"{path.name} line {number} is not an object. Each line should "
                    "be one record, like a row."
                )
            records.append(obj)
    else:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SeedReadError(f"{path.name} is not valid JSON: {exc.msg}.") from exc
        if isinstance(payload, dict):
            lists = [v for v in payload.values() if isinstance(v, list)]
            payload = lists[0] if len(lists) == 1 else payload.get("records", [])
        if not isinstance(payload, list):
            raise SeedReadError(
                f"{path.name} does not hold a list of records. I need an array of "
                "objects, or one object holding a single array."
            )
        records = [r for r in payload if isinstance(r, dict)]

    if not records:
        raise SeedReadError(f"{path.name} held no records.")

    columns: list[str] = []
    for record in records:
        for key in record:
            if key not in columns:
                columns.append(str(key))
    rows = [
        SeedRow(
            index=index,
            values={key: _clean_cell(record.get(key)) for key in columns},
        )
        for index, record in enumerate(records)
    ]
    return SeedTable(name=path.stem, columns=columns, rows=rows)


# --------------------------------------------------------------------------- mail


def _read_mbox(path: Path) -> SeedTable:
    box = mailbox.mbox(str(path), create=False)
    columns = ["message_id", "date", "sender", "subject", "body"]
    rows: list[SeedRow] = []
    try:
        for index, message in enumerate(box):
            rows.append(
                SeedRow(
                    index=index,
                    values={
                        "message_id": _header(message, "Message-ID") or f"message-{index + 1}",
                        "date": _header(message, "Date"),
                        "sender": _header(message, "From"),
                        "subject": _header(message, "Subject"),
                        "body": _mail_body(message),
                    },
                )
            )
    finally:
        box.close()
    if not rows:
        raise SeedReadError(f"{path.name} held no messages.")
    return SeedTable(name=path.stem, columns=columns, rows=rows)


def _header(message: Any, name: str) -> str | None:
    raw = message.get(name)
    if raw is None:
        return None
    return str(raw).strip() or None


def _mail_body(message: Any) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                return _decode_part(part)
        return ""
    return _decode_part(message)


def _decode_part(part: Any) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        return str(raw).strip() if isinstance(raw, str) else ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace").strip()
    except LookupError:
        return payload.decode("utf-8", errors="replace").strip()


# ------------------------------------------------------------------- notes folder


def _read_notes_folder(path: Path, *, ident: str, label: str) -> SeedRead:
    """A folder of notes. The scanning is the ingest command's, unchanged."""

    rows = [
        SeedRow(index=index, values={"note_ref": source_ref, "text": text.strip()})
        for index, (source_ref, text) in enumerate(iter_note_records(path))
    ]
    if not rows:
        raise SeedReadError(f"I found no notes under {path}. I read plain text and markdown files.")
    table = SeedTable(name=path.name or "notes", columns=["note_ref", "text"], rows=rows)
    provenance = SeedProvenance(
        id=ident,
        kind="personal_upload",
        label=label,
        location=str(path),
        retrieved_at=now_iso(),
        row_count=len(rows),
        columns=["note_ref", "text"],
    )
    return SeedRead(
        provenance=provenance,
        tables=[table],
        notes=["Each file became one note. Nothing in the folder was changed."],
    )


# --------------------------------------------------------------------- pages / web


class _PageText(HTMLParser):
    """Pull the readable text out of a page and drop the machinery."""

    SKIP = {"script", "style", "noscript", "template", "svg", "head"}
    BLOCK = {"p", "div", "li", "section", "article", "br", "tr", "td", "blockquote"}
    HEADINGS = {"h1", "h2", "h3", "h4"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.headings: list[str] = []
        self.title: str = ""
        self._skip_depth = 0
        self._capture: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self.SKIP:
            self._skip_depth += 1
            return
        if tag == "title" or tag in self.HEADINGS:
            self._capture = tag
            self._buffer = []
        if tag in self.BLOCK or tag in self.HEADINGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._capture == tag:
            text = " ".join("".join(self._buffer).split())
            if tag == "title":
                self.title = text
            elif text:
                self.headings.append(text)
            self._capture = None
            self._buffer = []
        if tag in self.BLOCK or tag in self.HEADINGS:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._capture is not None:
            self._buffer.append(data)
        self.chunks.append(data)

    def document_text(self) -> str:
        raw = "".join(self.chunks)
        lines = [" ".join(line.split()) for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


def _extract_page(html: str, *, location: str | None) -> SeedDocument:
    parser = _PageText()
    parser.feed(html)
    parser.close()
    text = parser.document_text()[:MAX_DOCUMENT_CHARS]
    title = parser.title or (parser.headings[0] if parser.headings else "untitled page")
    return SeedDocument(title=title, text=text, location=location, headings=parser.headings)


def _read_html_file(
    path: Path, *, ident: str, label: str | None, license_note: str | None
) -> SeedRead:
    """A page saved to disk. It is reference material, not the user's records."""

    document = _extract_page(path.read_text(encoding="utf-8", errors="replace"), location=str(path))
    provenance = SeedProvenance(
        id=ident,
        kind="public_link",
        label=label or document.title,
        location=str(path),
        retrieved_at=now_iso(),
        license=license_note or "unknown until someone checks",
    )
    return SeedRead(
        provenance=provenance,
        documents=[document],
        notes=["Read as a reference page. No rows were taken from it."],
    )


def _read_url(
    url: str,
    *,
    label: str | None,
    seed_id: str | None,
    license_note: str | None,
    fetch: bool,
) -> SeedRead:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SeedReadError(f"I can only read http and https addresses, not {parsed.scheme!r}.")

    ident = seed_id or _slug(parsed.netloc + parsed.path)
    if not fetch:
        raise SeedReadError(
            "Reading a web address goes out to the network. Add --fetch if you "
            "want me to open it, or save the page as .html and point me at the file."
        )

    from urllib.request import Request, urlopen

    request = Request(url, headers={"User-Agent": "domain-foundry-seed"})
    try:
        with urlopen(request, timeout=20) as response:  # noqa: S310 - scheme checked above
            charset = response.headers.get_content_charset() or "utf-8"
            html = response.read(4_000_000).decode(charset, errors="replace")
    except Exception as exc:  # noqa: BLE001 - any network failure reads the same to a user
        raise SeedReadError(
            f"I could not open {url}. Check the address, or save the page as .html "
            "and point me at the file."
        ) from exc

    document = _extract_page(html, location=url)
    provenance = SeedProvenance(
        id=ident,
        kind="public_link",
        label=label or document.title,
        location=url,
        retrieved_at=now_iso(),
        license=license_note or "unknown until someone checks",
    )
    return SeedRead(
        provenance=provenance,
        documents=[document],
        notes=["Read as a reference page. No rows were taken from it."],
    )


# ------------------------------------------------------------------------ helpers


def _is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (cleaned or "seed")[:120]


def _clean_cell(value: Any) -> CellValue:
    if value is None or isinstance(value, bool | int | float):
        return value
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True, default=str)
    text = value.strip()
    if not text:
        return None
    return text[:MAX_CELL_CHARS]


def _number_or_text(value: CellValue) -> CellValue:
    """A plain whole number in a text file is a number. Anything padded is text.

    ``007`` stays text because it is almost always an identifier somebody wrote
    that way on purpose.
    """

    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text in {"-", "+"}:
        return value
    body = text[1:] if text[0] in "+-" else text
    if body.isdigit() and (body == "0" or not body.startswith("0")):
        return int(text)
    if body.count(".") == 1:
        whole, _, decimals = body.partition(".")
        if (
            whole.isdigit()
            and decimals.isdigit()
            and (whole in {"", "0"} or not whole.startswith("0"))
        ):
            return float(text)
    return value


def _grid_to_table(name: str, grid: list[list[CellValue]]) -> SeedTable | None:
    """Take the first non-empty line as headers and the rest as rows."""

    rows_with_content = [row for row in grid if any(cell not in (None, "") for cell in row)]
    if len(rows_with_content) < 2:
        return None
    header_row = rows_with_content[0]
    columns: list[str] = []
    for position, cell in enumerate(header_row):
        name_text = str(cell).strip() if cell not in (None, "") else ""
        if not name_text:
            name_text = f"column_{position + 1}"
        base = name_text
        counter = 2
        while name_text in columns:
            name_text = f"{base}_{counter}"
            counter += 1
        columns.append(name_text)

    rows: list[SeedRow] = []
    for index, raw in enumerate(rows_with_content[1:]):
        values: dict[str, CellValue] = {}
        for position, column in enumerate(columns):
            values[column] = raw[position] if position < len(raw) else None
        rows.append(SeedRow(index=index, values=values))
    return SeedTable(name=name, columns=columns, rows=rows)
