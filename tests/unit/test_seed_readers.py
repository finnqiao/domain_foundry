"""E1: every reader lands the same shape, and a bad source says what it wanted."""

from __future__ import annotations

from pathlib import Path

import pytest

from domain_foundry_core.seed.models import summarize
from domain_foundry_core.seed.readers import SeedReadError, read_seed

FIXTURES = Path(__file__).resolve().parents[2] / "examples" / "seed-fixtures"

# The acceptance numbers from the story, pinned here so a drifting fixture fails.
TIDEPOOL_ROWS = 214
TIDEPOOL_PLACES = 7
TIDEPOOL_SPECIES = 9


def test_xlsx_reads_every_row_with_the_columns_a_person_typed():
    read = read_seed(FIXTURES / "tidepool-log.xlsx")

    table = read.primary_table
    assert table is not None
    assert table.row_count == TIDEPOOL_ROWS
    assert table.columns == ["Date", "Place", "Species", "Count", "Notes"]


def test_xlsx_dates_come_back_as_dates_not_serial_numbers():
    """A spreadsheet stores a date as a number. A reader that forgets that
    hands the rest of the pipeline five-digit integers."""

    read = read_seed(FIXTURES / "tidepool-log.xlsx")
    dates = [row.values["Date"] for row in read.primary_table.rows]

    assert all(isinstance(value, str) and len(value) == 10 for value in dates)
    assert min(dates) == "2024-04-05"


def test_xlsx_reads_both_shared_and_inline_strings():
    read = read_seed(FIXTURES / "tidepool-log.xlsx")
    rows = read.primary_table.rows

    # Places live in the shared string table; notes are written inline.
    assert {str(r.values["Place"]) for r in rows if r.values["Place"]}
    assert any(isinstance(r.values["Notes"], str) and r.values["Notes"] for r in rows)


def test_csv_and_xlsx_agree_row_for_row():
    """The same log, saved two ways, has to read the same. Otherwise the
    preview a person approves depends on which file they picked."""

    from_xlsx = read_seed(FIXTURES / "tidepool-log.xlsx").primary_table
    from_csv = read_seed(FIXTURES / "tidepool-log.csv").primary_table

    assert from_csv.columns == from_xlsx.columns
    assert from_csv.row_count == from_xlsx.row_count
    assert [r.values for r in from_csv.rows] == [r.values for r in from_xlsx.rows]


def test_jsonl_export_reads_as_rows():
    read = read_seed(FIXTURES / "tidepool-observations.jsonl")

    assert read.row_count == TIDEPOOL_ROWS
    assert "species" in read.primary_table.columns


def test_mbox_gives_subject_date_and_body():
    read = read_seed(FIXTURES / "tidepool-mail.mbox")

    table = read.primary_table
    assert table.columns == ["message_id", "date", "sender", "subject", "body"]
    assert table.row_count == 6
    assert all(row.values["subject"] for row in table.rows)
    assert all("Saw" in str(row.values["body"]) for row in table.rows)


def test_notes_folder_goes_through_the_existing_ingest_scan():
    read = read_seed(FIXTURES / "tidepool-notes")

    assert read.row_count == 3
    assert read.primary_table.columns == ["note_ref", "text"]
    assert read.provenance.kind == "personal_upload"


def test_a_page_is_reference_not_records():
    read = read_seed(FIXTURES / "field-guide.html")

    assert read.tables == []
    assert len(read.documents) == 1
    document = read.documents[0]
    assert document.title == "Rocky shore field guide: sea stars and anemones"
    assert "ochre sea star" in document.text.casefold()
    # Scripts and styles are machinery, not reading.
    assert "console.log" not in document.text
    assert "font-family" not in document.text


def test_a_page_is_a_public_link_with_a_licence_nobody_has_checked():
    read = read_seed(FIXTURES / "field-guide.html")

    assert read.provenance.kind == "public_link"
    assert read.provenance.shareable is True
    assert read.provenance.location
    assert read.provenance.retrieved_at
    assert "unknown" in (read.provenance.license or "")


def test_a_file_you_keep_is_personal_and_cannot_be_shared():
    read = read_seed(FIXTURES / "tidepool-log.xlsx")

    assert read.provenance.kind == "personal_upload"
    assert read.provenance.shareable is False
    assert read.provenance.license is None
    assert read.provenance.row_count == TIDEPOOL_ROWS


def test_a_missing_file_says_what_it_can_read():
    with pytest.raises(SeedReadError) as caught:
        read_seed("/nowhere/at/all.xlsx")

    message = str(caught.value)
    assert "could not find" in message
    assert ".xlsx" in message and ".mbox" in message


def test_an_unreadable_kind_names_the_kinds_it_knows(tmp_path: Path):
    odd = tmp_path / "holiday.pdf"
    odd.write_bytes(b"%PDF-1.4 not really")

    with pytest.raises(SeedReadError) as caught:
        read_seed(odd)

    assert "I do not know how to read holiday.pdf" in str(caught.value)


def test_a_spreadsheet_that_is_not_one_says_so(tmp_path: Path):
    broken = tmp_path / "log.xlsx"
    broken.write_text("this is a csv wearing a hat", encoding="utf-8")

    with pytest.raises(SeedReadError) as caught:
        read_seed(broken)

    assert "not a readable spreadsheet" in str(caught.value)


def test_a_web_address_does_not_touch_the_network_unless_asked():
    with pytest.raises(SeedReadError) as caught:
        read_seed("https://example.invalid/guide")

    assert "--fetch" in str(caught.value)


def test_the_summary_holds_shapes_and_counts(tmp_path: Path):
    read = read_seed(FIXTURES / "tidepool-log.xlsx")
    summary = summarize(read)

    assert summary.row_count == TIDEPOOL_ROWS
    assert summary.date_range == ("2024-04-05", "2026-06-10")
    repeated = {item.column: item.distinct for item in summary.repeated}
    assert repeated["Place"] == TIDEPOOL_PLACES
    assert repeated["Species"] == TIDEPOOL_SPECIES


def test_reading_never_writes_to_the_source(tmp_path: Path):
    copy = tmp_path / "log.xlsx"
    copy.write_bytes((FIXTURES / "tidepool-log.xlsx").read_bytes())
    before = (copy.read_bytes(), copy.stat().st_size)

    read_seed(copy)

    assert (copy.read_bytes(), copy.stat().st_size) == before
