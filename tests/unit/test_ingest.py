"""Bolt-on ingestion: non-destructive, idempotent import of existing notes."""

from __future__ import annotations

import os

os.environ.setdefault("DOMAIN_FOUNDRY_LLM", "heuristic")

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.ingest import ingest, iter_records


def _notes(tmp_path):
    d = tmp_path / "notes"
    (d / "climbing").mkdir(parents=True)
    (d / "climbing" / "a.md").write_text("good bouldering session at the gym, felt strong")
    (d / "climbing" / "b.md").write_text("another bouldering day, flashed a V4")
    (d / "shopping.md").write_text("milk, eggs, coffee")
    return d


def test_ingest_is_non_destructive_and_idempotent(tmp_path):
    notes = _notes(tmp_path)
    before = {p: p.read_bytes() for p in notes.rglob("*.md")}

    api = HarnessAPI(tmp_path / "home")
    api.init()
    api.new_domain("track my bouldering climbing sessions")
    # activate via wizard skip
    sid = api.new_domain("track my bouldering sessions")["session_id"]
    api.wizard_reply(sid, "skip")

    first = ingest(api, notes)
    assert first.scanned == 3
    assert first.captured == 3
    assert first.by_domain.get("bouldering", 0) >= 1  # keyworded notes route

    # re-run: idempotent, nothing new
    again = ingest(api, notes)
    assert again.captured == 0
    assert again.skipped_existing == 3

    # source files are untouched
    after = {p: p.read_bytes() for p in notes.rglob("*.md")}
    assert after == before


def test_dry_run_writes_nothing(tmp_path):
    notes = _notes(tmp_path)
    api = HarnessAPI(tmp_path / "home")
    api.init()
    sid = api.new_domain("track my bouldering sessions")["session_id"]
    api.wizard_reply(sid, "skip")

    report = ingest(api, notes, dry_run=True)
    assert report.scanned == 3
    assert report.captured == 0
    # nothing persisted → a real ingest afterwards still has everything to do
    real = ingest(api, notes, dry_run=False)
    assert real.captured == 3


def test_split_lines_for_logs(tmp_path):
    log = tmp_path / "journal.log"
    log.write_text("ran 5k this morning\n\nbouldering felt strong\ncoffee was great\n")
    recs = list(iter_records(log, split="lines"))
    assert len(recs) == 3  # blank line skipped
    assert all("#L" in ref for ref, _ in recs)


def test_only_filter_pulls_one_domain(tmp_path):
    notes = _notes(tmp_path)
    api = HarnessAPI(tmp_path / "home")
    api.init()
    sid = api.new_domain("track my bouldering sessions")["session_id"]
    api.wizard_reply(sid, "skip")
    # heuristic routes the two keyworded notes to bouldering; shopping.md does not.
    report = ingest(api, notes, only="bouldering")
    assert report.captured == 2
    assert report.filtered_out == 1
    assert report.by_domain.get("bouldering") == 2
    # the filtered note was left entirely untouched — not even an unfiled card
    assert api.query(domain="_unfiled") == [] or all(
        r.domain == "bouldering" for r in api.query()
    )


def test_ingest_endpoints(tmp_path):
    from pathlib import Path

    from fastapi.testclient import TestClient

    from domain_foundry_core.api.app import create_app

    notes = _notes(tmp_path)
    app = create_app(home=Path(tmp_path / "home"))
    c = TestClient(app)
    prev = c.post("/api/ingest/preview", json={"path": str(notes)})
    assert prev.status_code == 200
    assert prev.json()["scanned"] == 3
    assert prev.json()["captured"] == 0  # preview writes nothing
    commit = c.post("/api/ingest", json={"path": str(notes)})
    assert commit.status_code == 200
    assert commit.json()["captured"] == 3
    # remote capture stays disabled (in-process write path only)
    assert c.post("/api/capture").status_code == 410


def test_watch_picks_up_new_files(tmp_path):
    from domain_foundry_core.ingest import watch

    notes = _notes(tmp_path)  # 3 files to start
    api = HarnessAPI(tmp_path / "home")
    api.init()
    sid = api.new_domain("track my bouldering sessions")["session_id"]
    api.wizard_reply(sid, "skip")

    added = []

    def sleeper(_seconds):  # runs between scans — simulate a new note appearing
        if not added:
            (notes / "climbing" / "c.md").write_text("evening bouldering, sent a slab")
            added.append(True)

    reports = list(watch(api, notes, rounds=2, sleeper=sleeper))
    assert reports[0].captured == 3  # first scan pulls the existing notes
    assert reports[1].captured == 1  # second scan pulls only the new one
    assert reports[1].skipped_existing == 3
